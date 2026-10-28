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
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import yaml

from . import discovery, tapis as tapis_service, token_store
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


class RunTokenConfigurationError(RuntimeError):
    """Per-run token lifecycle is not safely configured."""


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
_PUBLISH_PIPELINE_ID = "subside-publish"
_JOB_APP_IDS = {
    "h2i": "subside-h2i-opera-analysis",
    "werc": "subside-werc-opera-analysis",
}


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


def _job_name_prefix(pipeline_key: str, lease_id: str) -> str:
    return f"subside-{pipeline_key}-opera-{lease_id}"


def _run_token_window_seconds(max_minutes: int) -> int:
    """Queue plus compute window shared by TTL and hard-deadline arithmetic."""
    return config.RUN_TOKEN_QUEUE_BUDGET_SECONDS + max(1, int(max_minutes)) * 60


def _hard_deadline(max_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(
        seconds=_run_token_window_seconds(max_minutes)
        + config.RUN_RECOVERY_GRACE_SECONDS,
    )).isoformat()


def _redact(text: str | None) -> str | None:
    value = str(text or "")
    if not value:
        return None
    value = re.sub(r"(?i)(x-tapis-token|authorization|tapis_token|token)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    return value[-2000:]


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
        "staging_path": base,
    }


def _run_token_ttl(max_minutes: int) -> int:
    # The initial token must cover scheduler queue time plus the requested
    # compute walltime. After that, the broker can rotate it while the lease is
    # still inside its finite hard deadline.
    requested = _run_token_window_seconds(max_minutes) + config.RUN_TOKEN_TTL_BUFFER_SECONDS
    if requested > config.RUN_TOKEN_TTL_MAX_SECONDS:
        raise RunTokenConfigurationError(
            "Required run-token TTL exceeds SUBSIDE_RUN_TOKEN_TTL_MAX_SECONDS; "
            "increase the maximum or reduce the queue/walltime budget."
        )
    return max(config.RUN_TOKEN_TTL_MIN_SECONDS, requested)


def _delete_staging(client, path: str | None) -> None:
    if not path:
        return
    try:
        client.files.delete(systemId=STAGING_SYSTEM, path=path)
    except Exception:
        pass


def _is_ambiguous_submission(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        try:
            if int(status_code) >= 500:
                return True
        except (TypeError, ValueError):
            pass
    text = str(exc).lower()
    return any(marker in text for marker in (
        "timeout", "timed out", "gateway", "connection", "temporarily unavailable", "504",
    ))


def _cleanup_lease(client, lease_id: str) -> bool:
    lease = token_store.claim_cleanup(lease_id)
    if lease is None:
        return False
    try:
        auth_token = _client_token(client)
        if not auth_token or not lease.token:
            raise tapis_service.TokenRevokeError("No credential available for token cleanup.")
        tapis_service.revoke_token(auth_token, lease.token)
    except Exception as exc:
        token_store.mark_cleanup_failed(lease_id, str(exc))
        return False
    token_store.mark_revoked(lease_id)
    _delete_staging(client, lease.staging_path)
    return True


def reconcile_run_tokens(client) -> int:
    """Recover active leases, then retry only safe cleanup records."""
    recovered = 0
    for lease in token_store.active_recovery_candidates():
        if not lease.workflow_uuid or not lease.token:
            continue
        try:
            run_client = tapis_service.client_from_token(lease.token)
            get_status(run_client, lease.workflow_uuid)
            recovered += 1
        except Exception:
            # Startup reconciliation is best-effort; the lease remains active
            # and the next status request or startup pass can retry it.
            continue
    cleaned = 0
    for lease in token_store.cleanup_candidates():
        cleanup_client = client
        if cleanup_client is None and lease.token:
            try:
                cleanup_client = tapis_service.client_from_token(lease.token)
            except Exception:
                cleanup_client = None
        if cleanup_client is not None and _cleanup_lease(cleanup_client, lease.lease_id):
            cleaned += 1
    for lease in token_store.expired_candidates():
        token_store.mark_expired(lease.lease_id)
        cleanup_client = client
        if cleanup_client is None and lease.token:
            try:
                cleanup_client = tapis_service.client_from_token(lease.token)
            except Exception:
                cleanup_client = None
        _delete_staging(cleanup_client, lease.staging_path)
        cleaned += 1
    return recovered + cleaned


def _workflow_args(req: RunRequest, staged: dict, allocation: str, token: str,
                   username: str = "",
                   max_minutes: int | None = None,
                   run_queue: tuple[str, int, int] | None = None,
                   job_name_prefix: str | None = None,
                   run_token_lease_id: str | None = None,
                   run_token_credential: str | None = None) -> dict[str, dict]:
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
    if job_name_prefix:
        args["job_name_prefix"] = {"value": job_name_prefix}
    if config.SUBSIDE_TOKEN_BROKER_URL and run_token_lease_id and run_token_credential:
        args.update({
            "token_broker_url": {"value": config.SUBSIDE_TOKEN_BROKER_URL},
            "run_token_lease_id": {"value": run_token_lease_id},
            "run_token_credential": {"value": run_token_credential},
        })
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
            # Who to credit as the CKAN dataset's "author" -- the logged-in
            # SUBSIDE user who submitted this run, not a fixed service contact.
            "submitter_username": {"value": username},
        })
    return args


