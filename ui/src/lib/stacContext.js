// Dynamic *context* layers (basemap / reference overlays) discovered from STAC.
//
// The stac-platform `subside-context` Collection holds one Item per renderable
// map service (WMS / XYZ raster / MVT vector tiles / remote GeoJSON). Registering
// an Item there makes the layer appear in the map's Reference panel with no
// frontend deploy — see stac-platform/stacmap/context.py for the Item shape.
//
// Each Item carries a self-contained `subside:context` property block (the
// contract we control) plus a web-map-links link (for generic STAC clients). We
// read the property block and normalize every service kind to one flat config the
// ContextLayer adapter renders.
//
// When STAC is disabled or the collection can't be reached, we fall back to the
// previously-hardcoded ArcGIS aquifer overlays so the panel never goes empty.
import { getConfig } from './runtimeConfig'
import { REFERENCE_LAYERS } from '../components/mapworkbench/ReferenceLayers'

const BASE = getConfig('VITE_STAC_API_BASE').replace(/\/$/, '')
const COLLECTION = getConfig('VITE_STAC_CONTEXT_COLLECTION') || 'subside-context'

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
    service: ctx.service, // 'geojson' | 'wms' | 'xyz' | 'mvt'
    href,
    color: ctx.color || '#1d4ed8',
    style: ctx.style || null,
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
  }
}

// The pre-STAC hardcoded aquifer overlays, in the same flat shape, so the panel
// behaves identically when STAC is unavailable.
function fallbackLayers() {
  return REFERENCE_LAYERS.map((l) => ({
    id: l.id,
    label: l.label,
    group: 'Reference',
    kind: l.kind,
    service: 'geojson',
    href: l.url,
    color: l.color,
    style: null,
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
  }))
}

// Fetch and normalize the context layers. Never rejects: on any failure it
// resolves to the hardcoded fallback so the Reference panel stays populated.
export async function listContextLayers({ collection = COLLECTION } = {}) {
  if (!BASE) return fallbackLayers()
  try {
    const resp = await fetch(`${BASE}/collections/${collection}/items?limit=100`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const payload = await resp.json()
    const layers = (payload.features || []).map(fromStacItem).filter(Boolean)
    return layers.length ? layers : fallbackLayers()
  } catch {
    return fallbackLayers()
  }
}
