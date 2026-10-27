#!/usr/bin/env python3
"""Test only the Tapis OAuth access-token refresh path.

This script deliberately does not mint run tokens, submit workflows, call the
Subside API, or revoke anything. It checks the Tapis password grant to see
whether a refresh token is available, then exercises the same refresh helper
used by the API when a refresh token is supplied.

Examples::

    # Use the burner credentials, report whether password login returns a
    # refresh token, and stop if it does not.
    python api/scripts/test_refresh.py --env-file .env.burner

    # Test an OAuth refresh token without putting it in the process argv.
    TAPIS_REFRESH_TOKEN='...' \\
        python api/scripts/test_refresh.py --env-file .env.burner

    # Or read the refresh token from a protected file.
    python api/scripts/test_refresh.py --env-file .env.burner \\
        --refresh-token-file /path/to/refresh-token

The refresh grant may rotate the refresh token. If it does, the script reports
that fact but never prints either token.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
SUBSIDE_ROOT = HERE.parents[2]
if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))


def _load_env_file(path: Path) -> None:
    """Load simple dotenv assignments without overwriting explicit env vars."""
    if not path.exists():
        raise SystemExit(f"Environment file not found: {path}")
    assignment = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = assignment.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            # .env.burner has a few unquoted inline comments. Keep literal
            # '#' characters unless the comment is separated by whitespace.
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def _token_from_file(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Refresh-token file not found: {path}")
    token = path.read_text().strip()
    if not token:
        raise SystemExit(f"Refresh-token file is empty: {path}")
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=SUBSIDE_ROOT / ".env.burner",
        help="dotenv file for Tapis settings (default: subside/.env.burner)",
    )
    parser.add_argument(
        "--refresh-token-file",
        type=Path,
        help="read the refresh token from a file instead of TAPIS_REFRESH_TOKEN",
    )
    args = parser.parse_args()
    _load_env_file(args.env_file)

    # Import after loading the selected env file because api.config reads its
    # settings at import time.
    from api.services import tapis

    username = os.environ.get("TAPIS_USERNAME") or os.environ.get("SUBSIDE_ADMIN_USERNAME")
    password = os.environ.get("TAPIS_PASSWORD") or os.environ.get("SUBSIDE_ADMIN_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "Set TAPIS_USERNAME/TAPIS_PASSWORD or "
            "SUBSIDE_ADMIN_USERNAME/SUBSIDE_ADMIN_PASSWORD."
        )

    print(f"Tapis base URL: {tapis.TAPIS_BASE_URL}")
    client_configured = bool(tapis.config.TAPIS_CLIENT_ID and tapis.config.TAPIS_CLIENT_KEY)
    client_partial = bool(tapis.config.TAPIS_CLIENT_ID) != bool(tapis.config.TAPIS_CLIENT_KEY)
    if client_partial:
        print("OAuth client authentication: INVALID (both client values are required)")
    else:
        print(f"OAuth client authentication: {'configured' if client_configured else 'not configured'}")
    print("1. Password grant")
    try:
        login_result = tapis.login_with_tokens(username, password)
    except Exception as exc:
        print(f"   FAIL: password grant did not complete ({type(exc).__name__})")
        return 1

    password_refresh = login_result.get("refresh_token")
    print("   PASS: access token returned")
    print(f"   refresh token returned: {'yes' if password_refresh else 'no'}")

    refresh_token = password_refresh
    if args.refresh_token_file:
        refresh_token = _token_from_file(args.refresh_token_file)
    elif os.environ.get("TAPIS_REFRESH_TOKEN"):
        refresh_token = os.environ["TAPIS_REFRESH_TOKEN"].strip()

    if not refresh_token:
        print("2. Refresh grant: NOT RUN")
        print(
            "   Tapis password grant did not return a refresh token. "
            "Supply TAPIS_REFRESH_TOKEN or --refresh-token-file from the "
            "OAuth authorization-code flow."
        )
        return 2

    print("2. Refresh grant")
    try:
        refreshed = tapis.refresh_user_token(refresh_token)
    except Exception as exc:
        print(f"   FAIL: refresh grant rejected ({type(exc).__name__})")
        return 1

    rotated = refreshed.get("refresh_token")
    print("   PASS: replacement access token returned")
    print(f"   refresh token rotated: {'yes' if rotated and rotated != refresh_token else 'no'}")
    print("RESULT: refresh logic passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
