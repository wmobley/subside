import { useEffect, useRef, useState } from 'react'
import { MapContainer, Rectangle, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'

const TEXAS_CENTER = [31.1, -99.2]
const TEXAS_BOUNDS = [
  [25.4, -107.4],
  [37.2, -93.0],
]

function bboxToBounds(bbox) {
  return [
    [bbox[1], bbox[0]],
    [bbox[3], bbox[2]],
  ]
}

function normalizeBbox(start, end) {
  return [
    Math.min(start.lng, end.lng),
    Math.min(start.lat, end.lat),
    Math.max(start.lng, end.lng),
    Math.max(start.lat, end.lat),
  ]
}

function isValidBbox(bbox) {
  return Math.abs(bbox[2] - bbox[0]) > 0.01 && Math.abs(bbox[3] - bbox[1]) > 0.01
}

function SpatialDrawEvents({ isDrawingEnabled, onDraw, onPreview, onDrawComplete }) {
  const startRef = useRef(null)
  const map = useMapEvents({
    mousedown(event) {
      if (!isDrawingEnabled) return
      startRef.current = event.latlng
      onPreview(null)
      map.dragging.disable()
      map.getContainer().classList.add('is-drawing')
    },
    mousemove(event) {
      if (!isDrawingEnabled || !startRef.current) return
      const bbox = normalizeBbox(startRef.current, event.latlng)
      if (isValidBbox(bbox)) onPreview(bbox)
    },
    mouseup(event) {
      if (!isDrawingEnabled || !startRef.current) return
      const bbox = normalizeBbox(startRef.current, event.latlng)
      startRef.current = null
      onPreview(null)
      map.dragging.enable()
      map.getContainer().classList.remove('is-drawing')
      if (isValidBbox(bbox)) {
        onDraw(bbox)
        onDrawComplete()
      }
    },
    mouseout() {
      if (!startRef.current) return
      startRef.current = null
      onPreview(null)
      map.dragging.enable()
      map.getContainer().classList.remove('is-drawing')
    },
  })
  return null
}

function SpatialMapResize({ bbox }) {
  const map = useMap()

  useEffect(() => {
    const container = map.getContainer()
    const invalidate = () => map.invalidateSize({ pan: false })
    const resizeObserver = new ResizeObserver(invalidate)
    resizeObserver.observe(container)
    const timer = window.setTimeout(() => {
      invalidate()
      map.fitBounds(bbox ? bboxToBounds(bbox) : TEXAS_BOUNDS, { padding: [18, 18], animate: false })
    }, 80)

    return () => {
      window.clearTimeout(timer)
      resizeObserver.disconnect()
    }
  }, [map, bbox])

  return null
}

export function SpatialFilterMap({ bbox, extentLabel, onBboxChange, onBboxClear }) {
  const [previewBbox, setPreviewBbox] = useState(null)
  const [isOpen, setIsOpen] = useState(false)
  const [isDrawingEnabled, setIsDrawingEnabled] = useState(false)
  const displayBbox = previewBbox || bbox
  const displayLabel = previewBbox ? 'Drawing extent' : extentLabel

  useEffect(() => {
    if (bbox && extentLabel) setIsOpen(true)
  }, [bbox, extentLabel])

  return (
    <div className="spatial-map-panel">
      <div className="spatial-map-header">
        <label>Map extent</label>
        <div className="spatial-map-actions">
          <button className="portal-btn portal-btn-outline portal-btn-sm" type="button" onClick={() => setIsOpen((current) => !current)}>
            {isOpen ? 'Hide map' : 'Show map'}
          </button>
          <button className="portal-btn portal-btn-outline portal-btn-sm" type="button" onClick={onBboxClear}>
            Clear extent
          </button>
        </div>
      </div>
      {isOpen ? (
        <div className={`ckan-spatial-map ${isDrawingEnabled ? 'is-draw-tool-active' : ''}`}>
          <button
            className={`draw-bbox-button ${isDrawingEnabled ? 'active' : ''}`}
            type="button"
            aria-label="Draw bounding box"
            title="Draw bounding box"
            onClick={() => setIsDrawingEnabled((current) => !current)}
          >
            <span aria-hidden="true" />
          </button>
          <MapContainer
            center={TEXAS_CENTER}
            zoom={5}
            minZoom={4}
            maxBounds={TEXAS_BOUNDS}
            maxBoundsViscosity={0.8}
            className="ckan-spatial-leaflet"
            scrollWheelZoom={false}
          >
            <SpatialMapResize bbox={bbox} />
            <SpatialDrawEvents
              isDrawingEnabled={isDrawingEnabled}
              onDraw={onBboxChange}
              onPreview={setPreviewBbox}
              onDrawComplete={() => setIsDrawingEnabled(false)}
            />
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {displayBbox ? (
              <Rectangle
                bounds={bboxToBounds(displayBbox)}
                pathOptions={{
                  color: '#005f86',
                  fillColor: '#00a9b7',
                  fillOpacity: previewBbox ? 0.18 : 0.12,
                  weight: 2,
                }}
              >
                {displayLabel ? (
                  <Tooltip className="bbox-region-label" direction="center" opacity={1} permanent>
                    {displayLabel}
                  </Tooltip>
                ) : null}
              </Rectangle>
            ) : null}
          </MapContainer>
        </div>
      ) : (
        <div className="spatial-map-summary">
          {bbox ? `${extentLabel || 'Extent'}: ${bbox.map((value) => value.toFixed(2)).join(', ')}` : 'No map extent set.'}
        </div>
      )}
    </div>
  )
}
