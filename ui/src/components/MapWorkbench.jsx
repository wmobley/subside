import { ModelMap } from './mapworkbench/ModelMap'

// SUBSIDE Risk Explorer: a full-width Leaflet map with the registered vector
// layers, OPERA availability shading, and the click-a-frame -> run-on-TACC
// panel (all rendered as on-map controls inside ModelMap).
export function MapWorkbench({ mapData, zoom, setZoom }) {
  return (
    <section className="map-section" id="map">
      <div className="map-header">
        <div>
          <h2>Risk Explorer</h2>
          <p>Pick an area on the map to see its subsidence risk — observed ground movement now, with a forecast on the Forecast tab. Shaded frames have satellite data available.</p>
        </div>
      </div>

      <div className="map-workbench map-workbench--full">
        <ModelMap mapData={mapData} zoom={zoom} setZoom={setZoom} />
      </div>
    </section>
  )
}
