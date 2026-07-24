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
// OPERA products went in, which frames, and a best-effort location name).
// Keys are set by the publisher's parse_manifest (stac-platform/stacmap/manifest.py).
export function itemMeta(item) {
  const p = item?.properties || {}
  const refLat = p['subside:reference_lat']
  const refLon = p['subside:reference_lon']
  const hasRef = Number.isFinite(Number(refLat)) && Number.isFinite(Number(refLon))
  return {
    start: p.start_datetime || p.datetime || null,
    end: p.end_datetime || null,
    productCount: p['subside:product_count'] ?? null,
    frameIds: p['subside:frame_ids'] || null,
    // Best-effort place name (e.g. "New Braunfels, Texas"), resolved once at
    // publish time -- absent on runs published before this field existed.
    location: p['subside:location'] || null,
    // The static reference point velocities are measured against, if published.
    reference: hasRef ? { lat: Number(refLat), lon: Number(refLon), mode: p['subside:reference_mode'] || null } : null,
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

function bboxToFeatureCollection(bbox) {
  const values = Array.isArray(bbox)
    ? bbox
    : bbox && typeof bbox === 'object'
      ? [bbox.lon_min, bbox.lat_min, bbox.lon_max, bbox.lat_max]
      : null
  if (!values || values.length !== 4) return null
  const [w, s, e, n] = values.map(Number)
  if ([w, s, e, n].some((v) => !Number.isFinite(v))) return null
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] },
    }],
  }
}

function toFeatureCollection(gj) {
  if (!gj || typeof gj !== 'object') return null
  if (gj.type === 'FeatureCollection') return gj
  if (gj.type === 'Feature') return { type: 'FeatureCollection', features: [gj] }
  if (gj.type && gj.coordinates) {
    return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: gj }] }
  }
  return null
}

function boundaryFromPayload(payload) {
  const direct = toFeatureCollection(payload)
  if (direct?.features?.length) return direct

  const candidates = [
    payload?.aoi_geojson,
    payload?.aoi,
    payload?.boundary,
    payload?.boundaries,
    payload?.geometry,
    payload?.config?.aoi_geojson,
    payload?.config?.aoi,
  ]
  for (const candidate of candidates) {
    const fc = toFeatureCollection(candidate)
    if (fc?.features?.length) return fc
  }
  return bboxToFeatureCollection(payload?.bbox)
}

function isBoundaryAsset(key, asset) {
  const haystack = [
    key,
    asset?.title,
    asset?.href,
    ...(asset?.roles || []),
  ].join(' ').toLowerCase()
  return /(^|[^a-z])(aoi|boundary|boundaries|area[-_ ]of[-_ ]interest)([^a-z]|$)/.test(haystack)
}

function boundaryAssetCandidates(item) {
  const assets = item?.assets || {}
  const preferred = ['boundaries', 'boundary', 'aoi', 'aoi_geojson', 'aoi-geojson', 'area_of_interest', 'area-of-interest']
  const out = []
  for (const key of preferred) {
    if (assets[key]?.href) out.push([key, assets[key]])
  }
  for (const entry of Object.entries(assets)) {
    const [key, asset] = entry
    if (asset?.href && isBoundaryAsset(key, asset) && !out.some(([k]) => k === key)) out.push(entry)
  }
  return out
}

async function fetchJsonAsset(asset) {
  const resp = await fetch(asset.href)
  if (!resp.ok) throw new Error(`Could not read boundary asset: ${resp.status} ${resp.statusText}`)
  return resp.json()
}

// Reusable AOI/boundary for a published run. Newer stac-platform items can carry
// a dedicated boundary/AOI GeoJSON asset; older items fall back to metadata
// fields, then the STAC Item geometry/bbox so a velocity follow-up can still use
// the same catalog footprint.
export async function itemBoundaryGeoJSON(item) {
  for (const [, asset] of boundaryAssetCandidates(item)) {
    try {
      const fc = boundaryFromPayload(await fetchJsonAsset(asset))
      if (fc?.features?.length) return fc
    } catch {
      // Try the next candidate; public CKAN assets may lag CORS/cache config.
    }
  }

  const metadata = item?.assets?.metadata
  if (metadata?.href) {
    try {
      const fc = boundaryFromPayload(await fetchJsonAsset(metadata))
      if (fc?.features?.length) return fc
    } catch {
      // Fall through to the STAC geometry/bbox.
    }
  }

  return boundaryFromPayload(item?.geometry) || bboxToFeatureCollection(item?.bbox)
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
