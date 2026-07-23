"""Fast unit tests for h2i_lab's preview NetCDF selection.

Guards the fix for a real incident: when multiple OPERA frames overlap a small
AOI, each frame's independently-cropped NetCDF can land entirely on nodata for a
given date even though the frame passed the overlap gate. `latest_netcdf` must
keep trying newest-first, since the "displacement" band read is a real
rioxarray/GDAL round trip requiring correct CRS/geotransform metadata -- so the
selection/fallback ordering is exercised here via monkeypatching the validity
check, independent of raster I/O.
"""

from __future__ import annotations

import pytest

from analysis.h2i_lab import preview


def _touch(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"")
    return path


def test_latest_netcdf_picks_newest_when_valid(tmp_path, monkeypatch):
    _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F01096_20250601.nc")
    newest = _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F30452_20250601.nc")
    monkeypatch.setattr(preview, "_displacement_is_valid", lambda path: True)

    assert preview.latest_netcdf(tmp_path) == newest


def test_latest_netcdf_skips_all_nodata_candidate(tmp_path, monkeypatch, capsys):
    older_valid = _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F01096_20250601.nc")
    newest_empty = _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F30452_20250601.nc")

    validity = {older_valid: True, newest_empty: False}
    monkeypatch.setattr(preview, "_displacement_is_valid", lambda path: validity[path])

    assert preview.latest_netcdf(tmp_path) == older_valid
    assert "Skipping" in capsys.readouterr().out


def test_latest_netcdf_raises_when_every_candidate_is_empty(tmp_path, monkeypatch):
    _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F01096_20250601.nc")
    _touch(tmp_path, "OPERA_L3_DISP-S1_IW_F30452_20250601.nc")
    monkeypatch.setattr(preview, "_displacement_is_valid", lambda path: False)

    with pytest.raises(RuntimeError, match="no valid displacement data|has valid displacement"):
        preview.latest_netcdf(tmp_path)


def test_latest_netcdf_raises_on_empty_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        preview.latest_netcdf(tmp_path)
