// Human context for a rendered displacement/velocity layer: what the quantity
// is, its units, the time window it was derived over, and the LOS sign
// convention. Shared by SubsideAnalysis.jsx (a run's own results panel) and
// StacResults.jsx (the previous-runs map popup) so this copy stays in one
// place instead of drifting between the two.
export function layerContext(layer, meta) {
  if (!layer) return null
  const d = (s) => (s ? String(s).slice(0, 10) : null)
  const start = d(meta?.start)
  const end = d(meta?.end)
  const window = start ? `${start} → ${end || '—'}` : null
  const ref = meta?.reference
  const reference = ref
    ? `${ref.lat.toFixed(5)}, ${ref.lon.toFixed(5)}${ref.mode ? ` (${ref.mode})` : ''}`
    : null
  const key = layer.key || ''
  if (key === 'velocity' || /velocit/i.test(layer.label || '')) {
    return {
      what: 'Average rate of line-of-sight (LOS) ground motion — the slope of a straight-line fit to each pixel’s displacement time series.',
      unit: layer.unit || 'mm/yr',
      windowLabel: 'Rate fit over',
      window,
      reference,
      sign: 'Negative = moving away from the satellite (subsidence, i.e. sinking faster); positive = moving toward it (uplift, i.e. rising). Measured relative to the static reference point below.',
    }
  }
  if (key === 'cumulative' || key === 'cog' || /cumulative|displacement/i.test(layer.label || '')) {
    return {
      what: 'Total line-of-sight (LOS) ground displacement accumulated across the window, relative to the static reference point.',
      unit: layer.unit || (key === 'cog' ? 'm' : 'mm'),
      windowLabel: 'Accumulated',
      window,
      reference,
      sign: 'Negative = motion away from the satellite (subsidence, i.e. more sinking); positive = motion toward it (uplift, i.e. less sinking).',
    }
  }
  return { what: layer.label, unit: layer.unit || '', windowLabel: 'Window', window, reference, sign: null }
}
