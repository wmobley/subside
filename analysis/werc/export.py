"""GeoTIFF export for cumulative displacement and velocity rasters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyproj
import rasterio
import rioxarray  # noqa: F401  # registers the .rio xarray accessor
import xarray as xr
from rasterio.enums import Resampling
from rasterio.transform import from_bounds


# DISP-S1 displacement is stored in meters; downstream consumers want mm.
_M_TO_MM = 1000.0


def write_cumulative_displacement_geotiff(
    stack: xr.Dataset,
    output_path: str | Path,
    reference_lon: float | None = None,
    reference_lat: float | None = None,
    clip_percentiles: tuple[float, float] = (1.0, 99.0),
) -> dict[str, Any]:
    """Reproject the latest masked displacement to EPSG:4326 and write a tiled GeoTIFF."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    da = stack.where(stack.recommended_mask == 1).isel(time=-1).displacement
    epsg = pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
    da.rio.write_crs(epsg, inplace=True)
    da.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=True)
    da_4326 = da.rio.reproject("EPSG:4326", resampling=Resampling.bilinear)

    data = (da_4326.values * _M_TO_MM).astype(np.float32)
    p_low = float(np.nanpercentile(data, clip_percentiles[0]))
    p_high = float(np.nanpercentile(data, clip_percentiles[1]))
    data = np.clip(data, p_low, p_high)

    xmin, ymin, xmax, ymax = da_4326.rio.bounds()
    height, width = data.shape
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    d1 = pd.to_datetime(stack.time.values[0]).strftime("%Y%m%d")
    d2 = pd.to_datetime(stack.time.values[-1]).strftime("%Y%m%d")

    with rasterio.open(
        str(output_path),
        mode="w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(data, 1)
        tags = {
            "long_name": "Cumulative LOS Displacement",
            "units": "mm",
            "source": "OPERA DISP-S1",
            "date_start": d1,
            "date_end": d2,
        }
        if reference_lon is not None:
            tags["reference_lon"] = f"{float(reference_lon):.6f}"
        if reference_lat is not None:
            tags["reference_lat"] = f"{float(reference_lat):.6f}"
        dst.update_tags(**tags)

    return {
        "path": str(output_path),
        "crs": "EPSG:4326",
        "bounds": [float(xmin), float(ymin), float(xmax), float(ymax)],
        "clip_range_mm": [p_low, p_high],
        "date_start": d1,
        "date_end": d2,
    }


def write_velocity_geotiff(
    velocity_da: xr.DataArray,
    stack: xr.Dataset,
    output_path: str | Path,
) -> dict[str, Any]:
    """Mask velocity, convert to mm/year, reproject to EPSG:4326, write tiled GeoTIFF."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    epsg = pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
    last = stack.isel(time=-1)
    mask = (last.recommended_mask == 1) & (last.water_mask == 1)
    vel_mm = (velocity_da * _M_TO_MM).where(mask)
    vel_mm.rio.write_crs(epsg, inplace=True)
    vel_mm.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=True)
    vel_4326 = vel_mm.rio.reproject("EPSG:4326", resampling=Resampling.bilinear)

    data = vel_4326.values.astype(np.float32)
    xmin, ymin, xmax, ymax = vel_4326.rio.bounds()
    height, width = data.shape
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)

    p_low = float(np.nanpercentile(data, 2))
    p_high = float(np.nanpercentile(data, 98))

    with rasterio.open(
        str(output_path),
        mode="w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(data, 1)
        dst.update_tags(
            long_name="OPERA DISP-S1 Linear Velocity",
            units="mm/year",
            source="OPERA DISP-S1",
            start_date=str(velocity_da.attrs.get("start_date", "")),
            end_date=str(velocity_da.attrs.get("end_date", "")),
        )

    return {
        "path": str(output_path),
        "crs": "EPSG:4326",
        "bounds": [float(xmin), float(ymin), float(xmax), float(ymax)],
        "p02_p98_mm_per_year": [p_low, p_high],
    }
