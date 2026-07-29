// Renders a STAC Item's COG asset (a public CKAN URL) as a raster on the map.
//
// This is the single COG renderer for the app: both the STAC discovery panel
// (StacResults) and a finished run's results (SubsideAnalysis) point it at a
// public STAC asset href (the CKAN resource download URL must allow CORS + range
// requests). Parses the GeoTIFF client-side and colors it with a ramp (default
// viridis; see `palette` prop) scaled to the asset's display range.
import { useEffect, useRef } from 'react'
import { useMap } from 'react-leaflet'

import { paletteFor, rampColor } from '../../lib/colorRamps'
import { withLoadSlot } from '../../lib/loadQueue'
import { sampleGeorasterValue } from '../../lib/pixelSample'

const loadGeoraster = () => Promise.all([
  import('georaster').then((m) => m.default),
  import('georaster-layer-for-leaflet').then((m) => m.default),
])

// Direct DOM evidence for the bug-010 stale-tile investigation: rather than
// asking someone to manually open the Elements panel, tag each layer's own
// container with the href it's rendering and log every `.leaflet-layer`
// container actually present in the page at the moments that matter. If a
// removed layer's container is still counted here after its "removing" log,
// that's the stale-tile bug caught in the act, not just theorized.
function logDomState(label) {
  const containers = [...document.querySelectorAll('.leaflet-layer')]
  console.log(`[StacCogLayer] DOM state (${label})`, {
    totalLeafletLayers: containers.length,
    tagged: containers.map((el) => el.getAttribute('data-stac-href') || '(untagged)'),
  })
}

export function StacCogLayer({ href, range, opacity = 0.8, fit = true, palette = 'viridis', onError, onReady }) {
  const map = useMap()
  const onErrorRef = useRef(onError)
  const onReadyRef = useRef(onReady)
  const layerRef = useRef(null)
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
    let retriesLeft = 5
    // Opening the COG (header read via geotiff.fromUrl) goes through a shared
    // concurrency gate (see lib/loadQueue.js): with up to ~24 runs per kind,
    // firing every layer's initial open at once floods the browser's ~6
    // connections-per-origin limit on CKAN's HTTP/1.1 and starves them all,
    // instead of each streaming cleanly via range requests as a COG should.
    // NB: this only covers the open step, not ongoing per-tile reads —
    // georaster-stack reads tile data via its own pool of Web Workers
    // (3 per layer), each with an isolated fetch() invisible to any
    // main-thread interception, so per-tile congestion on zoom/pan (a real,
    // separate, currently-unmitigated risk) can't be gated the same way.
    withLoadSlot(
      () => loadGeoraster()
        // Pass the URL (not an ArrayBuffer): georaster opens the COG with
        // geotiff.fromUrl, probes for an `.ovr` overview, parses only the header,
        // and reads tiles via HTTP range requests on demand (GeoRasterLayer calls
        // the lazy `getValues` per tile). So we stream the overview/tiles for the
        // current view instead of downloading the whole file — the point of a COG.
        .then(([parseGeoraster, GeoRasterLayer]) => parseGeoraster(href).then((g) => [g, GeoRasterLayer])),
      () => cancelled,
    )
      .then(([georaster, GeoRasterLayer]) => {
        if (cancelled) return
        const min = range?.vmin ?? georaster.mins?.[0] ?? 0
        const max = range?.vmax ?? georaster.maxs?.[0] ?? 1
        const span = max - min || 1
        const noData = georaster.noDataValue
        const ramp = paletteFor(palette)
        console.log('[StacCogLayer] rendering', { href, palette, min, max, noData, projection: georaster.projection })
        layer = new GeoRasterLayer({
          georaster,
          opacity,
          resolution: 256,
          // Without this, georaster-stack defaults to nearest-neighbor
          // ("near-vectorize") per-tile, which keeps nodata gaps hard-edged
          // and blocky at zoom instead of smooth like the server-built
          // (cubic-resampled) overview pyramid.
          resampleMethod: 'bilinear',
          pixelValuesToColorFn: (values) => {
            const v = values[0]
            if (v == null || Number.isNaN(v) || v === noData) return null
            return rampColor(ramp, (v - min) / span)
          },
        })
        // georaster-layer-for-leaflet@4.1.2 is a plain L.GridLayer with no
        // click/interactive-target support of its own — a `layer.on('click', ...)`
        // here would never fire. Real click/contextmenu handling lives at the
        // map level instead (StacResults.jsx), using `onReady`'s sampler below
        // to test the actual clicked point against this layer's bounds/pixels.
        // Individual tiles can fail on transient range-request errors against
        // the remote COG (e.g. connection-limit congestion — see loadQueue.js).
        // Leaflet leaves those tiles blank with no retry of its own, so
        // debounce a bounded redraw to recover them once the burst subsides.
        // Backs off (1s, 2s, 3s, ...) rather than a fixed 1s each time, since
        // the congestion this is recovering from can take a few seconds to clear.
        layer.on('tileerror', () => {
          if (cancelled || retriesLeft <= 0 || retryTimeout) return
          const attempt = 6 - retriesLeft // 1st attempt = 1, ...
          retryTimeout = setTimeout(() => {
            retryTimeout = null
            retriesLeft -= 1
            if (!cancelled) layer.redraw()
          }, attempt * 1000)
        })
        layer.addTo(map)
        layerRef.current = layer
        try { layer.getContainer?.()?.setAttribute('data-stac-href', href) } catch { /* ignore */ }
        logDomState(`after adding ${href}`)
        if (fit) {
          try { map.fitBounds(layer.getBounds()) } catch { /* ignore */ }
        }
        // Exposes this layer's bounds + a point sampler so StacResults can
        // test a real map click, a right-click, or an address-search result
        // against it — see the note above on why that can't happen here.
        onReadyRef.current?.({
          bounds: layer.getBounds(),
          sampleAt: (lat, lon) => sampleGeorasterValue(georaster, lat, lon),
        })
      })
      .catch((err) => { if (!cancelled) onErrorRef.current?.(err?.message || 'COG failed to load') })

    return () => {
      cancelled = true
      if (retryTimeout) clearTimeout(retryTimeout)
      if (layer) {
        console.log('[StacCogLayer] removing', { href, palette })
        logDomState(`before removing ${href}`)
        // georaster-layer-for-leaflet@4.1.2 doesn't override onRemove (only
        // onAdd), so it relies entirely on Leaflet's stock GridLayer cleanup.
        // User-reported (confirmed by toggling between a displacement and a
        // velocity run in production): the previous layer's tiles can remain
        // visible after map.removeLayer(), until a full page reload. Could
        // NOT reproduce this in an isolated local test (incl. simulated
        // network latency) despite trying, so this hardening is defensive,
        // not a confirmed fix -- forcibly detach the layer's own container
        // first as a backstop that doesn't depend on understanding whatever
        // the library's internal tile-cache/redraw race actually is.
        try { layer.getContainer?.()?.remove() } catch { /* ignore */ }
        logDomState(`after container.remove() for ${href}`)
        map.removeLayer(layer)
        logDomState(`after map.removeLayer() for ${href}`)
      }
      layerRef.current = null
      onReadyRef.current?.(null)
    }
  }, [map, href]) // eslint-disable-line react-hooks/exhaustive-deps

  return null
}
