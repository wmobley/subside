# SUBSIDE — Reusable ETL Primitives

This file inventories every function across `h2i_lab/` and `werc/`, classifies each as reusable / domain-specific / composition, and proposes a target layout so other analyses (different InSAR sources, HLS, GOES, etc.) can pull in just the primitives they need.

The classification rule:

- **Reusable.** Works on generic xarray / NetCDF / GeoTIFF / HTTP / GeoJSON inputs. Does not assume any property of OPERA DISP-S1 products.
- **Domain (OPERA).** Hard-coded to OPERA DISP-S1 product structure, ASF / opera_utils / disp_xr APIs, the OPERA frame index, or DISP-S1 variable names.
- **Composition.** Orchestration glue specific to either the H2I or WERC workflow — config schema, CLI parsing, runner pipelines.

## Catalog

### `h2i_lab/_session.py`
| Function/class                  | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `EarthdataSession`              | reusable  | Works for any URS-protected URL, not just OPERA.                                          |
| `earthdata_session()`           | reusable  | Factory.                                                                                 |

### `h2i_lab/aoi.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `bbox_dict_from_bounds`         | reusable  | Pure bbox shape conversion.                                                              |
| `bbox_list_from_dict`           | reusable  | "                                                                                        |
| `bbox_dict_from_list`           | reusable  | "                                                                                        |
| `load_aoi`                      | reusable  | GeoJSON / shapefile loader (geopandas).                                                  |
| `bounds_from_aoi`               | reusable  | Computes lon/lat bbox from any vector AOI.                                               |
| `download_frames_index`         | OPERA     | Pulls the OPERA frame index GeoJSON.                                                      |
| `find_intersecting_frames`      | OPERA     | Frame intersection logic specific to OPERA frames.                                       |
| `search_products_for_frames`    | OPERA     | Calls `opera_utils.disp._search.search`.                                                 |
| `filter_products_by_date`       | reusable  | Generic DataFrame date-window filter.                                                    |
| `product_urls`                  | reusable  | URL extraction from a DataFrame — works if column name is configurable.                  |

### `h2i_lab/download.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `clip_bbox`                     | reusable  | Generic xarray pixel-bbox slicer.                                                        |
| `copy_group_h5py`               | reusable  | Generic HDF5 group copy.                                                                 |
| `_subset_to_netcdf`             | reusable  | Generic encode-and-write helper.                                                         |
| `process_file`                  | mixed     | HTTP fetch + crop + write is generic; DISP-specific group handling (corrections, metadata, orbits) is OPERA-specific. Two functions hiding inside one. |
| `download_disp_files`           | reusable  | `ThreadPoolExecutor`-based parallel download pattern; the per-file callback is the only domain bit. |

### `h2i_lab/metadata.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `decode_metadata_time`          | reusable  | Time-string decode; not OPERA-specific.                                                  |
| `extract_pixel_bbox_from_lalo`  | reusable  | lon/lat bbox → pixel slice on any geo-referenced raster.                                |
| `get_metadata`                  | OPERA     | DISP-S1-specific (MintPy-compatible metadata).                                           |
| `pixel_bbox_from_product_bytes` | OPERA     | Composes `get_metadata` + `extract_pixel_bbox_from_lalo`.                                |
| `fetch_product_bytes`           | reusable  | HTTP fetch into BytesIO with `EarthdataSession`.                                         |
| `estimate_subset_size`          | reusable  | NetCDF byte-size estimation from a sample + pixel bbox.                                  |

### `h2i_lab/preview.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `latest_netcdf`                 | reusable  | Pure-glob helper.                                                                        |
| `make_displacement_overlay_png` | mixed     | PNG overlay is generic; the "displacement" variable name is hard-coded.                  |
| `write_folium_preview`          | reusable  | Folium HTML around any PNG overlay.                                                      |
| `archive_results`               | reusable  | `shutil.make_archive` wrapper.                                                           |

### `h2i_lab/runner.py`, `cli.py`, `config.py`
| Function                        | Bucket        | Notes                                                                                |
| ------------------------------- | ------------- | ------------------------------------------------------------------------------------ |
| `_earthdata_credentials`        | reusable      | env-var-then-netrc resolution.                                                       |
| `preflight`, `run`              | composition   | H2I-specific.                                                                        |
| `H2IRunConfig`, CLI parser      | composition   | Schema is H2I-specific.                                                              |

### `werc/stack.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `load_disp_product_list`        | OPERA     | Calls `disp_xr.product.get_disp_info`.                                                   |
| `build_displacement_stack`      | OPERA     | Calls `disp_xr.stack.combine_disp_product`.                                              |
| `stack_epsg`                    | reusable  | Pulls EPSG from `spatial_ref.attrs["crs_wkt"]` — works for any rioxarray-style dataset. |
| `resolve_frame_id`              | OPERA     | Frame ID regex on DISP filenames.                                                        |

