"""DISP-S1 metadata and pixel-bbox helpers from the H2I notebook."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any


def decode_metadata_time(value: Any) -> str:
    """Decode HDF5 metadata time values into strings."""

    import numpy as np

    if isinstance(value, (np.ndarray, bytes)):
        return b"".join(value).decode("utf-8") if isinstance(value[0], (bytes, np.bytes_)) else str(value)
    return str(value)


def extract_pixel_bbox_from_lalo(coord: Any, lonlat_bbox: dict[str, float]):
    """Convert lon/lat bbox fields into MintPy y/x slices."""

    min_lon = lonlat_bbox["lon_min"]
    max_lon = lonlat_bbox["lon_max"]
    min_lat = lonlat_bbox["lat_min"]
    max_lat = lonlat_bbox["lat_max"]
    y0, x0 = coord.lalo2yx(min_lat, min_lon)
    y1, x1 = coord.lalo2yx(max_lat, max_lon)
    return slice(int(min(y0, y1)), int(max(y0, y1))), slice(int(min(x0, x1)), int(max(x0, x1)))


def get_metadata(disp_nc: str | Path | BytesIO | Any, reference_date: str | None = None) -> dict[str, Any]:
    """Get DISP NetCDF metadata in the MintPy-compatible shape used by H2I."""

    import h5py
    import pandas as pd
    from pyproj import CRS
    from disp_xr import io

    if isinstance(disp_nc, BytesIO):
        disp_nc.seek(0)
    is_open_file = isinstance(disp_nc, h5py.File)
    ds = disp_nc if is_open_file else h5py.File(disp_nc, "r")
    try:
        length, width = ds["displacement"][:].shape
        metadata: dict[str, Any] = {}
        for key, value in ds.attrs.items():
            metadata[key] = value
        for key, value in ds["identification"].items():
            raw = value[()]
            metadata[key] = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        for key, value in ds["metadata"].items():
            if key not in ["reference_orbit", "secondary_orbit", "processing_information"]:
                metadata[key] = value[()]
        metadata["x"] = ds["x"][:]
        metadata["y"] = ds["y"][:]
        metadata["length"] = length
        metadata["width"] = width
    finally:
        if not is_open_file:
            ds.close()

    if isinstance(disp_nc, BytesIO):
        disp_nc.seek(0)
    geo_info = io.get_geospatial_info(disp_nc)
    metadata["LENGTH"] = geo_info.rows
    metadata["WIDTH"] = geo_info.cols
    metadata["X_FIRST"] = geo_info.gt[0]
    metadata["Y_FIRST"] = geo_info.gt[3]
    metadata["X_STEP"] = geo_info.gt[1]
    metadata["Y_STEP"] = geo_info.gt[5]
    metadata["GT"] = geo_info.transform
    metadata["X_UNIT"] = metadata["Y_UNIT"] = "meters"
    metadata["WAVELENGTH"] = metadata["radar_wavelength"]
    metadata["REF_DATE"] = reference_date

    proj = CRS.from_wkt(geo_info.crs.wkt)
    epsg_code = proj.to_epsg()
    if str(epsg_code).startswith("326"):
        metadata["UTM_ZONE"] = str(epsg_code)[3:] + "N"
    elif str(epsg_code).startswith("327"):
        metadata["UTM_ZONE"] = str(epsg_code)[3:] + "S"
    else:
        metadata["UTM_ZONE"] = "UNKNOWN"
    metadata["EPSG"] = epsg_code

    metadata["ALOOKS"] = 1
    metadata["RLOOkS"] = 1
    metadata["EARTH_RADIUS"] = 6371000.0
    metadata["FILE_TYPE"] = "timeseries"
    metadata["UNIT"] = "m"
    metadata["AZIMUTH_PIXEL_SIZE"] = 14.1

    try:
        times = pd.to_datetime(
            [metadata["reference_zero_doppler_start_time"], metadata["reference_zero_doppler_end_time"]]
        )
    except Exception:
        times = pd.to_datetime(
            [
                decode_metadata_time(metadata["reference_zero_doppler_start_time"]),
                decode_metadata_time(metadata["reference_zero_doppler_end_time"]),
            ]
        )
    mid_time = times[0] + times.diff()[1] / 2
    metadata["CENTER_LINE_UTC"] = (
        mid_time.hour * 3600
        + mid_time.minute * 60
        + mid_time.second
        + mid_time.microsecond / 1e6
    )

    for key in ["reference_datetime", "secondary_datetime"]:
        metadata.pop(key, None)
    return metadata


def pixel_bbox_from_product_bytes(file_bytes: BytesIO, lonlat_bbox: dict[str, float]) -> list[int]:
    """Build [col_start, col_end, row_start, row_end] from a product sample."""

    from mintpy.utils import utils as ut

    file_bytes.seek(0)
    metadata = get_metadata(file_bytes)
    coord = ut.coordinate(metadata)
    y_slice, x_slice = extract_pixel_bbox_from_lalo(coord, lonlat_bbox)
    return [x_slice.start, x_slice.stop, y_slice.start, y_slice.stop]


def fetch_product_bytes(url: str, username: str, password: str) -> BytesIO:
    """Fetch one product into memory for bbox and size estimation."""

    from subside_analysis.etl.auth import earthdata_session

    session = earthdata_session(username, password)
    try:
        response = session.get(url, timeout=300)
        response.raise_for_status()
        return BytesIO(response.content)
    finally:
        session.close()


def estimate_subset_size(file_bytes: BytesIO, pixel_bbox: list[int], product_count: int) -> dict[str, float]:
    """Estimate single-subset and total-stack size in MB/GB."""

    import xarray as xr

    file_bytes.seek(0)
    file_size_mb = file_bytes.getbuffer().nbytes / 1024**2
    with xr.open_dataset(file_bytes, engine="h5netcdf") as ds:
        full_height = ds.sizes["y"]
        full_width = ds.sizes["x"]
        col_start, col_end, row_start, row_end = pixel_bbox
        col_start = max(0, min(full_width, col_start))
        col_end = max(0, min(full_width, col_end))
        row_start = max(0, min(full_height, row_start))
        row_end = max(0, min(full_height, row_end))
        subset_height = row_end - row_start
        subset_width = col_end - col_start
        if subset_height <= 0 or subset_width <= 0:
            subset_file_size_mb = 0.0
        else:
            ratio = (subset_height * subset_width) / (full_height * full_width)
            raw_nbytes = ds.nbytes
            compression_ratio = (file_size_mb * 1024**2) / raw_nbytes
            subset_file_size_mb = (raw_nbytes * ratio * compression_ratio) / 1024**2
    return {
        "source_file_mb": float(file_size_mb),
        "subset_file_mb": float(subset_file_size_mb),
        "estimated_stack_gb": float((subset_file_size_mb * product_count) / 1024),
    }
