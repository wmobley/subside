#!/usr/bin/env python3
"""End-to-end client for the locally-running SUBSIDE API (Tapis Workflows path).

Exercises the request-path API the same way the UI does: log in to get a Tapis
token, submit a /runs pipeline run, poll its status, then read results and proxy
one archive file. This is the live counterpart to the static checks — it proves
that runPipeline submission, status mapping, and (crucially) archive resolution
work against the real Workflows service.

Auth (one of):
    export TAPIS_JWT=<token>                  # use an existing token, skip login
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...   # password-grant via /login

Examples::

    # Cheapest sanity check: health + list existing runs, no submission
    python api/test_api_client.py --list-only

    # Submit a cheap h2i run and poll to completion
    python api/test_api_client.py --pipeline h2i \
        --start 2023-01-01 --end 2023-03-01

    # Submit but don't wait (grab the runId, inspect later)
    python api/test_api_client.py --no-poll

    # Inspect an existing run (status -> results -> first file)
    python api/test_api_client.py --run-id <uuid>

This can CONSUME REAL COMPUTE on your TACC allocation once a run is submitted.
Use --no-poll or --list-only to avoid waiting; use --run-id to inspect only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests  (or run with the project .venv)")

TERMINAL = {"completed", "failed", "cancelled"}
DEFAULT_AOI = Path(__file__).resolve().parents[2] / "examples" / "sample_aoi.geojson"


def _die(msg: str, resp: requests.Response | None = None) -> None:
    if resp is not None:
        msg += f"\n  HTTP {resp.status_code}: {resp.text[:600]}"
    sys.exit(f"[FAIL] {msg}")


def _get_token(base: str) -> str:
    jwt = os.environ.get("TAPIS_JWT") or os.environ.get("X_TAPIS_TOKEN")
    if jwt:
        print("[auth]  using TAPIS_JWT from environment")
        return jwt
    user = os.environ.get("TAPIS_USERNAME")
    pw = os.environ.get("TAPIS_PASSWORD")
    if not (user and pw):
        _die("Set TAPIS_JWT, or TAPIS_USERNAME + TAPIS_PASSWORD, to authenticate.")
    print(f"[auth]  password-grant login as {user} via /api/subside/login")
    r = requests.post(f"{base}/api/subside/login", json={"username": user, "password": pw})
    if r.status_code != 200:
        _die("login failed", r)
    return r.json()["token"]


def _load_aoi(path: Path) -> dict:
    if not path.exists():
        _die(f"AOI file not found: {path} (pass --aoi)")
    return json.loads(path.read_text())


def _pretty(label: str, obj) -> None:
    print(f"\n----- {label} -----")
    print(json.dumps(obj, indent=2)[:4000])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("SUBSIDE_API_URL", "http://localhost:8000"))
    ap.add_argument("--pipeline", choices=["h2i", "werc"], default="h2i")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2023-03-01")
    ap.add_argument("--aoi", type=Path, default=DEFAULT_AOI, help="GeoJSON (FeatureCollection/Feature/geometry).")
    ap.add_argument("--allocation", default=None, help="Override SUBSIDE_DEFAULT_ALLOCATION.")
    ap.add_argument("--num-workers", type=int, default=2)
    ap.add_argument("--list-only", action="store_true", help="Health + list runs, then exit (no submit).")
    ap.add_argument("--run-id", default=None, help="Inspect an existing run instead of submitting.")
    ap.add_argument("--no-poll", action="store_true", help="Submit and print runId, but don't wait.")
    ap.add_argument("--poll-interval", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=3600, help="Max seconds to poll.")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    # 1. health (no auth)
    h = requests.get(f"{base}/api/subside/healthz")
    if h.status_code != 200:
        _die("healthz failed — is the API running?", h)
    print(f"[ok]    healthz: {h.json()}")

    token = _get_token(base)
    hdr = {"X-Tapis-Token": token}

    # 2. list runs (proves listPipelineRuns across both pipelines)
    lr = requests.get(f"{base}/api/subside/runs", headers=hdr)
    if lr.status_code != 200:
        _die("list runs failed", lr)
    runs = lr.json().get("runs", [])
    print(f"[ok]    list runs: {len(runs)} run(s) across configured pipelines")
    for r in runs[:5]:
        print(f"          {r.get('runId')}  {r.get('pipeline'):<5} {r.get('status'):<10} {r.get('created')}")
    if args.list_only:
        return

    # 3. acquire a run_id — either submit, or use the one passed in
    if args.run_id:
        run_id = args.run_id
        print(f"[info]  inspecting existing run {run_id}")
    else:
        body = {
            "pipeline": args.pipeline,
            "start_date": args.start,
            "end_date": args.end,
            "aoi_geojson": _load_aoi(args.aoi),
            "num_workers": args.num_workers,
        }
        if args.allocation:
            body["allocation"] = args.allocation
        print(f"[submit] {args.pipeline}  {args.start}..{args.end}")
        sr = requests.post(f"{base}/api/subside/runs", headers=hdr, json=body)
        if sr.status_code != 200:
            _die("submit failed", sr)
        info = sr.json()
        _pretty("submit response", info)
        run_id = info["runId"]
        print(f"[ok]    submitted -> runId={run_id} (pipeline={info.get('pipelineId')}, group={info.get('groupId')})")
        if args.no_poll:
            print(f"\nInspect later with:  python api/test_api_client.py --run-id {run_id}")
            return

    # 4. poll status to terminal (proves status mapping + task summaries)
    deadline = time.monotonic() + args.timeout
    status = None
    while time.monotonic() < deadline:
        sr = requests.get(f"{base}/api/subside/runs/{run_id}", headers=hdr)
        if sr.status_code != 200:
            _die("status failed", sr)
        st = sr.json()
        status = st.get("status")
        tasks = ", ".join(f"{t.get('taskId')}={t.get('status')}" for t in st.get("tasks", [])) or "—"
        print(f"[poll]  status={status:<10} tapis={st.get('tapisStatus'):<12} tasks: {tasks}")
        if status in TERMINAL:
            _pretty("final status", st)
            break
        time.sleep(args.poll_interval)
    else:
        print(f"[warn]  still '{status}' after {args.timeout}s — stopping poll (run continues server-side)")
        return

    if status != "completed":
        print(f"[done]  run ended '{status}'. lastMessage:\n{ (sr.json().get('lastMessage') or '')[:1500] }")
        return

    # 5. results (proves archive resolution + manifest/artifact listing)
    rr = requests.get(f"{base}/api/subside/runs/{run_id}/results", headers=hdr)
    if rr.status_code != 200:
        _die("results failed", rr)
    res = rr.json()
    arts = res.get("artifacts", [])
    print(f"[ok]    results: manifest={'yes' if res.get('manifest') else 'no'}, {len(arts)} artifact(s)")
    for a in arts[:10]:
        print(f"          {a.get('sizeBytes')!s:>10}  {a.get('path')}")
    if not arts:
        print("[warn]  no artifacts — archive may not have resolved. Check status.archive above.")
        return

    # 6. proxy one file (proves the /file path-scoping + streaming)
    target = arts[0]["path"]
    fr = requests.get(f"{base}/api/subside/runs/{run_id}/file", headers=hdr, params={"path": target})
    if fr.status_code != 200:
        _die(f"file proxy failed for {target}", fr)
    print(f"[ok]    fetched {target}: {len(fr.content)} bytes, content-type={fr.headers.get('content-type')}")
    print("\n[PASS] full request-path round-trip succeeded.")


if __name__ == "__main__":
    main()
