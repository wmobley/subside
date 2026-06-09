"""Viewport-lazy OPERA DISP-S1 availability cache.

Backs a "where is data available" map without a Tapis job and without ever
touching ASF on the hot tile path:

  * Frame footprints are served as an ordinary MVT layer (``layers.py``) — the
    map shows every frame instantly, and ``mvt_tile`` already returns only the
    frames intersecting each requested tile, so "in view" is free.
  * The client asks this module for availability over the current viewport
    (:func:`availability_for_bbox`). Frames intersecting the bbox are read from
    the ``frame_availability`` cache and returned immediately.
  * Frames missing from the cache, or older than ``ttl_hours`` (default 24 — the
    "daily cache"), are handed back as a stale list. The route schedules
    :func:`refresh_frames` for them in a background task, so the *next* poll is
    populated. A cron can call :func:`refresh_all` to warm everything off-path.

Because each frame's full product *timeline* is cached (not a per-date-window
boolean), any "available between X and Y?" question is answered locally from the
cache without re-hitting ASF — see :func:`_count_in_window`.

ASF product search needs disp_xr/opera_utils (reached via
``analysis.h2i_lab.aoi``), so those imports stay lazy and missing deps
surface as :class:`~api.discovery.DiscoveryUnavailable` (-> 503).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .. import config
from . import db
from ..config import SUBSIDE_ROOT
from .discovery import DiscoveryUnavailable

# analysis lives at subside/analysis (same hook discovery.py uses).
if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))

DEFAULT_LAYER = "satellite"
DEFAULT_FRAME_ID_COLUMN = "frame_id"
DEFAULT_TTL_HOURS = 24


def _safe_ident(name: str) -> str:
    """Validate a caller-supplied table/column identifier (reuses layers' rule)."""
    from .layers import _ident

    return _ident(name)


# --- frame geometry lookups (from the loaded footprint layer) --------------
def frames_in_bbox(
    bbox: list[float],
    layer: str = DEFAULT_LAYER,
    frame_id_column: str = DEFAULT_FRAME_ID_COLUMN,
) -> list[tuple[int, list[float]]]:
    """Frames whose footprint intersects ``bbox`` = [minLon, minLat, maxLon, maxLat].

    Returns ``[(frame_id, [w, s, e, n]), ...]`` — each frame's own footprint
    bbox rides along so a UI click on a frame can become an AOI without a second
    request. Uses the GiST-indexed ``&&`` overlap operator, so it stays fast even
    at low zoom. The frame-footprint layer must already be loaded via
    ``layers.create_or_load`` (e.g. ``"satellite"``)."""
    from psycopg import sql

    name = _safe_ident(layer)
    col = _safe_ident(frame_id_column)
    tbl = sql.Identifier(config.MVT_SCHEMA, name)
    with db.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                sql.SQL(
                    "SELECT {col}::bigint, "
                    "ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)), "
                    "ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)) "
                    "FROM {tbl} "
                    "WHERE {col} IS NOT NULL "
                    "AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326) "
                    "GROUP BY {col}"
                ).format(col=sql.Identifier(col), tbl=tbl),
                (bbox[0], bbox[1], bbox[2], bbox[3]),
            )
            rows = cur.fetchall()
        except Exception as exc:  # missing layer / missing frame-id column
            conn.rollback()
            raise ValueError(
                f"Could not read frame ids from layer {name!r}.{col} — is the frame "
                f"footprint layer loaded with a {col!r} column? ({exc})"
            ) from exc
    return [(int(r[0]), [float(r[1]), float(r[2]), float(r[3]), float(r[4])]) for r in rows]


# --- cache reads -----------------------------------------------------------
def get_cached(frame_ids: list[int], ttl_hours: int = DEFAULT_TTL_HOURS) -> dict[int, dict[str, Any]]:
    """Cached availability rows keyed by frame id, with a computed ``stale`` flag."""
    from psycopg import sql

    if not frame_ids:
        return {}
    schema = sql.Identifier(config.MVT_SCHEMA)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT frame_id, product_count, latest_date, timeline, checked_at, "
                "(checked_at < now() - make_interval(hours => %s)) AS stale "
                "FROM {}.frame_availability WHERE frame_id = ANY(%s)"
            ).format(schema),
            (ttl_hours, frame_ids),
        )
        rows = cur.fetchall()
    out: dict[int, dict[str, Any]] = {}
    for fid, count, latest, timeline, checked, stale in rows:
        out[int(fid)] = {
            "frame_id": int(fid),
            "product_count": int(count or 0),
            "latest_date": latest.isoformat() if latest else None,
            "timeline": timeline or [],
            "checked_at": checked.isoformat() if checked else None,
            "stale": bool(stale),
        }
    return out


# --- cache refresh (ASF) ---------------------------------------------------
def _frame_timeline(frame_id: int) -> tuple[int, str | None, list[str]]:
    """Query ASF for one frame; return (product_count, latest_date_iso, timeline).

    The timeline is the sorted set of distinct DISP-S1 secondary acquisition
    dates (the per-product end date), which is what date-window questions key
    off of."""
    import pandas as pd

    from analysis.h2i_lab import aoi as h2i_aoi

    df = h2i_aoi.search_products_for_frames([int(frame_id)])
    if df is None or df.empty or "secondary_datetime" not in df:
        return 0, None, []
    dates = pd.to_datetime(df["secondary_datetime"]).dt.date
    timeline = sorted({d.isoformat() for d in dates})
    latest = timeline[-1] if timeline else None
    return int(len(df)), latest, timeline


