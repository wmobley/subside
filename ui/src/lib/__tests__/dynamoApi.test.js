import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../dynamoApi'
import { bboxToAoiGeoJSON } from '../subsideApi'

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'content-type': 'application/json' },
})

let fetchMock
beforeEach(() => {
  window.__SUBSIDE_CONFIG__ = { VITE_DYNAMO_API_BASE: 'http://em.test/v1/' }
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

const lastCall = () => {
  const [url, init] = fetchMock.mock.calls.at(-1)
  return { url, init, body: init.body ? JSON.parse(init.body) : undefined }
}

describe('request shapes', () => {
  it('createRegion posts name + geojson with a Bearer token', async () => {
    fetchMock.mockResolvedValue(json({ region_id: 'aoi-1', created: true }))
    const geojson = { type: 'FeatureCollection', features: [] }
    await expect(api.createRegion('tok', { name: 'Waco', geojson })).resolves.toEqual({ region_id: 'aoi-1', created: true })
    const { url, init, body } = lastCall()
    expect(url).toBe('http://em.test/v1/regions')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers['X-Tapis-Token']).toBeUndefined()
    expect(body).toEqual({ name: 'Waco', geojson })
  })

  it('createRegion posts exactly the FeatureCollection bboxToAoiGeoJSON produces (shared EM fixture)', async () => {
    fetchMock.mockImplementation(async () => json({ region_id: 'aoi-1', created: true }))
    const geojson = bboxToAoiGeoJSON([-97.35, 31.4, -96.95, 31.7])
    expect(geojson).toEqual({
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [[[-97.35, 31.4], [-96.95, 31.4], [-96.95, 31.7], [-97.35, 31.7], [-97.35, 31.4]]],
        },
      }],
    })
    await api.createRegion('tok', { name: 'Waco', geojson })
    expect(lastCall().body.geojson).toEqual(geojson)
  })

  it('submitScenario builds the spec body: WERC, dates once, idempotency key', async () => {
    fetchMock.mockResolvedValue(json({ run_id: 'ue_1', status: 'planned', reused: false }))
    await api.submitScenario('tok', {
      pipeline: 'werc', regionId: 'aoi-1', startDate: '2024-01-01', endDate: '2024-12-31',
      minOverlapPercent: 60, reference: { lat: 31.5, lon: -97.1 }, publish: ['ckan', 'stac'], maxMinutes: 240.4,
    })
    const { url, init, body } = lastCall()
    expect(url).toBe('http://em.test/v1/plans/scenario')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(body.idempotency_key).toMatch(/^[0-9a-f-]{36}$/)
    expect(body).toMatchObject({
      app_label: 'SUBSIDE',
      model_id: 'https://w3id.org/okn/i/mint/opera-disp-s1-werc',
      region: { region_id: 'aoi-1' },
      start_date: '2024-01-01', end_date: '2024-12-31',
      publish: ['ckan', 'stac'], max_minutes: 240,
    })
    expect(body.name).toBe('WERC 2024-01-01..2024-12-31')
    expect(body.parameter_values).toEqual({
      NUM_WORKERS: 4, MIN_OVERLAP_PERCENT: 60, REFERENCE_MODE: 'point',
      REFERENCE_LAT: 31.5, REFERENCE_LON: -97.1, ANCHOR_RADIUS_M: 5000, N_REFERENCE_PIXELS: 25,
    })
    // dates are not duplicated in parameter_values
    expect(body.parameter_values).not.toHaveProperty('START_DATE')
    expect(body.parameter_values).not.toHaveProperty('END_DATE')
  })

  it('WERC without a reference point uses auto and no lat/lon', () => {
    const v = api.buildParameterValues('werc', {})
    expect(v.REFERENCE_MODE).toBe('auto')
    expect(v).not.toHaveProperty('REFERENCE_LAT')
  })

  it('H2I uses its model id and sends no reference or earthdata parameters', async () => {
    fetchMock.mockResolvedValue(json({ run_id: 'ue_2', status: 'planned' }))
    await api.submitScenario('tok', {
      pipeline: 'h2i', regionId: 'aoi-1', startDate: '2024-06-01', endDate: '2024-09-01',
      reference: { lat: 1, lon: 2 },
    })
    const { body } = lastCall()
    expect(body.model_id).toBe('https://w3id.org/okn/i/mint/opera-disp-s1-h2i-lab')
    expect(Object.keys(body.parameter_values).sort()).toEqual(['MIN_OVERLAP_PERCENT', 'NUM_WORKERS'])
    expect(JSON.stringify(body).toLowerCase()).not.toContain('earthdata')
    expect(body.publish).toEqual([])
  })

  it('each submission gets its own idempotency key unless one is supplied', async () => {
    fetchMock.mockImplementation(async () => json({ run_id: 'ue_3' }))
    const p = { pipeline: 'h2i', regionId: 'r', startDate: '2024-01-01', endDate: '2024-02-01' }
    await api.submitScenario('t', p)
    const a = lastCall().body.idempotency_key
    await api.submitScenario('t', p)
    const b = lastCall().body.idempotency_key
    expect(a).not.toBe(b)
    await api.submitScenario('t', { ...p, idempotencyKey: 'fixed' })
    expect(lastCall().body.idempotency_key).toBe('fixed')
  })

  it('the keyer reuses a key for an identical retry and rotates otherwise', () => {
    let n = 0
    const keyer = api.createSubmissionKeyer(() => `k${++n}`)
    expect(keyer.keyFor('a')).toBe('k1')
    expect(keyer.keyFor('a')).toBe('k1')
    expect(keyer.keyFor('b')).toBe('k2')
    keyer.reset()
    expect(keyer.keyFor('b')).toBe('k3')
  })

  it('listRuns, getRun, cancelRun, getPublishers hit the spec routes', async () => {
    fetchMock.mockResolvedValue(json({ runs: [{ run_id: 'ue_1', status: 'failed', failure_code: 'CANCELLED_BY_USER', model_id: 'x-werc', thread_id: 't1' }] }))
    const rows = await api.listRuns('tok')
    expect(lastCall().url).toBe('http://em.test/v1/plans/runs?app_label=SUBSIDE&limit=50')
    expect(rows[0]).toMatchObject({ runId: 'ue_1', status: 'cancelled', threadId: 't1', pipeline: 'werc' })

    fetchMock.mockResolvedValue(json({ run_id: 'ue_1', status: 'model_running' }))
    expect((await api.getRun('tok', 'ue_1')).status).toBe('running')
    expect(lastCall().url).toBe('http://em.test/v1/plans/runs/ue_1')

    fetchMock.mockResolvedValue(json({ ok: true }))
    await api.cancelRun('tok', 'ue_1')
    expect(lastCall().url).toBe('http://em.test/v1/plans/runs/ue_1/cancel')
    expect(lastCall().init.method).toBe('POST')

    fetchMock.mockResolvedValue(json({ publishers: [] }))
    await api.getPublishers('tok', api.MODEL_IDS.werc)
    expect(lastCall().url).toBe(`http://em.test/v1/plans/publishers?model_id=${encodeURIComponent(api.MODEL_IDS.werc)}`)
  })

  it('errors carry the EM code, step and status', async () => {
    fetchMock.mockResolvedValue(json({ message: 'no secret', code: 'SECRET_REQUIRED' }, 422))
    const err = await api.createRegion('t', { name: 'n', geojson: {} }).catch((e) => e)
    expect(err).toBeInstanceOf(api.DynamoError)
    expect(err).toMatchObject({ status: 422, code: 'SECRET_REQUIRED' })
    expect(api.dynamoErrorMessage(err)).toBe("This model's owner has not provided its Earthdata login.")

    fetchMock.mockResolvedValue(json({ message: 'dates differ', code: 'DATES_CONFLICT' }, 422))
    expect(api.dynamoErrorMessage(await api.getRun('t', 'x').catch((e) => e))).toBe('dates differ')
    fetchMock.mockResolvedValue(json({ message: 'nothing active', code: 'RUN_NOT_CANCELLABLE' }, 409))
    expect(api.dynamoErrorMessage(await api.cancelRun('t', 'x').catch((e) => e))).toBe('This run cannot be cancelled yet.')
    fetchMock.mockResolvedValue(json({ message: 'dry run needs a post-model adapter', code: 'DRY_RUN_UNSUPPORTED' }, 422))
    expect(api.dynamoErrorMessage(await api.getRun('t', 'x').catch((e) => e))).toBe('dry run needs a post-model adapter')
    fetchMock.mockResolvedValue(json({ message: 'bad ring', code: 'REGION_INVALID' }, 422))
    expect(api.dynamoErrorMessage(await api.getRun('t', 'x').catch((e) => e))).toBe('bad ring')
    fetchMock.mockResolvedValue(json({ message: 'boom', code: 'SCENARIO_STEP_FAILED', details: { step: 'thread', created: { task_id: 't' } } }, 500))
    const stepErr = await api.getRun('t', 'x').catch((e) => e)
    expect(stepErr.step).toBe('thread')
    expect(stepErr.created).toEqual({ task_id: 't' })
    expect(api.dynamoErrorMessage(stepErr)).toContain('thread')
    fetchMock.mockResolvedValue(json({ message: 'expired' }, 401))
    expect(api.isAuthError(await api.getRun('t', 'x').catch((e) => e))).toBe(true)
  })
})

