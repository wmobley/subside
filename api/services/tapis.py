"""Tapis client construction from a pass-through user token + password login."""

from __future__ import annotations

import base64
import json

from .. import config

from ..config import (
    TAPIS_BASE_URL, TAPIS_CLIENT_ID, TAPIS_CLIENT_KEY, TAPIS_OAUTH_CALLBACK_URL,
)


class OAuthNotConfigured(RuntimeError):
    """No Tapis OAuth client configured (TAPIS_CLIENT_ID/KEY unset)."""


class TokenMintError(RuntimeError):
    """The Tapis Tokens API could not mint a run token."""


class TokenRevokeError(RuntimeError):
    """The Tapis Tokens API could not revoke a run token."""


class OAuthRefreshError(RuntimeError):
    """The Tapis OAuth refresh grant could not issue a new access token."""


class JobsSearchError(RuntimeError):
    """The authenticated Jobs API search could not be completed."""


def _need_tapipy():
    try:
        from tapipy.tapis import Tapis
        return Tapis
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("tapipy is not installed (pip install tapipy).") from exc


def client_from_token(token: str):
    """Build a tapipy client that acts as the user who owns ``token``.

    Every API call made with this client carries the user's token, so Tapis sees
    normal user operations for Workflows submission and Files/Jobs inspection.
    """
    Tapis = _need_tapipy()
    client = Tapis(base_url=TAPIS_BASE_URL, jwt=token)
    try:
        client.subside_access_token = token
    except Exception:
        pass
    # tapipy doesn't populate .username from a bare jwt; derive it from the claim
    # so we can build the per-user staging path.
    username = username_from_token(token)
    if username:
        try:
            client.username = username
        except Exception:
            pass
    return client


