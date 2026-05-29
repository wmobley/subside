"""Client-side orchestrator ("manager") for the SUBSIDE pipelines.

This is the workaround for the Tapis Workflows restricted-service block: the
`workflows` service is not authorized to submit Jobs on behalf of `wmobley` in
the `portals` tenant, but YOU are. So instead of letting the Workflows engine
drive the pipeline, this script reads the same pipeline YAML and drives it
itself against the Jobs + Files APIs, which use your identity directly.

    you -> [this manager] -> Jobs service (submits as you)  ✅
                          -> Files service (reads archives) ✅

It is the precursor to a longer-lived "manager" service. Design choices:

* Heavy artifacts (the NetCDF stack) are passed between steps by **archive
  URI** — captured from each finished job's archiveSystemDir and templated into
  the next job's fileInputs. Bulk data never round-trips through the manager.
* Small JSON (manifests/summaries) ARE pulled back, for control-flow decisions
  ("did discover find products?") and to run `publish` locally.
* The `publish` function task runs here, in the manager. Because the manager
  has Tapis creds, it can fetch `tapis://` archive files via the Files API —
  which fixes the inline-code `urllib` placeholder the pipeline left as a TODO.

Usage::

    pip install tapipy pyyaml
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...        # or TAPIS_JWT
    export EARTHDATA_USERNAME=... EARTHDATA_PASSWORD=... # only with --with-netrc

    # Validate the plan + job payloads, submit nothing:
    python workflows/orchestrate.py --pipeline h2i --allocation PT2050-DataX --dry-run

    # Run it for real:
    python workflows/orchestrate.py --pipeline h2i --allocation PT2050-DataX --with-netrc

Test data (AOI, dates, workers, reference mode) is reused from smoke_test.py,
which mirrors workflow_apps/*/walkthrough.py.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import register
import smoke_test

REPO_ROOT = register.REPO_ROOT
PIPELINE_DIR = REPO_ROOT / "workflows" / "pipelines"
LOCAL_OUT = REPO_ROOT / "workflows" / "orchestrate_outputs"

# Tapis Jobs terminal statuses.
JOB_SUCCESS = {"FINISHED"}
JOB_FAILURE = {"FAILED", "CANCELLED"}

_TMPL = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-]+)\s*\}\}")


# --------------------------------------------------------------------------- #
# Templating: resolve {{ args.X }}, {{ workflow.inline_files.X }},             #
# {{ tasks.<id>.outputs.archive }} against a context dict.                     #
# --------------------------------------------------------------------------- #
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


def _parse_tapis_uri(uri: str) -> tuple[str, str]:
    """tapis://<system>/<path>  ->  (system, path)."""
    rest = uri[len("tapis://"):]
    system, _, path = rest.partition("/")
    return system, path


def _alloc_arg(allocation: str) -> str:
    """TACC SLURM wants the allocation as an account directive. The pipeline
    passed it bare; normalize to '-A <alloc>' unless the caller already did."""
    allocation = allocation.strip()
    return allocation if allocation.startswith("-") else f"-A {allocation}"


# --------------------------------------------------------------------------- #
# Input staging                                                               #
# --------------------------------------------------------------------------- #
def _build_run_config(pipeline_key: str) -> dict:
    """The run-config.json the app's CLI consumes.

    Paths are relative to the job working dir, matching the app's fileInput
    targetPaths (aoi mounts at config/aoi.geojson, outputs go to output/).
    h2i uses H2IRunConfig fields; werc adds the reference/anchor fields on top
    (WercRunConfig.from_dict accepts the flat h2i fields + werc fields)."""
    cfg = {
        "start_date": smoke_test.TEST_DATA["start_date"],
        "end_date": smoke_test.TEST_DATA["end_date"],
        "aoi_geojson_path": "config/aoi.geojson",
        "num_workers": smoke_test.TEST_DATA["num_workers"],
        "min_overlap_percent": smoke_test.TEST_DATA["min_overlap_percent"],
        "output_dir": "output",
        "results_dir": "OPERA_L3_DISP-S1",
        "require_products": True,
        "preview_only": False,
    }
    if pipeline_key == "werc":
        cfg.update({
            "reference_mode": smoke_test.TEST_DATA["reference_mode"],
            "anchor_radius_m": 5000,
            "n_reference_pixels": 25,
            "anchor_dir": "output/anchors",
            "skip_download": False,
        })
    return cfg


