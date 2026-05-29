# SUBSIDE Tapis Workflows — Design Log

Running log of every decision we make wiring up the Tapis Workflows pipeline. Each new decision gets a dated entry with the **decision**, the **why**, and any **open follow-ups**. Newest entries on top.

Authoritative references:
- Tapis Workflows: https://tapis.readthedocs.io/en/latest/technical/workflows.html
- Tapis Jobs: https://tapis.readthedocs.io/en/latest/technical/jobs.html
- Tapis Files (archives): https://tapis.readthedocs.io/en/latest/technical/files.html

Related local docs:
- `subside/TAPIS_WORKFLOW_TODO.md` — multi-session work plan; this file is the design memory inside the "Tapis Workflow Design" section.
- `subside/workflow_apps/{h2i_lab,werc}/` — the registered Tapis apps that the heavy tasks call.
- `subside/subside_analysis/{h2i_lab,werc}/` — the Python code the apps run.

---

## 2026-05-28 — Resolved (answers from user)

- **Q1 → Tenant: `portals.tapis.io`.** PortalsCI tenant. New workflow group `subside-ops` (assumed; rename via env var in registration script if needed).
- **Q2 → Archive system + path:** unchanged. Keep `cloud.data` with `HOST_EVAL($HOME)/tapis-jobs-archive/${JobCreateDate}/${JobName}-${JobUUID}`. Each pipeline run writes one archive directory; downstream tasks reference it as their input source via the Tapis Files API.
- **Q3 → WERC granularity: four tasks per stage.** `build-stack`, `compute-reference`, `estimate-velocity`, `export-geotiffs`. Trade-off accepted: each stage boundary spills the combined displacement stack (~GB-scale) to NetCDF on the archive and the next stage opens it. Mitigations called out under "Data passing between tasks" below.
- **Q4 → CKAN: later.** v1 `publish` task is stdlib JSON munging only.

### Image + app strategy

To support per-stage decomposition without ballooning the image catalogue, **one Docker image per package, multiple Tapis apps per stage**:

| Image                              | Used by Tapis apps                                                                                                                                          |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `subside-h2i-opera-analysis`       | `subside-h2i-discover`, `subside-h2i-analyze`                                                                                                               |
| `subside-werc-opera-analysis`      | `subside-werc-build-stack`, `subside-werc-compute-reference`, `subside-werc-estimate-velocity`, `subside-werc-export-geotiffs`                              |

Each Tapis app sets a `STAGE` env var (or first arg) that `run.sh` dispatches on; the container then invokes the right `subside_analysis.<pkg>.cli <subcommand>`. App-level differences are queue / `maxMinutes` / `appArgs` / `fileInputs`, not the image. This keeps the GHA build down to two images while giving the pipeline N retry/skip points.

### Data passing between tasks

Tapis Workflows passes artifacts between tasks through the archive system. Each `tapis_job` task's outputs land in its job's archive directory; the next task reads from there using a Tapis Files URI (`tapis://<system>/<path>`).

For the WERC sub-stages, the heavy artifact is the combined displacement stack (one NetCDF per stage boundary). To keep transfer cost bounded:

- `build-stack` writes ONE combined `displacement_stack.nc` derived from all DISP-S1 NetCDFs. Subsequent stages read only this single file, not the per-product NetCDFs.
- `compute-reference` writes `displacement_stack_referenced.nc` (the same stack with reference offset applied) + `reference_summary.json` + the anchor JSON.
- `estimate-velocity` writes `velocity.nc` (small — single 2D raster) + `velocity_summary.json`.
- `export-geotiffs` consumes both the referenced stack and the velocity raster; writes `opera_disp_s1_cumulative.tif` + `opera_disp_s1_velocity.tif` + `export_summary.json`.

Archive paths use a deterministic convention so the next task knows where to look:

```
<archive>/<run-id>/
  preflight-manifest.json
  OPERA_L3_DISP-S1/                 # h2i_lab download products
  displacement_stack.nc             # build-stack output
  displacement_stack_referenced.nc  # compute-reference output
  reference_anchor_FRAME{ID}.json
  reference_summary.json
  velocity.nc
  velocity_summary.json
  opera_disp_s1_cumulative.tif
  opera_disp_s1_velocity.tif
  export_summary.json
  subside-run-manifest.json         # publish output
```

Each task receives the archive base path as an env var (`SUBSIDE_RUN_DIR`) and writes/reads files by deterministic name. No need for the pipeline definition to thread paths between tasks explicitly.

---

## 2026-05-28 — Initial pipeline shape (proposed; pending answers)

