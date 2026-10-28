# Make Subside compute-job polling durable

## Status

Implemented

## Objective

Prevent a Subside run from being reported as failed when its inner Tapis Jobs
job continues running or finishes successfully after a transient Jobs API
outage. Recover the inner job after workflow-task failure or API restart,
automatically complete the existing publish path when safe, and revoke the
per-run credential only after compute and publishing are terminal.

## User need

The UI must not show a permanent failure merely because a long-running H2I or
WERC analysis lost access to the Jobs status endpoint. A later status request,
API restart, or reconciliation pass must identify the correct compute job,
recover its archive, finish the normal publication flow, and preserve the
credential while the job or publication is still active or uncertain.

The incident that motivated this work was workflow
`3670c9b6-a61c-4f0a-b177-2fd412ba0806`: its task failed on a Jobs API `504` at
20:18:47, while inner job
`4a6fb061-f576-412f-9b5f-a0fd400a13c7-007` later finished normally at 20:21:30.

## Current code/system summary

- The API submits a Tapis Workflows pipeline and stores a per-run token lease.
- Each pipeline's `run` function task submits an inner Tapis Jobs job and polls
  `getJob` with a retry budget of roughly 16 minutes.
- A transient Jobs API `504` exhausts that budget and fails the workflow task,
  even if the inner HPC job continues and later reaches `FINISHED`.
- The task emits the inner job UUID, but failed task executions do not always
  retain that output or stdout. `api/services/manager.py` can therefore fail to
  recover the archive.
- The API currently derives completed/failed status directly from the workflow
  task state and may clean up the per-run token as soon as the workflow is
  marked failed.
- `subside-publish` can manually republish a finished job, but there is no
  automatic status reconciliation.
- SQLite schema creation is not currently a migration mechanism; new recovery
  fields must be added idempotently for existing installations.
- Existing unrelated working-tree changes and untracked files are outside this
  change.

## Proposed design

### 1. Durable inner-job correlation

For API-created runs, derive a secret-free prefix from the registered pipeline
and lease id. The exact names are:

- H2I: `subside-h2i-opera-{lease_id}`
- WERC attempt 1: `subside-werc-opera-{lease_id}-attempt-1`
- WERC attempt 2: `subside-werc-opera-{lease_id}-attempt-2`
- Automatic publish recovery: `subside-publish-recovery-{lease_id}`

The API persists the prefix, pipeline id, hard deadline, selected compute job
UUID, recovery state, and publish workflow UUID in the lease store. Direct
pipeline invocations without the parameter retain a date-based fallback name.

Before submitting an inner job, the pipeline searches for the exact name and
expected app id. Zero matches permits submission. One matching job is adopted.
More than one match is an ambiguity and must fail without submitting another
job. If submission returns an ambiguous/transport error, the pipeline searches
again before deciding that submission failed; it never submits a duplicate
job because a response was lost.

For WERC, attempt 2 is permitted only after attempt 1 is confirmed terminal
with the expected OOM outcome. An active, unknown, or multiply-matched attempt
1 blocks a second submission.

### 2. Polling resilience

Transient Jobs API failures (`5xx`, gateway timeout, rate limit, and connection
errors) are retried with backoff until the requested compute walltime plus a
bounded scheduler-queue allowance plus a bounded grace period. The queue
allowance is operator-configurable, finite, and included in both the initial
per-run token TTL and the persisted hard deadline. The effective deadline is
persisted with the lease and is always finite. If the requested queue,
walltime, and token buffer exceed the configured maximum token TTL, submission
fails closed instead of silently issuing a token that expires too early.

Authentication errors, confirmed not-found responses, and terminal compute
states remain fail-fast. A polling timeout is recorded as uncertain; it is not
treated as evidence that the job failed and it cannot trigger a second job.

### 3. API-side reconciliation

Track outer workflow state, compute state, and publication state separately.
Recovery states are `none`, `reconciling`, `compute_active`,
`compute_succeeded`, `publish_submitting`, `publish_active`, `completed`,
`failed`, and `ambiguous`.

