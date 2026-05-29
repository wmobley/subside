#!/usr/bin/env bash
# WERC Tapis batch entrypoint.
#
# Mirrors the TACC cookbook pattern (notebookExamples/h2i_lab/run.sh):
# miniconda is installed at runtime under a persistent path, the conda
# environment is created from environment.yaml on first invocation, and
# subsequent runs reuse it. Set UPDATE_CONDA_ENV=true to force a rebuild.
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

ENV_INSTALL_DIR="${ENV_INSTALL_DIR:-${WORK:-/work}}"
CONDA_DIR="${ENV_INSTALL_DIR}/miniconda3"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-subside-werc-opera}"
UPDATE_CONDA_ENV="${UPDATE_CONDA_ENV:-false}"

MINICONDA_INSTALLER_URL="${MINICONDA_INSTALLER_URL:-https://repo.anaconda.com/miniconda/Miniconda3-py312_24.5.0-0-Linux-x86_64.sh}"

ENV_FILE="/tapis/environment.yaml"

install_conda() {
    # Treat a directory without conda.sh as a half-failed install from a
    # previous run and wipe it before retrying.
    if [ -d "${CONDA_DIR}" ] && [ ! -f "${CONDA_DIR}/etc/profile.d/conda.sh" ]; then
        echo "Detected incomplete miniconda install at ${CONDA_DIR}; removing."
        rm -rf "${CONDA_DIR}"
    fi
    if [ ! -d "${CONDA_DIR}" ]; then
        echo "Installing miniconda into ${CONDA_DIR}..."
        mkdir -p "${CONDA_DIR}"
        curl -fsSL "${MINICONDA_INSTALLER_URL}" -o "${CONDA_DIR}/miniconda.sh"
        bash "${CONDA_DIR}/miniconda.sh" -b -u -p "${CONDA_DIR}"
        rm -f "${CONDA_DIR}/miniconda.sh"
    fi
    # shellcheck disable=SC1091
    . "${CONDA_DIR}/etc/profile.d/conda.sh"
    conda config --set auto_activate_base false >/dev/null
}

conda_environment_exists() {
    conda env list | awk '{print $1}' | grep -qx "${CONDA_ENV_NAME}"
}

create_conda_environment() {
    echo "Creating conda env '${CONDA_ENV_NAME}' from ${ENV_FILE}..."
    conda env create -n "${CONDA_ENV_NAME}" -f "${ENV_FILE}" --yes
}

delete_conda_environment() {
    echo "Removing existing conda env '${CONDA_ENV_NAME}'..."
    conda env remove -n "${CONDA_ENV_NAME}" --yes >/dev/null
}

handle_installation() {
    if [ "${UPDATE_CONDA_ENV}" = "true" ] && conda_environment_exists; then
        delete_conda_environment
        create_conda_environment
    elif ! conda_environment_exists; then
        create_conda_environment
    else
        echo "Conda env '${CONDA_ENV_NAME}' already exists; reusing."
    fi
}

if [ -f ".netrc" ]; then
    cp ".netrc" "${HOME}/.netrc"
    chmod 600 "${HOME}/.netrc"
fi

install_conda
handle_installation
conda activate "${CONDA_ENV_NAME}"

case "${STAGE}" in
    run|preflight)
        CONFIG_PATH="${1:-config/run-config.json}"
        OUTPUT_DIR="${2:-${_tapisExecSystemOutputDir:-output}}"
        mkdir -p "${OUTPUT_DIR}"
        python -m subside_analysis.werc.cli "${STAGE}" \
            --config "${CONFIG_PATH}" \
            --output-dir "${OUTPUT_DIR}"
        ;;
    build-stack)
        # Per-stage inputs come from envVariables on the Workflows task so
        # the monolithic app's FIXED appArgs don't bleed in as positional args.
        python -m subside_analysis.werc.cli build-stack \
            --netcdf-dir       "${NETCDF_DIR:?STAGE=build-stack requires NETCDF_DIR}" \
            --output-stack     "${OUTPUT_STACK:?STAGE=build-stack requires OUTPUT_STACK}" \
            --output-products  "${OUTPUT_PRODUCTS:?STAGE=build-stack requires OUTPUT_PRODUCTS}"
        ;;
    compute-reference)
        python -m subside_analysis.werc.cli compute-reference \
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
        python -m subside_analysis.werc.cli estimate-velocity \
            --stack            "${STACK_INPUT:?STAGE=estimate-velocity requires STACK_INPUT}" \
            --output-velocity  "${OUTPUT_VELOCITY:?STAGE=estimate-velocity requires OUTPUT_VELOCITY}" \
            --output-summary   "${OUTPUT_SUMMARY:?STAGE=estimate-velocity requires OUTPUT_SUMMARY}"
        ;;
    export-geotiffs)
        python -m subside_analysis.werc.cli export-geotiffs \
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
