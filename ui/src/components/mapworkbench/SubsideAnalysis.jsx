// End-to-end "pick a frame -> run analysis on TACC" panel for the maps page.
//
// Mounted inside a react-leaflet <MapContainer>. The user clicks an OPERA
// availability frame (handled by SubsideLayers, lifted through ModelMap as
// `picked`); that frame's footprint becomes the AOI and its product date range
// pre-fills start/end. The panel then logs in to the SUBSIDE API, submits the
// chosen Tapis Workflows pipeline over that AOI, and polls status to completion.
//
// The control panel is portalled into a Leaflet control (top-left); the AOI
// rectangle is a normal react-leaflet child.
import L from 'leaflet'
import '@geoman-io/leaflet-geoman-free'
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ImageOverlay, Rectangle, useMap } from 'react-leaflet'

import {
  bboxToAoiGeoJSON, getRunResults, getRunStatus, listRuns, submitRun,
} from '../../subsideApi'
import { useAuth } from '../../auth'
import { findRunItem, itemDownloads, itemLayers, itemMeta, stacEnabled } from '../../stacApi'
import { StacCogLayer } from './StacCogLayer'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

// What the user is asking for, phrased as an outcome rather than a pipeline name.
// `pipeline` is what the API expects (h2i = acquire/preview, werc = + velocity).
const OUTCOMES = [
  { pipeline: 'h2i', label: 'See surface displacement', hint: 'a snapshot map — faster' },
  { pipeline: 'werc', label: 'Measure how fast it is sinking', hint: 'velocity, mm/yr — slower' },
]

// Plain-language status for the running pipeline (hide Tapis state machine detail).
const RUN_COPY = {
  completed: 'Done — your results are below.',
  failed: 'The analysis failed. Try a smaller area or a different time range.',
  cancelled: 'The analysis was cancelled.',
  running: 'Analyzing your area — this usually takes a few minutes.',
  queued: 'Queued on TACC — waiting for a compute slot.',
}

// The pipeline's Tapis tasks, in order, with plain-language labels. The API
// returns per-task status in `run.tasks` (taskId/status/lastMessage); we turn
// that into a stepper so the user sees which phase is happening. The heavy
// `run` task does the whole analysis, so its hint spells out the sub-steps.
const RUN_PHASES = [
  {
    id: 'run',
    label: 'Analyzing on TACC',
    hint: 'Downloading OPERA products, building the time-series stack, and computing displacement/velocity. This is the long step — usually a few minutes.',
  },
  { id: 'publish', label: 'Preparing outputs', hint: 'Packaging the result rasters from the run.' },
  { id: 'stac-publish', label: 'Publishing to the catalog', hint: 'Indexing the results so they appear on the map.' },
]

// Last non-empty line of a task message, trimmed — surfaces real job log output
// without dumping a 2 KB stderr blob into the panel.
function lastLogLine(msg) {
  const line = String(msg || '').split('\n').map((s) => s.trim()).filter(Boolean).pop()
  if (!line) return ''
  return line.length > 160 ? `${line.slice(0, 159)}…` : line
}

// Phase stepper for an in-flight (or just-finished) run, driven by run.tasks.
function RunProgress({ run }) {
  const byId = {}
  for (const t of run.tasks || []) byId[t.taskId] = t
  const phases = RUN_PHASES.map((p) => ({ ...p, task: byId[p.id], status: byId[p.id]?.status || 'pending' }))
  const failed = run.status === 'failed'
  // The phase to narrate: the running one, else the failed one, else the first
  // not-yet-done one. Undefined once every phase is complete.
  const active = phases.find((p) => p.status === 'running')
    || (failed && phases.find((p) => p.status === 'failed'))
    || phases.find((p) => p.status !== 'completed')
  const detail = active && active.task ? lastLogLine(active.task.lastMessage) : ''

  return (
    <div className="sap-run sap-runprogress">
      <ol className="sap-phases">
        {phases.map((p) => (
          <li key={p.id} className={`sap-phase is-${p.status}${active && active.id === p.id ? ' is-active' : ''}`}>
            <span className="sap-phase-mark" aria-hidden="true">
              {p.status === 'completed' ? '✓'
                : p.status === 'failed' ? '✕'
                  : p.status === 'running' ? <span className="sap-spinner" />
                    : '○'}
            </span>
            <span className="sap-phase-label">{p.label}</span>
          </li>
        ))}
      </ol>
      {active ? (
        <div className="sap-phase-detail">
          {failed ? (
            <span className="sap-error">{detail || RUN_COPY.failed}</span>
          ) : (
            <>
              <div>{active.status === 'queued' ? RUN_COPY.queued : active.hint}</div>
              {detail ? <div className="sap-phase-msg">{detail}</div> : null}
            </>
          )}
        </div>
      ) : (
        <span>{RUN_COPY[run.status] || run.status}</span>
      )}
    </div>
  )
}

