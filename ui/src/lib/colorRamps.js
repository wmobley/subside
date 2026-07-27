// Shared color ramps for COG rendering (StacCogLayer) AND their matching
// legend gradients (StacResults' RasterLegend, SubsideAnalysis' own legend) —
// one source of truth so the map's colors and the legend describing them can
// never drift apart the way they would with a hardcoded CSS gradient +
// separately-hardcoded JS color stops.
export const VIRIDIS = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e',
  '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725']

// Velocity uses this instead of viridis, both to visually distinguish it from
// Displacement at a glance and per user request.
export const PLASMA = ['#0d0887', '#41049d', '#6a00a8', '#8f0da4', '#b12a90',
  '#cc4778', '#e16462', '#f2844b', '#fca636', '#fcce25', '#f0f921']

export const PALETTES = { viridis: VIRIDIS, plasma: PLASMA }

function hexToRgb(h) {
  const n = parseInt(h.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function rampColor(palette, t) {
  const x = Math.max(0, Math.min(1, t)) * (palette.length - 1)
  const a = Math.floor(x)
  const b = Math.min(a + 1, palette.length - 1)
  const f = x - a
  const ca = hexToRgb(palette[a])
  const cb = hexToRgb(palette[b])
  const c = ca.map((v, i) => Math.round(v + (cb[i] - v) * f))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

export function paletteFor(name) {
  return PALETTES[name] || VIRIDIS
}

export function cssGradient(name) {
  return `linear-gradient(to right, ${paletteFor(name).join(', ')})`
}
