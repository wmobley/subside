#!/usr/bin/env python3
"""Diagnose the SUBSIDE Postgres/PostGIS connection (SUBSIDE_DATABASE_URL).

Standalone — no third-party deps. Drives the local ``psql``/``openssl`` clients
and passes the password via libpq ``PG*`` env vars, so the secret never lands in
``ps`` output or this script's logs.

What it checks, in order:
  1. SUBSIDE_DATABASE_URL is set (read from subside/.env, then the environment).
  2. The dbname isn't the ``DBNAME`` placeholder from .env.sample.
  3. The TLS tunnel answers for this SNI host (openssl) — independent of Postgres.
  4. Postgres auth + a live query (psql), using sslnegotiation=direct for the
     Tapis pods 443 TLS-SNI tunnel.
  5. If the target db is missing, it retries against the ``postgres`` maintenance
     db and lists the databases that DO exist — so you can fill in the real name.
  6. PostGIS extension, schemas, and whether the API's tables exist yet.

Run:  cd subside && python3 api/check_db.py
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import parse_qsl, urlsplit

HERE = pathlib.Path(__file__).resolve().parent
ENV_FILE = HERE.parent.parent / ".env"   # api/scripts -> api -> subside   # subside/.env
PLACEHOLDER_DBNAMES = {"", "dbname"}


def _load_env_url() -> str | None:
    """SUBSIDE_DATABASE_URL from the environment, falling back to subside/.env."""
    if os.environ.get("SUBSIDE_DATABASE_URL"):
        return os.environ["SUBSIDE_DATABASE_URL"]
    if not ENV_FILE.exists():
        return None
    for raw in ENV_FILE.read_text().splitlines():
        s = raw.strip()
        if s.startswith("#") or "SUBSIDE_DATABASE_URL" not in s:
            continue
        if s.lower().startswith("export "):
            s = s[7:].strip()
        key, _, val = s.partition("=")
        if key.strip() == "SUBSIDE_DATABASE_URL":
            return val.strip().strip('"').strip("'")
    return None


def _pg_env(url: str, dbname: str) -> dict[str, str]:
    """libpq PG* env for psql — keeps the password out of argv."""
    u = urlsplit(url)
    q = dict(parse_qsl(u.query))
    sslmode = q.get("sslmode", "require")
    if sslmode in {"", "prefer", "allow", "disable"}:
        sslmode = "require"  # direct negotiation needs require or stronger
    env = dict(os.environ)
    env.update({
        "PGHOST": u.hostname or "",
        "PGPORT": str(u.port or 5432),
        "PGUSER": u.username or "",
        "PGPASSWORD": u.password or "",
        "PGDATABASE": dbname,
        "PGSSLMODE": sslmode,
        "PGSSLNEGOTIATION": q.get("sslnegotiation", "direct"),
        "PGCONNECT_TIMEOUT": "15",
    })
    return env


def _psql(env: dict[str, str], sql: str) -> tuple[bool, str]:
    """Run one SQL statement; return (ok, trimmed_output_or_error)."""
    proc = subprocess.run(
        ["psql", "-X", "-A", "-t", "-w", "-c", sql],
        env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip()
    return True, proc.stdout.strip()


def _tls_probe(host: str, port: int) -> None:
    if not shutil.which("openssl"):
        print("  · openssl not found — skipping raw TLS probe.")
        return
    proc = subprocess.run(
        ["openssl", "s_client", "-servername", host, "-connect", f"{host}:{port}", "-brief"],
        input="", capture_output=True, text=True, timeout=20,
    )
    blob = (proc.stderr + proc.stdout).lower()
    if "connection established" in blob or "verification" in blob or "protocol" in blob:
        print(f"  ✓ TLS tunnel answers for SNI {host}:{port}")
    else:
        print(f"  ✗ No TLS response from {host}:{port} — host/port/network issue, not Postgres.")
        snippet = (proc.stderr or proc.stdout).strip().splitlines()[:3]
        for line in snippet:
            print("      ", line)


def main() -> int:
    print("SUBSIDE Postgres connection check\n" + "=" * 34)
    url = _load_env_url()
    if not url:
        print("✗ SUBSIDE_DATABASE_URL is not set (checked the environment and subside/.env).")
        print("  → Add it to subside/.env and SAVE the file, then re-run. Template:")
        print("    SUBSIDE_DATABASE_URL=postgresql://USER:PASS@HOST:443/REALDB"
              "?sslmode=require&sslnegotiation=direct")
        return 2

    u = urlsplit(url)
    host, port = u.hostname or "", u.port or 5432
    target_db = (u.path or "/").lstrip("/")
    print(f"host   : {host}")
    print(f"port   : {port}")
    print(f"user   : {u.username}")
    print(f"dbname : {target_db or '(empty)'}")
    placeholder = target_db.lower() in PLACEHOLDER_DBNAMES
    if placeholder:
        print("  ⚠ dbname looks like the .env.sample placeholder — will discover the real name.")
    print()

    if not shutil.which("psql"):
        print("✗ psql not found on PATH. Install libpq (brew install libpq) and retry.")
        return 2

    print("1) Raw TLS reachability")
    try:
        _tls_probe(host, port)
    except Exception as exc:
        print("  · TLS probe error:", exc)
    print()

    # Connect to the target db; if it's a placeholder/missing, use 'postgres'.
    first_db = "postgres" if placeholder else target_db
    print(f"2) Postgres auth + query (db='{first_db}', sslnegotiation=direct)")
    env = _pg_env(url, first_db)
    ok, out = _psql(env, "select version(), current_database(), current_user;")
    if not ok and not placeholder and "does not exist" in out.lower():
        print(f"  ⚠ database {target_db!r} does not exist — retrying against 'postgres'.")
        first_db = "postgres"
        env = _pg_env(url, first_db)
        ok, out = _psql(env, "select version(), current_database(), current_user;")
    if not ok:
        print("  ✗ Could not connect / authenticate:")
        for line in out.splitlines()[:6]:
            print("      ", line)
        print("\n  Common causes: wrong password, wrong dbname, or the tunnel needs")
        print("  sslnegotiation=direct (libpq < 17 cannot do TLS-first and will fail here).")
        return 1
    ver, curdb, curuser = (out.split("|") + ["", "", ""])[:3]
    print(f"  ✓ connected as {curuser} to db {curdb}")
    print(f"    {ver[:70]}")
    print()

    print("3) Databases on this server")
    ok, out = _psql(env, "select datname from pg_database where datistemplate=false order by 1;")
    dbs = [d for d in out.splitlines() if d] if ok else []
    for d in dbs:
        marker = "  ← your SUBSIDE_DATABASE_URL points here" if d == target_db else ""
        print(f"  · {d}{marker}")
    if placeholder or target_db not in dbs:
        guess = next((d for d in dbs if d not in {"postgres", "template0", "template1"}), None)
        print("\n  → Set the dbname in SUBSIDE_DATABASE_URL to one of the above"
              + (f" (likely '{guess}')." if guess else "."))
    print()

    # Inspect the database the API will actually use, if it exists.
    inspect_db = target_db if (target_db in dbs and not placeholder) else first_db
    env = _pg_env(url, inspect_db)
    print(f"4) PostGIS + schema state (db='{inspect_db}')")
    ok, out = _psql(env, "select extversion from pg_extension where extname='postgis';")
    print(f"  · PostGIS: {('installed v'+out) if (ok and out) else 'NOT installed (CREATE EXTENSION postgis needed)'}")
    schema = os.environ.get("SUBSIDE_MVT_SCHEMA", "subside")
    for tbl in (f"{schema}.layers", f"{schema}.frame_availability"):
        ok, out = _psql(env, f"select to_regclass('{tbl}');")
        exists = ok and out and out != ""
        print(f"  · table {tbl}: {'exists' if exists else 'not created yet (API bootstrap will create it)'}")

    print("\nVerdict: connection works." if dbs else "\nVerdict: see errors above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
