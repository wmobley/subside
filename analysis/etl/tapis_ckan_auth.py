"""Obtain a CKAN-usable bearer token from Tapis via the password grant.

ckan.tacc.utexas.edu is fronted by Tapis auth, so a Tapis access-token JWT works
directly as the CKAN bearer token (the same thing the SUBSIDE UI relies on).

Reads from the environment:
  TAPIS_BASE_URL  (default https://portals.tapis.io)
  TAPIS_USERNAME
  TAPIS_PASSWORD

Usage:
    from tapis_ckan_auth import ckan_token_from_tapis
    token = ckan_token_from_tapis()      # -> JWT string
"""
from __future__ import annotations

import os


def ckan_token_from_tapis(
    username: str | None = None,
    password: str | None = None,
    base_url: str | None = None,
) -> str:
    """Return a Tapis access-token JWT usable as the CKAN bearer token."""
    base_url = (base_url or os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io")).rstrip("/")
    username = username or os.environ.get("TAPIS_USERNAME")
    password = password or os.environ.get("TAPIS_PASSWORD")
    if not (username and password):
        raise SystemExit(
            "Set TAPIS_USERNAME and TAPIS_PASSWORD (env or subside/.env) to mint a CKAN token."
        )
    # Imported lazily so the module loads even where tapipy isn't installed.
    from tapipy.tapis import Tapis

    t = Tapis(base_url=base_url, username=username, password=password)
    t.get_tokens()
    return t.access_token.access_token


if __name__ == "__main__":
    # Print only a redacted confirmation, never the token itself.
    tok = ckan_token_from_tapis()
    print(f"Tapis token acquired (JWT, {tok.count('.') + 1} segments, len={len(tok)}).")
