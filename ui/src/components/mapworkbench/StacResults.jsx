// Previous runs (public STAC catalog), grouped by workflow into two map layers:
//   Displacement       -> H2I runs (displacement snapshot)
//   Subsidence Velocity -> WERC runs (velocity)
// The two toggles live in the Layers panel (StacResults portals them into the
// mount point SubsideLayers provides) and render every public run of that type
// in view. Renders nothing when VITE_STAC_API_BASE is unset.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ImageOverlay, useMap, useMapEvents } from 'react-leaflet'

import { itemLayers, overlayHref, searchItems, stacEnabled } from '../../stacApi'
import { StacCogLayer } from './StacCogLayer'

// Cap rendered runs per category per viewport so a dense area can't fire an
// unbounded number of raster loads. searchItems already caps the query at 50.
const MAX_RUNS = 24

function bboxToBounds(b) {
  return [[b[1], b[0]], [b[3], b[2]]] // [[s,w],[n,e]] for Leaflet
}

function hasBbox(item) {
  return Array.isArray(item.bbox) && item.bbox.length === 4
}

// WERC (velocity) runs carry a `velocity` COG asset; the id is also prefixed
// `subside-werc-`. Everything else is an H2I displacement run.
function isVelocityRun(item) {
  return /werc/i.test(item.id || '') || itemLayers(item).some((l) => l.key === 'velocity')
}

export function StacResults({ panelHost }) {
  const map = useMap()
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  // Off by default so the map stays clean; the counts show what's available.
  const [showDisplacement, setShowDisplacement] = useState(false)
  const [showVelocity, setShowVelocity] = useState(false)

  const refresh = () => {
    if (!stacEnabled() || !map) return
    searchItems(map.getBounds())
      .then((features) => { setItems(features); setError(null) })
      .catch((err) => setError(err?.message || 'STAC search failed'))
  }

  // Re-search on pan/zoom end.
  useMapEvents({ moveend: refresh, zoomend: refresh })
  useEffect(refresh, [map])

  if (!stacEnabled()) return null

  const velocityRuns = items.filter(isVelocityRun)
  const dispRuns = items.filter((it) => !isVelocityRun(it))

  // The renderable layer for a run: displacement prefers the cheap overlay PNG,
  // else its COG; velocity is the velocity COG (cloud-optimized, streamed).
  const renderRun = (it, kind) => {
    if (kind === 'displacement') {
      if (overlayHref(it) && hasBbox(it)) {
        return <ImageOverlay key={it.id} url={overlayHref(it)} bounds={bboxToBounds(it.bbox)} opacity={0.6} interactive={false} />
      }
      const cog = itemLayers(it).find((l) => l.type === 'cog')
      return cog ? <StacCogLayer key={it.id} href={cog.href} range={cog.range} opacity={0.65} fit={false} /> : null
    }
    const vel = itemLayers(it).find((l) => l.key === 'velocity') || itemLayers(it).find((l) => l.type === 'cog')
    return vel ? <StacCogLayer key={it.id} href={vel.href} range={vel.range} opacity={0.65} fit={false} /> : null
  }

  // Two checkboxes styled like the registered-layer rows (checkbox · swatch ·
  // name · count), portalled into the Layers panel.
  const panelContent = (
    <>
      <div className="slp-section">Previous runs</div>
      <label className="slp-row">
        <input type="checkbox" checked={showDisplacement} onChange={(e) => setShowDisplacement(e.target.checked)} />
        <span className="slp-swatch" style={{ background: '#00a9b7' }} />
        <span className="slp-name">Displacement</span>
        <span className="slp-count">{dispRuns.length}</span>
      </label>
      <label className="slp-row">
        <input type="checkbox" checked={showVelocity} onChange={(e) => setShowVelocity(e.target.checked)} />
        <span className="slp-swatch" style={{ background: '#7c3aed' }} />
        <span className="slp-name">Subsidence Velocity</span>
        <span className="slp-count">{velocityRuns.length}</span>
      </label>
      {error ? <div className="slp-error">{error}</div> : null}
    </>
  )

  return (
    <>
      {showDisplacement && dispRuns.slice(0, MAX_RUNS).map((it) => renderRun(it, 'displacement'))}
      {showVelocity && velocityRuns.slice(0, MAX_RUNS).map((it) => renderRun(it, 'velocity'))}
      {panelHost ? createPortal(panelContent, panelHost) : null}
    </>
  )
}
