// Programmatically renders every registered SUBSIDE layer (GET /api/subside/layers)
// as an MVT vector-tile overlay on the map, plus a viewport-driven availability
// shading for the OPERA frame-footprint layer ("satellite").
//
// Mounted *inside* a react-leaflet <MapContainer>. The toggle/legend panel is
// rendered into a Leaflet control via a React portal so it lives in the map corner.
import L from 'leaflet'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMap } from 'react-leaflet'

import { fetchAvailability, listLayers, tileUrlTemplate } from '../../subsideApi'
import { REFERENCE_LAYERS, ReferenceGeoJSON } from './ReferenceLayers'
import { VectorTileLayer } from './VectorTileLayer'

const AVAILABILITY_LAYER = 'satellite' // the OPERA frame-footprint layer
const PALETTE = ['#2563eb', '#7c3aed', '#0d9488', '#c2410c', '#9333ea', '#0891b2', '#4d7c0f']

// Availability shading buckets, by recency of the latest product.
const AVAIL = {
  loading: { color: '#9ca3af', label: 'loading / out of view' },
  none: { color: '#6b7280', label: 'no products' },
  recent: { color: '#16a34a', label: '< 6 mo' },
  mid: { color: '#f59e0b', label: '6–18 mo' },
  stale: { color: '#dc2626', label: '> 18 mo' },
}

function monthsSince(isoDate, nowMs) {
  if (!isoDate) return Infinity
  return (nowMs - Date.parse(isoDate)) / (1000 * 60 * 60 * 24 * 30.4)
}

function availabilityBucket(info, nowMs) {
  if (!info || !info.cached) return 'loading'
  if (!info.product_count) return 'none'
  const m = monthsSince(info.latest_date, nowMs)
  if (m < 6) return 'recent'
  if (m < 18) return 'mid'
  return 'stale'
}

function isPolygon(geomType) {
  return /polygon|geometry/i.test(geomType || '')
}
function isLine(geomType) {
  return /linestring/i.test(geomType || '')
}

function debounce(fn, ms) {
  let t
  const wrapped = (...args) => {
    clearTimeout(t)
    t = setTimeout(() => fn(...args), ms)
  }
  wrapped.cancel = () => clearTimeout(t)
  return wrapped
}

