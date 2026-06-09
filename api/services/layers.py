"""Generic GeoJSON -> PostGIS layers + Mapbox Vector Tile (MVT) serving.

A layer is created from any GeoJSON FeatureCollection: feature ``properties``
are scanned, scalar keys are promoted to typed columns (so they ride along as
MVT attributes), and the full original properties are kept in a ``props`` jsonb
column for lossless GeoJSON read-back. Geometry is stored in EPSG:4326 and
reprojected to web-mercator per tile by :func:`mvt_tile`.

The four initial layers (reservoirs major/minor, GAM grid, counties,
municipalities) are just the first things loaded through this path — there is
no per-layer special casing.

Identifier safety: every table/column identifier is validated/sanitised before
it reaches SQL (see :func:`_ident` / :func:`_sanitize_column`); all *values* go
through psycopg parameters. Nothing user-supplied is interpolated raw.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import config
from . import db

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_RESERVED_COLS = {"id", "geom", "props"}


# --- identifier / schema helpers -------------------------------------------
def _ident(name: str) -> str:
    """Validate a caller-supplied layer name. Lowercased; raises on anything
    that is not a safe unquoted SQL identifier."""
    cleaned = (name or "").strip().lower()
    if not _IDENT_RE.match(cleaned):
        raise ValueError(
            f"Invalid layer name {name!r}: use 1-63 chars [a-z][a-z0-9_], "
            "starting with a letter."
        )
    return cleaned


def _sanitize_column(key: str, taken: set[str]) -> str:
    """Map an arbitrary property key to a unique, safe column identifier."""
    base = re.sub(r"[^a-z0-9_]", "_", str(key).strip().lower()).strip("_")
    if not base or not base[0].isalpha():
        base = f"p_{base}" if base else "prop"
    base = base[:63]
    candidate = base
    i = 1
    while candidate in taken or candidate in _RESERVED_COLS:
        suffix = f"_{i}"
        candidate = base[: 63 - len(suffix)] + suffix
        i += 1
    taken.add(candidate)
    return candidate


def _pg_type(value: Any) -> str | None:
    """Postgres column type for a scalar JSON value, or None if not promotable."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "double precision"
    if isinstance(value, str):
        return "text"
    return None  # null / list / dict -> kept only in the props jsonb


def _features(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a GeoJSON value to a list of Features with geometry."""
    if not isinstance(geojson, dict):
        raise ValueError("Body must be a GeoJSON object.")
    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        feats = geojson.get("features") or []
    elif gtype == "Feature":
        feats = [geojson]
    elif gtype in {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    }:
        feats = [{"type": "Feature", "geometry": geojson, "properties": {}}]
    else:
        raise ValueError(f"Unsupported GeoJSON type: {gtype!r}")
    return [f for f in feats if isinstance(f, dict) and f.get("geometry")]


def _infer_columns(features: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Promote scalar property keys to columns.

    Returns ``{original_key: {"column": <ident>, "type": <pg type>}}``. A key
    seen with conflicting scalar types falls back to ``text``; keys that are
    only ever null/array/object are not promoted (they live in ``props``)."""
    types: dict[str, str | None] = {}
    for feat in features:
        for key, value in (feat.get("properties") or {}).items():
            pg = _pg_type(value)
            if pg is None:
                types.setdefault(key, None)
                continue
            prev = types.get(key)
            if prev is None and key not in types:
                types[key] = pg
            elif prev and prev != pg:
                types[key] = "text"  # mixed scalar types -> widen to text
            elif prev is None:
                types[key] = pg
    taken: set[str] = set()
    mapping: dict[str, dict[str, str]] = {}
    for key, pg in types.items():
        if pg is None:
            continue
        mapping[key] = {"column": _sanitize_column(key, taken), "type": pg}
    return mapping


def _dominant_geom_type(features: list[dict[str, Any]]) -> str:
    seen = {f["geometry"].get("type") for f in features if f.get("geometry")}
    seen.discard(None)
    return next(iter(seen)) if len(seen) == 1 else "Geometry"


# --- public API -------------------------------------------------------------
def list_layers() -> list[dict[str, Any]]:
    """Registry rows enriched with live feature count + bbox."""
    from psycopg import sql

    schema = sql.Identifier(config.MVT_SCHEMA)
    out: list[dict[str, Any]] = []
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT name, geom_type, srid, columns, created_at, updated_at "
                    "FROM {}.layers ORDER BY name").format(schema)
        )
        rows = cur.fetchall()
        for name, geom_type, srid, columns, created, updated in rows:
            count, bbox = _count_and_bbox(cur, name)
            out.append({
                "name": name,
                "geom_type": geom_type,
                "srid": srid,
                "columns": columns,
                "feature_count": count,
                "bbox": bbox,
                "created_at": created.isoformat() if created else None,
                "updated_at": updated.isoformat() if updated else None,
            })
    return out


