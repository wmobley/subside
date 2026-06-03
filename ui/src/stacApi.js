// Client for the stac-platform STAC API (search + asset helpers).
//
// The STAC API is a separate service from the SUBSIDE API. Point the UI at it
// with VITE_STAC_API_BASE (e.g. https://stac-api.pods.portals.tapis.io). When
// unset, STAC features are disabled (stacEnabled() === false).
//
// STAC responds with `application/geo+json` (not `application/json`), so we use
// fetch directly rather than the SUBSIDE `requestJson` (which asserts JSON).
import { getConfig } from './runtimeConfig'

const BASE = getConfig('VITE_STAC_API_BASE').replace(/\/$/, '')
// Default collection = the SUBSIDE subsidence-rates CKAN dataset.
const COLLECTION = getConfig('VITE_STAC_COLLECTION') || 'subsidence-rates'

export function stacEnabled() {
  return Boolean(BASE)
}

// Search items by viewport bbox (+ optional datetime range). `bounds` is a
// Leaflet LatLngBounds. Returns the STAC FeatureCollection's `features` array.
export async function searchItems(bounds, { collection = COLLECTION, datetime, limit = 50 } = {}) {
  if (!BASE) return []
  const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]
    .map((n) => Number(n.toFixed(6)))
  const body = { collections: [collection], bbox, limit }
  if (datetime) body.datetime = datetime
  const resp = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    throw new Error(`STAC search failed: ${resp.status} ${resp.statusText}`)
  }
  const payload = await resp.json()
  return payload.features || []
}

// Asset href helpers. Assets are keyed by role in stacmap/assets.py:
//   cog -> displacement COG, overlay -> PNG quick-look, metadata -> manifest.
export function cogHref(item) {
  return item?.assets?.cog?.href || null
}
export function overlayHref(item) {
  return item?.assets?.overlay?.href || null
}
// Per-band display range carried onto the COG asset (for the viridis ramp).
export function cogRange(item) {
  const stats = item?.assets?.cog?.['raster:bands']?.[0]?.statistics
  if (!stats) return null
  return { vmin: stats.minimum, vmax: stats.maximum }
}
