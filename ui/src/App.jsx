import { useCallback, useEffect, useState } from 'react'
import 'leaflet/dist/leaflet.css'

import { useAuth } from './lib/auth'
import { exchangeAuthCode, takeOAuthState } from './lib/subsideApi'
import { pageFromHash, hashForPage } from './lib/routes'
import { PortalPageContent } from './components/pages/PortalPageContent'
import { PortalHeader, PortalFooter } from './components/PortalChrome'

// Initial map view (Texas). The Risk Explorer's own layers + analysis panel
// drive the map; no dataset backend is needed to render it.
const MAP_DEFAULTS = { center: { lat: 30.26, lon: -97.74, zoom: 6 } }

export default function App() {
  // The URL hash drives the active page (see routes.js); initialise from it so
  // deep links like /#/risk-explorer land on the right page.
  const [activePage, setActivePage] = useState(() => pageFromHash())
  const [statusMessage, setStatusMessage] = useState('')
  const [zoom, setZoom] = useState(MAP_DEFAULTS.center.zoom)

  const { login } = useAuth()

  // Keep activePage in sync with the hash (browser back/forward, manual edits).
  useEffect(() => {
    const onHashChange = () => setActivePage(pageFromHash())
    window.addEventListener('hashchange', onHashChange)
    onHashChange() // reconcile state with the current hash on mount
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Navigate by updating the hash; the listener above flips activePage. Re-clicks
  // (same hash, no hashchange event) still resync state.
  const navigate = useCallback((page) => {
    const next = hashForPage(page)
    if (window.location.hash !== next) window.location.hash = next
    else setActivePage(pageFromHash(next))
  }, [])

  // OAuth2 redirect callback: Tapis returns the browser to the app with
  // ?code=&state=. Exchange the code for a token server-side, stash it where the
  // Risk Explorer reads it (localStorage), then land on the Risk Explorer page.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) return
    const returnedState = params.get('state')
    const expectedState = takeOAuthState()
    // Drop ?code= but keep the hash route.
    window.history.replaceState({}, '', window.location.pathname + window.location.hash)
    if (expectedState && returnedState && expectedState !== returnedState) {
      setStatusMessage('Login failed: state mismatch (possible CSRF). Please try again.')
      return
    }
    exchangeAuthCode(code)
      .then((res) => {
        login(res.token, res.username, res.expires_at)
        navigate('maps')
      })
      .catch((err) => setStatusMessage(`Login failed: ${err.message}`))
  }, [login, navigate])

  const mapWorkbenchProps = { mapData: MAP_DEFAULTS, zoom, setZoom, statusMessage }

  return (
    <div className="subside-page">
      <PortalHeader activePage={activePage} onPageChange={navigate} />
      <PortalPageContent
        activePage={activePage}
        onNavigate={navigate}
        mapWorkbenchProps={mapWorkbenchProps}
      />
      <PortalFooter />
    </div>
  )
}
