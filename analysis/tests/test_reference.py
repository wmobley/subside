"""Fast unit tests for reference-pixel de-referencing.

Covers the manual/point nearest-pixel path (apply_manual_reference, which both
'manual' and 'point' modes now use) and the auto path's zone helpers, on a small
synthetic stack.
"""

from __future__ import annotations

import numpy as np

from analysis.werc import reference

from .conftest import lonlat_of, make_stack


def test_manual_reference_subtracts_nearest_pixel():
    stack = make_stack(seed=5)
    # Pick a known pixel; its time series should become ~0 after de-referencing.
    iy, ix = 10, 12
    lon, lat = lonlat_of(stack, iy, ix)
    before = stack["displacement"].values[:, iy, ix].copy()

    sel = reference.apply_manual_reference(stack, lat, lon)

    after = stack["displacement"].values[:, iy, ix]
    assert np.allclose(after, 0.0, atol=1e-6)
    # The whole field shifted by that pixel's series (relative structure kept).
    assert sel.threshold_label == "manual"
    assert sel.anchor_lat == lat and sel.anchor_lon == lon
    assert before[-1] != 0  # sanity: there was a non-zero offset to remove


def test_zone_index_window_inside_and_outside():
    stack = make_stack(seed=6)
    epsg = 32614
    iy, ix = 20, 25
    lon, lat = lonlat_of(stack, iy, ix)
    win = reference.zone_index_window(stack, lon, lat, radius_m=300, epsg_code=epsg)
    assert win is not None
    iy0, iy1, ix0, ix1 = win
    assert iy0 < iy1 and ix0 < ix1

    # A point far outside the grid -> None.
    assert reference.zone_index_window(stack, 0.0, 0.0, radius_m=300, epsg_code=epsg) is None


def test_compute_quality_layers_shapes():
    stack = make_stack(seed=7)
    q = reference.compute_quality_layers(stack)
    ny, nx = stack.sizes["y"], stack.sizes["x"]
    assert q.mean_temporal_coherence.shape == (ny, nx)
    assert q.mask_coverage.shape == (ny, nx)
    assert q.ps_fraction.shape == (ny, nx)
    assert q.water_ok.shape == (ny, nx)