### Decision: split the work into 3–4 Tapis Workflow tasks per pipeline

Two pipelines, sharing the discovery / publish tasks:

**Pipeline A: `subside-h2i-opera`** (download + preview only)

```
  discover ──▶ analyze-h2i ──▶ publish
```

**Pipeline B: `subside-werc-opera`** (full stack / reference / velocity)

```
  discover ──▶ analyze-h2i ──▶ build-stack ──▶ compute-reference ──▶ estimate-velocity ──▶ export-geotiffs ──▶ publish
```

(Revised 2026-05-28 after Q3 answer — see "Resolved" section above.)

### Task taxonomy

| Task                  | Type        | What it does                                                                                                                                                                                                  | Tapis app / impl                                  |
| --------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `discover`            | `tapis_job` | `python -m subside_analysis.h2i_lab.cli preflight`. Fast (~30 s). Outputs `preflight-manifest.json` with frame_ids, product_count, warnings. Fails pipeline if `product_count == 0`.                          | `subside-h2i-discover` (`STAGE=preflight`)        |
| `analyze-h2i`         | `tapis_job` | `python -m subside_analysis.h2i_lab.cli run`. Heavy: parallel Earthdata download + crop, preview, zip. Outputs `run-manifest.json` + NetCDFs + previews + archive.                                            | `subside-h2i-analyze` (`STAGE=run`)               |
| `build-stack`         | `tapis_job` | `python -m subside_analysis.werc.cli build-stack`. Reads the per-product NetCDFs from `analyze-h2i`'s archive; writes one combined `displacement_stack.nc` + `disp_products.json`.                            | `subside-werc-build-stack`                        |
| `compute-reference`   | `tapis_job` | `python -m subside_analysis.werc.cli compute-reference`. Reads stack; auto- or manual-picks reference pixels; writes `displacement_stack_referenced.nc` + `reference_anchor_FRAME{ID}.json` + `reference_summary.json`. | `subside-werc-compute-reference`                  |
| `estimate-velocity`   | `tapis_job` | `python -m subside_analysis.werc.cli estimate-velocity`. Reads referenced stack; linear fit; writes `velocity.nc` + `velocity_summary.json`.                                                                  | `subside-werc-estimate-velocity`                  |
| `export-geotiffs`     | `tapis_job` | `python -m subside_analysis.werc.cli export-geotiffs`. Reads referenced stack + velocity; writes `opera_disp_s1_cumulative.tif` + `opera_disp_s1_velocity.tif` + `export_summary.json`.                       | `subside-werc-export-geotiffs`                    |
| `publish`             | `function`  | Stdlib-only Python. Reads every `*manifest.json` / `*summary.json` from the run archive; emits a unified `subside-run-manifest.json` the UI can consume. CKAN publication deferred (Q4).                       | Inline Python in the pipeline definition.         |

### Why split it this way

- **`discover` is its own task** so the pipeline fails fast and cheaply if the AOI has no products. Without this, we'd burn a heavy queue slot just to discover "nothing to do."
- **`analyze-h2i` and `analyze-werc` are separate tasks** so:
  - The H2I-only pipeline (Pipeline A) can stop after `analyze-h2i` and ship preview/archive without paying for WERC.
  - Failed WERC analysis can be retried against the same `analyze-h2i` output without re-downloading multi-GB NetCDFs (uses `skip_download=true`).
- **`publish` is a `function` task** because it's pure JSON munging — no need to spin up a container.
- **Heavy work stays as `tapis_job`** because of dependency weight (`disp-xr`, `rasterio`, `gdal`, etc.). Tapis function tasks run in the workflows runner environment, which we shouldn't bloat with conda envs.

### Why NOT decompose WERC further (stack / reference / velocity / export as separate tasks)

Considered: making each WERC analysis stage its own task. Rejected for v1:

- Data movement cost: passing a multi-GB displacement stack between tasks via the archive would dominate runtime.
- Limited benefit: per-stage retry isn't useful because failures in stack assembly almost always mean re-running everything anyway.
- Complexity: 4 tasks where 1 will do, with no offsetting upside.

Revisit if we find ourselves wanting per-stage UI status or selective re-run.

---

## 2026-05-28 — Reusable ETL primitives extracted

Independently of the Tapis Workflows wiring above, the Python code under `subside_analysis/` was refactored to surface the cross-cutting primitives both packages need. A new `subside_analysis/etl/` package holds dataset-agnostic helpers; `h2i_lab` and `werc` import from it. See [`subside_analysis/REUSABLE_PRIMITIVES.md`](../subside_analysis/REUSABLE_PRIMITIVES.md) for the function-by-function catalog and the deferred items.

