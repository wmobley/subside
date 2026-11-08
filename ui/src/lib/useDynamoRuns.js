// Run list for dynamo mode. The list endpoint returns stored (possibly stale)
// status, so each non-terminal row is also read through getRun on the backoff
// schedule (5 s -> 15 s -> 60 s, paused while the tab is hidden). Terminal rows
// are never polled.
import { useCallback, useEffect, useRef, useState } from 'react'

import { getRun, isAuthError, isTerminalStatus, listRuns, startPolling } from './dynamoApi'

// Merge a fresh list into the current rows. A row that getRun has already
// reconciled keeps its status/handoff so a stale list read cannot regress it.
export function mergeRunList(current, incoming) {
  const byId = new Map(current.map((r) => [r.runId, r]))
  return incoming.map((row) => {
    const prev = byId.get(row.runId)
    if (!prev?.reconciled) return row
    return { ...row, status: prev.status, rawStatus: prev.rawStatus, failureCode: prev.failureCode, handoff: prev.handoff, reconciled: true }
  })
}

export function useDynamoRuns(token, enabled, { onAuthError } = {}) {
  const [runs, setRuns] = useState([])
  const [error, setError] = useState('')
  const pollers = useRef(new Map()) // runId -> stop()
  const authRef = useRef(onAuthError)
  authRef.current = onAuthError
  // The token a request was sent with. A response for a token that has since
  // been replaced (a stale session from localStorage answered 401 after a fresh
  // login stored its token) must not log the fresh session out or overwrite it.
  const tokenRef = useRef(token)
  tokenRef.current = token

  const fail = useCallback((err, usedToken) => {
    if (usedToken !== undefined && usedToken !== tokenRef.current) return
    setError(err.message)
    if (isAuthError(err)) authRef.current?.()
  }, [])

  const refresh = useCallback(() => {
    if (!enabled || !token) return Promise.resolve()
    const used = token
    return listRuns(used)
      .then((rows) => {
        if (used !== tokenRef.current) return
        setRuns((cur) => mergeRunList(cur, rows)); setError('')
      })
      .catch((err) => fail(err, used))
  }, [enabled, token, fail])

  const upsert = useCallback((row) => {
    setRuns((cur) => {
      const merged = { ...(cur.find((r) => r.runId === row.runId) || {}), ...row, reconciled: true }
      return cur.some((r) => r.runId === row.runId)
        ? cur.map((r) => (r.runId === row.runId ? merged : r))
        : [merged, ...cur]
    })
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { if (!token || !enabled) setRuns([]) }, [token, enabled])

  // One poller per non-terminal row; started and stopped as rows change state.
  const activeKey = runs.filter((r) => !isTerminalStatus(r.status)).map((r) => r.runId).sort().join('|')
  useEffect(() => {
    if (!enabled || !token) return
    const active = new Set(activeKey ? activeKey.split('|') : [])
    for (const [id, stop] of pollers.current) {
      if (!active.has(id)) { stop(); pollers.current.delete(id) }
    }
    for (const id of active) {
      if (pollers.current.has(id)) continue
      const used = token
      pollers.current.set(id, startPolling(async () => {
        try {
          const row = await getRun(used, id)
          if (used !== tokenRef.current) return false
          upsert(row)
          return !isTerminalStatus(row.status)
        } catch (err) {
          fail(err, used)
          return used === tokenRef.current
        }
      }))
    }
  }, [activeKey, enabled, token, upsert, fail])
  useEffect(() => () => {
    for (const stop of pollers.current.values()) stop()
    pollers.current.clear()
  }, [token, enabled])

  return { runs, error, refresh, upsert }
}
