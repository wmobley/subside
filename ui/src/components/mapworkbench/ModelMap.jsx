import { useState } from 'react'
import { MapContainer, TileLayer, useMapEvents } from 'react-leaflet'
import { SubsideAnalysis } from './SubsideAnalysis'
import { SubsideLayers } from './SubsideLayers'
import { StacResults } from './StacResults'

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
  // The analysis panel lives OUTSIDE the map (a scrollable column to its left);
  // SubsideAnalysis portals its UI into this host while keeping its map layers
  // inside the MapContainer. Callback ref so the portal target is available.
  const [panelHost, setPanelHost] = useState(null)
  // Previous-runs list lives inside the Layers panel: SubsideLayers renders a
  // mount point, StacResults portals its list/toggle into it.
  const [prevRunsHost, setPrevRunsHost] = useState(null)
  return (
    <div className="map-canvas">
      <div className="map-stage">
        <div className="map-side-panel" ref={setPanelHost} />
        <div className="map-area">
          <MapContainer center={[mapData.center.lat, mapData.center.lon]} zoom={zoom} className="leaflet-map" scrollWheelZoom>
            <MapEventsBridge onZoomChange={setZoom} />
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <SubsideLayers onPickFrame={setPickedFrame} prevRunsHostRef={setPrevRunsHost} />
            <SubsideAnalysis picked={pickedFrame} panelHost={panelHost} />
            {/* Previous-runs layers on the map + list portalled into the Layers panel
                (no-op unless VITE_STAC_API_BASE set) */}
            <StacResults panelHost={prevRunsHost} />
          </MapContainer>
        </div>
      </div>
    </div>
  )
}
