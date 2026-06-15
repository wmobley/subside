"""Tapis Workflows pipeline lifecycle for the SUBSIDE API.

The public API still calls these "runs", but the durable unit is now a Tapis
Workflows pipeline run, not a direct Tapis Jobs submission. The heavy analysis
still happens inside the workflow's ``run`` task, which submits a Tapis job and
archives artifacts; this module treats that job as an implementation detail.
"""

from __future__ import annotations

import io
import json
import re
import time
import uuid
from typing import Any

import yaml

from . import discovery
from .. import config
from ..config import PIPELINE_DIR, PIPELINES, STAGING_PREFIX, STAGING_SYSTEM, TAPIS_BASE_URL
from ..models import Artifact, RunRequest

# --- OOM-aware queue selection for werc ------------------------------------
# werc's velocity step (np.linalg.lstsq over the whole displacement cube) holds
# ~_BYTES_PER_ELEM * n_acquisitions * AOI_pixels bytes resident. ls6 vm-small is
# only 32 GB; when the estimate won't fit we submit the first attempt straight to
# a 256 GB node instead of wasting a guaranteed-OOM vm-small attempt. The
# pipeline's OOM escalation (werc-opera.yaml) is the backstop if this under-shoots
# or discovery is unavailable.
_BYTES_PER_ELEM = 20            # resident stack (~12) + lstsq float64 copy (~8)
_VM_SMALL_BUDGET_GB = 26        # 32 GB node minus OS/python/libs headroom
_SMALL_QUEUE = ("vm-small", 16, 32000)
_BIG_QUEUE = ("normal", 128, 245000)


def _aoi_pixels(bbox: dict, resolution_m: float = 30.0) -> float:
    """Approximate OPERA-pixel count for a lon/lat bbox at ~30 m."""
    import math
    lat_mid = 0.5 * (float(bbox["lat_min"]) + float(bbox["lat_max"]))
    width_m = abs(float(bbox["lon_max"]) - float(bbox["lon_min"])) * 111_320 * math.cos(math.radians(lat_mid))
    height_m = abs(float(bbox["lat_max"]) - float(bbox["lat_min"])) * 110_540
    return (width_m / resolution_m) * (height_m / resolution_m)


def _pick_run_queue(req: RunRequest) -> tuple[str, int, int]:
    """Choose the first-attempt (queue, cores, memoryMB) for the run job.

    Only werc is memory-heavy enough to matter. If the estimated velocity peak
    (~_BYTES_PER_ELEM * nt * npix) exceeds vm-small's usable RAM, go straight to
    the big node. Any discovery failure falls back to vm-small (the pipeline's
    OOM escalation still protects the run).
    """
    if req.pipeline != "werc":
        return _SMALL_QUEUE
    try:
        frames = discovery.find_frames(req.aoi_geojson, req.min_overlap_percent)
        frame_ids = frames.get("frame_ids", [])
        bbox = frames.get("bbox")
        if not frame_ids or not bbox:
            return _SMALL_QUEUE
        nt = discovery.search_products(frame_ids, req.start_date, req.end_date).get("product_count", 0)
        peak_gb = _BYTES_PER_ELEM * nt * _aoi_pixels(bbox) / 1e9
        if peak_gb > _VM_SMALL_BUDGET_GB:
            return _BIG_QUEUE
    except Exception:
        pass  # discovery flaky -> default small; OOM escalation is the backstop
    return _SMALL_QUEUE

# Flat 12 h job walltime (see analysis.h2i_lab.estimate): a SLURM job frees its
# node the moment it finishes, so the cap is a safety ceiling, not a cost, and
# 12 h clears even the slow/throttled worst case. A caller may still override
# max_minutes; it's clamped to a sane 24 h ceiling.
_WALLTIME_DEFAULT_MIN = 720
_WALLTIME_CAP_MIN = 1440


def _resolve_walltime(req: RunRequest) -> int:
    """Walltime (minutes): the caller's max_minutes (clamped) or the flat 12 h default."""

    minutes = int(req.max_minutes) if req.max_minutes else _WALLTIME_DEFAULT_MIN
    return max(1, min(_WALLTIME_CAP_MIN, minutes))

