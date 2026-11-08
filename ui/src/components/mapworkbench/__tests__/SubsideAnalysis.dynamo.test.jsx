// SubsideAnalysis in dynamo mode (runs through the Ensemble Manager) vs legacy.
// The Leaflet map is real (jsdom); geoman, the COG layer and auth are stubbed and
// every network call goes through one fetch router.
import L from 'leaflet'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const hoisted = vi.hoisted(() => ({ map: null, findRunItem: vi.fn() }))

vi.mock('react-leaflet', () => ({ useMap: () => hoisted.map, ImageOverlay: () => null }))
vi.mock('@geoman-io/leaflet-geoman-free', () => ({}))
vi.mock('@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css', () => ({}))
vi.mock('../StacCogLayer', () => ({ StacCogLayer: () => null }))
vi.mock('../../../lib/authContext', () => ({ useAuth: () => ({ token: 'tok', logout: vi.fn() }) }))
vi.mock('../../../lib/stacApi', async (orig) => ({
  ...(await orig()),
  stacEnabled: () => true,
  findRunItem: hoisted.findRunItem,
}))

import { SubsideAnalysis } from '../SubsideAnalysis'

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
})
const BBOX = [-97.2, 31.4, -97.0, 31.6]
const REQUEST = { id: 1, bbox: BBOX }
const AVAILABILITY = { items: [{ frame_id: 1, product_count: 3, timeline: ['2024-06-05', '2024-07-05', '2024-08-05'] }] }

let calls
let routes
function installFetch() {
  calls = []
  routes = {}
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET'
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ url: String(url), method, body, headers: init.headers })
    const key = Object.keys(routes).find((k) => `${method} ${url}`.includes(k))
    if (key) return typeof routes[key] === 'function' ? routes[key](body) : routes[key]
    if (String(url).includes('/availability')) return json(AVAILABILITY)
    if (String(url).includes('/plans/publishers')) {
      return json({ publishers: [{ catalog_tokens: ['ckan', 'stac'], can_publish: { ok: true } }] })
    }
    if (String(url).includes('/plans/runs')) return json({ runs: [] })
    return json({ message: `unrouted ${method} ${url}` }, 404)
  }))
}
const emCalls = (m, part) => calls.filter((c) => c.method === m && c.url.includes(part))

async function mount() {
  const panelHost = document.createElement('div')
  document.body.appendChild(panelHost)
  const view = render(<SubsideAnalysis panelHost={panelHost} analysisAoiRequest={REQUEST} />)
  await waitFor(() => expect(screen.getByText(/OPERA products? available/i)).toBeInTheDocument())
  return { view, panelHost }
}

