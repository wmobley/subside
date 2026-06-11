#!/usr/bin/env python3
"""Re-point the registered SUBSIDE analysis apps at the containerImage declared in
their app-cpu.json (currently the moving ``:main`` tag).

Why this exists: the apps are pinned by hand and drift behind the repo; when GHCR
prunes the old ``sha-…`` tag the Singularity pull 404s and the run job dies with
exit 127. Pinning to ``:main`` (which CI republishes every push) avoids that.

Run as the app OWNER (wmobley) — patching needs MODIFY on the app, which the
admin service account does not have:

    TAPIS_USERNAME=wmobley TAPIS_PASSWORD=... \
        python subside/tapis/workflow_apps/patch_app_image.py

After it prints the new image for both apps, re-run the pipeline from the UI.
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

from tapipy.tapis import Tapis

HERE = Path(__file__).resolve().parent
APP_DEFS = [HERE / "h2i_lab" / "app-cpu.json", HERE / "werc" / "app-cpu.json"]


def main() -> int:
    base = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
    user = os.environ.get("TAPIS_USERNAME") or input("Tapis username: ")
    pw = os.environ.get("TAPIS_PASSWORD") or getpass.getpass("Tapis password: ")
    t = Tapis(base_url=base, username=user, password=pw)
    t.get_tokens()
    print(f"authenticated as {t.username} on {base}\n")

    for path in APP_DEFS:
        spec = json.loads(path.read_text())
        app_id, version, image = spec["id"], spec["version"], spec["containerImage"]
        t.apps.patchApp(appId=app_id, appVersion=version, containerImage=image)
        now = t.apps.getApp(appId=app_id, appVersion=version).containerImage
        flag = "OK" if now == image else "MISMATCH"
        print(f"[{flag}] {app_id} {version} -> {now}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
