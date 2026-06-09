import { AUDIENCE_CARDS } from '../lib/config'
import { startTapisLogin } from '../lib/subsideApi'

// The landing-page audience chooser. Public goes straight to the map; the
// professional path starts TACC login (and still lands on the map afterward,
// or now if login isn't available).
export function PortalCards({ onNavigate }) {
  async function choose(card) {
    if (!card.requiresLogin) {
      onNavigate('maps')
      return
    }
    try {
      await startTapisLogin() // redirects to TACC; returns to the map signed in
    } catch {
      onNavigate('maps') // login unavailable — still let them into the map
    }
  }

  return (
    <div className="portal-cards">
      {AUDIENCE_CARDS.map((card) => (
        <article className="portal-card" key={card.id}>
          <div className="portal-card-icon">
            <span aria-hidden="true">{card.icon}</span>
          </div>
          <h2>{card.title}</h2>
          <p>{card.description}</p>
          <ul className="card-features">
            {card.features.map((feature) => (
              <li key={feature}>{feature}</li>
            ))}
          </ul>
          <button
            className={`portal-btn ${card.requiresLogin ? 'portal-btn-outline' : ''}`}
            type="button"
            onClick={() => choose(card)}
          >
            {card.action}
          </button>
        </article>
      ))}
    </div>
  )
}
