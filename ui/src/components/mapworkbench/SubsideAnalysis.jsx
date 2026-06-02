// End-to-end "pick a frame -> run analysis on TACC" panel for the maps page.
//
// Mounted inside a react-leaflet <MapContainer>. The user clicks an OPERA
// availability frame (handled by SubsideLayers, lifted through ModelMap as
// `picked`); that frame's footprint becomes the AOI and its product date range
// pre-fills start/end. The panel then logs in to the SUBSIDE API, submits the
// chosen pipeline as a Tapis job over that AOI, and polls status to completion.
//
// The control panel is portalled into a Leaflet control (top-left); the AOI
// rectangle is a normal react-leaflet child.
import L from 'leaflet'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ImageOverlay, Rectangle, useMap } from 'react-leaflet'

import {
  bboxToAoiGeoJSON, fetchArtifactBlob, getRunResults, getRunStatus,
  listRuns, submitRun,
} from '../../subsideApi'
import { useAuth } from '../../auth'
import { CogLayer } from './CogLayer'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

// What the user is asking for, phrased as an outcome rather than a pipeline name.
// `pipeline` is what the API expects (h2i = acquire/preview, werc = + velocity).
const OUTCOMES = [
  { pipeline: 'h2i', label: 'See surface displacement', hint: 'a snapshot map — faster' },
  { pipeline: 'werc', label: 'Measure how fast it is sinking', hint: 'velocity, mm/yr — slower' },
]

// Plain-language status for the running job (hide Tapis state machine detail).
const RUN_COPY = {
  completed: 'Done — your results are below.',
  failed: 'The analysis failed. Try a smaller area or a different time range.',
  cancelled: 'The analysis was cancelled.',
  running: 'Analyzing your area — this usually takes a few minutes.',
  queued: 'Queued on TACC — waiting for a compute slot.',
}

function bboxToBounds(b) {
  return [[b[1], b[0]], [b[3], b[2]]] // [[s,w],[n,e]] for Leaflet
}

