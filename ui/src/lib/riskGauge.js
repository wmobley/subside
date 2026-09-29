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
