// Phase stepper for an in-flight (or just-finished) pipeline run, driven by the
// per-task status the API returns in run.tasks. Also mirrors a failure into the
// browser console once per run. Pure presentational — takes a `run` object.
import { useEffect, useRef } from 'react'

// Plain-language status for the running pipeline (hide Tapis state-machine detail).
// Exported because the analysis panel uses it for the no-tasks fallback line.
export const RUN_COPY = {
  completed: 'Done — your results are below.',
  failed: 'The analysis failed. Try a smaller area or a different time range.',
  cancelled: 'The analysis was cancelled.',
  running: 'Analyzing your area — this usually takes a few minutes.',
  queued: 'Queued on TACC — waiting for a compute slot.',
}

// The pipeline's Tapis tasks, in order, with plain-language labels. The heavy
// `run` task does the whole analysis, so its hint spells out the sub-steps.
const RUN_PHASES = [
  {
    id: 'run',
    label: 'Analyzing on TACC',
    hint: 'Downloading OPERA products, building the time-series stack, and computing displacement/velocity. This is the long step — usually a few minutes.',
  },
  { id: 'publish', label: 'Preparing outputs', hint: 'Packaging the result rasters from the run.' },
  { id: 'stac-publish', label: 'Publishing to the catalog', hint: 'Indexing the results so they appear on the map.' },
]

// Last non-empty line of a task message, trimmed — surfaces real job log output
// without dumping a 2 KB stderr blob into the panel.
function lastLogLine(msg) {
  const line = String(msg || '').split('\n').map((s) => s.trim()).filter(Boolean).pop()
  if (!line) return ''
  return line.length > 160 ? `${line.slice(0, 159)}…` : line
}

export function RunProgress({ run }) {
  const byId = {}
  for (const t of run.tasks || []) byId[t.taskId] = t
  const phases = RUN_PHASES.map((p) => ({ ...p, task: byId[p.id], status: byId[p.id]?.status || 'pending' }))
  const failed = run.status === 'failed'
  // The phase to narrate: the running one, else the failed one, else the first
  // not-yet-done one. Undefined once every phase is complete.
  const active = phases.find((p) => p.status === 'running')
    || (failed && phases.find((p) => p.status === 'failed'))
    || phases.find((p) => p.status !== 'completed')
  const detail = active && active.task ? lastLogLine(active.task.lastMessage) : ''
  // Full failure text: the failed task's message (stderr/stdout), falling back
  // to the run-level message. The API caps this at ~2 KB (manager._last_message).
  const failedTask = phases.find((p) => p.status === 'failed')?.task
  const errorText = String(failedTask?.lastMessage || run.lastMessage || '').trim()

  // Mirror the failure into the browser console (once per run) so it's grep-able
  // in devtools and survives the panel collapsing. Re-runs if the error text
  // arrives a poll after the status flips; the ref keeps it to one log per run.
  const loggedRef = useRef(null)
  useEffect(() => {
    if (!failed || loggedRef.current === run.runId) return
    loggedRef.current = run.runId
    const where = active ? active.label : 'unknown phase'
    console.group(`[SUBSIDE] run failed — ${run.runId}`)
    console.error('phase:', where)
    if (detail) console.error('reason:', detail)
    if (errorText) console.error('full error:\n' + errorText)
    else console.error('no error detail reported by Tapis')
    console.groupEnd()
  }, [failed, run.runId, errorText]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="sap-run sap-runprogress">
      <ol className="sap-phases">
        {phases.map((p) => (
          <li key={p.id} className={`sap-phase is-${p.status}${active && active.id === p.id ? ' is-active' : ''}`}>
            <span className="sap-phase-mark" aria-hidden="true">
              {p.status === 'completed' ? '✓'
                : p.status === 'failed' ? '✕'
                  : p.status === 'running' ? <span className="sap-spinner" />
                    : '○'}
            </span>
            <span className="sap-phase-label">{p.label}</span>
          </li>
        ))}
      </ol>
      {active ? (
        <div className="sap-phase-detail">
          {failed ? (
            <div className="sap-fail">
              <div className="sap-error">
                {RUN_COPY.failed}{active.label ? ` (failed at “${active.label}”)` : ''}
              </div>
              {detail ? <div className="sap-phase-msg">{detail}</div> : null}
              {errorText && errorText !== detail ? (
                <details className="sap-fail-detail">
                  <summary>Show full error</summary>
                  <pre className="sap-fail-log">{errorText}</pre>
                </details>
              ) : null}
              {!errorText ? (
                <div className="sap-hint">No error detail was reported. Run id: {run.runId}</div>
              ) : null}
            </div>
          ) : (
            <>
              <div>{active.status === 'queued' ? RUN_COPY.queued : active.hint}</div>
              {detail ? <div className="sap-phase-msg">{detail}</div> : null}
            </>
          )}
        </div>
      ) : (
        <span>{RUN_COPY[run.status] || run.status}</span>
      )}
    </div>
  )
}