def _stage(client, args: argparse.Namespace) -> dict:
    """Upload run-config.json, AOI, and (optionally) .netrc. Returns the
    template context's `args` URIs + the inline run_config_uri."""
    import os

    base = args.staging_path.rstrip("/")
    uris = {
        "run_config_uri": f"tapis://{args.staging_system}/{base}/run-config.json",
        "aoi_geojson_uri": f"tapis://{args.staging_system}/{base}/aoi.geojson",
        "earthdata_netrc_uri": "",
    }
    run_config = _build_run_config(args.pipeline)

    if args.dry_run:
        print(f"[dry-run] would mkdir tapis://{args.staging_system}/{base}")
        print(f"[dry-run] run-config.json:\n{json.dumps(run_config, indent=2)}")
        print(f"[dry-run] AOI    -> {uris['aoi_geojson_uri']}")
        print(f"[dry-run] config -> {uris['run_config_uri']}")
        if args.with_netrc:
            uris["earthdata_netrc_uri"] = f"tapis://{args.staging_system}/{base}/.netrc"
            print(f"[dry-run] .netrc -> {uris['earthdata_netrc_uri']} (from $EARTHDATA_*)")
        return uris

    print(f"[stage]   mkdir tapis://{args.staging_system}/{base}")
    try:
        client.files.mkdir(systemId=args.staging_system, path=base)
    except Exception as exc:
        raise SystemExit(
            f"[error] mkdir failed on tapis://{args.staging_system}/{base}: "
            f"{type(exc).__name__}: {str(exc)[:160]}\n"
            f"        Run: python workflows/smoke_test.py --probe  to find a writable path."
        ) from exc

    print(f"[stage]   upload run-config.json -> {uris['run_config_uri']}")
    client.files.insert(systemId=args.staging_system, path=f"{base}/run-config.json",
                        file=io.BytesIO(json.dumps(run_config).encode()))
    print(f"[stage]   upload AOI            -> {uris['aoi_geojson_uri']}")
    client.files.insert(systemId=args.staging_system, path=f"{base}/aoi.geojson",
                        file=io.BytesIO(json.dumps(smoke_test.AOI_GEOJSON).encode()))

    if args.with_netrc:
        user = os.environ.get("EARTHDATA_USERNAME")
        pw = os.environ.get("EARTHDATA_PASSWORD")
        if not (user and pw):
            raise SystemExit("--with-netrc needs EARTHDATA_USERNAME + EARTHDATA_PASSWORD in the env.")
        netrc = f"machine urs.earthdata.nasa.gov login {user} password {pw}\n"
        uris["earthdata_netrc_uri"] = f"tapis://{args.staging_system}/{base}/.netrc"
        print(f"[stage]   upload .netrc         -> {uris['earthdata_netrc_uri']}")
        client.files.insert(systemId=args.staging_system, path=f"{base}/.netrc",
                            file=io.BytesIO(netrc.encode()))
    return uris


# --------------------------------------------------------------------------- #
# Task ordering + job submission                                              #
# --------------------------------------------------------------------------- #
def _ordered_tasks(tasks: list[dict]) -> list[dict]:
    """Topologically order tasks by their depends_on edges."""
    by_id = {t["id"]: t for t in tasks}
    done: list[str] = []
    out: list[dict] = []
    remaining = list(by_id)
    while remaining:
        progressed = False
        for tid in list(remaining):
            deps = [d["id"] for d in (by_id[tid].get("depends_on") or [])]
            if all(d in done for d in deps):
                out.append(by_id[tid]); done.append(tid); remaining.remove(tid)
                progressed = True
        if not progressed:
            raise SystemExit(f"Dependency cycle or missing dep among: {remaining}")
    return out


def _build_job_body(job_def: dict, allocation: str, update_conda_env: str) -> dict:
    """Turn a resolved tapis_job_def into a Tapis Jobs submit body.

    Exec system / queue / archive / appArgs come from the registered app, so we
    only send the per-task overrides + inputs + parameterSet the pipeline set."""
    body: dict[str, Any] = {
        "name": job_def["name"],
        "appId": job_def["appId"],
        "appVersion": str(job_def["appVersion"]),
    }
    for k in ("nodeCount", "coresPerNode", "memoryMB", "maxMinutes"):
        if k in job_def:
            body[k] = job_def[k]

    # fileInputs: drop any whose sourceUrl resolved empty (e.g. no .netrc).
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
    out_pset: dict[str, Any] = {}
    if pset.get("envVariables"):
        out_pset["envVariables"] = [{"key": e["key"], "value": str(e.get("value", ""))}
                                    for e in pset["envVariables"]]
    # Replace the templated "TACC Allocation" arg with a real SLURM directive.
    sched = []
    for so in pset.get("schedulerOptions", []):
        if so.get("name") == "TACC Allocation":
            sched.append({"name": "TACC Allocation", "arg": _alloc_arg(allocation)})
        else:
            sched.append(so)
    if sched:
        out_pset["schedulerOptions"] = sched
    if out_pset:
        body["parameterSet"] = out_pset
    return body


