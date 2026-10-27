# Make Subside workflow credentials survive browser token expiry

## Status

Implemented

## Objective

Prevent a Subside analysis launched from the UI from failing merely because the
short-lived browser Tapis access token expires before the asynchronous Tapis
Workflow finishes.

The design must also prevent refresh tokens from being exposed to browser
JavaScript, browser storage, workflow arguments, logs, or error responses.

## User need

An authenticated scientist or analyst should be able to start an H2I or WERC
analysis, leave the page open or close it, and have the workflow continue to
completion. Returning to the application should show a durable run record and
an actionable authentication message if the interactive session itself must be
reauthorized.

The immediate user-visible failure is run durability. Silent long-term browser
reauthentication is included only if the project approves server-side refresh
token storage and session changes.

## Current code/system summary

- `ui/src/lib/auth.jsx` stores the Tapis access token, username, and expiry in
  `localStorage`, then logs out when the access token expires.
- `ui/src/lib/subsideApi.js` sends that access token as `X-Tapis-Token` for run
  submission, status, history, and result requests.
- `api/services/tapis.py::exchange_code()` exchanges the OAuth authorization
  code and receives an access token, expiry, and refresh token. It currently
  returns the refresh token to its caller.
- `api/models.py::AuthTokenResponse` and `api/main.py::auth_token()` omit the
  refresh token from the browser response, which is good for secret exposure,
  but no server-side refresh-token session is created.
- `api/services/manager.py::submit_run()` resolves the browser token and passes
  the same credential as `tapis_token`, and usually as the CKAN and STAC token,
  in workflow arguments.
- Both pipeline YAMLs use `tapis_token` in the long-running `run`, `publish`,
  and `stac-publish` tasks. A workflow therefore depends on the lifetime of the
  browser token.
- The API has no durable run-to-credential record, token-mint lifecycle, or
  cleanup/revocation path.
- The `subside` worktree already contains user-owned changes and untracked
  files. Those changes are outside this design and must remain untouched.

## Proposed design

### Phase 1: bounded per-run credential (required fix)

At authenticated run submission:

1. Validate the caller's current access token and derive the authenticated
   username from the validated Tapis identity.
2. Stage user inputs with the browser token, then compute a bounded token
   lifetime from the requested workflow walltime plus a configurable cleanup
   buffer. Enforce server-side minimum and maximum values; never accept an
   unbounded client-supplied TTL.
3. Mint a separate user-associated Tapis token for the run through the Tokens
   API. The verified portals contract is `POST /v3/tokens` with
   `token_tenant_id`, `account_type`, `token_username`, `target_site_id`, and
   `access_token_ttl`; the request is authenticated with the browser token.
4. Pass only the per-run token to workflow tasks. Do not pass the browser's
   access token or a refresh token as a workflow input.
5. Store the run token encrypted at rest in a SQLite lease store configured by
   `SUBSIDE_RUN_TOKEN_STORE_PATH` and protected by
   `SUBSIDE_RUN_TOKEN_ENCRYPTION_KEY`. The record contains the workflow run id,
   username, target site, creation/expiry timestamps, cleanup state, and a
   ciphertext token value. Plaintext token values must not appear in logs,
   diagnostics, or API responses. Deployments with multiple API replicas must
   mount the same protected store or replace this store with an equivalent
   shared implementation before enabling the feature.
6. Revoke the per-run token with the verified `POST /v3/tokens/revoke` contract
   and body `{ "token": <JWT> }` after successful completion, failure, cancellation,
   timeout, or an operator cleanup action. Cleanup must be idempotent and
   retried; natural expiry is the final fallback.

The portals token contract was verified against the installed Tapis Tokens API
OpenAPI and the burner sandbox probe. Production enablement still requires the
approved sandbox matrix in the test plan.

### Phase 2: server-managed interactive session (optional, separate gate)

If the product requires the browser to continue polling after access-token
expiry without an explicit login, retain the OAuth refresh token only on the
backend, encrypted at rest and bound to a server session/user record. Add a
backend refresh endpoint or middleware that rotates/refreshes the access token
without returning the refresh token to the browser.

