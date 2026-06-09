"""PostGIS connectivity for the vector-layer endpoints.

A lazily-built psycopg connection pool over ``SUBSIDE_DATABASE_URL`` (the
postgres *wire* endpoint behind the PostGIS database — not the PostgREST HTTP
URL). Like ``discovery.py`` with its geospatial deps, anything that needs the DB
raises :class:`DbUnavailable` (-> 503) when the URL is unset or the server is
unreachable, so the core Tapis API keeps working without a database.

The pool is created once, on first use, and bootstraps the schema PostGIS needs:
the extension, a dedicated schema (``SUBSIDE_MVT_SCHEMA``), and a ``layers``
registry table that records what ``layers.py`` has ingested.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from .. import config


class DbUnavailable(RuntimeError):
    """Raised when SUBSIDE_DATABASE_URL is unset or the database is unreachable."""


_pool = None
_pool_lock = threading.Lock()


def _need_psycopg():
    try:
        import psycopg  # noqa: F401
        from psycopg_pool import ConnectionPool
        return ConnectionPool
    except ImportError as exc:  # pragma: no cover
        raise DbUnavailable(
            "PostGIS layers need psycopg: pip install 'psycopg[binary]' psycopg-pool"
        ) from exc


def _bootstrap(conn) -> None:
    """Idempotently ensure PostGIS, the API's schema, and the layer registry."""
    from psycopg import sql

    schema = sql.Identifier(config.MVT_SCHEMA)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.layers (
                    name        text PRIMARY KEY,
                    geom_type   text NOT NULL DEFAULT 'Geometry',
                    srid        integer NOT NULL DEFAULT 4326,
                    columns     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at  timestamptz NOT NULL DEFAULT now(),
                    updated_at  timestamptz NOT NULL DEFAULT now()
                )
                """
            ).format(schema)
        )
        # Per-frame OPERA DISP-S1 availability cache backing the viewport-lazy
        # /availability endpoint (see availability.py). One row per frame: its
        # product timeline (so any date-window question is answered locally) plus
        # checked_at for the daily TTL.
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.frame_availability (
                    frame_id      bigint PRIMARY KEY,
                    product_count integer NOT NULL DEFAULT 0,
                    latest_date   date,
                    timeline      jsonb NOT NULL DEFAULT '[]'::jsonb,
                    checked_at    timestamptz NOT NULL DEFAULT now()
                )
                """
            ).format(schema)
        )
    conn.commit()


def get_pool():
    """Return the process-wide connection pool, creating it on first use."""
    global _pool
    if _pool is not None:
        return _pool
    if not config.DATABASE_URL:
        raise DbUnavailable(
            "SUBSIDE_DATABASE_URL is not set; vector-layer endpoints are disabled."
        )
    ConnectionPool = _need_psycopg()
    with _pool_lock:
        if _pool is None:
            try:
                pool = ConnectionPool(
                    conninfo=config.DATABASE_URL,
                    min_size=1,
                    max_size=4,
                    open=True,
                    kwargs={"autocommit": False},
                )
                with pool.connection() as conn:
                    _bootstrap(conn)
            except DbUnavailable:
                raise
            except Exception as exc:  # connection refused, auth, DNS, TLS, ...
                raise DbUnavailable(f"Cannot connect to PostGIS: {exc}") from exc
            _pool = pool
    return _pool


@contextmanager
def connection():
    """Yield a pooled connection.

    Connect/acquire failures surface as :class:`DbUnavailable` (-> 503) via
    :func:`get_pool`. Errors raised *inside* the ``with`` body (e.g. a bad
    GeoJSON insert) propagate unchanged so routes can map them to 400/500.
    """
    pool = get_pool()
    with pool.connection() as conn:
        yield conn
