// STAC discovery: searches the stac-platform API by viewport, lists matching
// items, and renders the selected item's COG asset on the map. Renders nothing
// when VITE_STAC_API_BASE is unset (stacEnabled() === false).
import { useEffect, useState } from 'react'
import { useMap, useMapEvents } from 'react-leaflet'

import { cogHref, cogRange, searchItems, stacEnabled } from '../../stacApi'
import { StacCogLayer } from './StacCogLayer'

function itemLabel(item) {
  const p = item.properties || {}
  const when = p.start_datetime
    ? `${p.start_datetime.slice(0, 10)}…${(p.end_datetime || '').slice(0, 10)}`
    : (p.datetime || '').slice(0, 10)
  return `${item.id}${when ? ` · ${when}` : ''}`
}

export function StacResults() {
  const map = useMap()
  const [items, setItems] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => {
    if (!stacEnabled() || !map) return
    searchItems(map.getBounds())
      .then((features) => { setItems(features); setError(null) })
      .catch((err) => setError(err?.message || 'STAC search failed'))
  }

  // Re-search on pan/zoom end.
  useMapEvents({ moveend: refresh, zoomend: refresh })
  useEffect(refresh, [map]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!stacEnabled()) return null

  const selectedItem = items.find((it) => it.id === selected)
  const href = selectedItem && cogHref(selectedItem)

  return (
    <>
      {href && (
        <StacCogLayer
          href={href}
          range={cogRange(selectedItem)}
          onError={(m) => setError(m)}
        />
      )}
      <div className="stac-results leaflet-control" style={panelStyle}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          STAC results ({items.length})
        </div>
        {error && <div style={{ color: '#b00', fontSize: 12 }}>{error}</div>}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 220, overflow: 'auto' }}>
          {items.map((it) => (
            <li key={it.id}>
              <button
                type="button"
                onClick={() => setSelected(it.id === selected ? null : it.id)}
                style={{
                  ...rowStyle,
                  background: it.id === selected ? '#e6f0ff' : 'transparent',
                }}
              >
                {itemLabel(it)}
              </button>
            </li>
          ))}
          {!items.length && !error && (
            <li style={{ fontSize: 12, color: '#666' }}>No items in view.</li>
          )}
        </ul>
      </div>
    </>
  )
}

const panelStyle = {
  position: 'absolute',
  top: 12,
  right: 12,
  zIndex: 1000,
  width: 260,
  padding: '8px 10px',
  background: 'rgba(255,255,255,0.95)',
  borderRadius: 6,
  boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
  font: '13px system-ui, sans-serif',
}
const rowStyle = {
  display: 'block',
  width: '100%',
  textAlign: 'left',
  border: 'none',
  padding: '4px 6px',
  cursor: 'pointer',
  borderRadius: 4,
  font: 'inherit',
}
