"""Reference-pixel selection for OPERA DISP-S1 displacement stacks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pyproj
import xarray as xr
from scipy.ndimage import uniform_filter


# (coh_min, mask_cov_min, ps_min, label) — strictest first.
DEFAULT_THRESH_LEVELS: tuple[tuple[float, float, float, str], ...] = (
    (0.70, 0.95, 0.50, "strict (PS-InSAR)"),
    (0.60, 0.90, 0.30, "relaxed-1"),
    (0.50, 0.85, 0.10, "relaxed-2"),
    (0.40, 0.75, 0.00, "relaxed-3"),
)
DEFAULT_ANCHOR_RADIUS_M = 5000
DEFAULT_N_REFERENCE_PIXELS = 25
DEFAULT_EDGE_BUFFER_PX = 5


@dataclass(frozen=True)
class QualityLayers:
    mean_temporal_coherence: xr.DataArray
    mask_coverage: xr.DataArray
    ps_fraction: xr.DataArray
    water_ok: xr.DataArray


@dataclass(frozen=True)
class ReferenceSelection:
    iy_sel: np.ndarray
    ix_sel: np.ndarray
    ref_scores: np.ndarray
    threshold_label: str
    anchor_lon: float
    anchor_lat: float
    ref_x_center: float
    ref_y_center: float
    newly_picked: bool = False
    anchor_path: str | None = None


def compute_quality_layers(stack: xr.Dataset) -> QualityLayers:
    """Compute the three intrinsic stability layers + water mask."""

    mean_temp_coh = stack["temporal_coherence"].mean(dim="time").compute()
    mask_coverage = (
        (stack["recommended_mask"] == 1).mean(dim="time").astype(float).compute()
    )
    ps_fraction = stack["persistent_scatterer_mask"].mean(dim="time").compute()
    water_ok = (stack["water_mask"].isel(time=-1) == 1).compute()
    return QualityLayers(mean_temp_coh, mask_coverage, ps_fraction, water_ok)


def zone_index_window(
    stack: xr.Dataset,
    lon_c: float,
    lat_c: float,
    radius_m: float,
    epsg_code: int,
) -> tuple[int, int, int, int] | None:
    """Return ``(iy0, iy1, ix0, ix1)`` for a square zone around ``(lon_c, lat_c)``.

    Returns ``None`` if the zone falls outside the stack or is too small.
    """

    transformer = pyproj.Transformer.from_crs(
        "EPSG:4326", f"EPSG:{epsg_code}", always_xy=True
    )
    xc, yc = transformer.transform(lon_c, lat_c)

    xs = stack.x.values
    ys = stack.y.values
    if not (
        xs.min() - radius_m < xc < xs.max() + radius_m
        and ys.min() - radius_m < yc < ys.max() + radius_m
    ):
        return None

    ix0 = int(np.searchsorted(xs, xc - radius_m, side="left"))
    ix1 = int(np.searchsorted(xs, xc + radius_m, side="right"))
    # y is typically descending; handle both orientations.
    if ys[0] > ys[-1]:
        iy0 = int(np.searchsorted(-ys, -(yc + radius_m), side="left"))
        iy1 = int(np.searchsorted(-ys, -(yc - radius_m), side="right"))
    else:
        iy0 = int(np.searchsorted(ys, yc - radius_m, side="left"))
        iy1 = int(np.searchsorted(ys, yc + radius_m, side="right"))

    iy0, iy1 = max(0, iy0), min(stack.sizes["y"], iy1)
    ix0, ix1 = max(0, ix0), min(stack.sizes["x"], ix1)
    if iy1 - iy0 < 3 or ix1 - ix0 < 3:
        return None
    return iy0, iy1, ix0, ix1


def select_pixels_in_zone(
    quality: QualityLayers,
    window: tuple[int, int, int, int],
    n_target: int,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    thresh_levels: Sequence[tuple[float, float, float, str]] = DEFAULT_THRESH_LEVELS,
    buffer_px: int = DEFAULT_EDGE_BUFFER_PX,
):
    """Find the highest-quality pixels inside ``window``.

    Returns ``(iy_global, ix_global, scores, threshold_label)`` or
    ``(None, None, None, None)`` if no threshold tier yields enough pixels.
    """

    iy0, iy1, ix0, ix1 = window
    coh_z = quality.mean_temporal_coherence.values[iy0:iy1, ix0:ix1]
    mcov_z = quality.mask_coverage.values[iy0:iy1, ix0:ix1]
    ps_z = quality.ps_fraction.values[iy0:iy1, ix0:ix1]
    water_z = quality.water_ok.values[iy0:iy1, ix0:ix1]

    edge_mask = np.ones_like(coh_z, dtype=bool)
    if edge_mask.shape[0] > 2 * buffer_px and edge_mask.shape[1] > 2 * buffer_px:
        edge_mask[:buffer_px, :] = False
        edge_mask[-buffer_px:, :] = False
        edge_mask[:, :buffer_px] = False
        edge_mask[:, -buffer_px:] = False

    for coh_t, mcov_t, ps_t, label in thresh_levels:
        passes = (
            (coh_z >= coh_t)
            & (mcov_z >= mcov_t)
            & (ps_z >= ps_t)
            & water_z
            & edge_mask
        )
        if int(passes.sum()) < n_target:
            continue

        score = (
            0.45 * np.nan_to_num(coh_z)
            + 0.35 * np.nan_to_num(mcov_z)
            + 0.20 * np.nan_to_num(ps_z)
        )
        score = np.round(uniform_filter(score, size=3), 6)
        score = np.where(passes, score, -np.inf)

        iy_loc, ix_loc = np.indices(score.shape)
        flat_score = score.ravel()
        flat_iy = iy_loc.ravel()
        flat_ix = ix_loc.ravel()
        # UTM coords tiebreak so ranking is bbox-invariant for the same pixel.
        flat_y_utm = y_axis[iy0 + flat_iy]
        flat_x_utm = x_axis[ix0 + flat_ix]

        order = np.lexsort((flat_x_utm, flat_y_utm, -flat_score))
        keep = order[:n_target]
        return (
            iy0 + flat_iy[keep],
            ix0 + flat_ix[keep],
            flat_score[keep],
            label,
        )
    return None, None, None, None


def autopick_anchor(
    quality: QualityLayers,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    epsg_code: int,
    radius_m: float,
    thresh_levels: Sequence[tuple[float, float, float, str]] = DEFAULT_THRESH_LEVELS,
    n_target: int = DEFAULT_N_REFERENCE_PIXELS,
) -> tuple[tuple[float, float] | None, int]:
    """Slide a coarse grid over the stack and pick the densest strict-pass zone."""

    coh = quality.mean_temporal_coherence
    mcov = quality.mask_coverage
    ps = quality.ps_fraction
    water_ok = quality.water_ok
    ny, nx = coh.shape

    coh_t, mcov_t, ps_t, _ = thresh_levels[0]
    strict_pass = (
        (coh.values >= coh_t)
        & (mcov.values >= mcov_t)
        & (ps.values >= ps_t)
        & water_ok.values
    )

    dx = float(np.median(np.diff(np.sort(x_axis))))
    dx = abs(dx) if dx != 0 else 30.0
    half_pix = max(3, int(radius_m / dx))

    cs = np.cumsum(np.cumsum(strict_pass.astype(np.int32), axis=0), axis=1)
    cs = np.pad(cs, ((1, 0), (1, 0)), mode="constant")

    best_count = -1
    best_yx: tuple[int, int] | None = None
    step = max(1, half_pix // 2)
    for cy in range(half_pix, ny - half_pix, step):
        for cx in range(half_pix, nx - half_pix, step):
            y0, y1 = cy - half_pix, cy + half_pix
            x0, x1 = cx - half_pix, cx + half_pix
            count = int(
                cs[y1 + 1, x1 + 1] - cs[y0, x1 + 1] - cs[y1 + 1, x0] + cs[y0, x0]
            )
            if count > best_count:
                best_count = count
                best_yx = (cy, cx)

    if best_yx is None or best_count < n_target:
        return None, 0

    cy, cx = best_yx
    transformer = pyproj.Transformer.from_crs(
        f"EPSG:{epsg_code}", "EPSG:4326", always_xy=True
    )
    lon_c, lat_c = transformer.transform(float(x_axis[cx]), float(y_axis[cy]))
    return (float(lon_c), float(lat_c)), best_count


def load_or_pick_anchor(
    quality: QualityLayers,
    stack: xr.Dataset,
    frame_id: int,
    anchor_dir: str | Path,
    radius_m: float = DEFAULT_ANCHOR_RADIUS_M,
    n_target: int = DEFAULT_N_REFERENCE_PIXELS,
    thresh_levels: Sequence[tuple[float, float, float, str]] = DEFAULT_THRESH_LEVELS,
) -> tuple[float, float, bool, Path]:
    """Reuse a persisted anchor for ``frame_id`` or auto-pick and persist one.

    Persistence keeps the reference pixel stable across BBOX variations so
    overlapping pixels reproduce across runs.
    """

    anchor_path = Path(anchor_dir) / f"reference_anchor_FRAME{frame_id}.json"
    if anchor_path.exists():
        payload = json.loads(anchor_path.read_text())
        return float(payload["lon"]), float(payload["lat"]), False, anchor_path

    epsg = pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
    pick, n_strict = autopick_anchor(
        quality, stack.x.values, stack.y.values, epsg, radius_m,
        thresh_levels=thresh_levels, n_target=n_target,
    )
    if pick is None:
        raise RuntimeError(
            "Auto-pick failed: no zone in the current stack contains enough "
            "high-quality pixels. Widen the BBOX or supply a manual anchor."
        )
    lon_anchor, lat_anchor = pick
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(
        json.dumps(
            {
                "frame_id": int(frame_id),
                "lon": lon_anchor,
                "lat": lat_anchor,
                "radius_m": radius_m,
                "n_strict_pixels_at_pick_time": int(n_strict),
            },
            indent=2,
        )
    )
    return lon_anchor, lat_anchor, True, anchor_path


def apply_auto_reference(
    stack: xr.Dataset,
    quality: QualityLayers,
    frame_id: int,
    anchor_dir: str | Path,
    radius_m: float = DEFAULT_ANCHOR_RADIUS_M,
    n_target: int = DEFAULT_N_REFERENCE_PIXELS,
    thresh_levels: Sequence[tuple[float, float, float, str]] = DEFAULT_THRESH_LEVELS,
) -> ReferenceSelection:
    """Auto-pick an anchor zone, select reference pixels, subtract the median offset."""

    epsg = pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
    lon_anchor, lat_anchor, newly_picked, anchor_path = load_or_pick_anchor(
        quality, stack, frame_id, anchor_dir,
        radius_m=radius_m, n_target=n_target, thresh_levels=thresh_levels,
    )

    window = zone_index_window(stack, lon_anchor, lat_anchor, radius_m, epsg)
    if window is None:
        raise RuntimeError(
            f"Anchor zone (lat={lat_anchor:.5f}, lon={lon_anchor:.5f}, "
            f"r={radius_m} m) is NOT inside the current BBOX. Widen the BBOX, "
            f"or delete {anchor_path} to pick a fresh anchor (breaks reproducibility)."
        )

    iy_sel, ix_sel, scores, label = select_pixels_in_zone(
        quality, window, n_target, stack.x.values, stack.y.values,
        thresh_levels=thresh_levels,
    )
    if iy_sel is None:
        raise RuntimeError(
            f"Anchor zone exists in this BBOX but no pixels passed any threshold "
            f"near (lat={lat_anchor:.5f}, lon={lon_anchor:.5f}). "
            f"Delete {anchor_path} to force a re-pick."
        )

    ref_disp = stack["displacement"].isel(
        y=xr.DataArray(iy_sel, dims="ref_pixel"),
        x=xr.DataArray(ix_sel, dims="ref_pixel"),
    )
    ref_offset = ref_disp.median(dim="ref_pixel").compute()
    stack["displacement"] = stack["displacement"] - ref_offset

    ref_xs = stack.x.values[ix_sel]
    ref_ys = stack.y.values[iy_sel]
    return ReferenceSelection(
        iy_sel=np.asarray(iy_sel),
        ix_sel=np.asarray(ix_sel),
        ref_scores=np.asarray(scores),
        threshold_label=label,
        anchor_lon=float(lon_anchor),
        anchor_lat=float(lat_anchor),
        ref_x_center=float(np.median(ref_xs)),
        ref_y_center=float(np.median(ref_ys)),
        newly_picked=newly_picked,
        anchor_path=str(anchor_path),
    )


def apply_manual_reference(
    stack: xr.Dataset,
    ref_lat: float,
    ref_lon: float,
) -> ReferenceSelection:
    """Subtract the nearest-pixel displacement at ``(ref_lat, ref_lon)`` from the stack."""

    epsg = pyproj.CRS(stack.spatial_ref.attrs["crs_wkt"]).to_epsg()
    proj = pyproj.Transformer.from_crs(
        "EPSG:4326", f"EPSG:{epsg}", always_xy=True
    )
    ref_x, ref_y = proj.transform(ref_lon, ref_lat)
    ref_disp = stack.sel(x=ref_x, y=ref_y, method="nearest").displacement
    stack["displacement"] = stack.displacement - ref_disp
    return ReferenceSelection(
        iy_sel=np.array([], dtype=int),
        ix_sel=np.array([], dtype=int),
        ref_scores=np.array([], dtype=float),
        threshold_label="manual",
        anchor_lon=float(ref_lon),
        anchor_lat=float(ref_lat),
        ref_x_center=float(ref_x),
        ref_y_center=float(ref_y),
        newly_picked=False,
        anchor_path=None,
    )
