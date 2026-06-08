// Standalone "potential subsidence" forecast page.
//
// Runs the in-process screening model (POST /api/subside/forecast) — no map, no
// OPERA run required. The form is prefilled from the model's own template
// (GET /forecast/template) so every field has a sensible default; the user edits
// what they know. Field keys are the model's visible Excel-style labels, which
// the API accepts directly.
//
// Next step (not yet wired): prefill these inputs from the TWDB CKAN/PostGIS
// spatial layers at a clicked location, leaving this form for overrides.
import { useEffect, useState } from 'react'

import { getForecastTemplate, runForecast } from '../subsideApi'
import { RiskGauge } from './mapworkbench/RiskGauge'

const LITHOLOGY = ['Unconsolidated Clastic', 'Consolidated Clastic', 'Carbonate', 'Igneous']
const CLAY_TYPE = ['Plastic Clay', 'Stiff Clay', 'Hard Clay']
const WL_METHOD = ['Current and Trend', 'Base and Future']

// Form layout. `k` is the model's visible-label key (also the template key).
const GROUPS = [
  {
    title: 'Site & aquifer geometry',
    fields: [
      { k: 'Land Surface (feet MSL)', label: 'Land surface', unit: 'ft MSL' },
      { k: 'Aquifer Top (feet MSL)', label: 'Aquifer top', unit: 'ft MSL' },
      { k: 'Aquifer Thickness', label: 'Aquifer thickness', unit: 'ft' },
      { k: 'Clay Thickness within Aquifer', label: 'Clay thickness', unit: 'ft' },
      { k: 'Unsaturated Thickness', label: 'Unsaturated thickness', unit: 'ft' },
    ],
  },
  {
    title: 'Water levels',
    fields: [
      { k: 'Water Levels to Use for Predictions', label: 'Prediction basis', type: 'select', options: WL_METHOD },
      { k: 'Predevelopment Water Level (feet MSL)', label: 'Predevelopment', unit: 'ft MSL' },
      { k: 'Current Water Level (feet MSL)', label: 'Current', unit: 'ft MSL' },
      { k: 'Preconsolidation (deepest) Water Level (feet MSL)', label: 'Preconsolidation (deepest)', unit: 'ft MSL' },
      { k: 'Base Water Level (feet MSL)', label: 'Base', unit: 'ft MSL' },
      { k: 'Future Water Level (feet MSL)', label: 'Future', unit: 'ft MSL' },
      { k: 'Water Level Trend', label: 'Trend', unit: 'ft/yr' },
    ],
  },
  {
    title: 'Aquifer properties',
    fields: [
      { k: 'Predominant Aquifer Lithology', label: 'Lithology', type: 'select', options: LITHOLOGY },
      { k: 'Aquifer Porosity', label: 'Aquifer porosity', unit: '%' },
      { k: 'Aquifer Storage Coefficient', label: 'Storage coefficient' },
      { k: 'Predominant Aquifer Clay Type', label: 'Clay type', type: 'select', options: CLAY_TYPE },
      { k: 'Aquifer Clay Porosity', label: 'Clay porosity', unit: '%' },
      { k: 'Groundwater Temperature', label: 'Groundwater temp', unit: '°C' },
      { k: 'Groundwater Total Dissolved Solids (TDS)', label: 'Groundwater TDS', unit: 'mg/L' },
    ],
  },
  {
    title: 'Evaluation period',
    fields: [
      { k: 'Beginning Year for Subsidence Evaluation', label: 'Start year' },
      { k: 'Ending Year for Subsidence Evaluation', label: 'End year' },
    ],
  },
]

const ADVANCED_FIELDS = [
  { k: 'Minimum Aquifer Compressibility', label: 'Min aquifer compressibility', unit: 'psi⁻¹' },
  { k: 'Maximum Aquifer Compressibility', label: 'Max aquifer compressibility', unit: 'psi⁻¹' },
  { k: 'Minimum Clay Compressibility', label: 'Min clay compressibility', unit: 'psi⁻¹' },
  { k: 'Maximum Clay Compressibility', label: 'Max clay compressibility', unit: 'psi⁻¹' },
]

const FACTOR_LABELS = {
  lithology_risk: 'Lithology',
  clay_thickness_risk: 'Clay thickness',
  clay_compressibility_risk: 'Clay compressibility',
  preconsolidation_risk: 'Preconsolidation',
  water_level_trend_risk: 'Water-level trend',
  future_decline_risk: 'Future decline',
}

