"""Load and combine OPERA DISP-S1 NetCDF products into a 3D stack."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd
import xarray as xr

from subside_analysis.etl.stack import stack_epsg  # noqa: F401  re-exported


_FRAME_ID_PATTERN = re.compile(r"_F(\d{4,5})_")


def load_disp_product_list(nc_dir: str | Path) -> pd.DataFrame:
    """Return the disp-xr product table for all NetCDFs in ``nc_dir``."""

    from disp_xr import product

    return product.get_disp_info(str(nc_dir))


def build_displacement_stack(disp_df: pd.DataFrame) -> xr.Dataset:
    """Combine DISP products into a ``(time, y, x)`` stack rebased to t0=0."""

    from disp_xr import stack as disp_stack

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*data_vars.*", category=FutureWarning
        )
        stack_prod = disp_stack.combine_disp_product(disp_df)

    stack_prod = stack_prod.isel(time=slice(1, None))
    stack_prod["displacement"] = (
        stack_prod["displacement"] - stack_prod.isel(time=0).displacement
    )
    return stack_prod


def resolve_frame_id(disp_df: pd.DataFrame) -> int:
    """Recover the OPERA frame id from the DISP-S1 filename pattern."""

    for path in disp_df["path"].astype(str).tolist():
        match = _FRAME_ID_PATTERN.search(path)
        if match:
            return int(match.group(1))
    raise RuntimeError("Could not extract FRAME_ID from disp_df filenames.")