This phase is not required for the workflow itself to continue. It is required
for silent UI recovery after the original access token expires. It requires an
approved storage and key-management mechanism, cookie/session policy, logout
revocation behavior, and multi-instance deployment behavior.

### Credential separation

The initial implementation must not assume that one minted user token is valid
for every downstream service. Verify independently whether the per-run token
can perform:

- Tapis Files, Jobs, and Workflows operations;
- CKAN dataset/resource writes through the configured front door; and
- STAC Transactions writes.

If CKAN or STAC require different credentials, keep their configured service
tokens separate from the per-run Tapis token and do not broaden the per-run
token's permissions to compensate.

### Failure behavior

- If token minting fails, do not submit a workflow and return a clear 502/503
  authorization-upstream error.
- If the lifecycle feature is not configured, fail closed with a clear
  configuration error; never fall back to passing the browser token to a
  long-running workflow.
- If workflow submission fails after minting, immediately attempt token cleanup
  and report the submission failure without exposing token data.
- If cleanup fails, retain a retryable cleanup record and emit a redacted
  operational warning; do not fail an already-completed scientific run solely
  because revocation was temporarily unavailable.
- If the browser token expires during status/results access and Phase 2 is not
  enabled, return an explicit reauthentication response. Do not create a second
  run automatically.

The Phase 1 state machine is intentionally conservative:

`staged -> token_ready -> submitted -> terminal -> revoke_pending -> revoked`

Submission exceptions that may indicate the remote request was accepted enter
`submission_unknown`; they are never blindly retried and their token is not
revoked until reconciliation proves the run is terminal or the bounded token
TTL has elapsed. This leaves a documented natural-expiry window for an
ambiguous mint or submission response because the current Tapis contracts do
not provide a verified idempotency key or token lookup API.

## Files likely affected

Required Phase 1 candidates:

- `api/services/tapis.py` — token mint/revoke client functions, response parsing,
  redaction-safe errors.
- `api/services/token_store.py` — encrypted SQLite lease records and retryable
  cleanup state.
- `api/services/manager.py` — per-run token creation, workflow argument
  selection, and cleanup hooks.
- `api/tests/test_token_lifecycle.py` — hermetic contract, state-transition,
  encryption, cleanup, and polling tests.
- `api/config.py` — token TTL buffer/min/max, target-site prefix, feature flag,
  encrypted-store path/key, and reconciliation settings.
- `api/main.py` — auth/upstream error mapping and any cleanup endpoint or
  background task wiring.
- `api/models.py` — run credential metadata only if it becomes part of an API
  response; secret values must not be represented.
- `tapis/workflows/pipelines/h2i-opera.yaml` — preserve argument names where
  possible while ensuring the supplied token is the per-run token.
- `tapis/workflows/pipelines/werc-opera.yaml` — same as H2I.
- New API tests under an existing test location, or a narrowly scoped
  `api/tests/` if the repository's test convention has no suitable location.

Optional Phase 2 candidates:

- `api/services/tapis.py` — refresh-token exchange and rotation.
- `api/services/session.py` or the existing persistence layer — encrypted
  refresh-token/session storage, if an approved storage mechanism exists.
- `api/main.py` / `api/models.py` — refresh/session endpoints and response
  contracts.
- `ui/src/lib/auth.jsx`, `ui/src/lib/subsideApi.js`, and
  `ui/src/components/mapworkbench/SubsideAnalysis.jsx` — refresh-aware requests,
  session recovery, and explicit reauthentication UX.
- `api/README.md` and `ARCHITECTURE.md` — final auth and credential lifecycle.

No existing user-owned workflow or untracked files are in scope for incidental
cleanup or reversion.

## API/schema changes

### Phase 1

- Existing `/auth/token` response remains free of refresh tokens.
- `POST /runs` continues to return a run id and status; it does not return the
  per-run token.
- Internal workflow argument names may remain `tapis_token`, `ckan_token`, and
  `stac_token` for compatibility, but their values must be independently
  selected and documented.
- The Phase 1 store is an encrypted SQLite lease database. A shared durable
  store is required for multi-replica deployments; the implementation does not
  silently claim SQLite is cluster-safe.
