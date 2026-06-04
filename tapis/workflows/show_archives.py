#!/usr/bin/env python3
"""Show where recent Tapis jobs archived, so we can see what location works.

A new run failed creating its archive dir on cloud.data. This lists your recent
jobs with their archiveSystemId / archiveSystemDir and status, so you can compare
the *failing* path against where *successful* runs wrote. Also lists the contents
of the archive root (to spot a full/cluttered home).

Usage (same env as orchestrate.py — tapipy + creds):
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...
    python tapis/workflows/show_archives.py [--limit 20]
"""

from __future__ import annotations

import argparse
import sys

import register  # reuse _authenticate()


def _f(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=20)
    args = p.parse_args(argv)

    t = register._authenticate()
    user = t.username
    print(f"Authenticated as {user}\n")

    try:
        jobs = t.jobs.getJobList(limit=args.limit, orderBy="lastUpdated(desc)")
    except Exception:
        jobs = t.jobs.getJobList(limit=args.limit)

    print(f"{'status':10} {'appId':32} archiveSystemId  archiveSystemDir")
    print("-" * 110)
    systems_seen: dict[str, int] = {}
    for j in jobs or []:
        uuid = _f(j, "uuid")
        try:
            full = t.jobs.getJob(jobUuid=uuid)   # summary list lacks archive fields
        except Exception:
            full = j
        status = str(_f(full, "status") or "?")
        app = str(_f(full, "appId") or "?")[:32]
        sysid = str(_f(full, "archiveSystemId") or "-")
        sysdir = str(_f(full, "archiveSystemDir") or "-")
        if status == "FINISHED":
            systems_seen[sysid] = systems_seen.get(sysid, 0) + 1
        print(f"{status:10} {app:32} {sysid:15}  {sysdir}")

    print("\nArchive systems used by FINISHED jobs:", systems_seen or "(none finished in this window)")

    # Peek at the archive root the failing job tried to use.
    root = f"home/{user}/tapis-jobs-archive"
    print(f"\nContents of cloud.data:/{root} (recent):")
    try:
        listing = t.files.listFiles(systemId="cloud.data", path=root, limit=20)
        for f in listing or []:
            print(f"  {_f(f,'type'):4} {_f(f,'size')}\t{_f(f,'name')}")
    except Exception as exc:
        print(f"  (could not list: {type(exc).__name__}: {str(exc)[:140]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
