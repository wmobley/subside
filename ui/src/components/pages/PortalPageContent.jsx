import ReactMarkdown from 'react-markdown'

import { CkanDatasets } from '../CkanDatasets'
import { ForecastTool } from '../ForecastTool'
import { MapWorkbench } from '../MapWorkbench'
import { PortalCards } from '../PortalCards'
import { PortalFooter, PortalHero } from '../PortalChrome'
import { CONTRACT_FLAG, getAbout, getGoals, getPartners } from '../../content'
import { HOW_IT_WORKS } from '../../config'

function HomePage({ onNavigate }) {
  return (
    <>
      <PortalHero />
      <main className="subside-main">
        <div className="subside-container">
          <PortalCards onNavigate={onNavigate} />

          <section className="about-section">
            <h2 className="about-section-title">How SUBSIDE works</h2>
            <div className="about-goal-grid">
              {HOW_IT_WORKS.map((step, i) => (
                <article className="about-goal" key={step.title}>
                  <h3>{i + 1}. {step.title}</h3>
                  <div className="about-goal-body"><p>{step.description}</p></div>
                </article>
              ))}
            </div>
          </section>
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
          <h1>Data</h1>
          <p>Browse the TWDB SUBSIDE spatial datasets published in CKAN. These layers add context to the Risk Explorer and feed the subsidence forecast.</p>
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

function AboutPage() {
  const about = getAbout()
  const goals = getGoals()
  const partners = getPartners()

  return (
    <main className="subside-main about-page">
      <div className="subside-container">
        <div className="page-heading">
          <h1>{about.title || 'About SUBSIDE'}</h1>
          {about.tagline ? <p>{about.tagline}</p> : null}
        </div>

        {about.body ? (
          <div className="about-intro">
            <ReactMarkdown>{about.body}</ReactMarkdown>
          </div>
        ) : null}

        {goals.length ? (
          <section className="about-section">
            <h2 className="about-section-title">What we're building</h2>
            <div className="about-goal-grid">
              {goals.map((goal) => (
                <article className="about-goal" key={goal.title}>
                  <h3>{goal.title}</h3>
                  <div className="about-goal-body">
                    <ReactMarkdown>{goal.description}</ReactMarkdown>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {partners.length ? (
          <section className="about-section">
            <h2 className="about-section-title">Partner Organizations</h2>
            <div className="about-partner-grid">
              {partners.map((partner) => (
                <a
                  className="about-partner"
                  key={partner.abbr || partner.name}
                  href={partner.url || '#'}
                  target="_blank"
                  rel="noreferrer"
                >
                  <div className="about-partner-head">
                    <span className="about-partner-abbr">{partner.abbr}</span>
                    {partner.role ? <span className="about-partner-role">{partner.role}</span> : null}
                  </div>
                  <div className="about-partner-name">{partner.name}</div>
                  <div className="about-partner-desc">
                    <ReactMarkdown>{partner.description}</ReactMarkdown>
                  </div>
                </a>
              ))}
            </div>
            <p className="about-stakeholders">
              SUBSIDE also works with subsidence districts, groundwater conservation
              districts, and other data providers and stakeholders — including the
              Harris–Galveston Subsidence District — who contribute data and guide the
              project's direction.
            </p>
          </section>
        ) : null}

        <p className="about-contract">{CONTRACT_FLAG}</p>
      </div>
      <PortalFooter />
    </main>
  )
}

export function PortalPageContent({
  activePage,
  onNavigate,
  mapWorkbenchProps,
}) {
  if (activePage === 'home') {
    return <HomePage onNavigate={onNavigate} />
  }
  if (activePage === 'datasets') return <DatasetsPage />
  if (activePage === 'maps') return <MapsPage mapWorkbenchProps={mapWorkbenchProps} />
  if (activePage === 'forecast') return <ForecastTool />
  return <AboutPage />
}
