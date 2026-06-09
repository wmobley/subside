// Hash-based routing for the portal's top-level pages.
//
// The URL hash is the single source of truth for which page is shown, so links
// like /#/risk-explorer are shareable and the browser back/forward buttons work.
// `id` is the internal page identifier used by PortalPageContent / NAV_ITEMS;
// `slug` is what appears in the hash. Home is the empty slug (/#/).
export const PAGES = [
  { id: 'home', slug: '' },
  { id: 'maps', slug: 'risk-explorer' },
  { id: 'forecast', slug: 'forecast' },
  { id: 'datasets', slug: 'data' },
  { id: 'about', slug: 'about' },
]

const DEFAULT_PAGE = 'home'

// "#/risk-explorer" | "#/risk-explorer/" -> "risk-explorer"; "" | "#" | "#/" -> ""
function normalizeSlug(hash) {
  return (hash || '').replace(/^#\/?/, '').replace(/\/+$/, '').toLowerCase()
}

// Resolve the current (or given) hash to a page id, defaulting to Home.
export function pageFromHash(hash = window.location.hash) {
  const slug = normalizeSlug(hash)
  const match = PAGES.find((p) => p.slug === slug)
  return match ? match.id : DEFAULT_PAGE
}

// The hash a given page id should live at (e.g. 'maps' -> "#/risk-explorer").
export function hashForPage(page) {
  const match = PAGES.find((p) => p.id === page)
  return `#/${match ? match.slug : ''}`
}
