"""Tapis client construction from a pass-through user token + password login."""

from __future__ import annotations

import base64
import json

from .config import (
    TAPIS_BASE_URL, TAPIS_CLIENT_ID, TAPIS_CLIENT_KEY, TAPIS_OAUTH_CALLBACK_URL,
)


class OAuthNotConfigured(RuntimeError):
    """No Tapis OAuth client configured (TAPIS_CLIENT_ID/KEY unset)."""


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


def login(username: str, password: str) -> str:
    """Exchange username/password for a Tapis access token (password grant)."""
    Tapis = _need_tapipy()
    client = Tapis(base_url=TAPIS_BASE_URL, username=username, password=password)
    client.get_tokens()
    access = getattr(client, "access_token", None)
    token = getattr(access, "access_token", None) or str(access) if access else None
    if not token:
        raise RuntimeError("Login succeeded but no access token was returned.")
    return token
