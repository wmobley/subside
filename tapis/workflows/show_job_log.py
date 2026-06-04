#!/usr/bin/env python3
"""Print a failed (or finished) job's log + archive listing, to see why it failed.

The app jobs archive on app error (archiveOnAppError=true), so the merged
stdout/stderr (``tapisjob.out``) is in the archive. This fetches it via the Files
API from the job's archiveSystemId/Dir and tails it.

Usage (same env as orchestrate.py):
    python tapis/workflows/show_job_log.py <job-uuid> [--tail 200]
"""

from __future__ import annotations

import argparse
import sys

import register  # reuse _authenticate()


def _f(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _text(raw) -> str:
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode(errors="replace")
    return raw if isinstance(raw, str) else str(raw)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("uuid")
    p.add_argument("--tail", type=int, default=200)
    args = p.parse_args(argv)

    t = register._authenticate()
    job = t.jobs.getJob(jobUuid=args.uuid)
    sysid = str(_f(job, "archiveSystemId") or "")
    sysdir = str(_f(job, "archiveSystemDir") or "")
    print(f"status={_f(job,'status')}  archive={sysid}:/{sysdir.lstrip('/')}\n")
    base = sysdir.lstrip("/")

    print(f"[archive listing] {sysid}:/{base}")
    try:
        for f in t.files.listFiles(systemId=sysid, path=base, limit=50) or []:
            print(f"  {_f(f,'type'):4} {str(_f(f,'size')):>10}  {_f(f,'name')}")
    except Exception as exc:
        print(f"  (list failed: {type(exc).__name__}: {str(exc)[:140]})")

    # The app's merged stdout+stderr. Try a couple of common locations.
    for rel in ("tapisjob.out", "output/tapisjob.out", "tapisjob.err"):
        try:
            raw = t.files.getContents(systemId=sysid, path=f"{base}/{rel}")
        except Exception:
            continue
        lines = _text(raw).splitlines()
        print(f"\n===== {rel} (last {args.tail} lines) =====")
        print("\n".join(lines[-args.tail:]))
        return 0

    print("\n(could not find tapisjob.out in the archive; try the listing above)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
