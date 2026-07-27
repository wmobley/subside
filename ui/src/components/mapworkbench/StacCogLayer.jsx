// Renders a STAC Item's COG asset (a public CKAN URL) as a raster on the map.
//
// This is the single COG renderer for the app: both the STAC discovery panel
// (StacResults) and a finished run's results (SubsideAnalysis) point it at a
// public STAC asset href (the CKAN resource download URL must allow CORS + range
// requests). Parses the GeoTIFF client-side and colors it with a viridis ramp
// scaled to the asset's display range.
import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'

import { sampleGeorasterValue } from '../../lib/pixelSample'

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

export function StacCogLayer({ href, range, opacity = 0.8, fit = true, onClick, onContextMenu, onError, onReady }) {
  const map = useMap()
  const onClickRef = useRef(onClick)
  const onContextMenuRef = useRef(onContextMenu)
  const onErrorRef = useRef(onError)
  const onReadyRef = useRef(onReady)
  const layerRef = useRef(null)
  onClickRef.current = onClick
  onContextMenuRef.current = onContextMenu
  onErrorRef.current = onError
  onReadyRef.current = onReady

  // The GeoRasterLayer is imperative and only built once per `href` (below); a
  // later opacity change (e.g. the transparency slider) needs to reach the
  // already-created layer directly rather than waiting for a rebuild.
  useEffect(() => {
    layerRef.current?.setOpacity(opacity)
  }, [opacity])

  useEffect(() => {
    if (!href) return undefined
    let layer
    let cancelled = false
    let retryTimeout = null
    let retriesLeft = 3
    loadGeoraster()
      // Pass the URL (not an ArrayBuffer): georaster opens the COG with
      // geotiff.fromUrl, probes for an `.ovr` overview, parses only the header,
      // and reads tiles via HTTP range requests on demand (GeoRasterLayer calls
      // the lazy `getValues` per tile). So we stream the overview/tiles for the
      // current view instead of downloading the whole file — the point of a COG.
      .then(([parseGeoraster, GeoRasterLayer]) => parseGeoraster(href).then((g) => [g, GeoRasterLayer]))
      .then(([georaster, GeoRasterLayer]) => {
        if (cancelled) return
        const min = range?.vmin ?? georaster.mins?.[0] ?? 0
        const max = range?.vmax ?? georaster.maxs?.[0] ?? 1
        const span = max - min || 1
        const noData = georaster.noDataValue
        layer = new GeoRasterLayer({
          georaster,
          opacity,
          interactive: Boolean(onClickRef.current || onContextMenuRef.current),
          resolution: 256,
          pixelValuesToColorFn: (values) => {
            const v = values[0]
            if (v == null || Number.isNaN(v) || v === noData) return null
            return viridis((v - min) / span)
          },
        })
        if (onClickRef.current) {
          layer.on('click', (event) => {
            sampleGeorasterValue(georaster, event.latlng.lat, event.latlng.lng)
              .catch(() => null)
              .then((value) => onClickRef.current?.(event, value))
          })
        }
        if (onContextMenuRef.current) {
          layer.on('contextmenu', (event) => {
            event.originalEvent?.preventDefault?.()
            onContextMenuRef.current?.(event)
          })
        }
        // Individual tiles can fail on transient range-request errors against
        // the remote COG (e.g. a burst of concurrent tile fetches). Leaflet
        // leaves those tiles blank with no retry of its own, so debounce a
        // bounded redraw to recover them once the burst subsides.
        layer.on('tileerror', () => {
          if (cancelled || retriesLeft <= 0 || retryTimeout) return
          retryTimeout = setTimeout(() => {
            retryTimeout = null
            retriesLeft -= 1
            if (!cancelled) layer.redraw()
          }, 1000)
        })
        layer.addTo(map)
        layerRef.current = layer
        if (fit) {
          try { map.fitBounds(layer.getBounds()) } catch { /* ignore */ }
        }
        // Lets a consumer probe an arbitrary lat/lon on demand (e.g. the
        // address-search flow), not just react to a Leaflet click.
        onReadyRef.current?.({
          bounds: layer.getBounds(),
          sampleAt: (lat, lon) => sampleGeorasterValue(georaster, lat, lon),
        })
      })
      .catch((err) => { if (!cancelled) onErrorRef.current?.(err?.message || 'COG failed to load') })

    return () => {
      cancelled = true
      if (retryTimeout) clearTimeout(retryTimeout)
      if (layer) map.removeLayer(layer)
      layerRef.current = null
      onReadyRef.current?.(null)
    }
  }, [map, href]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}
