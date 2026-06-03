#!/usr/bin/env python3
"""Register (or rotate) the SUBSIDE Tapis OAuth2 client for the redirect login.

The browser "Log in with TACC" flow needs a registered OAuth client whose
``callback_url`` exactly matches the URL Tapis redirects back to (the frontend
origin). This script (re)creates that client and writes the resulting
``TAPIS_CLIENT_ID`` / ``TAPIS_CLIENT_KEY`` / ``TAPIS_OAUTH_CALLBACK_URL`` into
``subside/.env`` so they can never drift from the live client.

It is also imported by ``tapis/register_pods.py``, which calls
``register_and_write_env()`` with its already-authenticated Tapis session right
before deploying the pods — so a fresh key is always written and picked up.

Usage:
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...   # or you'll be prompted
    python tapis/workflows/register_oauth_client.py \
        --callback-url https://subsideui.pods.portals.tapis.io/ \
        --client-id subside-portal-prod

Notes:
    * The callback URL must EXACTLY match TAPIS_OAUTH_CALLBACK_URL used by the
      API (including the trailing slash). Use separate clients (or re-run) for
      dev vs. production callback URLs.
    * Idempotent and non-destructive: an existing client is UPDATED in place
      (callback) and its existing client_key is read back and written to .env —
      the key is NOT rotated. (We don't delete+recreate: Tapis's delete is
      eventually-consistent, so an immediate recreate trips a uniqueness error.)
      register_pods.py still does this itself just before deploying the API pod,
      so .env and the pod always carry the live key.
"""

from __future__ import annotations

import argparse
import os
from getpass import getpass
from pathlib import Path

# subside/.env — parents: [0]=workflows, [1]=tapis, [2]=subside.
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Keys this script owns in .env.
CLIENT_ID_KEY = "TAPIS_CLIENT_ID"
CLIENT_KEY_KEY = "TAPIS_CLIENT_KEY"
CALLBACK_KEY = "TAPIS_OAUTH_CALLBACK_URL"


def write_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    """Insert or replace ``KEY=value`` lines in ``env_path`` in place.

    Existing lines for the given keys are rewritten where they sit (preserving
    order and surrounding comments); missing keys are appended. Other lines are
    left untouched. Creates the file if absent.
    """
    env_path = Path(env_path)
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        key = stripped.split("=", 1)[0].strip() if ("=" in stripped and not stripped.startswith("#")) else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():  # keys not already present
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n")


def _is_exists_conflict(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "already exists" in msg or "uniqueness" in msg


def register_oauth_client(t, *, client_id: str, callback_url: str,
                          display_name: str = "SUBSIDE Portal") -> tuple[str, str]:
    """Ensure the OAuth client exists with the given callback; return (id, key).

    Idempotent and NON-destructive: tries to create the client, and if it already
    exists, updates its callback in place and reads the existing ``client_key``
    back via ``get_client`` (so the key is NOT rotated — anything already holding
    it stays valid). We deliberately do NOT delete+recreate: Tapis's delete is
    eventually-consistent, so an immediate recreate trips a uniqueness constraint.
    Does NOT touch .env — see ``register_and_write_env``.
    """
    # 1. Try to create fresh.
    try:
        res = t.authenticator.create_client(
            client_id=client_id, callback_url=callback_url, display_name=display_name)
        key = getattr(res, "client_key", None)
        if key:
            print(f"Created OAuth client {client_id!r}.")
            return getattr(res, "client_id", client_id), key
    except Exception as exc:
        if not _is_exists_conflict(exc):
            raise
        print(f"OAuth client {client_id!r} exists; updating callback in place.")

    # 2. Already exists (or create didn't echo a key): update callback, read key.
    try:
        t.authenticator.update_client(
            client_id=client_id, callback_url=callback_url, display_name=display_name)
    except Exception as exc:
        print(f"  warning: update_client failed ({exc}); using the existing client as-is.")

    got = t.authenticator.get_client(client_id=client_id)
    key = getattr(got, "client_key", None)
    if not key:
        raise RuntimeError(
            f"Client {client_id!r} exists but Tapis did not return its client_key. "
            f"Delete it (t.authenticator.delete_client(client_id={client_id!r})) and "
            f"re-run, or pass a different --oauth-client-id.")
    return getattr(got, "client_id", client_id), key


def register_and_write_env(t, *, client_id: str, callback_url: str,
                           display_name: str = "SUBSIDE Portal",
                           env_path: Path = DEFAULT_ENV_PATH) -> tuple[str, str]:
    """Register the client and persist id/key/callback into ``env_path``."""
    cid, key = register_oauth_client(
        t, client_id=client_id, callback_url=callback_url, display_name=display_name)
    write_env_vars(env_path, {
        CLIENT_ID_KEY: cid,
        CLIENT_KEY_KEY: key,
        CALLBACK_KEY: callback_url,
    })
    return cid, key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register the SUBSIDE Tapis OAuth client.")
    parser.add_argument("--base-url", default=os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io"))
    parser.add_argument("--client-id", default="subside-portal-prod")
    parser.add_argument("--callback-url", default="https://subside.local:5174/",
                        help="Frontend origin Tapis redirects back to (Tapis requires https). "
                             "Must match TAPIS_OAUTH_CALLBACK_URL.")
    parser.add_argument("--display-name", default="SUBSIDE Portal")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH),
                        help="Path to the .env file to write (default: subside/.env).")
    args = parser.parse_args(argv)

    try:
        from tapipy.tapis import Tapis
    except ImportError:
        raise SystemExit("tapipy is not installed (pip install tapipy).")

    username = os.environ.get("TAPIS_USERNAME") or input("Tapis username: ")
    password = os.environ.get("TAPIS_PASSWORD") or getpass("Tapis password: ")

    t = Tapis(base_url=args.base_url.rstrip("/"), username=username, password=password)
    t.get_tokens()

    cid, _key = register_and_write_env(
        t, client_id=args.client_id, callback_url=args.callback_url,
        display_name=args.display_name, env_path=Path(args.env_file))

    print(f"\nOAuth client {cid!r} registered; wrote {CLIENT_ID_KEY}/{CLIENT_KEY_KEY}/"
          f"{CALLBACK_KEY} to {args.env_file}")
    print(f"  callback_url = {args.callback_url}")
    print("Keep TAPIS_CLIENT_KEY secret — .env is gitignored; do not commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