def _trigger_pipeline_id(client, pipeline_id: str, run_name: str,
                         run_args: dict[str, dict], description: str) -> str | None:
    group_id = config.SUBSIDE_WORKFLOW_GROUP
    existing = _workflow_by_name(client, pipeline_id, run_name)
    if existing:
        return existing
    before = set()
    try:
        prior = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        before = {_field(r, "uuid") for r in (prior or [])}
    except Exception:
        pass

    result = client.workflows.runPipeline(
        group_id=group_id,
        pipeline_id=pipeline_id,
        name=run_name,
        description=description,
        args=run_args,
    )
    run_uuid = _field(result, "uuid")
    if run_uuid:
        return run_uuid

    for _ in range(8):
        time.sleep(1)
        try:
            now = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        except Exception:
            continue
        new = {_field(r, "uuid") for r in (now or [])} - before
        new.discard(None)
        if new:
            return sorted(new)[0]
    return None


def _trigger_pipeline(client, pipeline_key: str, run_name: str, run_args: dict[str, dict]) -> str | None:
    return _trigger_pipeline_id(
        client, _pipeline_id(pipeline_key), run_name, run_args,
        "SUBSIDE API pipeline run",
    )


def submit_run(client, req: RunRequest) -> dict:
    """Stage inputs and submit a Tapis Workflows pipeline run. Does not poll."""
    if not config.RUN_TOKEN_ENABLED:
        raise RunTokenConfigurationError(
            "Per-run Tapis tokens are disabled; set SUBSIDE_RUN_TOKEN_ENABLED=true "
            "and configure the encrypted lease store."
        )
    try:
        token_store.validate_configuration()
    except token_store.TokenStoreConfigurationError as exc:
        raise RunTokenConfigurationError(str(exc)) from exc
    allocation = req.allocation or config.DEFAULT_ALLOCATION
    if not allocation:
        raise ValueError("No allocation: set one in the request or SUBSIDE_DEFAULT_ALLOCATION in .env.")
    token = _client_token(client)
    if not token:
        raise ValueError("Could not resolve the caller's Tapis token for the workflow run.")

    # Fall back to the "user" placeholder for the staging path only (it can't
    # be empty); the CKAN author arg gets the real claim or "" so
    # _dataset_payload's own fallback (not the literal word "user") applies.
    real_username = getattr(client, "username", None) or ""
    if not real_username:
        raise ValueError("Could not derive the authenticated Tapis username for the workflow run.")
    username = real_username or "user"
    short_id = uuid.uuid4().hex[:12]
    staged = None
    pipeline_id = _pipeline_id(req.pipeline)
    job_name_prefix = _job_name_prefix(req.pipeline, short_id)
    max_minutes = _resolve_walltime(req)
    run_token_ttl = _run_token_ttl(max_minutes)
    try:
        staged = _stage(client, username, short_id, req)
    except Exception:
        _delete_staging(client, STAGING_PREFIX.format(username=username) + f"/{short_id}")
        raise
    run_name = f"subside-api-{pipeline_id}-{req.start_date}-{req.end_date}-{short_id}"
    run_queue = _pick_run_queue(req)
    target_site_id = f"{config.RUN_TOKEN_TARGET_PREFIX}-{short_id}"
    broker_credential = secrets.token_urlsafe(32)
    try:
        minted = tapis_service.mint_run_token(
            token, real_username, target_site_id, run_token_ttl
        )
        run_token = minted["token"]
    except Exception:
        _delete_staging(client, staged.get("staging_path"))
        raise

    try:
        token_store.create(
            short_id,
            token=run_token,
            username=real_username,
            target_site_id=target_site_id,
            staging_path=staged.get("staging_path"),
            expires_at=minted.get("expires_at"),
            pipeline_id=pipeline_id,
            job_name_prefix=job_name_prefix,
            hard_deadline_at=_hard_deadline(max_minutes),
            broker_secret=broker_credential,
        )
    except Exception as exc:
        # The token exists but was not persisted, so compensate immediately.
        try:
            tapis_service.revoke_token(token, run_token)
        except Exception:
            pass
        _delete_staging(client, staged.get("staging_path"))
        raise RunTokenConfigurationError("Could not persist the run-token lease.") from exc

    run_args = _workflow_args(
        req, staged, allocation, run_token, username=real_username,
        max_minutes=max_minutes, run_queue=run_queue,
        job_name_prefix=job_name_prefix,
        run_token_lease_id=short_id,
        run_token_credential=broker_credential,
    )
    try:
        run_uuid = _trigger_pipeline(client, req.pipeline, run_name, run_args)
    except Exception as exc:
        if _is_ambiguous_submission(exc):
            token_store.mark_submission_unknown(short_id)
        else:
            _cleanup_lease(client, short_id)
        raise
    if not run_uuid:
        # The remote response may have been accepted even though no UUID was
        # returned. Never blindly retry or revoke a possibly-running workflow.
        token_store.mark_submission_unknown(short_id)
    else:
        token_store.bind_workflow(short_id, run_uuid)
    return {
        "uuid": run_uuid,
        "name": run_name,
        "pipelineId": pipeline_id,
        "groupId": config.SUBSIDE_WORKFLOW_GROUP,
        "tapisStatus": "submitted",
    }


