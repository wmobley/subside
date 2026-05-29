"""Tapis client construction from a pass-through user token + password login."""

from __future__ import annotations

import base64
import json

from .config import TAPIS_BASE_URL


def _need_tapipy():
    try:
        from tapipy.tapis import Tapis
        return Tapis
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("tapipy is not installed (pip install tapipy).") from exc


def client_from_token(token: str):
    """Build a tapipy client that acts as the user who owns ``token``.

    Every API call made with this client carries the user's token, so Tapis
    sees normal user operations (not workflows-service-on-behalf-of) — that is
    what sidesteps the restricted-service block for job submission.
    """
    Tapis = _need_tapipy()
    client = Tapis(base_url=TAPIS_BASE_URL, jwt=token)
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
