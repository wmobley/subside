import { CircleMarker, MapContainer, Popup, TileLayer, useMapEvents } from 'react-leaflet'
import { cellColor, cellRadius } from '../../modeling'

function MapEventsBridge({ onZoomChange }) {
  useMapEvents({
    zoomend(event) {
      onZoomChange(event.target.getZoom())
    },
  })
  return null
}

export function ModelMap({ mapData, zoom, setZoom, selectedSet, colorBy, toggleSelected }) {
  return (
    <div className="map-canvas">
      <MapContainer center={[mapData.center.lat, mapData.center.lon]} zoom={zoom} className="leaflet-map" scrollWheelZoom>
        <MapEventsBridge onZoomChange={setZoom} />
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {mapData.cells.map((cell) => {
          const selected = selectedSet.has(cell.cellId)
          return (
            <CircleMarker
              key={cell.cellId}
              center={[cell.lat, cell.lon]}
              radius={cellRadius(cell, selected)}
              pathOptions={{
                color: selected ? '#111827' : cellColor(cell, colorBy),
                fillColor: cellColor(cell, colorBy),
                fillOpacity: selected ? 0.95 : 0.7,
                weight: selected ? 3 : 1,
              }}
              eventHandlers={{ click: () => toggleSelected(cell.cellId) }}
            >
              <Popup>
                <strong>CELL_ID {cell.cellId}</strong><br />
                ROW {cell.row} COL {cell.col}<br />
                Flux {cell.flux}<br />
                GCD {cell.gcd}<br />
                PGMA {cell.pgma}
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
    </div>
  )
}
