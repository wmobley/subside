// Renders the map's vector layers from a single STAC-driven catalog
// (lib/stacContext.js): the SUBSIDE PostGIS layers served as MVT by the API, plus
// external WMS / XYZ / GeoJSON overlays — all discovered from one place and drawn
// through the generic <ContextLayer> adapter.
//
// The OPERA frame-footprint layer (role "availability") is intentionally NOT a
// map overlay here: its frames are far too large to use as a run AOI (they time
// out the workflow). lib/stacContext drops it from the catalog; its availability
// data now powers an advisory "products available to download" guide in the
// analysis panel (see SubsideAnalysis) once the user draws/uploads their own AOI.
//
// Mounted *inside* a react-leaflet <MapContainer>. The toggle panel is rendered
// into a Leaflet control via a React portal so it lives in the map corner.
import L from 'leaflet'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMap } from 'react-leaflet'

import { useAuth } from '../../lib/auth'
import { listContextLayers } from '../../lib/stacContext'
import { ContextLayer } from './ContextLayer'
import { RunActionsMenu } from './RunActionsMenu'

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

// Layers tagged as velocity-reference candidates (e.g. the stable GNSS marks).
// Surfaced automatically while the user is configuring a velocity run so they can
// pick a stable point; matched by role, not id, so any future stable-point layer
// behaves the same — see context_layers.json `role: "reference-candidate"`.
const REFERENCE_ROLE = 'reference-candidate'

export function SubsideLayers({ prevRunsHostRef, autoShowReference = false, onPickReference }) {
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
  // Per-layer transparency override, keyed by layer id; layers not present here
  // render at their catalog-provided (or default) opacity. Opened via the "..."
  // kebab on each row (actionsMenu holds which layer's popover is open).
  const [opacityById, setOpacityById] = useState(() => new Map())
  const [actionsMenu, setActionsMenu] = useState(null)

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

  // Velocity-reference candidate layers (the stable GNSS marks). When the analysis
  // panel signals a velocity run with an AOI (`autoShowReference`), turn them on so
  // the user can see and pick a stable mark; turn them back off when that context
  // ends. Matched by role so it isn't tied to one dataset.
  const referenceIds = useMemo(
    () => catalog.filter((l) => l.role === REFERENCE_ROLE).map((l) => l.id),
    [catalog],
  )
  useEffect(() => {
    if (!referenceIds.length) return
    setEnabled((current) => {
      const next = new Set(current)
      for (const id of referenceIds) {
        if (autoShowReference) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }, [autoShowReference, referenceIds])

  // Click -> popup with feature properties.
  const handleFeatureClick = useCallback(
    (event) => {
      const props = event.layer?.properties || {}
      const lines = []
      const name = props.cnty_nm || props.name || props.NAME
      if (name) lines.push(`<strong>${name}</strong>`)
      const keys = Object.keys(props).slice(0, 6)
      for (const k of keys) lines.push(`${k}: ${props[k]}`)
      L.popup().setLatLng(event.latlng).setContent(lines.join('<br/>')).openOn(map)
    },
    [map],
  )

  function toggle(id) {
    setEnabled((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const setLayerOpacity = (id, value) => {
    setOpacityById((current) => new Map(current).set(id, value))
  }

  const openLayerActionsMenu = (event, id) => {
    event.preventDefault()
    event.stopPropagation()
    const rect = event.currentTarget.getBoundingClientRect()
    setActionsMenu({ id, top: rect.bottom + 4, left: rect.left })
  }

  // Panel rows, grouped by `group`. Consolidate by group name (not just when the
  // group changes between consecutive items) so each group renders one header even
  // when the catalog interleaves groups (STAC item order isn't group-contiguous).
  const orderedGroups = []
  const byGroup = new Map()
  for (const layer of catalog) {
    const g = layer.group || 'Reference'
    if (!byGroup.has(g)) {
      byGroup.set(g, [])
      orderedGroups.push(g)
    }
    byGroup.get(g).push(layer)
  }
  const rows = orderedGroups.map((g) => (
    <div key={`group-${g}`}>
      <div className="slp-section">{g}</div>
      {byGroup.get(g).map((layer) => (
        <label key={layer.id} className="slp-row">
          <input type="checkbox" checked={enabled.has(layer.id)} onChange={() => toggle(layer.id)} />
          <span className="slp-swatch" style={{ background: layer.color }} />
          <span className="slp-name">{layer.label}</span>
          {layer.featureCount != null ? <span className="slp-count">{layer.featureCount}</span> : null}
          <button
            type="button"
            className="slp-row-actions-btn"
            aria-label={`${layer.label} layer actions`}
            onClick={(event) => openLayerActionsMenu(event, layer.id)}
          >
            ⋮
          </button>
        </label>
      ))}
    </div>
  ))

  const panel = (
    <div className="subside-layer-panel">
      <div className="slp-title">Layers</div>
      {error ? <div className="slp-error">{error}</div> : null}
      {!catalog.length && !error ? <div className="slp-empty">Loading layers…</div> : null}
      {rows}

      {/* Previous runs (STAC) — StacResults portals its list/toggle in here. */}
      <div ref={prevRunsHostRef} className="slp-prevruns" />
    </div>
  )

  const activeMenuLayer = actionsMenu ? catalog.find((l) => l.id === actionsMenu.id) : null

  return (
    <>
      {catalog.filter((l) => enabled.has(l.id)).map((layer) => (
        <ContextLayer
          key={layer.id}
          layer={{ ...layer, opacity: opacityById.get(layer.id) ?? layer.opacity ?? 1 }}
          onError={setError}
          onFeatureClick={handleFeatureClick}
          // On reference-candidate layers, let a click offer "use as velocity
          // reference" (only while the velocity workflow wants one).
          onPickReference={
            layer.role === REFERENCE_ROLE && autoShowReference ? onPickReference : null
          }
        />
      ))}
      {createPortal(panel, controlEl)}
      {actionsMenu ? (
        <RunActionsMenu
          top={actionsMenu.top}
          left={actionsMenu.left}
          showDownload={false}
          showZoomIn={false}
          opacity={opacityById.get(actionsMenu.id) ?? activeMenuLayer?.opacity ?? 1}
          onOpacityChange={(value) => setLayerOpacity(actionsMenu.id, value)}
          onClose={() => setActionsMenu(null)}
        />
      ) : null}
    </>
  )
}
