# SUBSIDE Tapis Workflow Todo

Last updated: 2026-05-28

This document tracks the multi-session work to split the OPERA DISP-S1 notebooks into reusable analysis code, Tapis-managed execution, and SUBSIDE UI visualization. The goal is to keep the browser focused on configuration, status, and results while Tapis handles the long-running analysis lifecycle.

Reference: https://tapis.readthedocs.io/en/latest/technical/workflows.html

## Session Progress — 2026-05-28

- **WERC extraction landed.** `subside_analysis/werc/` now contains `stack.py`, `reference.py` (auto + manual + per-frame anchor JSON persistence), `velocity.py`, `export.py`, `config.py` (`WercRunConfig` wraps `H2IRunConfig`), `runner.py` (composes `h2i_lab.runner.run` for the download stage), and `cli.py`. Function map mirrors h2i_lab's in [`subside_analysis/werc/README.md`](subside_analysis/werc/README.md).
- **Companion Tapis batch app.** `workflow_apps/werc/` scaffolded with `Dockerfile`, `run.sh`, `app-cpu.json` (`subside-werc-opera-analysis`), `environment.yaml`, `run-config.example.json`, `README.md`.
- **Cookbook-style runtime conda install.** Both Tapis apps switched from baked-env images to thin `ubuntu:22.04` + `run.sh` that downloads miniconda + materializes the env into `${ENV_INSTALL_DIR:-$WORK}/miniconda3` on first invocation and reuses thereafter. `UPDATE_CONDA_ENV=true` env var (exposed via `app-cpu.json`) forces a rebuild. Matches the `notebookExamples/h2i_lab/run.sh` pattern.
- **GitHub Actions CI.** `.github/workflows/build-images.yml` builds both images in a matrix, pushes to `ghcr.io/<owner>/subside-{h2i-opera,werc-opera}-analysis`, with path-filtered triggers, GHA layer cache, and a manual-dispatch push toggle.
- **Local validation.** `workflow_apps/{h2i_lab,werc}/walkthrough.py` cell-style scripts (`# %%` markers) exercise the full pipeline end-to-end or stepwise in any IDE. Shared `sample_aoi.geojson` over Houston-Galveston.
- **Earthdata auth bug fix.** Plain `requests.Session.auth` was being stripped on the cumulus.asf → urs.earthdata OAuth redirect. New `subside_analysis/h2i_lab/_session.py` introduces `EarthdataSession` (subclasses `requests.Session`, overrides `rebuild_auth` to preserve `Authorization` only for `urs.earthdata.nasa.gov`). Now used by `metadata.fetch_product_bytes` and `download.process_file`.
- **Env tweaks.** Both `environment.yaml`s bumped to `python=3.12` (disp-xr requirement). Added `aiohttp` (opera_utils transitive) and `s3fs`.
- **In-flight.** Local AOI run is mid-verification (frame discovery + product search succeed, auth fix being validated against real Earthdata download). GHCR push, Tapis smoke test, and full pipeline orchestration (Tapis Workflows above the apps) are still open.

## Architecture Decision

- [ ] Keep a small SUBSIDE API facade in front of Tapis.
  - Explanation: Tapis should own workflow registration, run submission, status, archives, files, and job execution. The SUBSIDE API should translate portal-specific concepts such as AOI, frame selection, OPERA product search, and result manifests into stable UI responses. This avoids leaking raw Tapis payloads into React components.

- [x] Use Tapis Workflows for orchestration and Tapis Jobs or a registered app/container for heavy OPERA analysis.
  - Explanation: The notebooks depend on heavy geospatial/scientific packages such as `rasterio`, `geopandas`, `xarray`, `disp_xr`, `h5py`, and MintPy-related utilities. A containerized Tapis app is a better fit than trying to pack all of this into a lightweight workflow `function` task.
  - Resolved 2026-05-28: two Tapis apps (`subside-h2i-opera-analysis`, `subside-werc-opera-analysis`) scaffolded as containers under `workflow_apps/`. Orchestration layer (Tapis Workflows pipeline chaining the two) still open.

- [x] Treat notebook visualization cells as UI reference material, not production execution code.
  - Explanation: The notebooks combine data download, transformation, plotting, widgets, and export. Production should separate those concerns so analysis can run remotely and results can be rendered consistently in SUBSIDE.

## Notebook Extraction

- [x] Inventory the two OPERA notebooks and map each cell to either analysis, visualization, auth, or dead/example code.
  - Explanation: This gives us a clear extraction map before moving code. Expected output is a short table identifying which notebook cells become Python functions, which become React UI features, and which are ignored.
  - Resolved 2026-05-28: cell-by-cell tables in `subside_analysis/h2i_lab/README.md` and `subside_analysis/werc/README.md`.

