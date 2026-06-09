export async function requestJson(url, options = {}) {
  const { headers: optionHeaders, ...rest } = options
  const response = await fetch(url, {
    ...rest,
    // Merge headers last so caller headers (e.g. X-Tapis-Token) don't clobber
    // Content-Type — spreading ...options after a headers key would drop it.
    headers: { 'Content-Type': 'application/json', ...(optionHeaders || {}) },
  })
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    const snippet = text.slice(0, 160).replace(/\s+/g, ' ').trim()
    throw new Error(`Expected JSON from ${url}, got ${response.status} ${response.statusText}: ${snippet}`)
  }
  const payload = await response.json()
  if (!response.ok) {
    // FastAPI puts the reason in `detail` (a string, or a list of validation
    // errors); fall back to error/message for the other backend.
    let detail = payload.detail
    if (Array.isArray(detail)) {
      detail = detail.map((d) => `${(d.loc || []).join('.')}: ${d.msg}`).join('; ')
    }
    throw new Error(detail || payload.error || payload.message || 'Request failed')
  }
  return payload
}