def _count_and_bbox(cur, name: str) -> tuple[int, list[float] | None]:
    from psycopg import sql

    tbl = sql.Identifier(config.MVT_SCHEMA, name)
    try:
        cur.execute(
            sql.SQL(
                "SELECT count(*)::bigint, "
                "ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)), "
                "ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)) FROM {}"
            ).format(tbl)
        )
        n, minx, miny, maxx, maxy = cur.fetchone()
    except Exception:
        cur.connection.rollback()
        return 0, None
    bbox = None if minx is None else [minx, miny, maxx, maxy]
    return int(n or 0), bbox


def create_or_load(layer: str, geojson: dict[str, Any], mode: str = "replace") -> dict[str, Any]:
    """Create/replace or append a layer from GeoJSON. Returns its summary."""
    from psycopg import sql

    name = _ident(layer)
    if mode not in {"replace", "append"}:
        raise ValueError("mode must be 'replace' or 'append'.")
    features = _features(geojson)
    if not features:
        raise ValueError("No GeoJSON features with geometry found.")

    schema = sql.Identifier(config.MVT_SCHEMA)
    tbl = sql.Identifier(config.MVT_SCHEMA, name)

    with db.connection() as conn, conn.cursor() as cur:
        if mode == "append":
            columns = _load_columns(cur, name)
            if columns is None:
                raise ValueError(f"Layer {name!r} does not exist; load it with mode=replace first.")
        else:
            columns = _infer_columns(features)
            _create_table(cur, name, tbl, columns)

        geom_type = _dominant_geom_type(features)
        _insert_features(cur, tbl, columns, features)

        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}.layers (name, geom_type, srid, columns, updated_at)
                VALUES (%s, %s, 4326, %s::jsonb, now())
                ON CONFLICT (name) DO UPDATE
                  SET geom_type = EXCLUDED.geom_type,
                      columns   = EXCLUDED.columns,
                      updated_at = now()
                """
            ).format(schema),
            (name, geom_type, json.dumps(columns)),
        )
        conn.commit()
        count, bbox = _count_and_bbox(cur, name)

    return {
        "name": name,
        "geom_type": geom_type,
        "srid": 4326,
        "columns": columns,
        "feature_count": count,
        "bbox": bbox,
        "loaded": len(features),
        "mode": mode,
    }


def _create_table(cur, name: str, tbl, columns: dict[str, dict[str, str]]) -> None:
    from psycopg import sql

    col_defs = [
        sql.SQL("{} {}").format(sql.Identifier(c["column"]), sql.SQL(c["type"]))
        for c in columns.values()
    ]
    cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(tbl))
    cur.execute(
        sql.SQL(
            "CREATE TABLE {} (id serial PRIMARY KEY, "
            "geom geometry(Geometry, 4326), props jsonb{}{})"
        ).format(
            tbl,
            sql.SQL(", ") if col_defs else sql.SQL(""),
            sql.SQL(", ").join(col_defs),
        )
    )
    # GiST spatial index — name built from the already-validated layer name.
    idx = sql.Identifier(f"{name}_geom_gix")
    cur.execute(sql.SQL("CREATE INDEX {} ON {} USING GIST (geom)").format(idx, tbl))


def _load_columns(cur, name: str) -> dict[str, dict[str, str]] | None:
    from psycopg import sql

    cur.execute(
        sql.SQL("SELECT columns FROM {}.layers WHERE name = %s").format(
            sql.Identifier(config.MVT_SCHEMA)
        ),
        (name,),
    )
    row = cur.fetchone()
    return None if row is None else (row[0] or {})


def _insert_features(cur, tbl, columns: dict[str, dict[str, str]], features: list[dict[str, Any]]) -> None:
    from psycopg import sql

    ordered = list(columns.items())  # [(orig_key, {column,type})]
    col_idents = [sql.Identifier("geom"), sql.Identifier("props")]
    col_idents += [sql.Identifier(meta["column"]) for _, meta in ordered]
    placeholders = [
        sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"),
        sql.SQL("%s::jsonb"),
    ] + [sql.SQL("%s")] * len(ordered)

    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        tbl, sql.SQL(", ").join(col_idents), sql.SQL(", ").join(placeholders)
    )

    rows = []
    for feat in features:
        props = feat.get("properties") or {}
        params: list[Any] = [json.dumps(feat["geometry"]), json.dumps(props)]
        for key, _meta in ordered:
            params.append(props.get(key))
        rows.append(params)
    cur.executemany(stmt, rows)


def drop_layer(layer: str) -> bool:
    """Drop a layer's table and registry row. Returns False if it was unknown."""
    from psycopg import sql

    name = _ident(layer)
    schema = sql.Identifier(config.MVT_SCHEMA)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("DELETE FROM {}.layers WHERE name = %s").format(schema), (name,)
        )
        existed = cur.rowcount > 0
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(config.MVT_SCHEMA, name)))
        conn.commit()
    return existed


