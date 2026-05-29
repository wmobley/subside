"""Generic NetCDF stack save/load helpers for inter-stage handoff.

Used by the WERC per-stage Tapis tasks today; designed so a second
time-series analysis (other InSAR datasets, HLS, Sentinel-2) can spill
its working stack between pipeline stages with the same API.
"""

from __future__ import annotations

from pathlib import Path

import pyproj


DEFAULT_ENGINE = "h5netcdf"


def save_stack(stack, path: str | Path, *, engine: str = DEFAULT_ENGINE) -> Path:
    """Write an ``xr.Dataset`` (or DataArray) to a single NetCDF file."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    stack.to_netcdf(output, engine=engine)
    return output


def load_stack(path: str | Path, *, engine: str = DEFAULT_ENGINE):
    """Open a NetCDF and eagerly ``.load()`` it back into memory."""

    import xarray as xr

    return xr.open_dataset(path, engine=engine).load()


def stack_epsg(stack) -> int:
    """Pull the EPSG code from a rioxarray-style ``spatial_ref`` coordinate."""

    return pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
