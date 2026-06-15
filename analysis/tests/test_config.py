"""Fast unit tests for WERC reference-mode config validation.

Locks in the post-cleanup contract: modes are auto / manual / point (no 'none'),
and manual/point require a coordinate. Pure — no heavy deps.
"""

from __future__ import annotations

import pytest

from analysis.werc.config import REFERENCE_MODES, WercRunConfig

_BASE = {
    "aoi_geojson_path": "config/aoi.geojson",
    "start_date": "2024-01-01",
    "end_date": "2025-01-01",
    "output_dir": "out",
}


def test_modes_are_auto_manual_point():
    assert set(REFERENCE_MODES) == {"auto", "manual", "point"}


def test_none_mode_rejected():
    with pytest.raises(ValueError):
        WercRunConfig.from_dict({**_BASE, "reference_mode": "none"})


@pytest.mark.parametrize("mode", ["point", "manual"])
def test_point_and_manual_require_coords(mode):
    with pytest.raises(ValueError):
        WercRunConfig.from_dict({**_BASE, "reference_mode": mode})
    cfg = WercRunConfig.from_dict(
        {**_BASE, "reference_mode": mode, "reference_lat": 29.7, "reference_lon": -95.4}
    )
    assert cfg.reference_mode == mode
    assert cfg.reference_lat == 29.7 and cfg.reference_lon == -95.4


def test_auto_is_default():
    assert WercRunConfig.from_dict(_BASE).reference_mode == "auto"
