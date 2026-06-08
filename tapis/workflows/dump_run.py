#!/usr/bin/env python3
"""Dump EVERYTHING about a Tapis Workflows pipeline run (for sharing with devs).

Pulls the full pipeline-run object, every task execution (untruncated
last_message / stderr / stdout), and the run logs, and writes them as JSON +
a readable text report. Use this to attach to a ticket / hand to the Tapis devs.

Usage (same env as smoke_test.py / orchestrate.py):
    python tapis/workflows/dump_run.py <run-uuid> [--pipeline h2i|werc] [--group subside-ops]

Example (the RestrictedService failure):
    python tapis/workflows/dump_run.py f94c740f-21b7-41f5-9755-323ed7bc03d4
"""

from __future__ import annotations

import argparse
import json
import sys

import register
import smoke_test


def _to_jsonable(obj):
    """Recursively turn a tapipy result (or anything) into JSON-able data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    d = getattr(obj, "__dict__", None)
    if d:
        return {k: _to_jsonable(v) for k, v in d.items() if not k.startswith("_")}
    return str(obj)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("uuid")
    p.add_argument("--pipeline", choices=["h2i", "werc"], default="h2i")
    p.add_argument("--group", default=register.DEFAULT_GROUP)
    p.add_argument("--out", default=None, help="JSON output path (default: run-<uuid>.json next to cwd)")
    args = p.parse_args(argv)

    pipeline_id = smoke_test.PIPELINES[args.pipeline]
    client = register._authenticate()
    print(f"Authenticated as {client.username}; group={args.group} pipeline={pipeline_id} run={args.uuid}\n")

    bundle: dict = {"group": args.group, "pipeline_id": pipeline_id, "run_uuid": args.uuid}

    # 1. the run object (+ logs)
    try:
        run = client.workflows.getPipelineRun(
            group_id=args.group, pipeline_id=pipeline_id, pipeline_run_uuid=args.uuid)
        bundle["run"] = _to_jsonable(run)
    except Exception as exc:
        bundle["run_error"] = f"{type(exc).__name__}: {exc}"

    # 2. every task execution, full detail
    try:
        execs = client.workflows.listTaskExecutions(
            group_id=args.group, pipeline_id=pipeline_id, pipeline_run_uuid=args.uuid) or []
        bundle["task_executions"] = [_to_jsonable(e) for e in execs]
    except Exception as exc:
        bundle["task_executions_error"] = f"{type(exc).__name__}: {exc}"
        execs = []

    out = args.out or f"run-{args.uuid}.json"
    with open(out, "w") as f:
        json.dump(bundle, f, indent=2, default=str)

    # --- readable report to stdout ---
    print("=" * 80)
    run_logs = (bundle.get("run") or {}).get("logs")
    if run_logs:
        print("[run.logs]\n" + str(run_logs).strip())
    for e in bundle.get("task_executions", []):
        print("\n" + "-" * 80)
        print(f"[task {e.get('task_id')}] status={e.get('status')} uuid={e.get('uuid')}")
        for fld in ("last_message", "stdout", "stderr"):
            val = e.get(fld)
            if val:
                print(f"\n  --- {fld} ---")
                print("  " + str(val).strip().replace("\n", "\n  "))
    print("\n" + "=" * 80)
    print(f"Full JSON written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
