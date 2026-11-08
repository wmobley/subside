import { describe, expect, it } from 'vitest'

import { localizeApiHref } from '../stacContext'

describe('localizeApiHref', () => {
  it('serves SUBSIDE API tile hrefs from the configured API (same-origin in dev)', () => {
    expect(localizeApiHref('https://subsideapi.pods.portals.tapis.io/api/subside/tiles/aquifers/{z}/{x}/{y}.mvt'))
      .toBe('/api/subside/tiles/aquifers/{z}/{x}/{y}.mvt')
  })
  it('leaves other hosts alone', () => {
    const wms = 'https://example.org/arcgis/services/aquifers/MapServer/WMSServer'
    expect(localizeApiHref(wms)).toBe(wms)
    expect(localizeApiHref(null)).toBeNull()
  })
})