export function SubsideLayers({ onPickFrame }) {
  const map = useMap()
  const [layers, setLayers] = useState([])
  const [enabled, setEnabled] = useState(() => new Set())
  const [refEnabled, setRefEnabled] = useState(() => new Set()) // ArcGIS reference overlays (off by default)
  const [error, setError] = useState('')
  const [styleVersion, setStyleVersion] = useState(0)
  const [availStats, setAvailStats] = useState(null)

  // frame_id -> availability item; mutated in place, redraw triggered via styleVersion.
  const availabilityRef = useRef(new Map())

  // Leaflet control container the panel is portalled into.
  const [controlEl] = useState(() => {
    const el = L.DomUtil.create('div', 'subside-layer-control')
    L.DomEvent.disableClickPropagation(el)
    L.DomEvent.disableScrollPropagation(el)
    return el
  })

  useEffect(() => {
    const ctrl = L.control({ position: 'topright' })
    ctrl.onAdd = () => controlEl
    ctrl.addTo(map)
    return () => ctrl.remove()
  }, [map, controlEl])

  // Load the registry once; enable everything by default.
  useEffect(() => {
    let cancelled = false
    listLayers()
      .then((rows) => {
        if (cancelled) return
        setLayers(rows)
        setEnabled(new Set(rows.map((r) => r.name)))
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [])

  const satelliteEnabled = enabled.has(AVAILABILITY_LAYER) && layers.some((l) => l.name === AVAILABILITY_LAYER)

  // Viewport-driven availability: fetch for the current bounds, accumulate, redraw.
  useEffect(() => {
    if (!satelliteEnabled) return undefined
    let cancelled = false
    const run = () => {
      fetchAvailability(map.getBounds(), { layer: AVAILABILITY_LAYER })
        .then((res) => {
          if (cancelled) return
          const store = availabilityRef.current
          for (const item of res.items || []) store.set(item.frame_id, item)
          setStyleVersion((v) => v + 1)
          const inView = res.items || []
          setAvailStats({
            inView: inView.length,
            withData: inView.filter((i) => i.cached && i.product_count > 0).length,
            refreshing: (res.refreshing || []).length,
          })
        })
        .catch(() => {})
    }
    run()
    const onMove = debounce(run, 450)
    map.on('moveend', onMove)
    return () => {
      cancelled = true
      onMove.cancel()
      map.off('moveend', onMove)
    }
  }, [map, satelliteEnabled])

  // While frames are still refreshing on the server, re-poll a few times so the
  // colors fill in without the user having to pan.
  useEffect(() => {
    if (!satelliteEnabled || !availStats?.refreshing) return undefined
    const id = setTimeout(() => {
      fetchAvailability(map.getBounds(), { layer: AVAILABILITY_LAYER })
        .then((res) => {
          const store = availabilityRef.current
          for (const item of res.items || []) store.set(item.frame_id, item)
          setStyleVersion((v) => v + 1)
          setAvailStats({
            inView: (res.items || []).length,
            withData: (res.items || []).filter((i) => i.cached && i.product_count > 0).length,
            refreshing: (res.refreshing || []).length,
          })
        })
        .catch(() => {})
    }, 6000)
    return () => clearTimeout(id)
  }, [map, satelliteEnabled, availStats?.refreshing, styleVersion])

  const nowMs = useMemo(() => Date.now(), [styleVersion])

  // Stable palette index per layer name (filtered render order must not change colors).
  const colorIndex = useMemo(
    () => Object.fromEntries(layers.map((l, i) => [l.name, i])),
    [layers],
  )

  // Click -> popup with feature properties (and availability for satellite frames).
  const handleFeatureClick = useCallback(
    (event) => {
      const props = event.layer?.properties || {}
      const lines = []
      if (props.frame_id != null) {
        const info = availabilityRef.current.get(Number(props.frame_id))
        lines.push(`<strong>OPERA frame ${props.frame_id}</strong>`)
        if (info?.cached) {
          lines.push(`${info.product_count} products`)
          lines.push(`latest: ${info.latest_date || 'n/a'}`)
        } else {
          lines.push('availability loading…')
        }
        // Hand the clicked frame to the analysis panel as an AOI + date range.
        if (onPickFrame && info?.bbox) {
          const timeline = info.timeline || []
          onPickFrame({
            frameId: Number(props.frame_id),
            bbox: info.bbox,
            startDate: timeline[0] || null,
            endDate: timeline[timeline.length - 1] || null,
            productCount: info.product_count || 0,
          })
        }
      } else {
        const name = props.cnty_nm || props.name || props.NAME
        if (name) lines.push(`<strong>${name}</strong>`)
        const keys = Object.keys(props).slice(0, 6)
        for (const k of keys) lines.push(`${k}: ${props[k]}`)
      }
      L.popup().setLatLng(event.latlng).setContent(lines.join('<br/>')).openOn(map)
    },
    [map, onPickFrame],
  )

  // Build a VectorGrid style function for a given registry row.
  const styleFor = useCallback((row, index) => {
    if (row.name === AVAILABILITY_LAYER) {
      return (props) => {
        const info = availabilityRef.current.get(Number(props.frame_id))
        const color = AVAIL[availabilityBucket(info, nowMs)].color
        return { weight: 1, color, fill: true, fillColor: color, fillOpacity: 0.35 }
      }
    }
    const color = PALETTE[index % PALETTE.length]
    if (isLine(row.geom_type)) return () => ({ weight: 2, color })
    if (isPolygon(row.geom_type)) {
      return () => ({ weight: 1, color, fill: true, fillColor: color, fillOpacity: 0.15 })
    }
    return () => ({ radius: 4, color, fill: true, fillColor: color, fillOpacity: 0.8 }) // point
  }, [nowMs])

  function toggle(name) {
    setEnabled((current) => {
      const next = new Set(current)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  function toggleRef(id) {
    setError('')
    setRefEnabled((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const panel = (
    <div className="subside-layer-panel">
      <div className="slp-title">Layers</div>
      {error ? <div className="slp-error">{error}</div> : null}
      {!layers.length && !error ? <div className="slp-empty">No registered layers.</div> : null}
      {layers.map((row) => (
        <label key={row.name} className="slp-row">
          <input type="checkbox" checked={enabled.has(row.name)} onChange={() => toggle(row.name)} />
          <span className="slp-swatch" style={{ background: PALETTE[colorIndex[row.name] % PALETTE.length] }} />
          <span className="slp-name">{row.name}</span>
          <span className="slp-count">{row.feature_count}</span>
        </label>
      ))}
      {satelliteEnabled ? (
        <div className="slp-legend">
          <div className="slp-legend-title">OPERA availability</div>
          {['recent', 'mid', 'stale', 'none', 'loading'].map((k) => (
            <div key={k} className="slp-legend-row">
              <span className="slp-swatch" style={{ background: AVAIL[k].color }} />
              <span>{AVAIL[k].label}</span>
            </div>
          ))}
          {availStats ? (
            <div className="slp-stats">
              {availStats.withData}/{availStats.inView} frames with data
              {availStats.refreshing ? ` · ${availStats.refreshing} refreshing…` : ''}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="slp-section">Reference</div>
      {REFERENCE_LAYERS.map((l) => (
        <label key={l.id} className="slp-row">
          <input type="checkbox" checked={refEnabled.has(l.id)} onChange={() => toggleRef(l.id)} />
          <span className="slp-swatch" style={{ background: l.color }} />
          <span className="slp-name">{l.label}</span>
        </label>
      ))}
      <div className="slp-stats">Texas aquifers · live from ArcGIS</div>
    </div>
  )

  return (
    <>
      {layers
        .filter((row) => enabled.has(row.name))
        .map((row) => (
          <VectorTileLayer
            key={row.name}
            url={tileUrlTemplate(row.name)}
            styleVersion={row.name === AVAILABILITY_LAYER ? styleVersion : 0}
            vectorTileLayerStyles={{ [row.name]: styleFor(row, colorIndex[row.name]) }}
            onFeatureClick={handleFeatureClick}
            maxNativeZoom={14}
          />
        ))}
      {REFERENCE_LAYERS.filter((l) => refEnabled.has(l.id)).map((l) => (
        <ReferenceGeoJSON key={l.id} url={l.url} kind={l.kind} onError={setError} />
      ))}
      {createPortal(panel, controlEl)}
    </>
  )
}
