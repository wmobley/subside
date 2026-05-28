# H2I Lab Tapis Batch App

This is the Tapis app scaffold for running the H2I Lab OPERA DISP-S1 extraction as a non-interactive batch job.

## Source And Code Locations

- Original cloned cookbook: `notebookExamples/h2i_lab/`
- Extracted Python functions: `subside_analysis/h2i_lab/`
- Function map: `subside_analysis/h2i_lab/README.md`
- Batch entrypoint: `workflow_apps/h2i_lab/run.sh`
- Tapis app definition draft: `workflow_apps/h2i_lab/app-cpu.json`

## Runtime Model

Tapis Workflows should orchestrate the run, but this app should perform the heavy work:

1. Workflow task receives normalized SUBSIDE run config.
2. Workflow submits this Tapis app as the heavy analysis job.
3. App runs `python -m subside_analysis.h2i_lab.cli run`.
4. App writes `run-manifest.json`, cropped NetCDFs, preview HTML, and zip output.
5. Workflow/archive layer exposes those outputs back to SUBSIDE.

## Config File

The required Tapis file input is `config/run-config.json`. A template lives at `workflow_apps/h2i_lab/run-config.example.json`:

```json
{
  "start_date": "2024-01-01",
  "end_date": "2025-01-01",
  "aoi_geojson_path": "config/aoi.geojson",
  "frame_ids": [],
  "num_workers": 2,
  "min_overlap_percent": 50,
  "output_dir": "output"
}
```

For local runs, set `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` or use a standard `.netrc` entry for `urs.earthdata.nasa.gov`. For production Tapis runs, prefer Tapis secrets/identity handling; the current scaffold also supports staging a protected `.netrc` file input.

## Local Walkthrough Notebook

[`walkthrough.ipynb`](walkthrough.ipynb) in this directory exercises the same code path as `run.sh` end-to-end (config → preflight → download → preview → archive) against real Earthdata. Use it to validate environment + credentials before building the container or submitting a Tapis job.

## Build Sketch

Build from the `subside/` directory so the Dockerfile can copy both `subside_analysis/` and this app directory:

```bash
docker build -f workflow_apps/h2i_lab/Dockerfile -t subside-h2i-opera-analysis:dev .
```

The `app-cpu.json` image tag is a placeholder and should be updated after the image is pushed.
