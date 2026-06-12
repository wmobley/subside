// Previous runs (public STAC catalog), grouped by workflow into two map layers:
//   Displacement       -> H2I runs (displacement snapshot)
//   Subsidence Velocity -> WERC runs (velocity)
// The two toggles live in the Layers panel (StacResults portals them into the
// mount point SubsideLayers provides) and render every public run of that type
// in view. Renders nothing when VITE_STAC_API_BASE is unset.
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ImageOverlay, Popup, useMap, useMapEvents } from 'react-leaflet'

import { itemLayers, itemMeta, overlayHref, searchItems, stacEnabled } from '../../lib/stacApi'
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

function runLayer(item, kind) {
  const layers = itemLayers(item)
  if (kind === 'velocity') {
    return layers.find((l) => l.key === 'velocity') || layers.find((l) => l.type === 'cog')
  }
  return layers.find((l) => l.key === 'cog') || layers.find((l) => l.type === 'cog')
}

function combinedRange(items, kind) {
  const ranges = items
    .map((item) => runLayer(item, kind))
    .filter((layer) => layer?.range)
  if (!ranges.length) return null
  const mins = ranges.map((layer) => Number(layer.range.min ?? layer.range.vmin)).filter(Number.isFinite)
  const maxs = ranges.map((layer) => Number(layer.range.max ?? layer.range.vmax)).filter(Number.isFinite)
  if (!mins.length || !maxs.length) return null
  return {
    min: Math.min(...mins),
    max: Math.max(...maxs),
    unit: ranges.find((layer) => layer.unit)?.unit || '',
  }
}

function legendValue(value) {
  if (!Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 100) return value.toFixed(0)
  if (abs >= 10) return value.toFixed(1)
  return value.toPrecision(3)
}

function formatBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null
  const values = bbox.map(Number)
  if (values.some((v) => !Number.isFinite(v))) return null
  return values.map((v) => v.toFixed(5)).join(', ')
}

function RasterLegend({ range, fallbackUnit }) {
  return (
    <div className="slp-raster-legend">
      <div className="slp-raster-legend-bar" />
      <div className="slp-raster-legend-labels">
        <span>{range ? legendValue(range.min) : 'low'}</span>
        <span>{range?.unit || fallbackUnit || ''}</span>
        <span>{range ? legendValue(range.max) : 'high'}</span>
      </div>
    </div>
  )
}

function observedRisk(range) {
  if (!range) return null
  const lo = Number(range.min ?? range.vmin)
  const hi = Number(range.max ?? range.vmax)
  const subsiding = Math.max(0, -Math.min(lo, hi))
  if (Number.isNaN(subsiding)) return null
  if (subsiding < 5) return { rate: subsiding, label: 'Low', color: '#16a34a' }
  if (subsiding < 15) return { rate: subsiding, label: 'Moderate', color: '#f59e0b' }
  if (subsiding < 30) return { rate: subsiding, label: 'High', color: '#ea580c' }
  return { rate: subsiding, label: 'Severe', color: '#dc2626' }
}

function RunDetailsPopup({ selection, onUseBbox }) {
  if (!selection) return null
  const { item, kind } = selection
  const meta = itemMeta(item)
  const layer = runLayer(item, kind)
  const risk = observedRisk(layer?.range)
  const isVelocity = kind === 'velocity'
  const bboxText = formatBbox(item.bbox)
  const handleUseBbox = () => {
    if (!bboxText) return
    onUseBbox?.({
      id: `${item.id || 'stac-item'}-${Date.now()}`,
      bbox: item.bbox,
      start: meta.start ? meta.start.slice(0, 10) : null,
      end: meta.end ? meta.end.slice(0, 10) : null,
      itemId: item.id,
    })
    selection.onClose?.()
  }
  return (
    <Popup position={selection.latlng} eventHandlers={{ remove: () => selection.onClose?.() }}>
      <div className="stac-run-popup">
        <div className="stac-run-popup-title">{isVelocity ? 'Subsidence Velocity' : 'Displacement'}</div>
        <div className="stac-run-popup-section">
          <div className="stac-run-popup-label">Observed</div>
          {isVelocity ? (
            risk ? (
              <>
                <div className="stac-run-popup-value" style={{ color: risk.color }}>{risk.label}</div>
                <div className="stac-run-popup-muted">up to {risk.rate.toFixed(0)} mm/yr</div>
              </>
            ) : (
              <div className="stac-run-popup-muted">Velocity layer</div>
            )
          ) : (
            <div className="stac-run-popup-muted">Displacement snapshot only</div>
          )}
        </div>
        <dl className="stac-run-popup-meta">
          {meta.start ? (
            <div>
              <dt>Acquisition window</dt>
              <dd>{meta.start.slice(0, 10)} → {(meta.end || '').slice(0, 10) || '—'}</dd>
            </div>
          ) : null}
          {meta.productCount != null ? (
            <div>
              <dt>OPERA products</dt>
              <dd>{meta.productCount}</dd>
            </div>
          ) : null}
          {meta.frameIds?.length ? (
            <div>
              <dt>{meta.frameIds.length > 1 ? 'Frames' : 'Frame'}</dt>
              <dd>{meta.frameIds.join(', ')}</dd>
            </div>
          ) : null}
          {layer?.range ? (
            <div>
              <dt>Layer range</dt>
              <dd>{legendValue(Number(layer.range.min ?? layer.range.vmin))} → {legendValue(Number(layer.range.max ?? layer.range.vmax))} {layer.unit || ''}</dd>
            </div>
          ) : null}
          {bboxText ? (
            <div>
              <dt>Bounding box</dt>
              <dd>{bboxText}</dd>
            </div>
          ) : null}
        </dl>
        {bboxText && onUseBbox ? (
          <button type="button" className="stac-run-popup-action" onClick={handleUseBbox}>
            Use bbox for velocity follow-up
          </button>
        ) : null}
      </div>
    </Popup>
  )
}

