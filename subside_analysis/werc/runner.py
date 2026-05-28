"""Batch runner for the WERC OPERA DISP-S1 workflow.

Composes the H2I Lab download/subset/preview pipeline with the WERC
stack-assembly, reference-pixel selection, velocity estimation, and raster
export steps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from subside_analysis.h2i_lab import runner as h2i_runner

from . import export, reference, stack as stack_mod, velocity
from .config import WercRunConfig


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, default=str)
    return output


def _resolve_netcdf_dir(config: WercRunConfig) -> Path:
    if config.netcdf_dir:
        return Path(config.netcdf_dir)
    return config.h2i.results_path()


def preflight(config: WercRunConfig) -> dict[str, Any]:
    return h2i_runner.preflight(config.h2i)


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