_STATUS_MAP = {
    "SUBMITTED": "queued",
    "STAGING": "queued",
    "INITIALIZING": "queued",
    "PENDING": "queued",
    "QUEUED": "queued",
    "ACTIVE": "running",
    "RUNNING": "running",
    "COMPLETED": "completed",
    "SUCCESS": "completed",
    "SUCCEEDED": "completed",
    "FINISHED": "completed",
    "FAILED": "failed",
    "ERROR": "failed",
    "TERMINATED": "failed",
    "STOPPED": "failed",
    "SUSPENDED": "failed",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}
SUCCESS_STATES = {"completed", "success", "succeeded", "finished"}
FAILURE_STATES = {"failed", "error", "terminated", "stopped", "suspended", "cancelled", "canceled"}
_JOB_UUID_RE = re.compile(r"submitted Tapis job\s+([A-Za-z0-9._-]+)")
_TAPIS_ARCHIVE_RE = re.compile(r"tapis://[^\s;,'\")]+")


def normalize_status(tapis_status: str) -> str:
    return _STATUS_MAP.get(str(tapis_status or "").upper(), "unknown")


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _status_of(obj: Any) -> str:
    return str(_field(obj, "status") or "unknown").lower()


def _client_token(client) -> str:
    token = getattr(client, "subside_access_token", None)
    if token:
        return str(token)
    access = getattr(client, "access_token", None)
    token = getattr(access, "access_token", None) if access is not None else None
    return str(token or access or "")


def _ckan_auth_token(token: str) -> str:
    token = str(token or "").strip()
    if not token or token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}" if token.count(".") == 2 else token


def _parse_tapis_uri(uri: str) -> tuple[str, str]:
    rest = uri[len("tapis://"):]
    system, _, path = rest.partition("/")
    return system, path.strip("/")


def _load_pipeline(pipeline_key: str) -> dict:
    path = PIPELINE_DIR / f"{PIPELINES[pipeline_key]}.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


def _pipeline_id(pipeline_key: str) -> str:
    return str(_load_pipeline(pipeline_key).get("id") or PIPELINES[pipeline_key])


def _pipeline_ids() -> dict[str, str]:
    return {key: _pipeline_id(key) for key in PIPELINES}


def _build_run_config(req: RunRequest) -> dict:
    """Legacy run-config kept staged for diagnostics and manual replay."""
    cfg: dict[str, Any] = {
        "start_date": req.start_date,
        "end_date": req.end_date,
        "aoi_geojson_path": "config/aoi.geojson",
        "num_workers": req.num_workers,
        "min_overlap_percent": req.min_overlap_percent,
        "output_dir": "output",
        "results_dir": "OPERA_L3_DISP-S1",
        "require_products": True,
        "preview_only": False,
    }
    if req.pipeline == "werc":
        cfg.update({
            "reference_mode": req.reference_mode,
            "reference_lat": req.reference_lat,
            "reference_lon": req.reference_lon,
            "anchor_radius_m": req.anchor_radius_m,
            "n_reference_pixels": req.n_reference_pixels,
            "anchor_dir": "output/anchors",
            "skip_download": False,
        })
    return cfg


def _stage(client, username: str, run_id: str, req: RunRequest) -> dict:
    """Upload AOI, optional .netrc, and a replay run-config; return tapis:// URIs."""
    base = STAGING_PREFIX.format(username=username) + f"/{run_id}"
    client.files.mkdir(systemId=STAGING_SYSTEM, path=base)

    run_config = _build_run_config(req)
    client.files.insert(
        systemId=STAGING_SYSTEM,
        path=f"{base}/run-config.json",
        file=io.BytesIO(json.dumps(run_config).encode()),
    )
    client.files.insert(
        systemId=STAGING_SYSTEM,
        path=f"{base}/aoi.geojson",
        file=io.BytesIO(json.dumps(req.aoi_geojson).encode()),
    )

    netrc_uri = req.earthdata_netrc_uri or ""
    ed_user = req.earthdata_username or config.EARTHDATA_USERNAME
    ed_pass = req.earthdata_password or config.EARTHDATA_PASSWORD
    if not netrc_uri and ed_user and ed_pass:
        netrc = f"machine urs.earthdata.nasa.gov login {ed_user} password {ed_pass}\n"
        client.files.insert(
            systemId=STAGING_SYSTEM,
            path=f"{base}/.netrc",
            file=io.BytesIO(netrc.encode()),
        )
        netrc_uri = f"tapis://{STAGING_SYSTEM}/{base}/.netrc"

    return {
        "run_config_uri": f"tapis://{STAGING_SYSTEM}/{base}/run-config.json",
        "aoi_geojson_uri": f"tapis://{STAGING_SYSTEM}/{base}/aoi.geojson",
        "earthdata_netrc_uri": netrc_uri,
    }


