"""Linear-fit velocity estimation from a DISP displacement stack."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def decimal_year(dates) -> np.ndarray:
    series = pd.to_datetime(dates)
    return np.asarray(series.year + (series.dayofyear - 1) / 365.25, dtype=float)


def estimate_velocity_linear(stack: xr.Dataset) -> xr.DataArray:
    """Fit ``displacement(t) = velocity * t + intercept`` per pixel.

    Follows the WERC notebook (OPERA DISP-S1.ipynb, cell 24) exactly: build the
    design matrix ``A = [t, 1]`` and solve one least-squares system over the whole
    stack with :func:`numpy.linalg.lstsq`, one right-hand side per pixel. The slope
    row is the velocity (m/year). Kept faithful to the example deliberately.

    Note: lstsq upcasts the displacement cube to float64 and sizes LAPACK's gelsd
    workspace by the pixel count, so memory scales with ``nt * npix`` — large
    (full-archive / full-frame) stacks can exhaust RAM. See ``velocity_check`` to
    profile it, and stream over spatial blocks if a cube is too big to fit.
    """

    disp = stack["displacement"].values  # (nt, ny, nx); meters
    times = stack["time"].values
    nt, ny, nx = disp.shape

    tdec = decimal_year(times)
    design = np.vstack([tdec, np.ones_like(tdec)]).T  # (nt, 2)
    coef, *_ = np.linalg.lstsq(design, disp.reshape(nt, -1), rcond=None)
    vel = coef[0].reshape(ny, nx).astype(np.float32)

    return xr.DataArray(
        vel,
        dims=("y", "x"),
        coords={"y": stack.y, "x": stack.x},
        attrs={
            "long_name": "Velocity",
            "units": "m/year",
            "description": "Linear velocity estimated from displacement time series",
            "start_date": str(times[0]),
            "end_date": str(times[-1]),
            "ref_date": str(times[0]),
        },
    )
