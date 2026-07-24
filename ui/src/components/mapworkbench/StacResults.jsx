// Previous runs (public STAC catalog), grouped by workflow into two map layers:
//   Displacement       -> H2I runs (displacement snapshot)
//   Subsidence Velocity -> WERC runs (velocity)
// The two toggles live in the Layers panel (StacResults portals them into the
// mount point SubsideLayers provides) and render every public run of that type
// in view. Renders nothing when VITE_STAC_API_BASE is unset.
import { Fragment, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { CircleMarker, ImageOverlay, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'

import { itemLayers, itemMeta, overlayHref, searchItems, stacEnabled } from '../../lib/stacApi'
import { RunActionsMenu } from './RunActionsMenu'
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

// Identify one run in the per-run toggle list: its date window, plus the
// reference mode for velocity runs (so overlapping runs are distinguishable).
function runRowLabel(item, kind) {
  const m = itemMeta(item)
  const win = m.start ? `${m.start.slice(0, 10)} → ${(m.end || '').slice(0, 10) || '—'}` : (item.id || 'run')
  const ref = kind === 'velocity' && m.reference?.mode ? ` · ref ${m.reference.mode}` : ''
  return win + ref
}

// LOS convention shared by both product types: negative = moving away from the
// satellite (subsidence/sinking); positive = moving toward it (uplift). See
// SubsideAnalysis.jsx's layerContext() for the same wording in the run-detail view.
function RasterLegend({ range, fallbackUnit }) {
  return (
    <div className="slp-raster-legend">
      <div className="slp-raster-legend-bar" />
      <div className="slp-raster-legend-labels">
        <span>{range ? legendValue(range.min) : 'low'}</span>
        <span>{range?.unit || fallbackUnit || ''}</span>
        <span>{range ? legendValue(range.max) : 'high'}</span>
      </div>
      <div className="slp-raster-legend-sign">Negative = subsidence (sinking) · Positive = uplift</div>
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
          {meta.reference ? (
            <div>
              <dt>Static reference{meta.reference.mode ? ` (${meta.reference.mode})` : ''}</dt>
              <dd>{meta.reference.lat.toFixed(5)}, {meta.reference.lon.toFixed(5)}</dd>
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
  // The open "..." actions menu (Download / Zoom In) for one run, if any --
  // shared between the Layers panel's kebab button and a right-click on the
  // rendered layer, so both trigger the identical menu/behavior.
  const [actionsMenu, setActionsMenu] = useState(null)
  // Off by default so the map stays clean; the counts show what's available.
  const [showDisplacement, setShowDisplacement] = useState(false)
  const [showVelocity, setShowVelocity] = useState(false)
  // Per-group transparency, applied to every run rendered under that group (the
  // group is the "layer" as far as the Layers panel is concerned; individual
  // runs within it don't get their own override). Defaults match the previous
  // hardcoded per-kind opacity.
  const [displacementOpacity, setDisplacementOpacity] = useState(0.6)
  const [velocityOpacity, setVelocityOpacity] = useState(0.65)
  // The open "..." actions menu for a group toggle row (Transparency only),
  // separate from `actionsMenu` (per-run Download/Zoom In/Transparency) below.
  const [groupActionsMenu, setGroupActionsMenu] = useState(null)
  // Per-run visibility: a group's master toggle reveals individual run rows, all
  // ON by default (so "see overlap" still works); this set holds the runs the user
  // has explicitly hidden. Tracking the *hidden* set (not the shown set) means runs
  // panning into view stay visible without re-checking them.
  const [hiddenIds, setHiddenIds] = useState(() => new Set())

  const toggleRun = (id) => {
    setHiddenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else {
        next.add(id)
        setSelection((sel) => (sel?.item?.id === id ? null : sel))  // drop popup for a hidden run
      }
      return next
    })
  }

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

  // Opens the shared "..." actions menu at a screen point (viewport px), from
  // either the kebab button's own bounding rect or a right-click's clientX/Y.
  const openActionsMenu = (item, kind, point) => {
    setActionsMenu({ item, kind, top: point.y, left: point.x })
  }
  const closeActionsMenu = () => setActionsMenu(null)

  const openActionsMenuFromClick = (event, item, kind) => {
    event.preventDefault()
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    openActionsMenu(item, kind, { x: rect.left, y: rect.bottom + 4 })
  }

  const openActionsMenuFromContextMenu = (event, item, kind) => {
    event.originalEvent?.preventDefault?.()
    const native = event.originalEvent
    openActionsMenu(item, kind, { x: native?.clientX ?? 0, y: native?.clientY ?? 0 })
  }

  const openGroupActionsMenu = (event, kind) => {
    event.preventDefault()
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    setGroupActionsMenu({ kind, top: rect.bottom + 4, left: rect.left })
  }

  const zoomToRun = (item) => {
    if (!hasBbox(item)) return
    map.fitBounds(bboxToBounds(item.bbox))
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
            opacity={displacementOpacity}
            interactive
            eventHandlers={{
              click: (event) => selectRun(it, kind, event.latlng),
              contextmenu: (event) => openActionsMenuFromContextMenu(event, it, kind),
            }}
          />
        )
      }
      const cog = itemLayers(it).find((l) => l.type === 'cog')
      return cog ? (
        <StacCogLayer
          key={it.id}
          href={cog.href}
          range={cog.range}
          opacity={displacementOpacity}
          fit={false}
          onClick={(event) => selectRun(it, kind, event.latlng)}
          onContextMenu={(event) => openActionsMenuFromContextMenu(event, it, kind)}
        />
      ) : null
    }
    const vel = itemLayers(it).find((l) => l.key === 'velocity') || itemLayers(it).find((l) => l.type === 'cog')
    if (!vel) return null
    const ref = itemMeta(it).reference
    return (
      <Fragment key={it.id}>
        <StacCogLayer
          href={vel.href}
          range={vel.range}
          opacity={velocityOpacity}
          fit={false}
          onClick={(event) => selectRun(it, kind, event.latlng)}
          onContextMenu={(event) => openActionsMenuFromContextMenu(event, it, kind)}
        />
        {ref ? (
          <CircleMarker
            center={[ref.lat, ref.lon]}
            radius={6}
            pathOptions={{ color: '#111', weight: 2, fillColor: '#fde725', fillOpacity: 1 }}
            eventHandlers={{
              click: (event) => selectRun(it, kind, event.latlng),
              contextmenu: (event) => openActionsMenuFromContextMenu(event, it, kind),
            }}
          >
            <Tooltip>
              Static reference{ref.mode ? ` (${ref.mode})` : ''}: {ref.lat.toFixed(5)}, {ref.lon.toFixed(5)}
            </Tooltip>
          </CircleMarker>
        ) : null}
      </Fragment>
    )
  }

  // Per-run rows shown under a group when its master toggle is on: one checkbox
  // per in-view run (hidden = in hiddenIds), so users can isolate/compare specific
  // overlapping footprints. Capped at MAX_RUNS to match what's rendered.
  const runRows = (runs, kind) => {
    const shown = runs.slice(0, MAX_RUNS)
    return (
      <div className="slp-run-list">
        {shown.map((it) => (
          <label key={it.id} className="slp-row slp-run-row">
            <input type="checkbox" checked={!hiddenIds.has(it.id)} onChange={() => toggleRun(it.id)} />
            <span className="slp-name">{runRowLabel(it, kind)}</span>
            <button
              type="button"
              className="slp-run-actions-btn"
              aria-label="Run actions"
              onClick={(event) => openActionsMenuFromClick(event, it, kind)}
            >
              ⋮
            </button>
          </label>
        ))}
        {runs.length > MAX_RUNS ? (
          <div className="slp-run-more">+{runs.length - MAX_RUNS} more in view — zoom in to narrow</div>
        ) : null}
        {!shown.length ? <div className="slp-run-more">No runs in this area.</div> : null}
      </div>
    )
  }

  // Master toggle per group (checkbox · swatch · name · count) + a legend and the
  // per-run rows when on. Portalled into the Layers panel.
  const panelContent = (
    <>
      <div className="slp-section">Previous runs</div>
      <label className="slp-row">
        <input type="checkbox" checked={showDisplacement} onChange={(e) => { setShowDisplacement(e.target.checked); if (!e.target.checked && selection?.kind === 'displacement') setSelection(null) }} />
        <span className="slp-swatch" style={{ background: '#406d68' }} />
        <span className="slp-name">Displacement</span>
        <span className="slp-count">{dispRuns.length}</span>
        <button
          type="button"
          className="slp-row-actions-btn"
          aria-label="Displacement layer actions"
          onClick={(event) => openGroupActionsMenu(event, 'displacement')}
        >
          ⋮
        </button>
      </label>
      {showDisplacement ? <RasterLegend range={displacementLegend} fallbackUnit="m" /> : null}
      {showDisplacement ? runRows(dispRuns, 'displacement') : null}
      <label className="slp-row">
        <input type="checkbox" checked={showVelocity} onChange={(e) => { setShowVelocity(e.target.checked); if (!e.target.checked && selection?.kind === 'velocity') setSelection(null) }} />
        <span className="slp-swatch" style={{ background: '#7c3aed' }} />
        <span className="slp-name">Subsidence Velocity</span>
        <span className="slp-count">{velocityRuns.length}</span>
        <button
          type="button"
          className="slp-row-actions-btn"
          aria-label="Subsidence Velocity layer actions"
          onClick={(event) => openGroupActionsMenu(event, 'velocity')}
        >
          ⋮
        </button>
      </label>
      {showVelocity ? <RasterLegend range={velocityLegend} fallbackUnit="mm/yr" /> : null}
      {showVelocity ? runRows(velocityRuns, 'velocity') : null}
      {error ? <div className="slp-error">{error}</div> : null}
    </>
  )

  return (
    <>
      {showDisplacement && dispRuns.slice(0, MAX_RUNS).filter((it) => !hiddenIds.has(it.id)).map((it) => renderRun(it, 'displacement'))}
      {showVelocity && velocityRuns.slice(0, MAX_RUNS).filter((it) => !hiddenIds.has(it.id)).map((it) => renderRun(it, 'velocity'))}
      <RunDetailsPopup selection={selection} onUseBbox={onUseBboxForAnalysis} />
      {actionsMenu ? (
        <RunActionsMenu
          top={actionsMenu.top}
          left={actionsMenu.left}
          downloadHref={runLayer(actionsMenu.item, actionsMenu.kind)?.href || null}
          downloadName={runLayer(actionsMenu.item, actionsMenu.kind)?.label || null}
          onZoomIn={hasBbox(actionsMenu.item) ? () => zoomToRun(actionsMenu.item) : null}
          onClose={closeActionsMenu}
        />
      ) : null}
      {groupActionsMenu ? (
        <RunActionsMenu
          top={groupActionsMenu.top}
          left={groupActionsMenu.left}
          showDownload={false}
          showZoomIn={false}
          opacity={groupActionsMenu.kind === 'displacement' ? displacementOpacity : velocityOpacity}
          onOpacityChange={groupActionsMenu.kind === 'displacement' ? setDisplacementOpacity : setVelocityOpacity}
          onClose={() => setGroupActionsMenu(null)}
        />
      ) : null}
      {panelHost ? createPortal(panelContent, panelHost) : null}
    </>
  )
}
