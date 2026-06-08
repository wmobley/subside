"""Live smoke test for the SUBSIDE Tapis Workflows pipelines or direct jobs.

Triggers each registered pipeline against ``portals.tapis.io`` with the
Houston-Galveston test data from the local walkthroughs, then polls the run
until it reaches a terminal state, printing per-task status as it goes.
With ``--direct-jobs`` it skips Workflows and submits the pipeline's monolithic
``run`` task directly through the Tapis Jobs API.

This CONSUMES REAL COMPUTE on your TACC allocation and downloads OPERA
products from Earthdata. Use ``--dry-run`` to validate the run payloads and
staging plan without submitting anything.

Usage::

    pip install tapipy pyyaml
    export TAPIS_USERNAME=<portals-username>
    export TAPIS_PASSWORD=<portals-password>          # or TAPIS_JWT
    export EARTHDATA_USERNAME=<earthdata-username>     # only if --with-netrc
    export EARTHDATA_PASSWORD=<earthdata-password>

    # Validate payloads + staging plan, no API calls that change anything:
    python workflows/smoke_test.py --dry-run

    # Real smoke test of the cheap pipeline only:
    python workflows/smoke_test.py --pipeline h2i \
        --allocation MyAllocation --staging-system cloud.data --with-netrc

    # Run the same app directly through Tapis Jobs, not Workflows:
    python workflows/smoke_test.py --direct-jobs --pipeline h2i \
        --allocation MyAllocation --staging-system cloud.data --with-netrc

    # Both pipelines:
    python workflows/smoke_test.py --pipeline both --allocation MyAllocation

The test data (AOI geometry, date window, worker count, reference mode) mirrors
``workflow_apps/{h2i_lab,werc}/walkthrough.py`` so a green smoke test means the
same inputs that work locally also work through Tapis Workflows.

NOTE: Earthdata credentials are read from the environment, never hardcoded.
The committed walkthrough scripts contain a plaintext password — that is a
secret leak that should be rotated; this script intentionally does not reuse it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from types import SimpleNamespace

# register.py lives next to this file and exposes the auth + tenant helpers.
# Importing it is side-effect free (its work is guarded by __main__).
import register

REPO_ROOT = register.REPO_ROOT  # subside/
PIPELINE_DIR = REPO_ROOT / "tapis" / "workflows" / "pipelines"

# --- Test data, lifted verbatim from the walkthroughs ----------------------
# Houston-Galveston: known subsidence + good DISP-S1 coverage, tiny AOI so the
# download stays small. Keep in sync with workflow_apps/*/walkthrough.py.
AOI_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-95.55, 29.55], [-95.35, 29.55],
                    [-95.35, 29.75], [-95.55, 29.75],
                    [-95.55, 29.55],
                ]],
            },
        }
    ],
}
TEST_DATA = {
    "start_date": "2024-06-01",
    "end_date": "2024-09-01",
    "num_workers": 2,            # walkthrough uses 2; keep the smoke test light
    "min_overlap_percent": 50.0,
    "update_conda_env": "false",
    "reference_mode": "auto",    # werc only
    "reference_lat": "",
    "reference_lon": "",
    "anchor_radius_m": 5000,
    "n_reference_pixels": 25,
    "stac_collection": "subsidence-rates",
    "stac_item_id": "",
    "ckan_url": "https://ckan.tacc.utexas.edu",
    "ckan_org": "tacc-water",
    "ckan_token": "",
    "stac_url": "",
    "stac_token": "",
}

# Pipeline id -> definition file. Both must already be registered (run
# register.py first). Order matters only for display.
PIPELINES = {
    "h2i": "subside-h2i-opera",
    "werc": "subside-werc-opera",
}
PIPELINE_FILES = {
    "h2i": "h2i-opera.yaml",
    "werc": "werc-opera.yaml",
}

# Terminal run/task statuses (compared case-insensitively). Anything not in
# either set means "still going" and we keep polling.
SUCCESS_STATES = {"completed", "success", "succeeded", "finished"}
FAILURE_STATES = {"failed", "error", "terminated", "stopped", "suspended", "cancelled", "canceled"}
_TMPL = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")


def _status_of(obj: Any) -> str:
    """Best-effort status string off a TapisResult-ish object or dict."""
    if isinstance(obj, dict):
        val = obj.get("status")
    else:
        val = getattr(obj, "status", None)
    return str(val or "unknown").lower()


def _probe(client) -> int:
    """List the user's storage systems + the contents of each system root.

    Use this to find a path you can actually write to before running the smoke
    test. Pick a system whose rootDir + a subpath you own, then pass it as
    ``--staging-system <id> --staging-path <subpath>``.
    """
    print("Storage systems you can access (id | host | rootDir | effectiveUser):")
    systems = client.systems.getSystems(
        listType="ALL",
        select="id,systemType,host,rootDir,effectiveUserId,canExec",
        limit=200,
    ) or []
    storage = [s for s in systems if str(getattr(s, "systemType", "")).upper() != "EXECUTION"]
    for s in storage:
        print(f"  {getattr(s,'id','?')} | {getattr(s,'host','?')} | "
              f"rootDir={getattr(s,'rootDir','?')} | "
              f"effectiveUser={getattr(s,'effectiveUserId','?')}")
        # Show the top level so the user can spot a writable subdir.
        for p in ("", f"{client.username}", f"home/{client.username}"):
            try:
                listing = client.files.listFiles(systemId=getattr(s, "id"), path=p or "/", limit=20)
                names = ", ".join(getattr(f, "name", "?") for f in (listing or [])[:20]) or "(empty)"
                print(f"      ls /{p}: {names}")
            except Exception as exc:
                print(f"      ls /{p}: <{type(exc).__name__}: {str(exc)[:80]}>")
    print("\nNext: python workflows/smoke_test.py --pipeline h2i --with-netrc \\")
    print("        --allocation <alloc> --staging-system <id> --staging-path <writable/subpath>")
    return 0


def _stage_inputs(
    client,
    args: argparse.Namespace,
) -> tuple[str, str | None]:
    """Upload the AOI GeoJSON (and optionally a .netrc) to a Tapis system.

    Returns ``(aoi_geojson_uri, earthdata_netrc_uri | None)`` as ``tapis://``
    URIs the pipelines can consume. In ``--dry-run`` mode nothing is uploaded;
    the URIs that *would* be produced are returned so the payload can be shown.
    """
    base = f"{args.staging_path.rstrip('/')}"
    aoi_path = f"{base}/aoi.geojson"
    aoi_uri = f"tapis://{args.staging_system}/{aoi_path}"

    netrc_uri = None
    if args.with_netrc:
        netrc_path = f"{base}/.netrc"
        netrc_uri = f"tapis://{args.staging_system}/{netrc_path}"

    if args.dry_run:
        print(f"[dry-run] would mkdir tapis://{args.staging_system}/{base}")
        print(f"[dry-run] would upload AOI    -> {aoi_uri}")
        if netrc_uri:
            print(f"[dry-run] would upload .netrc -> {netrc_uri} (from $EARTHDATA_*)")
        return aoi_uri, netrc_uri

    import io
    import os

    print(f"[stage]   mkdir  tapis://{args.staging_system}/{base}")
    try:
        client.files.mkdir(systemId=args.staging_system, path=base)
    except Exception as exc:
        raise SystemExit(
            f"\n[error]   mkdir failed on tapis://{args.staging_system}/{base}:\n"
            f"          {type(exc).__name__}: {str(exc)[:200]}\n\n"
            f"          You don't have write access at that path. Run:\n"
            f"              python workflows/smoke_test.py --probe\n"
            f"          to list your systems and a writable subpath, then re-run with\n"
            f"          --staging-system <id> --staging-path <writable/subpath>."
        ) from exc

    print(f"[stage]   upload AOI    -> {aoi_uri}")
    aoi_bytes = json.dumps(AOI_GEOJSON).encode()
    client.files.insert(
        systemId=args.staging_system, path=aoi_path, file=io.BytesIO(aoi_bytes)
    )

    if args.with_netrc:
        user = os.environ.get("EARTHDATA_USERNAME")
        pw = os.environ.get("EARTHDATA_PASSWORD")
        if not (user and pw):
            raise SystemExit(
                "--with-netrc set but EARTHDATA_USERNAME / EARTHDATA_PASSWORD "
                "are not both in the environment."
            )
        netrc = f"machine urs.earthdata.nasa.gov login {user} password {pw}\n"
        print(f"[stage]   upload .netrc -> {netrc_uri}")
        client.files.insert(
            systemId=args.staging_system,
            path=netrc_path,
            file=io.BytesIO(netrc.encode()),
        )

    return aoi_uri, netrc_uri


def _build_args(pipeline_key: str, aoi_uri: str, netrc_uri: str | None, allocation: str) -> dict:
    """Construct the ``args`` body for runPipeline.

    Each value is wrapped as ``{"value": <scalar>}`` — that is the shape the
    Workflows ``/run`` endpoint validates against (NOT a flat key->value map).
    """
    a: dict[str, dict] = {
        "start_date": {"value": TEST_DATA["start_date"]},
        "end_date": {"value": TEST_DATA["end_date"]},
        "aoi_geojson_uri": {"value": aoi_uri},
        "num_workers": {"value": TEST_DATA["num_workers"]},
        "min_overlap_percent": {"value": TEST_DATA["min_overlap_percent"]},
        "allocation": {"value": allocation},
        "update_conda_env": {"value": TEST_DATA["update_conda_env"]},
        "stac_collection": {"value": TEST_DATA["stac_collection"]},
        "stac_item_id": {"value": TEST_DATA["stac_item_id"]},
        "ckan_url": {"value": TEST_DATA["ckan_url"]},
        "ckan_org": {"value": TEST_DATA["ckan_org"]},
        "ckan_token": {"value": TEST_DATA["ckan_token"]},
        "stac_url": {"value": TEST_DATA["stac_url"]},
        "stac_token": {"value": TEST_DATA["stac_token"]},
    }
    a["earthdata_netrc_uri"] = {"value": netrc_uri or ""}
    if pipeline_key == "werc":
        a["reference_mode"] = {"value": TEST_DATA["reference_mode"]}
        a["reference_lat"] = {"value": TEST_DATA["reference_lat"]}
        a["reference_lon"] = {"value": TEST_DATA["reference_lon"]}
        a["anchor_radius_m"] = {"value": TEST_DATA["anchor_radius_m"]}
        a["n_reference_pixels"] = {"value": TEST_DATA["n_reference_pixels"]}
    return a


def _client_token(client) -> str:
    access = getattr(client, "access_token", None)
    return getattr(access, "access_token", None) or (str(access) if access else "")


def _add_workflow_auth_args(run_args: dict[str, dict], client) -> None:
    token = _client_token(client)
    if not token:
        raise SystemExit("Could not resolve a Tapis token for the hosted Workflows run task.")
    run_args["tapis_base_url"] = {"value": register.DEFAULT_BASE_URL}
    run_args["tapis_token"] = {"value": token}


def _redact_run_args(run_args: dict[str, dict]) -> dict[str, dict]:
    redacted = json.loads(json.dumps(run_args, default=str))
    for key in redacted:
        if "token" in key.lower():
            redacted[key] = {"value": "***"}
    return redacted


def _unwrap_args(run_args: dict[str, dict]) -> dict[str, Any]:
    """Convert Workflows-style ``{"key": {"value": x}}`` args to flat values."""
    return {key: value.get("value") if isinstance(value, dict) else value
            for key, value in run_args.items()}


def _resolve(value: Any, ctx: dict[str, Any]) -> Any:
    """Resolve the simple ``{{ args.foo }}`` templates used by run task YAML."""
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            cur: Any = ctx
            for part in match.group(1).split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is None:
                    return ""
            return str(cur)
        return _TMPL.sub(repl, value)
    if isinstance(value, list):
        return [_resolve(item, ctx) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, ctx) for key, item in value.items()}
    return value


def _load_pipeline(pipeline_key: str) -> dict[str, Any]:
    yaml = register._need("yaml")
    path = PIPELINE_DIR / PIPELINE_FILES[pipeline_key]
    with path.open() as f:
        return yaml.safe_load(f)


def _alloc_arg(allocation: str) -> str:
    allocation = allocation.strip()
    return allocation if allocation.startswith("-") else f"-A {allocation}"


def _build_direct_job_body(job_def: dict[str, Any], allocation: str) -> dict[str, Any]:
    """Convert a pipeline ``tapis_job_def`` into a Jobs ``submitJob`` body."""
    body: dict[str, Any] = {
        "name": job_def["name"],
        "appId": job_def["appId"],
        "appVersion": str(job_def["appVersion"]),
    }
    for key in (
        "nodeCount",
        "coresPerNode",
        "memoryMB",
        "maxMinutes",
        "execSystemId",
        "execSystemExecDir",
        "execSystemInputDir",
        "execSystemOutputDir",
        "execSystemLogicalQueue",
        "archiveSystemId",
        "archiveSystemDir",
        "archiveOnAppError",
    ):
        if key in job_def:
            body[key] = job_def[key]

    file_inputs = []
    for file_input in job_def.get("fileInputs", []) or []:
        source_url = str(file_input.get("sourceUrl") or "").strip()
        if not source_url:
            continue
        entry = {"name": file_input["name"], "sourceUrl": source_url}
        if file_input.get("targetPath"):
            entry["targetPath"] = file_input["targetPath"]
        file_inputs.append(entry)
    if file_inputs:
        body["fileInputs"] = file_inputs

    parameter_set = job_def.get("parameterSet", {}) or {}
    out_parameter_set: dict[str, Any] = {}
    env_vars = parameter_set.get("envVariables") or []
    if env_vars:
        out_parameter_set["envVariables"] = [
            {"key": item["key"], "value": str(item.get("value", ""))}
            for item in env_vars
        ]

    scheduler_options = []
    for option in parameter_set.get("schedulerOptions", []) or []:
        if option.get("name") == "TACC Allocation":
            scheduler_options.append({"name": "TACC Allocation", "arg": _alloc_arg(allocation)})
        else:
            scheduler_options.append(option)
    if scheduler_options:
        out_parameter_set["schedulerOptions"] = scheduler_options

    if out_parameter_set:
        body["parameterSet"] = out_parameter_set
    return body


def _workflow_job_def(pipeline_key: str, args: dict[str, Any]) -> dict[str, Any]:
    """Build the same job request the hosted run function submits."""
    app_id = {
        "h2i": "subside-h2i-opera-analysis",
        "werc": "subside-werc-opera-analysis",
    }[pipeline_key]
    max_minutes = 300 if pipeline_key == "werc" else 240
    prefix = "subside-werc-opera" if pipeline_key == "werc" else "subside-h2i-opera"
    env = [
        {"key": "STAGE", "value": "run"},
        {"key": "UPDATE_CONDA_ENV", "value": str(args.get("update_conda_env", "false"))},
        {"key": "START_DATE", "value": str(args.get("start_date", ""))},
        {"key": "END_DATE", "value": str(args.get("end_date", ""))},
        {"key": "NUM_WORKERS", "value": str(args.get("num_workers", 2))},
        {"key": "MIN_OVERLAP_PERCENT", "value": str(args.get("min_overlap_percent", 50.0))},
    ]
    if pipeline_key == "werc":
        env.extend([
            {"key": "REFERENCE_MODE", "value": str(args.get("reference_mode", "auto"))},
            {"key": "REFERENCE_LAT", "value": str(args.get("reference_lat", ""))},
            {"key": "REFERENCE_LON", "value": str(args.get("reference_lon", ""))},
            {"key": "ANCHOR_RADIUS_M", "value": str(args.get("anchor_radius_m", 5000))},
            {"key": "N_REFERENCE_PIXELS", "value": str(args.get("n_reference_pixels", 25))},
        ])

    file_inputs = []
    aoi_uri = str(args.get("aoi_geojson_uri") or "").strip()
    if aoi_uri:
        file_inputs.append({
            "name": "aoi-geojson",
            "sourceUrl": aoi_uri,
            "targetPath": "config/aoi.geojson",
        })
    netrc_uri = str(args.get("earthdata_netrc_uri") or "").strip()
    if netrc_uri:
        file_inputs.append({
            "name": "earthdata-netrc",
            "sourceUrl": netrc_uri,
            "targetPath": ".netrc",
        })

    return {
        "name": f"{prefix}-{args.get('start_date', '')}-{args.get('end_date', '')}",
        "appId": app_id,
        "appVersion": "0.1.1",
        "nodeCount": 1,
        "coresPerNode": 16,
        "memoryMB": 128000,
        "maxMinutes": max_minutes,
        "execSystemId": "ls6",
        "execSystemExecDir": "${JobWorkingDir}",
        "execSystemInputDir": "${JobWorkingDir}",
        "execSystemOutputDir": "${JobWorkingDir}/output",
        "execSystemLogicalQueue": "vm-small",
        "archiveSystemId": "ls6",
        "archiveSystemDir": "HOST_EVAL($WORK)/tapis-jobs-archive/${JobCreateDate}/${JobName}-${JobUUID}",
        "archiveOnAppError": True,
        "fileInputs": file_inputs,
        "parameterSet": {
            "envVariables": env,
            "schedulerOptions": [
                {"name": "TACC Allocation", "arg": _alloc_arg(str(args.get("allocation", "")))},
            ],
        },
    }


def _direct_job_body(pipeline_key: str, run_args: dict[str, dict], allocation: str) -> dict[str, Any]:
    pipeline = _load_pipeline(pipeline_key)
    run_task = next(task for task in pipeline["tasks"] if task["id"] == "run")
    ctx = {"args": _unwrap_args(run_args)}
    if "tapis_job_def" in run_task:
        job_def = _resolve(run_task["tapis_job_def"], ctx)
    else:
        job_def = _workflow_job_def(pipeline_key, ctx["args"])
    return _build_direct_job_body(job_def, allocation)


def _has_template(value: Any) -> bool:
    """Return true if a value still contains our local ``{{ ... }}`` placeholders."""
    if isinstance(value, str):
        return bool(_TMPL.search(value))
    if isinstance(value, list):
        return any(_has_template(item) for item in value)
    if isinstance(value, dict):
        return any(_has_template(item) for item in value.values())
    return False


def _hosted_workflow_supported(pipeline_key: str) -> bool:
    """Hosted Workflows does not render our local Jinja-style Jobs templates."""
    pipeline = _load_pipeline(pipeline_key)
    return not _has_template(pipeline)


def _submit_direct_job(client, body: dict[str, Any]) -> str | None:
    result = client.jobs.submitJob(**body)
    return _field(result, "uuid")


def _poll_direct_job(client, job_uuid: str, args: argparse.Namespace) -> str:
    deadline = time.monotonic() + args.timeout
    last_line = ""
    while True:
        job = client.jobs.getJob(jobUuid=job_uuid)
        status = _status_of(job)
        archive_system = _field(job, "archiveSystemId") or ""
        archive_dir = _field(job, "archiveSystemDir") or ""
        line = f"  job={status}"
        if archive_system or archive_dir:
            line += f" | archive=tapis://{archive_system}/{str(archive_dir).lstrip('/')}"
        if line != last_line:
            print(line)
            last_line = line

        if status in SUCCESS_STATES or status in FAILURE_STATES:
            if status in FAILURE_STATES:
                last_message = _field(job, "lastMessage")
                if last_message:
                    print("  lastMessage:")
                    print("    " + str(last_message).strip().replace("\n", "\n    "))
            return status
        if time.monotonic() > deadline:
            print(f"  [timeout] still '{status}' after {args.timeout}s; giving up polling")
            return f"timeout:{status}"
        time.sleep(args.poll_interval)


def _trigger(client, group_id: str, pipeline_id: str, run_args: dict) -> str | None:
    """Trigger a run; return its uuid (resolved from the response or by diffing
    the run list before/after). Returns None if it can't be resolved."""
    before = set()
    try:
        prior = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        before = {getattr(r, "uuid", None) for r in (prior or [])}
    except Exception:
        pass  # listing may 404 before the first run exists

    result = client.workflows.runPipeline(
        group_id=group_id,
        pipeline_id=pipeline_id,
        name=f"smoke-{pipeline_id}",
        description="Automated smoke test (workflows/smoke_test.py)",
        args=run_args,
    )
    uuid = getattr(result, "uuid", None)
    if uuid:
        return uuid

    # Fall back to diffing the run list — the trigger response may just be an ack.
    for _ in range(10):
        time.sleep(2)
        try:
            now = client.workflows.listPipelineRuns(group_id=group_id, pipeline_id=pipeline_id)
        except Exception:
            continue
        new = {getattr(r, "uuid", None) for r in (now or [])} - before
        new.discard(None)
        if new:
            return sorted(new)[0]
    return None


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _dump_failures(client, group_id: str, pipeline_id: str, run_uuid: str) -> None:
    """Print last_message / stderr / stdout for any non-completed task, plus the
    run-level logs. This is where the *real* reason a tapis_job task died shows up."""
    print(f"\n----- failure detail for run {run_uuid} -----")
    try:
        run = client.workflows.getPipelineRun(
            group_id=group_id, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid
        )
        logs = _field(run, "logs")
        if logs:
            print("[run.logs]")
            print("  " + str(logs).strip().replace("\n", "\n  "))
    except Exception as exc:
        print(f"  (could not fetch run logs: {type(exc).__name__}: {str(exc)[:120]})")

    try:
        execs = client.workflows.listTaskExecutions(
            group_id=group_id, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid
        ) or []
    except Exception as exc:
        print(f"  (could not list task executions: {type(exc).__name__}: {str(exc)[:120]})")
        return

    for e in execs:
        status = _status_of(e)
        if status in SUCCESS_STATES:
            continue
        tid = _field(e, "task_id")
        print(f"\n[task {tid}] status={status}")
        for fld in ("last_message", "stderr", "stdout"):
            val = _field(e, fld)
            if val:
                text = str(val).strip()
                tail = text if len(text) <= 2000 else "...(truncated)...\n" + text[-2000:]
                print(f"  {fld}:")
                print("    " + tail.replace("\n", "\n    "))