- [ ] Complete H2I Lab extraction and harden the first Tapis batch app.
  - Explanation: Initial function map and scaffolding live in `subside_analysis/h2i_lab/` and `workflow_apps/h2i_lab/`. Remaining work is dependency verification, credential handling, image build/push, and one real Tapis smoke test.
  - In progress 2026-05-28: dependency verification done (python=3.12, aiohttp, s3fs added); Earthdata credential handling done (env vars or `.netrc`, with `EarthdataSession` fixing the OAuth-redirect 401); image build/push automated via `.github/workflows/build-images.yml`. **Remaining: first real GHCR push + one Tapis smoke test on TACC.**

- [x] Create a reusable analysis package for OPERA DISP-S1 processing.
  - Explanation: Move analysis logic into normal Python modules with functions that can be tested and called from a CLI. Candidate package name: `subside_analysis` or `subside_backend.analysis`.
  - Resolved 2026-05-28: `subside_analysis/h2i_lab/` and `subside_analysis/werc/` are importable, function-based, and reusable.

- [x] Define a canonical run configuration schema.
  - Explanation: Every local run, Tapis run, and UI submission should use the same shape. It should include AOI geometry or bbox, frame id, date range, reference mode, output options, and publication settings.
  - Resolved 2026-05-28: `H2IRunConfig` (frozen dataclass with `from_dict` / `from_json_file`) for h2i_lab, `WercRunConfig` for WERC (wraps `H2IRunConfig` + reference/anchor options). Same JSON shape used by local CLI, walkthrough scripts, and the Tapis app inputs.

- [x] Build a CLI entrypoint for local and Tapis execution.
  - Explanation: Tapis should run a command such as `subside-opera-analysis --config run-config.json --output-dir outputs`. The same command should work locally for debugging.
  - Resolved 2026-05-28: `python -m subside_analysis.h2i_lab.cli {preflight|run}` and `python -m subside_analysis.werc.cli {preflight|run}`, both accepting `--config` + `--output-dir`. Tapis `run.sh` invokes the same modules.

- [ ] Add manifest generation to the analysis output.
  - Explanation: The UI should not scrape output folders. Each run should produce a `run-manifest.json` listing artifacts, bounds, units, dates, CRS, color ranges, provenance, logs, and warnings.
  - Partial 2026-05-28: `preflight-manifest.json` and `run-manifest.json` (h2i_lab) + `werc-run-manifest.json` (WERC) are written, containing config, frames, products, artifact paths, reference summary. Missing for full closure: explicit CRS, units, color-range hints per artifact, log capture, and software-version provenance.

## Analysis Outputs

- [x] Produce cumulative displacement GeoTIFF.
  - Explanation: This is the primary spatial output from the notebooks and should be map-ready, preferably reprojected to EPSG:4326 or another agreed display CRS.
  - Resolved 2026-05-28: `werc.export.write_cumulative_displacement_geotiff` — masks via `recommended_mask`, reprojects to EPSG:4326, converts m→mm, tiled+deflate, tags `date_start`/`date_end`/`reference_lat`/`reference_lon`.

- [x] Produce velocity GeoTIFF in mm/year.
  - Explanation: The velocity map is the key derived product for monitoring and decision workflows. The units and calculation window must be explicit in metadata.
  - Resolved 2026-05-28: `werc.export.write_velocity_geotiff` — `np.linalg.lstsq` per-pixel linear fit in `werc.velocity.estimate_velocity_linear`, masked, reprojected to EPSG:4326, mm/year, tagged with start/end dates.

- [x] Produce lightweight preview images.
  - Explanation: PNG previews let the UI show completed results quickly before loading larger rasters or tile layers.
  - Resolved 2026-05-28: `h2i_lab.preview.make_displacement_overlay_png` + `write_folium_preview` produce a PNG overlay and a Folium HTML map per H2I run.

- [x] Persist reference point/anchor metadata.
  - Explanation: The notebooks rely on automated or manual reference selection. The result manifest must record the selected reference coordinates, method, thresholds, and warnings.
  - Resolved 2026-05-28: `reference_anchor_FRAME{ID}.json` persisted per-frame under `anchor_dir`; full reference summary (lat/lon, threshold tier, pixel count, scores) added to `werc-run-manifest.json`.

- [ ] Persist provenance and run summary.
  - Explanation: Each result should record source products, frame id, date range, software versions, parameters, and user-facing warnings about short time windows or weak reference selection.
  - Partial 2026-05-28: manifests record frame id, date range, source product URLs, parameters, and warnings. Missing: pinned software/package versions (`disp-xr`, `opera-utils`, etc.) and the "weak reference / short window" advisory checks.

## Tapis Workflow Design

- [ ] Define the SUBSIDE workflow group and archive strategy.
  - Explanation: Tapis Workflows resources are owned by groups, and output persistence uses archives. We need a default group id convention, archive ids, archive system id, and archive directory convention.