describe('toSubsideStatus', () => {
  const table = {
    planned: 'queued', model_dispatching: 'queued', model_submitted: 'queued',
    model_running: 'running', model_succeeded: 'running', output_registering: 'running',
    output_verifying: 'running', output_verified: 'running', adapter_dispatching: 'running',
    adapter_running: 'running',
    completed: 'completed',
    unknown: 'unknown', model_unknown: 'unknown', adapter_unknown: 'unknown',
  }
  it.each(Object.entries(table))('%s -> %s', (from, to) => {
    expect(api.toSubsideStatus(from)).toBe(to)
  })
  it('failed is cancelled only for CANCELLED_BY_USER', () => {
    expect(api.toSubsideStatus('failed', 'CANCELLED_BY_USER')).toBe('cancelled')
    expect(api.toSubsideStatus('failed', 'OTHER')).toBe('failed')
    expect(api.toSubsideStatus('failed')).toBe('failed')
  })
  it('anything unrecognised is unknown', () => {
    expect(api.toSubsideStatus('brand_new_state')).toBe('unknown')
    expect(api.toSubsideStatus(undefined)).toBe('unknown')
  })
})

describe('publishChoice', () => {
  it('defaults to every token when publishing is allowed', () => {
    expect(api.publishChoice({ publishers: [{ catalog_tokens: ['ckan', 'stac'], can_publish: { ok: true } }] }))
      .toEqual({ ok: true, tokens: ['ckan', 'stac'], reason: '' })
    expect(api.publishChoice({ publishers: [{ catalog_tokens: 'ckan+stac', can_publish: { ok: true } }] }).tokens)
      .toEqual(['ckan', 'stac'])
  })
  it('is disabled with the reason otherwise', () => {
    expect(api.publishChoice({ publishers: [{ catalog_tokens: ['ckan'], can_publish: { ok: false, reason: 'not a CKAN member' } }] }))
      .toEqual({ ok: false, tokens: [], reason: 'not a CKAN member' })
    expect(api.publishChoice({}).ok).toBe(false)
  })
})

