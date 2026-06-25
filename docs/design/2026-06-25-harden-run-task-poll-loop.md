# Harden the pipeline `run` task job-status poll loop against transient Tapis API errors

## Status

In Review

## Objective

Stop a single transient network/API error between the Tapis Workflows engine pod
and `portals.tapis.io` from failing an entire pipeline run and orphaning a
healthy (queued or running) HPC job.

## User need

On 2026-06-25 the `subside-werc-opera` pipeline run `4cfd9d3d-d5f4-4a63-8aa7-67c4efcdc921`
was marked `FAILED` even though its compute job
(`7e38e97b-bbaa-4dae-927b-e70c4caeb6f1-007`) had not failed — it was still
`QUEUED` on LS6. The `run` task crashed because a single `t.jobs.getJob(...)`
call timed out:

```
TimeoutError: [Errno 110] Connection timed out
ConnectTimeout: HTTPSConnectionPool(host='portals.tapis.io', port=443):
  Max retries exceeded with url: /v3/jobs/7e38e97b-…-007
  -> tapipy.errors.BaseTapyException
  at entrypoint.py: job = t.jobs.getJob(jobUuid=job_uuid)
```

WERC/H2I runs poll for hours (`max_exec_time: 90000` ≈ 25h), so the exposure
window to a momentary API blip is large. When the `run` task dies, the
downstream `publish` and `stac-publish` tasks never fire, so a job whose
outputs land in the LS6 archive is silently never published to CKAN/STAC.

## Current code/system summary

The `run` task is inline Python in the pipeline YAMLs. Both pipelines share the
same vulnerable poll loop:

- `subside/tapis/workflows/pipelines/werc-opera.yaml` — `submit_and_wait()`,
  lines 183–200; the bare `getJob` is line 193.
- `subside/tapis/workflows/pipelines/h2i-opera.yaml` — same shape, lines 152–153.

```python
def submit_and_wait(body):
    result = t.jobs.submitJob(**body)
    job_uuid = getattr(result, "uuid", None)
    ...
    last = ""
    while True:
        job = t.jobs.getJob(jobUuid=job_uuid)          # <-- no error handling
        status = str(getattr(job, "status", "") or "").upper()
        if status != last:
            print(f"job {job_uuid} status={status}")
            last = status
        if status in SUCCESS or status in FAILURE:
            return status, job_uuid, job
        time.sleep(30)
```

There is already an in-repo precedent for resilient Tapis calls: the `publish`
task uses `_files_call()` with `RETRY_DELAYS = (10, 20, 40, 60, 90)`
(werc-opera.yaml lines 287–300). The poll loop simply does not use the same
pattern.

## Proposed design

Wrap the `getJob` call in a small retry helper local to `submit_and_wait`,
mirroring the existing `_files_call` style so the two pipelines stay
stylistically consistent.

Key behaviours:

1. **Per-poll retry budget, reset on success.** Each `getJob` gets its own
   bounded retry-with-backoff. A successful poll resets the budget, so a job
   that runs for hours with occasional blips never accumulates toward failure —
   only a *sustained* outage exhausts the budget.
2. **Transient vs terminal errors.** Connection/timeout/5xx/generic
   `BaseTapyException` are treated as transient and retried. A genuine
   "job not found" (404 / `NO_JOB`) or an auth error is terminal and still fails
   fast — we do not want to spin for 15 minutes on a real error.
3. **Bounded.** Tolerate roughly up to ~10–15 minutes of *consecutive* failed
   polls (e.g. backoff `(15, 30, 60, 120, 120, 120, 120)`), then give up and
   fail the task with a clear message naming the job uuid so the operator can
   recover it manually.
4. **Steady-state interval unchanged.** The normal 30s `time.sleep(30)` between
   successful polls is untouched.
5. **Observability.** Each retry prints `poll <uuid>: attempt N failed: <type>:
   <msg>; retrying after Ns` to the task stdout/stderr, so a future blip is
   visible in `dump_run.py` output instead of an opaque traceback.

Sketch:

```python
POLL_RETRY_DELAYS = (15, 30, 60, 120, 120, 120, 120)  # ~9.5 min of tolerance

def _is_terminal_api_error(exc):
    text = str(exc).lower()
    name = type(exc).__name__
    return ("NotAuthorized" in name or "Unauthorized" in name
            or "no_job" in text or "job not found" in text or "404" in text)

def _get_job(job_uuid):
    last = None
    for attempt, delay in enumerate((0, *POLL_RETRY_DELAYS), start=1):
        if delay:
            print(f"poll {job_uuid}: retrying after {delay}s")
            time.sleep(delay)
        try:
            return t.jobs.getJob(jobUuid=job_uuid)
        except Exception as exc:
            if _is_terminal_api_error(exc):
                raise
            last = exc
            print(f"poll {job_uuid}: attempt {attempt} failed: "
                  f"{type(exc).__name__}: {str(exc)[:240]}")
    raise last
```

