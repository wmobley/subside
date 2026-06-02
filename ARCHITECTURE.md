# SUBSIDE — Architecture

How the pieces fit together, what each subsystem does, and where the seams and
known constraints are. For a quick orientation and run instructions see
[README.md](README.md).

## 1. The product, in one sentence

SUBSIDE answers, for a place a user picks on a map: **"how much is the ground
sinking — observed, and projected — and what's around it?"** That maps onto three
engines that the rest of this document keeps coming back to:

| Engine | Question | Mechanism | Latency |
|---|---|---|---|
| **Observed** | How much / how fast has it moved? | OPERA DISP-S1 InSAR, run as **Tapis batch jobs** (`h2i`, `werc`) | minutes (queue + compute) |
| **Forecast** | What subsidence is projected? (0–10 risk) | Aquifer screening model run **in-process in the API** | sub-second |
| **Context** | What's around this location? | Spatial layers in **PostGIS**, served as vector tiles | per-tile |

The observed and forecast engines are deliberately different shapes: OPERA work
is heavy (downloads GBs, large jobs) so it goes through Tapis; the forecast is a
pure pandas calculation so it runs synchronously in the API.

## 2. System layout & data flow

```
  Browser (React/Vite SPA, :5174 dev)
    │
    │  /api/subside/*  → SUBSIDE API        /ckan/* → TACC CKAN catalog
    │  /api/*          → legacy backend (:5050, vestigial)
    ▼
  SUBSIDE API  (FastAPI, api/, :8000)
    ├── login                     → Tapis password grant → token (X-Tapis-Token on every other call)
    ├── runs (submit/status/...)  → Tapis Jobs API, AS THE USER ──► OPERA batch apps on TACC (ls6)
    │                                                                 │ archive
    │                                                                 ▼
    │                                            results/manifest read back from the job archive
    ├── forecast                  → in-process analysis.subsidence (numpy/pandas)
    ├── availability / aoi/frames → in-process discovery (geopandas + ASF), cached in PostGIS
    └── layers / tiles            → PostGIS (+ PostGIS MVT)
```

Auth model: users sign in via the **Tapis OAuth2 authorization-code (3-legged)
flow** — "Log in with TACC". The browser redirects to the tenant's hosted
`/v3/oauth2/authorize` page; Tapis returns to the app's callback with a one-time
`code`; the API exchanges that code for a token using the OAuth client secret
(which never leaves the server). The frontend then sends the resulting **Tapis
token** as the `X-Tapis-Token` header on every other call, and the API acts *as
that user* for job submission — so jobs run under the user's identity and
allocation (and sidestep the restricted Tapis Workflows service; see §9). A
password-grant `/login` endpoint is retained for scripts/dev. Registering the
OAuth client is a one-time step (`tapis/workflows/register_oauth_client.py`).

## 3. Frontend — `ui/src/`

React 19 + Vite 7 single-page app. Map rendering is Leaflet via react-leaflet,
with `leaflet.vectorgrid` for MVT vector layers and `georaster-layer-for-leaflet`
for client-side COG GeoTIFF rendering.

- **`App.jsx`** — top-level state container and page router (`home` / `maps` /
  `datasets` / `about`). Also still holds a vestigial MODFLOW login/apply/workflow
  apparatus (see §9).
- **`main.jsx`**, **`index.html`** — entry point.
- **`config.js`** — portal audience modes, hero/stats config, and feature cards.
- **`content.js`** — loads the Markdown site content from [`ui/content/`](ui/content/)
  at build time (Vite `import.meta.glob` + a tiny frontmatter parser); exports
  `getAbout()`, `getPartners()`, `getGoals()`, and the `CONTRACT_FLAG` placeholder.
- **`subsideApi.js`** — client for the SUBSIDE API: `login`, `submitRun`,
  `getRunStatus`, `getRunResults`, `fetchArtifactBlob`, `listLayers`,
  `tileUrlTemplate`, `fetchAvailability`, and the forecast calls `runForecast` /
  `getForecastTemplate`.