def refresh_run_token(lease_id: str, credential: str) -> dict:
    """Refresh the user's OAuth session, then rotate this run's bounded token."""
    lease = token_store.find_by_lease_credential(lease_id, credential)
    if not lease or lease.lease_state != "active":
        raise RunTokenConfigurationError("Run credential is invalid or inactive.")
    now = datetime.now(timezone.utc)
    if lease.hard_deadline_at:
        try:
            hard_deadline = datetime.fromisoformat(
                lease.hard_deadline_at.replace("Z", "+00:00")
            )
            if hard_deadline.tzinfo is None:
                hard_deadline = hard_deadline.replace(tzinfo=timezone.utc)
            if hard_deadline <= now:
                raise RunTokenConfigurationError("Run credential is past its hard deadline.")
        except ValueError as exc:
            raise RunTokenConfigurationError("Run credential has an invalid hard deadline.") from exc
    if lease.token and lease.expires_at:
        try:
            expires_at = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            # This also makes a retry after a lost broker response idempotent:
            # return the token already persisted by the first request.
            if expires_at > now + timedelta(seconds=60):
                return {"token": lease.token, "expires_at": lease.expires_at}
        except ValueError:
            pass
    refresh = token_store.get_user_refresh_token(lease.username)
    if not refresh:
        raise RunTokenConfigurationError("No server-side OAuth refresh token is stored for this user.")
    refreshed = tapis_service.refresh_user_token(refresh)
    token_store.upsert_user_refresh_token(lease.username, refreshed.get("refresh_token"))
    rotated = tapis_service.mint_run_token(
        refreshed["token"], lease.username, lease.target_site_id, 3600
    )
    if lease.token and lease.token != rotated["token"]:
        try:
            tapis_service.revoke_token(refreshed["token"], lease.token)
        except Exception:
            # An expired predecessor is already unusable; the new token is
            # still persisted so the workflow can continue and cleanup can
            # revoke the current token later.
            pass
    token_store.replace_token(lease.lease_id, rotated["token"], rotated.get("expires_at"))
    return {"token": rotated["token"], "expires_at": rotated.get("expires_at")}


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
                    return _redact(text)
    for key in ("last_message", "logs"):
        text = str(_field(run, key) or "").strip()
        if text:
            return _redact(text)
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
        for key in ("outputs", "output"):
            output = _field(task, key)
            if isinstance(output, dict):
                value = output.get("job_uuid") or output.get("JOB_UUID")
                if isinstance(value, dict):
                    value = value.get("value")
                if value:
                    return str(value)
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


