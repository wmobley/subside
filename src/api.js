export async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    const text = await response.text()
    const snippet = text.slice(0, 160).replace(/\s+/g, ' ').trim()
    throw new Error(`Expected JSON from ${url}, got ${response.status} ${response.statusText}: ${snippet}`)
  }
  const payload = await response.json()
  if (!response.ok) {
    throw new Error(payload.error || payload.message || 'Request failed')
  }
  return payload
}
