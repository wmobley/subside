import { useState } from 'react'
import { MapContainer, TileLayer, useMapEvents } from 'react-leaflet'
import { AddressSearch } from './AddressSearch'
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
  // The analysis panel lives OUTSIDE the map (a scrollable column to its left);
  // SubsideAnalysis portals its UI into this host while keeping its map layers
  // inside the MapContainer. Callback ref so the portal target is available.
  const [panelHost, setPanelHost] = useState(null)
  // Previous-runs list lives inside the Layers panel: SubsideLayers renders a
  // mount point, StacResults portals its list/toggle into it.
  const [prevRunsHost, setPrevRunsHost] = useState(null)
  // STAC previous-run rasters are siblings of the analysis panel. Lift requests
  // here so a public image's bbox can become the next analysis AOI.
  const [analysisAoiRequest, setAnalysisAoiRequest] = useState(null)
  // Velocity-reference coordination between the analysis panel (which knows the
  // chosen outcome + AOI) and the Layers panel (which renders the GNSS marks):
  //  - `wantsReference` (velocity outcome + an AOI) auto-shows the reference-
  //    candidate layers (e.g. stable GNSS marks) so the user can pick one;
  //  - `referencePoint` is the mark the user clicked, fed back to the analysis
  //    panel as the run's reference coordinate. The point is just lat/lon, so the
  //    workflow stays independent of which dataset surfaced it.
  const [wantsReference, setWantsReference] = useState(false)
  const [referencePoint, setReferencePoint] = useState(null)
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
            <AddressSearch />
            <SubsideLayers
              prevRunsHostRef={setPrevRunsHost}
              autoShowReference={wantsReference}
              onPickReference={setReferencePoint}
            />
            <SubsideAnalysis
              panelHost={panelHost}
              analysisAoiRequest={analysisAoiRequest}
              onWantsReferenceChange={setWantsReference}
              referencePoint={referencePoint}
              onClearReferencePoint={() => setReferencePoint(null)}
            />
            {/* Previous-runs layers on the map + list portalled into the Layers panel
                (no-op unless VITE_STAC_API_BASE set) */}
            <StacResults panelHost={prevRunsHost} onUseBboxForAnalysis={setAnalysisAoiRequest} />
          </MapContainer>
        </div>
      </div>
    </div>
  )
}
