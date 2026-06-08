#!/usr/bin/env bash
# WERC Tapis batch entrypoint.
#
# The conda environment is BAKED INTO THE IMAGE at build time (see Dockerfile,
# via micromamba). This script just activates it and runs — no runtime
# miniconda download / env solve. To change dependencies, edit
# environment.yaml and rebuild the image.
#
# STAGE env var selects which CLI subcommand to invoke. Defaults to "run"
# (full in-process pipeline) for backward compat with the
# subside-werc-opera-analysis app. Per-stage Tapis Workflows tasks set
# STAGE to one of: build-stack, compute-reference, estimate-velocity,
# export-geotiffs. For the full-pipeline stages ("run" / "preflight") the
# first two positional args are CONFIG_PATH + OUTPUT_DIR. For per-stage
# invocations, all positional args pass through verbatim to the CLI.

set -euo pipefail

STAGE="${STAGE:-run}"

# Activate the env baked into the image. MAMBA_ROOT_PREFIX / MAMBA_EXE are set
# by the micromamba base image; default them in case Singularity drops them.
ENV_NAME="${CONDA_ENV_NAME:-subside-werc-opera}"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-/opt/conda}"
MAMBA_EXE="${MAMBA_EXE:-/bin/micromamba}"

# `micromamba shell hook` references unset vars; relax `-u` just for activation.
set +u
eval "$("${MAMBA_EXE}" shell hook --shell bash)"
micromamba activate "${ENV_NAME}"
set -u

# Pin compute threads to the cores Slurm/Tapis actually allocated (the app
# requests coresPerNode=16). Without this, OpenBLAS/GDAL inside the Singularity
# container detect the full physical host and spawn far more threads than we
# hold — oversubscription that usually runs slower, not faster. The velocity
# lstsq (BLAS) and GeoTIFF reproject/compress are what benefit.
THREADS="${SLURM_CPUS_ON_NODE:-${NUM_THREADS:-16}}"
export OMP_NUM_THREADS="${THREADS}"
export OPENBLAS_NUM_THREADS="${THREADS}"
export MKL_NUM_THREADS="${THREADS}"
export NUMEXPR_NUM_THREADS="${THREADS}"
export GDAL_NUM_THREADS=ALL_CPUS
echo "Compute threads: OMP/OPENBLAS/MKL=${THREADS}, GDAL_NUM_THREADS=ALL_CPUS" >&2

if [ -f ".netrc" ]; then
    cp ".netrc" "${HOME}/.netrc"
    chmod 600 "${HOME}/.netrc"
fi

case "${STAGE}" in
    run|preflight)
        CONFIG_PATH="${1:-config/run-config.json}"
        OUTPUT_DIR="${2:-${_tapisExecSystemOutputDir:-output}}"
        mkdir -p "${OUTPUT_DIR}"
        # The run parameters come from the app's env-variable input fields.
        # run.sh materializes them into the CLI's config JSON at this internal
        # path — it is generated each run, never staged by the user.
        echo "Building ${CONFIG_PATH} from environment variables." >&2
        mkdir -p "$(dirname "${CONFIG_PATH}")"
        python - "${CONFIG_PATH}" <<'PY'
import json, os, sys

def as_bool(value, default):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")

def as_int_list(value):
    if not value:
        return []
    return [int(token) for token in value.replace(",", " ").split()]

def as_opt_float(value):
    if value is None or value == "":
        return None
    return float(value)

