import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, useMap, useMapEvents } from 'react-leaflet'
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

function MapSizeSync() {
  const map = useMap()
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false, debounceMoveend: true }))
    observer.observe(map.getContainer())
    return () => observer.disconnect()
  }, [map])
  return null
}

export function ModelMap({ mapData, zoom, setZoom }) {
  // The analysis panel lives OUTSIDE the map (a scrollable column to its left);
  // SubsideAnalysis portals its UI into this host while keeping its map layers
  // inside the MapContainer. Callback ref so the portal target is available.
  const [panelHost, setPanelHost] = useState(null)
  const [layersHost, setLayersHost] = useState(null)
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
  // An address-search selection is handed to StacResults so it can check
  // whether a currently-rendered Displacement/Velocity pixel exists there and,
  // if so, open the same pixel-value popup a click on it would.
  const [probeLocation, setProbeLocation] = useState(null)
  return (
    <div className="map-canvas">
      <div className="map-stage">
        <div className="map-side-panel" ref={setPanelHost} />
        <div className="map-area">
          <MapContainer
            center={[mapData.center.lat, mapData.center.lon]}
            zoom={zoom}
            className="leaflet-map"
            scrollWheelZoom
          >
            <MapEventsBridge onZoomChange={setZoom} />
            <MapSizeSync />
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <AddressSearch onSelect={setProbeLocation} />
            <SubsideLayers
              panelHost={layersHost}
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
            <StacResults panelHost={prevRunsHost} onUseBboxForAnalysis={setAnalysisAoiRequest} probeLocation={probeLocation} />
          </MapContainer>
        </div>
        <aside className="map-layers-panel" ref={setLayersHost} aria-label="Layers and legends" />
      </div>
    </div>
  )
}
