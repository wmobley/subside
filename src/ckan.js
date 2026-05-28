const CKAN_ORIGIN = 'https://ckan.tacc.utexas.edu'
const CKAN_PROXY_BASE = '/ckan'
const SUBSIDE_ORG = 'twdb-subside'

export const REGION_PRESETS = [
  { value: '', label: 'All regions', bbox: null },
  { value: 'texas', label: 'Texas', bbox: [-106.7, 25.8, -93.5, 36.6] },
  { value: 'gulf-coast', label: 'Gulf Coast', bbox: [-98.4, 25.7, -93.4, 30.8] },
  { value: 'houston-galveston', label: 'Houston-Galveston', bbox: [-96.4, 28.8, -94.3, 30.7] },
  { value: 'central-texas', label: 'Central Texas', bbox: [-99.3, 29.1, -96.5, 31.5] },
  { value: 'west-texas', label: 'West Texas', bbox: [-106.7, 29.0, -101.0, 33.5] },
  { value: 'custom', label: 'Custom bounding box', bbox: null },
]

export async function fetchSubsideDatasets() {
  const params = new URLSearchParams({
    fq: `organization:${SUBSIDE_ORG}`,
    rows: '100',
    sort: 'metadata_modified desc',
  })
  const payload = await fetchCkanJson(`/api/3/action/package_search?${params.toString()}`)
  if (!payload.success) throw new Error(payload.error?.message || 'CKAN dataset search failed')
  return {
    count: payload.result?.count || 0,
    datasets: (payload.result?.results || []).map(normalizeDataset),
  }
}

async function fetchCkanJson(path) {
  const bases = import.meta.env.DEV ? [CKAN_ORIGIN, CKAN_PROXY_BASE] : [CKAN_ORIGIN]
  let lastError = null
  for (const base of bases) {
    try {
      const response = await fetch(`${base}${path}`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error?.message || 'CKAN request failed')
      return payload
    } catch (error) {
      lastError = error
    }
  }
  throw lastError || new Error('CKAN request failed')
}

export function filterDatasets(datasets, filters) {
  const queryTerms = filters.query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const bbox = getActiveBbox(filters)
  return datasets.filter((dataset) => {
    if (queryTerms.length && !queryTerms.every((term) => dataset.searchText.includes(term))) return false
    if (filters.format && !dataset.formats.includes(filters.format)) return false
    if (filters.tag && !dataset.tags.includes(filters.tag)) return false
    if (bbox && (!dataset.bbox || !bboxesIntersect(dataset.bbox, bbox))) return false
    if (filters.requireSpatial && !dataset.bbox) return false
    return true
  })
}

export function getFilterOptions(datasets) {
  return {
    formats: uniqueSorted(datasets.flatMap((dataset) => dataset.formats)),
    tags: uniqueSorted(datasets.flatMap((dataset) => dataset.tags)),
  }
}

export function getActiveBbox(filters) {
  if (filters.region && filters.region !== 'custom') {
    return REGION_PRESETS.find((preset) => preset.value === filters.region)?.bbox || null
  }
  if (filters.region !== 'custom') return null
  const values = [filters.minLon, filters.minLat, filters.maxLon, filters.maxLat].map(Number)
  if (values.some((value) => Number.isNaN(value))) return null
  if (values[0] >= values[2] || values[1] >= values[3]) return null
  return values
}

function normalizeDataset(dataset) {
  const resources = dataset.resources || []
  const tags = (dataset.tags || []).map((tag) => tag.name).filter(Boolean)
  const formats = resources.map((resource) => resource.format || resource.mimetype).filter(Boolean)
  const bbox = getSpatialBbox(dataset)
  return {
    id: dataset.id,
    name: dataset.name,
    title: dataset.title || dataset.name,
    notes: dataset.notes || '',
    url: `${CKAN_ORIGIN}/dataset/${dataset.name}`,
    metadataModified: dataset.metadata_modified,
    license: dataset.license_title || 'License not specified',
    resourceCount: resources.length,
    tags: uniqueSorted(tags.map((tag) => tag.toLowerCase())),
    formats: uniqueSorted(formats.map((format) => format.toUpperCase())),
    bbox,
    searchText: [
      dataset.title,
      dataset.name,
      dataset.notes,
      tags.join(' '),
      resources.map((resource) => `${resource.name || ''} ${resource.description || ''} ${resource.format || ''}`).join(' '),
    ]
      .join(' ')
      .toLowerCase(),
  }
}

function getSpatialBbox(dataset) {
  const rawSpatial = dataset.spatial || dataset.extras?.find?.((extra) => extra.key === 'spatial')?.value
  if (!rawSpatial) return null
  const spatial = parseMaybeJson(rawSpatial)
  if (!spatial) return null
  if (Array.isArray(spatial.bbox) && spatial.bbox.length >= 4) return spatial.bbox.slice(0, 4).map(Number)
  return geojsonBbox(spatial)
}

function parseMaybeJson(value) {
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function geojsonBbox(geojson) {
  const points = []
  collectCoordinates(geojson, points)
  if (!points.length) return null
  return points.reduce(
    (bbox, point) => [
      Math.min(bbox[0], point[0]),
      Math.min(bbox[1], point[1]),
      Math.max(bbox[2], point[0]),
      Math.max(bbox[3], point[1]),
    ],
    [Infinity, Infinity, -Infinity, -Infinity],
  )
}

function collectCoordinates(node, points) {
  if (!node) return
  if (node.type === 'FeatureCollection') {
    node.features?.forEach((feature) => collectCoordinates(feature, points))
    return
  }
  if (node.type === 'Feature') {
    collectCoordinates(node.geometry, points)
    return
  }
  if (node.type && node.coordinates) {
    collectCoordinateArray(node.coordinates, points)
  }
}

function collectCoordinateArray(value, points) {
  if (!Array.isArray(value)) return
  if (typeof value[0] === 'number' && typeof value[1] === 'number') {
    points.push(value)
    return
  }
  value.forEach((item) => collectCoordinateArray(item, points))
}

function bboxesIntersect(a, b) {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]
}

function uniqueSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b))
}
