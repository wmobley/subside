// Contract: every catalog parameter the SUBSIDE -> DYNAMO mapping uses must exist
// in the OPERA model-catalog YAML with the label and type dynamoApi.js expects.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { parse } from 'yaml'

import { MODEL_IDS, PARAMETER_CONTRACT, PIPELINE_PARAMETERS } from '../dynamoApi'

const here = path.dirname(fileURLToPath(import.meta.url))
const CATALOG = path.resolve(here, '../../../../tapis/workflow_apps/opera-disp-s1.model-catalog.yaml')
const doc = parse(fs.readFileSync(CATALOG, 'utf8'))

// Depth-first search for the ModelConfiguration node with the given local id.
function findConfiguration(node, id) {
  if (Array.isArray(node)) {
    for (const n of node) { const f = findConfiguration(n, id); if (f) return f }
  } else if (node && typeof node === 'object') {
    if (node.id === id && [].concat(node.type || []).includes('ModelConfiguration')) return node
    for (const v of Object.values(node)) { const f = findConfiguration(v, id); if (f) return f }
  }
  return null
}

const first = (v) => (Array.isArray(v) ? v[0] : v)

describe.each(Object.entries(MODEL_IDS))('%s configuration', (pipeline, modelId) => {
  const localId = modelId.split('/').pop()
  const config = findConfiguration(doc, localId)

  it('exists in the catalog', () => {
    expect(config, `${localId} not found in ${CATALOG}`).toBeTruthy()
  })

  const byKey = Object.fromEntries((config?.hasParameter || []).map((p) => [p.tapisEnvKey, p]))

  it.each(PIPELINE_PARAMETERS[pipeline])('maps %s with the expected label and type', (key) => {
    const param = byKey[key]
    expect(param, `${key} missing from ${localId}`).toBeTruthy()
    expect(first(param.label)).toBe(PARAMETER_CONTRACT[key].label)
    expect(first(param.hasDataType)).toBe(PARAMETER_CONTRACT[key].type)
  })

  it('has the date parameters the EM derives from the top-level dates', () => {
    expect(first(byKey.START_DATE?.hasDataType)).toBe('date')
    expect(first(byKey.END_DATE?.hasDataType)).toBe('date')
  })
})

it('H2I has no reference parameters (the UI hides them)', () => {
  const h2i = findConfiguration(doc, MODEL_IDS.h2i.split('/').pop())
  const keys = (h2i.hasParameter || []).map((p) => p.tapisEnvKey)
  expect(keys.filter((k) => k.startsWith('REFERENCE_'))).toEqual([])
})
