"""Shared fixtures for the WERC fast unit tests.

Everything here is synthetic and in-memory — no network, no Earthdata, no real
OPERA products — so these tests run in GitHub Actions in seconds. Whole-flow
tests that need real data are marked ``@pytest.mark.ls6`` and run on ls6 only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyproj
import pytest
import xarray as xr

# A small UTM grid (EPSG:32614 — UTM 14N, the Texas zone the app uses).
_EPSG = 32614


def _times(nt: int) -> np.ndarray:
    return np.array(
        [np.datetime64("2017-01-01") + np.timedelta64(12 * i, "D") for i in range(nt)]
    )


def make_stack(
    nt: int = 24,
    ny: int = 40,
    nx: int = 50,
    *,
    rate_m_per_yr: float | None = None,
    seed: int = 0,
    with_masks: bool = True,
) -> xr.Dataset:
    """Build a synthetic OPERA-DISP-shaped stack on a real UTM grid.

    ``displacement`` is a per-pixel linear ramp (optionally a single known rate)
    plus light noise, in meters. Includes the quality layers + spatial_ref the
    reference/export code reads. ``y`` is descending (the real product layout).
    """
    rng = np.random.default_rng(seed)
    times = _times(nt)
    tdec = pd.to_datetime(times)
    tyears = (tdec.year + (tdec.dayofyear - 1) / 365.25).to_numpy(dtype=float)
    tyears = tyears - tyears[0]

    # 30 m pixels, origin near Houston in UTM 14N; y descending.
    x = 250_000.0 + 30.0 * np.arange(nx)
    y = 3_300_000.0 - 30.0 * np.arange(ny)

    if rate_m_per_yr is None:
        rate = rng.uniform(-0.05, 0.01, size=(ny, nx)).astype(np.float32)
    else:
        rate = np.full((ny, nx), float(rate_m_per_yr), dtype=np.float32)
    disp = (rate[None, :, :] * tyears[:, None, None]).astype(np.float32)
    disp += rng.normal(0, 1e-4, size=disp.shape).astype(np.float32)

    data_vars = {"displacement": (("time", "y", "x"), disp)}
    if with_masks:
        ones_t = np.ones((nt, ny, nx), dtype=np.int8)
        coh = rng.uniform(0.4, 0.95, size=(nt, ny, nx)).astype(np.float32)
        ps = rng.uniform(0.0, 0.8, size=(nt, ny, nx)).astype(np.float32)
        water = np.ones((nt, ny, nx), dtype=np.int8)  # all land by default
        data_vars.update({
            "temporal_coherence": (("time", "y", "x"), coh),
            "recommended_mask": (("time", "y", "x"), ones_t),
            "persistent_scatterer_mask": (("time", "y", "x"), ps),
            "water_mask": (("time", "y", "x"), water),
        })

    ds = xr.Dataset(
        data_vars,
        coords={"time": times, "y": y, "x": x},
    )
    # spatial_ref carries the CRS WKT the reference/export code reads.
    ds["spatial_ref"] = xr.DataArray(0, attrs={"crs_wkt": pyproj.CRS.from_epsg(_EPSG).to_wkt()})
    ds.attrs["frame_id"] = 8882
    return ds


@pytest.fixture
def stack() -> xr.Dataset:
    """A default small synthetic stack (24 × 40 × 50)."""
    return make_stack()


@pytest.fixture
def epsg() -> int:
    return _EPSG


def lonlat_of(stack: xr.Dataset, iy: int, ix: int) -> tuple[float, float]:
    """Lon/lat of pixel (iy, ix) — handy for exercising the lat/lon reference path."""
    to_ll = pyproj.Transformer.from_crs(f"EPSG:{_EPSG}", "EPSG:4326", always_xy=True)
    lon, lat = to_ll.transform(float(stack.x.values[ix]), float(stack.y.values[iy]))
    return float(lon), float(lat)
