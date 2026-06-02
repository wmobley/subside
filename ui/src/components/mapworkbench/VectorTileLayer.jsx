// react-leaflet wrapper around Leaflet.VectorGrid's protobuf (MVT) layer.
//
// react-leaflet has no built-in vector-tile layer, so we adapt L.vectorGrid.protobuf
// via @react-leaflet/core. The component forwards its ref to the underlying Leaflet
// instance, so callers can attach click handlers or call redraw() on it.
//
// Pass a `styleVersion` number that you bump whenever the data behind a dynamic
// `vectorTileLayerStyles` function changes (e.g. availability) — the update hook
// calls redraw() so styles re-evaluate without recreating the layer.
import L from 'leaflet'
import 'leaflet.vectorgrid'
import { createLayerComponent } from '@react-leaflet/core'

// leaflet.vectorgrid 1.3 calls L.DomEvent.fakeStop in its click handler — a
// pre-1.x Leaflet API removed in 1.x. Without it, every feature click throws
// "fakeStop is not a function" *before* the click reaches our handler. Shim it
// (stop() is the closest modern equivalent) so feature clicks fire.
if (typeof L.DomEvent.fakeStop !== 'function') {
  L.DomEvent.fakeStop = (e) => L.DomEvent.stop(e)
}

function createVectorTileLayer(props, context) {
  const { url, styleVersion, onFeatureClick, ...options } = props
  const instance = L.vectorGrid.protobuf(url, {
    rendererFactory: L.canvas.tile, // canvas: fast for vertex-dense polygons
    interactive: true,
    ...options,
  })
  // Bind once with a stable handler; the handler should read live data via refs.
  if (onFeatureClick) instance.on('click', onFeatureClick)
  return { instance, context: { ...context } }
}

function updateVectorTileLayer(instance, props, prevProps) {
  if (props.url !== prevProps.url) {
    // URL changed — safest to let React remount; nothing to do incrementally.
    return
  }
  if (props.styleVersion !== prevProps.styleVersion) {
    instance.redraw()
  }
}

export const VectorTileLayer = createLayerComponent(createVectorTileLayer, updateVectorTileLayer)