- Phase 1 supports a single API instance with a persistent protected store. It
  does not claim duplicate-free reconciliation across multiple replicas.

### Phase 2

- Add a server-managed session/refresh contract only after storage and cookie
  policy are approved. Do not add a `refresh_token` field to
  `AuthTokenResponse`.
- Prefer an HttpOnly, Secure, SameSite-appropriate session cookie or an
  equivalent server-session identifier over browser-accessible refresh-token
  storage.

## Data flow

```text
Browser OAuth code
        |
        v
API exchanges code with Tapis
        |
        +--> access token for the current request/session
        +--> refresh token retained only server-side (Phase 2 only)
        |
Browser submits run with access token
        |
        v
API validates caller -> mints bounded per-run token
        |
        +--> workflow args: per-run Tapis credential only
        +--> run credential metadata: no secret value
        |
        v
Workflow run/publish tasks execute as the user
        |
        v
Terminal state or cleanup job -> revoke per-run token
```

The browser access token controls API access only. The per-run token controls
the asynchronous workflow. These lifetimes are intentionally decoupled.

## Risks and tradeoffs

- **Token leakage:** Workflow arguments may be visible to workflow operators or
  task metadata. Mitigation: use the shortest bounded TTL, redact logs/errors,
  and verify whether Tapis Workflows supports secret inputs. A per-run token is
  still a bearer credential.
- **Token scope mismatch:** CKAN/STAC may not accept the minted user token or
  may require different authorization. Mitigation: test each service and keep
  credentials separate.
- **Revocation gaps:** API crashes or network failures can prevent immediate
  cleanup. Mitigation: durable cleanup metadata, retries, scheduled cleanup,
  and bounded expiry.
- **Duplicate submissions:** Retrying after an ambiguous submission could mint
  multiple tokens or launch duplicate runs. Mitigation: do not auto-resubmit;
  use an idempotency key or reconcile the workflow submission before retrying.
- **Refresh-token storage risk:** Phase 2 increases the impact of backend
  compromise and requires key management. Mitigation: keep it out of Phase 1
  unless silent browser recovery is a confirmed requirement.
- **Deployment topology:** In-memory token metadata is insufficient with
  multiple API replicas. A shared database or queue is required for durable
  cleanup.

## Alternatives considered

1. **Return the OAuth refresh token to the browser.** Rejected: it creates a
   long-lived bearer secret in JavaScript/localStorage and expands the impact of
   XSS or browser compromise.
2. **Refresh the original browser token inside the workflow.** Rejected: the
   workflow should not receive a refresh token, and its task runtime should not
   own interactive OAuth session state.
3. **Mint one long-lived token and never revoke it.** Rejected: it leaves
   unnecessary bearer credentials active and creates avoidable cleanup risk.
4. **Use only a server-side refresh-token session.** Insufficient for the
   required run durability: it can refresh future API calls, but the already
   submitted workflow still has the original access token unless the workflow
   receives a separate durable credential.
5. **Use a fixed service-account token for all runs.** Rejected: it loses
   user-attribution and may grant more access than the caller needs.
6. **Use the user-provided `/v3/tokens` request immediately in production.**
   Deferred: the exact portals tenant mint/revoke contract, scopes, and
   permissions must be verified with an approved non-production test first.

## Test plan

### Hermetic unit tests

- OAuth exchange receives a refresh token but never puts it in the browser
  response model.
- Per-run TTL is computed from the workflow walltime, includes the configured
  buffer, and is clamped to the server maximum.
- Mint request uses the authenticated username and stable target-site id, and
  never logs the token value.
- Workflow args contain the per-run token and do not contain the browser access
  token or refresh token.
- CKAN/STAC token selection is independent and follows configuration.
- Mint failure prevents workflow submission.
- Submission failure triggers best-effort cleanup without masking the original
  error.
- Revoke is attempted for completed, failed, cancelled, and timeout cleanup
  paths; repeated cleanup is safe.
- Revoke failure is recorded for retry and does not expose a secret.
- Error messages and structured logs redact JWTs, refresh tokens, and token
  response bodies.
- Existing user-owned worktree changes remain unchanged by the implementation.

### API/UI tests

