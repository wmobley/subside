// External "reference" overlays fetched live from ArcGIS — NOT ingested into
// PostGIS (nothing to re-seed, no DB load). This module exposes the layer
// config + a renderer; the toggle UI lives in the unified Layers panel
// (SubsideLayers), so there's a single on-map control.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { GeoJSON, useMap, useMapEvents } from 'react-leaflet'

// Categorical palette — one color per distinct aquifer name.
const PALETTE = [
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2',
  '#7f7f7f', '#bcbd22', '#17becf', '#393b79', '#637939', '#8c6d31', '#843c39',
  '#7b4173', '#3182bd', '#e6550d', '#31a354', '#756bb1', '#636363',
]

const ARCGIS = 'https://services1.arcgis.com/7DRakJXKPEhwv0fM/ArcGIS/rest/services/Z_Statewide_gdb/FeatureServer'
// f=geojson + outSR=4326 gives Leaflet-ready lon/lat; both layers are well under
// maxRecordCount (139 / 538), so a single query returns everything. The raw
// statewide polygons are ~33 MB, so simplify server-side (maxAllowableOffset in
// degrees ≈ 200 m, 5-decimal precision) → ~1.5 MB, plenty for a context overlay.
const query = (layer) =>
  `${ARCGIS}/${layer}/query?where=1%3D1&outFields=*&outSR=4326`
  + `&maxAllowableOffset=0.002&geometryPrecision=5&f=geojson`

export const REFERENCE_LAYERS = [
  { id: 'major-aquifers', label: 'Major aquifers', kind: 'Major aquifer', url: query(1), color: '#1d4ed8' },
  { id: 'minor-aquifers', label: 'Minor aquifers', kind: 'Minor aquifer', url: query(0), color: '#0d9488' },
]

// Best human name for a feature: AQ_NAME_UL is the title-cased name (e.g.
// "Seymour"); AQ_NAME/AQU_NAME are the uppercase variants. (AQUIFER is a numeric
// code and AREA is in degrees², so neither is shown.)
function featureName(props = {}) {
  return props.AQ_NAME_UL || props.AQ_NAME || props.AQU_NAME || null
}

function popupHtml(props, kind, color) {
  const name = featureName(props)
  const title = name ? `${name} Aquifer` : kind
  return (
    `<div class="ref-popup">`
    + `<div class="ref-popup-title">${title}</div>`
    + `<div class="ref-popup-kind"><span class="ref-popup-dot" style="background:${color}"></span>${kind}</div>`
    + `</div>`
  )
}

// Map each distinct aquifer name to a stable color (sorted so the assignment is
// deterministic across renders; cycles through the palette if names exceed it).
function makeColorScale(geojson) {
  const names = [...new Set(
    (geojson?.features || []).map((f) => featureName(f.properties)).filter(Boolean),
  )].sort()
  const byName = new Map(names.map((n, i) => [n, PALETTE[i % PALETTE.length]]))
  return (name) => byName.get(name) || '#888888'
}

// --- Esri FeatureServer (viewport-driven) ----------------------------------
// A FeatureServer layer can hold far more features than its maxRecordCount (TWDB
// Well Reports is ~680k points, cap 2000). So instead of one static fetch we
// re-query the layer's /query endpoint with the current map-bounds envelope on
// each pan/zoom, fetching only what's in view — what esri-leaflet's featureLayer
// does, but with zero new deps. A `minZoom` gate avoids trying to draw the whole
// state at once.

