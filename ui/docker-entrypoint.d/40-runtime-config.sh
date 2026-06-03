#!/bin/sh
# Write the SPA's /runtime-config.js from deploy-time env vars so one built image
# serves any environment. The nginx:alpine entrypoint runs every executable in
# /docker-entrypoint.d/ (sorted) before starting nginx, so this lands before the
# first request. Only keys that are set are emitted; unset keys fall back to the
# app's build-time defaults (import.meta.env). Keys mirror the VITE_* names.
set -eu

CONFIG_PATH="/usr/share/nginx/html/runtime-config.js"

{
  echo 'window.__SUBSIDE_CONFIG__ = window.__SUBSIDE_CONFIG__ || {};'
  if [ -n "${SUBSIDE_API_BASE:-}" ]; then
    echo "window.__SUBSIDE_CONFIG__.VITE_SUBSIDE_API_BASE = \"${SUBSIDE_API_BASE}\";"
  fi
  if [ -n "${SUBSIDE_STAC_API_BASE:-}" ]; then
    echo "window.__SUBSIDE_CONFIG__.VITE_STAC_API_BASE = \"${SUBSIDE_STAC_API_BASE}\";"
  fi
  if [ -n "${SUBSIDE_STAC_COLLECTION:-}" ]; then
    echo "window.__SUBSIDE_CONFIG__.VITE_STAC_COLLECTION = \"${SUBSIDE_STAC_COLLECTION}\";"
  fi
} > "$CONFIG_PATH"

echo "[runtime-config] wrote $CONFIG_PATH (API base: ${SUBSIDE_API_BASE:-<none>})"
