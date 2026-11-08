import { describe, expect, it } from 'vitest'

import { collectionList } from '../stacApi'

describe('collectionList', () => {
  it('splits a comma-separated setting and trims it', () => {
    expect(collectionList('subsidence-rates, subsidence-rates-dev ')).toEqual(['subsidence-rates', 'subsidence-rates-dev'])
  })
  it('keeps a single collection a single collection', () => {
    expect(collectionList('subsidence-rates-dev')).toEqual(['subsidence-rates-dev'])
  })
  it('falls back to the published collection when the setting is empty', () => {
    expect(collectionList('')).toEqual(['subsidence-rates'])
    expect(collectionList(' , ')).toEqual(['subsidence-rates'])
  })
})
