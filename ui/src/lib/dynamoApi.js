// Client for the MINT Ensemble Manager (DYNAMO), used when VITE_RUN_BACKEND=dynamo.
//
// SUBSIDE submits, lists and reads OPERA DISP-S1 runs through the EM instead of
// the SUBSIDE API's own Tapis Workflows pipelines. Auth is the Tapis JWT the
// SUBSIDE login already holds, sent as `Authorization: Bearer` (the SUBSIDE API
// takes the same token as X-Tapis-Token). Contract: monorepo
// docs/design/2026-11-05-subside-runs-through-dynamo.md.
import { dynamoApiBase } from './runtimeConfig'

export const APP_LABEL = 'SUBSIDE'

export const MODEL_IDS = {
  werc: 'https://w3id.org/okn/i/mint/opera-disp-s1-werc',
  h2i: 'https://w3id.org/okn/i/mint/opera-disp-s1-h2i-lab',
}

// --- parameter mapping (spec section 4) --------------------------------------
// Catalog parameter (tapisEnvKey) -> the label and type the SUBSIDE UI relies on.
// dynamoApi.contract.test.js checks these against opera-disp-s1.model-catalog.yaml
// so a renamed/retyped catalog parameter fails a test, not a run.
// START_DATE / END_DATE are deliberately absent: the EM derives them from the
// single top-level start_date/end_date pair (sending them is a DATES_CONFLICT risk).
export const PARAMETER_CONTRACT = {
  NUM_WORKERS: { label: 'Download workers', type: 'int' },
  MIN_OVERLAP_PERCENT: { label: 'Min overlap percent', type: 'float' },
  REFERENCE_MODE: { label: 'Reference mode', type: 'string' },
  REFERENCE_LAT: { label: 'Reference latitude', type: 'float' },
  REFERENCE_LON: { label: 'Reference longitude', type: 'float' },
  ANCHOR_RADIUS_M: { label: 'Anchor radius (m)', type: 'int' },
  N_REFERENCE_PIXELS: { label: 'Reference pixel count', type: 'int' },
}

// Which mapped parameters each pipeline's catalog configuration has. H2I has no
// reference parameters.
export const PIPELINE_PARAMETERS = {
  werc: Object.keys(PARAMETER_CONTRACT),
  h2i: ['NUM_WORKERS', 'MIN_OVERLAP_PERCENT'],
}

// Which form sections apply for a backend + pipeline. In dynamo mode the
// allocation is a managed plan parameter and the Earthdata login is the model
// owner's secret, so neither is asked of the user; H2I has no reference
// parameters in its catalog configuration.
export function formSections(backend, pipeline) {
  return {
    allocation: backend !== 'dynamo',
    earthdata: false, // never in the UI; legacy uses the API service account
    reference: pipeline === 'werc',
    publish: backend === 'dynamo',
  }
}

// --- errors ---------------------------------------------------------------------

// EM error bodies are `{ message, code, details }` (SCENARIO_STEP_FAILED carries
// `details: { step, created }`). `code` is what the UI branches on.
export class DynamoError extends Error {
  constructor(message, { status, code, step, created, body } = {}) {
    super(message)
    this.name = 'DynamoError'
    this.status = status
    this.code = code
    this.step = step
    this.created = created
    this.body = body
  }
}

// User-facing message for a failed call. SECRET_REQUIRED is relayed from the
// adapter when the model owner has not stored the Earthdata login.
export function dynamoErrorMessage(err) {
  if (err?.code === 'SECRET_REQUIRED') {
    return "This model's owner has not provided its Earthdata login."
  }
  if (err?.code === 'RUN_NOT_CANCELLABLE') return 'This run cannot be cancelled yet.'
  // DRY_RUN_UNSUPPORTED (422) and the other codes fall through to the EM's message.
  if (err?.code === 'SCENARIO_STEP_FAILED') {
    return `Setting up the run failed at the "${err.step || 'unknown'}" step${err.message ? `: ${err.message}` : '.'}`
  }
  return err?.message || 'Request failed'
}

