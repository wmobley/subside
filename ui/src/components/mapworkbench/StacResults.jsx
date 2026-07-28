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
import { cssGradient } from '../../lib/colorRamps'
import { layerContext } from '../../lib/layerContext'
import { itemLayers, itemMeta, overlayHref, searchItems, stacEnabled } from '../../lib/stacApi'
import { RunActionsMenu } from './RunActionsMenu'
import { StacCogLayer } from './StacCogLayer'

// Cap how many runs are LISTED per category per viewport (searchItems already
// caps the query at 50) — how many actually RENDER as live layers is separate
// and much smaller: only opted-in runs render (see isRunVisible below), so a
// dense area no longer means a burst of concurrent raster loads just from
// having many runs in view.
const MAX_RUNS = 24

// Date-range presets that narrow the underlying STAC search itself (bbox AND
// datetime), not just which already-fetched runs are visible — areas with a
// long processing history can have dozens of runs per viewport, and most of
// that history usually isn't relevant to "what does it look like now."
const DATE_RANGE_PRESETS = [
  { value: 'all', label: 'All time' },
  { value: '3m', label: 'Last 3 months' },
  { value: '6m', label: 'Last 6 months' },
  { value: '1y', label: 'Last year' },
]

function datetimeParamFor(preset) {
  const months = { '3m': 3, '6m': 6, '1y': 12 }[preset]
  if (!months) return undefined
  const from = new Date()
  from.setMonth(from.getMonth() - months)
  return `${from.toISOString()}/..`
}