- A short-lived mocked browser token expires while a run remains active; the UI
  does not submit a duplicate run and shows the correct reauthentication state.
- If Phase 2 is approved, a refresh-aware API call obtains a new access token
  through the server session and the refresh token never reaches browser
  storage, response JSON, or request headers from the browser.
- Reloading the UI reattaches to an active run by durable run history after
  reauthentication.

The hermetic tests also cover crash-safe ordering around persistence and
submission. They do not claim to prove idempotency for a lost Tapis POST
response; that remains an explicit integration/deployment risk.

### Approved integration tests

In a sandbox or other explicitly approved Tapis environment:

- Mint a short-lived run token, perform the exact Tapis Files/Workflows calls,
  wait past the original browser-token expiry, and verify the run continues.
- Verify CKAN and STAC operations separately.
- Revoke the token and verify subsequent calls fail.
- Exercise cleanup after terminal workflow states and after simulated API
  restart.

These tests are external state mutations and require explicit approval before
execution. Production token minting, revocation, workflow registration, and
deployment are out of scope for this design review.

## Documentation plan

- Update `api/README.md` to describe the separation between browser access
  tokens and per-run workflow credentials.
- Update `ARCHITECTURE.md` with the final token lifecycle, cleanup behavior,
  and any session-storage boundary.
- Add environment-variable documentation for TTL bounds, target-site id, and
  any storage/key-management settings.
- Document the verified Tapis mint/revoke contract and required CKAN/STAC
  permissions only after sandbox validation.

## Rollout/rollback plan

1. Add an explicit lifecycle feature flag. When enabled, a valid encryption key
   and persistent store path are required; missing or malformed configuration
   rejects runs. There is no browser-token fallback.
2. Deploy the API changes with minting disabled; run hermetic tests and config
   validation.
3. Enable minting in a sandbox and run the approved integration matrix.
4. Enable production minting after review of token permissions and cleanup
   observability.
5. Re-register workflow pipelines only after the pipeline argument contract is
   finalized; pipeline registration is an external write requiring approval.
6. Roll back by disabling per-run minting and restoring the prior pipeline/API
   version. Existing in-flight runs using minted credentials should be allowed
   to expire or be explicitly cleaned up; do not revoke unrelated tokens.

## Open questions

1. Is the immediate release required to keep the workflow alive only, or must
   the browser silently refresh and continue polling after access-token expiry?
2. If Phase 2 is required, what approved durable store and encryption/key
   management mechanism are available to the API deployment?
3. What is the maximum supported H2I/WERC runtime, including queue time and
   publish time? Recommended initial default: configured walltime plus a small
   buffer, capped by an operator-set maximum.
4. Does the deployment provide a protected persistent path for the SQLite lease
   store, and is the API single-instance? Multi-replica operation is not
   supported by this Phase 1 implementation.
5. Does the configured reconciliation service account have permission to revoke
   user-associated run tokens after an API restart?
6. Does a `/v3/tokens` token authorize Files, Workflows, CKAN, and STAC as
   required, or do downstream services need separate credentials?
7. Can Tapis Workflows store token inputs as secrets rather than ordinary task
   arguments?
8. Should user logout revoke the server-side refresh session and active run
   tokens, or should active analyses continue independently?
9. Is an approved Tapis sandbox tenant available for short-TTL mint/revoke
    tests?

## Decisions

### 2026-10-21 - Separate workflow durability from browser session durability

- **Decision:** Proposed default is a bounded per-run token for asynchronous
  workflow execution; server-managed refresh sessions remain an optional second
  phase.
- **Reason:** Refreshing the browser session does not retroactively change the
  credential already embedded in a running workflow.
- **Alternatives rejected:** Browser refresh-token exposure and fixed
  long-lived service tokens are rejected for security and attribution reasons.
- **User feedback:** No approval recorded yet; this is a proposal for review.
- **Impact on implementation:** Phase 1 can be implemented and tested without
  introducing a refresh-token database, but it still requires verified Tapis
  mint/revoke behavior and durable cleanup metadata.

### 2026-10-21 - Do not expose refresh tokens

- **Decision:** Never add `refresh_token` to the browser-facing auth response,
  localStorage, workflow args, or ordinary logs.
