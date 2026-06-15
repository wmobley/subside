"""Whole-flow WERC tests — REAL data, heavy compute. ls6 only, never in CI.

These are marked ``@pytest.mark.ls6`` so the GitHub Actions gate
(``pytest -m "not ls6 and not integration"``) skips them. Run them on an ls6
idev node via ``./test.sh`` (which targets ``-m ls6``), in the
``subside-werc-opera`` conda env with Earthdata credentials.

They are driven by env vars so they self-skip when the inputs aren't present:
  * ``WERC_TEST_NETCDF_DIR`` — a directory of already-downloaded OPERA DISP-S1
    NetCDFs to build a stack from (skips the network download).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.ls6


def _netcdf_dir() -> str:
    d = os.environ.get("WERC_TEST_NETCDF_DIR")
    if not d or not os.path.isdir(d):
        pytest.skip("set WERC_TEST_NETCDF_DIR to a dir of OPERA DISP-S1 NetCDFs")
    return d


def test_stack_to_velocity_on_real_products():
    """Build a real stack, auto-reference, and estimate velocity end to end."""
    from analysis.werc import reference, stack as stack_mod, velocity

    nc_dir = _netcdf_dir()
    disp_df = stack_mod.load_disp_product_list(nc_dir)
    assert not disp_df.empty, f"no DISP-S1 NetCDFs in {nc_dir}"

    stack = stack_mod.build_displacement_stack(disp_df)
    frame_id = stack_mod.resolve_frame_id(disp_df)
    quality = reference.compute_quality_layers(stack)
    reference.apply_auto_reference(
        stack, quality, frame_id, anchor_dir=os.environ.get("WERC_TEST_ANCHOR_DIR", "/tmp/anchors"),
    )

    vel = velocity.estimate_velocity_linear(stack)
    assert vel.dims == ("y", "x")
    # A real subsidence frame has finite velocities over a sensible mm/yr range.
    finite = np.isfinite(vel.values)
    assert finite.any()
    p2, p98 = np.nanpercentile(vel.values, [2, 98])
    assert np.isfinite(p2) and np.isfinite(p98)


def test_velocity_check_faithful_to_notebook_on_real_stack():
    """The shipped solver must reproduce the notebook's cell-24 lstsq on real data."""
    from analysis.werc import stack as stack_mod, velocity_check

    nc_dir = _netcdf_dir()
    stack = stack_mod.build_displacement_stack(stack_mod.load_disp_product_list(nc_dir))
    shipped = velocity_check.shipped_velocity(stack)
    ref = velocity_check.notebook_lstsq(stack)
    metrics = velocity_check.diff_metrics(shipped, ref)
    assert metrics["max_abs_diff"] < 1e-5
    assert metrics["nan_disagreement"] == 0
