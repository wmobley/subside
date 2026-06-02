export const EMPTY_FORM = {
  datasetName: '',
  datasetTitle: '',
  outputName: '',
  sourceUrl: '',
  changeSummary: '',
}

export function slugify(value) {
  return value.toLowerCase().trim().replace(/[^a-z0-9._-]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || 'dataset'
}

export function summarizePeriods(periods, options) {
  if (!periods.length) return 'Stress periods: all'
  const labels = periods
    .slice()
    .sort((a, b) => a - b)
    .map((period) => `SP ${period + 1}`)
  if (options.length && periods.length === options.length) return `Stress periods: all (${options.length})`
  return `Stress periods: ${labels.join(', ')}`
}

export function buildSuggestedFields(dataset, controls, state) {
  if (!dataset) return EMPTY_FORM
  const periodSummary = summarizePeriods(state.periods, controls.periodOptions || [])
  const baseName = slugify(state.datasetSuggestion && state.datasetSuggestion !== '__new__' ? state.datasetSuggestion : dataset.name)
  const selectedTag =
    state.colorBy !== 'flux' && state.categoryValue
      ? `${state.colorBy}-${slugify(state.categoryValue)}`
      : `${state.selectedIds.length}-cells`
  const rateTag =
    state.rateMode === 'scale_percent'
      ? `${Math.abs(Number(state.newRate) || 0)}pct-${Number(state.newRate) < 0 ? 'reduction' : 'increase'}`
      : `set-${Number(state.newRate) || 0}`
  const ext = state.fluxSource === 'rch' ? '.rch' : '.wel'
  return {
    datasetName: baseName,
    datasetTitle: dataset.title,
    outputName: `${dataset.name}_${slugify(rateTag)}_${slugify(selectedTag)}${ext}`,
    sourceUrl: dataset.sourceUrl,
    changeSummary: `${periodSummary}; rate mode: ${state.rateMode}; new rate: ${state.newRate}; selected cells: ${state.selectedIds.length}`,
  }
}

export function categoryColor(name) {
  const palette = ['#0f766e', '#b45309', '#7c3aed', '#2563eb', '#be123c', '#4d7c0f']
  let hash = 0
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0
  return palette[hash % palette.length]
}

export function fluxColor(value) {
  if (value < 0) return '#1d4ed8'
  if (value > 0) return '#b91c1c'
  return '#94a3b8'
}

export function cellColor(cell, colorBy) {
  if (colorBy === 'GCD_Name') return categoryColor(cell.gcd)
  if (colorBy === 'PGMA_Name') return categoryColor(cell.pgma)
  return fluxColor(cell.flux)
}

export function cellRadius(cell, selected) {
  const base = Math.min(14, Math.max(4, Math.round(Math.abs(cell.flux) / 25)))
  return selected ? base + 5 : base
}