def _workflow_args(req: RunRequest, staged: dict, allocation: str, token: str,
                   max_minutes: int | None = None,
                   run_queue: tuple[str, int, int] | None = None) -> dict[str, dict]:
    args: dict[str, dict] = {
        "start_date": {"value": req.start_date},
        "end_date": {"value": req.end_date},
        "aoi_geojson_uri": {"value": staged["aoi_geojson_uri"]},
        "earthdata_netrc_uri": {"value": staged["earthdata_netrc_uri"] or ""},
        "num_workers": {"value": req.num_workers},
        "min_overlap_percent": {"value": req.min_overlap_percent},
        "allocation": {"value": allocation},
        "update_conda_env": {"value": req.update_conda_env},
        "tapis_base_url": {"value": TAPIS_BASE_URL},
        "tapis_token": {"value": token},
    }
    if max_minutes:
        args["max_minutes"] = {"value": max_minutes}
    if req.pipeline == "werc":
        args.update({
            "reference_mode": {"value": req.reference_mode},
            "reference_lat": {"value": "" if req.reference_lat is None else req.reference_lat},
            "reference_lon": {"value": "" if req.reference_lon is None else req.reference_lon},
            "anchor_radius_m": {"value": req.anchor_radius_m},
            "n_reference_pixels": {"value": req.n_reference_pixels},
        })
        if run_queue:
            queue, cores, memory_mb = run_queue
            args.update({
                "run_queue": {"value": queue},
                "run_cores": {"value": cores},
                "run_memory_mb": {"value": memory_mb},
            })

    if config.SUBSIDE_STAC_URL:
        args.update({
            "stac_collection": {"value": config.SUBSIDE_STAC_COLLECTION},
            "ckan_url": {"value": config.SUBSIDE_CKAN_URL},
            "ckan_org": {"value": config.SUBSIDE_CKAN_ORG},
            "ckan_token": {"value": _ckan_auth_token(config.SUBSIDE_CKAN_TOKEN or token)},
            "stac_url": {"value": config.SUBSIDE_STAC_URL},
            "stac_token": {"value": config.SUBSIDE_STAC_TOKEN or token},
        })
    return args


def _trigger_pipeline(client, pipeline_key: str, run_name: str, run_args: dict[str, dict]) -> str | None:
    group_id = config.SUBSIDE_WORKFLOW_GROUP
    pipeline_id = _pipeline_id(pipeline_key)
    before = set()
    try:
        prior = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        before = {getattr(r, "uuid", None) for r in (prior or [])}
    except Exception:
        pass

    result = client.workflows.runPipeline(
        group_id=group_id,
        pipeline_id=pipeline_id,
        name=run_name,
        description="SUBSIDE API pipeline run",
        args=run_args,
    )
    run_uuid = getattr(result, "uuid", None)
    if run_uuid:
        return run_uuid

    for _ in range(8):
        time.sleep(1)
        try:
            now = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        except Exception:
            continue
        new = {getattr(r, "uuid", None) for r in (now or [])} - before
        new.discard(None)
        if new:
            return sorted(new)[0]
    return None


def submit_run(client, req: RunRequest) -> dict:
    """Stage inputs and submit a Tapis Workflows pipeline run. Does not poll."""
    allocation = req.allocation or config.DEFAULT_ALLOCATION
    if not allocation:
        raise ValueError("No allocation: set one in the request or SUBSIDE_DEFAULT_ALLOCATION in .env.")
    token = _client_token(client)
    if not token:
        raise ValueError("Could not resolve the caller's Tapis token for the workflow run.")

    username = getattr(client, "username", None) or "user"
    short_id = uuid.uuid4().hex[:12]
    staged = _stage(client, username, short_id, req)
    pipeline_id = _pipeline_id(req.pipeline)
    run_name = f"subside-api-{pipeline_id}-{req.start_date}-{req.end_date}-{short_id}"
    max_minutes = _resolve_walltime(req)
    run_queue = _pick_run_queue(req)
    run_args = _workflow_args(req, staged, allocation, token, max_minutes, run_queue=run_queue)
    run_uuid = _trigger_pipeline(client, req.pipeline, run_name, run_args)
    return {
        "uuid": run_uuid,
        "name": run_name,
        "pipelineId": pipeline_id,
        "groupId": config.SUBSIDE_WORKFLOW_GROUP,
        "tapisStatus": "submitted",
    }


