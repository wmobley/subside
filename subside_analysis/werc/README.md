# WERC OPERA Workflow Extraction

This package is the SUBSIDE fork of the WERC OPERA DISP-S1 notebook:

- Source clone: `notebookExamples/tacc_werc_ls/`
- Source notebook: `notebookExamples/tacc_werc_ls/OPERA DISP-S1.ipynb`
- Tapis batch app scaffold: `workflow_apps/werc/`
- Companion H2I extraction (download + discovery): `subside_analysis/h2i_lab/`

The original notebook remains unchanged. The files here are the workflow-oriented extraction target.

## Function Map

| Notebook cell | Original function or block | New location | Role |
| --- | --- | --- | --- |
| 2 | imports + git installs of MintPy / disp-xr | `workflow_apps/werc/environment.yaml` | Dependencies are baked into the Tapis image, not into Python modules. |
| 4 | AOI draw widget, ASF frame dropdown, date pickers | UI only, not ported | Browser AOI selection belongs in React; reuse `h2i_lab.aoi` for backend discovery. |
| 6 | `write_netrc`, `has_urs_credentials` | UI/notebook-only | Credentials come from `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` or a Tapis-staged `.netrc`. |
| 8 | `opera-utils disp-s1-download` shell call | reuses `subside_analysis.h2i_lab.runner.run` | The WERC runner composes the H2I download step instead of shelling out. |
| 10 | `product.get_disp_info`, last-file preview | `subside_analysis.werc.stack.load_disp_product_list` | Notebook preview plots are UI-only; backend just loads the product table. |
| 12 | `disp_stack.combine_disp_product`, drop t=0, rebase | `subside_analysis.werc.stack.build_displacement_stack` | Assemble the (time, y, x) stack with t=0 zeroed out. |
| 14 | mean coherence / mask coverage / PS fraction | `subside_analysis.werc.reference.compute_quality_layers` | Three intrinsic stability layers + water mask. |
| 15 | `_zone_index_window`, `_select_in_zone`, `_autopick_anchor`, anchor JSON persist, reference correction | `subside_analysis.werc.reference.{zone_index_window, select_pixels_in_zone, autopick_anchor, load_or_pick_anchor, apply_auto_reference}` | Auto reference-pixel selection with persisted per-frame anchor for reproducibility. |
| 17 | manual reference subtract | `subside_analysis.werc.reference.apply_manual_reference` | Manual `(lat, lon)` override path. |
| 19, 20, 25 (plot block) | basemap fetch / Folium overlay / matplotlib preview | UI/backlog | Notebook visualization helpers; will be replaced by React raster rendering. |
| 22 | cumulative displacement GeoTIFF export | `subside_analysis.werc.export.write_cumulative_displacement_geotiff` | Reproject latest reference-corrected displacement to EPSG:4326 and write tiled GeoTIFF (mm). |
| 24 | linear-fit velocity (`np.linalg.lstsq` over time) | `subside_analysis.werc.velocity.estimate_velocity_linear` | Per-pixel velocity in m/year with start/end metadata. |
| 25 (GeoTIFF half) | mask + reproject velocity, mm/year | `subside_analysis.werc.export.write_velocity_geotiff` | Masked velocity raster in mm/year for SUBSIDE viewers. |

## Composition

```
h2i_lab.preflight  →  h2i_lab.download_disp_files (skip with --skip-download)
                  ↓
        werc.stack.load_disp_product_list
                  ↓
        werc.stack.build_displacement_stack
                  ↓
        werc.reference.compute_quality_layers
                  ↓
   auto: apply_auto_reference (persists anchor JSON per frame)
   manual: apply_manual_reference
                  ↓
        werc.velocity.estimate_velocity_linear
                  ↓
        werc.export.{cumulative, velocity} GeoTIFFs
                  ↓
        werc-run-manifest.json
```

The H2I download stage is reused verbatim — WERC does not re-implement frame discovery, product search, or NetCDF download.

## Batch Entrypoint

Local preflight (delegates to the H2I preflight):

```bash
python -m subside_analysis.werc.cli preflight --config run-config.json --output-dir outputs
```

Local run:

```bash
EARTHDATA_USERNAME=... EARTHDATA_PASSWORD=... \
python -m subside_analysis.werc.cli run --config run-config.json --output-dir outputs
```

To reuse previously downloaded NetCDFs and skip the H2I download step:

```json
{
  "skip_download": true,
  "netcdf_dir": "outputs/OPERA_L3_DISP-S1",
  "reference_mode": "auto"
}
```

Tapis should call the same CLI through `workflow_apps/werc/run.sh`.

## Notes On Notebook Semantics

- DISP-S1 displacement is stored in **meters**; the WERC notebook writes `units="mm"` on the GeoTIFF without converting. The export module multiplies by 1000 so the value matches the unit label.
- Cell 22 of the notebook exports the *last single-file* displacement (`da_4326` from cell 10), which predates the reference correction. The port instead exports the latest reference-corrected time step taken from the combined `stack_prod`, which is what downstream tools expect.
- The persisted anchor JSON (`reference_anchor_FRAME{ID}.json`) is the contract that lets overlapping BBOXes produce identical reference offsets across runs. Deleting it forces a re-pick.

## Current Scope

This first WERC extraction covers stack assembly, intrinsic quality layers, auto and manual reference-pixel selection, linear velocity estimation, and cumulative + velocity GeoTIFF export. Notebook visualization (Folium overlays, ipyleaflet maps, matplotlib panels) is intentionally not ported and should land in the React portal instead.
