#!/usr/bin/env python3
"""Restart the SUBSIDE UI + API Tapis Pods so they re-pull their GHCR images.

Run by `.github/workflows/build-services.yml` after the `latest` images are
built and pushed. A pod restart stops + starts the container, which re-pulls the
`latest`-tagged image — picking up the freshly-built code WITHOUT touching the
pod spec (env vars, OAuth client, DB URL all stay as register_pods.py set them).

This is intentionally NOT register_pods.py: that script (re)registers the OAuth
client (rotating its key) and rebuilds the pod spec from subside/.env, neither of
which is available — or safe — in CI. Restarting only needs Tapis credentials.

Usage:
    export TAPIS_USERNAME=...   # or TAPIS_ID (CI secret alias)
    export TAPIS_PASSWORD=...
    python tapis/restart_pods.py                 # restart both
    python tapis/restart_pods.py --pods api       # just one
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Keep these in lockstep with register_pods.py (API_POD_ID / UI_POD_ID).
POD_IDS = {"api": "subsideapi", "ui": "subsideui"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Restart the SUBSIDE Tapis Pods.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io"),
    )
    parser.add_argument("--pods", choices=("both", "api", "ui"), default="both")
    args = parser.parse_args(argv)

    # CI stores the username as TAPIS_ID; locally it may be TAPIS_USERNAME.
    username = os.environ.get("TAPIS_USERNAME") or os.environ.get("TAPIS_ID")
    password = os.environ.get("TAPIS_PASSWORD")
    if not username or not password:
        print(
            "ERROR: set TAPIS_USERNAME (or TAPIS_ID) and TAPIS_PASSWORD.",
            file=sys.stderr,
        )
        return 2

    try:
        from tapipy.tapis import Tapis
    except ImportError:
        print("ERROR: tapipy is not installed (pip install tapipy).", file=sys.stderr)
        return 2

    t = Tapis(base_url=args.base_url.rstrip("/"), username=username, password=password)
    t.get_tokens()

    selected = ["api", "ui"] if args.pods == "both" else [args.pods]
    failures = 0
    for key in selected:
        pid = POD_IDS[key]
        try:
            t.pods.restart_pod(pod_id=pid)
            print(f"[{pid}] restart requested")
        except Exception as exc:  # noqa: BLE001 - surface any Tapis error, keep going
            print(f"[{pid}] restart FAILED: {exc}", file=sys.stderr)
            failures += 1
            continue
        # Best-effort confirmation that the pod is coming back up.
        time.sleep(2)
        try:
            status = getattr(t.pods.get_pod(pod_id=pid), "status", "?")
            print(f"[{pid}] status: {status}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{pid}] status check skipped: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
