# Add a scheduled development-queue H2I smoke test

## Status

Implemented

## Objective

Run the full SUBSIDE H2I batch image on the live Tapis `ls6` `development`
queue from GitHub Actions on a schedule and on demand, fail the workflow with
actionable Tapis job details when it does not complete, and clean up staged
test inputs after a confirmed terminal result.

## User need

- **Primary user:** SUBSIDE developers and operators responsible for the
  Tapis batch image, queue configuration, and workflow reliability.
- **Secondary users:** Project maintainers who need a visible CI signal without
  manually monitoring a long-running Tapis job.
- **Job-to-be-done:** Detect regressions in the H2I image, Earthdata staging,
  and LS6 development queue before users encounter them.
- **Current pain:** The test is run manually and requires an agent or developer
  to watch the job and diagnose failures.
- **Definition of success:** A scheduled or manually dispatched GitHub run
  submits one development-queue job, reports its job UUID and terminal status,
  removes its staging path, and produces a failed GitHub check with the
  failure message when the test fails.

## Current code/system summary

- `tapis/workflows/smoke_test.py` already stages a known AOI and optional
  Earthdata `.netrc` through Tapis Files and can submit the H2I app directly
  through Tapis Jobs.
- The direct-job helper currently hardcodes the queue from the local H2I
  pipeline definition (`vm-small`) and does not guarantee staging cleanup.
- The live LS6 system exposes a `development` queue. A direct H2I smoke test
  on that queue completed successfully on 2026-10-28.
- GitHub Actions already has Tapis credentials available for deployment jobs;
  the smoke test additionally requires Earthdata credentials and an allocation.

## Proposed design

1. Add `--queue` to the direct smoke-test command, defaulting to the pipeline
   queue for backward compatibility. The GitHub workflow passes
   `--queue development`.
2. Add `--max-minutes` as an optional direct-job override, defaulting to the
   existing harness value. The scheduled test uses a bounded value appropriate
   for the small known AOI.
3. Wrap staging and job execution in cleanup logic that deletes the unique
   Tapis Files staging directory after a confirmed terminal result. On timeout
   or ambiguous job ownership, cancel/reconcile first and retain the exact
   staging path when it may still be needed by a live job.
4. Add `.github/workflows/tapis-development-smoke.yml` with `workflow_dispatch`
   and a daily schedule. It installs only the workflow harness dependencies,
   passes credentials through GitHub secrets, uses a unique staging path, and
   relies on GitHub's native failed-workflow notifications.
5. Include the Tapis job UUID, queue, terminal state, and failure message in
   the GitHub log/summary without printing credentials or tokens.

## Files likely affected

- `.github/workflows/tapis-development-smoke.yml` — scheduled/manual CI job.
- `tapis/workflows/smoke_test.py` — queue, walltime, and cleanup support.
- `tapis/workflows/tests/test_smoke_test.py` — hermetic harness tests.
- `tapis/workflow_apps/h2i_lab/run.sh` and `app-cpu.json` — remove/exclude the
  temporary Earthdata credential file from job artifacts.
- `pyproject.toml` — include harness tests in the default test discovery.
- `tapis/workflows/README.md` — local command and required secret guidance.
- `docs/design/2026-10-28-github-development-queue-smoke-test.md` — decisions
  and implementation status.

## API/schema changes

None. The change uses the existing Tapis Jobs API and existing H2I app.

## Data flow

```text
GitHub schedule/manual dispatch
  -> checkout + install tapipy/PyYAML
  -> authenticate to Portals with repository secrets
  -> stage AOI + .netrc via Tapis Files
  -> submit H2I app to ls6/development
  -> poll Tapis Jobs to terminal state
  -> write job diagnostics to GitHub log/summary
  -> delete unique staging directory
  -> pass/fail GitHub check and native notification
```

## Risks and tradeoffs

- The test consumes TACC allocation and Earthdata requests; daily cadence and
  the small known AOI keep the cost bounded.
- GitHub secrets must be configured correctly; missing secrets should fail
  clearly before staging.
- The Earthdata `.netrc` is staged only for the job, removed by the image
  entrypoint at exit, excluded from the H2I archive filter, and redacted from
  diagnostics. If cancellation or submission ownership is unresolved, the
  staging path is intentionally retained for manual reconciliation.
- Job diagnostics are sanitized before they are written to the GitHub log or
  summary; raw remote stdout/stderr is not treated as safe output.
- GitHub's native notifications depend on repository/user notification settings;
  Slack or email can be added later without changing the test harness.
- The direct Jobs smoke test validates the image and development queue, not the
  Subside API's server-side token broker. The deployed Subside workflow remains
  the separate broker/recovery test.

## Alternatives considered

- **Only run the existing hosted Workflows pipeline:** rejected because the
  current H2I task hardcodes `vm-small` and does not exercise `development`.
- **Use SSH or a self-hosted runner:** rejected; Tapis Files and Jobs APIs are
  the approved access path and avoid coupling CI to a machine.
- **Create GitHub issues on failure:** deferred because issue creation adds
  repository state and project-dashboard bookkeeping; native workflow failure
  notifications are sufficient for the first version.

## Test plan

- Unit-test direct-job queue and max-minute overrides.
- Unit-test cleanup on success and on polling/submission failure.
- Run the smoke harness dry-run locally.
- Run the existing API/unit suite and Python compilation/lint checks.
- Run one manually dispatched GitHub development-queue smoke test after the
  workflow is pushed; confirm terminal success and staging cleanup.

## Documentation plan

Document the local direct-job command, the GitHub secret names, schedule,
allocation cost, and the distinction between this image/queue smoke test and
the Subside broker/recovery test.

## Rollout/rollback plan

1. Merge the harness and workflow without changing production services.
2. Configure the five required repository secrets before enabling the schedule.
3. Re-register the updated H2I app definition once so the `.netrc` archive
   exclusion is active.
4. Dispatch once manually and inspect the job output.
5. Leave the daily schedule enabled after a successful manual run.
6. Roll back by disabling/removing the workflow; no Tapis service or database
   state is changed beyond the disposable test staging path and compute job.
   If a timeout leaves staging retained, reconcile/cancel the named job and
   delete that exact path before rotating credentials.

## Open questions

None for the first version. Native GitHub notifications are the chosen default;
an additional webhook can be added later if the team wants Slack or Teams.

## Decisions

### 2026-10-28 — Use a direct Jobs smoke test on `development`

- **Decision:** Test the existing full H2I app directly through Tapis Jobs on
  `ls6/development`, while retaining the Subside API workflow as a separate
  broker/recovery test.
- **Reason:** The registered H2I workflow currently hardcodes `vm-small`; the
  direct harness can exercise the live development queue immediately without
  changing the production pipeline contract.

### 2026-10-28 — Use native GitHub failure notifications

- **Decision:** Fail the scheduled/manual workflow with detailed diagnostics and
  rely on GitHub Actions' native notifications instead of creating issues or
  requiring a webhook secret.
- **Reason:** It is visible to maintainers, has no additional secret or external
  write, and avoids duplicate issue/project bookkeeping.

## User feedback / decisions

- 2026-10-28: User approved setting up an automated GitHub test instead of
  manually monitoring development-queue runs.
- 2026-10-28: Implemented the direct queue/walltime overrides, unique job
  naming and adoption, timeout cancellation, credential redaction, staging
  cleanup, `.netrc` cleanup/archive exclusion, harness tests, documentation,
  and the scheduled/manual GitHub Actions workflow. No production API service
  behavior was changed.
