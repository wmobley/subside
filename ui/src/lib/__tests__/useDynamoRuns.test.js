import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../dynamoApi', async () => {
  const actual = await vi.importActual('../dynamoApi')
  return { ...actual, listRuns: vi.fn(), getRun: vi.fn(), startPolling: vi.fn(() => () => {}) }
})

import { DynamoError, listRuns } from '../dynamoApi'
import { useDynamoRuns } from '../useDynamoRuns'

const unauthorized = () => new DynamoError('expired', { status: 401 })

describe('useDynamoRuns auth errors', () => {
  beforeEach(() => { listRuns.mockReset() })

  it('logs out when the current token is rejected', async () => {
    listRuns.mockRejectedValue(unauthorized())
    const onAuthError = vi.fn()
    renderHook(() => useDynamoRuns('fresh', true, { onAuthError }))
    await act(async () => {})
    expect(onAuthError).toHaveBeenCalledTimes(1)
  })

  it('ignores a 401 for a token that was replaced before the response arrived', async () => {
    // A stale session from localStorage is asked first; the user then logs in and
    // the fresh token is stored before the stale request's 401 comes back.
    let rejectStale
    listRuns.mockImplementation((token) => token === 'stale'
      ? new Promise((_resolve, reject) => { rejectStale = reject })
      : Promise.resolve([]))
    const onAuthError = vi.fn()
    const { result, rerender } = renderHook(({ token }) => useDynamoRuns(token, true, { onAuthError }), {
      initialProps: { token: 'stale' },
    })
    rerender({ token: 'fresh' })
    await act(async () => { rejectStale(unauthorized()) })
    expect(onAuthError).not.toHaveBeenCalled()
    expect(result.current.error).toBe('')
  })
})
