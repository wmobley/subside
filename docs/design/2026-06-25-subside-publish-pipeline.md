# `subside-publish`: a standalone publish-only Tapis pipeline for finished jobs

## Status

Implemented

## Objective

Add a reusable Tapis Workflows pipeline that publishes an **already-finished**
SUBSIDE compute job's archived outputs to CKAN + STAC, given only the job UUID —
without re-running the (expensive) analysis. This recovers runs whose original
pipeline died after the compute job succeeded (e.g. the poll-loop failure of
2026-06-25), and is a general operational tool for re-publishing any run.

## User need

WERC job `05645338-47d6-4503-85bf-6b1550c58d51-007` finished on LS6, but its
pipeline run had already failed at the `run`-task poll step, so the `publish` and
`stac-publish` tasks never fired — the outputs sit in the LS6 archive,
unpublished. Re-running the full pipeline would recompute (~hours, queue wait).
The user wants to publish it via a pipeline (server-side on TACC, where the
outputs already live) rather than a local one-off CLI, and to keep that pipeline
around for the next orphaned run.

## Current code/system summary

- Pipelines are single YAML files in `subside/tapis/workflows/pipelines/`.
  `register.py` auto-discovers them via `PIPELINE_GLOB =
  "tapis/workflows/pipelines/*.yaml"` and registers each into the `subside-ops`
  workflows group; `--recreate-pipelines` deletes + recreates to re-sync
  structural changes (tasks). Function-task `code` is base64-encoded at register
  time.
- A pipeline YAML has: `id`, `type: workflow`, `group_id`, `tenant_id`,
  `params:` (typed inputs), and `tasks:` (each a `function` task with `input:`
  bound `value_from: {args: <param>}` or `{task_output: ...}`, and inline
  `code:`).
- Both existing pipelines already contain `publish` and `stac-publish` tasks
  that read the run job's archive and dual-write to CKAN + STAC:
  - `werc-opera.yaml`: `publish` (re-emits `werc-run-manifest.json` →
    `subside-run-manifest.json`) + `stac-publish` (~645 lines: fetch manifest +
    COGs, build CKAN dataset + STAC item, with httpx 5xx/429 retry).
  - `h2i-opera.yaml`: same shape for `run-manifest.json`.
  - Both currently source `ARCHIVE_URI` from `{task_output: {task_id: run,
    output_id: archive}}` — i.e. they depend on the `run` task having run in the
    same pipeline.
- `stacmap` (pip-installed from `stac-platform`) provides
  `parse_manifest()` (auto-detects WERC vs H2I by manifest artifacts) and
  `publish_from_dir()` / `publish_item()` — the library form of the dual-write,
  also used by the `stacmap.publish` CLI.

## Proposed design

New file `subside/tapis/workflows/pipelines/subside-publish.yaml` —
`id: subside-publish`, `group_id: subside-ops`. Three function tasks:

1. **`resolve`** — input: `job_uuid`, `tapis_base_url`, `tapis_token`.
   - `getJob(jobUuid=job_uuid)` → `archiveSystemId` / `archiveSystemDir` →
     `ctx.set_output("archive", "tapis://<sys>/<dir>")`.
   - Infer pipeline flavor from `job.appId`
     (`subside-werc-opera-analysis` → WERC / `werc-run-manifest.json` /
     `subside-werc`; otherwise H2I / `run-manifest.json` / `subside-h2i`) and
     emit `ctx.set_output("manifest_name", ...)` + `set_output("item_prefix", ...)`.
     A `manifest_name` pipeline param (default `""` = auto) overrides the
     inference.
   - Reuses the same resilient `_get_job` retry helper added to the `run` tasks
     (see the poll-loop hardening spec) so `resolve` itself tolerates a transient
     Tapis blip.

2. **`publish`** — `depends_on: [resolve]`. `ARCHIVE_URI` from
   `{task_output: {task_id: resolve, output_id: archive}}`, `MANIFEST_NAME` from
   resolve output. Same behavior as the existing `publish` task: locate the run
   manifest in the archive and re-emit the unified `subside-run-manifest.json`.

