// Generic renderer for a STAC-registered context layer. One component, four
// service kinds — each maps to a Leaflet primitive the app already relies on:
//
//   wms     -> <WMSTileLayer>           (server renders pre-styled tiles)
//   xyz     -> <TileLayer>              (remote raster XYZ tiles)
//   mvt     -> <VectorTileLayer>        (vector tiles; we apply the style hint)
//   geojson -> <ReferenceGeoJSON>       (remote GeoJSON; aquifer-style coloring)
//
// The layer config shape is produced by lib/stacContext.js. Adding a new context
// layer is a STAC Item registration — no change here.
import { useEffect, useRef, useState } from 'react'
import { GeoJSON, TileLayer, WMSTileLayer } from 'react-leaflet'

import { ReferenceFeatureServer, ReferenceGeoJSON } from './ReferenceLayers'
import { VectorTileLayer } from './VectorTileLayer'

// Turn a layer's style hint ({color, fillColor, fillOpacity, weight, radius,
// geomType}) into a VectorGrid style function, picking sensible per-geometry
// defaults — mirrors SubsideLayers' built-in MVT styling.
//
// `opacityRef` is read live on every tile draw (not captured at creation time):
// Leaflet.VectorGrid has no layer-level setOpacity, so the transparency slider
// works by mutating this ref and bumping `styleVersion` (see below) to force a
// redraw — the frozen style function then picks up the new value.
function vectorGridStyle(style, fallbackColor, opacityRef) {
  const s = style || {}
  const color = s.color || fallbackColor
  const geom = s.geomType || ''
  if (/line/i.test(geom)) {
    return () => ({ weight: s.weight ?? 2, color, opacity: opacityRef.current })
  }
  if (/point/i.test(geom)) {
    return () => ({
      radius: s.radius ?? 4, color, fill: true, fillColor: s.fillColor || color,
      opacity: opacityRef.current, fillOpacity: (s.fillOpacity ?? 0.8) * opacityRef.current,
    })
  }
  return () => ({
    weight: s.weight ?? 1, color, fill: true, fillColor: s.fillColor || color,
    opacity: opacityRef.current, fillOpacity: (s.fillOpacity ?? 0.15) * opacityRef.current,
  })
}

// Plain remote GeoJSON (no aquifer name-scale): single-color, from the style hint.
function PlainGeoJSON({ url, style, color, opacity, onError }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let cancelled = false
    fetch(url)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((gj) => { if (!cancelled) setData(gj) })
      .catch((e) => { if (!cancelled) onError?.(e.message) })
    return () => { cancelled = true }
  }, [url, onError])
  if (!data) return null
  const c = style?.color || color
  return (
    <GeoJSON
      data={data}
      style={() => ({
        color: c,
        weight: style?.weight ?? 1,
        fill: true,
        fillColor: style?.fillColor || c,
        fillOpacity: style?.fillOpacity ?? opacity ?? 0.35,
      })}
    />
  )
}

export function ContextLayer({ layer, onError, onFeatureClick, onPickReference }) {
  const { service, href } = layer
  const opacity = layer.opacity ?? 1

  // Stable across renders (unlike the style function itself, which VectorGrid
  // freezes at layer-creation time) — see vectorGridStyle's comment above.
  const mvtOpacityRef = useRef(opacity)
  mvtOpacityRef.current = opacity

  if (service === 'wms') {
    return (
      <WMSTileLayer
        url={href}
        layers={(layer.wmsLayers || []).join(',')}
        format={layer.format || 'image/png'}
        transparent={layer.wmsTransparent ?? true}
        styles={(layer.wmsStyles || []).join(',')}
        opacity={opacity}
        attribution={layer.attribution || undefined}
      />
    )
  }

  if (service === 'xyz') {
    return (
      <TileLayer
        url={href}
        opacity={opacity}
        maxNativeZoom={layer.maxZoom || undefined}
        attribution={layer.attribution || undefined}
      />
    )
  }

  if (service === 'mvt') {
    const keys = layer.sourceLayers && layer.sourceLayers.length ? layer.sourceLayers : [layer.id]
    const styleFn = vectorGridStyle(layer.style, layer.color, mvtOpacityRef)
    const vectorTileLayerStyles = Object.fromEntries(keys.map((k) => [k, styleFn]))
    return (
      <VectorTileLayer
        url={href}
        vectorTileLayerStyles={vectorTileLayerStyles}
        onFeatureClick={onFeatureClick}
        maxNativeZoom={layer.maxZoom || 14}
        styleVersion={opacity}
      />
    )
  }

  // feature-server: an Esri FeatureServer layer loaded viewport-by-viewport
  // (handles layers larger than the server's maxRecordCount; gated by minZoom).
  if (service === 'feature-server') {
    return (
      <ReferenceFeatureServer
        url={href}
        label={layer.label}
        style={layer.style}
        color={layer.color}
        opacity={layer.opacity}
        minZoom={layer.minZoom}
        queryFields={layer.queryFields}
        where={layer.where}
        onError={onError}
        onPickReference={onPickReference}
      />
    )
  }

  // geojson: aquifer-style multi-color rendering when a `kind` is present
  // (preserves the prior look); otherwise a plain single-color GeoJSON.
  if (layer.kind) {
    return <ReferenceGeoJSON url={href} kind={layer.kind} opacity={opacity} onError={onError} />
  }
  return (
    <PlainGeoJSON url={href} style={layer.style} color={layer.color} opacity={layer.opacity} onError={onError} />
  )
}
