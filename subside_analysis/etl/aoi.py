"""Generic AOI loading and bbox conversions.

OPERA-specific frame index and product search helpers live in
``subside_analysis.h2i_lab.aoi`` — this module only knows about generic
GeoJSON / shapefile AOIs and bbox shape conversions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def bbox_dict_from_bounds(bounds: Any) -> dict[str, float]:
    """Return notebook-compatible bbox fields from geospatial bounds."""

    minx, miny, maxx, maxy = [float(value) for value in bounds]
    return {"lon_min": minx, "lon_max": maxx, "lat_min": miny, "lat_max": maxy}


def bbox_list_from_dict(bbox: dict[str, float]) -> list[float]:
    """Return ``[lon_min, lat_min, lon_max, lat_max]``."""

    return [bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"]]


def bbox_dict_from_list(bbox: list[float]) -> dict[str, float]:
    """Return bbox fields from ``[lon_min, lat_min, lon_max, lat_max]``."""

    lon_min, lat_min, lon_max, lat_max = [float(value) for value in bbox]
    return {"lon_min": lon_min, "lon_max": lon_max, "lat_min": lat_min, "lat_max": lat_max}


def load_aoi(path: str | Path):
    """Load an AOI file with GeoPandas (GeoJSON / shapefile / GeoPackage)."""

    import geopandas as gpd

    return gpd.read_file(path)


def bounds_from_aoi(path: str | Path) -> dict[str, float]:
    """Return lon/lat bbox fields from an AOI file."""

    gdf = load_aoi(path).to_crs("EPSG:4326")
    return bbox_dict_from_bounds(gdf.total_bounds)