def _job_summary(job: Any) -> dict[str, Any]:
    fields = (
        "uuid", "name", "owner", "tenant", "appId", "status", "condition",
        "created", "ended", "archiveSystemId", "archiveSystemDir",
        "remoteOutcome", "remoteResultInfo",
    )
    return {field: _field(job, field) for field in fields if _field(job, field) is not None}


def _job_owner_matches(job: dict[str, Any], lease: token_store.Lease) -> bool:
    owner = str(job.get("owner") or "").strip()
    if not owner:
        return False
    return owner == lease.username or owner.split("@", 1)[0] == lease.username


def _job_is_success(job: dict[str, Any]) -> bool:
    return (
        str(job.get("status") or "").upper() == "FINISHED"
        and str(job.get("condition") or "").upper() == "NORMAL_COMPLETION"
    )


def _job_is_active(job: dict[str, Any]) -> bool:
    return str(job.get("status") or "").upper() in {
        "SUBMITTED", "STAGING", "INITIALIZING", "PENDING", "QUEUED", "ACTIVE", "RUNNING"
    }


def _job_is_failed(job: dict[str, Any]) -> bool:
    return str(job.get("status") or "").upper() in {"FAILED", "CANCELLED", "CANCELED", "STOPPED", "TERMINATED"}


def _job_is_oom(job: dict[str, Any]) -> bool:
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("remoteOutcome", "remoteResultInfo", "condition", "status")
    ).lower()
    return any(marker in blob for marker in (
        "out_of_memory", "oom", "out of memory", "memoryerror", "exit code 137",
        "exitcode 137", "code 137", "signal 9", "memory limit",
    ))


def _archive_from_job_summary(job: dict[str, Any]) -> str | None:
    system = job.get("archiveSystemId")
    archive_dir = job.get("archiveSystemDir")
    if system and archive_dir:
        return f"tapis://{system}/{str(archive_dir).lstrip('/')}".rstrip("/")
    return None


def _archive_ready(client, archive: str | None) -> bool:
    if not archive:
        return False
    try:
        system, base = _parse_tapis_uri(archive)
        listing = client.files.listFiles(systemId=system, path=base, recurse=True, limit=1000) or []
    except Exception:
        return False
    names = {str(_field(item, "path") or "").rsplit("/", 1)[-1] for item in listing}
    return bool(names & set(_MANIFEST_NAMES))


def _candidate_job_names(lease: token_store.Lease, pipeline_key: str) -> list[str]:
    if not lease.job_name_prefix:
        return []
    if pipeline_key == "werc":
        return [f"{lease.job_name_prefix}-attempt-1", f"{lease.job_name_prefix}-attempt-2"]
    return [lease.job_name_prefix]


def _find_recovery_job(client, lease: token_store.Lease, pipeline_key: str) -> dict[str, Any] | None:
    app_id = _JOB_APP_IDS.get(pipeline_key)
    if lease.compute_job_uuid:
        try:
            direct = _job_summary(client.jobs.getJob(jobUuid=lease.compute_job_uuid))
            if (direct.get("uuid") and (not app_id or direct.get("appId") == app_id)
                    and _job_owner_matches(direct, lease)):
                return direct
        except Exception:
            pass

    exact: list[dict[str, Any]] = []
    names = _candidate_job_names(lease, pipeline_key)
    if pipeline_key == "werc" and len(names) == 2:
        attempts = []
        for name in names:
            matches = [job for job in tapis_service.search_jobs(client, name=name, app_id=app_id)
                       if _job_owner_matches(job, lease)]
            if len(matches) > 1:
                raise ValueError("Multiple exact-name WERC attempt jobs matched this run.")
            attempts.append(matches[0] if matches else None)
        first, second = attempts
        if second:
            if not first or not (_job_is_failed(first) and _job_is_oom(first)):
                raise ValueError("WERC attempt 2 exists without confirmed OOM completion of attempt 1.")
            return second
        if first:
            return first
    else:
        for name in names:
            exact.extend(tapis_service.search_jobs(client, name=name, app_id=app_id))
        exact = [job for job in exact if _job_owner_matches(job, lease)]
        if len(exact) > 1:
            raise ValueError("Multiple exact-name compute jobs matched this run.")
        if exact:
            return exact[0]

    # Legacy runs have no durable prefix. Search is intentionally strict: a
    # time window with multiple candidates is not safe enough to adopt.
    if not app_id:
        return None
    legacy = tapis_service.search_jobs(client, app_id=app_id, created_after=lease.created_at)
    legacy = [job for job in legacy if _job_owner_matches(job, lease)]
    if len(legacy) > 1:
        raise ValueError("Multiple legacy compute jobs matched this run.")
    return legacy[0] if legacy else None


