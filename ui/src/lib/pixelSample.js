import proj4 from 'proj4'

// SUBSIDE's OPERA DISP displacement/velocity COGs are delivered in UTM, not
// EPSG:4326 (confirmed via gdalinfo against real published assets — e.g.
// EPSG:32614/32615 depending on the run's location). EPSG:326xx/327xx encode
// the UTM zone directly in the code, so the proj4 string can be built locally
// instead of doing a network EPSG lookup for the only projections these
// rasters actually use.
function utmProjString(epsg) {
  if (epsg >= 32601 && epsg <= 32660) return `+proj=utm +zone=${epsg - 32600} +datum=WGS84 +units=m +no_defs`
  if (epsg >= 32701 && epsg <= 32760) return `+proj=utm +zone=${epsg - 32700} +south +datum=WGS84 +units=m +no_defs`
  return null
}

// Reads the single raw pixel value under (lat, lon) from an already-parsed
// `georaster` (see StacCogLayer). Uses georaster's own windowed getValues() —
// a single-tile range request against the remote COG, not a full-raster
// download — so this stays cheap against the same asset StacCogLayer already
// streams for rendering. Returns null when the point falls outside the
// raster, the CRS isn't one we know how to reproject, or the pixel is nodata.
export async function sampleGeorasterValue(georaster, lat, lon) {
  if (!georaster) return null
  const epsg = georaster.projection
  let x = lon
  let y = lat
  if (epsg && epsg !== 4326) {
    const projStr = utmProjString(epsg)
    if (!projStr) return null
    try {
      [x, y] = proj4('EPSG:4326', projStr, [lon, lat])
    } catch {
      return null
    }
  }
  const col = Math.floor((x - georaster.xmin) / georaster.pixelWidth)
  const row = Math.floor((georaster.ymax - y) / georaster.pixelHeight)
  if (col < 0 || row < 0 || col >= georaster.width || row >= georaster.height) return null
  try {
    const rasters = await georaster.getValues({ left: col, top: row, right: col + 1, bottom: row + 1, width: 1, height: 1 })
    const value = rasters?.[0]?.[0]?.[0]
    if (value == null || Number.isNaN(value) || value === georaster.noDataValue) return null
    return value
  } catch {
    return null
  }
}
