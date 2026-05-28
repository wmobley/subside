import { visibleCardsForMode } from '../config'

export function PortalCards({ portalMode, onModeChange }) {
  return (
    <div className="portal-cards">
      {visibleCardsForMode(portalMode).map((card) => (
        <article className="portal-card" key={card.mode}>
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
            className={`portal-btn ${card.outline ? 'portal-btn-outline' : ''}`}
            type="button"
            onClick={() => onModeChange(card.mode)}
          >
            {card.action}
          </button>
        </article>
      ))}
    </div>
  )
}
