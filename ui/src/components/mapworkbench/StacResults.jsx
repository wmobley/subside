// Previous runs: searches the stac-platform API by viewport, draws each already-
// published run's footprint on the map (so users can see what's already been
// analyzed before launching a new run), lists them, and renders the selected
// run's COG. Renders nothing when VITE_STAC_API_BASE is unset.
import { useEffect, useState } from 'react'
import { GeoJSON, ImageOverlay, useMap, useMapEvents } from 'react-leaflet'

import { itemLayers, itemMeta, overlayHref, searchItems, stacEnabled } from '../../stacApi'
import { StacCogLayer } from './StacCogLayer'

// Cap how many actual-image layers we auto-render per viewport so a dense area
// doesn't fire too many loads at once. COGs now stream via range requests
// (StacCogLayer reads only the overview/tiles in view), so the cap is mostly
// about bounding concurrent header fetches, not whole-file downloads. Footprints
// mark any runs beyond the cap.
const MAX_OVERLAYS = 24
const MAX_COGS = 24

function bboxToBounds(b) {
  return [[b[1], b[0]], [b[3], b[2]]] // [[s,w],[n,e]] for Leaflet
}

function hasBbox(item) {
  return Array.isArray(item.bbox) && item.bbox.length === 4
}

function itemLabel(item) {
  const p = item.properties || {}
  const when = p.start_datetime
    ? `${p.start_datetime.slice(0, 10)}…${(p.end_datetime || '').slice(0, 10)}`
    : (p.datetime || '').slice(0, 10)
  return `${item.id}${when ? ` · ${when}` : ''}`
}

// One FeatureCollection of all in-view run footprints, for a single GeoJSON
// layer. Properties carry the id so styling can emphasize the selected run.
function footprintCollection(items) {
  return {
    type: 'FeatureCollection',
    features: items
      .filter((it) => it.geometry)
      .map((it) => ({ type: 'Feature', id: it.id, properties: { id: it.id }, geometry: it.geometry })),
  }
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
  useEffect(refresh, [map])

  if (!stacEnabled()) return null

  const selectedItem = items.find((it) => it.id === selected)
  // Render the item's first COG layer. Use itemLayers (not cogHref) so werc
  // items, whose COGs are keyed `cumulative`/`velocity` rather than `cog`, render.
  const layer = selectedItem ? itemLayers(selectedItem).find((l) => l.type === 'cog') : null
  const meta = selectedItem ? itemMeta(selectedItem) : null

  // Footprints are clickable: clicking one selects that run and renders its full
  // COG/overlay (below), so you can pull up a previous result by clicking it on
  // the map — no list or AOI buttons needed.
  const footprintStyle = (feature) => {
    const isSel = feature.properties?.id === selected
    return {
      color: isSel ? '#005f86' : '#8a6d3b',
      weight: isSel ? 2.5 : 1.5,
      fillColor: isSel ? '#00a9b7' : '#d9a441',
      fillOpacity: isSel ? 0.12 : 0.06,
      dashArray: isSel ? null : '4 3',
    }
  }
  // Toggle selection on click; a sticky tooltip hints it's clickable.
  const onEachFootprint = (feature, lyr) => {
    const id = feature.properties?.id
    lyr.on('click', () => setSelected((cur) => (cur === id ? null : id)))
    lyr.bindTooltip('Click to view this run', { sticky: true })
  }
  const footprints = footprintCollection(items)
  // Re-mount the layer when the in-view set or the selection changes so styles
  // refresh (small N: searchItems caps at 50).
  const footprintsKey = `${footprints.features.map((f) => f.id).join(',')}|${selected || ''}`

  // Actual published imagery for in-view runs, so users see the real result, not
  // just an outline. Skip the selected run (it renders below at full opacity).
  // Prefer the cheap overlay PNG (h2i); otherwise render the run's COG (werc
  // cumulative/velocity tifs) directly — they're cloud-optimized for exactly
  // this. Keyed by item id so panning doesn't re-fetch runs that stay in view.
  const others = items.filter((it) => it.id !== selected)
  const pngRuns = others.filter((it) => overlayHref(it) && hasBbox(it)).slice(0, MAX_OVERLAYS)
  const pngIds = new Set(pngRuns.map((it) => it.id))
  const cogRuns = others
    .filter((it) => !pngIds.has(it.id))
    .map((it) => ({ it, cog: itemLayers(it).find((l) => l.type === 'cog') }))
    .filter((x) => x.cog)
    .slice(0, MAX_COGS)

  return (
    <>
      {footprints.features.length > 0 && (
        <GeoJSON key={footprintsKey} data={footprints} style={footprintStyle} onEachFeature={onEachFootprint} />
      )}
      {pngRuns.map((it) => (
        <ImageOverlay key={it.id} url={overlayHref(it)} bounds={bboxToBounds(it.bbox)} opacity={0.55} interactive={false} />
      ))}
      {cogRuns.map(({ it, cog }) => (
        <StacCogLayer key={it.id} href={cog.href} range={cog.range} opacity={0.6} fit={false} />
      ))}
      {layer && (
        <StacCogLayer
          href={layer.href}
          range={layer.range}
          onError={(m) => setError(m)}
        />
      )}
      <div className="stac-results leaflet-control" style={panelStyle}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          Previous runs in view ({items.length})
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
              {it.id === selected && (
                <div style={detailStyle}>
                  {layer ? (
                    <div>
                      {layer.label}
                      {layer.range ? ` · ${Number(layer.range.vmin).toPrecision(3)}–${Number(layer.range.vmax).toPrecision(3)}${layer.unit ? ` ${layer.unit}` : ''}` : ''}
                    </div>
                  ) : <div>No raster asset.</div>}
                  {meta?.productCount != null && <div>{meta.productCount} OPERA products</div>}
                  {meta?.frameIds?.length ? <div>Frame{meta.frameIds.length > 1 ? 's' : ''} {meta.frameIds.join(', ')}</div> : null}
                </div>
              )}
            </li>
          ))}
          {!items.length && !error && (
            <li style={{ fontSize: 12, color: '#666' }}>No previous runs here — this area hasn’t been analyzed yet.</li>
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
const detailStyle = {
  padding: '2px 8px 6px',
  fontSize: 11,
  color: '#555',
  lineHeight: 1.4,
}