def _publish_args(lease: token_store.Lease, job_uuid: str) -> dict[str, dict]:
    token = lease.token or ""
    return {
        "job_uuid": {"value": job_uuid},
        "tapis_base_url": {"value": TAPIS_BASE_URL},
        "tapis_token": {"value": token},
        "submitter_username": {"value": lease.username},
        "manifest_name": {"value": ""},
        "stac_collection": {"value": config.SUBSIDE_STAC_COLLECTION},
        "stac_item_id": {"value": ""},
        "ckan_url": {"value": config.SUBSIDE_CKAN_URL},
        "ckan_org": {"value": config.SUBSIDE_CKAN_ORG},
        "ckan_token": {"value": _ckan_auth_token(config.SUBSIDE_CKAN_TOKEN or token)},
        "stac_url": {"value": config.SUBSIDE_STAC_URL},
        "stac_token": {"value": config.SUBSIDE_STAC_TOKEN or token},
    }


def _workflow_by_name(client, pipeline_id: str, name: str) -> str | None:
    runs = client.workflows.listPipelineRuns(
        group_id=config.SUBSIDE_WORKFLOW_GROUP, pipeline_id=pipeline_id,
    ) or []
    matches = [r for r in runs if _field(r, "name") == name]
    if len(matches) > 1:
        raise ValueError("Multiple publish workflow runs matched the recovery name.")
    return _field(matches[0], "uuid") if matches else None


def _publish_status(lease: token_store.Lease) -> str:
    if not lease.publish_workflow_uuid or not lease.token:
        return "pending"
    try:
        client = tapis_service.client_from_token(lease.token)
        run = client.workflows.getPipelineRun(
            group_id=config.SUBSIDE_WORKFLOW_GROUP,
            pipeline_id=_PUBLISH_PIPELINE_ID,
            pipeline_run_uuid=lease.publish_workflow_uuid,
        )
        raw = _status_of(run)
        try:
            tasks = client.workflows.listTaskExecutions(
                group_id=config.SUBSIDE_WORKFLOW_GROUP,
                pipeline_id=_PUBLISH_PIPELINE_ID,
                pipeline_run_uuid=lease.publish_workflow_uuid,
            ) or []
        except Exception:
            tasks = []
        if any(_status_of(task) in FAILURE_STATES for task in tasks):
            return "failed"
        if raw in SUCCESS_STATES:
            return "completed"
        if raw in FAILURE_STATES:
            return "failed"
        return "active"
    except Exception:
        return "active"