def _job_status(client, uuid: str) -> str:
    st = client.jobs.getJobStatus(jobUuid=uuid)
    return str(smoke_test._field(st, "status") or "UNKNOWN")


def _job_archive_uri(client, uuid: str) -> str | None:
    job = client.jobs.getJob(jobUuid=uuid)
    sys_id = smoke_test._field(job, "archiveSystemId")
    sys_dir = smoke_test._field(job, "archiveSystemDir")
    if sys_id and sys_dir:
        return f"tapis://{sys_id}/{sys_dir.lstrip('/')}"
    return None


def _run_job(client, task: dict, ctx: dict, args: argparse.Namespace) -> str:
    """Submit one tapis_job task, poll to terminal, record its archive URI."""
    job_def = _resolve(task["tapis_job_def"], ctx)
    body = _build_job_body(job_def, args.allocation, args.update_conda_env)

    print(f"\n=== task {task['id']} (tapis_job) ===")
    print(json.dumps(body, indent=2))
    if args.dry_run:
        ctx["tasks"][task["id"]] = {"outputs": {"archive": f"tapis://<archive-of-{task['id']}>"}}
        return "dry-run"

    res = client.jobs.submitJob(**body)
    uuid = smoke_test._field(res, "uuid")
    print(f"[job]     submitted uuid={uuid}")

    deadline = time.monotonic() + args.timeout
    last = ""
    while True:
        status = _job_status(client, uuid)
        if status != last:
            print(f"  {task['id']}: {status}")
            last = status
        if status in JOB_SUCCESS:
            uri = _job_archive_uri(client, uuid)
            ctx["tasks"][task["id"]] = {"outputs": {"archive": uri}, "uuid": uuid}
            print(f"  {task['id']}: archive -> {uri}")
            return status
        if status in JOB_FAILURE:
            job = client.jobs.getJob(jobUuid=uuid)
            print(f"  {task['id']}: FAILED — {smoke_test._field(job, 'lastMessage')}")
            return status
        if time.monotonic() > deadline:
            print(f"  {task['id']}: [timeout] still {status} after {args.timeout}s")
            return f"timeout:{status}"
        time.sleep(args.poll_interval)


# --------------------------------------------------------------------------- #
# publish (function task) — run locally, fetch tapis:// via the Files API      #
# --------------------------------------------------------------------------- #
def _fetch_json(client, uri: str) -> dict | None:
    """Download + parse a JSON file at a tapis:// URI. Falls back to searching
    the archive by basename if the exact path 404s (archive layout varies)."""
    system, path = _parse_tapis_uri(uri)
    try:
        raw = client.files.getContents(systemId=system, path=path)
        return json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
    except Exception:
        # Search the archive root for a file with this basename.
        base_dir = "/".join(path.split("/")[:-3]) or "/"  # strip /output/<file>
        want = path.split("/")[-1]
        try:
            listing = client.files.listFiles(systemId=system, path=base_dir, recurse=True, limit=1000)
            for f in listing or []:
                fpath = smoke_test._field(f, "path") or ""
                if fpath.endswith("/" + want) or fpath.endswith(want):
                    raw = client.files.getContents(systemId=system, path=fpath)
                    return json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception as exc:
            print(f"  [publish] could not fetch {want}: {type(exc).__name__}: {str(exc)[:120]}")
    return None


