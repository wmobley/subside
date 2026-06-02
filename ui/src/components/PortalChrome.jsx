import { useAuth } from '../auth'
import { startTapisLogin } from '../subsideApi'
import { HERO } from '../config'

const NAV_ITEMS = [
  { id: 'home', label: 'Home' },
  { id: 'maps', label: 'Risk Explorer' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'datasets', label: 'Data' },
  { id: 'about', label: 'About' },
]

async function handleHeaderLogin() {
  try {
    await startTapisLogin() // redirects to the Tapis-hosted login page
  } catch (err) {
    window.alert(`Login unavailable: ${err.message}`)
  }
}

export function PortalHeader({ activePage, onPageChange }) {
  const { isAuthed, username, logout } = useAuth()
  return (
    <header className="subside-header">
      <div className="subside-header-top">
        <div className="subside-container institution-bar">
          <div className="institutions" aria-label="Partner institutions">
            <a href="https://www.utexas.edu/">UT Austin</a>
            <span>|</span>
            <a href="https://www.tacc.utexas.edu/">TACC</a>
            <span>|</span>
            <a href="https://www.twdb.texas.gov/">TWDB</a>
          </div>
          <div className="contract-label">Contract #2300012717</div>
        </div>
      </div>

      <div className="subside-header-main">
        <div className="subside-container subside-header-content">
          <div className="subside-logo">
            <span className="subside-logo-badge">SUBSIDE</span>
            <span className="subside-logo-text">Data Discovery Portal</span>
          </div>

          <nav className="subside-nav" aria-label="Primary">
            <ul className="subside-nav-links">
              {NAV_ITEMS.map((item) => (
                <li key={item.id}>
                  <button
                    className={`nav-link ${activePage === item.id ? 'active' : ''}`}
                    type="button"
                    onClick={() => onPageChange(item.id)}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>

            <div className="subside-auth" aria-label="Account">
              {isAuthed ? (
                <>
                  <span className="subside-auth-user" title={`Signed in as ${username}`}>{username}</span>
                  <button type="button" className="subside-auth-btn" onClick={logout}>Log out</button>
                </>
              ) : (
                <button type="button" className="subside-auth-btn subside-auth-btn--primary" onClick={handleHeaderLogin}>
                  Log in
                </button>
              )}
            </div>
          </nav>
        </div>
      </div>
    </header>
  )
}

export function PortalHero() {
  return (
    <section className="subside-hero">
      <div className="subside-container">
        <h1>{HERO.title}</h1>
        <p>{HERO.subtitle}</p>
      </div>
    </section>
  )
}

export function PortalFooter() {
  return (
    <footer className="subside-footer">
      <div className="subside-container">
        <div className="footer-content">
          <section className="footer-section">
            <h3>Data</h3>
            <ul className="footer-links">
              <li><a href="#datasets">Browse datasets</a></li>
              <li><a href="#map">Download results</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>Tools</h3>
            <ul className="footer-links">
              <li><a href="#map">Risk Explorer</a></li>
              <li><a href="#map">Observed subsidence</a></li>
              <li><a href="#map">Subsidence forecast</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>Resources</h3>
            <ul className="footer-links">
              <li><a href="#home">Guide</a></li>
              <li><a href="#datasets">Tutorials</a></li>
              <li><a href="#datasets">Publications</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>About</h3>
            <ul className="footer-links">
              <li><a href="#about">Team</a></li>
              <li><a href="#about">Contact</a></li>
              <li><a href="#about">Terms</a></li>
            </ul>
          </section>
        </div>
        <div className="footer-bottom">
          <div>(c) 2026 TACC</div>
          <div className="footer-policy">
            <a href="#about">Privacy</a>
            <a href="#about">Access</a>
          </div>
        </div>
      </div>
    </footer>
  )
}
