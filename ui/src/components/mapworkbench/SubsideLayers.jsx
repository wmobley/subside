// Renders the map's vector layers from a single STAC-driven catalog
// (lib/stacContext.js): the SUBSIDE PostGIS layers served as MVT by the API, plus
// external WMS / XYZ / GeoJSON overlays — all discovered from one place. The
// OPERA frame-footprint layer (role "availability") additionally gets viewport
// availability shading + click-to-pick-frame; every other layer renders through
// the generic <ContextLayer> adapter.
//
// Mounted *inside* a react-leaflet <MapContainer>. The toggle/legend panel is
// rendered into a Leaflet control via a React portal so it lives in the map corner.
import L from 'leaflet'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMap } from 'react-leaflet'

import { useAuth } from '../../lib/auth'
import { fetchAvailability } from '../../lib/subsideApi'
import { listContextLayers } from '../../lib/stacContext'
import { ContextLayer } from './ContextLayer'
import { VectorTileLayer } from './VectorTileLayer'

const AVAILABILITY_ROLE = 'availability' // STAC role marking the OPERA frame layer

// Resolve a layer's default-on state against auth: `visible_when` (authed/anon/
// always/never) wins; otherwise the plain `default_visible` boolean applies.
function isDefaultOn(layer, isAuthed) {
  switch (layer.visibleWhen) {
    case 'authed':
      return isAuthed
    case 'anon':
      return !isAuthed
    case 'always':
      return true
    case 'never':
      return false
    default:
      return Boolean(layer.defaultVisible)
  }
}

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

function debounce(fn, ms) {
  let t
  const wrapped = (...args) => {
    clearTimeout(t)
    t = setTimeout(() => fn(...args), ms)
  }
  wrapped.cancel = () => clearTimeout(t)
  return wrapped
}

export function SubsideLayers({ onPickFrame, prevRunsHostRef }) {
  const map = useMap()
  const { isAuthed } = useAuth()
  // Latest auth, read when the catalog resolves so the default-on set reflects
  // login at navigation time — without re-running the fetch (which would clobber
  // the user's manual toggles) every time auth changes.
  const isAuthedRef = useRef(isAuthed)
  isAuthedRef.current = isAuthed
  const [catalog, setCatalog] = useState([]) // all vector layers, from STAC (or fallback)
  const [enabled, setEnabled] = useState(() => new Set())
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

  // Load the catalog once from STAC; default-visible layers start toggled on.
  useEffect(() => {
    let cancelled = false
    listContextLayers()
      .then((rows) => {
        if (cancelled) return
        setCatalog(rows)
        setEnabled(new Set(rows.filter((r) => isDefaultOn(r, isAuthedRef.current)).map((r) => r.id)))
        if (!rows.length) setError('No layers registered.')
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [])

  // The OPERA frame layer (if registered) drives the availability overlay.
  const availLayer = useMemo(
    () => catalog.find((l) => l.role === AVAILABILITY_ROLE) || null,
    [catalog],
  )
  const availId = availLayer?.id
  const satelliteEnabled = Boolean(availId && enabled.has(availId))

  // Viewport-driven availability: fetch for the current bounds, accumulate, redraw.
  useEffect(() => {
    if (!satelliteEnabled || !availId) return undefined
    let cancelled = false
    const run = () => {
      fetchAvailability(map.getBounds(), { layer: availId })
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
  }, [map, satelliteEnabled, availId])

  // While frames are still refreshing on the server, re-poll a few times so the
  // colors fill in without the user having to pan.
  useEffect(() => {
    if (!satelliteEnabled || !availId || !availStats?.refreshing) return undefined
    const id = setTimeout(() => {
      fetchAvailability(map.getBounds(), { layer: availId })
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
  }, [map, satelliteEnabled, availId, availStats?.refreshing, styleVersion])

  const nowMs = useMemo(() => Date.now(), [styleVersion])

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

  // VectorGrid style for the availability layer: color each OPERA frame by the
  // recency of its latest product (live, from availabilityRef + styleVersion).
  const availabilityStyle = useCallback(
    (props) => {
      const info = availabilityRef.current.get(Number(props.frame_id))
      const color = AVAIL[availabilityBucket(info, nowMs)].color
      return { weight: 1, color, fill: true, fillColor: color, fillOpacity: 0.35 }
    },
    [nowMs],
  )

  function toggle(id) {
    setEnabled((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Render one catalog layer: the availability layer gets the special shaded MVT
  // path; everything else goes through the generic adapter.
  function renderLayer(layer) {
    if (layer.role === AVAILABILITY_ROLE) {
      const sourceKey = (layer.sourceLayers && layer.sourceLayers[0]) || layer.id
      return (
        <VectorTileLayer
          key={layer.id}
          url={layer.href}
          styleVersion={styleVersion}
          vectorTileLayerStyles={{ [sourceKey]: availabilityStyle }}
          onFeatureClick={handleFeatureClick}
          maxNativeZoom={layer.maxZoom || 14}
        />
      )
    }
    return (
      <ContextLayer key={layer.id} layer={layer} onError={setError} onFeatureClick={handleFeatureClick} />
    )
  }

  // Panel rows, grouped by `group` with a header whenever the group changes.
  let lastGroup = null
  const rows = catalog.map((layer) => {
    const header = layer.group !== lastGroup ? layer.group : null
    lastGroup = layer.group
    return (
      <div key={layer.id}>
        {header ? <div className="slp-section">{header}</div> : null}
        <label className="slp-row">
          <input type="checkbox" checked={enabled.has(layer.id)} onChange={() => toggle(layer.id)} />
          <span className="slp-swatch" style={{ background: layer.color }} />
          <span className="slp-name">{layer.label}</span>
          {layer.featureCount != null ? <span className="slp-count">{layer.featureCount}</span> : null}
        </label>
      </div>
    )
  })

  const panel = (
    <div className="subside-layer-panel">
      <div className="slp-title">Layers</div>
      {error ? <div className="slp-error">{error}</div> : null}
      {!catalog.length && !error ? <div className="slp-empty">Loading layers…</div> : null}
      {rows}
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

      {/* Previous runs (STAC) — StacResults portals its list/toggle in here. */}
      <div ref={prevRunsHostRef} className="slp-prevruns" />
    </div>
  )

  return (
    <>
      {catalog.filter((l) => enabled.has(l.id)).map(renderLayer)}
      {createPortal(panel, controlEl)}
    </>
  )
}