function bboxToBounds(b) {
  return [[b[1], b[0]], [b[3], b[2]]] // [[s,w],[n,e]] for Leaflet
}

// Wrap a bare geometry / Feature into a FeatureCollection (what the run API wants).
function toFeatureCollection(gj) {
  if (!gj) return null
  if (gj.type === 'FeatureCollection') return gj
  if (gj.type === 'Feature') return { type: 'FeatureCollection', features: [gj] }
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: gj }] }
}

// [w, s, e, n] envelope over any GeoJSON FeatureCollection's coordinates.
function geometryBbox(fc) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const visit = (coords) => {
    if (typeof coords[0] === 'number') {
      const [x, y] = coords
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    } else coords.forEach(visit)
  }
  for (const f of fc?.features || []) {
    if (f?.geometry?.coordinates) visit(f.geometry.coordinates)
  }
  return minX === Infinity ? null : [minX, minY, maxX, maxY]
}

// Equirectangular shoelace area (km²) of a lon/lat ring, scaled at its latitude.
// Approximate — enough to warn on AOI size, not for reporting.
function ringAreaKm2(ring, lat) {
  const kx = 111.32 * Math.cos((lat * Math.PI) / 180)
  const ky = 110.574
  let s = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const [x1, y1] = ring[i]
    const [x2, y2] = ring[i + 1]
    s += x1 * kx * (y2 * ky) - x2 * kx * (y1 * ky)
  }
  return Math.abs(s) / 2
}

// AOI size/complexity stats + non-blocking warnings. OPERA runs over a large or
// many-frame AOI cost more and take longer, so we flag it before submit.
const AOI_AREA_WARN_KM2 = 15000 // ~122 km square; bigger likely spans frames
const AOI_VERTEX_WARN = 100
function aoiStats(fc) {
  let vertices = 0
  let area = 0
  for (const f of fc?.features || []) {
    const g = f?.geometry
    if (!g) continue
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : []
    for (const poly of polys) {
      const outer = poly[0] || []
      vertices += Math.max(0, outer.length - 1)
      const lat = outer.length ? outer.reduce((sum, p) => sum + p[1], 0) / outer.length : 0
      area += ringAreaKm2(outer, lat)
      for (let h = 1; h < poly.length; h++) area -= ringAreaKm2(poly[h], lat)
    }
  }
  const warnings = []
  if (area > AOI_AREA_WARN_KM2) {
    warnings.push(`Large area (~${Math.round(area).toLocaleString()} km²) — this may span several OPERA frames and take longer.`)
  }
  if (vertices > AOI_VERTEX_WARN) {
    warnings.push('Complex boundary — consider simplifying the polygon.')
  }
  return { area, vertices, warnings }
}

// Band the *observed* risk from the velocity layer's value range. LOS velocity
// is mm/yr; negative = motion toward subsidence. We band on the fastest
// subsidence rate (most-negative value) seen in the displayed range.
function observedRisk(range) {
  if (!range) return null
  const lo = Number(range.min ?? range.vmin)
  const hi = Number(range.max ?? range.vmax)
  const subsiding = Math.max(0, -Math.min(lo, hi)) // mm/yr, magnitude
  if (Number.isNaN(subsiding)) return null
  if (subsiding < 5) return { rate: subsiding, label: 'Low', color: '#16a34a' }
  if (subsiding < 15) return { rate: subsiding, label: 'Moderate', color: '#f59e0b' }
  if (subsiding < 30) return { rate: subsiding, label: 'High', color: '#ea580c' }
  return { rate: subsiding, label: 'Severe', color: '#dc2626' }
}