For a failed, uncertain, or stale run:

1. Prefer the job UUID already present in task output or logs.
2. Otherwise query the authenticated user's Jobs API for the exact durable job
   names derived from the lease id and pipeline id.
3. For legacy runs without the new name, use a bounded app-id/time-window
   fallback only when exactly one candidate matches; never guess among multiple
   jobs.
4. Require `status=FINISHED` and `condition=NORMAL_COMPLETION` before treating
   compute as successful. Resolve the archive from the job record and verify
   the expected archive/manifest is available to the publish pipeline.
5. If compute is queued/running, report recovery as active and retain the
   token. If Jobs API access is temporarily unavailable, report reconciling and
   retain the token until the hard deadline.
6. If compute is confirmed failed/cancelled, preserve the failure and clean up
   after no dependent task remains active.

The public status is `recovering` while compute or automatic publication is
active/uncertain, `completed` only after compute/archive and publication are
complete (or publication is explicitly not configured), and `failed` only for
confirmed compute or publication failure. `tapisStatus` remains the raw outer
workflow status. The API returns non-secret `reconciliationStatus`,
`computeStatus`, `publicationStatus`, and `innerJobUuid` fields for diagnosis.

### 4. Credential refresh, restart safety, and cleanup

OAuth authorization-code login stores the user's refresh token encrypted in the
protected backend token store. Each API-created run receives an opaque,
lease-bound broker credential. H2I, WERC, and publication tasks use that
credential to call the API broker when their current per-run access token is
expired. The broker refreshes the user's OAuth session server-side, mints a new
bounded per-run token, atomically replaces the encrypted lease token, and
revokes the predecessor when possible. OAuth refresh tokens are never passed
to workflow tasks.

When compute succeeds and publication is configured, reconciliation invokes the
existing `subside-publish` pipeline exactly once using the stored per-run token.
The publish run has a deterministic name and is persisted before/after the
submission attempt. An ambiguous publish response is reconciled by exact name;
it is never retried blindly. The existing publish pipeline remains the only
place that performs CKAN/STAC writes.

If publication is not configured, publication is marked `not_configured` and
compute/archive success is sufficient for completion. If publication fails,
the run is failed with the error retained for operator recovery; the compute
job is not rerun.

On API startup, reconcile persisted active/uncertain leases using each stored
per-run token, so recovery does not depend on service-admin visibility. A
stale cleanup claim is reclaimable. Token revocation and staging cleanup are
allowed only after compute and publication are terminal, or after the explicit
hard deadline with no active/uncertain job remaining. Tokens are never exposed
in logs or status responses.

## Files likely affected

- `api/services/manager.py` — job correlation, search/reconciliation, status and
  archive recovery, cleanup gating.
- `api/services/token_store.py` — idempotent recovery/cleanup fields and
  migration for existing SQLite installations.
- `api/services/tapis.py` — redacted Jobs search helper using the authenticated
  client token.
- `api/models.py` and `api/main.py` — additive status fields and startup
  reconciliation.
- `api/tests/` — reconciliation, idempotency, and cleanup tests.
- `api/config.py` — bounded polling/reconciliation grace settings if needed.
- `tapis/workflows/pipelines/h2i-opera.yaml` — durable job-name input and longer
  transient polling tolerance.
- `tapis/workflows/pipelines/werc-opera.yaml` — same, including OOM attempts.
- `ui/src/lib/runCopy.js`, `ui/src/components/mapworkbench/RunProgress.jsx`,
  and `SubsideAnalysis.jsx` — display and poll `recovering`.
- `api/README.md` and `tapis/workflows/README.md` — durable correlation,
  automatic recovery, and operational notes.
- This design spec — implementation status and deviations.

## API/schema changes

The existing endpoints remain unchanged. `RunStatusResponse` gains additive,
non-secret fields: `reconciliationStatus`, `computeStatus`,
`publicationStatus`, `innerJobUuid`, and `recovered`.

