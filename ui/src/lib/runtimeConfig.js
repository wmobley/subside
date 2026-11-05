// Resolve a config value at runtime: prefer window.__SUBSIDE_CONFIG__ (injected
// by /runtime-config.js at container start, so one built image serves any
// environment), then fall back to the build-time Vite env (import.meta.env),
// then "". Keys are the VITE_* names so dev (.env / import.meta.env) and prod
// (injected runtime-config.js) use the same identifiers.
export function getConfig(key) {
  const runtime =
    typeof window !== 'undefined' ? window.__SUBSIDE_CONFIG__?.[key] : undefined
  return runtime ?? import.meta.env?.[key] ?? ''
}

// Where SUBSIDE runs are submitted/listed: "legacy" = the SUBSIDE API's own Tapis
// Workflows pipelines (default), "dynamo" = the MINT Ensemble Manager (DYNAMO).
// A development switch, not a user-facing toggle. Read at call time so runtime
// config injected after module load (and tests) are honoured.
export function runBackend() {
  return String(getConfig('VITE_RUN_BACKEND') || 'legacy').toLowerCase() === 'dynamo'
    ? 'dynamo'
    : 'legacy'
}

// Ensemble Manager base URL incl. version, e.g. http://localhost:3001/v1.
export function dynamoApiBase() {
  return String(getConfig('VITE_DYNAMO_API_BASE') || '').replace(/\/$/, '')
}