export function StacResults({ panelHost, onUseBboxForAnalysis }) {
  const map = useMap()
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  const [selection, setSelection] = useState(null)
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
  const displacementLegend = combinedRange(dispRuns, 'displacement')
  const velocityLegend = combinedRange(velocityRuns, 'velocity')

  const selectRun = (item, kind, latlng) => {
    setSelection({ item, kind, latlng: latlng || map.getCenter(), onClose: () => setSelection(null) })
  }

  // The renderable layer for a run: displacement prefers the cheap overlay PNG,
  // else its COG; velocity is the velocity COG (cloud-optimized, streamed).
  const renderRun = (it, kind) => {
    if (kind === 'displacement') {
      if (overlayHref(it) && hasBbox(it)) {
        return (
          <ImageOverlay
            key={it.id}
            url={overlayHref(it)}
            bounds={bboxToBounds(it.bbox)}
            opacity={0.6}
            interactive
            eventHandlers={{ click: (event) => selectRun(it, kind, event.latlng) }}
          />
        )
      }
      const cog = itemLayers(it).find((l) => l.type === 'cog')
      return cog ? <StacCogLayer key={it.id} href={cog.href} range={cog.range} opacity={0.65} fit={false} onClick={(event) => selectRun(it, kind, event.latlng)} /> : null
    }
    const vel = itemLayers(it).find((l) => l.key === 'velocity') || itemLayers(it).find((l) => l.type === 'cog')
    return vel ? <StacCogLayer key={it.id} href={vel.href} range={vel.range} opacity={0.65} fit={false} onClick={(event) => selectRun(it, kind, event.latlng)} /> : null
  }

  // Two checkboxes styled like the registered-layer rows (checkbox · swatch ·
  // name · count), portalled into the Layers panel.
  const panelContent = (
    <>
      <div className="slp-section">Previous runs</div>
      <label className="slp-row">
        <input type="checkbox" checked={showDisplacement} onChange={(e) => { setShowDisplacement(e.target.checked); if (!e.target.checked && selection?.kind === 'displacement') setSelection(null) }} />
        <span className="slp-swatch" style={{ background: '#406d68' }} />
        <span className="slp-name">Displacement</span>
        <span className="slp-count">{dispRuns.length}</span>
      </label>
      {showDisplacement ? <RasterLegend range={displacementLegend} fallbackUnit="m" /> : null}
      <label className="slp-row">
        <input type="checkbox" checked={showVelocity} onChange={(e) => { setShowVelocity(e.target.checked); if (!e.target.checked && selection?.kind === 'velocity') setSelection(null) }} />
        <span className="slp-swatch" style={{ background: '#7c3aed' }} />
        <span className="slp-name">Subsidence Velocity</span>
        <span className="slp-count">{velocityRuns.length}</span>
      </label>
      {showVelocity ? <RasterLegend range={velocityLegend} fallbackUnit="mm/yr" /> : null}
      {error ? <div className="slp-error">{error}</div> : null}
    </>
  )

  return (
    <>
      {showDisplacement && dispRuns.slice(0, MAX_RUNS).map((it) => renderRun(it, 'displacement'))}
      {showVelocity && velocityRuns.slice(0, MAX_RUNS).map((it) => renderRun(it, 'velocity'))}
      <RunDetailsPopup selection={selection} onUseBbox={onUseBboxForAnalysis} />
      {panelHost ? createPortal(panelContent, panelHost) : null}
    </>
  )
}
