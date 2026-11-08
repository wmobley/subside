#!/usr/bin/env python3
"""Canary for the Tapis Workflows engine: does it launch tasks right now?

Registers two one-task throwaway pipelines in the group and runs both:

  subside-canary-fn    one ``function`` task that just prints (no job).
  subside-canary-job   one native ``tapis_job`` task (``poll: false``) that
                       submits the public ``hello-world`` app on the ls6
                       ``debug`` queue, 10 min max. Submission alone is the
                       test: it also proves whether the ``workflows``
                       restricted-service delegation works for this user.

Then watches both runs for ``--watch`` seconds. A healthy engine writes the
``[TASK] ... ACTIVE`` log line within seconds and the function task completes
in well under a minute; a stalled engine never writes it (see
diagnose_stalls.py). The pipelines are left registered so the runs can be
inspected or terminated afterwards; ``--cleanup`` deletes them.

Read-only except for the two pipeline registrations and two runs. Auth as
register.py (``TAPIS_JWT`` or ``TAPIS_USERNAME``/``TAPIS_PASSWORD``).

Usage:
    python tapis/workflows/canary.py                      # register + run + watch 180 s
    python tapis/workflows/canary.py --only fn --watch 120
    python tapis/workflows/canary.py --cleanup            # delete the canary pipelines
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import register
from dump_run import _to_jsonable

FN_ID = "subside-canary-fn"
JOB_ID = "subside-canary-job"


def _allocation() -> str:
    alloc = os.environ.get("TACC_ALLOCATION") or os.environ.get("SUBSIDE_DEFAULT_ALLOCATION")
    if not alloc:
        try:
            from dotenv import dotenv_values
            env_file = Path(__file__).resolve().parents[2] / ".env"
            alloc = (dotenv_values(env_file) or {}).get("SUBSIDE_DEFAULT_ALLOCATION")
        except ImportError:
            pass
    if not alloc:
        raise SystemExit("Set TACC_ALLOCATION (or SUBSIDE_DEFAULT_ALLOCATION in subside/.env).")
    return alloc


def _pipelines(allocation: str, n_inputs: int = 0, fetch_url: str = "") -> list[dict]:
    # With --inputs N the function task declares N ``value_from: args`` inputs,
    # like the real pipelines do (h2i's run task has 15). The engine stages each
    # one as a file in the task's NFS work dir before it logs TASK ACTIVE, which
    # is exactly the step the stalled runs never get past.
    fn = {
        "id": f"{FN_ID}-inputs" if n_inputs else FN_ID,
        "type": "workflow",
        "description": f"Engine canary: one function task that prints ({n_inputs} args inputs).",
        "execution_profile": {"max_exec_time": 600},
        "params": {f"canary_arg_{i}": {"type": "string", "required": True} for i in range(n_inputs)},
        "tasks": [{
            "id": "hello",
            "type": "function",
            "runtime": "python:3.11",
            "installer": "pip",
            "input": {
                f"CANARY_ARG_{i}": {"type": "string", "value_from": {"args": f"canary_arg_{i}"}}
                for i in range(n_inputs)
            },
            "code": (
                "from owe_python_sdk.runtime import execution_context as ctx\n"
                f"vals = [ctx.get_input('CANARY_ARG_%d' % i) for i in range({n_inputs})]\n"
                "print('canary ok', len(vals), 'inputs')\n"
                + (
                    # Reachability probe: can the executor reach this URL at all?
                    "import urllib.request, urllib.error, time\n"
                    f"url = {fetch_url!r}\n"
                    "t0 = time.time()\n"
                    "try:\n"
                    "    with urllib.request.urlopen(url, timeout=10) as r:\n"
                    "        print('fetch', url, 'HTTP', r.getcode(), 'in %.2fs' % (time.time()-t0))\n"
                    "except urllib.error.HTTPError as e:\n"
                    "    print('fetch', url, 'HTTP', e.code, 'in %.2fs' % (time.time()-t0))\n"
                    "except Exception as e:\n"
                    "    print('fetch', url, 'FAILED', type(e).__name__, str(e)[:200])\n"
                    if fetch_url else ""
                )
            ),
            "execution_profile": {"max_exec_time": 300},
        }],
    }
    register._encode_function_task_code(fn)
    job = {
        "id": JOB_ID,
        "type": "workflow",
        "description": "Engine canary: one native tapis_job task (submit only).",
        "execution_profile": {"max_exec_time": 600},
        "tasks": [{
            "id": "hello-job",
            "type": "tapis_job",
            "poll": False,
            "execution_profile": {"max_exec_time": 300},
            "tapis_job_def": {
                "name": "subside-canary-hello",
                "appId": "hello-world",
                "appVersion": "frank",
                "execSystemId": "ls6",
                "execSystemLogicalQueue": "debug",
                # The engine's ReqSubmitJob model defaults execSystemInputDir to
                # None and serialises it, which the Jobs API rejects as null, so
                # the dirs must be spelled out.
                "execSystemExecDir": "${JobWorkingDir}",
                "execSystemInputDir": "${JobWorkingDir}",
                "execSystemOutputDir": "${JobWorkingDir}/output",
                "archiveSystemId": "ls6",
                "archiveSystemDir": "HOST_EVAL($WORK)/tapis-jobs-archive/${JobCreateDate}/${JobName}-${JobUUID}",
                "nodeCount": 1,
                "coresPerNode": 1,
                "maxMinutes": 10,
                "parameterSet": {
                    "appArgs": [
                        {"name": "Greeting", "arg": "hello"},
                        {"name": "Target", "arg": "workflows"},
                        {"name": "Sleep Time", "arg": "5"},
                    ],
                    "schedulerOptions": [{"name": "TACC Allocation", "arg": f"-A {allocation}"}],
                },
            },
        }],
    }
    return [fn, job]


def _run(client, group: str, pipeline_id: str, run_args: dict | None = None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result = client.workflows.runPipeline(
        group_id=group, pipeline_id=pipeline_id, name=f"canary-{stamp}", args=run_args or {})
    uuid = getattr(result, "uuid", None) or (result.get("uuid") if isinstance(result, dict) else None)
    if not uuid:
        raise SystemExit(f"runPipeline for {pipeline_id} returned no uuid: {result}")
    return str(uuid)


def _snapshot(client, group: str, pipeline_id: str, run_uuid: str) -> tuple[dict, list[dict]]:
    run = _to_jsonable(client.workflows.getPipelineRun(
        group_id=group, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid))
    execs = [_to_jsonable(e) for e in (client.workflows.listTaskExecutions(
        group_id=group, pipeline_id=pipeline_id, pipeline_run_uuid=run_uuid) or [])]
    return run, execs


def _verdict(run: dict, execs: list[dict]) -> str:
    logs = str(run.get("logs") or "")
    status = str(run.get("status") or "").lower()
    launched = any("[TASK]" in l and " ACTIVE " in l for l in logs.splitlines())
    if status in ("completed",):
        return "LAUNCHED + COMPLETED"
    if status in ("failed", "terminated"):
        return "LAUNCHED + FAILED" if launched else "FAILED BEFORE LAUNCH"
    return "LAUNCHED, still running" if launched else "NOT LAUNCHED (engine stall signature)"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--group", default=register.DEFAULT_GROUP)
    p.add_argument("--only", choices=["fn", "job"], default=None)
    p.add_argument("--inputs", type=int, default=0,
                   help="Give the function task this many value_from:args inputs (0 = none).")
    p.add_argument("--fetch-url", default="",
                   help="Have the function task GET this URL and print the HTTP status "
                        "(proves the Workflows executor can reach e.g. a Tapis pod).")
    p.add_argument("--watch", type=int, default=180, help="Seconds to watch the runs.")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--repeat", type=int, default=1, help="Trigger this many runs of each pipeline.")
    p.add_argument("--no-register", action="store_true",
                   help="Skip (re)registration; the pipelines must already exist.")
    p.add_argument("--cleanup", action="store_true", help="Delete the canary pipelines and exit.")
    args = p.parse_args(argv)

    client = register._authenticate()
    print(f"Authenticated as {client.username}; group={args.group}")

    if args.cleanup:
        for pid in (FN_ID, f"{FN_ID}-inputs", JOB_ID):
            resp = register._api_delete(client, f"/v3/workflows/groups/{args.group}/pipelines/{pid}")
            print(f"[delete]  {pid}: HTTP {resp.status_code}")
        return 0

    wanted = _pipelines(_allocation(), args.inputs, args.fetch_url)
    if args.only:
        wanted = [pl for pl in wanted if pl["id"].startswith(FN_ID if args.only == "fn" else JOB_ID)]
    fn_args = {f"canary_arg_{i}": {"value": f"value-{i}"} for i in range(args.inputs)}

    runs: dict[str, tuple[str, str]] = {}   # label -> (pipeline_id, run_uuid)
    for pl in wanted:
        if not args.no_register:
            register._register_pipeline(client, args.group, pl, dry_run=False, recreate=True)
        for i in range(args.repeat):
            label = pl["id"] if args.repeat == 1 else f"{pl['id']}#{i + 1}"
            run_args = fn_args if pl["id"].startswith(FN_ID) else {}
            runs[label] = (pl["id"], _run(client, args.group, pl["id"], run_args))
            print(f"[run]     {label}  run={runs[label][1]}")

    t0 = time.time()
    final: dict[str, tuple[dict, list[dict]]] = {}
    while True:
        elapsed = int(time.time() - t0)
        print(f"\n--- t+{elapsed}s")
        pending = False
        for label, (pid, ruuid) in runs.items():
            run, execs = _snapshot(client, args.group, pid, ruuid)
            final[label] = (run, execs)
            tasks = ", ".join(f"{e.get('task_id')}={e.get('status')}" for e in execs) or "no executions"
            print(f"{label:24} run={str(run.get('status')).upper():10} {tasks:40} -> {_verdict(run, execs)}")
            if str(run.get("status") or "").lower() not in ("completed", "failed", "terminated"):
                pending = True
        if not pending or elapsed >= args.watch:
            break
        time.sleep(args.interval)

    print("\n" + "=" * 100)
    launched = sum(1 for run, execs in final.values() if not _verdict(run, execs).startswith("NOT"))
    print(f"\nlaunched {launched} of {len(final)} runs")
    for label, (run, execs) in final.items():
        print(f"\n## {label}  run={run.get('uuid')}  status={run.get('status')}  -> {_verdict(run, execs)}")
        for line in str(run.get("logs") or "").strip().splitlines():
            print("   ", line.replace(f"{args.group}.portals.", ""))
        for e in execs:
            print(f"    task {e.get('task_id')} status={e.get('status')} last_message={e.get('last_message')!r}")
            for fld in ("stderr", "stdout"):
                if e.get(fld):
                    print(f"      {fld}: {str(e[fld]).strip()[:800]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
