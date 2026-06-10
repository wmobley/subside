// The map's vector-layer catalog, discovered from STAC.
//
// STAC is the *meta repo*: one `subside-context` Collection holds an Item per
// renderable layer (the SUBSIDE PostGIS layers served as MVT by the API, plus
// external WMS / XYZ / GeoJSON overlays). Each Item carries where the tiles are
// served (`assets.service.href`) and how to present it (title, style, group,
// visibility) in a self-contained `subside:context` property block. Registering
// an Item makes a layer appear on the map with no frontend deploy — see
// stac-platform/stacmap/context.py.
//
// Fallback: if STAC is disabled or unreachable we rebuild the catalog from the
// SUBSIDE API's own layer registry (GET /api/subside/layers) plus the built-in
// ArcGIS aquifer overlays, so the map degrades to its pre-STAC behavior.
import { getConfig } from './runtimeConfig'
import { REFERENCE_LAYERS } from '../components/mapworkbench/ReferenceLayers'
import { listLayers, tileUrlTemplate } from './subsideApi'

const BASE = getConfig('VITE_STAC_API_BASE').replace(/\/$/, '')
const COLLECTION = getConfig('VITE_STAC_CONTEXT_COLLECTION') || 'subside-context'

// The OPERA frame-footprint layer (role 'availability') is no longer a map
// overlay: its frames are too large to select as a run AOI (they time out the
// workflow). The data now drives an advisory "products available to download"
// guide in the analysis panel instead — see SubsideAnalysis. Drop it from the
// rendered catalog here, at the single chokepoint, so it's hidden whether the
// catalog comes from STAC or the API fallback (and regardless of any stale
// registration still present in the STAC collection).
const HIDDEN_ROLE = 'availability'
const isShown = (l) => l && l.role !== HIDDEN_ROLE

// Categorical palette for fallback layers that carry no explicit color.
const FALLBACK_PALETTE = ['#2563eb', '#7c3aed', '#0d9488', '#c2410c', '#9333ea', '#0891b2', '#4d7c0f']

// A default VectorGrid style hint for a geometry type (used by the API fallback).
function styleForGeom(geomType, color) {
  if (/linestring/i.test(geomType || '')) return { geomType: 'LineString', color, weight: 2 }
  if (/polygon|geometry/i.test(geomType || '')) {
    return { geomType: 'Polygon', color, weight: 1, fillColor: color, fillOpacity: 0.15 }
  }
  return { geomType: 'Point', color, radius: 4, fillColor: color, fillOpacity: 0.8 }
}

// Normalize one STAC context Item -> the flat layer config the UI renders.
function fromStacItem(item) {
  const ctx = item?.properties?.['subside:context'] || {}
  const href = item?.assets?.service?.href || null
  if (!href || !ctx.service) return null
  return {
    id: item.id,
    label: item?.properties?.title || item.id,
    group: ctx.group || 'Reference',
    kind: ctx.kind || null,
    service: ctx.service, // 'geojson' | 'feature-server' | 'wms' | 'xyz' | 'mvt'
    href,
    color: ctx.color || '#1d4ed8',
    style: ctx.style || null,
    role: ctx.role || null, // e.g. 'availability' for the OPERA frame layer
    visibleWhen: ctx.visible_when || null, // 'authed' | 'anon' | 'always' | 'never'
    opacity: ctx.opacity ?? null,
    minZoom: ctx.min_zoom ?? null,
    maxZoom: ctx.max_zoom ?? null,
    attribution: ctx.attribution || null,
    legend: ctx.legend || null,
    defaultVisible: Boolean(ctx.default_visible),
    wmsLayers: ctx.wms_layers || null,
    wmsStyles: ctx.wms_styles || null,
    wmsTransparent: ctx.wms_transparent ?? null,
    format: ctx.format || null,
    sourceLayers: ctx.source_layers || null,
    featureCount: ctx.feature_count ?? null,
    // feature-server (Esri FeatureServer): outFields requested per viewport query
    // (drives the popup) + an optional server-side WHERE filter.
    queryFields: ctx.query_fields || null,
    where: ctx.where || null,
  }
}

// Normalize a SUBSIDE API registry row (GET /api/subside/layers) -> the same
// flat shape, for the no-STAC fallback. `satellite` keeps its availability role.
function fromApiRow(row, i) {
  const isAvailability = row.name === 'satellite'
  const color = isAvailability ? '#16a34a' : FALLBACK_PALETTE[i % FALLBACK_PALETTE.length]
  return {
    id: row.name,
    label: row.name,
    group: 'SUBSIDE',
    kind: null,
    service: 'mvt',
    href: tileUrlTemplate(row.name),
    color,
    style: styleForGeom(row.geom_type, color),
    role: isAvailability ? 'availability' : null,
    // Mirror the STAC policy in the fallback: the OPERA frame layer defaults on
    // only for logged-in users.
    visibleWhen: isAvailability ? 'authed' : null,
    opacity: null,
    minZoom: null,
    maxZoom: null,
    attribution: null,
    legend: null,
    defaultVisible: true,
    wmsLayers: null,
    wmsStyles: null,
    wmsTransparent: null,
    format: null,
    sourceLayers: [row.name],
    featureCount: row.feature_count ?? null,
    queryFields: null,
    where: null,
  }
}

// The built-in ArcGIS aquifer overlays in the flat shape (off by default).
function aquiferFallback() {
  return REFERENCE_LAYERS.map((l) => ({
    id: l.id,
    label: l.label,
    group: 'Reference',
    kind: l.kind,
    service: 'geojson',
    href: l.url,
    color: l.color,
    style: null,
    role: null,
    // Major aquifers stand in for anonymous users (when the OPERA layer is hidden).
    visibleWhen: l.id === 'major-aquifers' ? 'anon' : null,
    opacity: 0.35,
    minZoom: null,
    maxZoom: null,
    attribution: 'Texas aquifers · live from ArcGIS',
    legend: null,
    defaultVisible: false,
    wmsLayers: null,
    wmsStyles: null,
    wmsTransparent: null,
    format: null,
    sourceLayers: null,
    featureCount: null,
    queryFields: null,
    where: null,
  }))
}

// Rebuild the catalog without STAC: the API's own layers + the aquifer overlays.
async function fallbackCatalog() {
  let apiLayers = []
  try {
    apiLayers = await listLayers()
  } catch {
    apiLayers = []
  }
  return [...apiLayers.map(fromApiRow), ...aquiferFallback()].filter(isShown)
}

// Discover every vector layer the map should offer. Prefers the STAC catalog;
// resolves to the API+aquifer fallback when STAC is disabled, unreachable, or
// empty. Never rejects.
export async function listContextLayers({ collection = COLLECTION } = {}) {
  if (BASE) {
    try {
      const resp = await fetch(`${BASE}/collections/${collection}/items?limit=200`)
      if (resp.ok) {
        const payload = await resp.json()
        const layers = (payload.features || []).map(fromStacItem).filter(isShown)
        if (layers.length) return layers
      }
    } catch {
      // fall through to the fallback catalog
    }
  }
  return fallbackCatalog()
}