`status` gains the backward-compatible value `recovering`; the UI treats it as
non-terminal. `tapisStatus` remains the raw outer status. The internal
`job_name_prefix` argument remains optional for direct pipeline invocations.

The `run_token_leases` SQLite table gains nullable/defaulted columns for
pipeline id, job-name prefix, compute job UUID, recovery state, publish
workflow UUID, recovery attempts/errors/timestamps, and hard deadline. Startup
performs `PRAGMA table_info` checks and `ALTER TABLE ADD COLUMN` migrations;
existing rows remain valid and use legacy reconciliation rules.

## Data flow

```text
POST /runs
  -> durable lease + exact job names + queue-aware hard deadline
  -> workflow args
  -> run task submits inner Tapis Job with stable name
  -> run task polls with bounded transient retry
  -> API status lookup
       -> task output/log UUID, or exact job-name search
       -> compute state + archive readiness
       -> automatic subside-publish using stored run token
       -> completed/recovering/failed status
  -> revoke token and remove staging only after terminal publication
```

## Risks and tradeoffs

- Longer polling consumes a workflow function slot during a prolonged Jobs API
  outage. The bound remains finite and is tied to the job walltime.
- Exact-name lookup is reliable only for new runs; the legacy time-window
  fallback must reject ambiguous matches.
- Reporting a recovered inner job as completed while the outer workflow object
  remains failed is a deliberate normalization at the API boundary. The raw
  outer status remains available for operations.
- The inner job name is metadata visible to Tapis operators; it must contain no
  token or user secret.
- SQLite remains single-instance unless the deployment already provides the
  configured persistent shared volume. Multi-replica coordination is not added
  here.
- Automatic publication is an external-write path. It is limited to the
  existing `subside-publish` pipeline, uses the per-run credential, persists
  idempotency state, and is disabled when publication is not configured.
- Job owner, tenant, app id, archive, and run ownership must be checked before
  adoption or publication to prevent cross-user recovery.
- The publish pipeline's mutable dependency should be pinned to an immutable
  revision before enabling this path in production.

## Alternatives considered

1. **Only increase the polling retry budget.** Rejected as insufficient: a
   workflow can still fail after a longer outage, and the API would still lack a
   durable way to find the inner job after task output is lost.
2. **Only reconcile by workflow timestamps.** Rejected as unsafe when multiple
   jobs overlap; exact durable names are the primary lookup.
3. **Map all uncertainty to running.** Rejected because it hides a meaningful
   state; `recovering` is explicit and non-terminal.
4. **Submit the compute job directly from the API.** Rejected because it would
   duplicate pipeline orchestration and bypass the existing Workflows contract.
5. **Write CKAN/STAC directly from the API.** Rejected: publication remains in
   the existing audited `subside-publish` pipeline.

## Test plan

- Unit-test exact job-name generation for H2I and WERC/OOM attempts.
- Compile embedded YAML code and test exact-name adoption, ambiguous lookup,
  accepted-but-lost submission, and no duplicate submission.
- Unit-test a run-task status sequence with transient `504` responses followed by
  `FINISHED`; assert no false failure.
- Unit-test a permanent transient outage; assert bounded retry and no duplicate
  job submission.
- Unit-test API recovery from a failed workflow when the task has no job UUID
  but exact-name Jobs search returns `FINISHED`.
- Unit-test active-job recovery; assert `running` and no token cleanup.
- Unit-test ambiguous legacy candidates; assert no guessed archive and no unsafe
  cleanup.
- Unit-test genuine compute failure and auth/not-found errors.
- Unit-test startup reconciliation, stale cleanup-claim recovery, automatic
  publish submission/adoption, publish failure, and cleanup only after publish
  terminal.
- Test owner/app/tenant checks, token redaction, hard deadlines, archive
  readiness, and legacy ambiguity.
- Run existing token lifecycle tests, YAML parsing/embedded-code compilation,
  and focused API tests.
- After implementation and explicit external-write approval, run the approved
  Tapis sandbox scenario with a transient polling failure and verify recovery.

## Documentation plan

