#!/usr/bin/env bash
#
# Register SUBSIDE's STAC context layers + external CKAN datasets from the specs
# in this folder, using the project-agnostic stac-platform library.
#
# Prereqs:
#   * stac-platform installed:  pip install "git+https://github.com/wmobley/stac-platform"
#   * STAC_URL + STAC_TOKEN  (context layers -> STAC Transactions API), and
#     CKAN_URL + CKAN_TOKEN  (external datasets -> CKAN).
#     If tokens are absent, the stacmap CLIs mint a Tapis JWT from
#     TAPIS_BASE_URL / TAPIS_USERNAME / TAPIS_PASSWORD.
#
# Usage (from subside/):  ./stac/register.sh  [context|external|all]

set -euo pipefail
cd "$(dirname "$0")/.."          # subside/
PY="${PYTHON:-python}"
WHAT="${1:-all}"

if [ "$WHAT" = "all" ] || [ "$WHAT" = "context" ]; then
  echo "== register context layers -> STAC (subside-context) =="
  $PY -m stacmap.register_context --specs stac/context_layers.json
fi
if [ "$WHAT" = "all" ] || [ "$WHAT" = "external" ]; then
  echo "== register external datasets -> CKAN =="
  $PY -m stacmap.register_external --specs stac/external_datasets.json
fi
echo "done."