def refresh_frames(frame_ids: list[int]) -> int:
    """Refresh the cache for ``frame_ids`` from ASF. Returns the number refreshed.

    Per-frame failures are isolated (rolled back and skipped) so one bad frame
    doesn't abort the batch. Designed to run in a FastAPI background task or a
    cron — never on the tile path."""
    from psycopg import sql

    if not frame_ids:
        return 0
    try:  # probe the heavy deps once, up front, for a clean 503
        from analysis.h2i_lab import aoi as _probe  # noqa: F401
    except ImportError as exc:
        raise DiscoveryUnavailable(
            f"availability refresh needs disp_xr/geopandas: {exc}"
        ) from exc

    schema = sql.Identifier(config.MVT_SCHEMA)
    refreshed = 0
    with db.connection() as conn, conn.cursor() as cur:
        for fid in frame_ids:
            try:
                count, latest, timeline = _frame_timeline(int(fid))
            except Exception:  # ASF hiccup on one frame — leave its stale row as-is
                conn.rollback()
                continue
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.frame_availability
                        (frame_id, product_count, latest_date, timeline, checked_at)
                    VALUES (%s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (frame_id) DO UPDATE SET
                        product_count = EXCLUDED.product_count,
                        latest_date   = EXCLUDED.latest_date,
                        timeline      = EXCLUDED.timeline,
                        checked_at    = now()
                    """
                ).format(schema),
                (int(fid), count, latest, json.dumps(timeline)),
            )
            conn.commit()
            refreshed += 1
    return refreshed


def refresh_all(
    layer: str = DEFAULT_LAYER,
    frame_id_column: str = DEFAULT_FRAME_ID_COLUMN,
) -> int:
    """Warm the cache for every frame in the footprint layer (for a daily cron)."""
    from psycopg import sql

    name = _safe_ident(layer)
    col = _safe_ident(frame_id_column)
    tbl = sql.Identifier(config.MVT_SCHEMA, name)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT DISTINCT {col}::bigint FROM {tbl} WHERE {col} IS NOT NULL"
            ).format(col=sql.Identifier(col), tbl=tbl)
        )
        frames = [int(r[0]) for r in cur.fetchall()]
    return refresh_frames(frames)


# --- orchestration ---------------------------------------------------------
def _count_in_window(timeline: list[str], start_date: str | None, end_date: str | None) -> int:
    """Products in [start_date, end_date] from the cached ISO-date timeline.

    ISO dates sort lexicographically, so plain string comparison is correct."""
    lo = start_date or "0000-01-01"
    hi = end_date or "9999-12-31"
    return sum(1 for d in (timeline or []) if lo <= d <= hi)


def availability_for_bbox(
    bbox: list[float],
    *,
    layer: str = DEFAULT_LAYER,
    frame_id_column: str = DEFAULT_FRAME_ID_COLUMN,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Availability for all frames intersecting ``bbox``, read from the cache.

    Returns ``(items, stale)``. ``items`` carry the cached availability (plus, if
    a date window is given, an in-window count derived from the cached timeline —
    no ASF call). ``stale`` lists frames the caller should refresh (missing or
    older than ``ttl_hours``); hand them to :func:`refresh_frames`, typically in
    a background task, so the next poll is populated."""
    frames = frames_in_bbox(bbox, layer, frame_id_column)
    bbox_by_id = {fid: fbbox for fid, fbbox in frames}
    cached = get_cached(list(bbox_by_id), ttl_hours)
    items: list[dict[str, Any]] = []
    stale: list[int] = []
    for fid, fbbox in frames:
        row = cached.get(fid)
        if row is None:
            stale.append(fid)
            items.append({
                "frame_id": fid, "product_count": 0, "latest_date": None,
                "timeline": [], "checked_at": None, "stale": True, "cached": False,
                "bbox": fbbox,
            })
            continue
        if row["stale"]:
            stale.append(fid)
        row = {**row, "cached": True, "bbox": fbbox}
        if start_date or end_date:
            row["count_in_window"] = _count_in_window(row["timeline"], start_date, end_date)
            row["available_in_window"] = row["count_in_window"] > 0
        items.append(row)
    return items, stale


if __name__ == "__main__":  # daily cron entrypoint: python -m api.availability
    import argparse

    parser = argparse.ArgumentParser(description="Refresh the OPERA DISP-S1 availability cache.")
    parser.add_argument("--layer", default=DEFAULT_LAYER, help="Frame-footprint layer name.")
    parser.add_argument("--frame-id-column", default=DEFAULT_FRAME_ID_COLUMN)
    args = parser.parse_args()
    n = refresh_all(args.layer, args.frame_id_column)
    print(f"Refreshed {n} frames in layer '{args.layer}'.")
