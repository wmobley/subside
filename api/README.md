# SUBSIDE API

FastAPI gateway in front of Tapis. Turns portal concepts (AOI, frames, products,
runs, results) into stable UI responses, and submits the OPERA analysis as Tapis
**Workflows pipeline runs as the calling user**. The workflow's `run` task still
submits the heavy analysis job internally, but the API tracks the pipeline run.

## Run (dev)

```bash
cd subside
pip install -r api/requirements.txt          # core deps
uvicorn api.main:app --reload --port 8000
```

The Vite frontend (`:5173`) is allow-listed for CORS. Point the dev proxy or
`fetch` at `http://localhost:8000`.

## Auth and run-token lifecycle

1. `POST /api/subside/login` with `{username, password}` → `{token, username}`.
2. Send that token on every other call as the `X-Tapis-Token` header.

The API builds a per-request tapipy client from the token and uses it only for
the request and input staging. When `SUBSIDE_RUN_TOKEN_ENABLED=true`, a run
submission mints a separate, bounded user token through the Portals Tokens API.
Only that per-run token is passed to the workflow's `tapis_token` argument and
used as the default CKAN/STAC credential. Explicit CKAN/STAC credentials still
take precedence.

The per-run token is encrypted in the SQLite lease store before workflow
submission. Configure `SUBSIDE_RUN_TOKEN_ENCRYPTION_KEY` with a Fernet key and
`SUBSIDE_RUN_TOKEN_STORE_PATH` on protected persistent storage. Runs fail closed
if the feature is enabled without a valid key; the browser token is never used
as a fallback. API-created compute jobs use a lease-derived durable name, so a
failed workflow task can be reconciled through the Jobs API. The API reports
`recovering` while the compute job or automatic `subside-publish` recovery is
active, and only revokes the token after publication is terminal. Startup
reconciliation uses the stored per-run token to resume active leases and also
retries cleanup-pending leases. Phase 1 assumes one API instance sharing one
persistent store; it is not a multi-replica coordination mechanism.

OAuth login stores the user's refresh token encrypted in the protected backend
store. The retained password-grant `/login` endpoint also stores the refresh
token when Tapis returns one, which supports scripts and sandbox validation.
Hosted tasks receive only an opaque lease credential for the API refresh
broker; the OAuth refresh token is never passed into workflow arguments or task
environments. Set `SUBSIDE_TOKEN_BROKER_URL` to the API base URL reachable by
hosted workflows. The broker rotates the bounded per-run token after expiry.

## Endpoints

| Method + path | Auth | Notes |
|---|---|---|
| `GET  /api/subside/healthz` | no | liveness |
| `POST /api/subside/login` | no | username/password → Tapis token |
| `POST /api/subside/aoi/frames` | no | frames intersecting an AOI (in-process, fast) |
| `POST /api/subside/products/search` | no | OPERA products for frames + dates (in-process) |
| `POST /api/subside/runs` | yes | stage inputs + submit a Tapis Workflows pipeline run; returns `runId` |
| `GET  /api/subside/runs/{runId}` | yes | normalized status: queued/running/recovering/completed/failed/cancelled; includes recovery fields |
| `GET  /api/subside/runs/{runId}/results` | yes | manifest + artifact download URLs once completed |
| `GET  /api/subside/layers` | no | list ingested PostGIS layers (count + bbox) |
| `POST /api/subside/layers/{layer}` | no | create/replace (or append) a layer from GeoJSON |
| `DELETE /api/subside/layers/{layer}` | no | drop a layer + its registry row |
| `GET  /api/subside/layers/{layer}.geojson` | no | read a layer back as GeoJSON (`?bbox=&limit=`) |
| `GET  /api/subside/tiles/{layer}/{z}/{x}/{y}.mvt` | no | Mapbox Vector Tile (protobuf); 204 when empty |

`runId` is the Tapis Workflows pipeline-run uuid. Submission is **non-blocking** — poll the status
endpoint; fetch results when `status == "completed"`.

## PostGIS vector layers (GeoJSON → MVT)

`POST /layers/{layer}` ingests **any** GeoJSON FeatureCollection into a PostGIS
table; scalar `properties` are promoted to typed columns (so they ride along as
tile attributes) and the full properties are kept in a `props` jsonb column for
lossless GeoJSON read-back. `GET /tiles/{layer}/{z}/{x}/{y}.mvt` serves it as
Mapbox Vector Tiles (`ST_AsMVT`), ready for any MVT client (MapLibre GL, or
Leaflet via the `Leaflet.VectorGrid` plugin). The four initial layers —
reservoirs major/minor, GAM grid, counties, municipalities — are just the first
things loaded through this generic path; there is no per-layer special casing.