def _workflow_details(client, run_uuid: str, pipeline_key: str | None = None) -> dict:
    ids = _pipeline_ids()
    keys = [pipeline_key] if pipeline_key else list(ids)
    errors = []
    for key in keys:
        if key not in ids:
            continue
        pipeline_id = ids[key]
        try:
            run = client.workflows.getPipelineRun(
                group_id=config.SUBSIDE_WORKFLOW_GROUP,
                pipeline_id=pipeline_id,
                pipeline_run_uuid=run_uuid,
            )
        except Exception as exc:
            errors.append(f"{pipeline_id}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        try:
            execs = client.workflows.listTaskExecutions(
                group_id=config.SUBSIDE_WORKFLOW_GROUP,
                pipeline_id=pipeline_id,
                pipeline_run_uuid=run_uuid,
            ) or []
        except Exception:
            execs = []
        return {"pipeline": key, "pipelineId": pipeline_id, "run": run, "tasks": execs}
    detail = "; ".join(errors) if errors else "no SUBSIDE pipeline matched"
    raise LookupError(detail)


def _tasks_summary(execs: list[Any]) -> list[dict]:
    out = []
    for task in execs:
        raw_status = _status_of(task)
        out.append({
            "taskId": _field(task, "task_id"),
            "status": normalize_status(raw_status),
            "tapisStatus": raw_status,
            "lastMessage": _field(task, "last_message"),
        })
    return out


def _effective_status(run: Any, execs: list[Any]) -> tuple[str, str]:
    raw = _status_of(run)
    failed = [e for e in execs if _status_of(e) in FAILURE_STATES]
    if failed:
        return raw, "failed"
    if raw in SUCCESS_STATES:
        return raw, "completed"
    if raw in FAILURE_STATES:
        return raw, normalize_status(raw)
    return raw, normalize_status(raw)


def _last_message(run: Any, execs: list[Any]) -> str | None:
    for task in execs:
        if _status_of(task) in FAILURE_STATES:
            for key in ("last_message", "stderr", "stdout"):
                text = str(_field(task, key) or "").strip()
                if text:
                    return text[-2000:]
    for key in ("last_message", "logs"):
        text = str(_field(run, key) or "").strip()
        if text:
            return text[-2000:]
    return None


def _archive_from_task_output(task: Any) -> str | None:
    for key in ("outputs", "output"):
        output = _field(task, key)
        if isinstance(output, dict):
            for name in ("archive", "ARCHIVE_URI", "archive_uri"):
                value = output.get(name)
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, str) and value.startswith("tapis://"):
                    return value.rstrip("/")
    return None


def _job_uuid_from_tasks(execs: list[Any]) -> str | None:
    ordered = sorted(execs, key=lambda e: 0 if _field(e, "task_id") == "run" else 1)
    for task in ordered:
        text = "\n".join(str(_field(task, key) or "") for key in ("stdout", "stderr", "last_message"))
        match = _JOB_UUID_RE.search(text)
        if match:
            return match.group(1)
    return None


def _archive_from_text(run: Any, execs: list[Any]) -> str | None:
    chunks = [str(_field(run, "logs") or "")]
    for task in execs:
        chunks.extend(str(_field(task, key) or "") for key in ("stdout", "stderr", "last_message"))
    for text in chunks:
        for match in _TAPIS_ARCHIVE_RE.findall(text):
            cleaned = match.rstrip(".,;:)]}'\"")
            if "tapis-jobs-archive" in cleaned:
                return cleaned
    return None


def _archive_from_job(client, job_uuid: str | None) -> str | None:
    if not job_uuid:
        return None
    try:
        job = client.jobs.getJob(jobUuid=job_uuid)
    except Exception:
        return None
    system = _field(job, "archiveSystemId")
    archive_dir = _field(job, "archiveSystemDir")
    if system and archive_dir:
        return f"tapis://{system}/{str(archive_dir).lstrip('/')}".rstrip("/")
    return None


