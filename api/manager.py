"""Tapis run lifecycle for the SUBSIDE API: stage -> submit -> status -> results.

This is the request-driven cousin of workflows/orchestrate.py. It submits the
single monolithic `run` job per pipeline (the apps' STAGE=run does discover +
download [+ analysis] in one job), polled separately by the status endpoint.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from typing import Any

import yaml

from .config import PIPELINE_DIR, PIPELINES, STAGING_PREFIX, STAGING_SYSTEM, TAPIS_BASE_URL
from .models import Artifact, RunRequest

_TMPL = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")

# Tapis Job status -> normalized UI status.
_STATUS_MAP = {
    "PENDING": "queued", "PROCESSING_INPUTS": "queued", "STAGING_INPUTS": "queued",
    "STAGING_JOB": "queued", "SUBMITTING_JOB": "queued", "QUEUED": "queued",
    "BLOCKED": "queued", "PAUSED": "queued",
    "RUNNING": "running", "ARCHIVING": "running",
    "FINISHED": "completed", "FAILED": "failed", "CANCELLED": "cancelled",
}


def normalize_status(tapis_status: str) -> str:
    return _STATUS_MAP.get(str(tapis_status or "").upper(), "unknown")


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _resolve(value: Any, ctx: dict) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            cur: Any = ctx
            for part in m.group(1).split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is None:
                    return ""
            return str(cur)
        return _TMPL.sub(repl, value)
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    return value


def _alloc_arg(allocation: str) -> str:
    allocation = allocation.strip()
    return allocation if allocation.startswith("-") else f"-A {allocation}"


def _parse_tapis_uri(uri: str) -> tuple[str, str]:
    rest = uri[len("tapis://"):]
    system, _, path = rest.partition("/")
    return system, path


def _build_run_config(req: RunRequest) -> dict:
    """The run-config.json the app CLI consumes. Paths are relative to the job
    working dir (aoi mounts at config/aoi.geojson, outputs go to output/)."""
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


def _load_pipeline(pipeline_key: str) -> dict:
    path = PIPELINE_DIR / f"{PIPELINES[pipeline_key]}.yaml"
    with path.open() as f:
        return yaml.safe_load(f)


def _build_job_body(job_def: dict, allocation: str) -> dict:
    body: dict[str, Any] = {
        "name": job_def["name"],
        "appId": job_def["appId"],
        "appVersion": str(job_def["appVersion"]),
    }
    for k in ("nodeCount", "coresPerNode", "memoryMB", "maxMinutes"):
        if k in job_def:
            body[k] = job_def[k]
    file_inputs = []
    for fi in job_def.get("fileInputs", []):
        src = (fi.get("sourceUrl") or "").strip()
        if not src:
            continue
        entry = {"name": fi["name"], "sourceUrl": src}
        if fi.get("targetPath"):
            entry["targetPath"] = fi["targetPath"]
        file_inputs.append(entry)
    if file_inputs:
        body["fileInputs"] = file_inputs
    pset = job_def.get("parameterSet", {}) or {}
    out: dict[str, Any] = {}
    if pset.get("envVariables"):
        out["envVariables"] = [{"key": e["key"], "value": str(e.get("value", ""))}
                               for e in pset["envVariables"]]
    sched = []
    for so in pset.get("schedulerOptions", []):
        if so.get("name") == "TACC Allocation":
            sched.append({"name": "TACC Allocation", "arg": _alloc_arg(allocation)})
        else:
            sched.append(so)
    if sched:
        out["schedulerOptions"] = sched
    if out:
        body["parameterSet"] = out
    return body


def _stage(client, username: str, run_id: str, req: RunRequest) -> dict:
    """Upload run-config.json, AOI, and (optionally) a .netrc; return URIs."""
    base = STAGING_PREFIX.format(username=username) + f"/{run_id}"
    client.files.mkdir(systemId=STAGING_SYSTEM, path=base)

    run_config = _build_run_config(req)
    client.files.insert(systemId=STAGING_SYSTEM, path=f"{base}/run-config.json",
                        file=io.BytesIO(json.dumps(run_config).encode()))
    client.files.insert(systemId=STAGING_SYSTEM, path=f"{base}/aoi.geojson",
                        file=io.BytesIO(json.dumps(req.aoi_geojson).encode()))

    netrc_uri = req.earthdata_netrc_uri or ""
    if not netrc_uri and req.earthdata_username and req.earthdata_password:
        netrc = (f"machine urs.earthdata.nasa.gov login {req.earthdata_username} "
                 f"password {req.earthdata_password}\n")
        client.files.insert(systemId=STAGING_SYSTEM, path=f"{base}/.netrc",
                            file=io.BytesIO(netrc.encode()))
        netrc_uri = f"tapis://{STAGING_SYSTEM}/{base}/.netrc"

    return {
        "run_config_uri": f"tapis://{STAGING_SYSTEM}/{base}/run-config.json",
        "aoi_geojson_uri": f"tapis://{STAGING_SYSTEM}/{base}/aoi.geojson",
        "earthdata_netrc_uri": netrc_uri,
    }


def submit_run(client, req: RunRequest) -> dict:
    """Stage inputs + submit the monolithic run job. Returns submission info.
    Does NOT poll — the status endpoint does that."""
    username = getattr(client, "username", None) or "user"
    run_id = uuid.uuid4().hex[:12]
    staged = _stage(client, username, run_id, req)

    pipeline = _load_pipeline(req.pipeline)
    run_task = next(t for t in pipeline["tasks"] if t["id"] == "run")
    ctx = {
        "args": {
            "start_date": req.start_date,
            "end_date": req.end_date,
            "aoi_geojson_uri": staged["aoi_geojson_uri"],
            "earthdata_netrc_uri": staged["earthdata_netrc_uri"],
            "update_conda_env": req.update_conda_env,
            "allocation": req.allocation,
        },
        "workflow": {"inline_files": {"run_config_uri": staged["run_config_uri"]}},
    }
    job_def = _resolve(run_task["tapis_job_def"], ctx)
    body = _build_job_body(job_def, req.allocation)
    result = client.jobs.submitJob(**body)
    return {
        "uuid": _field(result, "uuid"),
        "name": body["name"],
        "tapisStatus": _field(result, "status") or "PENDING",
    }


def get_status(client, run_uuid: str) -> dict:
    job = client.jobs.getJob(jobUuid=run_uuid)
    tapis_status = str(_field(job, "status") or "UNKNOWN")
    sys_id, sys_dir = _field(job, "archiveSystemId"), _field(job, "archiveSystemDir")
    archive = f"tapis://{sys_id}/{str(sys_dir).lstrip('/')}" if sys_id and sys_dir else None
    return {
        "tapisStatus": tapis_status,
        "status": normalize_status(tapis_status),
        "lastMessage": _field(job, "lastMessage"),
        "archive": archive,
    }


# Manifest filenames written by the apps, in priority order.
_MANIFEST_NAMES = ("werc-run-manifest.json", "run-manifest.json", "subside-run-manifest.json")


def get_results(client, run_uuid: str) -> dict:
    st = get_status(client, run_uuid)
    out: dict[str, Any] = {"status": st["status"], "manifest": None, "artifacts": []}
    archive = st["archive"]
    if st["status"] != "completed" or not archive:
        return out

    system, base = _parse_tapis_uri(archive)
    # List the archive (recursively) to find artifacts + the manifest.
    try:
        listing = client.files.listFiles(systemId=system, path=base, recurse=True, limit=1000) or []
    except Exception:
        listing = []

    artifacts: list[Artifact] = []
    manifest_paths: dict[str, str] = {}
    for f in listing:
        path = _field(f, "path") or ""
        ftype = str(_field(f, "type") or "file")
        if ftype == "dir" or not path:
            continue
        name = path.rsplit("/", 1)[-1]
        if name in _MANIFEST_NAMES:
            manifest_paths[name] = path
        artifacts.append(Artifact(
            name=name, path=path, sizeBytes=_field(f, "size"),
            url=f"{TAPIS_BASE_URL}/v3/files/content/{system}/{path.lstrip('/')}",
        ))
    out["artifacts"] = artifacts

    for mname in _MANIFEST_NAMES:
        if mname in manifest_paths:
            try:
                raw = client.files.getContents(systemId=system, path=manifest_paths[mname])
                out["manifest"] = json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
            except Exception:
                pass
            break
    return out
