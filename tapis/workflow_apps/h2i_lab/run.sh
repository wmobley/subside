#!/usr/bin/env bash
# H2I Lab Tapis batch entrypoint.
#
# The conda environment is BAKED INTO THE IMAGE at build time (see Dockerfile,
# via micromamba). This script just activates it and runs — no runtime
# miniconda download / env solve. To change dependencies, edit
# environment.yaml and rebuild the image.
#
# STAGE env var selects which CLI subcommand to invoke. Defaults to "run"
# (full download + preview + archive) for backward compat. The discover task
# sets STAGE=preflight to perform only the fast frame/product discovery step.

set -euo pipefail

STAGE="${STAGE:-run}"
CONFIG_PATH="${1:-config/run-config.json}"
OUTPUT_DIR="${2:-${_tapisExecSystemOutputDir:-output}}"

# Activate the env baked into the image. MAMBA_ROOT_PREFIX / MAMBA_EXE are set
# by the micromamba base image; default them in case Singularity drops them.
ENV_NAME="${CONDA_ENV_NAME:-subside-h2i-opera}"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-/opt/conda}"
MAMBA_EXE="${MAMBA_EXE:-/bin/micromamba}"

# `micromamba shell hook` references unset vars; relax `-u` just for activation.
set +u
eval "$("${MAMBA_EXE}" shell hook --shell bash)"
micromamba activate "${ENV_NAME}"
set -u

# Pin compute threads to the cores Slurm/Tapis actually allocated (the app
# requests coresPerNode=16). Without this, OpenBLAS/GDAL inside the Singularity
# container detect the full physical host and oversubscribe — slower, not faster.
THREADS="${SLURM_CPUS_ON_NODE:-${NUM_THREADS:-16}}"
export OMP_NUM_THREADS="${THREADS}"
export OPENBLAS_NUM_THREADS="${THREADS}"
export MKL_NUM_THREADS="${THREADS}"
export NUMEXPR_NUM_THREADS="${THREADS}"
export GDAL_NUM_THREADS=ALL_CPUS
echo "Compute threads: OMP/OPENBLAS/MKL=${THREADS}, GDAL_NUM_THREADS=ALL_CPUS" >&2

# Stage Earthdata netrc if Tapis supplied one alongside the job inputs.
if [ -f ".netrc" ]; then
    cp ".netrc" "${HOME}/.netrc"
    chmod 600 "${HOME}/.netrc"
fi

mkdir -p "${OUTPUT_DIR}"

case "${STAGE}" in
    run|preflight)
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

config = {
    "start_date": os.environ.get("START_DATE", ""),
    "end_date": os.environ.get("END_DATE", ""),
    "aoi_geojson_path": os.environ.get("AOI_GEOJSON_PATH") or None,
    "frame_ids": as_int_list(os.environ.get("FRAME_IDS", "")),
    "num_workers": int(os.environ.get("NUM_WORKERS") or 8),
    "min_overlap_percent": float(os.environ.get("MIN_OVERLAP_PERCENT") or 50),
    "results_dir": os.environ.get("RESULTS_DIR") or "OPERA_L3_DISP-S1",
    "require_products": as_bool(os.environ.get("REQUIRE_PRODUCTS"), True),
    "preview_only": as_bool(os.environ.get("PREVIEW_ONLY"), False),
    "bbox_mode": os.environ.get("BBOX_MODE") or "prime",
}
with open(sys.argv[1], "w") as handle:
    json.dump(config, handle, indent=2)
PY
        python -m analysis.h2i_lab.cli "${STAGE}" \
            --config "${CONFIG_PATH}" \
            --output-dir "${OUTPUT_DIR}"
        ;;
    *)
        echo "Unknown STAGE: ${STAGE}" >&2
        echo "Valid values: run, preflight" >&2
        exit 2
        ;;
esac