- **`api.js`** — shared `requestJson` fetch helper. **`ckan.js`** — TACC CKAN client.
- **`components/`**
  - `PortalChrome.jsx` — header/nav, hero, search, stats, footer.
  - `pages/PortalPageContent.jsx` — page bodies; the **About** page renders from `content.js`.
  - `CkanDatasets.jsx` + `datasets/` — the Data tab (CKAN browse + spatial filter).
  - `MapWorkbench.jsx` → `mapworkbench/`:
    - `ModelMap.jsx` — the Leaflet `MapContainer`; lifts a clicked frame to the analysis panel.
    - `SubsideLayers.jsx` — renders every registered PostGIS layer as MVT + viewport-lazy OPERA frame-availability shading; the layer toggle/legend control.
    - `SubsideAnalysis.jsx` — the **Risk Explorer** panel: pick a frame → choose outcome (displacement / velocity) → submit a Tapis run → poll → show result layers; plus the **Observed** and **Potential** (forecast) risk cards.
    - `RiskGauge.jsx` — the 0–10 forecast risk gauge.
    - `CogLayer.jsx` / `VectorTileLayer.jsx` — COG raster + MVT layer wrappers.
- **`styles.css`** — the SUBSIDE/TACC visual system (CSS variables, all `.sap-*`, `.risk-*`, `.about-*` classes).

## 4. API — `api/`

FastAPI gateway (`uvicorn api.main:app`). Every endpoint is under
`/api/subside/`. Designed to **degrade gracefully**: optional dependencies
(PostGIS driver, geo stack, pandas) are imported lazily and their endpoints
return 503 when absent, so the core API runs with the minimal requirements.

| Endpoint | Purpose | Backed by | Auth |
|---|---|---|---|
| `GET /auth/config` | OAuth client_id + authorize/callback URLs (non-secret) | `tapis.oauth_public_config` | — |
| `POST /auth/token` | Exchange OAuth2 code → token (client secret server-side) | `tapis.exchange_code` | — |
| `POST /login` | Tapis password grant → token (scripts/dev fallback) | `tapis.py` | — |
| `POST /runs` | Submit an OPERA pipeline as a Tapis job | `manager.submit_run` | token |
| `GET /runs` | The caller's run history | `manager.list_runs` | token |
| `GET /runs/{id}` | Job status (normalized) | `manager.get_status` | token |
| `GET /runs/{id}/results` | Manifest + artifacts from the archive | `manager.get_results` | token |
| `GET /runs/{id}/file` | Proxy one archive file (COG/PNG/zip) | `manager.fetch_file` | token |
| `POST /forecast` | **Forecast engine** — 0–10 risk + annual projection | `forecast.compute` → `analysis.subsidence` | — |
| `GET /forecast/template` | Starter scenario for the forecast | `forecast.template` | — |
| `POST /aoi/frames` | Frames intersecting an AOI | `discovery.find_frames` | — |
| `POST /products/search` | DISP-S1 products for frames+dates | `discovery.search_products` | — |
| `GET /availability` | Viewport-lazy frame availability | `availability.availability_for_bbox` | — |
| `GET/POST/DELETE /layers...` | PostGIS GeoJSON ingest + registry | `layers.py` | — |
| `GET /tiles/{layer}/{z}/{x}/{y}.mvt` | Mapbox vector tiles | `layers.mvt_tile` | — |

