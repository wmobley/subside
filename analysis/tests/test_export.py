"""Fast unit test for the cumulative GeoTIFF water+recommended masking.

Guards the fix that the cumulative export drops water pixels (both masks),
matching the notebook and the velocity export. Writes tiny GeoTIFFs to a tmp dir
and reads them back. Needs rasterio/rioxarray (installed in CI test deps).
"""

from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("rioxarray")

from analysis.werc import export  # noqa: E402

from .conftest import make_stack  # noqa: E402


def _finite_count(path) -> int:
    with rasterio.open(path) as src:
        return int(np.isfinite(src.read(1)).sum())


def test_cumulative_masks_drop_pixels(tmp_path):
    """Masking a block of water at the last step must reduce finite output pixels."""
    base = make_stack(seed=8)
    out_full = tmp_path / "full.tif"
    info = export.write_cumulative_displacement_geotiff(base, out_full)
    assert info["crs"] == "EPSG:4326"
    full_finite = _finite_count(out_full)

    masked = make_stack(seed=8)  # identical, then mask a 10x10 block as water
    last = masked.sizes["time"] - 1
    masked["water_mask"].values[last, 5:15, 5:15] = 0
    out_masked = tmp_path / "masked.tif"
    export.write_cumulative_displacement_geotiff(masked, out_masked)
    masked_finite = _finite_count(out_masked)

    assert masked_finite < full_finite  # the water block was dropped

    with rasterio.open(out_masked) as src:
        assert src.tags().get("units") == "mm"


def test_recommended_mask_also_applied(tmp_path):
    """Independently, a non-recommended block must also reduce finite pixels."""
    full = tmp_path / "full2.tif"
    export.write_cumulative_displacement_geotiff(make_stack(seed=9), full)
    base_finite = _finite_count(full)

    masked = make_stack(seed=9)
    last = masked.sizes["time"] - 1
    masked["recommended_mask"].values[last, 5:15, 5:15] = 0
    out = tmp_path / "masked2.tif"
    export.write_cumulative_displacement_geotiff(masked, out)
    assert _finite_count(out) < base_finite
