// Address / place search for the map. Keyless geocoding via OpenStreetMap
// Nominatim (same data as the basemap); results are biased toward the current
// viewport and the US. Selecting a result flies the map there and drops a
// temporary marker.
//
// Mounted *inside* a react-leaflet <MapContainer>. The search box is portalled
// into a Leaflet control (top-left, under the zoom buttons) so it tracks the map
// and swallows clicks/scroll like the other on-map controls.
import L from 'leaflet'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CircleMarker, Popup, useMap } from 'react-leaflet'

const NOMINATIM = 'https://nominatim.openstreetmap.org/search'
const MIN_CHARS = 3
const DEBOUNCE_MS = 350

// Query Nominatim. `viewbox` is "minLon,maxLat,maxLon,minLat" to prefer (not
// restrict, bounded=0) results near the current view. `signal` aborts in-flight
// requests when the query changes.
async function geocode(q, viewbox, signal) {
  const params = new URLSearchParams({
    q, format: 'json', limit: '6', addressdetails: '0', countrycodes: 'us',
  })
  if (viewbox) {
    params.set('viewbox', viewbox)
    params.set('bounded', '0')
  }
  const resp = await fetch(`${NOMINATIM}?${params.toString()}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!resp.ok) throw new Error(`Geocoding failed (${resp.status})`)
  return resp.json()
}

function viewboxOf(map) {
  const b = map.getBounds()
  return [b.getWest(), b.getNorth(), b.getEast(), b.getSouth()].map((n) => n.toFixed(5)).join(',')
}

export function AddressSearch({ onSelect }) {
  const map = useMap()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [active, setActive] = useState(-1) // keyboard-highlighted result index
  const [marker, setMarker] = useState(null) // { lat, lon, label }
  const markerRef = useRef(null)

  // Leaflet control container the search box is portalled into.
  const [controlEl] = useState(() => {
    // `leaflet-control` gives it the standard corner margins (sits below the zoom).
    const el = L.DomUtil.create('div', 'address-search leaflet-control')
    L.DomEvent.disableClickPropagation(el)
    L.DomEvent.disableScrollPropagation(el)
    return el
  })

  useEffect(() => {
    const ctrl = L.control({ position: 'topleft' })
    ctrl.onAdd = () => controlEl
    ctrl.addTo(map)
    // addTo() appends after the zoom control; move it to the top of the corner
    // so the search box sits *above* the zoom buttons.
    const corner = controlEl.parentNode
    if (corner && corner.firstChild !== controlEl) corner.insertBefore(controlEl, corner.firstChild)
    return () => ctrl.remove()
  }, [map, controlEl])

  // Close the suggestion list when the user interacts with the map.
  useEffect(() => {
    const close = () => setOpen(false)
    map.on('click dragstart', close)
    return () => map.off('click dragstart', close)
  }, [map])

  // Debounced geocode as the user types.
  useEffect(() => {
    const q = query.trim()
    if (q.length < MIN_CHARS) {
      setResults([])
      setError('')
      setLoading(false)
      return undefined
    }
    const controller = new AbortController()
    setLoading(true)
    const id = setTimeout(() => {
      geocode(q, viewboxOf(map), controller.signal)
        .then((rows) => {
          setResults(rows)
          setActive(rows.length ? 0 : -1)
          setOpen(true)
          setError(rows.length ? '' : 'No matches')
        })
        .catch((err) => {
          if (err.name !== 'AbortError') setError(err.message)
        })
        .finally(() => setLoading(false))
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(id)
      controller.abort()
    }
  }, [query, map])

  // Open the popup whenever a new marker is dropped.
  useEffect(() => {
    if (marker && markerRef.current) markerRef.current.openPopup()
  }, [marker])

  const select = useCallback((r) => {
    if (!r) return
    const lat = Number(r.lat)
    const lon = Number(r.lon)
    const bb = (r.boundingbox || []).map(Number) // [south, north, west, east]
    if (bb.length === 4 && bb.every((n) => Number.isFinite(n))) {
      map.flyToBounds([[bb[0], bb[2]], [bb[1], bb[3]]], { maxZoom: 16, duration: 0.8 })
    } else {
      map.flyTo([lat, lon], 14, { duration: 0.8 })
    }
    setMarker({ lat, lon, label: r.display_name })
    setQuery(r.display_name)
    setResults([])
    setOpen(false)
    onSelect?.({ lat, lon })
  }, [map, onSelect])

  function onKeyDown(e) {
    if (!open || !results.length) {
      if (e.key === 'Enter') e.preventDefault()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i - 1 + results.length) % results.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      select(results[active] || results[0])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  function clear() {
    setQuery('')
    setResults([])
    setError('')
    setOpen(false)
    setMarker(null)
  }

  const box = (
    <div className="as-box">
      <input
        className="as-input"
        type="text"
        value={query}
        placeholder="Search address or place…"
        aria-label="Search address or place"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {query ? (
        <button type="button" className="as-clear" aria-label="Clear search" onClick={clear}>×</button>
      ) : null}
      {loading ? <span className="as-spinner" aria-hidden /> : null}
      {open && (results.length || error) ? (
        <ul className="as-results">
          {results.map((r, i) => (
            <li
              key={`${r.place_id || r.osm_id || i}`}
              className={`as-result${i === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); select(r) }}
            >
              {r.display_name}
            </li>
          ))}
          {!results.length && error ? <li className="as-result as-muted">{error}</li> : null}
        </ul>
      ) : null}
    </div>
  )

  return (
    <>
      {marker ? (
        <CircleMarker
          ref={markerRef}
          center={[marker.lat, marker.lon]}
          radius={8}
          pathOptions={{ color: '#dc2626', weight: 2, fillColor: '#dc2626', fillOpacity: 0.4 }}
        >
          <Popup>{marker.label}</Popup>
        </CircleMarker>
      ) : null}
      {createPortal(box, controlEl)}
    </>
  )
}