// True when the token was rejected, so the caller should force a re-login.
export function isAuthError(err) {
  return err?.status === 401
}

async function dynamoRequest(token, path, { method = 'GET', body } = {}) {
  const base = dynamoApiBase()
  if (!base) throw new DynamoError('VITE_DYNAMO_API_BASE is not set.')
  const url = `${base}${path}`
  const headers = { Authorization: `Bearer ${token}` }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const isJson = (response.headers.get('content-type') || '').includes('application/json')
  const payload = isJson ? await response.json() : null
  if (!response.ok) {
    const p = payload || {}
    throw new DynamoError(
      p.message || p.error?.message || (typeof p.detail === 'string' ? p.detail : '')
        || `Request failed (${response.status} ${response.statusText})`,
      {
        status: response.status,
        code: p.code || p.error?.code || p.detail?.code,
        step: p.details?.step ?? p.step,
        created: p.details?.created ?? p.created,
        body: payload,
      },
    )
  }
  return payload ?? {}
}

// --- status vocabulary (spec section 3) ----------------------------------------

const QUEUED = new Set(['planned', 'model_dispatching', 'model_submitted'])
const RUNNING = new Set([
  'model_running', 'model_succeeded', 'output_registering', 'output_verifying',
  'output_verified', 'adapter_dispatching', 'adapter_running',
])
export const CANCELLED_CODE = 'CANCELLED_BY_USER'

// Unified EM status (+ failure_code) -> the SUBSIDE display vocabulary:
// queued | running | completed | failed | cancelled | unknown.
export function toSubsideStatus(status, failureCode) {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return failureCode === CANCELLED_CODE ? 'cancelled' : 'failed'
  if (QUEUED.has(status)) return 'queued'
  if (RUNNING.has(status)) return 'running'
  return 'unknown' // unknown, model_unknown, adapter_unknown, or anything new
}

export const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])
export const isTerminalStatus = (s) => TERMINAL_STATUSES.has(s)

// --- run rows --------------------------------------------------------------------

export function pipelineForModel(modelId) {
  const id = String(modelId || '')
  if (id.includes('werc')) return 'werc'
  if (id.includes('h2i')) return 'h2i'
  return null
}

// An EM run record (list row or getRun response) -> the row shape the run list
// renders. Fields the record does not carry are left undefined so a getRun
// response can be merged over a list row without erasing it.
export function normalizeRun(raw = {}) {
  const status = raw.status
  const failureCode = raw.failure_code ?? raw.failureCode
  const row = {
    runId: raw.run_id ?? raw.runId ?? raw.id,
    name: raw.name,
    threadId: raw.thread_id ?? raw.threadId,
    modelId: raw.model_id ?? raw.modelId,
    rawStatus: status,
    failureCode,
    created: raw.created_at ?? raw.created,
    handoff: raw.output_handoff ?? raw.outputHandoff,
    region: raw.region,
    thread: raw.thread,
  }
  if (status !== undefined) row.status = toSubsideStatus(status, failureCode)
  const pipeline = pipelineForModel(row.modelId)
  if (pipeline) row.pipeline = pipeline
  return Object.fromEntries(Object.entries(row).filter(([, v]) => v !== undefined))
}

// --- region + scenario ---------------------------------------------------------------

// Create-or-find a region from GeoJSON. Returns { region_id, created }.
export function createRegion(token, { name, geojson, categoryId, parentRegionId }) {
  const body = { name, geojson }
  if (categoryId) body.category_id = categoryId
  if (parentRegionId) body.parent_region_id = parentRegionId
  return dynamoRequest(token, '/regions', { method: 'POST', body })
}