def _reconcile_lease(client, details: dict, run: Any, tasks: list[Any]) -> dict[str, Any] | None:
    if not config.RUN_RECOVERY_ENABLED:
        return None
    lease = token_store.find_by_workflow(str(_field(run, "uuid") or ""))
    pipeline_key = details.get("pipeline")
    if (not lease or lease.lease_state != "active" or not lease.token
            or pipeline_key not in _JOB_APP_IDS):
        return None
    token_store.set_recovery_state(lease.lease_id, "reconciling")
    try:
        job = _find_recovery_job(client, lease, pipeline_key)
    except tapis_service.JobsSearchError as exc:
        token_store.set_recovery_state(lease.lease_id, "reconciling", error=str(exc))
        return {"status": "recovering", "reconciliationStatus": "reconciling",
                "computeStatus": "unknown", "publicationStatus": "pending",
                "recovered": False, "innerJobUuid": lease.compute_job_uuid}
    except ValueError as exc:
        token_store.set_recovery_state(lease.lease_id, "ambiguous", error=str(exc))
        return {"status": "recovering", "reconciliationStatus": "ambiguous",
                "computeStatus": "ambiguous", "publicationStatus": "pending",
                "recovered": False, "innerJobUuid": lease.compute_job_uuid,
                "lastMessage": str(exc)}

    if not job:
        token_store.set_recovery_state(lease.lease_id, "reconciling", error="Compute job not found yet.")
        return {"status": "recovering", "reconciliationStatus": "reconciling",
                "computeStatus": "unknown", "publicationStatus": "pending",
                "recovered": False, "innerJobUuid": lease.compute_job_uuid}

    job_uuid = str(job.get("uuid") or "")
    if job_uuid:
        token_store.record_compute_job(lease.lease_id, job_uuid)
    if _job_is_active(job):
        token_store.set_recovery_state(lease.lease_id, "compute_active")
        return {"status": "recovering", "reconciliationStatus": "compute_active",
                "computeStatus": str(job.get("status") or "unknown").lower(),
                "publicationStatus": "pending", "recovered": True, "innerJobUuid": job_uuid}
    if _job_is_failed(job):
        token_store.set_recovery_state(lease.lease_id, "failed", error="Inner compute job failed.")
        return {"status": "failed", "reconciliationStatus": "failed",
                "computeStatus": str(job.get("status") or "failed").lower(),
                "publicationStatus": "not_started", "recovered": True, "innerJobUuid": job_uuid}
    if not _job_is_success(job):
        token_store.set_recovery_state(lease.lease_id, "ambiguous", error="Inner job lacked normal completion.")
        return {"status": "recovering", "reconciliationStatus": "ambiguous",
                "computeStatus": "ambiguous", "publicationStatus": "pending",
                "recovered": True, "innerJobUuid": job_uuid}

    archive = _archive_from_job_summary(job) or _workflow_archive(client, run, tasks)
    if not _archive_ready(client, archive):
        token_store.set_recovery_state(lease.lease_id, "compute_succeeded", error="Archive manifest is not ready.")
        return {"status": "recovering", "reconciliationStatus": "compute_succeeded",
                "computeStatus": "completed", "publicationStatus": "pending",
                "recovered": True, "innerJobUuid": job_uuid, "archive": archive}

    if not config.SUBSIDE_STAC_URL or not config.RUN_RECOVERY_PUBLISH:
        token_store.set_recovery_state(lease.lease_id, "completed")
        return {"status": "completed", "reconciliationStatus": "completed",
                "computeStatus": "completed", "publicationStatus": "not_configured",
                "recovered": True, "innerJobUuid": job_uuid, "archive": archive}

    if lease.publish_workflow_uuid:
        pub_status = _publish_status(lease)
        if pub_status == "completed":
            token_store.set_recovery_state(lease.lease_id, "completed")
            return {"status": "completed", "reconciliationStatus": "completed",
                    "computeStatus": "completed", "publicationStatus": "completed",
                    "recovered": True, "innerJobUuid": job_uuid, "archive": archive}
        if pub_status == "failed":
            token_store.set_recovery_state(lease.lease_id, "failed", error="Recovery publication failed.")
            return {"status": "failed", "reconciliationStatus": "failed",
                    "computeStatus": "completed", "publicationStatus": "failed",
                    "recovered": True, "innerJobUuid": job_uuid, "archive": archive}
        token_store.set_recovery_state(lease.lease_id, "publish_active")
        return {"status": "recovering", "reconciliationStatus": "publish_active",
                "computeStatus": "completed", "publicationStatus": "active",
                "recovered": True, "innerJobUuid": job_uuid, "archive": archive}

    try:
        if not lease.token:
            raise RuntimeError("Stored run token is unavailable for recovery publication.")
        publish_client = tapis_service.client_from_token(lease.token)
        name = f"subside-publish-recovery-{lease.lease_id}"
        token_store.set_recovery_state(lease.lease_id, "publish_submitting")
        existing = _workflow_by_name(publish_client, _PUBLISH_PIPELINE_ID, name)
        publish_uuid = existing or _trigger_pipeline_id(
            publish_client, _PUBLISH_PIPELINE_ID, name, _publish_args(lease, job_uuid),
            "SUBSIDE automatic recovery publication",
        )
        if not publish_uuid:
            token_store.set_recovery_state(lease.lease_id, "ambiguous", error="Publish submission returned no UUID.")
            return {"status": "recovering", "reconciliationStatus": "ambiguous",
                    "computeStatus": "completed", "publicationStatus": "unknown",
                    "recovered": True, "innerJobUuid": job_uuid, "archive": archive}
        token_store.set_recovery_state(
            lease.lease_id, "publish_active", publish_workflow_uuid=publish_uuid,
        )
    except Exception as exc:
        if _is_ambiguous_submission(exc):
            token_store.set_recovery_state(lease.lease_id, "publish_submitting", error=str(exc))
            return {"status": "recovering", "reconciliationStatus": "publish_submitting",
                    "computeStatus": "completed", "publicationStatus": "unknown",
                    "recovered": True, "innerJobUuid": job_uuid, "archive": archive}
        token_store.set_recovery_state(lease.lease_id, "failed", error=str(exc))
        return {"status": "failed", "reconciliationStatus": "failed",
                "computeStatus": "completed", "publicationStatus": "failed",
                "recovered": True, "innerJobUuid": job_uuid, "archive": archive,
                "lastMessage": _redact(str(exc))}
    return {"status": "recovering", "reconciliationStatus": "publish_active",
            "computeStatus": "completed", "publicationStatus": "active",
            "recovered": True, "innerJobUuid": job_uuid, "archive": archive}


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
            row = {
                "runId": _field(run, "uuid"),
                "name": _field(run, "name"),
                "pipeline": key,
                "pipelineId": pipeline_id,
                "appId": None,
                "status": normalize_status(raw_status),
                "tapisStatus": raw_status,
                "created": str(_field(run, "started_at") or _field(run, "created_at") or "") or None,
            }
            run_uuid = row["runId"]
            if run_uuid:
                try:
                    detail = get_status(client, str(run_uuid))
                    row.update({key: detail[key] for key in (
                        "status", "reconciliationStatus", "computeStatus",
                        "publicationStatus", "recovered", "innerJobUuid",
                    ) if key in detail})
                except Exception:
                    pass
            out.append(row)
    out.sort(key=lambda row: row.get("created") or "", reverse=True)
    return out[:limit]


