import { PORTAL_CONFIGS } from '../config'

const NAV_ITEMS = [
  { id: 'home', label: 'Home' },
  { id: 'datasets', label: 'Datasets' },
  { id: 'maps', label: 'Maps' },
  { id: 'api', label: 'API' },
  { id: 'about', label: 'About' },
]

export function PortalHeader({ activePage, portalMode, onPageChange, onModeChange }) {
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

            <div className="mode-switcher" aria-label="Audience mode">
              {Object.entries(PORTAL_CONFIGS).map(([mode, config]) => (
                <button
                  className={`mode-btn ${portalMode === mode ? 'active' : ''}`}
                  key={mode}
                  type="button"
                  onClick={() => onModeChange(mode)}
                >
                  {config.label}
                </button>
              ))}
            </div>
          </nav>
        </div>
      </div>
    </header>
  )
}

export function PortalHero({ modeConfig }) {
  return (
    <section className="subside-hero">
      <div className="subside-container">
        <h1>{modeConfig.title}</h1>
        <p>{modeConfig.subtitle}</p>
      </div>
    </section>
  )
}

export function SearchSection({ modeConfig, searchTerm, onSearchTermChange, onSearch }) {
  return (
    <section className="search-section">
      <div className="subside-container">
        <div className="search-wrapper">
          <form className="search-form" onSubmit={onSearch}>
            <input
              className="search-input"
              value={searchTerm}
              onChange={(event) => onSearchTermChange(event.target.value)}
              placeholder={modeConfig.search}
              type="search"
            />
            <button className="search-btn" type="submit">Search</button>
          </form>
        </div>
      </div>
    </section>
  )
}

export function StatsSection({ stats }) {
  return (
    <section className="stats-section">
      <div className="subside-container">
        <div className="stats-grid">
          {stats.map((stat) => (
            <div className="stat" key={`${stat.value}-${stat.label}`}>
              <div className="stat-value">{stat.value}</div>
              <div className="stat-label">{stat.label}</div>
            </div>
          ))}
        </div>
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
              <li><a href="#datasets">Browse</a></li>
              <li><a href="#api">API</a></li>
              <li><a href="#map">Download</a></li>
            </ul>
          </section>
          <section className="footer-section">
            <h3>Tools</h3>
            <ul className="footer-links">
              <li><a href="#map">Web Services</a></li>
              <li><a href="#api">Jupyter</a></li>
              <li><a href="#map">Processing</a></li>
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
