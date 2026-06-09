"""Auto-provision a user on login: add them to the Tapis Workflows group and
the CKAN organization so they can submit runs and publish outputs.

A brand-new user can't add themselves, so the API acts as a dedicated SERVICE
ACCOUNT: SUBSIDE_ADMIN_USERNAME/PASSWORD (a group owner/admin) for the Tapis
group add, and SUBSIDE_CKAN_ADMIN_TOKEN (a CKAN org/sysadmin) for the org add.

Everything here is best-effort and idempotent: any failure is logged, never
raised, so provisioning can't block a login. Re-running on every login is fine
(adds are no-ops once the user is a member), which avoids tracking "first time".
"""

from __future__ import annotations

import logging

import requests

from .. import config
from . import tapis as tapis_mod

log = logging.getLogger("subside.provision")

# Cache the admin Tapis token across logins; refreshed on a 401.
_admin = {"token": None}


def _admin_token(force: bool = False) -> str | None:
    if not (config.SUBSIDE_ADMIN_USERNAME and config.SUBSIDE_ADMIN_PASSWORD):
        return None
    if _admin["token"] and not force:
        return _admin["token"]
    _admin["token"] = tapis_mod.login(config.SUBSIDE_ADMIN_USERNAME, config.SUBSIDE_ADMIN_PASSWORD)
    return _admin["token"]


def ensure_group_member(username: str) -> None:
    """Idempotently add ``username`` to the Workflows group as a non-admin member."""
    if not (config.SUBSIDE_ADMIN_USERNAME and config.SUBSIDE_ADMIN_PASSWORD):
        log.info("provision: Tapis admin creds unset; skipping group add for %s", username)
        return
    group = config.SUBSIDE_WORKFLOW_GROUP
    url = f"{config.TAPIS_BASE_URL}/v3/workflows/groups/{group}/users"
    body = {"username": username, "is_admin": False}
    for attempt in (1, 2):
        token = _admin_token(force=(attempt == 2))
        if not token:
            return
        resp = requests.post(url, headers={"X-Tapis-Token": token}, json=body, timeout=30)
        if resp.status_code == 401 and attempt == 1:
            continue  # admin token expired -> refresh once and retry
        if resp.status_code < 300:
            log.info("provision: added %s to group %s", username, group)
        elif resp.status_code == 409 or "exist" in resp.text.lower():
            log.info("provision: %s already in group %s", username, group)
        else:
            log.warning("provision: group add failed for %s: HTTP %s %s",
                        username, resp.status_code, resp.text[:200])
        return


def _ckan_auth_header(token: str) -> dict:
    """ckan.tacc is Tapis-fronted: send a JWT as a bearer token; a plain CKAN API
    key goes in the raw Authorization header."""
    auth = f"Bearer {token}" if token.count(".") == 2 else token
    return {"Authorization": auth}


def ensure_ckan_user(username: str, user_token: str | None) -> None:
    """Provision the user's CKAN account by making one authenticated call AS them.

    ckan.tacc maps a valid Tapis token to a CKAN user, creating it on first use —
    so authenticating once with the user's own JWT "logs them in" and materializes
    their account, which is what lets the admin org-add below find them. Needs the
    user's token (only available at login); no-op without it.
    """
    if not (user_token and config.SUBSIDE_CKAN_URL):
        return
    url = f"{config.SUBSIDE_CKAN_URL.rstrip('/')}/api/3/action/user_show"
    resp = requests.post(url, headers=_ckan_auth_header(user_token),
                         json={"id": username}, timeout=30)
    if resp.status_code < 300:
        log.info("provision: CKAN account ensured for %s", username)
    else:
        # The authenticated request itself usually triggers provisioning even if
        # this lookup 404s; logged so we can see if the org-add still can't find them.
        log.info("provision: CKAN user_show for %s -> HTTP %s", username, resp.status_code)


def ensure_ckan_org_member(username: str) -> None:
    """Idempotently add ``username`` to the CKAN org at the configured role.

    Auth: an explicit SUBSIDE_CKAN_ADMIN_TOKEN if set, otherwise the service
    account's own Tapis token (ckan.tacc accepts a Tapis JWT) — which works as
    long as that account is an admin of the org. So one set of service-account
    credentials covers both the Tapis group add and this CKAN org add.
    """
    if not (config.SUBSIDE_CKAN_URL and config.SUBSIDE_CKAN_ORG):
        log.info("provision: CKAN url/org unset; skipping org add for %s", username)
        return
    explicit = (config.SUBSIDE_CKAN_ADMIN_TOKEN or "").strip()
    if not explicit and not (config.SUBSIDE_ADMIN_USERNAME and config.SUBSIDE_ADMIN_PASSWORD):
        log.info("provision: no CKAN admin token nor service account; skipping org add for %s", username)
        return
    url = f"{config.SUBSIDE_CKAN_URL.rstrip('/')}/api/3/action/organization_member_create"
    body = {"id": config.SUBSIDE_CKAN_ORG, "username": username, "role": config.PROVISION_CKAN_ROLE}
    for attempt in (1, 2):
        # Prefer an explicit CKAN token; else reuse the service account's Tapis token.
        token = explicit or _admin_token(force=(attempt == 2))
        if not token:
            return
        resp = requests.post(url, headers=_ckan_auth_header(token), json=body, timeout=30)
        # A stale service-account token -> refresh once (only when we minted it).
        if resp.status_code == 401 and attempt == 1 and not explicit:
            continue
        ok = False
        try:
            ok = resp.status_code < 300 and bool((resp.json() or {}).get("success"))
        except ValueError:
            ok = False
        if ok:
            log.info("provision: %s -> CKAN org %s as %s",
                     username, config.SUBSIDE_CKAN_ORG, config.PROVISION_CKAN_ROLE)
        else:
            # Most common non-fatal case: the user has never logged into CKAN, so
            # CKAN has no account to add yet. Logged, not raised; a later login retries.
            log.warning("provision: CKAN org add failed for %s: HTTP %s %s",
                        username, resp.status_code, resp.text[:200])
        return


def provision_user(username: str, user_token: str | None = None) -> None:
    """Add the user to the group + CKAN org. Best-effort: never raises.

    ``user_token`` (their own login token) lets us provision their CKAN account
    first by authenticating as them; without it the CKAN add still runs but only
    succeeds if they already exist in CKAN.
    """
    if not (config.PROVISION_ON_LOGIN and username):
        return
    try:
        ensure_group_member(username)
    except Exception as exc:  # noqa: BLE001 - provisioning must not break login
        log.warning("provision: group add error for %s: %s", username, exc)
    try:
        ensure_ckan_user(username, user_token)  # materialize their CKAN account first
    except Exception as exc:  # noqa: BLE001
        log.warning("provision: CKAN user provisioning error for %s: %s", username, exc)
    try:
        ensure_ckan_org_member(username)
    except Exception as exc:  # noqa: BLE001
        log.warning("provision: CKAN org add error for %s: %s", username, exc)