def _workflow_archive(client, run: Any, execs: list[Any]) -> str | None:
    for task in execs:
        if _field(task, "task_id") == "run":
            archive = _archive_from_task_output(task)
            if archive:
                return archive
    return _archive_from_job(client, _job_uuid_from_tasks(execs)) or _archive_from_text(run, execs)


def list_runs(client, limit: int = 100, include_all: bool = False) -> list[dict]:
    """List recent Tapis Workflows runs for the registered SUBSIDE pipelines."""
    del include_all  # The API owns only the configured SUBSIDE pipelines.
    out: list[dict] = []
    for key, pipeline_id in _pipeline_ids().items():
        try:
            runs = client.workflows.listPipelineRuns(
                group_id=config.SUBSIDE_WORKFLOW_GROUP,
                pipeline_id=pipeline_id,
            ) or []
        except Exception:
            continue
        for run in runs:
            raw_status = _status_of(run)
            out.append({
                "runId": _field(run, "uuid"),
                "name": _field(run, "name"),
                "pipeline": key,
                "pipelineId": pipeline_id,
                "appId": None,
                "status": normalize_status(raw_status),
                "tapisStatus": raw_status,
                "created": str(_field(run, "started_at") or _field(run, "created_at") or "") or None,
            })
    out.sort(key=lambda row: row.get("created") or "", reverse=True)
    return out[:limit]


def get_status(client, run_uuid: str) -> dict:
    details = _workflow_details(client, run_uuid)
    run = details["run"]
    tasks = details["tasks"]
    raw_status, status = _effective_status(run, tasks)
    return {
        "pipeline": details["pipeline"],
        "pipelineId": details["pipelineId"],
        "tapisStatus": raw_status,
        "status": status,
        "lastMessage": _last_message(run, tasks),
        "archive": _workflow_archive(client, run, tasks),
        "tasks": _tasks_summary(tasks),
    }


_MANIFEST_NAMES = ("werc-run-manifest.json", "run-manifest.json", "subside-run-manifest.json")


def fetch_file(client, run_uuid: str, path: str) -> tuple[bytes, str, str]:
    """Stream one file from the workflow run task's archive."""
    import mimetypes

    st = get_status(client, run_uuid)
    archive = st.get("archive")
    if not archive:
        raise ValueError("Pipeline run has no analysis archive yet.")
    system, base = _parse_tapis_uri(archive)
    rel = path.lstrip("/")
    base = base.rstrip("/")
    if not (rel == base or rel.startswith(base + "/")):
        raise PermissionError("Path is outside the pipeline run archive.")
    raw = client.files.getContents(systemId=system, path=rel)
    data = raw if isinstance(raw, (bytes, bytearray)) else (
        raw.encode() if isinstance(raw, str) else bytes(raw))
    name = rel.rsplit("/", 1)[-1]
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return bytes(data), name, ctype


def get_results(client, run_uuid: str) -> dict:
    st = get_status(client, run_uuid)
    out: dict[str, Any] = {"status": st["status"], "manifest": None, "artifacts": []}
    archive = st.get("archive")
    if not archive:
        return out

    system, base = _parse_tapis_uri(archive)
    try:
        listing = client.files.listFiles(systemId=system, path=base, recurse=True, limit=1000) or []
    except Exception:
        listing = []

    artifacts: list[Artifact] = []
    manifest_paths: dict[str, str] = {}
    for item in listing:
        path = _field(item, "path") or ""
        ftype = str(_field(item, "type") or "file").lower()
        if ftype == "dir" or not path:
            continue
        name = path.rsplit("/", 1)[-1]
        if name in _MANIFEST_NAMES:
            manifest_paths[name] = path
        artifacts.append(Artifact(
            name=name,
            path=path,
            sizeBytes=_field(item, "size"),
            url=f"{TAPIS_BASE_URL}/v3/files/content/{system}/{path.lstrip('/')}",
        ))
    out["artifacts"] = artifacts

    for name in _MANIFEST_NAMES:
        if name not in manifest_paths:
            continue
        try:
            raw = client.files.getContents(systemId=system, path=manifest_paths[name])
            text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            out["manifest"] = json.loads(text)
        except Exception:
            pass
        break
    return out