3. **`stac-publish`** — `depends_on: [resolve, publish]`. `ARCHIVE_URI` +
   `MANIFEST_NAME` + `ITEM_PREFIX` from resolve; CKAN/STAC args from params.
   Same dual-write behavior as the existing `stac-publish` task. No-ops when
   `ckan_token`/`stac_url` are blank (preserved).

`params`: `job_uuid` (required), `tapis_base_url`, `tapis_token` (required),
`manifest_name` (default `""` = auto), `stac_collection` (default
`subsidence-rates`), `stac_item_id` (default `""` = derive), `ckan_url`,
`ckan_org`, `ckan_token`, `stac_url`, `stac_token` — same publish args as the
existing pipelines, minus all the `run`/compute params.

**Task-code reuse decision (the main tradeoff — see Alternatives):** the
`publish` and `stac-publish` task bodies are **copied from `werc-opera.yaml`**
with two minimal changes — `ARCHIVE_URI`/`MANIFEST_NAME`/`ITEM_PREFIX` come from
the `resolve` task/params instead of being hard-wired — because that code is
already production-proven (CKAN/STAC 5xx+429 retry, Files API retry, asset
construction, bbox fallback) and WERC/H2I differ only in manifest filename +
item prefix, which we now parameterize. This duplicates ~700 lines of inline
code; mitigated by a follow-up to extract the shared logic (below).

### Triggering (for the user's immediate need)

Via the API client / orchestrate-style trigger or `smoke_test`-style helper:
`job_uuid = 05645338-47d6-4503-85bf-6b1550c58d51-007`, `tapis_token` = the
caller's, `ckan_url`/`ckan_org`/`stac_url` from `.env`, `ckan_token`/`stac_token`
default to the caller's Tapis token. Runs entirely on TACC.

## Files likely affected

- **New:** `subside/tapis/workflows/pipelines/subside-publish.yaml`.
- `subside/tapis/workflows/smoke_test.py` — add `"publish": "subside-publish"`
  to `PIPELINES` so `dump_run.py --list` / smoke helpers can see it.
- Possibly a small trigger helper (e.g. `tapis/workflows/republish.py`) or a new
  API endpoint in `api/services/manager.py` (`submit_publish(job_uuid)`) — out of
  scope for v1 unless requested; v1 can trigger via the existing generic
  workflow-run submission path.
- `api/config.py` `PIPELINES` map — only if the API should expose the publish
  pipeline; defer until an endpoint is wanted.

## API/schema changes

- New pipeline registered in the `subside-ops` workflows group:
  `id: subside-publish` with params/tasks above.
- No CKAN/STAC schema change: it writes the same dataset/item shape the existing
  `stac-publish` task already produces.
- No HTTP API change in v1 (no new endpoint unless requested).

## Data flow

`job_uuid` → **resolve** (`getJob` → `archive` tapis:// URI + manifest_name +
item_prefix) → **publish** (read run manifest from archive → emit unified
manifest) → **stac-publish** (fetch manifest + COG(s) from archive → CKAN
dataset + resources → STAC collection ensure + item upsert). Identical to the
back half of the existing pipelines; the only new edge is `resolve` replacing the
`run` task as the source of `archive`.

## Risks and tradeoffs

- **Code duplication (primary).** Copying ~700 lines of `publish`/`stac-publish`
  code into a third pipeline means three places to fix a publish bug. Mitigation:
  the copy is mechanical and the follow-up refactor (extract to
  `stacmap`/thin wrapper) is filed below.
- **Drift.** If `werc-opera.yaml`'s `stac-publish` is later changed, the copy
  goes stale. Mitigation: a comment in both pointing at each other + the refactor.
- **Re-publish / idempotency.** Re-running for the same job upserts the same
  CKAN dataset + STAC item (deterministic `dataset_name`/`item_id`), so it is
  safe to re-run; but if `stac_item_id` is left to auto-derive, the derivation
  must be stable across re-runs (use job dates + uuid, as the existing
  `_default_item_id` does).
- **Wrong-flavor inference.** If `resolve` misreads `appId`, it could fetch the
  wrong manifest name. Mitigation: `manifest_name` param override + fail fast
  with a clear message when the manifest isn't found.
