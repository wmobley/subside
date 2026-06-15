"""Linear-fit velocity estimation from a DISP displacement stack."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def decimal_year(dates) -> np.ndarray:
    series = pd.to_datetime(dates)
    return np.asarray(series.year + (series.dayofyear - 1) / 365.25, dtype=float)


#: Pixel columns processed per matvec block. Caps the working set at roughly
#: ``nt * _PIXEL_CHUNK`` float32s (a few hundred MB) so the fit scales to a
#: full-archive stack (hundreds of acquisitions over a whole frame) without the
#: float64 upcast + LAPACK gelsd workspace that made ``lstsq`` OOM on a 128 GB node.
_PIXEL_CHUNK = 2_000_000


def estimate_velocity_linear(stack: xr.Dataset) -> xr.DataArray:
    """Fit ``displacement(t) = velocity * t + intercept`` per pixel.

    Returns velocity (m/year) as an :class:`xr.DataArray` on the stack grid.

    The per-pixel rate is the ordinary-least-squares slope, which has a closed
    form — ``slope = Σ(t-t̄)·d / Σ(t-t̄)²`` — so we compute it directly instead of
    calling :func:`numpy.linalg.lstsq` per pixel. lstsq would solve a 2-parameter
    system with one right-hand side *per pixel*: it upcasts the whole cube to
    float64 and gives LAPACK's gelsd a workspace sized by the pixel count, which
    exhausts memory on large stacks. The centered-time dot product below is one
    BLAS matvec in float32, chunked over pixels, and the discarded intercept
    falls out because ``Σ(t-t̄) = 0``.
    """

    disp = stack["displacement"].values  # (nt, ny, nx); meters
    times = stack["time"].values
    nt, ny, nx = disp.shape

    tdec = decimal_year(times)
    tc = (tdec - tdec.mean()).astype(np.float32)  # centered time -> intercept drops out
    denom = float(np.dot(tc, tc))

    flat = disp.reshape(nt, -1)  # (nt, npix) view of the C-contiguous cube
    npix = flat.shape[1]
    vel_flat = np.empty(npix, dtype=np.float32)
    for start in range(0, npix, _PIXEL_CHUNK):
        block = flat[:, start:start + _PIXEL_CHUNK]   # (nt, k); NaNs propagate per-pixel
        vel_flat[start:start + _PIXEL_CHUNK] = (tc @ block) / denom
    vel = vel_flat.reshape(ny, nx)

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
