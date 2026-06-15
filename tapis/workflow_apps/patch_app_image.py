#!/usr/bin/env python3
"""Re-point the registered SUBSIDE analysis apps at a container image.

This is the deploy glue between a freshly-built GHCR image and the Tapis *app*
record (which stores an image *reference*, separate from the image itself, and
only the owner may MODIFY). Two modes:

  * ``--image-tag sha-<gitsha>`` (how CI calls it): pin each app to that exact,
    **immutable** tag built this run. Immutable tags give provenance, dodge GHCR
    pruning surprises, AND bust the exec host's Singularity SIF cache (a changing
    digest forces a re-pull, which the moving ``:main`` tag does not).
  * no flag (manual use): use the ``containerImage`` declared in each app-cpu.json
    verbatim (the ``:main`` fallback).

Run as the app OWNER (wmobley) — patching needs MODIFY on the app, which the
admin service account does not have. CI uses the owner-scoped TAPIS_ID /
TAPIS_PASSWORD repo secrets (see .github/workflows/build-images.yml). Manually,
set TAPIS_USERNAME (or TAPIS_ID) + TAPIS_PASSWORD:

    TAPIS_USERNAME=wmobley TAPIS_PASSWORD=... \
        python subside/tapis/workflow_apps/patch_app_image.py [--image-tag sha-abc1234]

After it prints the new image for both apps, the next pipeline run picks it up.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from tapipy.tapis import Tapis

HERE = Path(__file__).resolve().parent
APP_DEFS = [HERE / "h2i_lab" / "app-cpu.json", HERE / "werc" / "app-cpu.json"]


def retag(container_image: str, tag: str) -> str:
    """Replace the tag on a ``docker://registry/owner/name:tag`` reference.

    The tag is the substring after the final ``:`` (registry has no port here),
    so rpartition splits it off without touching the ``docker://`` scheme colon.
    """
    base, sep, _old = container_image.rpartition(":")
    return f"{base}:{tag}" if sep else f"{container_image}:{tag}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Re-point the SUBSIDE analysis apps at a container image.")
    p.add_argument("--image-tag", default=None,
                   help="Pin every app to this exact tag (e.g. sha-abc1234), keeping each "
                        "app-cpu.json's registry/name. Omit to use the image as declared.")
    args = p.parse_args(argv)

    base = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
    # TAPIS_ID is the repo/CI convention (see build-services.yml); TAPIS_USERNAME
    # is the conventional tapipy name. Accept either.
    user = os.environ.get("TAPIS_USERNAME") or os.environ.get("TAPIS_ID") or input("Tapis username: ")
    pw = os.environ.get("TAPIS_PASSWORD") or getpass.getpass("Tapis password: ")
    t = Tapis(base_url=base, username=user, password=pw)
    t.get_tokens()
    print(f"authenticated as {t.username} on {base}\n")

    rc = 0
    for path in APP_DEFS:
        spec = json.loads(path.read_text())
        app_id, version = spec["id"], spec["version"]
        image = retag(spec["containerImage"], args.image_tag) if args.image_tag else spec["containerImage"]
        t.apps.patchApp(appId=app_id, appVersion=version, containerImage=image)
        now = t.apps.getApp(appId=app_id, appVersion=version).containerImage
        flag = "OK" if now == image else "MISMATCH"
        if flag == "MISMATCH":
            rc = 1
        print(f"[{flag}] {app_id} {version} -> {now}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