- **Auth.** `tapis_token` must belong to the job owner (to read the archive) and
  have CKAN/STAC write rights — same constraint as the live pipeline.
- **External write to register.** `register.py --recreate-pipelines` mutates the
  Tapis workflows group; requires approval (gate below).

## Alternatives considered

1. **Lean stac-publish that just calls `stacmap.publish_from_dir`.** A much
   smaller task (fetch files → one library call), no duplicated bespoke code.
   Rejected as the v1 default because the inline task adds production robustness
   (httpx 5xx/429 retry, custom CKAN resource fields, mimetype/bbox handling)
   that `publish_from_dir` may not match; adopting it would change publish
   behavior, not just relocate it. **Strong candidate for the follow-up refactor**
   — fold that robustness into `stacmap`, then have all three pipelines call the
   thin wrapper.
2. **One-off local `stacmap.publish` CLI** (the prior plan). Rejected by the
   user: runs on a laptop, pulls COGs down, not reusable.
3. **Re-run the full pipeline.** Rejected: recomputes hours of analysis.
4. **`archive_uri` input instead of `job_uuid`.** Rejected by the user in favor
   of the more ergonomic job-uuid + `resolve` task.
5. **Add publish/stac-publish as resumable steps on the existing pipeline.**
   Not supported by the engine for an already-failed run; would still need a
   separate trigger path.

## Test plan

- **Lint/parse:** YAML parses and every embedded task body `compile()`s (same
  check used for the poll-loop change).
- **`resolve` unit logic:** extract `_get_job` + appId→manifest_name/item_prefix
  inference and unit-test (WERC appId → `werc-run-manifest.json`/`subside-werc`;
  H2I appId → `run-manifest.json`/`subside-h2i`; `manifest_name` override wins).
- **Dry-run / no-op path:** trigger with blank `ckan_token`/`stac_url` and
  confirm `stac-publish` no-ops (writes nothing) while `resolve`+`publish`
  succeed — a safe end-to-end smoke that touches no external service.
- **Live publish (gated):** trigger for job `05645338-…-007` with real
  CKAN/STAC creds; verify one CKAN dataset (4 resources) + one STAC item; verify
  re-running upserts (no duplicates).
- **Negative:** bad/non-existent job uuid → `resolve` fails fast with a clear
  message; manifest-not-found → clear error.

## Documentation plan

- Add a section to `tapis/workflows/README.md` / `DESIGN.md`: "Re-publishing a
  finished run" with the `subside-publish` trigger example.
- Cross-reference comments between `subside-publish.yaml` and the source
  `werc-opera.yaml` publish/stac-publish tasks (drift warning).

## Rollout/rollback plan

- **Rollout:** add the YAML, `register.py --pipelines-only --recreate-pipelines`
  (external write — approval required), smoke-test the no-op path, then run the
  gated live publish for `05645338-…-007`.
- **Rollback:** delete the `subside-publish` pipeline from the group (or just
  leave it unused — it has no schedule/trigger of its own); remove the YAML.
  No data migration; CKAN/STAC writes it performs are independently reversible
  (`package_delete` / item delete).

## Open questions

1. v1 trigger mechanism: a small `republish.py` CLI helper, or wire a
   `POST /runs/{job_uuid}/publish` endpoint into the API? (Recommend the CLI
   helper for v1; endpoint later.)
2. Commit to the follow-up refactor (extract publish logic into `stacmap`, thin
   the tasks) now as a tracked task, or revisit after v1 proves out?
3. Should `resolve` verify the job actually `FINISHED` (vs publishing a
   partial/failed archive)? (Recommend: yes — fail unless status is FINISHED.)

## Decisions

- 2026-06-25: User chose to build a **pipeline** (server-side on TACC) over the
  one-off local CLI publish.
- 2026-06-25: Input = **job UUID** with a `resolve` task auto-deriving the
  archive (over passing the archive URI directly).
- 2026-06-25: Scope = **generic WERC + H2I** (`subside-publish`), relying on
  `parse_manifest` auto-detection + `manifest_name`/`item_prefix` from `resolve`.