Update the API and workflow README files with recovered-status semantics,
stable inner-job correlation, bounded retries, automatic publication conditions,
token cleanup rules, restart behavior, and manual recovery guidance. Document
every new environment variable and the production dependency pinning gate.

## Rollout/rollback plan

1. Land code, migrations, tests, and docs without changing live Tapis
   registrations or executing CKAN/STAC writes.
2. Validate pipeline definitions locally and register them only after explicit
   external-write approval.
3. Enable automatic recovery in the sandbox and run the approved short-TTL
   scenario, including restart and failed-mint/revoke cases.
4. Monitor reconciliation state, exact job adoption, publication runs, and
   lease cleanup.
5. Roll back the API image/pipeline definitions if recovery becomes ambiguous;
   existing compute jobs remain untouched. Additive SQLite columns are
   backward-compatible and may remain during rollback.

## Open questions

1. Confirm the lease SQLite volume is persistent across API restarts and the
   publish dependency is pinned before production enablement.
2. The current UI session still requires a valid browser token to call status;
   this change protects backend completion and cleanup but does not redesign
   OAuth refresh for the browser.
3. Confirm the expected manifest filenames against the registered H2I and WERC
   publish definitions before sandbox execution.

4. Confirm the production value for the scheduler queue allowance. The initial
   implementation default is 24 hours; operators may lower or raise it only
   alongside the configured maximum per-run token TTL.

## Decisions

### 2026-10-26 — Cover scheduler queue time in the run-token contract

- **Status:** Superseded by the refresh-broker decision below.
- **Decision:** Add an explicit, bounded scheduler-queue allowance to the per-run token TTL and hard reconciliation deadline. Treat a required lifetime above the configured maximum as a submission error rather than silently issuing a shorter token. Classify token-expiry observations as recoverable credential state, not compute failure.
- **Reason:** The approved live test proved that the prior implementation covered declared compute walltime plus grace but not queue delay: the inner job waited past the JWT expiry, then finished normally. A static workflow token cannot be refreshed safely with the current Tapis Workflows input contract.
- **Alternatives rejected:** Passing an OAuth refresh token into the hosted workflow was rejected because it would expose a higher-value credential. A broad service/admin credential was rejected because it would expand cross-user access. A fixed retry increase without a queue budget was rejected because it does not establish a credential-lifetime contract.
- **User feedback:** The user explicitly pointed out that token-expiry survival was the stated fix and approved continuing the correction.
- **Impact on implementation:** Add queue-budget configuration, include it in TTL/deadline arithmetic, validate the minted expiry, update status/recovery handling, add queue-delay regression tests, and correct the spec's live-test evidence. The longer-term least-privilege recovery identity remains a follow-up before production use.

### 2026-10-26 — Refresh run credentials through a server-side broker

- **Decision:** Keep OAuth refresh tokens only in the backend's encrypted user-token store. Give each run an opaque, lease-bound broker credential; hosted workflow tasks use it to request a freshly minted per-run access token when the current access token expires. Refresh tokens are never passed into workflow arguments or task environments.
- **Reason:** A static workflow argument cannot be updated by the API after the access token expires. A longer TTL only postpones the same failure. The broker lets the backend perform the OAuth refresh and rotate the bounded run token without exposing the refresh token to Tapis Workflows.
- **Alternatives rejected:** A longer fixed TTL is only a bounded mitigation. Passing the OAuth refresh token into hosted tasks increases credential exposure. A broad service/admin credential would weaken per-user authorization and attribution.
- **User feedback:** The user explicitly clarified that automatic refresh, not merely a longer-lived token, is the required fix.
- **Impact on implementation:** Add encrypted per-user refresh-token persistence, token rotation helpers, a lease-bound internal broker endpoint, broker arguments and renewal handling in H2I/WERC/publish tasks, rotation/revocation tests, and deployment configuration for the API's reachable broker URL.

### 2026-10-28 — Make the lease deadline queue-aware