config = {
    "start_date": os.environ.get("START_DATE", ""),
    "end_date": os.environ.get("END_DATE", ""),
    "aoi_geojson_path": os.environ.get("AOI_GEOJSON_PATH") or None,
    "frame_ids": as_int_list(os.environ.get("FRAME_IDS", "")),
    "num_workers": int(os.environ.get("NUM_WORKERS") or 2),
    "min_overlap_percent": float(os.environ.get("MIN_OVERLAP_PERCENT") or 50),
    "results_dir": os.environ.get("RESULTS_DIR") or "OPERA_L3_DISP-S1",
    "require_products": as_bool(os.environ.get("REQUIRE_PRODUCTS"), True),
    "reference_mode": (os.environ.get("REFERENCE_MODE") or "auto").lower(),
    "reference_lat": as_opt_float(os.environ.get("REFERENCE_LAT")),
    "reference_lon": as_opt_float(os.environ.get("REFERENCE_LON")),
    "anchor_radius_m": int(os.environ.get("ANCHOR_RADIUS_M") or 5000),
    "n_reference_pixels": int(os.environ.get("N_REFERENCE_PIXELS") or 25),
    "anchor_dir": os.environ.get("ANCHOR_DIR") or None,
    "displacement_geotiff_name": os.environ.get("DISPLACEMENT_GEOTIFF_NAME") or None,
    "velocity_geotiff_name": os.environ.get("VELOCITY_GEOTIFF_NAME") or None,
}
with open(sys.argv[1], "w") as handle:
    json.dump(config, handle, indent=2)
PY
        python -m analysis.werc.cli "${STAGE}" \
            --config "${CONFIG_PATH}" \
            --output-dir "${OUTPUT_DIR}"
        ;;
    build-stack)
        # Per-stage inputs come from envVariables on the Workflows task so
        # the monolithic app's FIXED appArgs don't bleed in as positional args.
        python -m analysis.werc.cli build-stack \
            --netcdf-dir       "${NETCDF_DIR:?STAGE=build-stack requires NETCDF_DIR}" \
            --output-stack     "${OUTPUT_STACK:?STAGE=build-stack requires OUTPUT_STACK}" \
            --output-products  "${OUTPUT_PRODUCTS:?STAGE=build-stack requires OUTPUT_PRODUCTS}"
        ;;
    compute-reference)
        python -m analysis.werc.cli compute-reference \
            --stack              "${STACK_INPUT:?STAGE=compute-reference requires STACK_INPUT}" \
            --output-stack       "${OUTPUT_STACK:?STAGE=compute-reference requires OUTPUT_STACK}" \
            --output-summary     "${OUTPUT_SUMMARY:?STAGE=compute-reference requires OUTPUT_SUMMARY}" \
            --mode               "${REFERENCE_MODE:-auto}" \
            --anchor-dir         "${ANCHOR_DIR:?STAGE=compute-reference requires ANCHOR_DIR}" \
            --anchor-radius-m    "${ANCHOR_RADIUS_M:-5000}" \
            --n-reference-pixels "${N_REFERENCE_PIXELS:-25}" \
            ${REFERENCE_LAT:+--reference-lat "${REFERENCE_LAT}"} \
            ${REFERENCE_LON:+--reference-lon "${REFERENCE_LON}"}
        ;;
    estimate-velocity)
        python -m analysis.werc.cli estimate-velocity \
            --stack            "${STACK_INPUT:?STAGE=estimate-velocity requires STACK_INPUT}" \
            --output-velocity  "${OUTPUT_VELOCITY:?STAGE=estimate-velocity requires OUTPUT_VELOCITY}" \
            --output-summary   "${OUTPUT_SUMMARY:?STAGE=estimate-velocity requires OUTPUT_SUMMARY}"
        ;;
    export-geotiffs)
        python -m analysis.werc.cli export-geotiffs \
            --stack      "${STACK_INPUT:?STAGE=export-geotiffs requires STACK_INPUT}" \
            --velocity   "${VELOCITY_INPUT:?STAGE=export-geotiffs requires VELOCITY_INPUT}" \
            --output-dir "${OUTPUT_DIR_PATH:?STAGE=export-geotiffs requires OUTPUT_DIR_PATH}" \
            ${REFERENCE_SUMMARY:+--reference-summary       "${REFERENCE_SUMMARY}"} \
            ${DISPLACEMENT_GEOTIFF_NAME:+--displacement-geotiff-name "${DISPLACEMENT_GEOTIFF_NAME}"} \
            ${VELOCITY_GEOTIFF_NAME:+--velocity-geotiff-name "${VELOCITY_GEOTIFF_NAME}"}
        ;;
    *)
        echo "Unknown STAGE: ${STAGE}" >&2
        echo "Valid values: run, preflight, build-stack, compute-reference, estimate-velocity, export-geotiffs" >&2
        exit 2
        ;;
esac
