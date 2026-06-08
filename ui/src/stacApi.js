// Client for the stac-platform STAC API (search + asset helpers).
//
// The STAC API is a separate service from the SUBSIDE API. Point the UI at it
// with VITE_STAC_API_BASE (e.g. https://stacapi.pods.portals.tapis.io). When
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

// Asset href helpers. Assets are keyed in stacmap/publish.py:
//   h2i  -> cog (displacement), overlay (PNG), metadata (manifest)
//   werc -> cumulative, velocity (each a COG), overlay, metadata
export function cogHref(item) {
  return item?.assets?.cog?.href || null
}
export function overlayHref(item) {
  return item?.assets?.overlay?.href || null
}
// Per-band display range carried onto a COG asset (for the viridis ramp).
function assetRange(asset) {
  const stats = asset?.['raster:bands']?.[0]?.statistics
  if (!stats) return null
  return { vmin: stats.minimum, vmax: stats.maximum }
}
export function cogRange(item) {
  return assetRange(item?.assets?.cog)
}

// Fallback units by COG asset key, used until the publisher carries an explicit
// `raster:bands[].unit` (see the stac-platform unit follow-up). h2i displacement
// pixels are meters; werc cumulative is mm and velocity is mm/yr.
const UNIT_BY_KEY = { cog: 'm', cumulative: 'mm', velocity: 'mm/yr' }
function assetUnit(asset, key) {
  return asset?.['raster:bands']?.[0]?.unit || UNIT_BY_KEY[key] || ''
}

// COG asset keys, in display order. Pipeline-dependent (see publish.py).
const COG_KEYS = ['cog', 'cumulative', 'velocity']

// Renderable layers from a published Item, in display order:
//   COG assets  -> {type:'cog', href, range, unit}  (StacCogLayer)
//   overlay PNG -> {type:'png', href}               (ImageOverlay)
export function itemLayers(item) {
  const assets = item?.assets || {}
  const layers = []
  for (const key of COG_KEYS) {
    const a = assets[key]
    if (a?.href) layers.push({ key, type: 'cog', href: a.href, label: a.title || key, range: assetRange(a), unit: assetUnit(a, key) })
  }
  const ov = assets.overlay
  if (ov?.href) layers.push({ key: 'overlay', type: 'png', href: ov.href, label: ov.title || 'Displacement (preview)' })
  return layers
}

// Human-facing item metadata the panels surface (acquisition window, how many
// OPERA products went in, which frames). Keys are set by the publisher's
// granule_from_subside_manifest (stac-platform/stacmap/manifest.py).
export function itemMeta(item) {
  const p = item?.properties || {}
  return {
    start: p.start_datetime || p.datetime || null,
    end: p.end_datetime || null,
    productCount: p['subside:product_count'] ?? null,
    frameIds: p['subside:frame_ids'] || null,
  }
}

// Every downloadable asset (products + metadata) as {key, name, href}. Public
// CKAN hrefs, so downloads no longer go through the authenticated API proxy.
export function itemDownloads(item) {
  const assets = item?.assets || {}
  return Object.entries(assets)
    .filter(([, a]) => a?.href)
    .map(([key, a]) => ({ key, name: a.title || key, href: a.href }))
}

// Temporal anchor for newest-first sorting.
function itemTime(item) {
  const p = item?.properties || {}
  return p.updated || p.created || p.end_datetime || p.datetime || p.start_datetime || ''
}

// Find the STAC Item a finished run published. The publisher derives item ids
// from the archive path (no clean runId link), so we match on the run's AOI
// bbox + date window and take the most recently published item. `bbox` is
// [west, south, east, north]. Returns null when STAC is disabled or no match.
export async function findRunItem({ bbox, start, end, collection = COLLECTION } = {}) {
  if (!BASE || !Array.isArray(bbox) || bbox.length !== 4) return null
  const body = {
    collections: [collection],
    bbox: bbox.map((n) => Number(Number(n).toFixed(6))),
    limit: 20,
  }
  if (start && end) body.datetime = `${start}T00:00:00Z/${end}T23:59:59Z`
  const resp = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`STAC search failed: ${resp.status} ${resp.statusText}`)
  const payload = await resp.json()
  const feats = payload.features || []
  feats.sort((a, b) => itemTime(b).localeCompare(itemTime(a)))
  return feats[0] || null
}