- [ ] Create the initial pipeline definition.
  - Explanation: Start with a simple pipeline: `preflight-products`, `run-opera-analysis`, and `publish-results`. The heavy step can be a Tapis job or registered Tapis app.

- [ ] Decide which tasks are workflow `function` tasks versus Tapis app/job tasks.
  - Explanation: Lightweight JSON validation, manifest shaping, or publication metadata can be `function` tasks. OPERA analysis should use a container/app because of dependency and runtime weight.

- [ ] Implement workflow registration.
  - Explanation: The backend should check whether the pipeline exists in the selected group and create it if missing. This should follow the existing `flopy-interactive` workflow gateway pattern.

- [x] Implement run submission.
  - Explanation: The backend should call Tapis `runPipeline` or submit the registered Tapis app/job, then return a normalized `runId`, `pipelineId`, `groupId`, and initial status to the UI.
  - Resolved 2026-05-29: `api/manager.submit_run` stages inputs + submits the single monolithic `run` job **as the user** (Tapis Jobs, not `runPipeline`, since the `workflows` restricted service is blocked — see `memory`/orchestrate.py). `POST /api/subside/runs` returns `runId` (job uuid) + normalized status. Non-blocking.

- [x] Implement run status normalization.
  - Explanation: The UI should see stable states such as `queued`, `running`, `completed`, `failed`, and `cancelled`, regardless of the exact Tapis status payload.
  - Resolved 2026-05-29: `api/manager.normalize_status` maps the 13 Tapis job statuses → queued/running/completed/failed/cancelled (unknown fallback). Served by `GET /api/subside/runs/{runId}`.

- [x] Implement result discovery from Tapis outputs.
  - Explanation: On completion, the backend should resolve archive/files output locations and return the `run-manifest.json` plus artifact URLs or file handles usable by the UI.
  - Resolved 2026-05-29: `api/manager.get_results` resolves the finished job's archive, lists artifacts (with Tapis Files content URLs), and fetches the run manifest (werc-run-manifest.json / run-manifest.json). Served by `GET /api/subside/runs/{runId}/results`.

## API Facade

> FastAPI facade landed 2026-05-29 under `subside/api/` (see `api/README.md`).
> Auth is token pass-through (`X-Tapis-Token`), the API acts as the user.

- [x] Add `POST /api/subside/aoi/frames`.
  - Explanation: Fast interactive endpoint for finding OPERA frames intersecting the selected AOI. This should not be a long-running workflow run.
  - Resolved 2026-05-29: `api/discovery.find_frames` (in-process, `require_products=False` → geopandas only). Returns 503 if geopandas is absent.

- [x] Add `POST /api/subside/products/search`.
  - Explanation: Fast preflight endpoint for searching available OPERA DISP-S1 products for frame/date/AOI inputs.
  - Resolved 2026-05-29: `api/discovery.search_products`. Needs `disp_xr`; returns 503 if absent.

- [ ] Add `POST /api/subside/runs/estimate`.
  - Explanation: Estimate product count, approximate download size, expected output count, and whether the selected time range is scientifically weak.

- [ ] Add `POST /api/subside/workflow/register`.
  - Explanation: Portal wrapper around Tapis group/archive/pipeline setup. (Moot while the `workflows` restricted service is blocked; the API submits Jobs directly instead.)

- [x] Add `POST /api/subside/runs`.
  - Explanation: Portal wrapper around Tapis workflow or job submission.
  - Resolved 2026-05-29: submits the monolithic `run` job as the user; returns `runId`.

- [x] Add `GET /api/subside/runs/:runId`.
  - Explanation: Portal wrapper around Tapis run/job status with normalized status for React.
  - Resolved 2026-05-29.

- [x] Add `GET /api/subside/runs/:runId/results`.
  - Explanation: Portal wrapper around Tapis archive/files lookup and result manifest retrieval.
  - Resolved 2026-05-29.

## UI Work

- [ ] Replace the current MODFLOW-centered map workbench language with OPERA/SUBSIDE analysis language.
  - Explanation: `subside/src/components/MapWorkbench.jsx` still says "MODFLOW WEL/RCH visualization and update workbench". The UX should focus on AOI selection, OPERA product discovery, workflow runs, and result viewing.

- [ ] Add AOI drawing and upload controls.
  - Explanation: Users need to draw a rectangle/polygon or upload a boundary before frame discovery. React Leaflet can handle the interactive map side.

- [ ] Add frame discovery results.
  - Explanation: After AOI selection, show frame id, flight direction, coverage, product availability, and date bounds.

- [ ] Add run configuration panel.
  - Explanation: Users need controls for start/end date, workers or compute profile, reference mode, output products, and optional publish target.