// Subsidence min–max band over the evaluation years, drawn as a tiny inline SVG.
function AnnualChart({ annual }) {
  const rows = (annual || []).filter((a) => a.subsidence_max_ft != null)
  if (rows.length < 2) return null
  const W = 380
  const H = 130
  const PAD = 6
  const maxV = Math.max(...rows.map((a) => a.subsidence_max_ft || 0), 0.001)
  const x = (i) => PAD + (i / (rows.length - 1)) * (W - 2 * PAD)
  const y = (v) => H - PAD - (v / maxV) * (H - 2 * PAD)

  const band = [
    ...rows.map((a, i) => `${x(i)},${y(a.subsidence_max_ft || 0)}`),
    ...rows.map((a) => a).reverse().map((a, j) => {
      const i = rows.length - 1 - j
      return `${x(i)},${y(rows[i].subsidence_min_ft || 0)}`
    }),
  ].join(' ')
  const maxLine = rows.map((a, i) => `${x(i)},${y(a.subsidence_max_ft || 0)}`).join(' ')

  return (
    <div className="fc-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Projected subsidence over time">
        <polygon points={band} fill="var(--tacc-accent)" opacity="0.18" />
        <polyline points={maxLine} fill="none" stroke="var(--tacc-primary-dark)" strokeWidth="2" />
      </svg>
      <div className="fc-chart-axis">
        <span>{rows[0].year}</span>
        <span>cumulative subsidence (ft) — min–max band</span>
        <span>{rows[rows.length - 1].year}</span>
      </div>
    </div>
  )
}

export function ForecastTool() {
  const [form, setForm] = useState(null) // keyed by visible-label
  const [loadingTpl, setLoadingTpl] = useState(true)
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    getForecastTemplate()
      .then((tpl) => { if (!cancelled) { setForm(tpl); setLoadingTpl(false) } })
      .catch((err) => { if (!cancelled) { setError(err.message); setLoadingTpl(false) } })
    return () => { cancelled = true }
  }, [])

  const setField = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function resetDefaults() {
    setResult(null)
    setError('')
    setLoadingTpl(true)
    try {
      setForm(await getForecastTemplate())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingTpl(false)
    }
  }

  async function estimate(event) {
    event.preventDefault()
    setRunning(true)
    setError('')
    try {
      setResult(await runForecast(form))
    } catch (err) {
      setError(err.message)
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  const renderField = ({ k, label, unit, type, options }) => (
    <label className="fc-field" key={k}>
      <span className="fc-field-label">
        {label}{unit ? <span className="fc-unit"> ({unit})</span> : null}
      </span>
      {type === 'select' ? (
        <select value={form?.[k] ?? ''} onChange={setField(k)}>
          {options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      ) : (
        <input type="number" step="any" value={form?.[k] ?? ''} onChange={setField(k)} />
      )}
    </label>
  )

  const proj = result?.projection
  const factors = result?.risk_factors || {}

  return (
    <main className="subside-main">
      <div className="subside-container">
        <div className="page-heading">
          <h1>Subsidence forecast</h1>
          <p>
            Estimate <strong>potential</strong> future subsidence and a 0–10 risk
            score from aquifer and water-level inputs. This is a screening
            estimate, not a site-specific prediction.
          </p>
        </div>

        <div className="fc-note">
          Inputs are prefilled with a representative Texas aquifer scenario.
          Location-based prefill from TWDB spatial layers is coming — for now,
          adjust the values you know and re-estimate.
        </div>

        {loadingTpl && !form ? (
          <div className="fc-loading">Loading default scenario…</div>
        ) : (
          <div className="fc-layout">
            <form className="fc-form" onSubmit={estimate}>
              {GROUPS.map((group) => (
                <fieldset className="fc-group" key={group.title}>
                  <legend>{group.title}</legend>
                  <div className="fc-grid">{group.fields.map(renderField)}</div>
                </fieldset>
              ))}

              <details className="fc-advanced">
                <summary>Advanced — aquifer & clay compressibility</summary>
                <div className="fc-grid">{ADVANCED_FIELDS.map(renderField)}</div>
              </details>

              <div className="fc-actions">
                <button type="submit" className="fc-submit" disabled={running}>
                  {running ? 'Estimating…' : 'Estimate risk'}
                </button>
                <button type="button" className="sap-link" onClick={resetDefaults} disabled={running}>
                  reset to defaults
                </button>
              </div>
              {error ? <div className="sap-error">{error}</div> : null}
            </form>

            <aside className="fc-result">
              {result ? (
                <>
                  <div className="fc-result-head">Potential subsidence risk</div>
                  <RiskGauge score={result.risk_score} />
                  {proj?.final_subsidence_max_ft != null ? (
                    <div className="fc-projection">
                      <strong>
                        {proj.final_subsidence_min_ft?.toFixed(1)}–{proj.final_subsidence_max_ft.toFixed(1)} ft
                      </strong> of cumulative subsidence projected by {proj.final_year}
                      <div className="fc-projection-sub">
                        ({proj.final_drawdown_ft?.toFixed(0)} ft of water-level drawdown from {proj.start_year})
                      </div>
                    </div>
                  ) : null}

                  <AnnualChart annual={result.annual} />

                  <div className="fc-factors">
                    <div className="fc-factors-head">Risk drivers (1–5)</div>
                    {Object.entries(FACTOR_LABELS).map(([key, label]) => (
                      <div className="fc-factor" key={key}>
                        <span>{label}</span>
                        <span className="fc-factor-val">{factors[key] ?? '—'}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="fc-result-empty">
                  <RiskGauge score={null} pending />
                  <p>Fill in what you know and select <strong>Estimate risk</strong> to see a projected 0–10 subsidence risk and a multi-decade subsidence curve.</p>
                </div>
              )}
            </aside>
          </div>
        )}
      </div>
    </main>
  )
}
