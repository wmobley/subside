#!/usr/bin/env python3
"""Diagnose Tapis Workflows runs that hang at app-job submission.

Walks every Workflows group the caller belongs to (or ``--group``), every
pipeline in it, and every run started in the last ``--hours``; pulls the run
logs + task executions and classifies each run:

  ENGINE_STALL   a task execution is active/pending but the pipeline log never
                 got a ``[TASK] ... ACTIVE`` line for it. The engine never
                 launched the task container, so none of the pipeline code ran
                 and no Tapis job exists. (Signature first seen 2026-10-28 /
                 2026-11-02; Tapis-side, report to the Workflows team.)
  TASK_RUNNING   the engine launched the task and its code is submitting or
                 polling a Tapis job. Healthy while the HPC queue is slow.
  NOT_CONSUMED   run is SUBMITTED with no task executions: the API queued it
                 but no engine worker has picked it up (seen 2026-11-03 after
                 the engine stopped consuming entirely).
  DONE / FAILED  terminal runs, kept in the table to bracket *when* launches
                 stopped working (look at the ``launch`` column: seconds from
                 run start to first task ACTIVE line, or ``never``).

It also lists the caller's recent Tapis jobs so each run can be matched to a
job -- or shown to have none.

Read-only. Auth is the same as smoke_test.py: ``TAPIS_JWT``, or
``TAPIS_USERNAME`` + ``TAPIS_PASSWORD``. Base URL from ``TAPIS_BASE_URL``.

Usage:
    python tapis/workflows/diagnose_stalls.py                       # all groups, last 7 days
    python tapis/workflows/diagnose_stalls.py --group adapter-ops --hours 72
    python tapis/workflows/diagnose_stalls.py --active-only --verbose
    python tapis/workflows/diagnose_stalls.py --json stalls.json    # full bundle for a ticket
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

import register
from dump_run import _to_jsonable

TERMINAL = {"COMPLETED", "FAILED", "TERMINATED", "SUSPENDED", "ARCHIVED"}
ACTIVE_TASK = {"active", "pending", "staging", "submitted"}


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _get(session: requests.Session, base: str, path: str, **params):
    r = session.get(f"{base}{path}", params=params or None, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"GET {path} -> HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    return body.get("result", body)


def _ts(value) -> datetime | None:
    """Parse the ISO timestamps Workflows/Jobs return (naive or with offset)."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age(dt: datetime | None, now: datetime) -> str:
    if not dt:
        return "?"
    secs = int((now - dt).total_seconds())
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60}m"
    return f"{secs / 3600:.1f}h"


_TASK_LINE = re.compile(r"\[TASK\][^\n]*", re.IGNORECASE)
_LOG_TS = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)")


def _first_task_active(logs: str, task_id: str | None = None) -> tuple[bool, datetime | None, str]:
    """Return (seen, timestamp, line) for the first ``[TASK] ... ACTIVE`` log line.

    A healthy run writes this within a few seconds of starting; a run the
    engine never launched has no such line for the task at all.
    """
    for m in _TASK_LINE.finditer(logs or ""):
        line = m.group(0)
        if "ACTIVE" not in line.upper():
            continue
        if task_id and task_id not in line:
            continue
        ts = _LOG_TS.search(line)
        return True, _ts(ts.group(1)) if ts else None, line.strip()
    return False, None, ""