// The most recently-acquired run in a list (by itemMeta().start), or null if
// empty — the one run shown by default before a user has picked anything for
// that kind (see isRunVisible/toggleRun).
function mostRecentId(runs) {
  if (!runs.length) return null
  let best = runs[0]
  let bestStart = itemMeta(best).start || ''
  for (const it of runs) {
    const start = itemMeta(it).start || ''
    if (start > bestStart) { best = it; bestStart = start }
  }
  return best.id
}

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
function RasterLegend({ range, fallbackUnit, palette = 'viridis' }) {
  return (
    <div className="slp-raster-legend">
      <div className="slp-raster-legend-bar" style={{ background: cssGradient(palette) }} />
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

  // The registered layer whose bounds contain (lat, lon) and whose sampled
  // pixel there isn't nodata, checked topmost-rendered-first (same order a
  // real overlapping-layer click would resolve). Shared by a real map click,
  // a right-click, and an address-search probe — see samplersRef above for
  // why layer-level click events can't do this themselves.
  const findSampledRunAt = async (lat, lon) => {
    const point = { lat, lng: lon }
    const registered = [...samplersRef.current.values()].reverse()
    for (const { bounds, sampleAt, item, kind } of registered) {
      if (!bounds?.contains?.(point)) continue
      const value = await sampleAt(lat, lon)
      if (value == null) continue
      return { item, kind, value }
    }
    return null
  }

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
  // Narrows the underlying STAC search (date) and the fetched run list
  // (location, client-side) — see DATE_RANGE_PRESETS/datetimeParamFor above.
  const [dateRangePreset, setDateRangePreset] = useState('all')
  const [locationFilter, setLocationFilter] = useState('')
  // Per-run visibility is opt-in, not opt-out: a group's master toggle reveals
  // individual run rows, but only the single most-recently-acquired run of
  // that kind renders by default (see mostRecentId/isRunVisible) — with up to
  // ~24 runs listed per kind, defaulting all of them to visible meant up to
  // ~24 live COG layers competing for the browser's connection budget at
  // once. `shownIds` only takes effect once the user has manually toggled at
  // least one run for that kind (tracked by `pickedKinds`); until then,
  // isRunVisible falls back to "just the most recent one."
  const [shownIds, setShownIds] = useState(() => new Set())
  const [pickedKinds, setPickedKinds] = useState(() => new Set())

  const isRunVisible = (id, kind, runs) => {
    if (pickedKinds.has(kind)) return shownIds.has(id)
    return id === mostRecentId(runs)
  }

  const toggleRun = (id, kind, runs) => {
    const firstInteractionForKind = !pickedKinds.has(kind)
    setPickedKinds((prev) => (prev.has(kind) ? prev : new Set(prev).add(kind)))
    setShownIds((prev) => {
      // First toggle for this kind: seed with whatever was showing by
      // default (the most-recent run) so flipping a *different* run on
      // doesn't silently hide the one already visible.
      const next = new Set(prev)
      if (firstInteractionForKind) {
        const def = mostRecentId(runs)
        if (def) next.add(def)
      }
      if (next.has(id)) {
        next.delete(id)
        setSelection((sel) => (sel?.item?.id === id ? null : sel)) // drop popup for a hidden run
      } else {
        next.add(id)
      }
      return next
    })
  }

  const refresh = () => {
    if (!stacEnabled() || !map) return
    searchItems(map.getBounds(), { datetime: datetimeParamFor(dateRangePreset) })
      .then((features) => { setItems(features); setError(null) })
      .catch((err) => setError(err?.message || 'STAC search failed'))
  }

  // A real click/right-click on a rendered COG-backed layer: the layers
  // themselves can't fire this (see samplersRef/findSampledRunAt above), so
  // the map itself is the interactive surface. No hit -> no popup, and a
  // right-click with no hit falls through to the browser's own context menu.
  const handleMapClick = (event) => {
    const { lat, lng: lon } = event.latlng
    findSampledRunAt(lat, lon).then((hit) => {
      if (!hit) return
      setSelection({ item: hit.item, kind: hit.kind, latlng: event.latlng, value: hit.value, onClose: () => setSelection(null) })
    })
  }
  const handleMapContextMenu = (event) => {
    const { lat, lng: lon } = event.latlng
    findSampledRunAt(lat, lon).then((hit) => {
      if (!hit) return
      event.originalEvent?.preventDefault?.()
      setActionsMenu({ item: hit.item, kind: hit.kind, top: event.originalEvent?.clientY ?? 0, left: event.originalEvent?.clientX ?? 0 })
    })
  }

  // Re-search on pan/zoom end, and whenever the date range changes.
  useMapEvents({ moveend: refresh, zoomend: refresh, click: handleMapClick, contextmenu: handleMapContextMenu })
  useEffect(refresh, [map, dateRangePreset])

  // Address-search selected a point: same lookup a real click does above.
  useEffect(() => {
    if (!probeLocation) return undefined
    let cancelled = false
    findSampledRunAt(probeLocation.lat, probeLocation.lon).then((hit) => {
      if (cancelled || !hit) return
      const latlng = { lat: probeLocation.lat, lng: probeLocation.lon }
      setSelection({ item: hit.item, kind: hit.kind, latlng, value: hit.value, onClose: () => setSelection(null) })
    })
    return () => { cancelled = true }
  }, [probeLocation])

  if (!stacEnabled()) return null

  // Location is a pure client-side narrowing of whatever the current
  // viewport+date search already returned (STAC search itself is bbox-based,
  // not location-name-based) — but applied here, before everything else, so
  // the group counts, legend range, run rows, and what's eligible to be the
  // "most recent" default all consistently reflect the filter.
  const needle = locationFilter.trim().toLowerCase()
  const matchesLocation = (it) => !needle || (itemMeta(it).location || '').toLowerCase().includes(needle)
  const velocityRuns = items.filter(isVelocityRun).filter(matchesLocation)
  const dispRuns = items.filter((it) => !isVelocityRun(it)).filter(matchesLocation)
  // The color scale (and its matching legend) is computed from only the runs
  // actually being RENDERED right now (isRunVisible), not every run the
  // current viewport's search happened to also return. Using the full
  // candidate list here was a real bug: panning/zooming changes which OTHER
  // (unrendered, not even opted-in) runs are "in view", which shifted this
  // combined min/max, which silently recolored an unchanged, still-visible
  // run — the exact same pixel value could render as a different color
  // purely because the viewport moved. Scoping to what's visible makes a
  // run's colors stable for as long as it stays the one being shown.
  const visibleDispRuns = dispRuns.filter((it) => isRunVisible(it.id, 'displacement', dispRuns))
  const visibleVelocityRuns = velocityRuns.filter((it) => isRunVisible(it.id, 'velocity', velocityRuns))
  const displacementLegend = combinedRange(visibleDispRuns, 'displacement')
  const velocityLegend = combinedRange(visibleVelocityRuns, 'velocity')
  // Color every currently-shown run of a kind against the SAME min/max (the
  // legend's combined range across all of them), not each run's own range —
  // otherwise two runs sitting side by side on the map use different color
  // scales and the same color means different physical values in each, while
  // the single shared legend shown for the group would be flat wrong for one
  // of them. Falls back to the per-run range if nothing visible has one.
  const displacementColorRange = displacementLegend ? { vmin: displacementLegend.min, vmax: displacementLegend.max } : null
  const velocityColorRange = velocityLegend ? { vmin: velocityLegend.min, vmax: velocityLegend.max } : null

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
            range={displacementColorRange || cog.range}
            opacity={displacementOpacity}
            fit={false}
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
          range={velocityColorRange || vel.range}
          opacity={velocityOpacity}
          fit={false}
          palette="plasma"
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

  // Per-run rows shown under a group when its master toggle is on: one
  // checkbox per in-view run, so users can isolate/compare specific
  // overlapping footprints. Only the checked ones actually render as live
  // layers (see isRunVisible) — capped at MAX_RUNS to match what's listed.
  const runRows = (runs, kind) => {
    const shown = runs.slice(0, MAX_RUNS)
    return (
      <div className="slp-run-list">
        {shown.map((it) => {
          const parts = runRowParts(it, kind)
          return (
            <label key={it.id} className="slp-row slp-run-row">
              <input type="checkbox" checked={isRunVisible(it.id, kind, runs)} onChange={() => toggleRun(it.id, kind, runs)} />
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
      <div className="slp-run-filters">
        <input
          type="text"
          className="slp-filter-input"
          placeholder="Filter by location…"
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
        />
        <select
          className="slp-filter-select"
          value={dateRangePreset}
          onChange={(e) => setDateRangePreset(e.target.value)}
          aria-label="Date range"
        >
          {DATE_RANGE_PRESETS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
      </div>
      <label className="slp-row">
        <input type="checkbox" checked={showDisplacement} onChange={(e) => {
          const checked = e.target.checked
          console.log('[StacResults] Displacement toggle ->', checked, 'would show:', visibleDispRuns.map((it) => ({ id: it.id, href: runLayer(it, 'displacement')?.href })))
          setShowDisplacement(checked)
          if (!checked && selection?.kind === 'displacement') setSelection(null)
        }} />
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
        <input type="checkbox" checked={showVelocity} onChange={(e) => {
          const checked = e.target.checked
          console.log('[StacResults] Velocity toggle ->', checked, 'would show:', visibleVelocityRuns.map((it) => ({ id: it.id, href: runLayer(it, 'velocity')?.href })))
          setShowVelocity(checked)
          if (!checked && selection?.kind === 'velocity') setSelection(null)
        }} />
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
      {showVelocity ? <RasterLegend range={velocityLegend} fallbackUnit="mm/yr" palette="plasma" /> : null}
      {showVelocity ? runRows(velocityRuns, 'velocity') : null}
      {error ? <div className="slp-error">{error}</div> : null}
    </>
  )

  return (
    <>
      {showDisplacement && dispRuns.slice(0, MAX_RUNS).filter((it) => isRunVisible(it.id, 'displacement', dispRuns)).map((it) => renderRun(it, 'displacement'))}
      {showVelocity && velocityRuns.slice(0, MAX_RUNS).filter((it) => isRunVisible(it.id, 'velocity', velocityRuns)).map((it) => renderRun(it, 'velocity'))}
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