- **Reason:** Refresh tokens are long-lived bearer credentials.
- **Alternatives rejected:** Browser-managed refresh is not acceptable for this
  release unless the security design is explicitly changed and approved.
- **User feedback:** No approval recorded yet; this is a proposed security
  invariant.
- **Impact on implementation:** `exchange_code()` may continue to receive the
  refresh token, but its caller must either store it through an approved secure
  session mechanism or discard it.

### 2026-10-21 - Use a disposable Tapis sandbox lifecycle test

- **Decision:** Validate the token-lifecycle design with a short-lived minted
  token, a workflow that outlives the original browser token, explicit revoke
  verification, restart/reconciliation coverage, and failed mint/revoke cases.
- **Reason:** This exercises the actual failure mode and the cleanup paths that
  hermetic mocks cannot prove.
- **Alternatives rejected:** Unit tests alone are insufficient because they do
  not verify the portals tenant's token permissions, mint/revoke contract, or
  downstream CKAN/STAC behavior.
- **User feedback:** User agreed that this is the plan to test.
- **Impact on implementation:** The integration test must use a disposable test
  identity/workflow, a simulated browser token with a 1–2 minute TTL, and a
  per-run token whose TTL exceeds the test workflow's maximum duration plus a
  buffer. Explicit approval is required before any external mint, workflow
  submission, or revoke operation. Production testing remains out of scope.

### 2026-10-21 - Keep the per-run token longer than the workflow

- **Decision:** Use the 1–2 minute lifetime only for the simulated browser
  access token; the per-run token must outlive the test workflow and cleanup
  window.
- **Reason:** A per-run token that expires before the workflow completes would
  test token expiration itself, not whether run credentials are decoupled from
  the browser session.
- **Alternatives rejected:** A 1–2 minute per-run token is unsuitable for a
  workflow expected to run longer than the browser token.
- **User feedback:** None; this is a safety correction to the test design.
- **Impact on implementation:** The sandbox harness must configure separate
  TTLs and assert that the per-run token's expiry is later than the workflow
  deadline plus cleanup buffer.

### 2026-10-21 - Sandbox preflight findings

- **Decision:** Treat the initial live probe as contract/permission preflight,
  not as completion of the end-to-end workflow test.
- **Reason:** Mint and revoke succeeded, and Workflows accepted the minted user
  token, but Files could not access `cloud.data` because the test user lacks
  TMS_KEYS credentials. CKAN/STAC read probes returned success but do not prove
  write permission. The current Subside implementation also does not yet mint
  per-run credentials or persist cleanup metadata.
- **Alternatives rejected:** Starting a production-like workflow with missing
  Files credentials would produce an ambiguous infrastructure failure rather
  than test token-expiry durability.
- **User feedback:** User authorized use of the `.env` user; no approval has
  been recorded for changing that user's Tapis system credentials or writing to
  a non-disposable CKAN/STAC resource.
- **Impact on implementation:** Before the full test, provision or identify a
  disposable Files system/path for the test user, confirm CKAN/STAC write
  targets, and implement the per-run token/cleanup path.

### 2026-10-21 - Use Tapis Files API, not direct SSH

- **Decision:** The test and Subside implementation must interact with storage
  through the Tapis Files API. No direct SSH login or shell access is part of
  the workflow test.
- **Reason:** The `TMS_KEYS` error came from the backend authentication method
  configured on the Tapis `cloud.data` system; it does not mean the test agent
  should SSH to the host.
- **Alternatives rejected:** Direct SSH would bypass the Tapis authorization
  path being tested and would not represent the Subside workflow.
- **User feedback:** User clarified that SSH access should not be used.
- **Impact on implementation:** Use a pre-provisioned Tapis Files system/path
  whose credentials are configured in Tapis, or change the staging target to a
  Tapis-supported storage backend appropriate for the deployment. Do not add
  SSH commands or host credentials to the test harness.

### 2026-10-21 - Burner token lifecycle probe results

- **Decision:** Mark the token-lifecycle portion of the sandbox plan as
  validated; leave the Earthdata-backed workflow portion pending explicit
  approval of credential staging or a credential-free disposable workflow.
