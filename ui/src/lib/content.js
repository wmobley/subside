// Site content loader.
//
// The site's editable text lives as Markdown files under `subside/ui/content/`
// (see content/README.md). This module reads those files at build time and
// hands the components plain objects — so non-developers edit Markdown, never
// JSX. To add/reorder cards, add/rename files in content/; nothing here changes.

// Vite inlines every matching file's raw text at build time. Globs must be
// string literals, so each collection gets its own call.
const ABOUT = import.meta.glob('../../content/about.md', { eager: true, query: '?raw', import: 'default' })
const PARTNERS = import.meta.glob('../../content/partners/*.md', { eager: true, query: '?raw', import: 'default' })
const GOALS = import.meta.glob('../../content/goals/*.md', { eager: true, query: '?raw', import: 'default' })
const WORKFLOWS = import.meta.glob('../../content/workflows/*.md', { eager: true, query: '?raw', import: 'default' })

// Split a Markdown file into its frontmatter fields and body text.
function parse(raw) {
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
  if (!match) return { data: {}, body: raw.trim() }
  const data = {}
  for (const line of match[1].split('\n')) {
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    const value = line.slice(idx + 1).trim().replace(/^["']|["']$/g, '')
    if (key) data[key] = value
  }
  return { data, body: match[2].trim() }
}

// Parse every file in a glob result, ordered by filename (so the numeric
// prefixes — 1-, 2-, … — control card order; numeric-aware so 10 follows 9).
function load(glob) {
  return Object.entries(glob)
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([, raw]) => parse(raw))
}

export function getAbout() {
  const entry = load(ABOUT)[0] || { data: {}, body: '' }
  return { ...entry.data, body: entry.body }
}

export function getPartners() {
  return load(PARTNERS).map(({ data, body }) => ({ ...data, description: body }))
}

export function getGoals() {
  return load(GOALS).map(({ data, body }) => ({ title: data.title, description: body }))
}

// Per-workflow documentation, keyed by the file's stem so callers fetch by
// pipeline id (e.g. content/workflows/h2i.md -> docs.h2i). Drop a new
// <pipeline>.md in content/workflows/ and that workflow gets docs automatically.
export function getWorkflowDocs() {
  const out = {}
  for (const [path, raw] of Object.entries(WORKFLOWS)) {
    const id = path.split('/').pop().replace(/\.md$/, '')
    const { data, body } = parse(raw)
    out[id] = { ...data, body }
  }
  return out
}

// Confirmed TWDB contract number for SUBSIDE. Shown on the About page and the
// site header (see PortalChrome).
export const CONTRACT_LABEL = 'TWDB Contract #2401792868'