def get_status(client, run_uuid: str) -> dict:
    details = _workflow_details(client, run_uuid)
    run = details["run"]
    tasks = details["tasks"]
    raw_status, status = _effective_status(run, tasks)
    result = {
        "pipeline": details["pipeline"],
        "pipelineId": details["pipelineId"],
        "tapisStatus": raw_status,
        "status": status,
        "lastMessage": _last_message(run, tasks),
        "archive": _workflow_archive(client, run, tasks),
        "tasks": _tasks_summary(tasks),
        "reconciliationStatus": "none",
        "computeStatus": "unknown",
        "publicationStatus": (
            "completed" if status == "completed" and config.SUBSIDE_STAC_URL
            else "not_configured" if status == "completed" else "pending"
        ),
        "innerJobUuid": _job_uuid_from_tasks(tasks),
        "recovered": False,
    }
    lease = token_store.find_by_workflow(run_uuid)
    recovery = None
    if lease and status not in SUCCESS_STATES and lease.recovery_state == "completed":
        result.update({
            "status": "completed",
            "reconciliationStatus": "completed",
            "computeStatus": "completed",
            "publicationStatus": "completed" if config.SUBSIDE_STAC_URL else "not_configured",
            "innerJobUuid": lease.compute_job_uuid,
            "recovered": True,
        })
        result["archive"] = _archive_from_job(client, lease.compute_job_uuid) or result["archive"]
    if lease and lease.lease_state == "active" and status not in SUCCESS_STATES:
        recovery = _reconcile_lease(client, details, run, tasks)
        if recovery:
            result.update(recovery)
            if recovery.get("archive"):
                result["archive"] = recovery["archive"]
            if recovery.get("lastMessage"):
                result["lastMessage"] = recovery["lastMessage"]
    if lease and (
        status in SUCCESS_STATES
        or result.get("reconciliationStatus") in {"completed", "failed"}
    ):
        _cleanup_lease(client, lease.lease_id)
    return result


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