// "opera_disp_s1_cumulative.tif" -> "Cumulative"
function layerLabel(name) {
  const base = (name || '').replace(/\.tif$/i, '').replace(/^opera_disp_s1_/i, '').replace(/_/g, ' ').trim()
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : name
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

  const [aoi, setAoi] = useState(null) // [w, s, e, n]
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

  // Completed-run results: the displacement overlay + downloadable artifacts.
  const [results, setResults] = useState(null)
  const [selectedLayer, setSelectedLayer] = useState(null) // {type:'cog'|'png', name, path, label, bounds?}
  const [pngUrl, setPngUrl] = useState(null)               // blob URL when a PNG layer is shown
  const [cogRange, setCogRange] = useState(null)           // {min,max} reported by the COG layer
  const [velocityRange, setVelocityRange] = useState(null) // cached range of the velocity layer, for the Observed risk card
  const [resultsErr, setResultsErr] = useState('')

  // A frame was clicked on the map: adopt its footprint as the AOI and, when the
  // frame has products, pre-fill the date window from its timeline range.
  const lastPicked = useRef(null)
  useEffect(() => {
    if (!picked || picked === lastPicked.current) return
    lastPicked.current = picked
    if (picked.bbox) setAoi(picked.bbox)
    setFrameId(picked.frameId ?? null)
    if (picked.startDate && picked.endDate) {
      setForm((f) => ({ ...f, start_date: picked.startDate, end_date: picked.endDate }))
      setDatesFromFrame(true)
    } else {
      setDatesFromFrame(false)
    }
  }, [picked])

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

  // When a run is completed, pull its results (the list of layers). Don't render
  // anything until the user picks a layer. Clears when the run isn't completed.
  useEffect(() => {
    if (!token || !run?.runId) { setResults(null); setSelectedLayer(null); return undefined }
    if (run.status !== 'completed') { setSelectedLayer(null); return undefined }
    let cancelled = false
    setResultsErr('')
    getRunResults(token, run.runId)
      .then((res) => { if (!cancelled) { setResults(res); setSelectedLayer(null) } })
      .catch((err) => { if (!cancelled) setResultsErr(err.message) })
    return () => { cancelled = true }
  }, [token, run?.runId, run?.status])

  // A selected PNG layer needs a blob URL for the ImageOverlay (COGs fetch
  // themselves inside CogLayer). Revoke the URL when the selection changes.
  useEffect(() => {
    if (selectedLayer?.type !== 'png') { setPngUrl(null); return undefined }
    let cancelled = false
    let url
    fetchArtifactBlob(token, run.runId, selectedLayer.path)
      .then((u) => {
        if (cancelled) { URL.revokeObjectURL(u); return }
        url = u
        setPngUrl(u)
        try { map.fitBounds(selectedLayer.bounds) } catch { /* ignore */ }
      })
      .catch((err) => setResultsErr(err.message))
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [selectedLayer, token, run?.runId, map])

  // Cache the velocity layer's value range so the Observed risk card can read a
  // rate even back in the layer-list view (where no COG is rendered).
  useEffect(() => {
    if (cogRange && selectedLayer && /velocit/i.test(selectedLayer.label || selectedLayer.name || '')) {
      setVelocityRange(cogRange)
    }
  }, [cogRange, selectedLayer])

  // A fresh run starts with no known velocity range.
  useEffect(() => { setVelocityRange(null) }, [run?.runId])

  // Pull the durable job history whenever we have a token (incl. after refresh).
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

  // Re-attach the status poller to a job picked from history.
  function attachRun(item) {
    setRun({ runId: item.runId, status: item.status, tapisStatus: item.tapisStatus, lastMessage: '' })
  }

  async function downloadArtifact(art) {
    try {
      const url = await fetchArtifactBlob(token, run.runId, art.path)
      const a = document.createElement('a')
      a.href = url
      a.download = art.name
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
    } catch (err) {
      setResultsErr(err.message)
    }
  }

  async function handleSubmit() {
    if (!aoi) {
      setSubmitErr('Click an availability frame on the map first.')
      return
    }
    setSubmitErr('')
    setSubmitting(true)
    try {
      const body = {
        pipeline: form.pipeline,
        start_date: form.start_date,
        end_date: form.end_date,
        aoi_geojson: bboxToAoiGeoJSON(aoi),
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

  // Result layers (selectable rasters) + the archive zip, from the run manifest.
  const artifacts = results?.artifacts || []
  const mbbox = results?.manifest?.bbox
  const layerOptions = [
    ...artifacts
      .filter((a) => /\.tif$/i.test(a.name || ''))
      .map((a) => ({ type: 'cog', name: a.name, path: a.path, label: layerLabel(a.name) })),
    ...(mbbox?.lat_min != null
      ? artifacts
        .filter((a) => /disp_overlay\.png$/i.test(a.name || ''))
        .map((a) => ({
          type: 'png', name: a.name, path: a.path, label: 'Displacement (preview)',
          bounds: [[mbbox.lat_min, mbbox.lon_min], [mbbox.lat_max, mbbox.lon_max]],
        }))
      : []),
  ]
  const zipArt = artifacts.find((a) => /\.zip$/i.test(a.name || ''))
  const legendRange = cogRange || (selectedLayer?.range)

  // Risk-card inputs. A velocity layer in the manifest means this run measured a
  // rate (werc); without one it's a displacement-only snapshot (h2i).
  const velocityLayer = layerOptions.find((l) => /velocit/i.test(l.label) || /velocit/i.test(l.name))
  const observed = observedRisk(velocityRange)

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
                  Area selected ✓{frameId != null ? <span className="sap-hint"> (frame {frameId})</span> : null}
                </div>
              ) : (
                <div className="sap-hint">Click a shaded frame on the map to choose your area.</div>
              )}
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

          <button type="button" className="sap-submit" disabled={submitting || !aoi} onClick={handleSubmit}>
            {submitting ? 'Submitting…' : 'Run analysis'}
          </button>
          {submitErr ? <div className="sap-error">{submitErr}</div> : null}

          {run ? (
            <div className={`sap-run sap-${run.status}`}>
              {!TERMINAL.has(run.status) ? <span className="sap-spinner" /> : null}
              <span>{RUN_COPY[run.status] || run.status}</span>
            </div>
          ) : null}

          {run?.status === 'completed' ? (
            <div className="sap-results">
              {resultsErr ? <div className="sap-error">{resultsErr}</div> : null}

              {selectedLayer ? (
                <>
                  <button type="button" className="sap-link" onClick={() => { setSelectedLayer(null); setCogRange(null) }}>
                    ← all results
                  </button>
                  <div className="sap-results-head">{selectedLayer.label}</div>
                  <div className="sap-legend2">
                    <div className="sap-legend-bar" />
                    <div className="sap-legend-labels">
                      <span>{legendRange ? Number(legendRange.min ?? legendRange.vmin).toPrecision(3) : 'low'}</span>
                      <span>{selectedLayer.label}</span>
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

                  <div className="sap-results-head">Result layers</div>
                  {layerOptions.length ? layerOptions.map((l) => (
                    <button type="button" key={l.path} className="sap-layer-row" onClick={() => { setCogRange(null); setSelectedLayer(l) }}>
                      ▦ {l.label}
                    </button>
                  )) : (!resultsErr ? <div className="sap-hint">No raster layers in this run.</div> : null)}
                  {zipArt ? (
                    <button type="button" className="sap-dl" onClick={() => downloadArtifact(zipArt)}>
                      ⤓ {zipArt.name}
                    </button>
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
      {aoi ? <Rectangle bounds={bboxToBounds(aoi)} pathOptions={{ color: '#005f86', weight: 2, fillOpacity: 0.08 }} /> : null}
      {selectedLayer?.type === 'cog' ? (
        <CogLayer token={token} runId={run.runId} path={selectedLayer.path} onRange={setCogRange} onError={setResultsErr} />
      ) : null}
      {selectedLayer?.type === 'png' && pngUrl ? (
        <ImageOverlay url={pngUrl} bounds={selectedLayer.bounds} opacity={0.8} />
      ) : null}
      {createPortal(panel, controlEl)}
    </>
  )
}
