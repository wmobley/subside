// Small "..." actions menu (Download / Zoom In) for one previous-run layer.
// Opened two ways -- both funnel into the same menu/state so behavior stays
// identical: the kebab button in the Layers panel's per-run row, and a
// right-click (contextmenu) on the rendered layer itself on the map. Portalled
// to <body> so it isn't clipped by the Layers panel or the Leaflet pane.
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

export function RunActionsMenu({ top, left, downloadHref, downloadName, onZoomIn, onClose }) {
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
      {downloadHref ? (
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
      )}
      <button
        type="button"
        className="slp-run-actions-item"
        disabled={!onZoomIn}
        onClick={() => { onZoomIn?.(); onClose() }}
      >
        Zoom In
      </button>
    </div>,
    document.body,
  )
}
