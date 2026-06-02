import { useState } from 'react'
import { MapContainer, TileLayer, useMapEvents } from 'react-leaflet'
import { SubsideAnalysis } from './SubsideAnalysis'
import { SubsideLayers } from './SubsideLayers'

function MapEventsBridge({ onZoomChange }) {
  useMapEvents({
    zoomend(event) {
      onZoomChange(event.target.getZoom())
    },
  })
  return null
}

export function ModelMap({ mapData, zoom, setZoom }) {
  // Frame picked on the availability layer -> becomes the analysis AOI + dates.
  const [pickedFrame, setPickedFrame] = useState(null)
  return (
    <div className="map-canvas">
      <MapContainer center={[mapData.center.lat, mapData.center.lon]} zoom={zoom} className="leaflet-map" scrollWheelZoom>
        <MapEventsBridge onZoomChange={setZoom} />
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <SubsideLayers onPickFrame={setPickedFrame} />
        <SubsideAnalysis picked={pickedFrame} />
      </MapContainer>
    </div>
  )
}