- [ ] Add preflight review step.
  - Explanation: Before submission, show estimated granule count, approximate size, warnings, and expected outputs.

- [ ] Add workflow run timeline/status panel.
  - Explanation: Long-running analysis needs visible progress by stage: discovery, download/subset, stack/reference, export, publish.

- [ ] Add result layer viewer.
  - Explanation: Display cumulative displacement and velocity overlays, legends, units, AOI boundary, frame boundary, date range, and selected reference point.

- [ ] Add artifact download links.
  - Explanation: Users should be able to download GeoTIFFs, previews, manifest, provenance, and logs directly from the results panel.

## Credentials And Security

- [ ] Decide how Earthdata credentials are stored and supplied to runs.
  - Explanation: Do not send Earthdata passwords in browser-visible workflow args. Prefer Tapis secrets/identities or a backend-managed credential flow.

- [ ] Keep Tapis tokens server-side where possible.
  - Explanation: The current frontend stores a token for workflow calls. For production, prefer backend session handling or short-lived token exchange to reduce exposure.

- [ ] Separate public discovery from authenticated execution.
  - Explanation: AOI frame discovery and product search may be available without Tapis login, but downloads, archives, and publication require authenticated execution.

## Publication And Data Management

- [ ] Decide whether completed outputs publish to CKAN automatically or remain in Tapis archive by default.
  - Explanation: Automatic CKAN publication is useful but adds metadata, ownership, and cleanup concerns. The first implementation can keep outputs in Tapis and add explicit publish later.

- [ ] Define CKAN metadata for derived SUBSIDE products.
  - Explanation: If publishing, datasets/resources need title, name, standard variables, spatial extent, temporal extent, provenance, license, and maintainer.

- [ ] Add run cleanup and retention policy.
  - Explanation: DISP-S1 subsets and derived rasters can be large. We need a policy for temporary files, archived outputs, failed runs, and re-runs.

## Testing And Validation

- [x] Add a tiny AOI/date-range fixture for local testing.
  - Explanation: We need a small, repeatable test case that does not require hours of download and processing.
  - Resolved 2026-05-28: `sample_aoi.geojson` (Houston-Galveston 0.2°×0.2° box) + `workflow_apps/{h2i_lab,werc}/walkthrough.py` cell-style drivers that exercise the full pipeline against a 3-month window.

- [ ] Add unit tests for config validation and manifest generation.
  - Explanation: These are stable boundaries and should catch mistakes before Tapis runs are submitted.

- [ ] Add integration tests for API facade endpoints with mocked Tapis responses.
  - Explanation: The frontend should not break if Tapis payloads vary. Mocked tests should verify normalized status and result manifest handling.

- [ ] Run one end-to-end Tapis smoke test.
  - Explanation: Before UI polish, verify that a real run can register, submit, complete, archive outputs, and return a manifest.

## Suggested Session Breakdown

- [x] Session 1: Notebook inventory and extraction map.
  - Explanation: Produce the cell-to-module mapping and decide package layout.
  - Done 2026-05-28: h2i_lab + werc function maps in their READMEs; package layout `subside_analysis/<pkg>/{config,stack,reference,velocity,export,runner,cli}.py`.

- [x] Session 2: Analysis config schema, CLI skeleton, and manifest format.
  - Explanation: Establish the contract between UI, backend, and Tapis.
  - Done 2026-05-28: `H2IRunConfig` + `WercRunConfig`, both `cli.py`s with `preflight` / `run` subcommands, basic manifest format (see "Add manifest generation" above for follow-on polish).

- [ ] Session 3: Local analysis path for one small AOI.
  - Explanation: Prove the extracted code can produce the expected artifacts without Tapis.
  - In progress 2026-05-28: walkthrough scripts + Houston AOI fixture in place; H2I preflight + frame/product discovery verified end-to-end; Earthdata download being validated after the `EarthdataSession` fix.

- [x] Session 4: Tapis app/container and workflow definition.
  - Explanation: Make the remote execution path real.
  - Done 2026-05-28 for the *app/container* half — both `app-cpu.json`s, Dockerfiles, cookbook-style `run.sh`s, env files, and GHA CI/CD. Tapis *Workflows* pipeline tying the apps together (see "Tapis Workflow Design" above) remains open.

- [ ] Session 5: SUBSIDE API facade endpoints.
  - Explanation: Connect UI-friendly endpoints to discovery and Tapis operations.

- [ ] Session 6: UI workflow configuration and run status.
  - Explanation: Let users configure and submit real runs from SUBSIDE.

- [ ] Session 7: Result viewer and artifact downloads.
  - Explanation: Complete the loop from selected AOI to map-ready outputs.

- [ ] Session 8: CKAN publication, provenance polish, and validation.
  - Explanation: Add durable publication and tighten scientific metadata.
