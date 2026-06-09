// Pure AOI geometry helpers for the analysis panel: bbox<->Leaflet bounds,
// GeoJSON normalization, an envelope over a FeatureCollection, and AOI
// size/complexity warnings. No React, no I/O — just data.

export function bboxToBounds(b) {
  return [[b[1], b[0]], [b[3], b[2]]] // [[s,w],[n,e]] for Leaflet
}

// Wrap a bare geometry / Feature into a FeatureCollection (what the run API wants).
export function toFeatureCollection(gj) {
  if (!gj) return null
  if (gj.type === 'FeatureCollection') return gj
  if (gj.type === 'Feature') return { type: 'FeatureCollection', features: [gj] }
  return { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: gj }] }
}

// [w, s, e, n] envelope over any GeoJSON FeatureCollection's coordinates.
export function geometryBbox(fc) {
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
export function aoiStats(fc) {
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