Then `submit_and_wait` calls `job = _get_job(job_uuid)` in place of the bare
call. Same change applied to both pipelines.

## Files likely affected

- `subside/tapis/workflows/pipelines/werc-opera.yaml` (inline `run` task code).
- `subside/tapis/workflows/pipelines/h2i-opera.yaml` (inline `run` task code).
- Re-registration of both pipelines so the engine picks up the new task code:
  `python tapis/workflows/register.py --pipelines-only --recreate-pipelines`
  (external write — requires approval; not part of the code edit itself).

## API/schema changes

None. No pipeline args, task inputs/outputs, or HTTP API surfaces change. The
edit is confined to the body of the existing `run` task.

## Data flow

Unchanged. The poll loop still: submit job -> poll status until SUCCESS/FAILURE
-> emit `archive` output -> downstream `publish`/`stac-publish`. The only
difference is that a transient `getJob` error is absorbed and retried instead of
propagating and terminating the task.

## Risks and tradeoffs

- **Masking a real outage.** If Tapis is down for longer than the retry budget,
  the task still fails — by design. The budget is a tradeoff between resilience
  and not hanging forever; ~10 min is chosen to cover typical blips without
  pinning a worker indefinitely.
- **Misclassifying a terminal error as transient.** If `_is_terminal_api_error`
  is too narrow, a real "job not found" could be retried for the full budget
  before failing. Mitigation: keep the terminal matchers broad and lean toward
  failing fast on auth/404.
- **Worker occupancy.** A retrying task holds its engine worker for up to the
  budget during an outage. Acceptable given these are long-lived tasks already.
- **OOM-escalation interaction.** The retry only wraps `getJob`; the existing
  OOM-escalation logic keys off the *job's* terminal status, which is unchanged.

## Alternatives considered

1. **Reuse `_files_call` verbatim.** Rejected: its budget is per-call with no
   "reset on success" semantics suited to a long poll loop, and it lives in a
   different task scope. We mirror its *style* but tune for polling.
2. **Catch-all `try/except` that ignores every error and keeps looping.**
   Rejected: would spin forever on a genuinely deleted job or auth failure.
3. **Make the engine itself retry / resume orphaned jobs.** Out of scope — that
   is upstream `open-workflow-engine` behaviour, not code we own here.
4. **Reduce the poll interval.** Does not address the problem (the failure is a
   dropped connection, not staleness).

## Test plan

The task code is inline YAML executed inside the engine, so unit-testing in
place is awkward. Plan:

- **Extract-and-test the helper logic.** Lift `_get_job` / `_is_terminal_api_error`
  into a tiny local harness (or a `tests/` module) and unit-test:
  - transient error then success -> returns the job, budget reset;
  - N consecutive transient errors past the budget -> re-raises the last error;
  - terminal error (auth / 404) -> raises immediately, no retries;
  - clean success -> single call, no sleeps.
- **Smoke test.** Run `tapis/workflows/smoke_test.py --pipeline werc` (and h2i)
  to confirm a normal run still completes end-to-end after the edit.
- **Manual fault injection (optional).** Temporarily point `TAPIS_BASE_URL` at an
  unreachable host mid-poll in a scratch copy to confirm the retry/backoff log
  lines appear and the task eventually fails cleanly with the job uuid.

## Documentation plan

- Note the retry behaviour in `tapis/workflows/DESIGN.md` (poll-loop section).
- Brief comment in both YAMLs above `_get_job` explaining the reset-on-success
  budget and the transient-vs-terminal split.

## Rollout/rollback plan

- **Rollout:** edit both YAMLs, then re-register pipelines
  (`register.py --pipelines-only --recreate-pipelines`) — an external write that
  needs explicit approval. Verify with a smoke test run.
- **Rollback:** the change is isolated to the inline task code; revert the YAML
  edits and re-register to restore prior behaviour. No data migration, no schema
  change.

## Open questions

1. Retry budget: is ~10 min of consecutive-failure tolerance the right ceiling,
   or should it scale with the job's remaining `maxMinutes`?
2. Should an exhausted-retry failure emit a distinct notification (so the
   operator knows it was an API outage, not a compute failure) vs a normal
   task failure?
3. Should we also persist the `job_uuid` more prominently on failure (it is
   already in the message) so orphaned jobs are trivially recoverable?

## Decisions

- 2026-06-25: User chose "spec then implement" for this fix (vs implement
  directly or defer).
- 2026-06-25: User chose to let the in-flight queued job
  `7e38e97b-…-007` run to completion and publish its outputs manually, rather
  than cancel + resubmit. (Tracked separately from this code change.)

## User feedback / decisions

_(pending review of this spec)_