def username_from_token(token: str) -> str | None:
    """Decode the (unverified) JWT payload to read the Tapis username claim.

    The token belongs to the caller; we only read it to build their staging
    path, we do not trust it for authz (Tapis enforces that server-side)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad base64
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return None
    return (
        claims.get("tapis/username")
        or claims.get("username")
        or claims.get("sub")
    )


def oauth_public_config() -> dict | None:
    """Non-secret bits the browser needs to build the authorize redirect.

    Returns None when no OAuth client is configured, so the API can advertise
    that the redirect login is unavailable (the endpoint maps that to 503).
    """
    if not (TAPIS_CLIENT_ID and TAPIS_OAUTH_CALLBACK_URL):
        return None
    return {
        "base_url": TAPIS_BASE_URL,
        "client_id": TAPIS_CLIENT_ID,
        "callback_url": TAPIS_OAUTH_CALLBACK_URL,
        "authorize_url": f"{TAPIS_BASE_URL}/v3/oauth2/authorize",
    }


def exchange_code(code: str) -> dict:
    """Exchange an OAuth2 authorization code for a Tapis access token.

    Server-side leg of the 3-legged flow: POSTs to the tenant's token endpoint
    with HTTP Basic ``client_id:client_key`` and the same ``redirect_uri`` used
    in the authorize request. The client_key never leaves the server.
    Returns ``{token, username, expires_at, refresh_token}``.
    """
    if not (TAPIS_CLIENT_ID and TAPIS_CLIENT_KEY):
        raise OAuthNotConfigured(
            "No Tapis OAuth client configured. Set TAPIS_CLIENT_ID and "
            "TAPIS_CLIENT_KEY (see workflows/register_oauth_client.py)."
        )
    import requests

    resp = requests.post(
        f"{TAPIS_BASE_URL}/v3/oauth2/tokens",
        auth=(TAPIS_CLIENT_ID, TAPIS_CLIENT_KEY),
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": TAPIS_OAUTH_CALLBACK_URL,
        },
        timeout=30,
    )
    if resp.status_code >= 400:
        # Surface Tapis's message (e.g. invalid/expired code) to the caller.
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text[:300]}")
    result = (resp.json() or {}).get("result") or {}
    access = result.get("access_token") or {}
    token = access.get("access_token")
    if not token:
        raise RuntimeError("Token exchange returned no access_token.")
    refresh = (result.get("refresh_token") or {}).get("refresh_token")
    return {
        "token": token,
        "username": username_from_token(token) or "",
        "expires_at": access.get("expires_at"),
        "refresh_token": refresh,
    }


def login_with_tokens(username: str, password: str) -> dict:
    """Exchange username/password for the access and refresh token pair."""
    import requests

    client_id = config.TAPIS_CLIENT_ID
    client_key = config.TAPIS_CLIENT_KEY
    if bool(client_id) != bool(client_key):
        raise OAuthNotConfigured(
            "Tapis OAuth client configuration is incomplete; set both "
            "TAPIS_CLIENT_ID and TAPIS_CLIENT_KEY."
        )
    request_kwargs = {
        "json": {"username": username, "password": password, "grant_type": "password"},
        "timeout": 30,
    }
    if client_id and client_key:
        request_kwargs["auth"] = (client_id, client_key)

    try:
        resp = requests.post(
            f"{TAPIS_BASE_URL}/v3/oauth2/tokens",
            **request_kwargs,
        )
    except Exception as exc:
        raise RuntimeError("Tapis password-grant request failed.") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"Tapis password-grant failed (HTTP {resp.status_code}).")
    try:
        result = (resp.json() or {}).get("result") or {}
        access = result.get("access_token") or {}
        token = access.get("access_token")
        refresh = (result.get("refresh_token") or {}).get("refresh_token")
    except Exception as exc:
        raise RuntimeError("Tapis password-grant returned an invalid response.") from exc
    if not token:
        raise RuntimeError("Login succeeded but no access token was returned.")
    return {
        "token": token,
        "username": username_from_token(token) or username,
        "expires_at": access.get("expires_at"),
        "refresh_token": refresh,
    }


def login(username: str, password: str) -> str:
    """Exchange username/password for a Tapis access token (password grant)."""
    return login_with_tokens(username, password)["token"]


def refresh_user_token(refresh_token: str) -> dict:
    """Exchange a server-stored OAuth refresh token for a rotated token pair."""
    if not config.TAPIS_CLIENT_ID or not config.TAPIS_CLIENT_KEY:
        raise OAuthRefreshError("OAuth client credentials are not configured.")
    import requests
    try:
        resp = requests.post(
            f"{config.TAPIS_BASE_URL}/v3/oauth2/tokens",
            auth=(config.TAPIS_CLIENT_ID, config.TAPIS_CLIENT_KEY),
            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=30,
        )
    except Exception as exc:
        raise OAuthRefreshError("Tapis OAuth refresh request failed.") from exc
    if resp.status_code >= 400:
        raise OAuthRefreshError(f"Tapis OAuth refresh failed (HTTP {resp.status_code}).")
    try:
        result = (resp.json() or {}).get("result") or {}
        access = result.get("access_token") or {}
        token = access.get("access_token")
        rotated = (result.get("refresh_token") or {}).get("refresh_token")
    except Exception as exc:
        raise OAuthRefreshError("Tapis OAuth refresh returned an invalid response.") from exc
    if not token:
        raise OAuthRefreshError("Tapis OAuth refresh returned no access token.")
    return {
        "token": token,
        "expires_at": access.get("expires_at"),
        "refresh_token": rotated or refresh_token,
    }


def mint_run_token(caller_token: str, username: str, target_site_id: str, ttl_seconds: int) -> dict:
    """Mint a bounded user token through the verified Tokens API contract.

    The raw token is returned to the caller for immediate encrypted persistence;
    this function never logs it or includes response bodies in exceptions.
    """
    try:
        ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise TokenMintError("Tapis run-token TTL must be a positive integer.") from exc
    if ttl <= 0:
        raise TokenMintError("Tapis run-token TTL must be a positive integer.")

    import requests

    body = {
        "token_tenant_id": "portals",
        "account_type": "user",
        "token_username": username,
        "target_site_id": target_site_id,
        "access_token_ttl": ttl,
    }
    try:
        resp = requests.post(
            f"{config.TAPIS_BASE_URL}/v3/tokens",
            headers={"X-Tapis-Token": caller_token, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
    except Exception as exc:
        raise TokenMintError("Tapis run-token mint request failed.") from exc
    if resp.status_code >= 400:
        raise TokenMintError(f"Tapis run-token mint failed (HTTP {resp.status_code}).")
    try:
        result = (resp.json() or {}).get("result") or {}
        access = result.get("access_token") or {}
        token = access.get("access_token")
    except Exception as exc:
        raise TokenMintError("Tapis run-token mint returned an invalid response.") from exc
    if not token:
        raise TokenMintError("Tapis run-token mint returned no access token.")
    return {
        "token": token,
        "expires_at": access.get("expires_at"),
        "expires_in": access.get("expires_in"),
    }


def revoke_token(auth_token: str, token: str) -> None:
    """Revoke a JWT through POST /v3/tokens/revoke without exposing it."""
    import requests

    try:
        resp = requests.post(
            f"{config.TAPIS_BASE_URL}/v3/tokens/revoke",
            headers={"X-Tapis-Token": auth_token, "Content-Type": "application/json"},
            json={"token": token},
            timeout=30,
        )
    except Exception as exc:
        raise TokenRevokeError("Tapis run-token revoke request failed.") from exc
    if resp.status_code >= 400:
        raise TokenRevokeError(f"Tapis run-token revoke failed (HTTP {resp.status_code}).")


_JOB_SEARCH_FIELDS = (
    "uuid", "name", "owner", "tenant", "appId", "appVersion", "status",
    "condition", "created", "ended", "lastUpdated", "execSystemId",
    "archiveSystemId", "archiveSystemDir", "maxMinutes", "remoteOutcome",
    "remoteResultInfo",
)


def search_jobs(client, *, name: str | None = None, app_id: str | None = None,
                created_after: str | None = None, limit: int = 100) -> list[dict]:
    """Search Jobs using only allowlisted fields and the caller's token.

    The search endpoint is intentionally kept here instead of depending on a
    tapipy version-specific ``jobs.search`` shape. Results are sanitized before
    they reach reconciliation code, and response bodies are never included in
    exception text.
    """
    token = getattr(client, "subside_access_token", None) or ""
    if not token:
        raise JobsSearchError("Jobs search requires an authenticated Tapis token.")
    base_url = getattr(client, "base_url", None) or config.TAPIS_BASE_URL
    params = {"limit": max(1, min(int(limit), 1000)), "skip": 0}
    if name:
        params["name.eq"] = name
    if app_id:
        params["appId.eq"] = app_id
    if created_after:
        params["created.gt"] = created_after
    import requests

    try:
        resp = requests.get(
            f"{str(base_url).rstrip('/')}/v3/jobs/search",
            headers={"X-Tapis-Token": str(token)},
            params=params,
            timeout=30,
        )
    except Exception as exc:
        raise JobsSearchError("Tapis Jobs search request failed.") from exc
    if resp.status_code >= 400:
        raise JobsSearchError(f"Tapis Jobs search failed (HTTP {resp.status_code}).")
    try:
        result = (resp.json() or {}).get("result") or []
        if isinstance(result, dict):
            result = result.get("jobs") or result.get("items") or result.get("results") or []
        if not isinstance(result, list):
            raise ValueError("result is not a list")
    except Exception as exc:
        raise JobsSearchError("Tapis Jobs search returned an invalid response.") from exc
    return [
        {field: item.get(field) for field in _JOB_SEARCH_FIELDS if field in item}
        for item in result if isinstance(item, dict)
    ]