### `werc/reference.py`
| Function/class                  | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `QualityLayers`, `ReferenceSelection` | reusable  | Dataclasses; carry generic arrays.                                                  |
| `compute_quality_layers`        | mixed     | Operation is generic (mean / fraction / coverage along `time`); the FOUR input variable names (`temporal_coherence`, `recommended_mask`, `persistent_scatterer_mask`, `water_mask`) are OPERA-specific. Parametrizing them by name would make it fully reusable. |
| `zone_index_window`             | reusable  | Geospatial window picker around (lon, lat).                                              |
| `select_pixels_in_zone`         | reusable  | Threshold-tier pixel selector with edge buffer and UTM tiebreaker. Pure InSAR-PS idea, but the algorithm is generic. |
| `autopick_anchor`               | reusable  | Sliding-window densest-strict-pass-cluster picker.                                       |
| `load_or_pick_anchor`           | reusable  | Persist/load per-id anchor JSON for reproducibility across BBOX changes.                 |
| `apply_auto_reference`          | reusable  | Composes the above + median-subtract over `ref_pixel` dim.                                |
| `apply_manual_reference`        | reusable  | `.sel(method="nearest")` + subtract.                                                     |

### `werc/velocity.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `decimal_year`                  | reusable  | Pure datetime conversion.                                                                |
| `estimate_velocity_linear`      | reusable  | `np.linalg.lstsq` linear-fit over a (`time`, `y`, `x`) stack. Pure technique.            |

### `werc/export.py`
| Function                        | Bucket    | Notes                                                                                    |
| ------------------------------- | --------- | ---------------------------------------------------------------------------------------- |
| `write_cumulative_displacement_geotiff` | mixed | Mask-and-reproject-and-write is generic; variable names `displacement` / `recommended_mask` and the m→mm conversion are OPERA conventions. |
| `write_velocity_geotiff`        | mixed     | Same pattern; mask uses OPERA `recommended_mask` + `water_mask`.                          |

### `werc/runner.py`, `cli.py`, `config.py`
All composition.

---

## Proposed target layout

```
subside_analysis/
├── etl/                            # NEW — generic reusable primitives
│   ├── auth.py                     # EarthdataSession + cred resolution
│   ├── aoi.py                      # GeoJSON load, bbox conversions, pixel-bbox, date filter, URL extract
│   ├── download.py                 # parallel HTTP NetCDF download + clip + subset_to_netcdf + h5py group copy
│   ├── stack.py                    # save/load NetCDF stack, stack_epsg, generic stack helpers
│   ├── quality.py                  # compute_quality_layers(stack, *, coh_var, mask_var, ps_var, water_var)
│   ├── reference.py                # zone selection, threshold tiers, persisted anchor, ref subtraction
│   ├── velocity.py                 # decimal_year + linear fit
│   ├── geotiff.py                  # write_raster_geotiff(da, path, *, mask=None, unit_scale=None, ...)
│   ├── preview.py                  # PNG overlay (configurable var name), Folium HTML, zip archive
│   └── manifest.py                 # JSON manifest writers
├── opera_disp/                     # NEW — OPERA DISP-S1 domain logic
│   ├── frames.py                   # download_frames_index, find_intersecting_frames
│   ├── search.py                   # search_products_for_frames (opera_utils)
│   ├── metadata.py                 # get_metadata (MintPy), DISP filename parsing, frame ID resolver
│   └── products.py                 # load_disp_product_list, build_displacement_stack (disp_xr wrappers)
├── h2i_lab/                        # OPERA H2I download/preview workflow (composition)
│   ├── config.py
│   ├── runner.py                   # uses etl.* + opera_disp.*
│   └── cli.py
└── werc/                           # OPERA WERC stack/ref/velocity workflow (composition)
    ├── config.py
    ├── runner.py                   # uses etl.* + opera_disp.*
    └── cli.py
```

Once `etl/` and `opera_disp/` exist, h2i_lab and werc shrink to just the config + runner + CLI; everything in their current `*.py` modules either moves into `etl/` (the reusable bits) or `opera_disp/` (the OPERA-specific bits).

## What a second analysis would actually reuse

A hypothetical InSAR-from-elsewhere or HLS time-series analysis would pull:

- **`etl.auth`** — credentials, session subclass (any Earthdata-protected source).
- **`etl.aoi`** — drop-in.
- **`etl.download`** — drop-in (per-file callback configurable).
- **`etl.stack`** — drop-in.
- **`etl.quality`** — drop-in once variable names are parametrized.
- **`etl.reference`** — drop-in (the algorithm is dataset-independent).
- **`etl.velocity`** — drop-in.
- **`etl.geotiff`** — drop-in once the var/mask names are args.
- **`etl.preview`** — drop-in once the var name is configurable.
- **`etl.manifest`** — drop-in.

The OPERA-specific bits (`opera_disp/`) would be replaced by the new analysis's equivalent — e.g., an `s1_iw_slc/` package for raw Sentinel-1 SLC or `hls/` for HLS L30/S30.

That's basically the whole pipeline. The "what's left domain-specific" is essentially product discovery + metadata parsing.

## Migration phases

