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
