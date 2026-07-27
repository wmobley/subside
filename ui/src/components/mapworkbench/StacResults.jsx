// Previous runs (public STAC catalog), grouped by workflow into two map layers:
//   Displacement       -> H2I runs (displacement snapshot)
//   Subsidence Velocity -> WERC runs (velocity)
// The two toggles live in the Layers panel (StacResults portals them into the
// mount point SubsideLayers provides) and render every public run of that type
// in view. Renders nothing when VITE_STAC_API_BASE is unset.
import { Fragment, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CircleMarker, ImageOverlay, Popup, Tooltip, useMap, useMapEvents } from 'react-leaflet'

import { useAuth } from '../../lib/auth'
import { layerContext } from '../../lib/layerContext'
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

// Publisher item ids look like `subside-{pipeline}-{start}-{end}-{uuid}-{jobSuffix}`
// (e.g. `subside-werc-2025-06-01-2025-09-01-17482688-525b-4e67-8b0d-52d29964626c-007`).
// Pulls the same `<short-uuid>-<jobSuffix>` disambiguator CKAN already shows in its
// resource titles ("... - run 17482688-007"), so the two stay consistent.
const RUN_ID_RE = /^subside-[a-z0-9]+-\d{4}-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}-([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-(\d+)$/i
function runIdSuffix(item) {
  const m = RUN_ID_RE.exec(item.id || '')
  return m ? `${m[1]}-${m[2]}` : null
}

// Identify one run in the per-run toggle list: its location (if resolved at
// publish time) as the headline, its date window, and its frame(s)/run id (so
// runs sharing a date window — reprocessing passes, alternate framing — are
// still distinguishable), plus the reference mode for velocity runs. Split
// into three lines (rather than one long string) so the important part —
// where — isn't buried/truncated behind the least important part — the run id.
function runRowParts(item, kind) {
  const m = itemMeta(item)
  const dates = m.start ? `${m.start.slice(0, 10)} → ${(m.end || '').slice(0, 10) || '—'}` : null
  const title = m.location || dates || item.id || 'run'
  const frames = m.frameIds?.length
    ? `${m.frameIds.length > 1 ? 'Frames' : 'Frame'} ${m.frameIds.join(', ')}`
    : null
  const runId = runIdSuffix(item)
  const ref = kind === 'velocity' && m.reference?.mode ? `ref ${m.reference.mode}` : null
  return {
    title,
    // Only show a separate dates line when the title above is the location —
    // otherwise the dates would just repeat the title.
    dates: m.location && dates ? dates : null,
    meta: [frames, runId ? `run ${runId}` : null, ref].filter(Boolean).join(' · ') || null,
  }
}

function runRowTooltip(item, kind) {
  const { title, dates, meta } = runRowParts(item, kind)
  return [title, dates ? `Dates: ${dates}` : null, meta].filter(Boolean).join(' · ')
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

// Anonymous users get just the sampled value and a plain-language explanation
// of what that Displacement/Velocity rate means — not the full run metadata
// below (that's reserved for logged-in users, who have the full SubsideAnalysis
// workflow for deeper detail). Reuses the quantity/units/sign-convention copy
// shared with the analysis panel (see lib/layerContext.js).
function PixelValuePopup({ selection }) {
  const { item, kind, value, latlng, onClose } = selection
  const meta = itemMeta(item)
  const layer = runLayer(item, kind)
  const ctx = layerContext(layer, meta)
  const isVelocity = kind === 'velocity'
  return (
    <Popup position={latlng} eventHandlers={{ remove: () => onClose?.() }}>
      <div className="stac-run-popup">
        <div className="stac-run-popup-title">{isVelocity ? 'Subsidence Velocity' : 'Displacement'}</div>
        {value != null ? (
          <div className="stac-run-popup-value">{legendValue(value)} {ctx?.unit || layer?.unit || ''}</div>
        ) : (
          <div className="stac-run-popup-muted">Exact value unavailable for this preview layer.</div>
        )}
        {ctx ? (
          <div className="stac-run-popup-muted">
            {ctx.what} {ctx.sign}
          </div>
        ) : null}
      </div>
    </Popup>
  )
}

function RunDetailsPopup({ selection, onUseBbox }) {
  const { isAuthed } = useAuth()
  if (!selection) return null
  if (!isAuthed) return <PixelValuePopup selection={selection} />
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
          {meta.location ? (
            <div>
              <dt>Location</dt>
              <dd>{meta.location}</dd>
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
          {runIdSuffix(item) ? (
            <div>
              <dt>Run ID</dt>
              <dd>{runIdSuffix(item)}</dd>
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

export function StacResults({ panelHost, onUseBboxForAnalysis, probeLocation }) {
  const map = useMap()
  const [items, setItems] = useState([])
  const [error, setError] = useState(null)
  const [selection, setSelection] = useState(null)
  // Registered by each rendered StacCogLayer via its `onReady` callback (see
  // renderRun below); lets an address-search selection probe the currently
  // visible Displacement/Velocity layers for a pixel value, the same way a
  // click on one would. Keyed by `${kind}:${item.id}`; a plain ref (not state)
  // since it's only read inside the probe effect below, never rendered.
  const samplersRef = useRef(new Map())
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

  // Address-search selected a point: check whether any currently-rendered
  // Displacement/Velocity layer has a pixel there (topmost-first, same as a
  // real click would resolve overlapping layers) and open the same popup a
  // click would. No match (or the sampled pixel is nodata) -> no popup.
  useEffect(() => {
    if (!probeLocation) return undefined
    const { lat, lon } = probeLocation
    const point = { lat, lng: lon }
    let cancelled = false
    ;(async () => {
      const registered = [...samplersRef.current.values()].reverse()
      for (const { bounds, sampleAt, item, kind } of registered) {
        if (cancelled) return
        if (!bounds?.contains?.(point)) continue
        const value = await sampleAt(lat, lon)
        if (cancelled) return
        if (value == null) continue
        setSelection({ item, kind, latlng: point, value, onClose: () => setSelection(null) })
        return
      }
    })()
    return () => { cancelled = true }
  }, [probeLocation])

  if (!stacEnabled()) return null

  const velocityRuns = items.filter(isVelocityRun)
  const dispRuns = items.filter((it) => !isVelocityRun(it))
  const displacementLegend = combinedRange(dispRuns, 'displacement')
  const velocityLegend = combinedRange(velocityRuns, 'velocity')

  const selectRun = (item, kind, latlng, value) => {
    setSelection({ item, kind, latlng: latlng || map.getCenter(), value, onClose: () => setSelection(null) })
  }

  // Registers/evicts a rendered layer's {bounds, sampleAt} for the probe
  // effect above; StacCogLayer calls this with `null` on unmount/href-change.
  const registerSampler = (kind, item, info) => {
    const key = `${kind}:${item.id}`
    if (info) samplersRef.current.set(key, { ...info, item, kind })
    else samplersRef.current.delete(key)
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

  // The renderable layer for a run: always the COG (cloud-optimized, streamed
  // via range requests) for both displacement and velocity, so every run gets
  // real per-pixel values. Falls back to the cheap preview PNG only for a run
  // that has no COG asset published at all (no pixel sampling possible then).
  const renderRun = (it, kind) => {
    if (kind === 'displacement') {
      const cog = itemLayers(it).find((l) => l.type === 'cog')
      if (cog) {
        return (
          <StacCogLayer
            key={it.id}
            href={cog.href}
            range={cog.range}
            opacity={displacementOpacity}
            fit={false}
            onClick={(event, value) => selectRun(it, kind, event.latlng, value)}
            onContextMenu={(event) => openActionsMenuFromContextMenu(event, it, kind)}
            onReady={(info) => registerSampler(kind, it, info)}
          />
        )
      }
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
      return null
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
          onClick={(event, value) => selectRun(it, kind, event.latlng, value)}
          onContextMenu={(event) => openActionsMenuFromContextMenu(event, it, kind)}
          onReady={(info) => registerSampler(kind, it, info)}
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
        {shown.map((it) => {
          const parts = runRowParts(it, kind)
          return (
            <label key={it.id} className="slp-row slp-run-row">
              <input type="checkbox" checked={!hiddenIds.has(it.id)} onChange={() => toggleRun(it.id)} />
              <span className="slp-name" title={runRowTooltip(it, kind)}>
                <span className="slp-run-title">{parts.title}</span>
                {parts.dates ? <span className="slp-run-dates">Dates: {parts.dates}</span> : null}
                {parts.meta ? <span className="slp-run-meta">{parts.meta}</span> : null}
              </span>
              <button
                type="button"
                className="slp-run-actions-btn"
                aria-label="Run actions"
                onClick={(event) => openActionsMenuFromClick(event, it, kind)}
              >
                ⋮
              </button>
            </label>
          )
        })}
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
