#!/usr/bin/env python3
"""Re-ingest SUBSIDE PostGIS layers from their sources.

Recovers the map layers after a database wipe — e.g. a Postgres pod restarting
without a persistent volume. Each layer has a source (a repo-local GeoJSON
and/or a download URL) and is loaded through the same code path as the API's
`POST /layers/{name}` endpoint, so the result is identical.

Usage:
    python api/seed_layers.py                 # seed every layer (replace)
    python api/seed_layers.py satellite       # seed only the named layers
    python api/seed_layers.py --list          # list available layers
    python api/seed_layers.py --mode append   # append instead of replacing

Requires SUBSIDE_DATABASE_URL configured (subside/.env), same as the API.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Make `api` importable whether run as `python api/seed_layers.py` or `-m`.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.services import db, layers  # noqa: E402

# Layer name -> source. `path` (repo-local) is tried first, then `url` as the
# canonical/fallback source. The name is what the frontend references; the
# OPERA availability shading specifically expects the "satellite" layer.
LAYERS: dict[str, dict] = {
    "satellite": {
        "description": "OPERA DISP-S1 frame footprints — drives availability shading.",
        "path": "examples/frames_info.geojson",
        "url": "https://raw.githubusercontent.com/OPERA-Cal-Val/OPERA_Applications/"
               "refs/heads/main/DISP/Discover/Frames_Information.geojson",
    },
    "texas_counties": {
        "description": "Texas county boundaries (detailed) — TACC CKAN.",
        "url": "https://ckan.tacc.utexas.edu/dataset/cd3deceb-7102-44b1-a83b-35da7c8f6855/"
               "resource/204f8874-0db4-4e81-95e3-e695f4056bdc/download/"
               "texas_county_boundaries_detailed.geojson",
    },
}


def _load_geojson(spec: dict) -> dict:
    """Read a layer's GeoJSON from its local path if present, else its URL."""
    path = spec.get("path")
    if path:
        local = ROOT / path
        if local.exists():
            print(f"    source: {local}")
            return json.loads(local.read_text())
    url = spec.get("url")
    if url:
        print(f"    source: {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "subside-seed/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    raise FileNotFoundError("No available source (path or url) for this layer.")


def seed(names: list[str], mode: str) -> int:
    failures = 0
    for name in names:
        spec = LAYERS[name]
        print(f"[{name}] {spec['description']}")
        try:
            geojson = _load_geojson(spec)
            feats = geojson.get("features") if isinstance(geojson, dict) else geojson
            print(f"    {len(feats or [])} features -> ingesting (mode={mode})…")
            info = layers.create_or_load(name, geojson, mode)
            cols = list((info.get("columns") or {}).keys())
            print(f"    OK: {info.get('feature_count')} rows | geom={info.get('geom_type')} "
                  f"| columns={cols[:8]}{'…' if len(cols) > 8 else ''}")
        except db.DbUnavailable as exc:
            print(f"    DB UNAVAILABLE: {exc}")
            print("    (set SUBSIDE_DATABASE_URL in subside/.env — see README)")
            return 2
        except Exception as exc:  # noqa: BLE001 — report and continue with the next layer
            print(f"    FAILED: {type(exc).__name__}: {exc}")
            failures += 1
    print("\nDone." + (f" {failures} layer(s) failed." if failures else " All layers seeded."))
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Seed/re-ingest SUBSIDE PostGIS layers.")
    parser.add_argument("layers", nargs="*", help="Layer names to seed (default: all).")
    parser.add_argument("--mode", choices=("replace", "append"), default="replace")
    parser.add_argument("--list", action="store_true", help="List available layers and exit.")
    args = parser.parse_args(argv)

    if args.list:
        for name, spec in LAYERS.items():
            print(f"{name:16} {spec['description']}")
        return 0

    names = args.layers or list(LAYERS)
    unknown = [n for n in names if n not in LAYERS]
    if unknown:
        parser.error(f"Unknown layer(s): {', '.join(unknown)}. Known: {', '.join(LAYERS)}")
    return seed(names, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