// parameter_values for the pipeline from SUBSIDE form values. Only parameters
// the pipeline's catalog configuration has are sent, and never START/END_DATE.
export function buildParameterValues(pipeline, {
  numWorkers = 4, minOverlapPercent = 50, reference, anchorRadiusM = 5000, nReferencePixels = 25,
} = {}) {
  const values = {
    NUM_WORKERS: Number(numWorkers),
    MIN_OVERLAP_PERCENT: Number(minOverlapPercent),
  }
  if (pipeline === 'werc') {
    const point = reference && Number.isFinite(Number(reference.lat)) && Number.isFinite(Number(reference.lon))
    values.REFERENCE_MODE = point ? 'point' : 'auto'
    if (point) {
      values.REFERENCE_LAT = Number(reference.lat)
      values.REFERENCE_LON = Number(reference.lon)
    }
    values.ANCHOR_RADIUS_M = Number(anchorRadiusM)
    values.N_REFERENCE_PIXELS = Number(nReferencePixels)
  }
  return values
}

// The POST /plans/scenario body (spec section 2).
export function buildScenarioBody({
  pipeline, regionId, startDate, endDate, name, publish, maxMinutes, idempotencyKey, dryRun, ...formValues
}) {
  const modelId = MODEL_IDS[pipeline]
  if (!modelId) throw new Error(`Unknown pipeline: ${pipeline}`)
  const body = {
    idempotency_key: idempotencyKey,
    app_label: APP_LABEL,
    name: name || `${pipeline === 'werc' ? 'WERC' : 'H2I'} ${startDate}..${endDate}`,
    region: { region_id: regionId },
    model_id: modelId,
    start_date: startDate,
    end_date: endDate,
    parameter_values: buildParameterValues(pipeline, formValues),
    publish: publish || [],
  }
  if (maxMinutes != null) body.max_minutes = Math.round(Number(maxMinutes))
  if (dryRun) body.dry_run = true
  return body
}

// Create the run in one call. `idempotencyKey` defaults to a fresh UUID; pass the
// same key when retrying the same submission so a lost response cannot start a
// second HPC job. Returns { problem_statement_id, task_id, thread_id, plan_id,
// run_id, status, reused }.
export function submitScenario(token, params) {
  const body = buildScenarioBody({
    ...params,
    idempotencyKey: params.idempotencyKey || globalThis.crypto.randomUUID(),
  })
  return dynamoRequest(token, '/plans/scenario', { method: 'POST', body })
}

// One key per form submission: the same key while the submission is identical
// (a retry after a failure), a new one after success or when the form changed.
export function createSubmissionKeyer(makeKey = () => globalThis.crypto.randomUUID()) {
  let current = null
  return {
    keyFor(fingerprint) {
      if (!current || current.fingerprint !== fingerprint) current = { fingerprint, key: makeKey() }
      return current.key
    },
    reset() { current = null },
  }
}

// --- runs --------------------------------------------------------------------------------

// Stored rows (status is NOT reconciled; read each active row with getRun).
export async function listRuns(token, appLabel = APP_LABEL, limit = 50) {
  const q = new URLSearchParams({ app_label: appLabel, limit: String(limit) })
  const res = await dynamoRequest(token, `/plans/runs?${q.toString()}`)
  return (res.runs || []).map(normalizeRun)
}

// Reconciled status, incl. output_handoff.publication.
export async function getRun(token, runId) {
  return normalizeRun(await dynamoRequest(token, `/plans/runs/${encodeURIComponent(runId)}`))
}

