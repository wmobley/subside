// End-to-end "draw an area -> run analysis on TACC" panel for the maps page.
//
// Mounted inside a react-leaflet <MapContainer>. The user draws a polygon or
// uploads a GeoJSON to define the AOI. We then look up OPERA DISP-S1 availability
// for that area and show it as a guide — how many products are available to
// download in the chosen window — so the user can size the area/window before a
// run (whole OPERA frames are too large and time out the workflow). The panel
// then logs in to the SUBSIDE API, submits the chosen Tapis Workflows pipeline
// over that AOI, and polls status to completion.
//
// The control panel is portalled into a Leaflet control (top-left); the AOI is a
// normal react-leaflet child.
import L from 'leaflet'
import '@geoman-io/leaflet-geoman-free'
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ImageOverlay, useMap } from 'react-leaflet'
import ReactMarkdown from 'react-markdown'

import {
  bboxToAoiGeoJSON, fetchAvailability, getRunResults, getRunStatus, listRuns, submitRun,
} from '../../lib/subsideApi'
import { getWorkflowDocs } from '../../lib/content'
import { useAuth } from '../../lib/auth'
import { findRunItem, itemDownloads, itemLayers, itemMeta, stacEnabled } from '../../lib/stacApi'
import { aoiStats, bboxToBounds, geometryBbox, toFeatureCollection } from './aoiGeometry'
import { RUN_COPY, RunProgress } from './RunProgress'
import { StacCogLayer } from './StacCogLayer'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

// Per-workflow documentation, keyed by pipeline id (content/workflows/<id>.md).
const WORKFLOW_DOCS = getWorkflowDocs()

// What the user is asking for, phrased as an outcome rather than a pipeline name.
// `pipeline` is what the API expects (h2i = acquire/preview, werc = + velocity).
const OUTCOMES = [
  { pipeline: 'h2i', label: 'See surface displacement', hint: 'a snapshot map — faster' },
  { pipeline: 'werc', label: 'Measure how fast it is sinking', hint: 'velocity, mm/yr — slower' },
]

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