Modules:
- **`main.py`** — the FastAPI app + routes + the `require_client` token dependency.
- **`models.py`** — Pydantic request/response models (`RunRequest`, `ForecastRequest`/`ForecastResponse`, `LayerInfo`, …).
- **`config.py`** — env-driven config: `TAPIS_BASE_URL`, `EARTHDATA_*`, `DEFAULT_ALLOCATION`, staging system/prefix, `DATABASE_URL`, MVT params, CORS, and the `PIPELINES` map (`h2i`→`h2i-opera`, `werc`→`werc-opera`). Loads `.env` via python-dotenv.
- **`tapis.py`** — `login`, `client_from_token`, username-from-JWT.
- **`manager.py`** — the Tapis Jobs lifecycle: stage inputs, build the run-config, submit as the user, normalize status (Tapis's many states → queued/running/completed/failed/cancelled), discover results, and proxy archive files. Manifest preference order: `werc-run-manifest.json` → `run-manifest.json` → `subside-run-manifest.json`.
- **`discovery.py`** — fast in-process frame/product discovery via `analysis.h2i_lab.aoi` (no Tapis job); raises `DiscoveryUnavailable` if the geo stack is missing.
- **`availability.py`** — caches per-frame DISP-S1 availability in PostGIS; serves the viewport from cache and refreshes stale frames from ASF in the background (`refresh_frames`, `refresh_all` cron entrypoint).
- **`layers.py`** — ingests GeoJSON into PostGIS (typed columns + a `props` jsonb fallback, identifier sanitizing) and serves MVT tiles via `ST_AsMVT`.
- **`db.py`** — psycopg3 connection pool over `SUBSIDE_DATABASE_URL`; idempotent bootstrap of the PostGIS extension, API schema, and `frame_availability` table; raises `DbUnavailable` when unset/unreachable.
- **`forecast.py`** — bridge to the in-process screening model; ensures the repo root is importable, lazily imports `analysis.subsidence`, and raises `ForecastUnavailable` (→503) if numpy/pandas are absent.

## 5. Analysis package — `analysis/`

Reusable Python shared by the Tapis apps, the API, and local walkthroughs.

- **`etl/`** — shared helpers: `auth.py` (Earthdata session/credentials), `manifest.py` (`write_json`), `aoi.py` (AOI/bbox loaders), `stack.py`, `archive.py`.
- **`h2i_lab/`** — the **observed acquisition** stage: discover overlapping OPERA frames, download + AOI-crop DISP-S1 NetCDFs, render a displacement preview. `runner.run()/preflight()` take an `H2IRunConfig`; `cli.py` is the `python -m analysis.h2i_lab.cli run --config … --output-dir …` entrypoint.
- **`werc/`** — the **observed velocity** stage: builds on `h2i_lab` (reuses its download), then assembles a displacement time-series stack, selects a reference (auto/manual/none), inverts per-pixel velocity, and exports cumulative + velocity GeoTIFFs. `cli.py` exposes both the full pipeline and per-stage entrypoints.
- **`subsidence/`** — the **forecast engine**: `model.py` (vendored Texas Aquifer Potential Subsidence screening tool) + `forecast.py` (`run_forecast`, `default_scenario`). Pure numpy/pandas; see [analysis/subsidence/README.md](analysis/subsidence/README.md).

The relationship between `h2i_lab` and `werc` is composition, not duplication —
WERC calls `h2i_lab.runner.run` as its first stage. (This mirrors the two source
notebooks; the productionized code reuses the shared front-half.)

## 6. Tapis batch apps — `tapis/workflow_apps/`

Container definitions for the OPERA apps that run on TACC. Two configurations of
one capability:

- **`h2i_lab/`** → app `subside-h2i-opera-analysis` — acquire + preview.
- **`werc/`** → app `subside-werc-opera-analysis` — + reference/velocity/export.

Each contains `Dockerfile` (micromamba base, bakes the conda env from
`environment.yaml`), `run.sh` (entrypoint: a `STAGE` env var selects
`preflight`/`run`; it materializes a `run-config.json` from env variables, stages
`.netrc` if present, then invokes the matching `analysis.*.cli`),
`app-cpu.json` (the Tapis app definition: container image, file inputs
`aoi-geojson`/`earthdata-netrc`, env-variable parameter set, scheduler options),
and `walkthrough.py` (a local, cell-style end-to-end test against real Earthdata
— the same code path the batch app runs). **`opera-disp-s1.model-catalog.yaml`**
registers both apps in the MINT model catalog as one model / two configurations.

## 7. Registration & orchestration — `tapis/workflows/`

- **`pipelines/h2i-opera.yaml`, `werc-opera.yaml`** — Tapis Workflows pipeline
  definitions. Each is a single `tapis_job` task (`STAGE=run`, the whole pipeline
  in one job) plus a `publish` function task that emits the unified
  `subside-run-manifest.json` the UI reads. Params are templated as
  `{{ args.* }}` (dates, AOI URI, workers, allocation, and WERC's reference args).
- **`register.py`** — registers/updates the apps (from `tapis/workflow_apps/*/app-*.json`)
  and pipelines (from `tapis/workflows/pipelines/*.yaml`) with Tapis; supports image
  retagging (`--image-tag` or git HEAD sha), pruning, dry-run, and recreate.
- **`orchestrate.py`** — a **client-side** pipeline runner that submits each task's
  Tapis job directly as the user (Jobs + Files APIs), used because the Tapis
  Workflows `runPipeline` service is restricted (§9). This is the path the API's
  `manager.py` mirrors.
- **`smoke_test.py`** — live end-to-end test that triggers each pipeline (via the
  Workflows engine) against a Houston–Galveston AOI and polls to completion.

## 8. Content & examples

- **`ui/content/`** — editable Markdown for the site (About mission, partner cards,
  goal cards). Loaded by `ui/src/content.js`; documented for non-developers in
  [ui/content/README.md](ui/content/README.md). Edits require a rebuild/redeploy
  (e.g. edit via the GitHub web UI to trigger CI).
- **`examples/notebookExamples/`** — the original H2I and WERC analysis notebooks the
  pipelines were extracted from (design/source reference).
- **`examples/webpage_Examples/`** — the original static HTML wireframe.

## 9. Deployment, infra & known constraints

**CI / images.** `.github/workflows/build-images.yml` builds the `h2i_lab` and
`werc` Docker images (matrix) and pushes them to `ghcr.io/<owner>/...` on pushes
to `main` (path-filtered to `analysis/**` and the app dirs). Registering
those images as Tapis apps + pipelines is a manual `tapis/workflows/register.py` step.

**API runtime env.** Run the API from the `subside-h2i-opera` conda env — it's
the only env with the API deps *plus* the ASF/geo/pandas stack the discovery and
forecast endpoints need. A bare venv silently no-ops the availability refresh.

**PostGIS.** Layers/tiles/availability need `SUBSIDE_DATABASE_URL` pointing at the
Postgres *wire* endpoint (not PostgREST HTTP). On Tapis it's the postgres pod over
the pods 443 TLS-SNI tunnel; with a recent libpq the URL needs
`sslnegotiation=direct`. Unset → those endpoints return 503; the rest still works.

**Known constraints / vestiges:**
- **Tapis Workflows is restricted.** The hosted `runPipeline` service requires the
  `workflows` service grant in the portals tenant, which isn't in place — so the
  API and `orchestrate.py` submit jobs *as the user* via the Jobs API instead.
  Registering brand-new pipelines is likewise gated until that grant lands.
- **Forecast uses a representative scenario.** The Potential card runs the model's
  default aquifer template, not location-specific inputs. Making it truly
  per-location means deriving the ~17 required aquifer inputs from spatial layers.
- **MODFLOW vestiges in the frontend.** `App.jsx` still carries a MODFLOW
  login/`handleApply`/`WorkflowModal` apparatus and `modeling.js` from the portal
  template this was scaffolded from; it's no longer reachable from the nav and is
  slated for removal.
- **Contract number unconfirmed.** The header hardcodes `#2300012717` while project
  records cite `#2401792868`; the About page shows an obvious placeholder
  (`CONTRACT_FLAG` in `ui/src/content.js`) pending confirmation.

See [TAPIS_WORKFLOW_TODO.md](TAPIS_WORKFLOW_TODO.md) for the deeper Tapis design
notes and running status.
