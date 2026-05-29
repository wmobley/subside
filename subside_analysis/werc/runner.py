"""Batch runner for the WERC OPERA DISP-S1 workflow.

Two execution surfaces here:

* ``run(config)`` does the full pipeline in-process and is what the
  walkthrough / single-task Tapis app invokes.
* ``run_build_stack`` / ``run_compute_reference`` / ``run_estimate_velocity``
  / ``run_export_geotiffs`` are the per-stage entrypoints used by the
  decomposed Tapis Workflows pipeline. Each spills its result to disk so
  the next Tapis task can pick it up from the run archive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from subside_analysis.etl.manifest import write_json as _write_json
from subside_analysis.etl.stack import DEFAULT_ENGINE as _STACK_ENGINE, load_stack as _load_stack, save_stack as _save_stack
from subside_analysis.h2i_lab import runner as h2i_runner

from . import export, reference, stack as stack_mod, velocity
from .config import WercRunConfig


def _resolve_netcdf_dir(config: WercRunConfig) -> Path:
    if config.netcdf_dir:
        return Path(config.netcdf_dir)
    return config.h2i.results_path()


def preflight(config: WercRunConfig) -> dict[str, Any]:
    return h2i_runner.preflight(config.h2i)


# ---------------------------------------------------------------------------
# Per-stage entrypoints for the Tapis Workflows pipeline.
# ---------------------------------------------------------------------------


def run_build_stack(
    netcdf_dir: str | Path,
    output_stack_path: str | Path,
    output_products_path: str | Path,
) -> dict[str, Any]:
    """Stage 1: combine per-product NetCDFs into one displacement stack."""

    nc_dir = Path(netcdf_dir)
    if not nc_dir.exists():
        raise RuntimeError(f"NetCDF directory not found: {nc_dir}")

    disp_df = stack_mod.load_disp_product_list(nc_dir)
    if disp_df.empty:
        raise RuntimeError(f"No DISP-S1 NetCDFs found in {nc_dir}.")

    stack_prod = stack_mod.build_displacement_stack(disp_df)
    frame_id = stack_mod.resolve_frame_id(disp_df)
    # Stash frame_id so downstream stages can recover it without re-parsing filenames.
    stack_prod.attrs["frame_id"] = int(frame_id)

    _save_stack(stack_prod, output_stack_path)

    products_path = Path(output_products_path)
    products_path.parent.mkdir(parents=True, exist_ok=True)
    disp_df.to_json(products_path, indent=2, default_handler=str)

    summary = {
        "stage": "build-stack",
        "frame_id": int(frame_id),
        "stack_path": str(output_stack_path),
        "products_path": str(products_path),
        "dims": {dim: int(size) for dim, size in stack_prod.sizes.items()},
        "product_count": int(len(disp_df)),
    }
    return summary


def run_compute_reference(
    stack_path: str | Path,
    output_stack_path: str | Path,
    output_summary_path: str | Path,
    mode: str,
    anchor_dir: str | Path | None = None,
    reference_lat: float | None = None,
    reference_lon: float | None = None,
    anchor_radius_m: int = 5000,
    n_reference_pixels: int = 25,
) -> dict[str, Any]:
    """Stage 2: pick a reference and subtract its offset from every pixel/time."""

    if mode not in ("auto", "manual", "none"):
        raise ValueError(f"mode must be 'auto', 'manual', or 'none' (got {mode!r}).")
    if mode == "manual" and (reference_lat is None or reference_lon is None):
        raise ValueError("Manual reference requires reference_lat and reference_lon.")
    if mode == "auto" and anchor_dir is None:
        raise ValueError("Auto reference requires anchor_dir for per-frame anchor JSON persistence.")

    stack_prod = _load_stack(stack_path)
    frame_id = int(stack_prod.attrs.get("frame_id", 0))

    ref: reference.ReferenceSelection | None
    if mode == "auto":
        quality = reference.compute_quality_layers(stack_prod)
        ref = reference.apply_auto_reference(
            stack_prod, quality, frame_id, Path(anchor_dir),
            radius_m=anchor_radius_m, n_target=n_reference_pixels,
        )
    elif mode == "manual":
        ref = reference.apply_manual_reference(stack_prod, reference_lat, reference_lon)
    else:
        ref = None

    _save_stack(stack_prod, output_stack_path)

    summary: dict[str, Any] = {
        "stage": "compute-reference",
        "mode": mode,
        "frame_id": frame_id,
        "stack_path": str(output_stack_path),
    }
    if ref is not None:
        summary.update({
            "anchor_lat": ref.anchor_lat,
            "anchor_lon": ref.anchor_lon,
            "ref_x_center": ref.ref_x_center,
            "ref_y_center": ref.ref_y_center,
            "threshold_label": ref.threshold_label,
            "n_pixels": int(len(ref.iy_sel)),
            "ref_scores": [float(v) for v in ref.ref_scores.tolist()],
            "newly_picked": bool(ref.newly_picked),
            "anchor_path": ref.anchor_path,
        })
    _write_json(output_summary_path, summary)
    return summary


def run_estimate_velocity(
    stack_path: str | Path,
    output_velocity_path: str | Path,
    output_summary_path: str | Path,
) -> dict[str, Any]:
    """Stage 3: per-pixel linear fit of displacement(t)."""

    import numpy as np

    stack_prod = _load_stack(stack_path)
    vel_da = velocity.estimate_velocity_linear(stack_prod)
    vel_da.name = "velocity"

    output_velocity_path = Path(output_velocity_path)
    output_velocity_path.parent.mkdir(parents=True, exist_ok=True)
    vel_da.to_netcdf(output_velocity_path, engine=_STACK_ENGINE)

    summary = {
        "stage": "estimate-velocity",
        "velocity_path": str(output_velocity_path),
        "start_date": str(vel_da.attrs.get("start_date", "")),
        "end_date": str(vel_da.attrs.get("end_date", "")),
        "stats_m_per_year": {
            "p2": float(np.nanpercentile(vel_da, 2)),
            "p50": float(np.nanpercentile(vel_da, 50)),
            "p98": float(np.nanpercentile(vel_da, 98)),
        },
    }
    _write_json(output_summary_path, summary)
    return summary


def run_export_geotiffs(
    stack_path: str | Path,
    velocity_path: str | Path,
    output_dir: str | Path,
    reference_summary_path: str | Path | None = None,
    displacement_geotiff_name: str = "opera_disp_s1_cumulative.tif",
    velocity_geotiff_name: str = "opera_disp_s1_velocity.tif",
) -> dict[str, Any]:
    """Stage 4: write the cumulative + velocity GeoTIFFs."""

    import xarray as xr

    stack_prod = _load_stack(stack_path)
    vel_da = xr.open_dataarray(velocity_path, engine=_STACK_ENGINE).load()

    ref_lat: float | None = None
    ref_lon: float | None = None
    if reference_summary_path is not None and Path(reference_summary_path).exists():
        with Path(reference_summary_path).open() as f:
            ref_summary = json.load(f)
        ref_lat = ref_summary.get("anchor_lat")
        ref_lon = ref_summary.get("anchor_lon")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    disp_info = export.write_cumulative_displacement_geotiff(
        stack_prod,
        output_dir / displacement_geotiff_name,
        reference_lon=ref_lon,
        reference_lat=ref_lat,
    )
    vel_info = export.write_velocity_geotiff(
        vel_da, stack_prod, output_dir / velocity_geotiff_name
    )

    summary = {
        "stage": "export-geotiffs",
        "cumulative_displacement_geotiff": disp_info,
        "velocity_geotiff": vel_info,
    }
    _write_json(output_dir / "export_summary.json", summary)
    return summary


# ---------------------------------------------------------------------------
# Full in-process pipeline (walkthrough / single-task Tapis app).
# ---------------------------------------------------------------------------


def run(config: WercRunConfig) -> dict[str, Any]:
    """Run the full WERC pipeline and write ``werc-run-manifest.json``."""

    output_dir = config.output_path()
    output_dir.mkdir(parents=True, exist_ok=True)

    if config.skip_download:
        h2i_manifest: dict[str, Any] = preflight(config)
        h2i_artifacts: dict[str, Any] = {"results_dir": str(_resolve_netcdf_dir(config))}
    else:
        h2i_manifest = h2i_runner.run(config.h2i)
        h2i_artifacts = dict(h2i_manifest.get("artifacts") or {})

    nc_dir = _resolve_netcdf_dir(config)
    if not nc_dir.exists():
        raise RuntimeError(f"NetCDF directory not found: {nc_dir}")

    disp_df = stack_mod.load_disp_product_list(nc_dir)
    if disp_df.empty:
        raise RuntimeError(f"No DISP-S1 NetCDFs found in {nc_dir}.")

    stack_prod = stack_mod.build_displacement_stack(disp_df)
    frame_id = stack_mod.resolve_frame_id(disp_df)
    quality = reference.compute_quality_layers(stack_prod)

    ref: reference.ReferenceSelection | None
    if config.reference_mode == "auto":
        ref = reference.apply_auto_reference(
            stack_prod,
            quality,
            frame_id,
            config.anchor_path(),
            radius_m=config.anchor_radius_m,
            n_target=config.n_reference_pixels,
        )
    elif config.reference_mode == "manual":
        ref = reference.apply_manual_reference(
            stack_prod, config.reference_lat, config.reference_lon
        )
    else:
        ref = None

    vel_da = velocity.estimate_velocity_linear(stack_prod)

    disp_name = config.displacement_geotiff_name or "opera_disp_s1_cumulative.tif"
    vel_name = config.velocity_geotiff_name or "opera_disp_s1_velocity.tif"
    disp_export = export.write_cumulative_displacement_geotiff(
        stack_prod,
        output_dir / disp_name,
        reference_lon=(ref.anchor_lon if ref else None),
        reference_lat=(ref.anchor_lat if ref else None),
    )
    vel_export = export.write_velocity_geotiff(
        vel_da, stack_prod, output_dir / vel_name
    )

    reference_summary: dict[str, Any] | None = None
    if ref is not None:
        reference_summary = {
            "mode": config.reference_mode,
            "anchor_lat": ref.anchor_lat,
            "anchor_lon": ref.anchor_lon,
            "ref_x_center": ref.ref_x_center,
            "ref_y_center": ref.ref_y_center,
            "threshold_label": ref.threshold_label,
            "n_pixels": int(len(ref.iy_sel)),
            "ref_scores": [float(v) for v in ref.ref_scores.tolist()],
            "newly_picked": bool(ref.newly_picked),
            "anchor_path": ref.anchor_path,
        }

    base_warnings = (
        h2i_manifest.get("warnings", []) if isinstance(h2i_manifest, dict) else []
    )
    run_manifest = {
        "source": "werc",
        "stage": "complete",
        "frame_id": int(frame_id),
        "config": config.to_manifest_config(),
        "h2i_manifest": h2i_manifest,
        "artifacts": {
            **h2i_artifacts,
            "cumulative_displacement_geotiff": disp_export,
            "velocity_geotiff": vel_export,
        },
        "reference": reference_summary,
        "warnings": list(base_warnings),
    }
    _write_json(output_dir / "werc-run-manifest.json", run_manifest)
    return run_manifest
