#!/usr/bin/env python3
"""Diagnose the cloud.data archive-mkdir failure that breaks job runs.

A run job failed with FILES_REMOTE_MKDIRS_ERROR creating
``/home/<user>/tapis-jobs-archive/...`` on cloud.data (http 500). Staging to the
same home dir works, so this probes the *archive* path specifically to tell a
transient 500 from a persistent perms/quota problem.

Usage (same env you run orchestrate.py in — tapipy + creds):
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...
    python tapis/workflows/check_archive.py
"""

from __future__ import annotations

import sys

import register  # reuse _authenticate()

SYSTEM = "cloud.data"


def _try(label, fn):
    try:
        fn()
        print(f"  OK   {label}")
        return True
    except Exception as exc:
        print(f"  FAIL {label}: {type(exc).__name__}: {str(exc)[:160]}")
        return False


def main() -> int:
    t = register._authenticate()
    user = t.username
    print(f"Authenticated as {user} against {register.DEFAULT_BASE_URL}\n")

    home = f"home/{user}"
    archive_root = f"{home}/tapis-jobs-archive"
    probe = f"{archive_root}/_probe_check"

    print(f"[1] list {SYSTEM}:/{home}")
    _try("list home", lambda: t.files.listFiles(systemId=SYSTEM, path=home, limit=5))

    print(f"[2] list {SYSTEM}:/{archive_root}  (does the archive root exist / readable?)")
    _try("list tapis-jobs-archive", lambda: t.files.listFiles(systemId=SYSTEM, path=archive_root, limit=5))

    print(f"[3] mkdir {SYSTEM}:/{probe}  (the operation the Jobs worker does)")
    made = _try("mkdir probe under archive", lambda: t.files.mkdir(systemId=SYSTEM, path=probe))

    if made:
        print(f"[4] cleanup: delete {probe}")
        _try("delete probe", lambda: t.files.delete(systemId=SYSTEM, path=probe))

    print("\nInterpretation:")
    print("  - [1]/[2] OK but [3] FAIL 500  -> archive path perms/quota or a stale dir; check ownership/quota of tapis-jobs-archive.")
    print("  - [3] OK now                   -> the earlier 500 was transient; just re-run the pipeline.")
    print("  - everything FAIL              -> cloud.data is down / your home isn't provisioned; check TACC system status.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
