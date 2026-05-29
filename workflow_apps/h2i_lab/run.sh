#!/usr/bin/env bash
# H2I Lab Tapis batch entrypoint.
#
# Mirrors the TACC cookbook pattern (notebookExamples/h2i_lab/run.sh):
# miniconda is installed at runtime under a persistent path, the conda
# environment is created from environment.yaml on first invocation, and
# subsequent runs reuse it. Set UPDATE_CONDA_ENV=true to force a rebuild.

set -euo pipefail

CONFIG_PATH="${1:-config/run-config.json}"
OUTPUT_DIR="${2:-${_tapisExecSystemOutputDir:-output}}"

# Persist conda install + env across job runs.
# Tapis on TACC sets $WORK; ENV_INSTALL_DIR overrides for local Docker tests.
ENV_INSTALL_DIR="${ENV_INSTALL_DIR:-${WORK:-/work}}"
CONDA_DIR="${ENV_INSTALL_DIR}/miniconda3"
CONDA_ENV_NAME="${CONDA_ENV_NAME:-subside-h2i-opera}"
UPDATE_CONDA_ENV="${UPDATE_CONDA_ENV:-false}"

# Pin: py312 base so disp-xr (requires Python >=3.12) installs cleanly.
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

# Stage Earthdata netrc if Tapis supplied one alongside the job inputs.
if [ -f ".netrc" ]; then
    cp ".netrc" "${HOME}/.netrc"
    chmod 600 "${HOME}/.netrc"
fi

mkdir -p "${OUTPUT_DIR}"

install_conda
handle_installation
conda activate "${CONDA_ENV_NAME}"

python -m subside_analysis.h2i_lab.cli run \
    --config "${CONFIG_PATH}" \
    --output-dir "${OUTPUT_DIR}"