- **Evidence:** With `.env.burner`, a 120-second minted user token successfully
  accessed Tapis Files and Workflows before expiry and was rejected by both
  services after expiry. A separate 10-minute minted user token continued to
  access both services after the short token expired. Revocation returned HTTP
  200 and subsequent use of the revoked token was rejected. Malformed mint and
  invalid revoke requests returned HTTP 400.
- **Limitation:** The attempted H2I submission was stopped before any Tapis
  request because the test harness would upload the Earthdata `.netrc` from
  `.env.burner` to `cloud.data` and submit real compute. The network approval
  gate required explicit authorization for that credential transfer. No SSH was
  used and no Earthdata credential was uploaded by the completed tests.
- **Impact on implementation:** The remaining end-to-end test must use an
  explicitly approved disposable credential-staging path, or a credential-free
  test workflow. It must still verify workflow completion after browser-token
  expiry, cleanup/revocation, restart reconciliation, and failed cleanup.

### 2026-10-22 - Burner H2I workflow attempts

- **Evidence:** Two explicitly authorized H2I attempts used `.env.burner`, a
  120-second browser-simulation token, and a separate 60-minute per-run token.
  Both successfully staged the AOI and Earthdata `.netrc` through Tapis Files,
  submitted a Workflows run, and reached the post-expiry poll using the
  separate token. The first run later failed after a polling DNS outage caused
  cleanup to revoke the still-active per-run token. The retry used resilient
  polling and failed in the H2I `run` task before reaching `publish` or
  `stac-publish`.
- **Cleanup:** Both disposable staging directories were deleted through Tapis
  Files. Both per-run tokens were revoked with HTTP 200. No CKAN/STAC writes
  were enabled.
- **Interpretation:** The test demonstrates token separation and expiry
  behavior, but not successful completion of the Earthdata-backed H2I job. The
  remaining failure is in the Tapis Jobs/H2I execution path or its environment,
  not evidence that the short browser token expired inside the workflow. The
  remote task failure detail could not be retrieved after the external-tool
  usage limit was reached.
- **Next diagnostic:** Repeat a read-only task-detail query when Tapis access is
  available, including the run-task execution output/job UUID and its failure
  message. Do not change token design or add refresh-token exposure based on
  this inconclusive compute failure.

### 2026-10-23 - Approve encrypted per-run token leases

- **Decision:** Implement Phase 1 with a bounded per-run token, encrypted SQLite
  lease records, best-effort revoke, and startup reconciliation through the
  configured service account. Fail closed when lifecycle configuration or minting
  is unavailable; do not reuse the browser token.
- **Reason:** The live probe confirmed the mint/revoke contract, while restart
  cleanup cannot work from a token id alone because Tapis revoke requires the
  JWT value. Encrypted storage provides a recoverable local lease without
  exposing the token to the browser or ordinary diagnostics.
- **Alternatives rejected:** In-memory metadata cannot reconcile after restart;
  storing plaintext JWTs is not acceptable; passing the browser token as a
  fallback preserves the original failure mode and weakens the security boundary.
- **User feedback:** The user said “lets do it” after reviewing the proposed
  fix and sandbox plan.
- **Impact on implementation:** Add `api/services/token_store.py`, token mint/
  revoke helpers, bounded TTL configuration, manager cleanup/reconciliation,
  hermetic API tests, and documentation. Preserve the existing workflow
  `tapis_token` argument names and the user-owned H2I YAML edit.

### 2026-10-23 - Bound ambiguous external operations

- **Decision:** Do not retry a token mint or workflow submission after a timeout
  or other ambiguous response. Persist `submission_unknown` when possible, keep
  the run token until reconciliation or natural expiry, and never blindly submit
  a second workflow.
- **Reason:** The verified Tapis contracts do not provide an idempotency key or
  a token lookup operation that can prove an ambiguous POST was not accepted.
- **Alternatives rejected:** Blind retries can create duplicate bearer tokens or
  duplicate scientific runs. Revoking immediately can break a run that was
  accepted remotely.

### 2026-10-23 - Reject invalid TTLs before mint requests

- **Decision:** The client-side mint helper rejects non-positive or non-integer
  TTL values before making a Tokens API request.
