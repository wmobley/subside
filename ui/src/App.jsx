import { useEffect, useState } from 'react'
import 'leaflet/dist/leaflet.css'

import { useAuth } from './auth'
import { exchangeAuthCode, takeOAuthState } from './subsideApi'
import { PortalPageContent } from './components/pages/PortalPageContent'
import { PortalHeader } from './components/PortalChrome'

// Initial map view (Texas). The Risk Explorer's own layers + analysis panel
// drive the map; no dataset backend is needed to render it.
const MAP_DEFAULTS = { center: { lat: 30.26, lon: -97.74, zoom: 6 } }

export default function App() {
  const [activePage, setActivePage] = useState('home')
  const [statusMessage, setStatusMessage] = useState('')
  const [zoom, setZoom] = useState(MAP_DEFAULTS.center.zoom)

  const { login } = useAuth()

  // OAuth2 redirect callback: Tapis returns the browser to the app with
  // ?code=&state=. Exchange the code for a token server-side, stash it where the
  // Risk Explorer reads it (localStorage), then land on the maps page.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) return
    const returnedState = params.get('state')
    const expectedState = takeOAuthState()
    window.history.replaceState({}, '', window.location.pathname) // drop ?code= from the URL
    if (expectedState && returnedState && expectedState !== returnedState) {
      setStatusMessage('Login failed: state mismatch (possible CSRF). Please try again.')
      return
    }
    exchangeAuthCode(code)
      .then((res) => {
        login(res.token, res.username, res.expires_at)
        setActivePage('maps')
      })
      .catch((err) => setStatusMessage(`Login failed: ${err.message}`))
  }, [login])

  const mapWorkbenchProps = { mapData: MAP_DEFAULTS, zoom, setZoom, statusMessage }

  return (
    <div className="subside-page">
      <PortalHeader activePage={activePage} onPageChange={setActivePage} />
      <PortalPageContent
        activePage={activePage}
        onNavigate={setActivePage}
        mapWorkbenchProps={mapWorkbenchProps}
      />
    </div>
  )
}
