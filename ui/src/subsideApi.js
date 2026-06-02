// Client for the SUBSIDE FastAPI (layers / tiles / availability).
//
// In dev these go through the Vite proxy (`/api/subside` -> :8000). For other
// deployments set VITE_SUBSIDE_API_BASE to the API origin.
import { requestJson } from './api'

const BASE = (import.meta.env?.VITE_SUBSIDE_API_BASE || '').replace(/\/$/, '')

const path = (p) => `${BASE}/api/subside${p}`

// Registry rows: [{ name, geom_type, srid, columns, feature_count, bbox, ... }]
export async function listLayers() {
  const payload = await requestJson(path('/layers'))
  return payload.layers || []
}

// MVT tile-URL template for Leaflet.VectorGrid (it fills {z}/{x}/{y}).
export function tileUrlTemplate(layer) {
  return path(`/tiles/${encodeURIComponent(layer)}/{z}/{x}/{y}.mvt`)
}

// Viewport-lazy availability for the frame-footprint layer. `bbox` is a Leaflet
// LatLngBounds. Returns { items: [{ frame_id, product_count, latest_date, ... }], ... }.
export async function fetchAvailability(bounds, { layer = 'satellite', ttlHours, startDate, endDate } = {}) {
  const bbox = [
    bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth(),
  ].map((n) => n.toFixed(6)).join(',')
  const params = new URLSearchParams({ bbox, layer })
  if (ttlHours != null) params.set('ttl_hours', String(ttlHours))
  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)
  return requestJson(path(`/availability?${params.toString()}`))
}

// --- forecast (potential subsidence — in-process, no auth, no Tapis job) ----

// Run the screening model for a scenario; returns { risk_score, projection,
// annual, risk_factors, ... }. `scenario` uses visible Excel-style labels.
export async function runForecast(scenario) {
  return requestJson(path('/forecast'), {
    method: 'POST',
    body: JSON.stringify({ scenario }),
  })
}

// A starter scenario the UI can run or let the user edit. Returns { scenario }.
export async function getForecastTemplate() {
  const payload = await requestJson(path('/forecast/template'))
  return payload.scenario || {}
}

// --- auth (Tapis OAuth2 "Log in with TACC" redirect flow) -------------------

const OAUTH_STATE_KEY = 'subside.oauthState'

// Non-secret config for building the authorize redirect: { base_url, client_id,
// callback_url, authorize_url }.
export async function getAuthConfig() {
  return requestJson(path('/auth/config'))
}

// Server-side exchange of the OAuth2 authorization code for a Tapis token (the
// client_key stays on the API). Returns { token, username, expires_at }.
export async function exchangeAuthCode(code) {
  return requestJson(path('/auth/token'), {
    method: 'POST',
    body: JSON.stringify({ code }),
  })
}

// Begin the redirect login: fetch config, stash a CSRF `state`, and send the
// browser to the Tapis-hosted authorize page. Returns nothing (navigates away).
export async function startTapisLogin() {
  const cfg = await getAuthConfig()
  const state = (window.crypto?.randomUUID?.() || `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`)
  sessionStorage.setItem(OAUTH_STATE_KEY, state)
  const url = `${cfg.authorize_url}?client_id=${encodeURIComponent(cfg.client_id)}`
    + `&redirect_uri=${encodeURIComponent(cfg.callback_url)}`
    + `&response_type=code&state=${encodeURIComponent(state)}`
  window.location.assign(url)
}

// Read the stored CSRF state and clear it (single-use).
export function takeOAuthState() {
  const s = sessionStorage.getItem(OAUTH_STATE_KEY)
  sessionStorage.removeItem(OAUTH_STATE_KEY)
  return s
}

// --- runs (Tapis jobs on TACC, as the logged-in user) ----------------------

// Password grant -> a Tapis access token. Returns { token, username }.
// Retained for scripts/dev; the web app uses the OAuth2 redirect flow above.
export async function login(username, password) {
  return requestJson(path('/login'), {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

// Submit a pipeline run. `token` is the Tapis token from login(); it rides on
// the X-Tapis-Token header the API's require_client dependency expects.
export async function submitRun(token, body) {
  return requestJson(path('/runs'), {
    method: 'POST',
    headers: { 'X-Tapis-Token': token },
    body: JSON.stringify(body),
  })
}

// The caller's durable job history (Tapis jobs submitted with our pipeline apps).
export async function listRuns(token) {
  return requestJson(path('/runs'), { headers: { 'X-Tapis-Token': token } })
}

export async function getRunStatus(token, runId) {
  return requestJson(path(`/runs/${encodeURIComponent(runId)}`), {
    headers: { 'X-Tapis-Token': token },
  })
}

export async function getRunResults(token, runId) {
  return requestJson(path(`/runs/${encodeURIComponent(runId)}/results`), {
    headers: { 'X-Tapis-Token': token },
  })
}

function fileUrl(runId, archivePath) {
  return path(`/runs/${encodeURIComponent(runId)}/file?path=${encodeURIComponent(archivePath)}`)
}

// Fetch one archive file through the API proxy (same-origin + token header) and
// return an object URL — usable as a Leaflet ImageOverlay/`<img>` src or download.
export async function fetchArtifactBlob(token, runId, archivePath) {
  const res = await fetch(fileUrl(runId, archivePath), { headers: { 'X-Tapis-Token': token } })
  if (!res.ok) throw new Error(`File ${res.status} ${res.statusText}`)
  return URL.createObjectURL(await res.blob())
}

// Same, but as an ArrayBuffer — for parsing a COG GeoTIFF client-side.
export async function fetchArtifactArrayBuffer(token, runId, archivePath) {
  const res = await fetch(fileUrl(runId, archivePath), { headers: { 'X-Tapis-Token': token } })
  if (!res.ok) throw new Error(`File ${res.status} ${res.statusText}`)
  return res.arrayBuffer()
}

// Build a one-feature Polygon FeatureCollection from a [w, s, e, n] bbox.
export function bboxToAoiGeoJSON(bbox) {
  const [w, s, e, n] = bbox
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
    }],
  }
}
