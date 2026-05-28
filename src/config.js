export const PORTAL_CONFIGS = {
  public: {
    label: 'Public',
    title: 'Check Your Property for Subsidence Risk',
    subtitle: 'Easy tools for Texas residents to monitor ground movement',
    search: 'Enter your property address...',
    stats: [
      { value: '250K+', label: 'Properties' },
      { value: 'Low', label: 'Avg Risk' },
      { value: '<1"', label: 'Movement' },
      { value: '23', label: 'Counties' },
      { value: 'Daily', label: 'Updates' },
    ],
    tabs: ['My Area', 'Learn', 'FAQ', 'Help'],
    datasets: [
      { title: 'Property Assessment', description: 'Check your property', tags: ['Simple', 'Property'] },
      { title: 'Education Center', description: 'Learn about subsidence', tags: ['Guide', 'FAQ'] },
      { title: 'Community Data', description: 'Neighborhood info', tags: ['Reports', 'Maps'] },
    ],
  },
  professional: {
    label: 'Professional',
    title: 'Professional Subsidence Management',
    subtitle: 'Tools for infrastructure and water management',
    search: 'Search by region or infrastructure...',
    stats: [
      { value: '847', label: 'GPS Sites' },
      { value: '98%', label: 'Coverage' },
      { value: '7', label: 'Alerts' },
      { value: '<24h', label: 'Latency' },
      { value: '15TB', label: 'Monthly' },
    ],
    tabs: ['Monitoring', 'Analysis', 'Reports', 'Models'],
    datasets: [
      { title: 'Infrastructure Risk', description: 'Real-time monitoring', tags: ['GIS', 'Risk'] },
      { title: 'Regional Models', description: 'Predictive analysis', tags: ['Models', 'Planning'] },
      { title: 'Water Management', description: 'Groundwater data', tags: ['Aquifer', 'Analysis'] },
    ],
  },
  technical: {
    label: 'Technical',
    title: 'Research Data Repository',
    subtitle: 'Raw datasets and computational resources',
    search: 'Query datasets...',
    stats: [
      { value: '1.2PB', label: 'Data' },
      { value: '45K+', label: 'API/Day' },
      { value: '127', label: 'Jobs' },
      { value: '342', label: 'Users' },
      { value: '8ms', label: 'Response' },
    ],
    tabs: ['Raw Data', 'Processing', 'API', 'Docs'],
    datasets: [
      { title: 'GPS Time Series', description: 'Raw RINEX data', tags: ['GPS', 'Raw'] },
      { title: 'Sentinel-1 SLC', description: 'InSAR processing', tags: ['InSAR', 'SLC'] },
      { title: 'Pipeline API', description: 'Custom workflows', tags: ['API', 'Cloud'] },
    ],
  },
}

export const FEATURE_CARDS = [
  {
    mode: 'public',
    icon: 'Home',
    title: 'Public Access',
    description: 'Check subsidence risk for your property with simple tools and visualizations.',
    features: ['Property assessment', 'Visual indicators', 'Educational resources', 'Reports'],
    action: 'Get Started',
  },
  {
    mode: 'professional',
    icon: 'Pro',
    title: 'Professional Tools',
    description: 'Advanced dashboard for water managers with GIS and modeling capabilities.',
    features: ['GIS integration', 'Scenario modeling', 'Risk analysis', 'Custom reports'],
    action: 'Dashboard',
    outline: true,
  },
  {
    mode: 'technical',
    icon: 'API',
    title: 'Research Portal',
    description: 'Full data access with APIs and cloud computing for researchers.',
    features: ['Raw data access', 'RESTful APIs', 'Jupyter notebooks', 'Processing'],
    action: 'View Docs',
    outline: true,
  },
]

export function visibleCardsForMode(mode) {
  if (mode === 'public') return FEATURE_CARDS.filter((card) => card.mode !== 'technical')
  if (mode === 'professional') return FEATURE_CARDS.filter((card) => card.mode !== 'public')
  return FEATURE_CARDS.filter((card) => card.mode === 'technical')
}