describe('polling', () => {
  it('backs off 5 s -> 15 s -> 60 s', () => {
    expect(api.runsPollingDelay(0)).toBe(5000)
    expect(api.runsPollingDelay(5)).toBe(5000)
    expect(api.runsPollingDelay(6)).toBe(15000)
    expect(api.runsPollingDelay(7)).toBe(15000)
    expect(api.runsPollingDelay(8)).toBe(60000)
    expect(api.runsPollingDelay(50)).toBe(60000)
  })

  const fakeDoc = () => {
    const listeners = new Set()
    return {
      hidden: false,
      addEventListener: (_, f) => listeners.add(f),
      removeEventListener: (_, f) => listeners.delete(f),
      setHidden(h) { this.hidden = h; listeners.forEach((f) => f()) },
    }
  }

  it('follows the schedule, stops when fn returns false', async () => {
    vi.useFakeTimers()
    const doc = fakeDoc()
    const fn = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false)
    api.startPolling(fn, { doc })
    await vi.advanceTimersByTimeAsync(4999)
    expect(fn).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(fn).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(120000)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('pauses while hidden and resumes when visible', async () => {
    vi.useFakeTimers()
    const doc = fakeDoc()
    const fn = vi.fn().mockResolvedValue(true)
    const stop = api.startPolling(fn, { doc })
    doc.setHidden(true)
    await vi.advanceTimersByTimeAsync(600000)
    expect(fn).not.toHaveBeenCalled()
    doc.setHidden(false)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(1)
    stop()
    await vi.advanceTimersByTimeAsync(600000)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('does not start a timer when created while hidden', async () => {
    vi.useFakeTimers()
    const doc = fakeDoc()
    doc.hidden = true
    const fn = vi.fn().mockResolvedValue(true)
    api.startPolling(fn, { doc })
    await vi.advanceTimersByTimeAsync(600000)
    expect(fn).not.toHaveBeenCalled()
  })

  it('keeps polling after fn throws', async () => {
    vi.useFakeTimers()
    const fn = vi.fn().mockRejectedValueOnce(new Error('x')).mockResolvedValue(true)
    api.startPolling(fn, { doc: fakeDoc() })
    await vi.advanceTimersByTimeAsync(10000)
    expect(fn).toHaveBeenCalledTimes(2)
  })
})

describe('resolveRunWindow', () => {
  const bbox = [-97.2, 31.4, -97.0, 31.6]
  it('normalizeRun maps region and thread from the EM row', () => {
    const row = api.normalizeRun({
      run_id: 'ue_1', status: 'completed',
      region: { id: 'aoi-1', name: 'AOI', bbox }, thread: { start_date: '2024-01-01', end_date: '2024-12-31' },
    })
    expect(row.region.bbox).toEqual(bbox)
    expect(row.thread.end_date).toBe('2024-12-31')
  })

  it('prefers the run row region.bbox and thread dates over cache and drawing', () => {
    api.rememberRunRegion('ue_1', { bbox: [9, 9, 9, 9], start: '2020-01-01', end: '2020-02-01' })
    const win = api.resolveRunWindow(
      { runId: 'ue_1', region: { bbox }, thread: { start_date: '2024-01-01T00:00:00Z', end_date: '2024-12-31' } },
      { drawnBbox: [0, 0, 1, 1] },
    )
    expect(win).toEqual({ bbox, start: '2024-01-01', end: '2024-12-31' })
  })

  it('falls back to the per-run cache, then the live drawing and form dates', () => {
    api.rememberRunRegion('ue_2', { bbox, start: '2023-01-01', end: '2023-02-01' })
    expect(api.resolveRunWindow({ runId: 'ue_2' }, { drawnBbox: [0, 0, 1, 1] }))
      .toEqual({ bbox, start: '2023-01-01', end: '2023-02-01' })
    expect(api.resolveRunWindow({ runId: 'ue_3' }, { drawnBbox: bbox, fallbackDates: { start: '2024-06-01', end: '2024-09-01' } }))
      .toEqual({ bbox, start: '2024-06-01', end: '2024-09-01' })
  })

  it('no longer reads the thread route', () => {
    expect(api.getThread).toBeUndefined()
  })
})