Three plausible scopes (see the question I'm about to ask):

1. **Doc only.** Land this file, do nothing else. Future agents and contributors know the shape; refactor when there's a second consumer to validate against.
2. **Quick wins.** Extract the highest-confidence reusable bits with no API surface to design around: `etl/auth.py`, `etl/manifest.py`, `etl/aoi.py` (the bbox + AOI loader bits, not OPERA frames), `etl/archive.py`. Update existing imports. ~6 files moved, low risk.
3. **Full refactor.** Stand up `etl/` and `opera_disp/` per the layout above; refactor h2i_lab + werc to be pure composition. ~15 file moves, requires touching every existing module, but the result is the cleanest base for a second analysis.

Recommendation: **Quick wins now, full refactor when a second analysis lands.** Refactoring against one consumer is speculative; we'd over-fit. But the obvious quick wins (auth, aoi, manifest, archive helpers) have zero API design risk and are worth doing today.

---

## Implementation status — 2026-05-28

Scope chosen: pieces that align with both packages now. Five modules under `subside_analysis/etl/`.

### Shipped

| Module                | Functions / classes                                                                                                                                            | Originated in                            | Now imported by                                                  |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------- |
| `etl/auth.py`         | `EarthdataSession`, `earthdata_session`, `earthdata_credentials`                                                                                              | `h2i_lab/_session.py` (deleted), `h2i_lab/runner._earthdata_credentials` (deleted) | `h2i_lab/metadata.py`, `h2i_lab/download.py`, `h2i_lab/runner.py` |
| `etl/aoi.py`          | `bbox_dict_from_bounds`, `bbox_list_from_dict`, `bbox_dict_from_list`, `load_aoi`, `bounds_from_aoi`                                                          | `h2i_lab/aoi.py`                          | `h2i_lab/aoi.py` re-exports; `h2i_lab/runner.py` uses both transitively |
| `etl/manifest.py`     | `write_json`                                                                                                                                                   | duplicated in `h2i_lab/runner._write_json` + `werc/runner._write_json` | `h2i_lab/runner.py`, `werc/runner.py`                            |
| `etl/stack.py`        | `save_stack`, `load_stack`, `stack_epsg`, `DEFAULT_ENGINE`                                                                                                    | `werc/runner._save_stack` / `_load_stack` + `werc/stack.stack_epsg` (all deleted) | `werc/runner.py`, `werc/stack.py` re-exports                     |
| `etl/archive.py`      | `archive_results`                                                                                                                                              | `h2i_lab/preview.archive_results` (deleted) | `h2i_lab/preview.py` re-exports                                  |

### Back-compat surface

To avoid breaking any caller that imports `from subside_analysis.h2i_lab.aoi import load_aoi`, `from subside_analysis.h2i_lab.preview import archive_results`, or `from subside_analysis.werc.stack import stack_epsg`, those modules now re-export the etl symbols. New code should import directly from `subside_analysis.etl.*`.

### Deferred (need a second consumer to validate the API)

- **`etl/quality.py`** — `compute_quality_layers` with variable names parametrized. Today's signature is hardcoded to DISP variables; generalizing now without a second InSAR / optical analysis to compare against is over-fitting.
- **`etl/reference.py`** — the zone selection / anchor / threshold-tier picker. Algorithm is generic, but the OPERA-shaped data flow (`recommended_mask`, `water_mask`, `persistent_scatterer_mask` as inputs) needs a second analysis to validate which knobs become arguments vs. defaults.
- **`etl/velocity.py`** — `decimal_year` + linear-fit. Trivially generic, but it's only one consumer (werc); moving it now adds an import without saving any duplication.
- **`etl/geotiff.py`** — `write_raster_geotiff(da, path, mask=..., unit_scale=..., tags=...)`. Both displacement and velocity writers in werc are almost the same function; a unified writer is the right shape. Same caveat: one consumer.
- **`etl/preview.py`** — PNG overlay + Folium HTML. Same caveat as above.
- **`etl/download.py`** — parallel HTTP NetCDF download. The pattern is generic but the per-file callback in `process_file` mixes generic and OPERA-specific code; needs untangling before promoting.
- **`opera_disp/`** — OPERA frame index, ASF search, MintPy metadata, disp_xr wrappers. Would be a separate refactor once `etl/` has more than one consumer.

### Effect on a future second analysis

A new analysis (other InSAR, HLS, Sentinel-2) can now drop in:

- `from subside_analysis.etl.auth import EarthdataSession, earthdata_credentials` — any URS-protected source.
- `from subside_analysis.etl.aoi import bounds_from_aoi, load_aoi, bbox_dict_from_*` — any geospatial AOI flow.
- `from subside_analysis.etl.manifest import write_json` — any pipeline manifest.
- `from subside_analysis.etl.stack import save_stack, load_stack, stack_epsg` — any NetCDF time-series.
- `from subside_analysis.etl.archive import archive_results` — any zip output.

That's the cross-cutting infrastructure handled. The new analysis's own product discovery, metadata parsing, and product-specific stack assembly stay in its own package — analogous to today's `h2i_lab.aoi` (OPERA frames), `h2i_lab.metadata` (DISP MintPy), and `werc.stack` (disp_xr wrappers).