def _classify(run: dict, execs: list[dict]) -> tuple[str, str]:
    """Return (classification, detail) for one run."""
    status = str(run.get("status") or "").upper()
    logs = str(run.get("logs") or "")
    if status in TERMINAL:
        label = "DONE" if status == "COMPLETED" else status
        return label, ""
    live = [e for e in execs if str(e.get("status") or "").lower() in ACTIVE_TASK]
    if not live:
        if not execs:
            # The API accepted the run but no engine worker has consumed it from
            # the broker yet (healthy engines do this within seconds).
            return "NOT_CONSUMED", "run SUBMITTED; engine never picked it up (no task executions)"
        return status or "UNKNOWN", "no active task executions"
    stalled, running = [], []
    for e in live:
        tid = str(e.get("task_id") or "")
        seen, _, _ = _first_task_active(logs, tid)
        (running if seen else stalled).append(tid)
    if stalled:
        return "ENGINE_STALL", f"task(s) never launched by engine: {', '.join(stalled)}"
    return "TASK_RUNNING", f"task(s) executing: {', '.join(running)}"


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--group", action="append", default=None,
                   help="Workflows group id (repeatable). Default: every group you belong to.")
    p.add_argument("--hours", type=float, default=168,
                   help="Only runs started within this many hours (default 168 = 7 days).")
    p.add_argument("--active-only", action="store_true", help="Skip terminal runs.")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Print log tail + task execution detail for every non-terminal run.")
    p.add_argument("--jobs", type=int, default=100,
                   help="How many recent Tapis jobs to pull for correlation (0 = skip).")
    p.add_argument("--json", default=None, help="Write the full raw bundle here.")
    args = p.parse_args(argv)

    base = register.DEFAULT_BASE_URL.rstrip("/")
    client = register._authenticate()
    session = requests.Session()
    session.headers.update(register._auth_headers(client))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)
    username = getattr(client, "username", None) or "?"
    print(f"Authenticated as {username} @ {base}; runs since {since:%Y-%m-%d %H:%M}Z\n")

    # --- groups ------------------------------------------------------------
    if args.group:
        groups = args.group
    else:
        groups = [str(g.get("id")) for g in _get(session, base, "/v3/workflows/groups") or []]
    if not groups:
        print("No Workflows groups visible to this user.")
        return 1
    print(f"groups: {', '.join(groups)}")

    # --- recent Tapis jobs (for correlation) --------------------------------
    jobs: list[dict] = []
    if args.jobs:
        try:
            jobs = _get(session, base, "/v3/jobs/list", limit=args.jobs,
                        orderBy="created(desc)", computeTotal="false") or []
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not list jobs: {exc}", file=sys.stderr)
    jobs_recent = [j for j in jobs if (_ts(j.get("created")) or since) >= since]
    print(f"tapis jobs created in window: {len(jobs_recent)}\n")

    # --- walk pipelines / runs ---------------------------------------------
    rows: list[dict] = []
    bundle: dict = {"generated_at": now.isoformat(), "base_url": base, "user": username,
                    "groups": groups, "jobs": jobs_recent, "runs": []}
    for gid in groups:
        try:
            pipelines = _get(session, base, f"/v3/workflows/groups/{gid}/pipelines") or []
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {gid}: {exc}", file=sys.stderr)
            continue
        for pl in pipelines:
            pid = str(pl.get("id"))
            try:
                runs = _get(session, base, f"/v3/workflows/groups/{gid}/pipelines/{pid}/runs") or []
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {gid}/{pid}: {exc}", file=sys.stderr)
                continue
            for run in runs:
                started = _ts(run.get("started_at") or run.get("created_at"))
                if started and started < since:
                    continue
                status = str(run.get("status") or "").upper()
                if args.active_only and status in TERMINAL:
                    continue
                ruuid = str(run.get("uuid"))
                rpath = f"/v3/workflows/groups/{gid}/pipelines/{pid}/runs/{ruuid}"
                try:
                    full = _get(session, base, rpath) or run
                except Exception:  # noqa: BLE001
                    full = run
                try:
                    execs = _get(session, base, f"{rpath}/executions") or []
                except Exception as exc:  # noqa: BLE001
                    execs = []
                    full["_executions_error"] = str(exc)
                full = _to_jsonable(full)
                execs = [_to_jsonable(e) for e in execs]
                label, detail = _classify(full, execs)
                seen, ts_active, _ = _first_task_active(str(full.get("logs") or ""))
                launch = "never"
                if seen:
                    launch = f"{int((ts_active - started).total_seconds())}s" if (ts_active and started) else "yes"
                # jobs created within 6 h after this run started
                matched = []
                if started:
                    for j in jobs_recent:
                        jc = _ts(j.get("created"))
                        if jc and started <= jc <= started + timedelta(hours=6):
                            matched.append(j)
                rows.append({"group": gid, "pipeline": pid, "uuid": ruuid, "status": status,
                             "started": started, "label": label, "detail": detail,
                             "launch": launch, "jobs": matched,
                             "tasks": [(e.get("task_id"), e.get("status")) for e in execs]})
                bundle["runs"].append({"group": gid, "pipeline": pid, "run": full,
                                       "executions": execs, "classification": label,
                                       "detail": detail, "matched_jobs": matched})

    rows.sort(key=lambda r: r["started"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # --- report --------------------------------------------------------------
    print(f"{'started (UTC)':17} {'age':>6}  {'group':13} {'pipeline':32} {'status':10} "
          f"{'launch':>7}  {'class':13} uuid")
    print("-" * 150)
    for r in rows:
        st = f"{r['started']:%m-%d %H:%M:%S}" if r["started"] else "?"
        print(f"{st:17} {_age(r['started'], now):>6}  {r['group']:13} {r['pipeline'][:32]:32} "
              f"{r['status']:10} {r['launch']:>7}  {r['label']:13} {r['uuid']}")
    if not rows:
        print("(no runs in window)")

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    print("\nby class: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    healthy = [r for r in rows if r["launch"] != "never"]
    stalled = [r for r in rows if r["label"] == "ENGINE_STALL"]
    if healthy:
        last_ok = healthy[0]
        print(f"most recent run where the engine DID launch a task: "
              f"{last_ok['started']:%Y-%m-%d %H:%M}Z  {last_ok['group']}/{last_ok['pipeline']}  "
              f"launch={last_ok['launch']}")
    if stalled:
        first_bad = stalled[-1]
        print(f"earliest ENGINE_STALL in window:                     "
              f"{first_bad['started']:%Y-%m-%d %H:%M}Z  {first_bad['group']}/{first_bad['pipeline']}")

    # --- detail for non-terminal runs --------------------------------------
    for r in rows:
        if r["label"] in TERMINAL or r["label"] == "DONE":
            continue
        print("\n" + "=" * 150)
        print(f"{r['label']}  {r['group']}/{r['pipeline']}  run {r['uuid']}  "
              f"started {r['started']}  ({_age(r['started'], now)} ago)")
        print(f"  {r['detail']}")
        print(f"  task executions: {r['tasks'] or 'none'}")
        if r["jobs"]:
            for j in r["jobs"]:
                print(f"  tapis job after start: {j.get('created')}  {j.get('status'):22} "
                      f"{j.get('appId')}  {j.get('uuid')}  {j.get('name')}")
        else:
            print("  tapis jobs created after start: NONE")
        if args.verbose:
            entry = next(b for b in bundle["runs"] if b["run"].get("uuid") == r["uuid"])
            logs = str(entry["run"].get("logs") or "").strip()
            tail = logs.splitlines()[-20:]
            print("  --- pipeline log tail ---")
            for line in tail or ["(empty)"]:
                print("   ", line)
            for e in entry["executions"]:
                print(f"  --- task {e.get('task_id')} status={e.get('status')} "
                      f"started={e.get('started_at')} last_modified={e.get('last_modified')}")
                for fld in ("last_message", "stderr", "stdout"):
                    if e.get(fld):
                        print(f"      {fld}: {str(e[fld]).strip()[:600]}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(bundle, f, indent=2, default=str)
        print(f"\nfull bundle written to {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