What this means for the Tapis Workflows side:

- **No Dockerfile / app JSON changes.** The Tapis images already `COPY subside_analysis /opt/subside/subside_analysis`, so `etl/` ships with both images automatically.
- **No pipeline YAML / `register.py` changes.** Pipeline tasks invoke CLI subcommands, not Python internals; the move was import-only.
- **Behaviour-preserving.** Verified by a fresh preflight run against the Houston-Galveston sample AOI (3 frames, 2 products) producing identical results to the pre-refactor run.

What the second-analysis story now looks like (e.g. other InSAR DAACs, HLS, Sentinel-2):

- The new analysis stands up its own `subside_analysis/<new_pkg>/{config,runner,cli}.py` composition layer.
- It imports `subside_analysis.etl.{auth, aoi, manifest, stack, archive}` for the cross-cutting bits — Earthdata auth survives URS OAuth redirects, AOI loading + bbox conversions, manifest writing, NetCDF stack save/load, zip archive.
- It defines its own discovery / metadata / product-specific stack assembly (analogous to today's `h2i_lab.aoi`, `h2i_lab.metadata`, `werc.stack`).
- Its Tapis app(s) follow the same Dockerfile + `run.sh` + STAGE-dispatch pattern; its workflow pipeline follows the same YAML shape (discover → analyze → publish, or with stage decomposition à la WERC).

Deferred items (quality layers, reference selection, velocity, GeoTIFF writers, preview, OPERA frame index → `opera_disp/`) intentionally still live in `h2i_lab`/`werc` because they have only one consumer; promotion happens when a second analysis lands to validate the right API surface.

---

## Implementation status — 2026-05-28

| Piece                                                                              | Status     | Location                                                                                       |
| ---------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------- |
| Per-stage WERC CLI subcommands (`build-stack`, `compute-reference`, `estimate-velocity`, `export-geotiffs`) | done       | `subside_analysis/werc/cli.py`, `subside_analysis/werc/runner.py`                              |
| Stack save/load NetCDF spill (with `frame_id` stashed as a stack attr)             | done       | `runner._save_stack` / `runner._load_stack`                                                    |
| `run.sh` STAGE dispatch (both h2i_lab + werc)                                      | done       | `workflow_apps/{h2i_lab,werc}/run.sh`                                                          |
| Per-stage Tapis app JSONs (5 new: discover + 4 WERC stages)                        | done       | `workflow_apps/{h2i_lab,werc}/app-*.json`                                                      |
| Pipeline YAML (A: h2i-opera, B: werc-opera)                                        | done — schema unverified | `workflows/pipelines/{h2i-opera,werc-opera}.yaml`                                  |
| Registration script (tapipy)                                                       | done — schema unverified | `workflows/register.py`                                                            |
| `workflows/README.md` explaining the registration flow + invocation                | done       | `workflows/README.md`                                                                          |
| `publish` function task body (stdlib JSON munging)                                 | done — runtime fetch placeholder | inline in each pipeline YAML                                            |

### Known unknowns (need real-tenant verification)

1. **Tapis Workflows V3 schema.** The pipeline YAML uses what I believe is the current shape for `tapis_job` tasks, `depends_on`, `params`, and `function` tasks with inline Python. Several templated placeholders (`{{ tasks.X.outputs.archive }}`, `{{ args.X }}`) may need the live syntax — verify on first dry run.
2. **`publish` runtime fetch.** The inline Python uses `urllib.request` against `tapis://` URIs as a stand-in. The function-task runtime on portals.tapis.io needs either a Tapis Files mount or a fetch helper; first run will tell us which and we'll wire it in.
3. **Workflows API endpoints in tapipy.** `register.py` uses typed methods where they exist (`client.workflows.get_group`, `client.workflows.run_pipeline`) and falls back to raw `client.post` / `client.put` against `/v3/workflows/groups/...` paths where they don't. The fallback paths are documented endpoint shapes; verify on first invocation.

---

## Out-of-scope for this session (will revisit)

- Tapis secrets / identity for Earthdata creds (still env var + `.netrc` in the apps).
- Status normalization endpoint for the React UI (TAPIS_WORKFLOW_TODO API Facade section).
- Per-stage progress reporting from inside `analyze-*` tasks back to Tapis Workflows.
- Manifest schema versioning (we'll cut v0 in `publish`, version it once a second consumer appears).
- CKAN publication step (Q4 deferred).
- Real Tapis smoke test of either pipeline (depends on GHCR image push + the schema verifications above).
