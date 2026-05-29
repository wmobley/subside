"""Fast, in-process OPERA discovery (no Tapis job) for the pre-submit UI step.

Calls the same subside_analysis.h2i_lab.aoi helpers the batch app uses. These
pull heavy geospatial deps (geopandas; product search additionally needs
disp_xr), so imports are lazy and failures surface as a clear 503 rather than
crashing the whole API.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .config import SUBSIDE_ROOT

# subside_analysis lives at subside/subside_analysis.
if str(SUBSIDE_ROOT) not in sys.path:
    sys.path.insert(0, str(SUBSIDE_ROOT))


class DiscoveryUnavailable(RuntimeError):
    """Raised when a discovery dependency (geopandas / disp_xr) is missing."""


def _aoi_to_tempfile(aoi_geojson: dict[str, Any]) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False)
    json.dump(aoi_geojson, tmp)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


def find_frames(aoi_geojson: dict[str, Any], min_overlap_percent: float) -> dict[str, Any]:
    """Frames intersecting the AOI. require_products=False keeps it pure-geopandas
    (no disp_xr/opera_utils) so it stays fast and dependency-light."""
    try:
        from subside_analysis.h2i_lab import aoi as h2i_aoi
    except ImportError as exc:
        raise DiscoveryUnavailable(f"frame discovery needs geopandas: {exc}") from exc

    aoi_path = _aoi_to_tempfile(aoi_geojson)
    try:
        bbox = h2i_aoi.bounds_from_aoi(aoi_path)
        frames_index = aoi_path.parent / f"{aoi_path.stem}.frames.geojson"
        if not frames_index.exists():
            h2i_aoi.download_frames_index(frames_index)
        frames = h2i_aoi.find_intersecting_frames(
            frames_index, aoi_path,
            min_overlap_percent=min_overlap_percent, require_products=False,
        )
        frame_ids: list[int] = []
        records: list[dict[str, Any]] = []
        if not frames.empty:
            frame_ids = [int(v) for v in frames["Frame ID"].tolist()]
            records = json.loads(frames.drop(columns="geometry").to_json()).get("features", [])
        return {"frame_ids": frame_ids, "frames": records, "bbox": bbox}
    finally:
        aoi_path.unlink(missing_ok=True)


def search_products(frame_ids: list[int], start_date: str, end_date: str) -> dict[str, Any]:
    """OPERA DISP-S1 products for the frames within the date window. Needs disp_xr."""
    try:
        from subside_analysis.h2i_lab import aoi as h2i_aoi
    except ImportError as exc:
        raise DiscoveryUnavailable(f"product search needs disp_xr/geopandas: {exc}") from exc

    try:
        products = h2i_aoi.search_products_for_frames(frame_ids)
        if not products.empty:
            products = h2i_aoi.filter_products_by_date(products, start_date, end_date)
        urls = h2i_aoi.product_urls(products) if not products.empty else []
    except ImportError as exc:  # disp_xr imported lazily inside search_products_for_frames
        raise DiscoveryUnavailable(f"product search needs disp_xr: {exc}") from exc
    return {"product_count": len(urls), "product_urls": urls}
