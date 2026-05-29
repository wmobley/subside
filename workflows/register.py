"""Register SUBSIDE Tapis apps + Workflows pipelines against a Tapis tenant.

Usage::

    pip install tapipy pyyaml
    export TAPIS_USERNAME=<your-username>
    export TAPIS_PASSWORD=<your-password>        # or TAPIS_JWT for token auth
    python workflows/register.py [--dry-run]

What it does (in order):

1. Authenticates against ``$TAPIS_BASE_URL`` (default: PortalsCI).
2. Ensures the workflow group ``$SUBSIDE_WORKFLOW_GROUP`` exists.
3. Registers/updates every Tapis app definition under ``workflow_apps/<pkg>/app-*.json``.
4. Registers/updates every Tapis Workflows pipeline definition under ``workflows/pipelines/*.yaml``.

The Tapis Workflows V3 API surface is still moving. Where tapipy doesn't yet
expose a typed method, this script falls back to raw HTTP via the
authenticated tapipy session. Verify the endpoint paths against the live
tenant the first time you run it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]  # subside/
APP_JSON_GLOB = "workflow_apps/*/app-*.json"
PIPELINE_GLOB = "workflows/pipelines/*.yaml"

DEFAULT_BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")
DEFAULT_GROUP = os.environ.get("SUBSIDE_WORKFLOW_GROUP", "subside-ops")


def _need(module: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise SystemExit(
            f"Missing dependency '{module}'. Install with: pip install tapipy pyyaml"
        ) from exc


def _authenticate():
    Tapis = _need("tapipy").tapis.Tapis  # type: ignore[attr-defined]
    username = os.environ.get("TAPIS_USERNAME")
    password = os.environ.get("TAPIS_PASSWORD")
    jwt = os.environ.get("TAPIS_JWT")
    if jwt:
        client = Tapis(base_url=DEFAULT_BASE_URL, jwt=jwt)
    elif username and password:
        client = Tapis(base_url=DEFAULT_BASE_URL, username=username, password=password)
        client.get_tokens()
    else:
        raise SystemExit(
            "Set TAPIS_USERNAME + TAPIS_PASSWORD or TAPIS_JWT before running."
        )
    return client


def _ensure_group(client, group_id: str, dry_run: bool) -> None:
    try:
        client.workflows.get_group(group_id=group_id)
        print(f"[ok] group exists: {group_id}")
    except Exception as exc:
        print(f"[+] creating group: {group_id}  ({exc.__class__.__name__})")
        if dry_run:
            return
        # tapipy may not expose workflows.create_group on every version; try
        # the typed method first, fall back to raw POST.
        try:
            client.workflows.create_group(id=group_id, owner=client.username)
        except AttributeError:
            client.post(
                f"/v3/workflows/groups",
                data=json.dumps({"id": group_id, "owner": client.username}),
                headers={"Content-Type": "application/json"},
            )


def _load_app(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def _register_app(client, app: dict[str, Any], dry_run: bool) -> None:
    app_id = app["id"]
    version = app["version"]
    try:
        client.apps.getAppLatestVersion(appId=app_id)
        action = "update"
    except Exception:
        action = "create"
    print(f"[{action}] app {app_id}@{version}")
    if dry_run:
        return
    if action == "create":
        client.apps.createApp(**app)
    else:
        client.apps.patchApp(appId=app_id, appVersion=version, **app)


def _load_pipeline(path: Path) -> dict[str, Any]:
    yaml = _need("yaml")
    with path.open() as f:
        return yaml.safe_load(f)


def _register_pipeline(client, group_id: str, pipeline: dict[str, Any], dry_run: bool) -> None:
    pipeline_id = pipeline["id"]
    existing = None
    try:
        existing = client.workflows.get_pipeline(group_id=group_id, pipeline_id=pipeline_id)
    except Exception:
        pass
    action = "update" if existing else "create"
    print(f"[{action}] pipeline {pipeline_id}  (group={group_id})")
    if dry_run:
        return
    body = json.dumps(pipeline)
    if action == "create":
        client.post(
            f"/v3/workflows/groups/{group_id}/pipelines",
            data=body,
            headers={"Content-Type": "application/json"},
        )
    else:
        client.put(
            f"/v3/workflows/groups/{group_id}/pipelines/{pipeline_id}",
            data=body,
            headers={"Content-Type": "application/json"},
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register SUBSIDE Tapis apps + Workflows pipelines.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be registered without making API calls.")
    parser.add_argument("--group", default=DEFAULT_GROUP, help="Tapis Workflows group id.")
    parser.add_argument("--apps-only", action="store_true", help="Skip pipeline registration.")
    parser.add_argument("--pipelines-only", action="store_true", help="Skip app registration.")
    args = parser.parse_args(argv)

    client = _authenticate()
    print(f"Authenticated against {DEFAULT_BASE_URL} as {client.username}")

    if not args.pipelines_only:
        for path in sorted(REPO_ROOT.glob(APP_JSON_GLOB)):
            app = _load_app(path)
            _register_app(client, app, dry_run=args.dry_run)

    if not args.apps_only:
        _ensure_group(client, args.group, dry_run=args.dry_run)
        for path in sorted(REPO_ROOT.glob(PIPELINE_GLOB)):
            pipeline = _load_pipeline(path)
            _register_pipeline(client, args.group, pipeline, dry_run=args.dry_run)

    print("Done." + (" (dry-run, no changes made)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
