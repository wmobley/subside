"""Batch runner for the H2I Lab OPERA workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from analysis.etl.manifest import write_json as _write_json
from analysis.etl.profiling import Profiler

from .aoi import (
    bbox_dict_from_list,
    bounds_from_aoi,
    download_frames_index,
    filter_products_by_date,
    find_intersecting_frames,
    product_urls,
    search_products_for_frames,
)
from .config import H2IRunConfig
from .download import download_via_opera_utils
from .preview import (
    archive_results,
    latest_netcdf,
    make_displacement_cog,
    make_displacement_overlay_png,
    write_folium_preview,
)


def _aoi_path(config: H2IRunConfig) -> str | None:
    return config.aoi_shapefile_path or config.aoi_geojson_path


def _config_bbox(config: H2IRunConfig) -> dict[str, float] | None:
    return bbox_dict_from_list(config.bbox) if config.bbox else None


def preflight(config: H2IRunConfig) -> dict[str, Any]:
    """Run AOI/frame/product discovery and return a preflight manifest."""

    output_dir = config.output_path()
    output_dir.mkdir(parents=True, exist_ok=True)

    aoi_path = _aoi_path(config)
    lonlat_bbox = bounds_from_aoi(aoi_path) if aoi_path else _config_bbox(config)
    frames_index = Path(config.frames_index_path) if config.frames_index_path else output_dir / "frames_info.geojson"
    if not frames_index.exists():
        download_frames_index(frames_index, config.frames_index_url)

    frame_ids = list(config.frame_ids)
    frame_records: list[dict[str, Any]] = []
    frame_warnings: list[str] = []
    if aoi_path and not frame_ids:
        frames = find_intersecting_frames(
            frames_index,
            aoi_path,
            min_overlap_percent=config.min_overlap_percent,
            require_products=config.require_products,
        )
        if not frames.empty:
            # single_frame (WERC): keep only the frame with the greatest AOI
            # overlap; mixing frames/geometries into one velocity stack is invalid.
            if config.single_frame and len(frames) > 1:
                frames = frames.sort_values("overlap_ratio", ascending=False)
                kept = int(frames["Frame ID"].iloc[0])
                dropped = [int(v) for v in frames["Frame ID"].tolist()[1:]]
                frames = frames.head(1)
                frame_warnings.append(
                    f"AOI overlaps {len(dropped) + 1} OPERA frames; using the "
                    f"best-overlap frame {kept} and dropping {dropped}. "
                    f"Set FRAME_IDS to pick a specific frame."
                )
            frame_ids = [int(value) for value in frames["Frame ID"].tolist()]
            frame_records = json.loads(frames.drop(columns="geometry").to_json()).get("features", [])
    elif config.single_frame and len(frame_ids) > 1:
        frame_warnings.append(
            f"single_frame: using frame {frame_ids[0]} and ignoring {frame_ids[1:]}."
        )
        frame_ids = frame_ids[:1]

    products_df = search_products_for_frames(frame_ids)
    filtered_df = filter_products_by_date(products_df, config.start_date, config.end_date) if not products_df.empty else products_df
    urls = product_urls(filtered_df)
    if config.max_products:
        urls = urls[: config.max_products]

    manifest = {
        "source": "h2i_lab",
        "stage": "preflight",
        "config": config.to_manifest_config(),
        "bbox": lonlat_bbox,
        "frame_ids": frame_ids,
        "frame_records": frame_records,
        "product_count": len(urls),
        "product_urls": urls,
        "warnings": list(frame_warnings),
    }
    if not frame_ids:
        manifest["warnings"].append("No OPERA frames selected or discovered.")
    if not urls:
        manifest["warnings"].append("No OPERA DISP-S1 products found for the selected date range.")

    _write_json(output_dir / "preflight-manifest.json", manifest)
    return manifest


def run(config: H2IRunConfig) -> dict[str, Any]:
    """Run the H2I download/subset/preview workflow."""

    prof = Profiler()
    with prof.stage("preflight"):
        manifest = preflight(config)

    bbox = manifest.get("bbox")
    if bbox is None:
        raise RuntimeError("Cannot run H2I workflow without an AOI bbox.")
    frame_ids = manifest.get("frame_ids") or []
    if not frame_ids:
        raise RuntimeError("Cannot run H2I workflow without a discovered/selected OPERA frame.")

    results_path = config.results_path()

    # Download + AOI-subset via the official `opera-utils disp-s1-download` CLI —
    # the same tool the OPERA notebook uses (cell 8). It handles product discovery
    # and bbox cropping per frame; we loop frames into one results dir (WERC forces
    # a single frame; H2I may keep several). No bespoke search/range-subset here.
    if config.preview_only:
        downloaded: list[Path] = []
    else:
        with prof.stage("download"):
            for frame_id in frame_ids:
                download_via_opera_utils(
                    frame_id,
                    bbox,
                    config.start_date,
                    config.end_date,
                    results_path,
                    num_workers=config.num_workers,
                )
        downloaded = sorted(results_path.glob("*.nc"))

    artifacts: dict[str, Any] = {
        "results_dir": str(results_path),
        "downloaded_files": [str(path) for path in downloaded],
    }
    aoi_path = _aoi_path(config)
    if downloaded and aoi_path:
        with prof.stage("preview"):
            latest = latest_netcdf(results_path)
            overlay_path = config.output_path() / "disp_overlay.png"
            ranges = make_displacement_overlay_png(latest, overlay_path)
            cog_path = config.output_path() / "disp_displacement.tif"
            make_displacement_cog(latest, cog_path)
            preview_path = results_path / "Example_Map.html"
            write_folium_preview(overlay_path, aoi_path, preview_path, vmin=ranges["vmin"], vmax=ranges["vmax"])
            archive_base = config.output_path() / (config.archive_name or config.results_dir)
            archive_path = archive_results(results_path, archive_base)
        artifacts.update(
            {
                "overlay_png": str(overlay_path),
                "cog_tif": str(cog_path),
                "preview_html": str(preview_path),
                "archive_zip": str(archive_path),
                "display_range": ranges,
            }
        )

    run_manifest = {
        **manifest,
        "stage": "complete",
        "downloader": "opera-utils disp-s1-download",
        "artifacts": artifacts,
        "timings": prof.summary(),
    }
    _write_json(config.output_path() / "run-manifest.json", run_manifest)
    return run_manifest
