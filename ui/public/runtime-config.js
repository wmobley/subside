/* eslint-disable */
// Runtime configuration. In a deployed container this file is REWRITTEN at
// startup by docker-entrypoint.d/40-runtime-config.sh from the pod's env vars
// (e.g. SUBSIDE_API_BASE), so one image serves any environment without a rebuild.
//
// In local dev it stays empty and the app falls back to import.meta.env / the
// Vite proxy (see ui/src/runtimeConfig.js). Keys mirror the VITE_* names.
window.__SUBSIDE_CONFIG__ = window.__SUBSIDE_CONFIG__ || {};
