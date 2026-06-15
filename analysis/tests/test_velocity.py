"""Fast unit tests for the velocity solver.

The shipped solver ([analysis/werc/velocity.py]) follows the WERC notebook
(OPERA DISP-S1.ipynb cell 24): ``np.linalg.lstsq(A, disp.reshape(nt,-1))``. These
tests confirm it recovers a known rate and stays faithful to an independent
re-implementation of that lstsq, on small synthetic cubes. The on-real-data /
large-cube memory + faithfulness profile is the separate
``analysis.werc.velocity_check`` tool, exercised on ls6 (see test_pipeline_ls6.py).
"""

from __future__ import annotations

import numpy as np

from analysis.werc import velocity

from .conftest import make_stack


def _lstsq_reference(stack):
    """The notebook's exact solver, for equivalence checking."""
    disp = stack["displacement"].values
    times = stack["time"].values
    nt, ny, nx = disp.shape
    tdec = velocity.decimal_year(times)
    design = np.vstack([tdec, np.ones_like(tdec)]).T
    coef, *_ = np.linalg.lstsq(design, disp.reshape(nt, -1), rcond=None)
    return coef[0].reshape(ny, nx).astype(np.float32)


def test_recovers_known_rate():
    stack = make_stack(rate_m_per_yr=-0.03, seed=1)  # 30 mm/yr subsidence
    vel = velocity.estimate_velocity_linear(stack).values
    assert np.allclose(vel, -0.03, atol=1e-3)


def test_matches_lstsq_default():
    stack = make_stack(seed=2)  # per-pixel random rates
    closed = velocity.estimate_velocity_linear(stack).values
    ref = _lstsq_reference(stack)
    assert np.nanmax(np.abs(closed - ref)) < 1e-5


def test_matches_lstsq_various_sizes():
    for nt, ny, nx in [(6, 8, 8), (50, 30, 40), (12, 1, 200)]:
        stack = make_stack(nt=nt, ny=ny, nx=nx, seed=nt)
        closed = velocity.estimate_velocity_linear(stack).values
        ref = _lstsq_reference(stack)
        assert closed.shape == (ny, nx)
        assert np.nanmax(np.abs(closed - ref)) < 1e-5


def test_nan_columns_propagate():
    stack = make_stack(seed=3)
    stack["displacement"].values[:, 0, 0] = np.nan  # one masked pixel
    vel = velocity.estimate_velocity_linear(stack).values
    assert np.isnan(vel[0, 0])
    assert np.isfinite(vel[1, 1])


def test_velocity_units_and_metadata():
    stack = make_stack(seed=4)
    da = velocity.estimate_velocity_linear(stack)
    assert da.attrs["units"] == "m/year"
    assert da.dims == ("y", "x")
