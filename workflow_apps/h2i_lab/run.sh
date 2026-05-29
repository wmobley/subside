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

# Stage Earthdata netrc if Tapis supplied one alongside the job inputs.
if [ -f ".netrc" ]; then
    cp ".netrc" "${HOME}/.netrc"
    chmod 600 "${HOME}/.netrc"
fi

mkdir -p "${OUTPUT_DIR}"

case "${STAGE}" in
    run|preflight)
        python -m subside_analysis.h2i_lab.cli "${STAGE}" \
            --config "${CONFIG_PATH}" \
            --output-dir "${OUTPUT_DIR}"
        ;;
    *)
        echo "Unknown STAGE: ${STAGE}" >&2
        echo "Valid values: run, preflight" >&2
        exit 2
        ;;
esac
