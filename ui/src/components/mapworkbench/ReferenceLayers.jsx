// External "reference" overlays fetched live from ArcGIS — NOT ingested into
// PostGIS (nothing to re-seed, no DB load). This module exposes the layer
// config + a renderer; the toggle UI lives in the unified Layers panel
// (SubsideLayers), so there's a single on-map control.
import { useEffect, useMemo, useState } from 'react'
import { GeoJSON } from 'react-leaflet'

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

export function ReferenceGeoJSON({ url, kind, onError }) {
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
        return { color: c, weight: 1, fill: true, fillColor: c, fillOpacity: 0.35 }
      }}
      onEachFeature={(feature, layer) => {
        const c = colorFor(featureName(feature.properties))
        layer.bindPopup(popupHtml(feature.properties || {}, kind, c))
      }}
    />
  )
}
