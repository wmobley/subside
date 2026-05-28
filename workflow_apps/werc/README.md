# WERC Tapis Batch App

This is the Tapis app scaffold for running the SUBSIDE WERC OPERA DISP-S1 stack/reference/velocity analysis as a non-interactive batch job. It composes the H2I Lab download/subset stage with the WERC stack-assembly, reference-pixel selection, velocity estimation, and GeoTIFF export steps.

## Source And Code Locations

- Original cloned cookbook: `notebookExamples/tacc_werc_ls/`
- Source notebook: `notebookExamples/tacc_werc_ls/OPERA DISP-S1.ipynb`
- Extracted Python functions: `subside_analysis/werc/`
- Reused download/discovery code: `subside_analysis/h2i_lab/`
- Function map: `subside_analysis/werc/README.md`
- Batch entrypoint: `workflow_apps/werc/run.sh`
- Tapis app definition draft: `workflow_apps/werc/app-cpu.json`

## Runtime Model

Tapis Workflows should orchestrate the run, but this app should perform the heavy work:

1. Workflow task receives a normalized SUBSIDE WERC run config.
2. Workflow submits this Tapis app as the heavy analysis job.
3. App runs `python -m subside_analysis.werc.cli run`.
4. App writes `werc-run-manifest.json`, cumulative and velocity GeoTIFFs, persisted anchor JSON, and the H2I download/preview artifacts.
5. Workflow/archive layer exposes those outputs back to SUBSIDE.

## Config File

The required Tapis file input is `config/run-config.json`. A template lives at `workflow_apps/werc/run-config.example.json`:

```json
{
  "start_date": "2024-01-01",
  "end_date": "2025-01-01",
  "aoi_geojson_path": "config/aoi.geojson",
  "frame_ids": [],
  "num_workers": 2,
  "min_overlap_percent": 50,
  "output_dir": "output",
  "results_dir": "OPERA_L3_DISP-S1",
  "reference_mode": "auto",
  "anchor_radius_m": 5000,
  "n_reference_pixels": 25,
  "anchor_dir": "output/anchors"
}
```

Reference modes:

- `auto` — auto-pick (or reuse) a stable anchor zone per OPERA frame and subtract the median displacement of the top reference pixels.
- `manual` — supply `reference_lat` and `reference_lon`; the nearest pixel's displacement is subtracted from every time step.
- `none` — leave displacement uncorrected (use only when the upstream pipeline has already referenced).

For local runs, set `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` or use a standard `.netrc` entry for `urs.earthdata.nasa.gov`. For production Tapis runs, prefer Tapis secrets/identity handling; the scaffold also supports staging a protected `.netrc` file input.

## Local Walkthrough Notebook

[`walkthrough.ipynb`](walkthrough.ipynb) in this directory drives the full WERC pipeline cell-by-cell (config → H2I download → stack → quality + reference → velocity → export), then re-runs everything through `werc.runner.run` for Tapis-equivalence. Use it to validate environment + credentials before building the container or submitting a Tapis job.

## Build Sketch

Build from the `subside/` directory so the Dockerfile can copy both `subside_analysis/` and this app directory:

```bash
docker build -f workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
```

The `app-cpu.json` image tag is a placeholder and should be updated after the image is pushed.
