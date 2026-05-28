"""AOI and OPERA frame/product discovery helpers from the H2I notebook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DEFAULT_FRAMES_INDEX_URL


def bbox_dict_from_bounds(bounds: Any) -> dict[str, float]:
    """Return notebook-compatible bbox fields from geospatial bounds."""

    minx, miny, maxx, maxy = [float(value) for value in bounds]
    return {"lon_min": minx, "lon_max": maxx, "lat_min": miny, "lat_max": maxy}


def bbox_list_from_dict(bbox: dict[str, float]) -> list[float]:
    """Return [lon_min, lat_min, lon_max, lat_max]."""

    return [bbox["lon_min"], bbox["lat_min"], bbox["lon_max"], bbox["lat_max"]]


def bbox_dict_from_list(bbox: list[float]) -> dict[str, float]:
    """Return bbox fields from [lon_min, lat_min, lon_max, lat_max]."""

    lon_min, lat_min, lon_max, lat_max = [float(value) for value in bbox]
    return {"lon_min": lon_min, "lon_max": lon_max, "lat_min": lat_min, "lat_max": lat_max}


def download_frames_index(output_path: str | Path, url: str = DEFAULT_FRAMES_INDEX_URL) -> Path:
    """Download the OPERA frame index GeoJSON used by the notebook."""

    import requests

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    output.write_bytes(response.content)
    return output


def load_aoi(path: str | Path):
    """Load an AOI file with GeoPandas."""

    import geopandas as gpd

    return gpd.read_file(path)


def bounds_from_aoi(path: str | Path) -> dict[str, float]:
    """Return lon/lat bbox fields from an AOI file."""

    gdf = load_aoi(path).to_crs("EPSG:4326")
    return bbox_dict_from_bounds(gdf.total_bounds)


def find_intersecting_frames(
    frames_index_path: str | Path,
    aoi_path: str | Path,
    *,
    projected_crs: str = "EPSG:32614",
    min_overlap_percent: float = 50.0,
    require_products: bool = True,
):
    """Find OPERA frames intersecting the AOI."""

    import geopandas as gpd

    frames_gdf = gpd.read_file(frames_index_path)
    aoi_gdf = gpd.read_file(aoi_path)
    if frames_gdf.crs != aoi_gdf.crs:
        aoi_gdf = aoi_gdf.to_crs(frames_gdf.crs)

    frames_projected = frames_gdf.to_crs(projected_crs)
    aoi_projected = aoi_gdf.to_crs(projected_crs)
    intersections = gpd.overlay(frames_projected, aoi_projected, how="intersection")
    if intersections.empty:
        return intersections

    intersections["intersect_area"] = intersections.geometry.area
    intersections["bound_area"] = aoi_projected.geometry.area.iloc[0]
    intersections["overlap_ratio"] = (intersections["intersect_area"] / intersections["bound_area"]) * 100
    intersections = intersections[intersections["overlap_ratio"] >= float(min_overlap_percent)]

    if require_products and not intersections.empty:
        from opera_utils.disp._search import search

        unavailable = []
        for frame_id in intersections["Frame ID"].tolist():
            if len(search(frame_id=int(frame_id))) == 0:
                unavailable.append(frame_id)
        intersections = intersections[~intersections["Frame ID"].isin(unavailable)]

    return intersections


def search_products_for_frames(frame_ids: list[int]):
    """Search OPERA DISP-S1 products for all selected frame ids."""

    import pandas as pd
    from disp_xr import download

    frames = [int(frame_id) for frame_id in frame_ids]
    if not frames:
        return pd.DataFrame()
    return pd.concat([download.search(frame_id=frame_id) for frame_id in frames], ignore_index=True)


def filter_products_by_date(products_df, start_date: str, end_date: str):
    """Filter products by the reference/secondary datetime window."""

    from datetime import datetime, timezone

    start_datetime = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_datetime = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return products_df[
        (products_df["reference_datetime"] >= start_datetime)
        & (products_df["secondary_datetime"] <= end_datetime)
    ].copy()


def product_urls(products_df) -> list[str]:
    """Return non-empty NetCDF product URLs from a product search dataframe."""

    if products_df.empty or "filename" not in products_df:
        return []
    return [line.strip() for line in products_df["filename"].values if isinstance(line, str) and line.strip()]
