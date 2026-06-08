// Renders a STAC Item's COG asset (a public CKAN URL) as a raster on the map.
//
// Sibling to CogLayer.jsx: that one streams a workflow artifact through the
// authenticated SUBSIDE API proxy; this one fetches a public STAC asset href
// directly (the CKAN resource download URL must allow CORS + range requests).
// Shares the viridis ramp + display-range scaling behavior.
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'

const loadGeoraster = () => Promise.all([
  import('georaster').then((m) => m.default),
  import('georaster-layer-for-leaflet').then((m) => m.default),
])

const VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e',
  '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725']

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
function viridis(t) {
  const x = Math.max(0, Math.min(1, t)) * (VIRIDIS.length - 1)
  const a = Math.floor(x)
  const b = Math.min(a + 1, VIRIDIS.length - 1)
  const f = x - a
  const ca = hexToRgb(VIRIDIS[a])
  const cb = hexToRgb(VIRIDIS[b])
  const c = ca.map((v, i) => Math.round(v + (cb[i] - v) * f))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

export function StacCogLayer({ href, range, opacity = 0.8, fit = true, onError }) {
  const map = useMap()

  useEffect(() => {
    if (!href) return undefined
    let layer
    let cancelled = false
    fetch(href)
      .then((r) => {
        if (!r.ok) throw new Error(`COG fetch ${r.status}`)
        return r.arrayBuffer()
      })
      .then((buf) => Promise.all([buf, loadGeoraster()]))
      .then(([buf, [parseGeoraster, GeoRasterLayer]]) => parseGeoraster(buf).then((g) => [g, GeoRasterLayer]))
      .then(([georaster, GeoRasterLayer]) => {
        if (cancelled) return
        const min = range?.vmin ?? georaster.mins?.[0] ?? 0
        const max = range?.vmax ?? georaster.maxs?.[0] ?? 1
        const span = max - min || 1
        const noData = georaster.noDataValue
        layer = new GeoRasterLayer({
          georaster,
          opacity,
          resolution: 256,
          pixelValuesToColorFn: (values) => {
            const v = values[0]
            if (v == null || Number.isNaN(v) || v === noData) return null
            return viridis((v - min) / span)
          },
        })
        layer.addTo(map)
        if (fit) {
          try { map.fitBounds(layer.getBounds()) } catch { /* ignore */ }
        }
      })
      .catch((err) => { if (!cancelled) onError?.(err?.message || 'COG failed to load') })

    return () => {
      cancelled = true
      if (layer) map.removeLayer(layer)
    }
  }, [map, href]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}
