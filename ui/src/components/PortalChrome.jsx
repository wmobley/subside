import { Fragment } from 'react'

import { useAuth } from '../lib/auth'
import { startTapisLogin } from '../lib/subsideApi'
import { HERO } from '../lib/config'
import { hashForPage } from '../lib/routes'
import { getPartners } from '../lib/content'

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
  // Partner institutions come from the same content the About page uses
  // (content/partners/*.md), so the header stays in sync with one source.
  const partners = getPartners()
  return (
    <header className="subside-header">
      <div className="subside-header-top">
        <div className="subside-container institution-bar">
          <div className="institutions" aria-label="Partner institutions">
            {partners.map((partner, i) => (
              <Fragment key={partner.abbr || partner.name}>
                {i > 0 ? <span>|</span> : null}
                <a
                  href={partner.url || '#'}
                  target="_blank"
                  rel="noreferrer"
                  title={partner.name}
                >
                  {partner.abbr || partner.name}
                </a>
              </Fragment>
            ))}
          </div>
          <div className="contract-label">Contract #2401792868</div>
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
              <li><a href={hashForPage('datasets')}>Browse datasets</a></li>
              <li><a href={hashForPage('maps')}>Download results</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>Tools</h3>
            <ul className="footer-links">
              <li><a href={hashForPage('maps')}>Risk Explorer</a></li>
              <li><a href={hashForPage('maps')}>Observed subsidence</a></li>
              <li><a href={hashForPage('forecast')}>Subsidence forecast</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>Resources</h3>
            <ul className="footer-links">
              <li><a href={hashForPage('home')}>Guide</a></li>
              <li><a href="https://ptdatax.tacc.utexas.edu/workbench/applications/DSO-Institute-2026-app-cpu" target="_blank" rel="noreferrer">Tutorials</a></li>
              <li><a href={hashForPage('datasets')}>Publications</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>About</h3>
            <ul className="footer-links">
              <li><a href={hashForPage('about')}>Team</a></li>
              <li><a href={hashForPage('about')}>Contact</a></li>
              <li><a href={hashForPage('about')}>Terms</a></li>
            </ul>
          </section>
        </div>
        <div className="footer-bottom">
          <div>(c) 2026 TACC</div>
          <div className="footer-policy">
            <a href={hashForPage('about')}>Privacy</a>
            <a href={hashForPage('about')}>Access</a>
          </div>
        </div>
      </div>
    </footer>
  )
}
