"""Live smoke test for the SUBSIDE Tapis Workflows pipelines.

Triggers each registered pipeline against ``portals.tapis.io`` with the
Houston-Galveston test data from the local walkthroughs, then polls the run
until it reaches a terminal state, printing per-task status as it goes.

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
import sys
import time
from pathlib import Path
from typing import Any

# register.py lives next to this file and exposes the auth + tenant helpers.
# Importing it is side-effect free (its work is guarded by __main__).
import register

REPO_ROOT = register.REPO_ROOT  # subside/
PIPELINE_DIR = REPO_ROOT / "workflows" / "pipelines"

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
    "reference_mode": "auto",    # werc only
}

# Pipeline id -> definition file. Both must already be registered (run
# register.py first). Order matters only for display.
PIPELINES = {
    "h2i": "subside-h2i-opera",
    "werc": "subside-werc-opera",
}

# Terminal run/task statuses (compared case-insensitively). Anything not in
# either set means "still going" and we keep polling.
SUCCESS_STATES = {"completed", "success", "succeeded"}
FAILURE_STATES = {"failed", "error", "terminated", "stopped", "suspended"}


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
    }
    if netrc_uri:
        a["earthdata_netrc_uri"] = {"value": netrc_uri}
    if pipeline_key == "werc":
        a["reference_mode"] = {"value": TEST_DATA["reference_mode"]}
    return a


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

        if run_status in SUCCESS_STATES or run_status in FAILURE_STATES:
            if run_status in FAILURE_STATES:
                _dump_failures(client, group_id, pipeline_id, run_uuid)
            return run_status
        if time.monotonic() > deadline:
            print(f"  [timeout] still '{run_status}' after {args.timeout}s; giving up polling")
            return f"timeout:{run_status}"
        time.sleep(args.poll_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipeline", choices=["h2i", "werc", "both"], default="h2i",
                        help="Which pipeline(s) to smoke test. Default: h2i (cheapest).")
    parser.add_argument("--allocation", default=None,
                        help="TACC allocation to charge. Required for a live run "
                             "(env: TACC_ALLOCATION).")
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
    args.allocation = args.allocation or os.environ.get("TACC_ALLOCATION")
    args.staging_system = os.environ.get("TAPIS_STAGING_SYSTEM", args.staging_system)

    if not args.dry_run and not args.allocation:
        raise SystemExit("A live run needs --allocation (or $TACC_ALLOCATION).")

    selected = ["h2i", "werc"] if args.pipeline == "both" else [args.pipeline]

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
        print(f"\n=== {pipeline_id} ===")
        print("args:", json.dumps(run_args, indent=2))

        if args.dry_run:
            results[pipeline_id] = "dry-run"
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
