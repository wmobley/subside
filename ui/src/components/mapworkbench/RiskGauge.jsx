// Compact 0–10 risk readout used by the Risk Explorer's "Potential subsidence"
// card. Designed to map directly onto the screening model's
// `weighted_risk_0_to_10_approx` output (subsidence_pandas), but takes a plain
// score so it can render a placeholder before the forecast engine is wired up.
//
// Fits the narrow on-map control: a horizontal band (low→severe) with a marker
// at the score, plus a worded band label. Pass `score={null}` for the
// "forecast not run yet" state.

// Five qualitative bands across the 0–10 screening scale.
const BANDS = [
  { max: 2, label: 'Very low', color: '#16a34a' },
  { max: 4, label: 'Low', color: '#84cc16' },
  { max: 6, label: 'Moderate', color: '#f59e0b' },
  { max: 8, label: 'High', color: '#ea580c' },
  { max: 10.01, label: 'Severe', color: '#dc2626' },
]

export function riskBand(score) {
  if (score == null || Number.isNaN(score)) return null
  return BANDS.find((b) => score < b.max) || BANDS[BANDS.length - 1]
}

export function RiskGauge({ score = null, pending = false }) {
  const band = riskBand(score)
  const pct = score == null ? 0 : Math.max(0, Math.min(100, (score / 10) * 100))

  return (
    <div className={`risk-gauge${pending ? ' risk-gauge--pending' : ''}`}>
      <div className="risk-gauge-head">
        <span className="risk-gauge-score">
          {score == null ? '—' : score.toFixed(1)}
          <span className="risk-gauge-denom">/10</span>
        </span>
        <span className="risk-gauge-band" style={band ? { color: band.color } : undefined}>
          {pending ? 'not run yet' : band ? band.label : 'no estimate'}
        </span>
      </div>
      <div className="risk-gauge-track">
        {score != null ? (
          <span
            className="risk-gauge-marker"
            style={{ left: `${pct}%`, borderColor: band?.color }}
          />
        ) : null}
      </div>
      <div className="risk-gauge-scale">
        <span>Low</span>
        <span>Severe</span>
      </div>
    </div>
  )
}