export function SubsideAnalysis({ picked }) {
  const map = useMap()

  const [aoi, setAoi] = useState(null) // [w, s, e, n] envelope (all AOI sources set this)
  // The real AOI geometry when drawn/uploaded (FeatureCollection); null for a
  // frame-footprint AOI, which renders as the <Rectangle> below and submits via
  // bboxToAoiGeoJSON. When set, the geometry is submitted verbatim.
  const [aoiGeometry, setAoiGeometry] = useState(null)
  const aoiLayerRef = useRef(null) // the Leaflet layer for a drawn/uploaded AOI
  const [frameId, setFrameId] = useState(null)
  const [datesFromFrame, setDatesFromFrame] = useState(false)

  // Shared session: token persists across the site and auto-expires (see auth.jsx).
  // Login/logout live in the header; logout() here is the 401 -> force re-login path.
  const { token, logout } = useAuth()

  const [history, setHistory] = useState([])
  const [historyErr, setHistoryErr] = useState('')

  const [form, setForm] = useState({
    pipeline: 'h2i',
    start_date: '2024-06-01',
    end_date: '2024-09-01',
    allocation: '',
    min_overlap_percent: 50,
  })
  const [run, setRun] = useState(null)
  const [submitErr, setSubmitErr] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Completed-run results: the STAC Item the pipeline published for this run.
  // All result rasters render from its public asset hrefs (no API proxy).
  const [stacItem, setStacItem] = useState(null)
  const [selectedLayer, setSelectedLayer] = useState(null) // {key, type:'cog'|'png', href, label, range?}
  const [resultsErr, setResultsErr] = useState('')

  // A frame was clicked on the map: adopt its footprint as the AOI and, when the
  // frame has products, pre-fill the date window from its timeline range.
  const lastPicked = useRef(null)
  useEffect(() => {
    if (!picked || picked === lastPicked.current) return
    lastPicked.current = picked
    if (picked.bbox) {
      // A frame footprint replaces any drawn/uploaded geometry.
      removeAoiLayer()
      setAoiGeometry(null)
      setAoi(picked.bbox)
    }
    setFrameId(picked.frameId ?? null)
    if (picked.startDate && picked.endDate) {
      setForm((f) => ({ ...f, start_date: picked.startDate, end_date: picked.endDate }))
      setDatesFromFrame(true)
    } else {
      setDatesFromFrame(false)
    }
  }, [picked]) // eslint-disable-line react-hooks/exhaustive-deps

  // Leaflet control to host the panel.
  const [controlEl] = useState(() => {
    const el = L.DomUtil.create('div', 'subside-analysis-control')
    L.DomEvent.disableClickPropagation(el)
    L.DomEvent.disableScrollPropagation(el)
    return el
  })
  useEffect(() => {
    const ctrl = L.control({ position: 'topleft' })
    ctrl.onAdd = () => controlEl
    ctrl.addTo(map)
    return () => ctrl.remove()
  }, [map, controlEl])

  // --- AOI by drawing / upload (leaflet-geoman) ----------------------------
  // These only touch state setters, refs, and the (stable) map, so the geoman
  // effect below can capture them once.
  function removeAoiLayer() {
    const prev = aoiLayerRef.current
    if (prev) {
      try { map.removeLayer(prev) } catch { /* already gone */ }
      aoiLayerRef.current = null
    }
  }

  function clearAoi() {
    removeAoiLayer()
    setAoiGeometry(null)
    setAoi(null)
    setFrameId(null)
  }

  // Adopt a drawn/uploaded Leaflet layer as the single AOI: drop any previous
  // AOI layer, derive the geometry + envelope, and track edits.
  function adoptAoiLayer(layer) {
    const prev = aoiLayerRef.current
    if (prev && prev !== layer) {
      try { map.removeLayer(prev) } catch { /* already gone */ }
    }
    aoiLayerRef.current = layer
    const sync = () => {
      const fc = toFeatureCollection(layer.toGeoJSON())
      setAoiGeometry(fc)
      const bbox = geometryBbox(fc)
      if (bbox) setAoi(bbox)
    }
    layer.on('pm:edit', sync)
    sync()
    setFrameId(null)
    setDatesFromFrame(false)
  }

  function handleUploadFile(event) {
    const file = event.target.files?.[0]
    event.target.value = '' // let the same file be re-selected
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try {
        const fc = toFeatureCollection(JSON.parse(String(reader.result)))
        if (!fc?.features?.length) throw new Error('no features found')
        if (!geometryBbox(fc)) throw new Error('no coordinates found')
        const layer = L.geoJSON(fc, {
          pmIgnore: false,
          style: { color: '#005f86', weight: 2, fillOpacity: 0.08 },
        }).addTo(map)
        adoptAoiLayer(layer)
        try { map.fitBounds(layer.getBounds(), { padding: [18, 18] }) } catch { /* ignore */ }
        setSubmitErr('')
      } catch (err) {
        setSubmitErr(`Could not read GeoJSON: ${err.message}`)
      }
    }
    reader.readAsText(file)
  }

  // Mount the geoman draw toolbar (top-right, clear of the analysis panel) and
  // wire create/remove to the single-AOI model.
  useEffect(() => {
    if (!map.pm) return undefined
    map.pm.addControls({
      position: 'topright',
      drawPolygon: true,
      drawRectangle: true,
      editMode: true,
      dragMode: true,      // pan/move existing shapes
      removalMode: true,
      drawMarker: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawText: false,
      rotateMode: false,
      cutPolygon: false,
    })
    map.pm.setGlobalOptions({ snappable: false })

    const onCreate = (e) => adoptAoiLayer(e.layer)
    const onRemove = (e) => { if (e.layer === aoiLayerRef.current) clearAoi() }
    map.on('pm:create', onCreate)
    map.on('pm:remove', onRemove)
    return () => {
      map.off('pm:create', onCreate)
      map.off('pm:remove', onRemove)
      try { map.pm.removeControls() } catch { /* ignore */ }
    }
    // adoptAoiLayer/clearAoi are stable (setters + refs only).
  }, [map]) // eslint-disable-line react-hooks/exhaustive-deps

  // Poll status until terminal.
  useEffect(() => {
    if (!run?.runId || !token || TERMINAL.has(run.status)) return undefined
    const id = setInterval(() => {
      getRunStatus(token, run.runId)
        .then((st) => setRun((cur) => ({ ...cur, ...st })))
        .catch((err) => setSubmitErr(err.message))
    }, 5000)
    return () => clearInterval(id)
  }, [run?.runId, run?.status, token])

  // When a run completes, resolve the STAC Item the pipeline published for it,
  // then render result rasters from its public asset hrefs. We get the run's
  // AOI bbox + date window from the results manifest (a metadata call, not a
  // raster proxy) so this also works for runs reattached from history. Clears
  // when the run isn't completed.
  useEffect(() => {
    if (!token || !run?.runId || run.status !== 'completed') {
      setStacItem(null); setSelectedLayer(null); return undefined
    }
    let cancelled = false
    setResultsErr(''); setStacItem(null); setSelectedLayer(null)
    if (!stacEnabled()) {
      setResultsErr('Map visualization needs the STAC API — set VITE_STAC_API_BASE.')
      return undefined
    }
    getRunResults(token, run.runId)
      .then((res) => {
        const m = res?.manifest || {}
        const b = m.bbox
        const bbox = b && b.lon_min != null
          ? [b.lon_min, b.lat_min, b.lon_max, b.lat_max]
          : aoi
        const cfg = m.config || {}
        return findRunItem({
          bbox,
          start: cfg.start_date || form.start_date,
          end: cfg.end_date || form.end_date,
        })
      })
      .then((item) => {
        if (cancelled) return
        setStacItem(item)
        if (!item) setResultsErr('Results are still being published to the catalog — check back shortly.')
      })
      .catch((err) => { if (!cancelled) setResultsErr(err.message) })
    return () => { cancelled = true }
  }, [token, run?.runId, run?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fit the map to a selected PNG overlay (COGs fit themselves in StacCogLayer).
  useEffect(() => {
    if (selectedLayer?.type !== 'png' || !stacItem?.bbox) return
    try { map.fitBounds(bboxToBounds(stacItem.bbox)) } catch { /* ignore */ }
  }, [selectedLayer, stacItem, map])

  // Pull the durable workflow history whenever we have a token (incl. after refresh).
  function refreshHistory(tok = token) {
    if (!tok) return
    listRuns(tok)
      .then((res) => { setHistory(res.runs || []); setHistoryErr('') })
      .catch((err) => {
        setHistoryErr(err.message)
        if (/token|401|unauthor/i.test(err.message)) logout() // expired -> force re-login
      })
  }
  useEffect(() => { refreshHistory() }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  // When the session ends (logout or expiry from the header), drop run state.
  useEffect(() => {
    if (!token) { setHistory([]); setRun(null) }
  }, [token])

  // Survive a page refresh: component state resets, but the session (localStorage
  // token) and the server-side run history persist. If a run is still in flight
  // and we aren't already tracking one, re-attach the poller to the most recent
  // live run so the progress stepper resumes on its own.
  useEffect(() => {
    if (run) return
    const live = history
      .filter((h) => !TERMINAL.has(h.status))
      .sort((a, b) => String(b.created || '').localeCompare(String(a.created || '')))[0]
    if (live) attachRun(live)
  }, [history]) // eslint-disable-line react-hooks/exhaustive-deps

  // Re-attach the status poller to a pipeline run picked from history.
  function attachRun(item) {
    setRun({ runId: item.runId, status: item.status, tapisStatus: item.tapisStatus, lastMessage: '' })
  }

  async function handleSubmit() {
    if (!aoi) {
      setSubmitErr('Pick an area first — click a frame, draw an area, or upload a GeoJSON.')
      return
    }
    setSubmitErr('')
    setSubmitting(true)
    try {
      const body = {
        pipeline: form.pipeline,
        start_date: form.start_date,
        end_date: form.end_date,
        // A drawn/uploaded geometry is submitted verbatim; a frame footprint is
        // an envelope, sent as its bbox polygon.
        aoi_geojson: aoiGeometry || bboxToAoiGeoJSON(aoi),
        min_overlap_percent: Number(form.min_overlap_percent),
      }
      if (form.allocation.trim()) body.allocation = form.allocation.trim()
      const res = await submitRun(token, body)
      setRun({ runId: res.runId, status: res.status, tapisStatus: res.tapisStatus, lastMessage: '' })
      refreshHistory()
    } catch (err) {
      setSubmitErr(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const setField = (k) => (e) => {
    if (k === 'start_date' || k === 'end_date') setDatesFromFrame(false)
    setForm((f) => ({ ...f, [k]: e.target.value }))
  }

  // Result layers (selectable rasters) + downloads + metadata, from the STAC Item.
  const layerOptions = itemLayers(stacItem)
  const downloads = itemDownloads(stacItem)
  const meta = itemMeta(stacItem)
  const legendRange = selectedLayer?.range

  // Risk-card inputs. A velocity layer means this run measured a rate (werc);
  // without one it's a displacement-only snapshot (h2i). The display range rides
  // on the STAC asset, so we can read the rate without rendering the layer.
  const velocityLayer = layerOptions.find((l) => l.key === 'velocity' || /velocit/i.test(l.label))
  const observed = observedRisk(velocityLayer?.range)

  // AOI size/complexity warnings, on the exact geometry that will be submitted.
  const aoiFc = aoi ? (aoiGeometry || bboxToAoiGeoJSON(aoi)) : null
  const aoiWarnings = aoiFc ? aoiStats(aoiFc).warnings : []

  const panel = (
    <div className="subside-analysis-panel">
      <div className="sap-title">Subsidence risk at this location</div>

      {!token ? (
        <div className="sap-login">
          <div className="sap-hint">Log in with your TACC account (top-right) to run an analysis.</div>
        </div>
      ) : (
        <>
          <div className="sap-step">
            <span className="sap-step-num">1</span>
            <div className="sap-step-body">
              <div className="sap-step-label">Where</div>
              {aoi ? (
                <div className="sap-frame-ok">
                  Area selected ✓
                  {frameId != null ? <span className="sap-hint"> (frame {frameId})</span>
                    : aoiGeometry ? <span className="sap-hint"> (custom area)</span> : null}
                  <button type="button" className="sap-link" onClick={clearAoi}>clear</button>
                </div>
              ) : (
                <div className="sap-hint">
                  Click a shaded frame, draw an area with the map tools (top-right), or upload a GeoJSON.
                </div>
              )}
              <div className="sap-aoi-tools">
                <button type="button" className="sap-link" onClick={() => map.pm?.enableDraw('Polygon')}>
                  ✏ Draw area
                </button>
                <label className="sap-link sap-upload-aoi">
                  ⤒ Upload GeoJSON
                  <input
                    type="file"
                    accept=".geojson,.json,application/geo+json,application/json"
                    onChange={handleUploadFile}
                    hidden
                  />
                </label>
              </div>
            </div>
          </div>

          <div className="sap-step">
            <span className="sap-step-num">2</span>
            <div className="sap-step-body">
              <div className="sap-step-label">What do you want to know?</div>
              <select value={form.pipeline} onChange={setField('pipeline')}>
                {OUTCOMES.map((o) => (
                  <option key={o.pipeline} value={o.pipeline}>{o.label}</option>
                ))}
              </select>
              <div className="sap-hint">{OUTCOMES.find((o) => o.pipeline === form.pipeline)?.hint}</div>
            </div>
          </div>

          <div className="sap-step">
            <span className="sap-step-num">3</span>
            <div className="sap-step-body">
              <div className="sap-step-label">Over what time range</div>
              <div className="sap-dates">
                <input type="date" value={form.start_date} onChange={setField('start_date')} />
                <span className="sap-dates-sep">→</span>
                <input type="date" value={form.end_date} onChange={setField('end_date')} />
              </div>
              {datesFromFrame ? <div className="sap-hint">set from this area's available data</div> : null}
              {form.pipeline === 'werc' ? <div className="sap-hint">a multi-year range gives a more reliable rate</div> : null}
            </div>
          </div>

          <details className="sap-advanced">
            <summary>Advanced</summary>
            <label className="sap-field">
              <span className="sap-label">Allocation</span>
              <input placeholder="server default" value={form.allocation} onChange={setField('allocation')} />
            </label>
          </details>

          {aoiWarnings.length ? (
            <div className="sap-warn">{aoiWarnings.map((w) => <div key={w}>{w}</div>)}</div>
          ) : null}

          <button type="button" className="sap-submit" disabled={submitting || !aoi} onClick={handleSubmit}>
            {submitting ? 'Submitting…' : 'Run analysis'}
          </button>
          {submitErr ? <div className="sap-error">{submitErr}</div> : null}

          {run ? (
            run.tasks?.length ? (
              <RunProgress run={run} />
            ) : (
              <div className={`sap-run sap-${run.status}`}>
                {!TERMINAL.has(run.status) ? <span className="sap-spinner" /> : null}
                <span>{RUN_COPY[run.status] || run.status}</span>
              </div>
            )
          ) : null}

          {run?.status === 'completed' ? (
            <div className="sap-results">
              {resultsErr ? <div className="sap-error">{resultsErr}</div> : null}

              {selectedLayer ? (
                <>
                  <button type="button" className="sap-link" onClick={() => setSelectedLayer(null)}>
                    ← all results
                  </button>
                  <div className="sap-results-head">{selectedLayer.label}</div>
                  <div className="sap-legend2">
                    <div className="sap-legend-bar" />
                    <div className="sap-legend-labels">
                      <span>{legendRange ? Number(legendRange.min ?? legendRange.vmin).toPrecision(3) : 'low'}</span>
                      <span>{selectedLayer.unit || ''}</span>
                      <span>{legendRange ? Number(legendRange.max ?? legendRange.vmax).toPrecision(3) : 'high'}</span>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="sap-results-head">Observed subsidence</div>
                  <div className="risk-summary risk-summary--single">
                    <div className="risk-card">
                      <div className="risk-card-head">Observed</div>
                      {velocityLayer ? (
                        observed ? (
                          <>
                            <div className="risk-card-value" style={{ color: observed.color }}>
                              {observed.label}
                            </div>
                            <div className="risk-card-sub">up to {observed.rate.toFixed(0)} mm/yr</div>
                          </>
                        ) : (
                          <button type="button" className="sap-link" onClick={() => setSelectedLayer(velocityLayer)}>
                            View velocity layer to read the rate →
                          </button>
                        )
                      ) : (
                        <div className="risk-card-sub">Displacement snapshot only — run “Measure how fast it is sinking” for a rate.</div>
                      )}
                      <div className="risk-card-note">measured · OPERA DISP-S1</div>
                    </div>
                  </div>
                  <div className="sap-hint sap-forecast-pointer">
                    Want a projection? The <strong>Forecast</strong> tab estimates potential future subsidence and a 0–10 risk score.
                  </div>

                  {(meta.start || meta.productCount != null || meta.frameIds?.length) ? (
                    <>
                      <div className="sap-results-head">Run details</div>
                      <dl className="sap-meta">
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
                      </dl>
                    </>
                  ) : null}

                  <div className="sap-results-head">Result layers</div>
                  {layerOptions.length ? layerOptions.map((l) => (
                    <button type="button" key={l.key} className="sap-layer-row" onClick={() => setSelectedLayer(l)}>
                      ▦ {l.label}
                    </button>
                  )) : (!resultsErr ? <div className="sap-hint">No raster layers in this run.</div> : null)}
                  {downloads.length ? (
                    <div className="sap-downloads">
                      {downloads.map((d) => (
                        <a key={d.key} className="sap-dl" href={d.href} target="_blank" rel="noreferrer" download>
                          ⤓ {d.name}
                        </a>
                      ))}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          ) : null}

          <div className="sap-history">
            <div className="sap-history-head">
              <span>Your past runs</span>
              <button type="button" className="sap-link" onClick={() => refreshHistory()}>refresh</button>
            </div>
            {historyErr ? <div className="sap-error">{historyErr}</div> : null}
            {!history.length && !historyErr ? <div className="sap-hint">No runs yet.</div> : null}
            {history.map((h) => (
              <button
                type="button"
                key={h.runId}
                className={`sap-history-row${run?.runId === h.runId ? ' active' : ''}`}
                onClick={() => attachRun(h)}
                title={h.name || h.runId}
              >
                <span className={`sap-dot sap-${h.status}`} />
                <span className="sap-history-name">
                  {(h.pipeline === 'werc' ? 'Velocity' : h.pipeline === 'h2i' ? 'Displacement' : (h.pipeline || h.appId))} · {h.created ? h.created.slice(0, 10) : '—'}
                </span>
                <span className="sap-history-status">{h.status}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )

  return (
    <>
      {aoi && !aoiGeometry ? <Rectangle bounds={bboxToBounds(aoi)} pathOptions={{ color: '#005f86', weight: 2, fillOpacity: 0.08 }} /> : null}
      {selectedLayer?.type === 'cog' ? (
        <StacCogLayer href={selectedLayer.href} range={selectedLayer.range} onError={setResultsErr} />
      ) : null}
      {selectedLayer?.type === 'png' && stacItem?.bbox ? (
        <ImageOverlay url={selectedLayer.href} bounds={bboxToBounds(stacItem.bbox)} opacity={0.8} />
      ) : null}
      {createPortal(panel, controlEl)}
    </>
  )
}
