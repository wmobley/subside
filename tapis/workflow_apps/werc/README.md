# WERC Tapis Batch App

This is the Tapis app scaffold for running the SUBSIDE WERC OPERA DISP-S1 stack/reference/velocity analysis as a non-interactive batch job. It composes the H2I Lab download/subset stage with the WERC stack-assembly, reference-pixel selection, velocity estimation, and GeoTIFF export steps.

## Source And Code Locations

- Upstream cookbook (GitHub): https://github.com/mosiwsp/tacc_werc_ls
- Original cloned cookbook: `examples/notebookExamples/tacc_werc_ls/`
- Source notebook: `examples/notebookExamples/tacc_werc_ls/OPERA DISP-S1.ipynb`
- Extracted Python functions: `analysis/werc/`
- Reused download/discovery code: `analysis/h2i_lab/`
- Function map: `analysis/werc/README.md`
- Batch entrypoint: `tapis/workflow_apps/werc/run.sh`
- Tapis app definition draft: `tapis/workflow_apps/werc/app-cpu.json`

## Runtime Model

Tapis Workflows should orchestrate the run, but this app should perform the heavy work:

1. Workflow task receives a normalized SUBSIDE WERC run config.
2. Workflow submits this Tapis app as the heavy analysis job.
3. App runs `python -m analysis.werc.cli run`.
4. App writes `werc-run-manifest.json`, cumulative and velocity GeoTIFFs, persisted anchor JSON, and the H2I download/preview artifacts.
5. Workflow/archive layer exposes those outputs back to SUBSIDE.

## Run Parameters

Run parameters are exposed as **input fields** (Tapis env-variable parameters) on the app form: the H2I discovery/download fields (`START_DATE`, `END_DATE`, `AOI_GEOJSON_PATH`, `FRAME_IDS`, `NUM_WORKERS`, `MIN_OVERLAP_PERCENT`, `RESULTS_DIR`, `REQUIRE_PRODUCTS`) plus the WERC-specific fields (`REFERENCE_MODE`, `REFERENCE_LAT`, `REFERENCE_LON`, `ANCHOR_RADIUS_M`, `N_REFERENCE_PIXELS`, `ANCHOR_DIR`, `DISPLACEMENT_GEOTIFF_NAME`, `VELOCITY_GEOTIFF_NAME`). There is no run-config file input — for the `run`/`preflight` stages, `run.sh` materializes these values into the CLI's config JSON internally before invoking the workflow. (The decomposed per-stage Workflows tasks — `build-stack`, `compute-reference`, etc. — drive themselves from their own env vars and never touch the run config.)

Reference modes:

- `auto` — auto-pick (or reuse) a stable anchor zone per OPERA frame and subtract the median displacement of the top reference pixels.
- `manual` — supply `reference_lat` and `reference_lon`; the nearest pixel's displacement is subtracted from every time step.
- `none` — leave displacement uncorrected (use only when the upstream pipeline has already referenced).

For local runs, set `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` or use a standard `.netrc` entry for `urs.earthdata.nasa.gov`. For production Tapis runs, prefer Tapis secrets/identity handling; the scaffold also supports staging a protected `.netrc` file input.

## Local Walkthrough

[`walkthrough.py`](walkthrough.py) in this directory drives the full WERC pipeline cell-by-cell (config → H2I download → stack → quality + reference → velocity → export), then re-runs everything through `werc.runner.run` for Tapis-equivalence. Use it to validate environment + credentials before building the container or submitting a Tapis job.

Run end-to-end:

```bash
python tapis/workflow_apps/werc/walkthrough.py
```

Or step through cells in any editor that recognises `# %%` markers (VS Code, PyCharm, Cursor, Spyder).

## Runtime Conda Install (cookbook pattern)

The Docker image is intentionally **thin** — `analysis/` and `run.sh` are copied in, but no conda environment is baked in. On first invocation, `run.sh`:

1. Downloads miniconda (py312) into `${ENV_INSTALL_DIR}/miniconda3` — on TACC this resolves to `$WORK/miniconda3`, locally it defaults to `/work/miniconda3`.
2. Creates a conda env named `subside-werc-opera` from `/tapis/environment.yaml` (override the env name via `CONDA_ENV_NAME`).
3. Activates it and runs `python -m analysis.werc.cli run …`.

Subsequent runs detect the existing env and reuse it (no re-solve). To force a clean rebuild after bumping `environment.yaml`, set `UPDATE_CONDA_ENV=true` (exposed as a Tapis env variable in `app-cpu.json`).

The first run pays a one-time ~5–10 min penalty for the conda solve + pip install of `disp-xr`/`opera-utils`. Image pulls become trivial.

## Build Sketch

Build from the `subside/` directory so the Dockerfile can copy both `analysis/` and this app directory:

```bash
docker build -f tapis/workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
```

Local smoke test (use a Docker **named volume** for the conda install — bind-mounting it from a macOS host fails with `[Errno 22]` on case-pair files like `ncurses` terminfo `2621A` / `2621a`; named volumes live inside the Linux VM and are case-sensitive):

```bash
mkdir -p .docker-work
docker volume create subside-conda-werc

docker run --rm \
  -e ENV_INSTALL_DIR=/opt/conda-root \
  -e EARTHDATA_USERNAME -e EARTHDATA_PASSWORD \
  -e START_DATE=2024-01-01 -e END_DATE=2025-01-01 \
  -e AOI_GEOJSON_PATH=config/aoi.geojson -e NUM_WORKERS=2 \
  -e REFERENCE_MODE=auto \
  -v subside-conda-werc:/opt/conda-root \
  -v "$PWD/.docker-work:/work" \
  -v "$PWD/examples/sample_aoi.geojson:/work/config/aoi.geojson:ro" \
  subside-werc-opera-analysis:dev
```

On TACC/Lustre this is a non-issue and `$WORK` is automatically used — the case-pair workaround is only for Docker on macOS.

The `app-cpu.json` image is pinned to the moving `:main` tag, which CI (`build-images.yml`)
republishes on every push to `main`, so it never points at a pruned `sha-…` digest. Re-register
the Tapis app whenever you want it to pick up a new `:main` build (a SHA pin is more reproducible
but gets garbage-collected from GHCR, which 404s the pull and fails the job with exit 127).
