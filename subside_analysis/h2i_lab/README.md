# H2I Lab OPERA Workflow Extraction

This package is the SUBSIDE fork of the H2I Lab notebook:

- Source clone: `notebookExamples/h2i_lab/`
- Source notebook: `notebookExamples/h2i_lab/OPERA Surface Displacement_05.11.2026.ipynb`
- Tapis batch app scaffold: `workflow_apps/h2i_lab/`

The original notebook remains unchanged. The files here are the workflow-oriented extraction target.

## Function Map

| Notebook cell | Original function or block | New location | Role |
| --- | --- | --- | --- |
| 8 | `clear_m`, `handle_draw`, `save_drawn_aoi` | UI only, not ported | Browser AOI drawing belongs in React, not the Tapis job. |
| 9 | `print_boxed_message` | UI only, not ported | Notebook display helper. Portal status messages should come from React/backend responses. |
| 10 | `decode_metadata_time` | `subside_analysis.h2i_lab.metadata.decode_metadata_time` | Decode DISP metadata timestamps. |
| 10 | `extract_pixel_bbox_from_lalo` | `subside_analysis.h2i_lab.metadata.extract_pixel_bbox_from_lalo` | Convert lon/lat AOI bounds to DISP pixel slices. |
| 10 | `get_metadata` | `subside_analysis.h2i_lab.metadata.get_metadata` | Build MintPy-compatible metadata from one DISP NetCDF. |
| 11 | `process_file` | `subside_analysis.h2i_lab.download.process_file` | Download and optionally crop one DISP NetCDF. |
| 11 | nested `clip_bbox` | `subside_analysis.h2i_lab.download.clip_bbox` | Clip xarray datasets by pixel bbox. |
| 11 | `copy_group_h5py` | `subside_analysis.h2i_lab.download.copy_group_h5py` | Preserve metadata/orbit groups in cropped NetCDFs. |
| 11 | `download_disp_files` | `subside_analysis.h2i_lab.download.download_disp_files` | Parallel product download/subset. |
| 16 | frames index download | `subside_analysis.h2i_lab.aoi.download_frames_index` | Fetch OPERA frame index GeoJSON. |
| 16 | VLM raster download/map overlay | UI/backlog | This is a visualization aid. Add it to React later if needed. |
| 17 | AOI bounds and frame intersection | `subside_analysis.h2i_lab.aoi.bounds_from_aoi`, `find_intersecting_frames` | Find candidate OPERA frames and overlap ratios. |
| 17 | `download.search(frame_id=...)` | `subside_analysis.h2i_lab.aoi.search_products_for_frames` | Query DISP-S1 product availability. |
| 19 | date filtering and URL extraction | `filter_products_by_date`, `product_urls` | Select products for the requested date range. |
| 21 | estimate stack size | `metadata.fetch_product_bytes`, `pixel_bbox_from_product_bytes`, `estimate_subset_size` | Preflight download/storage estimate. |
| 22 | download selected files | `runner.run` calling `download.download_disp_files` | Batch analysis step. |
| 24 | PNG overlay and Folium preview | `preview.make_displacement_overlay_png`, `write_folium_preview` | First preview artifact until React raster rendering is added. |
| 25 | save map and zip outputs | `preview.archive_results` | Archive downloaded/cropped products for Tapis output. |

## Batch Entrypoint

Local preflight:

```bash
python -m subside_analysis.h2i_lab.cli preflight --config run-config.json --output-dir outputs
```

Local run:

```bash
EARTHDATA_USERNAME=... EARTHDATA_PASSWORD=... \
python -m subside_analysis.h2i_lab.cli run --config run-config.json --output-dir outputs
```

The runner also accepts a standard `.netrc` entry for `urs.earthdata.nasa.gov`, which is the preferred Tapis staging path until secrets/identity handling is finalized.

Tapis should call the same CLI through `workflow_apps/h2i_lab/run.sh`.

## Current Scope

This first H2I extraction covers frame discovery, product search, size estimation, NetCDF download/subset, preview HTML, and zip archiving. The companion WERC stack/reference/velocity workflow lives in [`subside_analysis/werc/`](../werc/README.md) and composes the H2I download step (`h2i_lab.runner.run`) before its stack-assembly, reference-pixel selection, linear-velocity estimation, and GeoTIFF export steps.