## Implementation summary (2026-06-25)

Implemented as designed (reuse + CLI trigger + require FINISHED).

- **New:** `subside/tapis/workflows/pipelines/subside-publish.yaml` — `id:
  subside-publish`, group `subside-ops`, 11 params, 3 tasks (`resolve` →
  `publish` → `stac-publish`). The `publish`/`stac-publish` bodies were lifted
  **verbatim** from `werc-opera.yaml` by a generator (no hand-transcription);
  only the WERC-specific constants are parameterized:
  - `publish`: manifest name → `ctx.get_input("MANIFEST_NAME")`, unified-manifest
    label → `ctx.get_input("PIPELINE_LABEL")`.
  - `stac-publish`: `MANIFEST_NAME`/`ITEM_PREFIX`/`subside_pipeline` →
    `val(...)` from resolve outputs.
  The generator asserts each substitution matches exactly once, so source drift
  fails loudly rather than silently mis-generating.
- **New:** `subside/tapis/workflows/republish.py` — CLI trigger. Default is a
  VALIDATION run (blank `ckan_token`/`stac_url` → `stac-publish` no-ops, no
  external write); `--publish` performs the real CKAN+STAC dual-write; `--wait`
  polls + dumps failures.
- **Edit:** `smoke_test.py` `PIPELINES`/`PIPELINE_FILES` gain a `publish` entry
  so `dump_run.py --list` and helpers recognize the new pipeline.

Deviations from the approved design: none material. The unified-manifest
"pipeline" label in the `publish` task was also parameterized (`PIPELINE_LABEL`)
so H2I runs are labeled correctly — a small addition consistent with the generic
scope.

Validation performed:
- YAML parses; all three task bodies `compile()`.
- Wiring asserted: `ARCHIVE_URI`/manifest/prefix/label flow from `resolve`
  outputs; `depends_on` is `resolve` → `publish` → (`resolve`,`publish`);
  `JOB_UUID` ← `args.job_uuid`.
- WERC constants confirmed parameterized in `publish` + `stac-publish`.
- `resolve` appId→(manifest, prefix, label) inference unit-tested (WERC, H2I,
  manifest override) and matched against the resolve task source; FINISHED guard
  present.
- `republish.py` compiles; `--help` OK; `--wait` now supplies
  `--poll-interval`/`--timeout` that `_poll` requires.

NOT yet done (external write — needs explicit approval):
- Register the pipeline so the engine knows it:
  `python tapis/workflows/register.py --pipelines-only --recreate-pipelines`.
- The gated live publish of job `05645338-…-007` (`republish.py … --publish`).

Open-question resolutions:
1. v1 trigger = CLI helper (`republish.py`); no API endpoint yet.
2. Follow-up de-dup refactor (fold publish robustness into `stacmap`, thin all
   pipelines) left as a tracked follow-up, not done in v1.
3. `resolve` DOES require `status == FINISHED` (fails fast otherwise).

## Post-registration fix (2026-06-25)

First live run (`bff9f99b-…`) for job `05645338-…-007`: `resolve` ✅ + `publish`
✅, but `stac-publish` failed with `NameError: name 'val' is not defined` at the
`MANIFEST_NAME = val(...)` line. Root cause: in the lifted WERC code,
`MANIFEST_NAME`/`ITEM_PREFIX` are assigned at module top **before** `def val`,
so calling `val()` there was use-before-def. The `compile()` check passed
(syntactically valid; runtime NameError). It crashed **before** any CKAN/STAC
call, so nothing was written.

Fix: the generator now parameterizes those two constants via `ctx.get_input(...)`
(`ctx` is imported at the very top, so no ordering hazard) instead of `val()`.
Added a validation guard asserting `ctx` import precedes the constants, which
precede `def val`, and that no `val()` use-before-def remains. Requires
re-registration (`register.py --recreate-pipelines`) and a re-run.

## User feedback / decisions

- 2026-06-25: User approved the spec as proposed ("yes that's fine") — reuse the
  proven task code, CLI trigger for v1, require FINISHED.