// Build the FeatureServer /query URL for the current bounds (lon/lat, f=geojson).
function featureQueryUrl(base, bounds, { where, queryFields } = {}) {
  const env = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`
  const params = new URLSearchParams({
    where: where || '1=1',
    geometry: env,
    geometryType: 'esriGeometryEnvelope',
    inSR: '4326',
    spatialRel: 'esriSpatialRelIntersects',
    outFields: (queryFields && queryFields.length ? queryFields : ['*']).join(','),
    outSR: '4326',
    returnGeometry: 'true',
    resultRecordCount: '2000',
    f: 'geojson',
  })
  return `${base.replace(/\/$/, '')}/query?${params.toString()}`
}

// Epoch-ms fields (Esri returns dates as ms) -> a plain date; everything else verbatim.
function formatValue(key, value) {
  if (value == null || value === '') return null
  if (/date/i.test(key) && typeof value === 'number') {
    return new Date(value).toISOString().slice(0, 10)
  }
  return String(value)
}

// Inner popup content (title + property rows), without the outer wrapper — shared
// by the static HTML popup and the interactive "pick reference" DOM popup.
function featurePopupInner(props = {}, title, color) {
  const rows = Object.entries(props)
    .map(([k, v]) => [k, formatValue(k, v)])
    .filter(([, v]) => v != null)
    .map(([k, v]) => `<div class="ref-popup-row"><span class="ref-popup-key">${k}</span> ${v}</div>`)
    .join('')
  return (
    `<div class="ref-popup-title"><span class="ref-popup-dot" style="background:${color}"></span>${title}</div>`
    + rows
  )
}

function featurePopupHtml(props = {}, title, color) {
  return `<div class="ref-popup">${featurePopupInner(props, title, color)}</div>`
}

// A popup DOM node that adds a "use as velocity reference" button. Built as a real
// element (not an HTML string) so the button can call back into React. `onPick`
// receives the mark's {lat, lon, label}.
function featurePickNode(props, title, color, point, onPick) {
  const wrap = document.createElement('div')
  wrap.className = 'ref-popup'
  wrap.innerHTML = featurePopupInner(props, title, color)
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'ref-popup-pick'
  btn.textContent = '★ Use as velocity reference'
  btn.addEventListener('click', () => onPick(point))
  wrap.appendChild(btn)
  return wrap
}

export function ReferenceFeatureServer({
  url, label, style, color, opacity, minZoom, queryFields, where, onError, onPickReference,
}) {
  const map = useMap()
  const [data, setData] = useState(null)
  const [version, setVersion] = useState(0)
  const abortRef = useRef(null)

  const refresh = useCallback(() => {
    // Below the gate, drawing the whole extent would blow past maxRecordCount —
    // clear instead so the map shows nothing until the user zooms in.
    if (minZoom != null && map.getZoom() < minZoom) {
      setData(null)
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    fetch(featureQueryUrl(url, map.getBounds(), { where, queryFields }), { signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((gj) => { setData(gj); setVersion((v) => v + 1) })
      .catch((e) => { if (e.name !== 'AbortError') onError?.(e.message) })
  }, [map, url, where, queryFields, minZoom, onError])

  // Initial load + reload on every pan/zoom settle.
  useEffect(() => { refresh() }, [refresh])
  useMapEvents({ moveend: refresh, zoomend: refresh })
  useEffect(() => () => abortRef.current?.abort(), [])

  const c = style?.color || color || '#b45309'
  const radius = style?.radius ?? 3
  const fillColor = style?.fillColor || c
  const fillOpacity = (style?.fillOpacity ?? 0.85) * (opacity ?? 1)

  if (!data) return null
  return (
    <GeoJSON
      key={version}
      data={data}
      pointToLayer={(feature, latlng) =>
        L.circleMarker(latlng, {
          radius, color: c, weight: style?.weight ?? 1,
          fill: true, fillColor, fillOpacity,
        })
      }
      onEachFeature={(feature, layer) => {
        const props = feature.properties || {}
        const title = label || 'Feature'
        if (onPickReference) {
          // Point features only: coordinates are [lon, lat] (outSR=4326).
          const coords = feature.geometry?.coordinates || []
          const point = {
            lon: Number(coords[0]),
            lat: Number(coords[1]),
            label: props.NAME || props.PID || title,
          }
          layer.bindPopup(featurePickNode(props, title, c, point, (pt) => {
            onPickReference(pt)
            map.closePopup()
          }))
        } else {
          layer.bindPopup(featurePopupHtml(props, title, c))
        }
      }}
    />
  )
}

export function ReferenceGeoJSON({ url, kind, opacity, onError }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let cancelled = false
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((gj) => { if (!cancelled) setData(gj) })
      .catch((e) => { if (!cancelled) onError?.(e.message) })
    return () => { cancelled = true }
  }, [url, onError])

  const colorFor = useMemo(() => makeColorScale(data), [data])

  if (!data) return null
  return (
    <GeoJSON
      data={data}
      style={(feature) => {
        const c = colorFor(featureName(feature.properties))
        return { color: c, weight: 1, fill: true, fillColor: c, fillOpacity: 0.35 * (opacity ?? 1) }
      }}
      onEachFeature={(feature, layer) => {
        const c = colorFor(featureName(feature.properties))
        layer.bindPopup(popupHtml(feature.properties || {}, kind, c))
      }}
    />
  )
}
