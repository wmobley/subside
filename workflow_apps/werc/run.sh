#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-config/run-config.json}"
OUTPUT_DIR="${2:-${_tapisExecSystemOutputDir:-output}}"

if [ -f ".netrc" ]; then
  cp ".netrc" "${HOME}/.netrc"
  chmod 600 "${HOME}/.netrc"
fi

mkdir -p "${OUTPUT_DIR}"

python -m subside_analysis.werc.cli run \
  --config "${CONFIG_PATH}" \
  --output-dir "${OUTPUT_DIR}"