beforeEach(() => {
  hoisted.map = L.map(document.body.appendChild(document.createElement('div')))
  hoisted.map.setView([31.5, -97.1], 9)
  hoisted.findRunItem.mockReset().mockResolvedValue(null)
  installFetch()
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('dynamo mode', () => {
  beforeEach(() => {
    window.__SUBSIDE_CONFIG__ = { VITE_RUN_BACKEND: 'dynamo', VITE_DYNAMO_API_BASE: 'http://em.test/v1' }
  })

  it('hides Earthdata and allocation fields; shows reference only for velocity (WERC)', async () => {
    await mount() // an image-bbox request selects the velocity (werc) pipeline
    expect(screen.queryByText(/earthdata/i)).toBeNull()
    expect(screen.queryByLabelText(/allocation/i)).toBeNull()
    expect(screen.getByText(/Reference point/i)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/What do you want to know/i), { target: { value: 'h2i' } })
    expect(screen.queryByText(/Reference point/i)).toBeNull()
  })

  it('submits region then scenario with a Bearer token, once, and lists the run', async () => {
    let release
    routes['POST http://em.test/v1/regions'] = () => json({ region_id: 'aoi-abc', created: true })
    routes['POST http://em.test/v1/plans/scenario'] = () => new Promise((resolve) => {
      release = () => resolve(json({ run_id: 'ue_1', thread_id: 'th1', status: 'planned', reused: false }))
    })
    await mount()
    await waitFor(() => expect(screen.getByLabelText(/Publish results/i)).toBeChecked())
    fireEvent.change(screen.getByLabelText(/What do you want to know/i), { target: { value: 'h2i' } })

    const button = screen.getByRole('button', { name: /Run analysis/i })
    fireEvent.click(button)
    fireEvent.click(button) // double click
    await waitFor(() => expect(screen.getByRole('button', { name: /Submitting/i })).toBeDisabled())
    await waitFor(() => expect(emCalls('POST', '/plans/scenario')).toHaveLength(1))

    const scenario = emCalls('POST', '/plans/scenario')[0]
    expect(scenario.headers.Authorization).toBe('Bearer tok')
    expect(scenario.body).toMatchObject({
      region: { region_id: 'aoi-abc' },
      model_id: 'https://w3id.org/okn/i/mint/opera-disp-s1-h2i-lab',
      start_date: expect.stringMatching(/^2024-0[6-8]-\d\d$/), // snapped into the OPERA availability span
      publish: ['ckan', 'stac'],
    })
    expect(Object.keys(scenario.body.parameter_values)).not.toContain('REFERENCE_MODE')
    expect(scenario.body.idempotency_key).toBeTruthy()
    expect(emCalls('POST', '/regions')).toHaveLength(1)

    await act(async () => { release() })
    await waitFor(() => expect(screen.getByRole('button', { name: /Run analysis/i })).toBeEnabled())
    expect(screen.getByText(/Queued on TACC/i)).toBeInTheDocument()
    // legacy API never touched
    expect(calls.some((c) => c.url.includes('/api/subside/runs'))).toBe(false)
  })

  it('shows the owner-secret message for SECRET_REQUIRED', async () => {
    routes['POST http://em.test/v1/regions'] = () => json({ region_id: 'aoi-abc', created: false })
    routes['POST http://em.test/v1/plans/scenario'] = () => json(
      { message: 'secret earthdata missing', code: 'SECRET_REQUIRED' }, 422,
    )
    await mount()
    fireEvent.click(screen.getByRole('button', { name: /Run analysis/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent("This model's owner has not provided its Earthdata login.")
  })

  it('shows DATES_CONFLICT with its message', async () => {
    routes['POST http://em.test/v1/regions'] = () => json({ region_id: 'aoi-abc', created: false })
    routes['POST http://em.test/v1/plans/scenario'] = () => json(
      { message: 'START_DATE differs from start_date', code: 'DATES_CONFLICT' }, 422,
    )
    await mount()
    fireEvent.click(screen.getByRole('button', { name: /Run analysis/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('START_DATE differs from start_date')
  })

  it('disables publishing with the reason when the caller cannot publish', async () => {
    routes['/plans/publishers'] = () => json({
      publishers: [{ catalog_tokens: ['ckan'], can_publish: { ok: false, reason: 'not a CKAN org member' } }],
    })
    await mount()
    const box = await screen.findByLabelText(/Publish results/i)
    expect(box).toBeDisabled()
    expect(box).not.toBeChecked()
    expect(screen.getByText('not a CKAN org member')).toBeInTheDocument()
  })

  it('results: window comes from the run row region and thread dates, not the legacy results endpoint', async () => {
    routes['GET http://em.test/v1/plans/runs?'] = () => json({
      runs: [{
        run_id: 'ue_9', name: 'WERC', thread_id: 'th9', model_id: 'https://w3id.org/okn/i/mint/opera-disp-s1-werc',
        status: 'completed', created_at: '2024-12-01T00:00:00Z',
        region: { id: 'aoi-9', name: 'AOI', bbox: BBOX },
        thread: { start_date: '2023-01-01', end_date: '2023-12-31' },
        output_handoff: { resource_uri: 'tapis://corral/out', publication: { status: 'failed', error: 'CKAN 403' } },
      }],
    })
    await mount()
    fireEvent.click(await screen.findByTitle('WERC'))

    await waitFor(() => expect(hoisted.findRunItem).toHaveBeenCalled())
    expect(hoisted.findRunItem.mock.calls[0][0]).toMatchObject({ bbox: BBOX, start: '2023-01-01', end: '2023-12-31' })
    // not published: failure + the model output location are shown
    const results = await screen.findByText(/Publication failed: CKAN 403/)
    expect(results).toHaveTextContent('tapis://corral/out')
    expect(calls.some((c) => c.url.includes('/api/subside/runs') || c.url.includes('/threads/'))).toBe(false)
  })

  it('after publication the Item behind output_handoff.publication.stac_item is used', async () => {
    routes['GET http://em.test/v1/plans/runs?'] = () => json({
      runs: [{
        run_id: 'ue_7', name: 'H2I', thread_id: 'th7', model_id: 'https://w3id.org/okn/i/mint/opera-disp-s1-h2i-lab',
        status: 'completed', created_at: '2024-12-01T00:00:00Z',
        output_handoff: { publication: { status: 'published', stac_item: 'http://stac.test/items/ue_7' } },
      }],
    })
    routes['GET http://stac.test/items/ue_7'] = () => json({
      id: 'ue_7', type: 'Feature', bbox: BBOX, properties: {},
      assets: { displacement: { href: 'http://x/d.tif', type: 'image/tiff', roles: ['data'] } },
    })
    await mount()
    fireEvent.click(await screen.findByTitle('H2I'))
    await waitFor(() => expect(calls.some((c) => c.url === 'http://stac.test/items/ue_7')).toBe(true))
    expect(hoisted.findRunItem).not.toHaveBeenCalled()
  })

  it('offers cancel only for running runs and maps RUN_NOT_CANCELLABLE', async () => {
    routes['GET http://em.test/v1/plans/runs?'] = () => json({
      runs: [{ run_id: 'ue_3', name: 'live', thread_id: 't3', model_id: 'x-h2i', status: 'adapter_running' }],
    })
    routes['GET http://em.test/v1/plans/runs/ue_3'] = () => json({ run_id: 'ue_3', status: 'adapter_running' })
    routes['POST http://em.test/v1/plans/runs/ue_3/cancel'] = () => json(
      { message: 'no active adapter run', code: 'RUN_NOT_CANCELLABLE' }, 409,
    )
    await mount()
    fireEvent.click(await screen.findByRole('button', { name: 'cancel' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('This run cannot be cancelled yet.')
  })

  it('does not offer cancel for a queued run', async () => {
    routes['GET http://em.test/v1/plans/runs?'] = () => json({
      runs: [{ run_id: 'ue_4', name: 'queued', thread_id: 't4', model_id: 'x-h2i', status: 'planned' }],
    })
    routes['GET http://em.test/v1/plans/runs/ue_4'] = () => json({ run_id: 'ue_4', status: 'planned' })
    await mount()
    await screen.findByText(/Queued on TACC/i)
    expect(screen.queryByRole('button', { name: 'cancel' })).toBeNull()
  })
})

describe('legacy mode (default)', () => {
  it('keeps the allocation field and never calls the Ensemble Manager', async () => {
    routes['/api/subside/runs'] = () => json({ runs: [] })
    await mount()
    expect(screen.getByText('Allocation')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Publish results/i)).toBeNull()
    expect(calls.some((c) => c.url.includes('em.test') || c.url.includes('/plans/'))).toBe(false)
    expect(calls.some((c) => c.method === 'GET' && c.url.endsWith('/api/subside/runs'))).toBe(true)
  })
})
