#!/usr/bin/env python3
"""Register (or update) the SUBSIDE UI + API as Tapis Pods on portals.tapis.io.

Creates two custom-image pods from the GHCR images built by
`.github/workflows/build-services.yml`:

    subsideapi  ->  https://subsideapi.pods.portals.tapis.io   (FastAPI :8000)
    subsideui   ->  https://subsideui.pods.portals.tapis.io    (nginx :80)

(pod_id has no hyphen — Tapis requires lowercase-alphanumeric ids; the GHCR
image names ghcr.io/<owner>/subside-{api,ui} keep their hyphens.)

The UI pod serves static files only; the browser calls the API DIRECTLY (CORS) at
SUBSIDE_API_BASE (set here to the API pod URL, injected into the UI's runtime
config at container start). A UI pod cannot proxy back through the Tapis ingress
to the API pod — that egress times out — so same-origin proxying is not used.
Pod env vars (DB URL, OAuth client, Earthdata, …) are read from the environment /
subside/.env — the same values the API uses locally.

Usage:
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...      # or you'll be prompted
    python tapis/register_pods.py --image-tag latest --owner wmobley
    python tapis/register_pods.py --pods api          # just one
    python tapis/register_pods.py --recreate          # delete + recreate
    python tapis/register_pods.py --dry-run           # print specs, don't call Tapis

Prerequisites:
    * Images built & pushed to GHCR (the build-services workflow).
    * The GHCR packages must be PULLABLE by Tapis — make them public, since
      Pods custom images pull anonymously. (Private GHCR won't pull.)
    * After the UI pod exists, register the OAuth client against its URL:
        python tapis/workflows/register_oauth_client.py \\
            --callback-url https://subsideui.pods.portals.tapis.io/
      and set TAPIS_OAUTH_CALLBACK_URL to match.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # subside/

# API env vars forwarded into the API pod (only those actually set are sent).
# SECRET_KEYS are stored in the pod spec as plaintext — see the warning below.
# Forwarded verbatim from the local environment / .env (only if set). NOTE:
# TAPIS_OAUTH_CALLBACK_URL and SUBSIDE_CORS_ORIGINS are deliberately NOT here —
# they are deployment-derived and get set to the UI pod's URL below (the local
# dev values like https://subside.local:5174/ are wrong for a pod).
API_ENV_KEYS = [
    "SUBSIDE_DATABASE_URL",
    "TAPIS_BASE_URL",
    "TAPIS_CLIENT_ID",
    "TAPIS_CLIENT_KEY",
    "EARTHDATA_USERNAME",
    "EARTHDATA_PASSWORD",
    "SUBSIDE_DEFAULT_ALLOCATION",
    "SUBSIDE_STAGING_SYSTEM",
    "SUBSIDE_STAGING_PREFIX",
    "SUBSIDE_MVT_SCHEMA",
]
SECRET_KEYS = {"SUBSIDE_DATABASE_URL", "TAPIS_CLIENT_KEY", "EARTHDATA_PASSWORD"}


def _load_dotenv() -> None:
    """Load subside/.env so local config/secrets populate os.environ."""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass


def _pods_domain(base_url: str) -> str:
    # https://portals.tapis.io -> portals.tapis.io
    return base_url.rstrip("/").split("://", 1)[-1]


# Tapis pod_id must be lowercase alphanumeric, first char alpha — NO hyphens.
# The pod's URL is derived from this id (https://<pod_id>.pods.<domain>), so the
# two must stay in lockstep; don't reintroduce a hyphen in one but not the other.
API_POD_ID = "subsideapi"
UI_POD_ID = "subsideui"


def _ui_env(api_url: str) -> dict[str, str]:
    """Env for the UI pod: the API origin the browser calls (rewritten into
    /runtime-config.js at container start) plus optional STAC settings."""
    env = {"SUBSIDE_API_BASE": api_url}
    for k in ("SUBSIDE_STAC_API_BASE", "SUBSIDE_STAC_COLLECTION"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def build_specs(owner: str, tag: str, base_url: str) -> dict[str, dict]:
    domain = _pods_domain(base_url)
    api_url = f"https://{API_POD_ID}.pods.{domain}"
    ui_url = f"https://{UI_POD_ID}.pods.{domain}"

    api_env = {k: os.environ[k] for k in API_ENV_KEYS if os.environ.get(k)}
    # Deployment-derived (always the pod URLs, never the local dev values):
    api_env["TAPIS_OAUTH_CALLBACK_URL"] = f"{ui_url}/"
    api_env["SUBSIDE_CORS_ORIGINS"] = ui_url
    api_env.setdefault("TAPIS_BASE_URL", base_url.rstrip("/"))

    api = {
        "pod_id": API_POD_ID,
        "image": f"ghcr.io/{owner}/subside-api:{tag}",
        "description": "SUBSIDE FastAPI gateway (full geo stack)",
        "networking": {"default": {"protocol": "http", "port": 8000}},
        # Geo/scientific stack baked in → heavier runtime footprint.
        "resources": {"cpu_request": 500, "cpu_limit": 2000,
                      "mem_request": 1024, "mem_limit": 4096},
        "environment_variables": api_env,
        "time_to_stop_default": -1,  # long-running service
    }
    ui = {
        "pod_id": UI_POD_ID,
        "image": f"ghcr.io/{owner}/subside-ui:{tag}",
        "description": "SUBSIDE web UI (nginx) - proxies /api/subside to the API pod",
        "networking": {"default": {"protocol": "http", "port": 80}},
        # Tenant floor is cpu_request>=250, mem_request>=256 (breaking it needs
        # an extra role). nginx is light, so request the minimum.
        "resources": {"cpu_request": 250, "cpu_limit": 1000,
                      "mem_request": 256, "mem_limit": 512},
        # The browser calls the API directly at this origin (CORS); it's baked
        # into /runtime-config.js at container start. STAC base is optional and
        # forwarded only when set locally (STAC features are off otherwise).
        "environment_variables": _ui_env(api_url),
        "time_to_stop_default": -1,
    }
    return {"api": api, "ui": ui, "_urls": {"api": api_url, "ui": ui_url}}


def upsert_pod(t, spec: dict, *, recreate: bool, start: bool) -> None:
    pid = spec["pod_id"]
    exists = True
    try:
        t.pods.get_pod(pod_id=pid)
    except Exception:
        exists = False

    if exists and recreate:
        print(f"  [{pid}] deleting existing pod (--recreate)…")
        t.pods.delete_pod(pod_id=pid)
        exists = False

    if exists:
        print(f"  [{pid}] updating…")
        # Best-effort in-place update; some fields may require --recreate.
        t.pods.update_pod(**spec)
    else:
        print(f"  [{pid}] creating…")
        t.pods.create_pod(**spec)

    if start:
        # A freshly-created pod auto-starts; start_pod only works from STOPPED.
        # Check status first so re-runs don't spew a scary RuntimeError.
        try:
            status = getattr(t.pods.get_pod(pod_id=pid), "status", None)
        except Exception:
            status = None
        if status and status != "STOPPED":
            print(f"  [{pid}] already {status}; not starting")
        else:
            try:
                t.pods.start_pod(pod_id=pid)
                print(f"  [{pid}] start requested")
            except Exception as exc:
                print(f"  [{pid}] start skipped: {exc}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Register SUBSIDE UI + API as Tapis Pods.")
    parser.add_argument("--base-url", default=os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io"))
    parser.add_argument("--owner", default=os.environ.get("GHCR_OWNER", "wmobley"),
                        help="GHCR owner/org for the images (ghcr.io/<owner>/subside-*).")
    parser.add_argument("--image-tag", default="latest")
    parser.add_argument("--pods", choices=("both", "api", "ui"), default="both")
    parser.add_argument("--recreate", action="store_true", help="Delete + recreate instead of update.")
    parser.add_argument("--no-start", action="store_true", help="Create/update but don't start.")
    parser.add_argument("--dry-run", action="store_true", help="Print specs; don't call Tapis.")
    args = parser.parse_args(argv)

    _load_dotenv()
    specs = build_specs(args.owner, args.image_tag, args.base_url)
    urls = specs.pop("_urls")
    selected = ["api", "ui"] if args.pods == "both" else [args.pods]

    # Warn about secrets that will be stored in the pod spec.
    leaked = sorted(k for k in SECRET_KEYS if os.environ.get(k))
    if leaked and "api" in selected:
        print("WARNING: these secrets will be stored in the API pod's environment_variables "
              "(visible to the pod owner): " + ", ".join(leaked))
        print("         For production, move them to Tapis secrets (${pods:secrets:KEY}).\n")

    if args.dry_run:
        for key in selected:
            spec = dict(specs[key])
            spec["environment_variables"] = {
                k: ("***" if k in SECRET_KEYS else v)
                for k, v in spec["environment_variables"].items()
            }
            print(f"--- {spec['pod_id']} ---")
            print(json.dumps(spec, indent=2))
        print(f"\nURLs once running:\n  API: {urls['api']}\n  UI:  {urls['ui']}")
        return 0

    try:
        from tapipy.tapis import Tapis
    except ImportError:
        raise SystemExit("tapipy is not installed (pip install tapipy).")

    username = os.environ.get("TAPIS_USERNAME") or input("Tapis username: ")
    password = os.environ.get("TAPIS_PASSWORD") or getpass("Tapis password: ")
    t = Tapis(base_url=args.base_url.rstrip("/"), username=username, password=password)
    t.get_tokens()

    for key in selected:
        upsert_pod(t, specs[key], recreate=args.recreate, start=not args.no_start)

    print("\nDone. Pods (once started):")
    if "api" in selected:
        print(f"  API: {urls['api']}   (health: {urls['api']}/api/subside/healthz)")
    if "ui" in selected:
        print(f"  UI:  {urls['ui']}")
    print("\nNext: register the OAuth client against the UI URL and set "
          "TAPIS_OAUTH_CALLBACK_URL to it:")
    print(f"  python tapis/workflows/register_oauth_client.py --callback-url {urls['ui']}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