def _poll(client, group_id: str, pipeline_id: str, run_uuid: str, args: argparse.Namespace) -> str:
    """Poll a run to a terminal state (or timeout). Returns the final status."""
    deadline = time.monotonic() + args.timeout
    last_line = ""
    while True:
        run = client.workflows.getPipelineRun(
            group_id=group_id, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid
        )
        run_status = _status_of(run)

        try:
            execs = client.workflows.listTaskExecutions(
                group_id=group_id, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid
            ) or []
        except Exception:
            execs = []
        task_bits = " ".join(
            f"{getattr(e, 'task_id', '?')}={_status_of(e)}" for e in execs
        )
        line = f"  run={run_status} | {task_bits}".rstrip()
        if line != last_line:  # only print on change to keep output readable
            print(line)
            last_line = line

        failed_tasks = [e for e in execs if _status_of(e) in FAILURE_STATES]
        if run_status in SUCCESS_STATES or run_status in FAILURE_STATES:
            if run_status in FAILURE_STATES or failed_tasks:
                _dump_failures(client, group_id, pipeline_id, run_uuid)
            if failed_tasks and run_status in SUCCESS_STATES:
                return "failed"
            return run_status
        if time.monotonic() > deadline:
            print(f"  [timeout] still '{run_status}' after {args.timeout}s; giving up polling")
            return f"timeout:{run_status}"
        time.sleep(args.poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipeline", choices=["h2i", "werc", "both"], default="h2i",
                        help="Which pipeline(s) to smoke test. Default: h2i (cheapest).")
    parser.add_argument("--direct-jobs", action="store_true",
                        help="Submit each pipeline's monolithic run task directly through "
                             "Tapis Jobs instead of triggering the Workflows pipeline.")
    parser.add_argument("--allocation", default=None,
                        help="TACC allocation to charge. Required for a live run "
                             "(env: TACC_ALLOCATION / SUBSIDE_DEFAULT_ALLOCATION).")
    parser.add_argument("--staging-system", default="cloud.data",
                        help="Tapis storage system to stage the AOI/.netrc onto "
                             "(env: TAPIS_STAGING_SYSTEM). Default: cloud.data.")
    parser.add_argument("--staging-path", default=None,
                        help="Path on the staging system. Default: <username>/subside-smoke.")
    parser.add_argument("--with-netrc", action="store_true",
                        help="Build a .netrc from $EARTHDATA_USERNAME/$EARTHDATA_PASSWORD, "
                             "upload it, and pass earthdata_netrc_uri.")
    parser.add_argument("--group", default=register.DEFAULT_GROUP, help="Tapis Workflows group id.")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between status polls.")
    parser.add_argument("--timeout", type=int, default=7200, help="Max seconds to poll one run.")
    parser.add_argument("--no-poll", action="store_true", help="Trigger runs and print uuids; don't poll.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the staging plan + run payloads; submit nothing.")
    parser.add_argument("--probe", action="store_true",
                        help="List your storage systems + writable paths and exit. "
                             "Use this to pick --staging-system / --staging-path.")
    parser.add_argument("--describe-run", metavar="UUID", default=None,
                        help="Dump task last_message/stderr/stdout + run logs for an "
                             "existing run uuid and exit. Use with --pipeline to pick which.")
    args = parser.parse_args(argv)

    import os

    # Match orchestrate.py/API behavior: local secrets and defaults live in
    # subside/.env. No-op when python-dotenv is absent.
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass

    register.DEFAULT_BASE_URL = os.environ.get("TAPIS_BASE_URL", register.DEFAULT_BASE_URL)
    register.DEFAULT_GROUP = os.environ.get("SUBSIDE_WORKFLOW_GROUP", register.DEFAULT_GROUP)

    args.allocation = args.allocation or os.environ.get("TACC_ALLOCATION") \
        or os.environ.get("SUBSIDE_DEFAULT_ALLOCATION")
    args.staging_system = os.environ.get("TAPIS_STAGING_SYSTEM", args.staging_system)

    if not args.dry_run and not args.allocation:
        raise SystemExit("A live run needs --allocation (or $TACC_ALLOCATION / $SUBSIDE_DEFAULT_ALLOCATION).")

    selected = ["h2i", "werc"] if args.pipeline == "both" else [args.pipeline]

    if args.dry_run and not (args.probe or args.describe_run):
        client = SimpleNamespace(username=os.environ.get("TAPIS_USERNAME") or os.environ.get("USER") or "user")
        print(f"[dry-run] not authenticating; using username={client.username!r} for staging path defaults")
    else:
        client = register._authenticate()
        print(f"Authenticated against {register.DEFAULT_BASE_URL} as {client.username}")

    if args.probe:
        return _probe(client)

    if args.describe_run:
        if args.pipeline == "both":
            raise SystemExit("--describe-run needs a single --pipeline (h2i or werc).")
        _dump_failures(client, args.group, PIPELINES[args.pipeline], args.describe_run)
        return 0

    if args.staging_path is None:
        # cloud.data has rootDir=/, so the Tapis path is $HOME minus the leading
        # slash: /home/<user> -> home/<user>. Override with --staging-path for
        # other systems / quota-friendly filesystems.
        args.staging_path = f"home/{client.username}/subside-smoke"

    aoi_uri, netrc_uri = _stage_inputs(client, args)

    results: dict[str, str] = {}
    for key in selected:
        pipeline_id = PIPELINES[key]
        run_args = _build_args(key, aoi_uri, netrc_uri, args.allocation or "<allocation>")
        if not args.direct_jobs and not args.dry_run:
            _add_workflow_auth_args(run_args, client)
        print(f"\n=== {pipeline_id}{' direct job' if args.direct_jobs else ''} ===")
        print("args:", json.dumps(_redact_run_args(run_args), indent=2))

        if args.direct_jobs:
            job_body = _direct_job_body(key, run_args, args.allocation or "<allocation>")
            shown_body = json.loads(json.dumps(job_body))
            for file_input in shown_body.get("fileInputs", []):
                if file_input.get("name") == "earthdata-netrc":
                    file_input["sourceUrl"] = "***"
            print("job:", json.dumps(shown_body, indent=2))
            if args.dry_run:
                results[pipeline_id] = "dry-run"
                continue

            print(f"[submit]  jobs.submitJob app={job_body['appId']} version={job_body['appVersion']}")
            job_uuid = _submit_direct_job(client, job_body)
            if not job_uuid:
                print("[error]   could not resolve a job uuid; check the tenant UI.")
                results[pipeline_id] = "submit-failed"
                continue
            print(f"[job]     uuid={job_uuid}")

            if args.no_poll:
                results[pipeline_id] = f"submitted:{job_uuid}"
                continue
            results[pipeline_id] = _poll_direct_job(client, job_uuid, args)
            continue

        if args.dry_run:
            results[pipeline_id] = "dry-run"
            continue

        if not _hosted_workflow_supported(key):
            print(
                "[error]   hosted Workflows cannot run this dynamic pipeline definition: "
                "the run task's tapis_job_def still contains local {{ args.* }} templates, "
                "and the Workflows engine passes those literals through to Tapis Jobs. "
                "Use --direct-jobs for this smoke test, or replace the hosted task with "
                "a static job definition."
            )
            results[pipeline_id] = "unsupported-hosted-template"
            continue

        print(f"[trigger] POST /v3/workflows/groups/{args.group}/pipelines/{pipeline_id}/run")
        run_uuid = _trigger(client, args.group, pipeline_id, run_args)
        if not run_uuid:
            print("[error]   could not resolve a run uuid; check the tenant UI.")
            results[pipeline_id] = "trigger-failed"
            continue
        print(f"[run]     uuid={run_uuid}")

        if args.no_poll:
            results[pipeline_id] = f"submitted:{run_uuid}"
            continue
        results[pipeline_id] = _poll(client, args.group, pipeline_id, run_uuid, args)

    # --- Summary + exit code -------------------------------------------------
    print("\n===== SMOKE TEST SUMMARY =====")
    ok = True
    for pid, status in results.items():
        bare = status.split(":", 1)[0]
        mark = "OK " if bare in SUCCESS_STATES or bare in ("dry-run", "submitted") else "XX "
        if mark == "XX ":
            ok = False
        print(f"  {mark} {pid}: {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