- **Decision:** Keep a finite hard deadline, anchored at run-token mint/lease creation, as scheduler queue allowance + requested compute walltime + recovery grace. Calculate the initial run-token TTL from scheduler queue allowance + requested compute walltime + token buffer. Add `SUBSIDE_RUN_TOKEN_QUEUE_BUDGET_SECONDS` as an operator-controlled bound and reject a request when the required initial TTL exceeds `SUBSIDE_RUN_TOKEN_TTL_MAX_SECONDS`.
- **Reason:** The live test's inner job waited approximately 13 hours before starting and then finished successfully. The broker returned 503 because the old submission-based deadline was only 12 hours plus grace, so a valid queued job was treated as past its hard deadline.
- **Alternatives rejected:** Removing the deadline would leave refreshable run credentials active indefinitely. A fixed increase to the existing grace period would not express queue capacity or protect against stuck jobs. Starting the deadline only after compute begins is more precise but requires a new authenticated lease-state callback from the hosted task; the bounded queue allowance is the smallest safe change now.
- **User feedback:** On 2026-10-28 the user asked whether a deadline is needed when job lengths vary and approved implementing the queue-aware design.
- **Impact on implementation:** Update configuration forwarding and documentation, change TTL/deadline arithmetic, fail closed on a max-TTL mismatch, and add regression tests for queue delay and maximum-bound rejection.

### 2026-10-25 - Correlate inner jobs with the existing lease id

- **Decision:** Add a stable, secret-free job-name prefix derived from the
  existing run-token lease id and pass it through the workflow.
- **Reason:** The lease id is already persisted and unique per API run, while
  task output/log retention is not reliable after a polling failure.
- **Alternatives rejected:** Timestamp-only matching and storing raw job output
  only in workflow task metadata.
- **User feedback:** The user requested a durable fix after confirming that the
  inner HPC job succeeded while the workflow reported failure.
- **Impact on implementation:** Pipeline YAML, manager correlation logic,
  token-store migration, API status fields, and focused tests change.

### 2026-10-25 - Automatic publication is approved

- **Decision:** After confirmed compute success and archive readiness, invoke
  the existing `subside-publish` pipeline automatically and exactly once.
- **Reason:** Compute-only recovery would still leave the user without the
  expected CKAN/STAC result and would not fix the full workflow outcome.
- **Guardrails:** Use the stored per-run token, deterministic publish name,
  persisted workflow UUID, ownership checks, and cleanup only after terminal
  publication.
- **User feedback:** On 2026-10-26 the user approved automatic recovery and
  publication.

### 2026-10-25 - Explicit recovery status

- **Decision:** Add `recovering` rather than hiding uncertainty as `running`.
- **Reason:** Operators and users need to distinguish active recovery from a
  healthy compute task while retaining backward-compatible terminal handling.

### 2026-10-25 - Existing publish pipeline remains the write boundary

- **Decision:** The API orchestrates `subside-publish`; it does not implement
  direct CKAN/STAC writes.
- **Reason:** Preserve the existing publication contract and isolate external
  writes for audit and rollback.

## User feedback / decisions

- The user confirmed automatic recovery/publication is acceptable.
- The user explicitly requested no SSH-based testing; validation uses local
  repository code and authenticated Tapis APIs only when separately approved.
- The user requested a durable fix rather than a one-off retry increase.
- On 2026-10-28: User approved implementing a finite, queue-aware deadline after the live run showed a successful inner job but a broker 503 after queue delay.

Implementation completed with additive lease-store migration, exact-name job
adoption, bounded workflow polling, API/startup reconciliation, automatic
`subside-publish` orchestration, cleanup gating, additive status fields, UI
`recovering` handling, queue-aware token TTL/deadline arithmetic, fail-closed
TTL validation, and focused tests. No live Tapis registration, deployment,
CKAN write, or STAC write was performed in this implementation pass.

- 2026-10-25: User asked to make the fix durable after confirming the underlying
  HPC job succeeded despite the failed workflow status.
- 2026-10-28: The queue-aware deadline implementation was reviewed, tested, and
  recorded as the follow-up correction for scheduler delay.
