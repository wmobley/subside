"""Batch runner for the H2I Lab OPERA workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

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
from .download import download_disp_files
from .metadata import estimate_subset_size, fetch_product_bytes, pixel_bbox_from_product_bytes
from .preview import archive_results, latest_netcdf, make_displacement_overlay_png, write_folium_preview


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
    return output


def _aoi_path(config: H2IRunConfig) -> str | None:
    return config.aoi_shapefile_path or config.aoi_geojson_path


def _earthdata_credentials() -> tuple[str, str]:
    username = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "").strip()
    if username and password:
        return username, password

    from netrc import netrc

    try:
        auth = netrc().authenticators("urs.earthdata.nasa.gov")
    except Exception as exc:
        raise RuntimeError(
            "Missing Earthdata credentials. Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD "
            "or stage a protected .netrc file for urs.earthdata.nasa.gov."
        ) from exc
    if not auth:
        raise RuntimeError("No urs.earthdata.nasa.gov entry found in .netrc.")
    username, _account, password = auth
    return username, password


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
    if aoi_path and not frame_ids:
        frames = find_intersecting_frames(
            frames_index,
            aoi_path,
            min_overlap_percent=config.min_overlap_percent,
            require_products=config.require_products,
        )
        if not frames.empty:
            frame_ids = [int(value) for value in frames["Frame ID"].tolist()]
            frame_records = json.loads(frames.drop(columns="geometry").to_json()).get("features", [])

    products_df = search_products_for_frames(frame_ids)
    filtered_df = filter_products_by_date(products_df, config.start_date, config.end_date) if not products_df.empty else products_df
    urls = product_urls(filtered_df)

    manifest = {
        "source": "h2i_lab",
        "stage": "preflight",
        "config": config.to_manifest_config(),
        "bbox": lonlat_bbox,
        "frame_ids": frame_ids,
        "frame_records": frame_records,
        "product_count": len(urls),
        "product_urls": urls,
        "warnings": [],
    }
    if not frame_ids:
        manifest["warnings"].append("No OPERA frames selected or discovered.")
    if not urls:
        manifest["warnings"].append("No OPERA DISP-S1 products found for the selected date range.")

    _write_json(output_dir / "preflight-manifest.json", manifest)
    return manifest


def run(config: H2IRunConfig) -> dict[str, Any]:
    """Run the H2I download/subset/preview workflow."""

    manifest = preflight(config)
    urls = manifest.get("product_urls") or []
    if not urls:
        raise RuntimeError("Cannot run H2I workflow without product URLs.")

    username, password = _earthdata_credentials()
    bbox = manifest.get("bbox")
    if bbox is None:
        raise RuntimeError("Cannot run H2I workflow without an AOI bbox.")

    sample_bytes = fetch_product_bytes(urls[0], username, password)
    pixel_bbox = pixel_bbox_from_product_bytes(sample_bytes, bbox)
    size_estimate = estimate_subset_size(sample_bytes, pixel_bbox, len(urls))
    sample_bytes.close()

    results_path = config.results_path()
    downloaded = [] if config.preview_only else download_disp_files(
        urls,
        pixel_bbox,
        results_path,
        username,
        password,
        num_workers=config.num_workers,
    )

    artifacts: dict[str, Any] = {
        "results_dir": str(results_path),
        "downloaded_files": [str(path) for path in downloaded],
    }
    aoi_path = _aoi_path(config)
    if downloaded and aoi_path:
        overlay_path = config.output_path() / "disp_overlay.png"
        ranges = make_displacement_overlay_png(latest_netcdf(results_path), overlay_path)
        preview_path = results_path / "Example_Map.html"
        write_folium_preview(overlay_path, aoi_path, preview_path, vmin=ranges["vmin"], vmax=ranges["vmax"])
        archive_base = config.output_path() / (config.archive_name or config.results_dir)
        archive_path = archive_results(results_path, archive_base)
        artifacts.update(
            {
                "overlay_png": str(overlay_path),
                "preview_html": str(preview_path),
                "archive_zip": str(archive_path),
                "display_range": ranges,
            }
        )

    run_manifest = {
        **manifest,
        "stage": "complete",
        "pixel_bbox": pixel_bbox,
        "size_estimate": size_estimate,
        "artifacts": artifacts,
    }
    _write_json(config.output_path() / "run-manifest.json", run_manifest)
    return run_manifest