def _run_publish(client, task: dict, ctx: dict, args: argparse.Namespace) -> str:
    print(f"\n=== task {task['id']} (function/local) ===")
    inputs = _resolve(task.get("inputs", {}) or {}, ctx)
    print("resolved inputs:", json.dumps(inputs, indent=2))
    if args.dry_run:
        return "dry-run"

    fetched = {key: _fetch_json(client, uri) for key, uri in inputs.items()}

    werc_manifest = fetched.get("werc_run_manifest_uri")
    if werc_manifest is not None:
        # werc's run job already wrote a unified manifest; just re-stamp it.
        unified = {"pipeline": ctx["pipeline_id"], "schema_version": "v0", **werc_manifest}
    else:
        preflight = fetched.get("preflight_manifest_uri") or {}
        run_manifest = fetched.get("run_manifest_uri") or fetched.get("h2i_run_manifest_uri") or {}
        unified = {
            "pipeline": ctx["pipeline_id"],
            "schema_version": "v0",
            "frame_ids": preflight.get("frame_ids", []),
            "product_count": preflight.get("product_count", 0),
            "warnings": list(preflight.get("warnings", [])) + list(run_manifest.get("warnings", [])),
            "artifacts": run_manifest.get("artifacts", {}),
            "config": run_manifest.get("config", {}),
        }
    unified["inputs_fetched"] = {k: (v is not None) for k, v in fetched.items()}
    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    out_file = LOCAL_OUT / f"{ctx['pipeline_id']}-run-manifest.json"
    out_file.write_text(json.dumps(unified, indent=2, sort_keys=True, default=str))
    print(f"[publish] wrote {out_file}")
    print(json.dumps(unified, indent=2, default=str))
    return "FINISHED" if any(v is not None for v in fetched.values()) else "FAILED"


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pipeline", choices=["h2i", "werc"], default="h2i")
    p.add_argument("--allocation", default=None, help="TACC allocation (env: TACC_ALLOCATION).")
    p.add_argument("--staging-system", default="cloud.data")
    p.add_argument("--staging-path", default=None, help="Default: home/<user>/subside-smoke.")
    p.add_argument("--with-netrc", action="store_true")
    p.add_argument("--update-conda-env", default="false")
    p.add_argument("--group", default=register.DEFAULT_GROUP)
    p.add_argument("--poll-interval", type=int, default=30)
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    import os
    args.allocation = args.allocation or os.environ.get("TACC_ALLOCATION")
    args.staging_system = os.environ.get("TAPIS_STAGING_SYSTEM", args.staging_system)
    if not args.allocation:
        raise SystemExit("Need --allocation (or $TACC_ALLOCATION).")

    pipeline_file = PIPELINE_DIR / f"{'h2i-opera' if args.pipeline == 'h2i' else 'werc-opera'}.yaml"
    pipeline = register._load_pipeline(pipeline_file)
    pipeline_id = pipeline["id"]

    client = register._authenticate()
    print(f"Authenticated against {register.DEFAULT_BASE_URL} as {client.username}")
    if args.staging_path is None:
        args.staging_path = f"home/{client.username}/subside-smoke"

    staged = _stage(client, args)

    # Template context. args.* mirrors the pipeline params; we fill the ones the
    # job defs reference (defaults from the param block otherwise).
    ctx: dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "args": {
            "start_date": smoke_test.TEST_DATA["start_date"],
            "end_date": smoke_test.TEST_DATA["end_date"],
            "aoi_geojson_uri": staged["aoi_geojson_uri"],
            "earthdata_netrc_uri": staged["earthdata_netrc_uri"],
            "num_workers": smoke_test.TEST_DATA["num_workers"],
            "min_overlap_percent": smoke_test.TEST_DATA["min_overlap_percent"],
            "reference_mode": smoke_test.TEST_DATA["reference_mode"],
            "anchor_radius_m": 5000,
            "n_reference_pixels": 25,
            "reference_lat": "",
            "reference_lon": "",
            "allocation": args.allocation,
            "update_conda_env": args.update_conda_env,
        },
        "workflow": {"inline_files": {"run_config_uri": staged["run_config_uri"]}},
        "tasks": {},
    }

    results: dict[str, str] = {}
    for task in _ordered_tasks(pipeline["tasks"]):
        if task["type"] == "tapis_job":
            status = _run_job(client, task, ctx, args)
        elif task["type"] == "function":
            status = _run_publish(client, task, ctx, args)
        else:
            status = f"skipped:{task['type']}"
        results[task["id"]] = status
        # Stop the chain on a real failure (don't submit downstream jobs).
        bare = status.split(":", 1)[0]
        if bare not in JOB_SUCCESS and bare not in ("dry-run", "FINISHED"):
            print(f"\n[stop] {task['id']} ended '{status}'; skipping downstream tasks.")
            break

    print("\n===== ORCHESTRATION SUMMARY =====")
    ok = True
    for tid, status in results.items():
        bare = status.split(":", 1)[0]
        good = bare in JOB_SUCCESS or bare in ("dry-run", "FINISHED")
        ok = ok and good
        print(f"  {'OK ' if good else 'XX '} {tid}: {status}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
