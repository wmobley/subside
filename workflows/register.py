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
    """Import ``module`` (including submodule path like ``tapipy.tapis``).

    Returns the leaf module object. Raises a friendly error if the package
    is missing.
    """
    try:
        # fromlist=['*'] forces submodule resolution, so 'tapipy.tapis' returns
        # the tapis submodule itself rather than the top-level tapipy package.
        return __import__(module, fromlist=["*"])
    except ImportError as exc:
        raise SystemExit(
            f"Missing dependency '{module}'. Install with: pip install tapipy pyyaml"
        ) from exc


def _authenticate():
    Tapis = _need("tapipy.tapis").Tapis
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


def _auth_headers(client) -> dict[str, str]:
    """Resolve the Tapis access token for raw HTTP calls.

    Works whether the user authed via username/password (tapipy generates a
    token in ``client.access_token``) or via ``TAPIS_JWT`` directly.
    """
    token = None
    access = getattr(client, "access_token", None)
    if access is not None:
        token = getattr(access, "access_token", None) or str(access)
    if not token:
        token = os.environ.get("TAPIS_JWT")
    if not token:
        raise SystemExit("Could not resolve a Tapis access token from the client.")
    return {"X-Tapis-Token": token, "Content-Type": "application/json"}


def _api_url(client, path: str) -> str:
    base = client.base_url.rstrip("/")
    return f"{base}{path}"


def _api_get(client, path: str):
    import requests
    return requests.get(_api_url(client, path), headers=_auth_headers(client), timeout=30)


def _api_post(client, path: str, body: dict):
    import requests
    return requests.post(
        _api_url(client, path), headers=_auth_headers(client), data=json.dumps(body), timeout=60
    )


def _api_put(client, path: str, body: dict):
    import requests
    return requests.put(
        _api_url(client, path), headers=_auth_headers(client), data=json.dumps(body), timeout=60
    )


def _api_patch(client, path: str, body: dict):
    import requests
    return requests.patch(
        _api_url(client, path), headers=_auth_headers(client), data=json.dumps(body), timeout=60
    )


def _api_delete(client, path: str):
    import requests
    return requests.delete(_api_url(client, path), headers=_auth_headers(client), timeout=30)


def _list_user_apps(client, prefix: str = "subside-") -> list[str]:
    """Return ids of all apps owned by the current user whose id starts with ``prefix``."""
    resp = _api_get(client, "/v3/apps?listType=MINE&limit=200&select=id")
    if not (200 <= resp.status_code < 300):
        raise SystemExit(f"Failed to list apps: HTTP {resp.status_code} — {resp.text[:400]}")
    data = resp.json()
    apps = data.get("result", [])
    return sorted({a["id"] for a in apps if a.get("id", "").startswith(prefix)})


def _delete_app(client, app_id: str, dry_run: bool) -> bool:
    """Soft-delete a Tapis app. Returns True on success or no-op, False on error.

    Tapis V3 uses ``POST /v3/apps/{appId}/delete`` (HTTP DELETE on that path
    returns 405). The endpoint marks every version of the app as ``deleted``;
    they no longer show up in default listings but can be undeleted via
    ``POST /v3/apps/{appId}/undelete``.
    """
    if dry_run:
        print(f"[delete]  app:          {app_id}  (dry-run)")
        return True
    resp = _api_post(client, f"/v3/apps/{app_id}/delete", {})
    if 200 <= resp.status_code < 300:
        print(f"[deleted] app:          {app_id}")
        return True
    if resp.status_code == 404:
        print(f"[skip]    app:          {app_id}  (not registered)")
        return True
    print(f"[error]   app:          {app_id}  HTTP {resp.status_code} — {resp.text[:300]}")
    return False


def _prune_apps(client, local_app_ids: set[str], dry_run: bool) -> None:
    """Delete any subside-* apps owned by the user that aren't in the local catalog.

    Continues past individual delete failures so a flaky one doesn't block the rest.
    """
    registered = _list_user_apps(client, prefix="subside-")
    stale = [aid for aid in registered if aid not in local_app_ids]
    if not stale:
        print("[ok]      no stale subside-* apps registered")
        return
    print(f"Found {len(stale)} stale subside-* app(s) not in local catalog:")
    for aid in stale:
        print(f"    - {aid}")
    failures = [aid for aid in stale if not _delete_app(client, aid, dry_run=dry_run)]
    if failures:
        print(f"\n[warn]    {len(failures)} delete(s) failed: {', '.join(failures)}")
        print("          You can retry per-app with: --delete-app <id>")


