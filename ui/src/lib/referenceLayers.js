const ARCGIS = 'https://services1.arcgis.com/7DRakJXKPEhwv0fM/ArcGIS/rest/services/Z_Statewide_gdb/FeatureServer'

const query = (layer) =>
  `${ARCGIS}/${layer}/query?where=1%3D1&outFields=*&outSR=4326`
  + `&maxAllowableOffset=0.002&geometryPrecision=5&f=geojson`

export const REFERENCE_LAYERS = [
  { id: 'major-aquifers', label: 'Major aquifers', kind: 'Major aquifer', url: query(1), color: '#1d4ed8' },
  { id: 'minor-aquifers', label: 'Minor aquifers', kind: 'Minor aquifer', url: query(0), color: '#0d9488' },
]