```bash
# load (layer name must match [a-z][a-z0-9_]{0,62})
curl -X POST localhost:8000/api/subside/layers/counties \
  -H 'Content-Type: application/json' \
  -d '{"geojson": <FeatureCollection>, "mode": "replace"}'

# a vector tile
curl -o tile.mvt localhost:8000/api/subside/tiles/counties/6/15/26.mvt
```

**Connection:** these endpoints need `SUBSIDE_DATABASE_URL` — the postgres
*wire* endpoint behind the database, **not** the PostgREST HTTP URL
(`subsidepostgrest.pods.portals.tapis.io`). psycopg speaks the postgres
protocol, not HTTP; on Tapis that is the postgres pod over the pods 443
TLS-SNI tunnel. If the URL is unset or `psycopg` is not installed, the layer
endpoints return **503** and the rest of the API is unaffected. Geometry is
stored in EPSG:4326 and reprojected to web-mercator per tile.

## Discovery deps (heavy)

`/aoi/frames` needs `geopandas` (frame search uses `require_products=False`, so
no `disp_xr`). `/products/search` additionally needs `disp_xr`. If a dep is
missing the endpoint returns **503** with a clear message rather than crashing.
To serve discovery in-process, run the API inside a conda env built from
[`workflow_apps/h2i_lab/environment.yaml`](../workflow_apps/h2i_lab/environment.yaml),
or `pip install` the geospatial extras listed in `requirements.txt`.

## Module map

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, routes, CORS, token dependency, startup lease reconciliation |
| `tapis.py` | Tapis clients, password-grant login, username-from-JWT, token mint/revoke |
| `manager.py` | input staging, run-token lifecycle, workflow submit/status/results, archive lookup |
| `token_store.py` | encrypted SQLite lease records and cleanup state transitions |
| `discovery.py` | in-process frames/products via `analysis` (lazy imports) |
| `db.py` | lazy psycopg pool + PostGIS/schema/registry bootstrap (`DbUnavailable` → 503) |
| `layers.py` | generic GeoJSON ingest, layer list/drop, GeoJSON read-back, MVT tiles |
| `models.py` | pydantic request/response models |
| `config.py` | base URL, staging system/path, run-token lifecycle, CORS, DB/MVT settings |

### Run-token environment variables

| Variable | Purpose |
|---|---|
| `SUBSIDE_RUN_TOKEN_ENABLED` | Explicitly enables per-run token minting; default `false`. |
| `SUBSIDE_RUN_TOKEN_ENCRYPTION_KEY` | Fernet key used to encrypt stored run JWTs; required when enabled. |
| `SUBSIDE_RUN_TOKEN_STORE_PATH` | Protected persistent SQLite path. |
| `SUBSIDE_RUN_TOKEN_VOLUME_ID` | Deployment-side Tapis Pod volume used for the lease store. |
| `SUBSIDE_RUN_TOKEN_TTL_BUFFER_SECONDS` | Cleanup/polling buffer added to the queue budget plus requested walltime; default 900. |
| `SUBSIDE_RUN_TOKEN_QUEUE_BUDGET_SECONDS` | Maximum scheduler queue allowance included in the initial token TTL and hard deadline; default 86400 (24 hours). |
| `SUBSIDE_RUN_TOKEN_TTL_MIN_SECONDS` / `MAX_SECONDS` | Server-side TTL bounds; defaults 900 / 172800. |
| `SUBSIDE_RUN_TOKEN_TARGET_PREFIX` | Prefix for the server-generated token target id. |
| `SUBSIDE_TOKEN_BROKER_URL` | Public API base URL used by hosted tasks for server-side run-token rotation. |
| `SUBSIDE_RUN_TOKEN_RECONCILE_ON_STARTUP` | Retry cleanup-pending leases at API startup. |
| `SUBSIDE_RUN_RECOVERY_ENABLED` | Enable durable inner-job reconciliation; default `true`. |
| `SUBSIDE_RUN_RECOVERY_PUBLISH` | Automatically invoke `subside-publish` after confirmed compute/archive success; default `true`. |
| `SUBSIDE_RUN_RECOVERY_GRACE_SECONDS` | Jobs API outage grace after requested walltime; default 1200. |
| `SUBSIDE_RUN_RECOVERY_CLEANUP_STALE_SECONDS` | Time before a crashed revoke claim can be reclaimed; default 300. |

The configured maximum token TTL must be at least the queue budget plus the
largest allowed job walltime plus the TTL buffer. Requests that do not fit
that bound are rejected before staging or token minting.