// 409 RUN_NOT_CANCELLABLE when no adapter child is active.
export function cancelRun(token, runId) {
  return dynamoRequest(token, `/plans/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' })
}

export function getPublishers(token, modelId) {
  return dynamoRequest(token, `/plans/publishers?model_id=${encodeURIComponent(modelId)}`)
}

// Publish choice from GET /plans/publishers: default every catalog token the
// caller may publish to; disabled with the adapter's reason otherwise.
export function publishChoice(response) {
  const publishers = response?.publishers || []
  const tokens = []
  let reason = ''
  for (const p of publishers) {
    if (p?.can_publish?.ok) {
      const list = Array.isArray(p.catalog_tokens)
        ? p.catalog_tokens
        : String(p.catalog_tokens || '').split('+')
      for (const t of list) if (t && !tokens.includes(t)) tokens.push(t)
    } else if (!reason) {
      reason = p?.can_publish?.reason || ''
    }
  }
  if (tokens.length) return { ok: true, tokens, reason: '' }
  return { ok: false, tokens: [], reason: reason || 'Publishing is not available for this model.' }
}

// --- polling ---------------------------------------------------------------------------------

// Delay before the next read of an active run: 5 s for the first 30 s, 15 s for
// the next 30 s, then once a minute.
export function runsPollingDelay(attempt) {
  if (attempt < 6) return 5000
  if (attempt < 8) return 15000
  return 60000
}

// Run `fn(attempt)` on the backoff schedule until it returns false or stop() is
// called. Paused while the document is hidden; on return to the tab the schedule
// restarts from the short delay. `fn` errors do not stop polling.
export function startPolling(fn, {
  getDelay = runsPollingDelay, doc = typeof document === 'undefined' ? null : document,
} = {}) {
  let attempt = 0
  let timer = null
  let stopped = false

  const clear = () => { if (timer !== null) { clearTimeout(timer); timer = null } }
  const schedule = () => {
    clear()
    if (stopped || doc?.hidden) return
    timer = setTimeout(async () => {
      timer = null
      let again = true
      try { again = (await fn(attempt)) !== false } catch { /* keep polling */ }
      attempt += 1
      if (again) schedule(); else stopped = true
    }, getDelay(attempt))
  }
  const onVisibility = () => {
    if (stopped) return
    if (doc.hidden) { clear(); return }
    attempt = 0
    schedule()
  }
  doc?.addEventListener?.('visibilitychange', onVisibility)
  schedule()
  return () => {
    stopped = true
    clear()
    doc?.removeEventListener?.('visibilitychange', onVisibility)
  }
}

// --- results window (spec section 5) --------------------------------------------------------------

const REGION_CACHE_KEY = 'subside.dynamoRunRegions'

// The UI drew the region, so remember its bbox + dates per run for later reloads.
export function rememberRunRegion(runId, { bbox, start, end }) {
  try {
    const all = JSON.parse(localStorage.getItem(REGION_CACHE_KEY) || '{}')
    all[runId] = { bbox, start, end }
    localStorage.setItem(REGION_CACHE_KEY, JSON.stringify(all))
  } catch { /* storage unavailable: reload falls back to the thread's region */ }
}

export function recallRunRegion(runId) {
  try {
    return JSON.parse(localStorage.getItem(REGION_CACHE_KEY) || '{}')[runId] || null
  } catch { return null }
}

const day = (d) => (d ? String(d).slice(0, 10) : undefined)

// bbox + date window for the STAC lookup of a run. The EM run row carries
// `region.bbox` and `thread.start_date/end_date`; those win. Then the per-run
// cache written at submit, then the live drawing / form dates.
export function resolveRunWindow(run, { drawnBbox, fallbackDates } = {}) {
  const cached = recallRunRegion(run.runId)
  const bbox = run.region?.bbox
  return {
    bbox: (Array.isArray(bbox) && bbox.length === 4 ? bbox : null) || cached?.bbox || drawnBbox || null,
    start: day(run.thread?.start_date) || cached?.start || fallbackDates?.start,
    end: day(run.thread?.end_date) || cached?.end || fallbackDates?.end,
  }
}

// The STAC Item JSON a published run points at (output_handoff.publication.stac_item).
export async function fetchStacItem(url) {
  const resp = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!resp.ok) throw new Error(`STAC item fetch failed: ${resp.status} ${resp.statusText}`)
  return resp.json()
}
