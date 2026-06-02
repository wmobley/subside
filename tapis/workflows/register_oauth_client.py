#!/usr/bin/env python3
"""Register (or rotate) the SUBSIDE Tapis OAuth2 client for the redirect login.

The browser "Log in with TACC" flow needs a registered OAuth client whose
``callback_url`` exactly matches the URL Tapis redirects back to (the frontend
origin). This one-time script creates that client and prints the ``.env`` lines
to paste into the API's config.

Usage:
    # credentials via env (preferred) or interactive prompt
    export TAPIS_USERNAME=... TAPIS_PASSWORD=...
    python workflows/register_oauth_client.py \
        --callback-url http://127.0.0.1:5174/ \
        --client-id subside-portal

Notes:
    * The callback URL must EXACTLY match TAPIS_OAUTH_CALLBACK_URL used by the
      API (including the trailing slash). Use separate clients (or re-run) for
      dev vs. production callback URLs.
    * Re-running with an existing --client-id rotates/recreates it; the new
      client_key is printed. Store the key as a secret (never commit it).
"""

from __future__ import annotations

import argparse
import os
from getpass import getpass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register the SUBSIDE Tapis OAuth client.")
    parser.add_argument("--base-url", default=os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io"))
    parser.add_argument("--client-id", default="subside-portal")
    parser.add_argument("--callback-url", default="https://subside.local:5174/",
                        help="Frontend origin Tapis redirects back to (Tapis requires https). "
                             "Must match TAPIS_OAUTH_CALLBACK_URL.")
    parser.add_argument("--display-name", default="SUBSIDE Portal")
    args = parser.parse_args(argv)

    try:
        from tapipy.tapis import Tapis
    except ImportError:
        raise SystemExit("tapipy is not installed (pip install tapipy).")

    username = os.environ.get("TAPIS_USERNAME") or input("Tapis username: ")
    password = os.environ.get("TAPIS_PASSWORD") or getpass("Tapis password: ")

    t = Tapis(base_url=args.base_url.rstrip("/"), username=username, password=password)
    t.get_tokens()

    # Recreate idempotently: delete an existing client with this id, then create.
    try:
        t.authenticator.delete_client(client_id=args.client_id)
        print(f"Removed existing client {args.client_id!r}.")
    except Exception:
        pass

    res = t.authenticator.create_client(
        client_id=args.client_id,
        callback_url=args.callback_url,
        display_name=args.display_name,
    )
    client_id = getattr(res, "client_id", args.client_id)
    client_key = getattr(res, "client_key", None)
    if not client_key:
        raise SystemExit(f"Client created but no client_key returned: {res}")

    print("\nOAuth client registered. Add these to subside/.env:\n")
    print(f"TAPIS_CLIENT_ID={client_id}")
    print(f"TAPIS_CLIENT_KEY={client_key}")
    print(f"TAPIS_OAUTH_CALLBACK_URL={args.callback_url}")
    print("\nKeep TAPIS_CLIENT_KEY secret — do not commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