export function SubsideAnalysis({ panelHost }) {
  const map = useMap()

  const [aoi, setAoi] = useState(null) // [w, s, e, n] envelope of the drawn/uploaded AOI
  // The AOI geometry (FeatureCollection), submitted verbatim. Set by drawing or
  // uploading; the bbox envelope above rides along for availability lookups.
  const [aoiGeometry, setAoiGeometry] = useState(null)
  const aoiLayerRef = useRef(null) // the Leaflet layer for the drawn/uploaded AOI
  // OPERA product availability for the current AOI. Drives the date-picker bounds
  // (so a window can't be set outside the data) and the "products available to
  // download" guide. `frames` keeps each intersecting frame's product-date
  // timeline so we can count granules (= frame-dates) in the chosen window.
  // { status: 'loading'|'ready'|'none'|'error', dates?, frames?, start?, end? }
  const [avail, setAvail] = useState(null)

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
  const [docOpen, setDocOpen] = useState(false) // workflow documentation modal

  // Completed-run results: the STAC Item the pipeline published for this run.
  // All result rasters render from its public asset hrefs (no API proxy).
  const [stacItem, setStacItem] = useState(null)
  const [selectedLayer, setSelectedLayer] = useState(null) // {key, type:'cog'|'png', href, label, range?}
  const [resultsErr, setResultsErr] = useState('')

  // Whenever the AOI changes, look up OPERA availability for it so we can pin the
  // date picker to dates that have data and tell the user how many products are
  // available to download. The /availability endpoint is viewport-lazy and may
  // still be caching on the server, so retry once if it comes back empty. We keep
  // each intersecting frame's product-date timeline (every frame-date is one
  // DISP-S1 granule) so the guide can count granules in the chosen window.
  useEffect(() => {
    if (!aoi) { setAvail(null); return undefined }
    let cancelled = false
    let timer
    setAvail({ status: 'loading' })
    const bounds = L.latLngBounds([[aoi[1], aoi[0]], [aoi[3], aoi[2]]])
    const attempt = (retriesLeft) => {
      fetchAvailability(bounds)
        .then((res) => {
          if (cancelled) return
          const items = (res.items || []).filter((i) => (i.product_count || 0) > 0)
          // Per-frame product-date timelines (normalized to YYYY-MM-DD).
          const frames = items.map(
            (i) => (i.timeline || []).map((d) => String(d).slice(0, 10)).filter(Boolean),
          )
          const dates = [...new Set(frames.flat())].sort()
          if (dates.length) {
            setAvail({ status: 'ready', dates, frames, start: dates[0], end: dates[dates.length - 1] })
          } else if (retriesLeft > 0) {
            timer = setTimeout(() => attempt(retriesLeft - 1), 2500)
          } else {
            setAvail({ status: 'none', dates: [], frames: [] })
          }
        })
        .catch(() => { if (!cancelled) setAvail({ status: 'error' }) })
    }
    attempt(1)
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [aoi])

  // Snap the date window into the available span once we know it: if the current
  // window is entirely outside the data, default to the full span; otherwise just
  // clamp the endpoints. Runs only when availability resolves (not on keystrokes).
  useEffect(() => {
    if (avail?.status !== 'ready') return
    setForm((f) => {
      if (f.end_date < avail.start || f.start_date > avail.end) {
        return { ...f, start_date: avail.start, end_date: avail.end }
      }
      return {
        ...f,
        start_date: f.start_date < avail.start ? avail.start : f.start_date,
        end_date: f.end_date > avail.end ? avail.end : f.end_date,
      }
    })
  }, [avail])

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
          style: { color: '#003399', weight: 2, fillOpacity: 0.08 },
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
      position: 'topleft',  // below the zoom control; the analysis panel left the map
      drawPolygon: true,
      drawRectangle: true,
      editMode: true,
      removalMode: true,
      // No dragMode: geoman's "drag" moves shapes, not the map, and reads as a
      // broken pan button. The map pans normally whenever no draw tool is active.
      dragMode: false,
      drawMarker: false,
      drawCircle: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawText: false,
      rotateMode: false,
      cutPolygon: false,
    })
    // tooltips:false removes the floating "Click to finish" hints; continueDrawing
    // :false makes draw exit after one shape so panning works again immediately.
    map.pm.setGlobalOptions({ snappable: false, tooltips: false, continueDrawing: false })

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
      setSubmitErr('Pick an area first — draw an area or upload a GeoJSON.')
      return
    }
    setSubmitErr('')
    setSubmitting(true)
    try {
      const body = {
        pipeline: form.pipeline,
        start_date: form.start_date,
        end_date: form.end_date,
        // The drawn/uploaded geometry is submitted verbatim (bbox fallback is
        // defensive — every AOI source sets the geometry).
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

  // OPERA availability for the chosen AOI + window. Granules available to download
  // = OPERA DISP-S1 products whose date falls in the window, summed across every
  // frame that intersects the AOI (each frame-date is a distinct product).
  const availReady = avail?.status === 'ready'
  const noData = avail?.status === 'none'
  const granulesInWindow = availReady
    ? avail.frames.reduce(
      (n, timeline) => n + timeline.filter((d) => d >= form.start_date && d <= form.end_date).length,
      0,
    )
    : null
  const emptyWindow = availReady && granulesInWindow === 0

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
                  <button type="button" className="sap-link" onClick={clearAoi}>clear</button>
                </div>
              ) : (
                <div className="sap-hint">
                  Draw an area with the polygon tool (top-right) or upload a GeoJSON.
                  Keep it tight — large areas can time out the analysis.
                  The map pans normally when you’re not drawing.
                </div>
              )}
              <div className="sap-aoi-tools">
                <button
                  type="button"
                  className="sap-link"
                  onClick={() => {
                    // Toggle: start a polygon draw, or cancel one in progress (back to pan).
                    if (map.pm?.globalDrawModeEnabled?.()) map.pm.disableDraw()
                    else map.pm?.enableDraw('Polygon')
                  }}
                >
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
              {WORKFLOW_DOCS[form.pipeline] ? (
                <button type="button" className="sap-link sap-doc-link" onClick={() => setDocOpen(true)}>
                  Learn more about this analysis →
                </button>
              ) : null}
            </div>
          </div>

          <div className="sap-step">
            <span className="sap-step-num">3</span>
            <div className="sap-step-body">
              <div className="sap-step-label">Over what time range</div>
              <div className="sap-dates">
                <input
                  type="date"
                  value={form.start_date}
                  min={availReady ? avail.start : undefined}
                  max={availReady ? avail.end : undefined}
                  onChange={setField('start_date')}
                />
                <span className="sap-dates-sep">→</span>
                <input
                  type="date"
                  value={form.end_date}
                  min={availReady ? avail.start : undefined}
                  max={availReady ? avail.end : undefined}
                  onChange={setField('end_date')}
                />
              </div>
              {avail?.status === 'loading' ? <div className="sap-hint">Checking OPERA availability for this area…</div> : null}
              {availReady && !emptyWindow ? (
                <div className="sap-avail-guide">
                  <strong>{granulesInWindow}</strong> OPERA product{granulesInWindow === 1 ? '' : 's'} available to download for this area in the selected window.
                  <div className="sap-hint">Data here spans {avail.start} → {avail.end}.</div>
                </div>
              ) : null}
              {noData ? <div className="sap-warn">No OPERA DISP-S1 data found for this area. Pick a different area.</div> : null}
              {emptyWindow ? <div className="sap-warn">No OPERA products in this window — widen the dates to the available range ({avail.start} → {avail.end}).</div> : null}
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

          <button type="button" className="sap-submit" disabled={submitting || !aoi || noData || emptyWindow} onClick={handleSubmit}>
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
      {selectedLayer?.type === 'cog' ? (
        <StacCogLayer href={selectedLayer.href} range={selectedLayer.range} onError={setResultsErr} />
      ) : null}
      {selectedLayer?.type === 'png' && stacItem?.bbox ? (
        <ImageOverlay url={selectedLayer.href} bounds={bboxToBounds(stacItem.bbox)} opacity={0.8} />
      ) : null}
      {panelHost ? createPortal(panel, panelHost) : null}
      {docOpen && WORKFLOW_DOCS[form.pipeline]
        ? createPortal(
          <div className="workflow-modal-backdrop" role="presentation" onClick={() => setDocOpen(false)}>
            <div
              className="workflow-modal sap-doc-modal"
              role="dialog"
              aria-modal="true"
              aria-label={WORKFLOW_DOCS[form.pipeline].title || 'About this analysis'}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="workflow-modal-head">
                <h2>{WORKFLOW_DOCS[form.pipeline].title || 'About this analysis'}</h2>
                <button type="button" className="modal-close" aria-label="Close" onClick={() => setDocOpen(false)}>×</button>
              </div>
              <div className="sap-doc-body">
                <ReactMarkdown>{WORKFLOW_DOCS[form.pipeline].body}</ReactMarkdown>
              </div>
              {WORKFLOW_DOCS[form.pipeline].labUrl ? (
                <p className="sap-doc-lab">
                  <a href={WORKFLOW_DOCS[form.pipeline].labUrl} target="_blank" rel="noreferrer">
                    {WORKFLOW_DOCS[form.pipeline].lab || 'Project site'} →
                  </a>
                </p>
              ) : null}
            </div>
          </div>,
          document.body,
        )
        : null}
    </>
  )
}