def mvt_tile(layer: str, z: int, x: int, y: int) -> bytes:
    """Return one MVT (protobuf) tile for the layer, empty bytes if no features."""
    from psycopg import sql

    name = _ident(layer)
    columns = None
    tbl = sql.Identifier(config.MVT_SCHEMA, name)
    attr_idents = []
    with db.connection() as conn, conn.cursor() as cur:
        columns = _load_columns(cur, name)
        if columns is None:
            raise ValueError(f"Unknown layer {name!r}.")
        attr_idents = [sql.Identifier(c["column"]) for c in columns.values()]
        attr_select = sql.SQL("").join(
            [sql.SQL(", ") + sql.SQL("t.{}").format(ident) for ident in attr_idents]
        ) if attr_idents else sql.SQL("")

        query = sql.SQL(
            """
            WITH bounds AS (
                SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS geom3857,
                       ST_Transform(ST_TileEnvelope(%(z)s, %(x)s, %(y)s), 4326) AS geom4326
            ),
            mvtgeom AS (
                SELECT ST_AsMVTGeom(
                           ST_Transform(t.geom, %(srid)s),
                           bounds.geom3857,
                           %(extent)s, %(buffer)s, true
                       ) AS geom,
                       t.id{attrs}
                FROM {tbl} t, bounds
                WHERE t.geom && bounds.geom4326
            )
            SELECT ST_AsMVT(mvtgeom.*, %(layer)s, %(extent)s, 'geom')
            FROM mvtgeom
            WHERE geom IS NOT NULL
            """
        ).format(tbl=tbl, attrs=attr_select)

        cur.execute(
            query,
            {
                "z": z, "x": x, "y": y, "layer": name,
                "srid": config.MVT_SRID, "extent": config.MVT_EXTENT,
                "buffer": config.MVT_BUFFER,
            },
        )
        row = cur.fetchone()
    data = row[0] if row else None
    return bytes(data) if data else b""


def read_geojson(layer: str, bbox: list[float] | None = None, limit: int = 5000) -> dict[str, Any]:
    """Read a layer back as a GeoJSON FeatureCollection (optionally bbox-filtered)."""
    from psycopg import sql

    name = _ident(layer)
    tbl = sql.Identifier(config.MVT_SCHEMA, name)
    with db.connection() as conn, conn.cursor() as cur:
        if _load_columns(cur, name) is None:
            raise ValueError(f"Unknown layer {name!r}.")
        where = sql.SQL("")
        params: dict[str, Any] = {"limit": limit}
        if bbox:
            where = sql.SQL(
                "WHERE geom && ST_MakeEnvelope(%(minx)s, %(miny)s, %(maxx)s, %(maxy)s, 4326)"
            )
            params.update({"minx": bbox[0], "miny": bbox[1], "maxx": bbox[2], "maxy": bbox[3]})
        cur.execute(
            sql.SQL(
                """
                SELECT COALESCE(json_agg(json_build_object(
                    'type', 'Feature',
                    'id', id,
                    'geometry', ST_AsGeoJSON(geom)::json,
                    'properties', COALESCE(props, '{{}}'::jsonb)
                )), '[]'::json)
                FROM (SELECT id, geom, props FROM {tbl} {where} LIMIT %(limit)s) s
                """
            ).format(tbl=tbl, where=where),
            params,
        )
        (features,) = cur.fetchone()
    return {"type": "FeatureCollection", "features": features}