def _ensure_group(client, group_id: str, dry_run: bool) -> None:
    resp = _api_get(client, f"/v3/workflows/groups/{group_id}")
    if 200 <= resp.status_code < 300:
        print(f"[ok]      group exists: {group_id}")
        return
    if resp.status_code not in (401, 404):
        print(f"[warn]    group check returned {resp.status_code}: {resp.text[:200]}")
    print(f"[create]  group:        {group_id}")
    if dry_run:
        return
    create = _api_post(client, "/v3/workflows/groups", {"id": group_id, "owner": client.username})
    if not (200 <= create.status_code < 300):
        raise SystemExit(f"Failed to create group {group_id}: HTTP {create.status_code} — {create.text[:400]}")


def _load_app(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


# Tapis V3 app PATCH disallows these in the body — they're either URL-path
# params (id/version), set at create time (owner), or only changeable via
# dedicated endpoints (enabled, runtimeVersion).
_PATCH_FORBIDDEN_KEYS = frozenset({"id", "version", "owner", "enabled", "runtimeVersion"})


def _register_app(client, app: dict[str, Any], dry_run: bool) -> None:
    app_id = app["id"]
    version = app["version"]
    resp = _api_get(client, f"/v3/apps/{app_id}/{version}")
    exists = 200 <= resp.status_code < 300
    action = "update" if exists else "create"
    print(f"[{action}]  app:          {app_id}@{version}")
    if dry_run:
        return
    if exists:
        body = {k: v for k, v in app.items() if k not in _PATCH_FORBIDDEN_KEYS}
        resp = _api_patch(client, f"/v3/apps/{app_id}/{version}", body)
    else:
        resp = _api_post(client, "/v3/apps", app)
    if not (200 <= resp.status_code < 300):
        raise SystemExit(
            f"Failed to {action} app {app_id}@{version}: HTTP {resp.status_code} — {resp.text[:400]}"
        )


def _load_pipeline(path: Path) -> dict[str, Any]:
    yaml = _need("yaml")
    with path.open() as f:
        return yaml.safe_load(f)


def _register_pipeline(client, group_id: str, pipeline: dict[str, Any], dry_run: bool) -> None:
    pipeline_id = pipeline["id"]
    resp = _api_get(client, f"/v3/workflows/groups/{group_id}/pipelines/{pipeline_id}")
    exists = 200 <= resp.status_code < 300
    action = "update" if exists else "create"
    print(f"[{action}]  pipeline:     {pipeline_id}  (group={group_id})")
    if dry_run:
        return
    if exists:
        resp = _api_put(client, f"/v3/workflows/groups/{group_id}/pipelines/{pipeline_id}", pipeline)
    else:
        resp = _api_post(client, f"/v3/workflows/groups/{group_id}/pipelines", pipeline)
    if not (200 <= resp.status_code < 300):
        raise SystemExit(
            f"Failed to {action} pipeline {pipeline_id}: HTTP {resp.status_code} — {resp.text[:400]}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register SUBSIDE Tapis apps + Workflows pipelines.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be registered without making API calls.")
    parser.add_argument("--group", default=DEFAULT_GROUP, help="Tapis Workflows group id.")
    parser.add_argument("--apps-only", action="store_true", help="Skip pipeline registration.")
    parser.add_argument("--pipelines-only", action="store_true", help="Skip app registration.")
    parser.add_argument(
        "--delete-app",
        action="append",
        metavar="APP_ID",
        help="Delete a Tapis app by id. Repeatable. Skips registration entirely.",
    )
    parser.add_argument(
        "--prune-apps",
        action="store_true",
        help="Delete any user-owned subside-* apps that aren't in the local workflow_apps/ catalog. "
             "Runs BEFORE registration so a single invocation can clean up + re-register.",
    )
    parser.add_argument(
        "--list-apps",
        action="store_true",
        help="List user-owned subside-* apps registered in Tapis and exit.",
    )
    args = parser.parse_args(argv)

    client = _authenticate()
    print(f"Authenticated against {DEFAULT_BASE_URL} as {client.username}")

    # --list-apps short-circuits: no auth side-effects, no registration.
    if args.list_apps:
        for aid in _list_user_apps(client):
            print(f"  {aid}")
        return 0

    # --delete-app short-circuits: no registration after deletion.
    if args.delete_app:
        for aid in args.delete_app:
            _delete_app(client, aid, dry_run=args.dry_run)
        return 0

    # Local app catalog (used by --prune-apps to know what to keep).
    local_app_ids = {
        _load_app(p)["id"] for p in REPO_ROOT.glob(APP_JSON_GLOB)
    }

    if args.prune_apps:
        _prune_apps(client, local_app_ids, dry_run=args.dry_run)

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
