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

## Local Walkthrough

[`walkthrough.py`](walkthrough.py) in this directory drives the full WERC pipeline cell-by-cell (config → H2I download → stack → quality + reference → velocity → export), then re-runs everything through `werc.runner.run` for Tapis-equivalence. Use it to validate environment + credentials before building the container or submitting a Tapis job.

Run end-to-end:

```bash
python workflow_apps/werc/walkthrough.py
```

Or step through cells in any editor that recognises `# %%` markers (VS Code, PyCharm, Cursor, Spyder).

## Runtime Conda Install (cookbook pattern)

The Docker image is intentionally **thin** — `subside_analysis/` and `run.sh` are copied in, but no conda environment is baked in. On first invocation, `run.sh`:

1. Downloads miniconda (py312) into `${ENV_INSTALL_DIR}/miniconda3` — on TACC this resolves to `$WORK/miniconda3`, locally it defaults to `/work/miniconda3`.
2. Creates a conda env named `subside-werc-opera` from `/tapis/environment.yaml` (override the env name via `CONDA_ENV_NAME`).
3. Activates it and runs `python -m subside_analysis.werc.cli run …`.

Subsequent runs detect the existing env and reuse it (no re-solve). To force a clean rebuild after bumping `environment.yaml`, set `UPDATE_CONDA_ENV=true` (exposed as a Tapis env variable in `app-cpu.json`).

The first run pays a one-time ~5–10 min penalty for the conda solve + pip install of `disp-xr`/`opera-utils`. Image pulls become trivial.

## Build Sketch

Build from the `subside/` directory so the Dockerfile can copy both `subside_analysis/` and this app directory:

```bash
docker build -f workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
```

Local smoke test (use a Docker **named volume** for the conda install — bind-mounting it from a macOS host fails with `[Errno 22]` on case-pair files like `ncurses` terminfo `2621A` / `2621a`; named volumes live inside the Linux VM and are case-sensitive):

```bash
mkdir -p .docker-work
docker volume create subside-conda-werc

docker run --rm \
  -e ENV_INSTALL_DIR=/opt/conda-root \
  -e EARTHDATA_USERNAME -e EARTHDATA_PASSWORD \
  -v subside-conda-werc:/opt/conda-root \
  -v "$PWD/.docker-work:/work" \
  -v "$PWD/workflow_apps/werc/run-config.example.json:/work/config/run-config.json:ro" \
  -v "$PWD/sample_aoi.geojson:/work/config/aoi.geojson:ro" \
  subside-werc-opera-analysis:dev
```

On TACC/Lustre this is a non-issue and `$WORK` is automatically used — the case-pair workaround is only for Docker on macOS.

The `app-cpu.json` image tag is a placeholder and should be updated after the image is pushed.
