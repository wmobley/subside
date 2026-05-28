import { AuthPanel } from '../AuthPanel'
import { CkanDatasets } from '../CkanDatasets'
import { MapWorkbench } from '../MapWorkbench'
import { PortalCards } from '../PortalCards'
import { PortalFooter, PortalHero, SearchSection, StatsSection } from '../PortalChrome'

function HomePage({ modeConfig, portalMode, searchTerm, onSearchTermChange, onSearch, onModeChange }) {
  return (
    <>
      <PortalHero modeConfig={modeConfig} />
      <SearchSection
        modeConfig={modeConfig}
        searchTerm={searchTerm}
        onSearchTermChange={onSearchTermChange}
        onSearch={onSearch}
      />
      <StatsSection stats={modeConfig.stats} />
      <main className="subside-main">
        <div className="subside-container">
          <PortalCards portalMode={portalMode} onModeChange={onModeChange} />
        </div>
      </main>
    </>
  )
}

function DatasetsPage() {
  return (
    <main className="subside-main">
      <div className="subside-container">
        <div className="page-heading">
          <h1>Datasets</h1>
          <p>Search and filter the TWDB SUBSIDE datasets published in CKAN.</p>
        </div>
        <CkanDatasets />
      </div>
    </main>
  )
}

function MapsPage({ mapWorkbenchProps }) {
  return (
    <main className="subside-main">
      <div className="subside-container">
        <MapWorkbench {...mapWorkbenchProps} />
      </div>
    </main>
  )
}

function ApiPage({ authProps }) {
  return (
    <main className="subside-main">
      <div className="subside-container api-page">
        <div className="page-heading">
          <h1>API</h1>
          <p>Authenticate with Tapis and connect SUBSIDE workflows for data processing and publication.</p>
        </div>
        <div className="api-grid">
          <AuthPanel {...authProps} />
          <section className="api-card">
            <h2>Workflow Gateway</h2>
            <p>The React app uses `/api/*` endpoints through the Vite proxy while developing locally.</p>
            <div className="endpoint-list">
              <code>/api/datasets</code>
              <code>/api/login</code>
              <code>/api/apply</code>
              <code>/api/workflow/register</code>
            </div>
          </section>
        </div>
      </div>
    </main>
  )
}

function AboutPage() {
  return (
    <main className="subside-main about-page">
      <div className="subside-container">
        <div className="page-heading">
          <h1>About SUBSIDE</h1>
          <p>SUBSIDE brings Texas subsidence data, map exploration, and workflow-backed analysis into one portal.</p>
        </div>
      </div>
      <PortalFooter />
    </main>
  )
}

export function PortalPageContent({
  activePage,
  modeConfig,
  portalMode,
  searchTerm,
  onSearchTermChange,
  onSearch,
  onModeChange,
  authProps,
  mapWorkbenchProps,
}) {
  if (activePage === 'home') {
    return (
      <HomePage
        modeConfig={modeConfig}
        portalMode={portalMode}
        searchTerm={searchTerm}
        onSearchTermChange={onSearchTermChange}
        onSearch={onSearch}
        onModeChange={onModeChange}
      />
    )
  }
  if (activePage === 'datasets') return <DatasetsPage />
  if (activePage === 'maps') return <MapsPage mapWorkbenchProps={mapWorkbenchProps} />
  if (activePage === 'api') return <ApiPage authProps={authProps} />
  return <AboutPage />
}
