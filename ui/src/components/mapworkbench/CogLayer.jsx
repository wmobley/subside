// Renders a pipeline run's Cloud-Optimized GeoTIFF as a real raster on the Leaflet map.
//
// Fetches the COG through the API proxy (token in header) as an ArrayBuffer,
// parses it with georaster (geotiff.js), and adds a GeoRasterLayer — which
// reprojects from the file's CRS (OPERA UTM) to web-mercator and lets us color
// pixels by value with a viridis ramp scaled to the run's display range.
import { useEffect } from 'react'
import { useMap } from 'react-leaflet'

import { fetchArtifactArrayBuffer } from '../../subsideApi'

// georaster + geotiff.js are heavy (~2 MB), so load them on first COG view only.
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

export function CogLayer({ token, runId, path, range, opacity = 0.8, onBounds, onError, onRange }) {
  const map = useMap()

  useEffect(() => {
    if (!token || !runId || !path) return undefined
    let layer
    let cancelled = false
    Promise.all([fetchArtifactArrayBuffer(token, runId, path), loadGeoraster()])
      .then(([buf, [parseGeoraster, GeoRasterLayer]]) => parseGeoraster(buf).then((g) => [g, GeoRasterLayer]))
      .then(([georaster, GeoRasterLayer]) => {
        if (cancelled) return
        // Diagnostic: projection is the usual culprit when a COG renders blank.
        console.log('[COG]', {
          projection: georaster.projection, width: georaster.width, height: georaster.height,
          mins: georaster.mins, maxs: georaster.maxs, noData: georaster.noDataValue,
          bands: georaster.numberOfRasters, pixelWidth: georaster.pixelWidth,
        })
        const min = range?.vmin ?? georaster.mins?.[0] ?? 0
        const max = range?.vmax ?? georaster.maxs?.[0] ?? 1
        const span = max - min || 1
        onRange?.({ min, max })
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
        try {
          const b = layer.getBounds()
          map.fitBounds(b)
          onBounds?.(b)
        } catch { /* ignore */ }
      })
      .catch((err) => { if (!cancelled) onError?.(err?.message || 'COG failed to load') })

    return () => {
      cancelled = true
      if (layer) map.removeLayer(layer)
    }
  }, [map, token, runId, path]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}
