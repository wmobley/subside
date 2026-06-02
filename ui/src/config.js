// Landing-page content. SUBSIDE serves two audiences to start (per the project's
// stakeholder work): the General Public (intuitive, local, plain-language risk —
// no account) and Professionals (water providers, groundwater districts,
// agencies, researchers — run analysis on TACC, needs a TACC account).

export const HERO = {
  title: 'Understand your land subsidence risk',
  subtitle:
    'SUBSIDE shows where the ground is sinking across Texas — observed from NASA '
    + 'satellite radar, with a forecast of what may come — for everyone from '
    + 'homeowners to water managers.',
}

// The two starting user types, shown as a chooser on the landing page.
export const AUDIENCE_CARDS = [
  {
    id: 'public',
    icon: '🗺️',
    title: 'General Public',
    requiresLogin: false,
    description:
      'See how the ground is moving where you live, in plain language — '
      + 'no account needed.',
    features: [
      'Explore the statewide subsidence map',
      'Observed ground movement from satellite radar',
      'Plain-language subsidence risk forecast for your area',
      'Aquifer, county & other context layers',
    ],
    action: 'Explore the map',
  },
  {
    id: 'professional',
    icon: '⚙️',
    title: 'Professional',
    requiresLogin: true,
    description:
      'For water providers, groundwater districts, agencies, and researchers. '
      + 'Run subsidence analysis on TACC and get GIS-ready results. '
      + 'Requires a TACC account.',
    features: [
      'Run OPERA DISP-S1 analysis on TACC',
      'Cumulative displacement & velocity (GIS-ready GeoTIFFs)',
      'Process any area and time range',
      'Everything in the public view',
    ],
    action: 'Log in with TACC',
  },
]

// "How it works" — the three-beat product story for the landing page.
export const HOW_IT_WORKS = [
  {
    title: 'Pick your area',
    description: 'Choose a location on the statewide map — your neighborhood, a city, or a water-management region.',
  },
  {
    title: 'See observed movement',
    description: 'View how much, and how fast, the ground has moved, measured from NASA OPERA DISP-S1 satellite radar.',
  },
  {
    title: 'Get a forecast',
    description: 'Estimate potential future subsidence and a 0–10 risk score to support planning decisions.',
  },
]
