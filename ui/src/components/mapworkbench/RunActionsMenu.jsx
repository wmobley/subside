// Small "..." actions menu for one map layer. Originally just Download / Zoom
// In for a previous-run raster -- opened two ways that funnel into the same
// menu/state so behavior stays identical: the kebab button in the Layers
// panel's per-run row, and a right-click (contextmenu) on the rendered layer
// itself on the map. Portalled to <body> so it isn't clipped by the Layers
// panel or the Leaflet pane.
//
// Also reused (kebab-only, no right-click) for catalog layer rows and the
// Displacement/Subsidence Velocity group toggles, where only the Transparency
// slider applies -- Download/Zoom In are omitted there via showDownload/
// showZoomIn rather than rendered disabled, since neither action makes sense
// for a whole layer group.
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

export function RunActionsMenu({
  top, left, downloadHref, downloadName, onZoomIn, opacity, onOpacityChange,
  showDownload = true, showZoomIn = true, onClose,
}) {
  useEffect(() => {
    const handlePointerDown = (event) => {
      if (!event.target.closest?.('.slp-run-actions-menu')) onClose()
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    // Capture phase: a right-click that opens this menu also fires its own
    // 'contextmenu' on document; listening on mousedown (not click) closes on
    // the same gesture that opens a *different* run's menu.
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  return createPortal(
    <div className="slp-run-actions-menu" style={{ top, left }}>
      {showDownload ? (
        downloadHref ? (
          <a
            className="slp-run-actions-item"
            href={downloadHref}
            download={downloadName || true}
            target="_blank"
            rel="noreferrer"
            onClick={onClose}
          >
            Download
          </a>
        ) : (
          <span className="slp-run-actions-item slp-run-actions-item--disabled">Download</span>
        )
      ) : null}
      {showZoomIn ? (
        <button
          type="button"
          className="slp-run-actions-item"
          disabled={!onZoomIn}
          onClick={() => { onZoomIn?.(); onClose() }}
        >
          Zoom In
        </button>
      ) : null}
      {onOpacityChange ? (
        <div className="slp-run-actions-item slp-run-actions-opacity">
          <span className="slp-run-actions-opacity-label">
            Transparency · {Math.round((opacity ?? 1) * 100)}%
          </span>
          <input
            type="range"
            min={0}
            max={100}
            value={Math.round((opacity ?? 1) * 100)}
            onChange={(e) => onOpacityChange(Number(e.target.value) / 100)}
          />
        </div>
      ) : null}
    </div>,
    document.body,
  )
}