- **Reason:** The sandbox accepted a negative TTL instead of returning a useful
  validation error. Production run-token calculation already clamps to the
  configured positive bounds, but the lower-level helper should fail closed too.
- **Impact on implementation:** Add local validation and regression coverage;
  the verified positive mint/revoke contract is unchanged.

### 2026-10-23 - Persist Pod lease state on a dedicated volume

- **Decision:** Pod deployments must mount a dedicated Tapis volume at
  `/var/lib/subside` and store the encrypted lease database there.
- **Reason:** The container filesystem is not a restart-safe reconciliation
  store. Reusing an existing application-data volume would risk mixing token
  leases with unrelated state.
- **Impact on implementation:** `tapis/register_pods.py` now forwards the
  run-token settings, creates the named volume idempotently, and fails closed
  when the encryption key is absent.
- **User feedback:** None; this is the conservative safety boundary surfaced by
  the pre-implementation review.
- **Impact on implementation:** Add explicit state handling and document the
  bounded natural-expiry window as a remaining deployment risk.

### 2026-10-23 - Confirm the live token API contract

- **Decision:** Use `POST /v3/tokens` for minting and `POST /v3/tokens/revoke`
  with `{ "token": <JWT> }` for revocation.
- **Reason:** The installed Tapis Tokens OpenAPI defines these endpoints and the
  burner sandbox probe confirmed successful mint, expiry, revoke, and rejected
  post-revoke calls.
- **Alternatives rejected:** A guessed DELETE-by-id endpoint is not the verified
  Tapis contract; a token identifier alone is insufficient for revoke.
- **User feedback:** None beyond the approved test/implementation request.
- **Impact on implementation:** `api/services/tapis.py` must use the exact JSON
  shapes and retain no raw response body in errors or logs.

### 2026-10-23 - Implementation completed with bounded ambiguity handling

- **Decision:** Mark Phase 1 implemented with encrypted single-instance leases,
  fail-closed minting, terminal/startup cleanup, and extended transient Jobs
  polling retries. Leave token-mint/submission idempotency and multi-replica
  coordination as explicit deployment follow-up risks.
- **Reason:** The repository and verified Tapis contracts do not expose a tested
  idempotency key or lookup path for ambiguous POST responses. Blind retries
  would be less safe than bounded natural expiry.
- **Alternatives rejected:** Claiming full distributed durability or silently
  retrying ambiguous submissions would overstate the guarantee and risk duplicate
  workflows or bearer-token leaks.
- **User feedback:** User approved implementation with “lets do it.”
- **Impact on implementation:** Live sandbox execution remains a separate
  externally approved validation step; no live write was performed by this code
  change.

### 2026-10-27 - Authenticate password grants with the registered OAuth client

- **Decision:** When both `TAPIS_CLIENT_ID` and `TAPIS_CLIENT_KEY` are configured,
  password-grant login sends them as HTTP Basic authentication so Tapis can
  return a refresh token. If neither is configured, preserve the legacy
  password-grant fallback. If only one is configured, fail before the network
  request.
- **Reason:** A live Portals token-endpoint probe returned an access token and a
  refresh token only when the registered client credentials were supplied. The
  previous helper omitted Basic authentication, so the API could authenticate
  the user but could not persist a refresh token for the broker.
- **Security constraint:** Client credentials, passwords, access tokens, and
  refresh tokens remain absent from diagnostics. The refresh diagnostic reports
  only configuration state, HTTP/result categories, token-presence booleans,
  and whether rotation occurred.
- **Impact on implementation:** `api/services/tapis.py`,
  `api/scripts/test_refresh.py`, and the focused token lifecycle tests now
  cover the configured, fallback, and partial-configuration cases.

## User feedback / decisions

- 2026-10-21: User asked what can be tested and implemented, then approved the
  disposable sandbox lifecycle plan.
- 2026-10-23: User said “lets do it,” approving implementation of the bounded
  per-run token lifecycle. Silent browser refresh remains out of Phase 1.
- Remaining deployment questions are listed above; they do not block the
  hermetic implementation, but they do block production enablement in a
  multi-replica deployment.
