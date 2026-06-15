"""Command line entrypoint for the WERC OPERA workflow.

Two flavours of subcommand here:

* ``preflight`` / ``run`` — full in-process pipeline, used by the
  walkthrough script and the single-task Tapis app.
* ``build-stack`` / ``compute-reference`` / ``estimate-velocity`` /
  ``export-geotiffs`` — per-stage entrypoints used by the decomposed
  Tapis Workflows pipeline. Each reads its inputs from a path on the
  shared archive and writes its outputs to another path.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from analysis.h2i_lab.config import H2IRunConfig

from .config import WercRunConfig
from . import runner as runner_mod


def _add_full_pipeline_commands(subparsers: argparse._SubParsersAction) -> None:
    for command in ("preflight", "run"):
        p = subparsers.add_parser(
            command,
            help="Full in-process WERC pipeline ('run') or its discovery prefix ('preflight').",
        )
        p.add_argument("--config", required=True, help="Path to WERC run-config JSON.")
        p.add_argument("--output-dir", help="Override output_dir from config.")


def _add_stage_commands(subparsers: argparse._SubParsersAction) -> None:
    build = subparsers.add_parser(
        "build-stack",
        help="Stage 1: combine DISP-S1 NetCDFs into one displacement stack NetCDF.",
    )
    build.add_argument("--netcdf-dir", required=True, help="Directory of OPERA DISP-S1 NetCDFs.")
    build.add_argument("--output-stack", required=True, help="Output path for combined stack NetCDF.")
    build.add_argument("--output-products", required=True, help="Output path for the disp-product table JSON.")

    ref = subparsers.add_parser(
        "compute-reference",
        help="Stage 2: select a reference and subtract its offset from the stack.",
    )
    ref.add_argument("--stack", required=True, help="Input combined stack NetCDF.")
    ref.add_argument("--output-stack", required=True, help="Output corrected stack NetCDF.")
    ref.add_argument("--output-summary", required=True, help="Output reference-summary JSON path.")
    ref.add_argument("--mode", required=True, choices=("auto", "manual", "point"))
    ref.add_argument("--anchor-dir", help="Directory holding per-frame anchor JSON (required for auto).")
    ref.add_argument("--reference-lat", type=float, help="Reference latitude (required for 'point' and 'manual').")
    ref.add_argument("--reference-lon", type=float, help="Reference longitude (required for 'point' and 'manual').")
    ref.add_argument("--anchor-radius-m", type=int, default=5000)
    ref.add_argument("--n-reference-pixels", type=int, default=25)

    vel = subparsers.add_parser(
        "estimate-velocity",
        help="Stage 3: per-pixel linear-fit velocity from the referenced stack.",
    )
    vel.add_argument("--stack", required=True, help="Input referenced stack NetCDF.")
    vel.add_argument("--output-velocity", required=True, help="Output velocity NetCDF.")
    vel.add_argument("--output-summary", required=True, help="Output velocity-summary JSON.")

    exp = subparsers.add_parser(
        "export-geotiffs",
        help="Stage 4: write cumulative + velocity GeoTIFFs (EPSG:4326, mm units).",
    )
    exp.add_argument("--stack", required=True, help="Input referenced stack NetCDF.")
    exp.add_argument("--velocity", required=True, help="Input velocity NetCDF.")
    exp.add_argument("--output-dir", required=True, help="Output directory for GeoTIFFs + export_summary.json.")
    exp.add_argument("--reference-summary", help="Optional reference-summary JSON to tag the cumulative GeoTIFF with.")
    exp.add_argument("--displacement-geotiff-name", default="opera_disp_s1_cumulative.tif")
    exp.add_argument("--velocity-geotiff-name", default="opera_disp_s1_velocity.tif")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the WERC OPERA DISP-S1 workflow — full pipeline or per-stage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_full_pipeline_commands(subparsers)
    _add_stage_commands(subparsers)
    return parser


def _run_full_pipeline(args: argparse.Namespace) -> dict:
    config = WercRunConfig.from_json_file(args.config)
    if args.output_dir:
        h2i = H2IRunConfig.from_dict({**config.h2i.__dict__, "output_dir": args.output_dir})
        config = replace(config, h2i=h2i)
    if args.command == "preflight":
        return runner_mod.preflight(config)
    return runner_mod.run(config)


# Distinct exit code so the orchestrating pipeline can tell an out-of-memory
# failure apart from any other error and retry on a bigger queue. 137 (128+SIGKILL)
# would collide with a SLURM cgroup OOM-kill; 42 is our own "Python MemoryError".
OOM_EXIT_CODE = 42


def _dispatch(args) -> dict:
    if args.command in ("preflight", "run"):
        return _run_full_pipeline(args)
    if args.command == "build-stack":
        return runner_mod.run_build_stack(
            args.netcdf_dir, args.output_stack, args.output_products,
        )
    if args.command == "compute-reference":
        return runner_mod.run_compute_reference(
            args.stack, args.output_stack, args.output_summary,
            mode=args.mode,
            anchor_dir=args.anchor_dir,
            reference_lat=args.reference_lat,
            reference_lon=args.reference_lon,
            anchor_radius_m=args.anchor_radius_m,
            n_reference_pixels=args.n_reference_pixels,
        )
    if args.command == "estimate-velocity":
        return runner_mod.run_estimate_velocity(
            args.stack, args.output_velocity, args.output_summary,
        )
    if args.command == "export-geotiffs":
        return runner_mod.run_export_geotiffs(
            args.stack, args.velocity, args.output_dir,
            reference_summary_path=args.reference_summary,
            displacement_geotiff_name=args.displacement_geotiff_name,
            velocity_geotiff_name=args.velocity_geotiff_name,
        )
    raise SystemExit(f"Unknown command: {args.command}")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        payload = _dispatch(args)
    except MemoryError as exc:
        # Signal OOM with a dedicated code so the pipeline can escalate to a
        # bigger-memory queue instead of treating it as a generic failure.
        print(f"WERC_OOM: out of memory during '{args.command}': {exc}", file=sys.stderr)
        return OOM_EXIT_CODE

    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
