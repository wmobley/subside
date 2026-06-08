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

## Auth (token pass-through)

1. `POST /api/subside/login` with `{username, password}` → `{token, username}`.
2. Send that token on every other call as the `X-Tapis-Token` header.

The API builds a per-request tapipy client from the token and acts as that user.
No passwords are stored server-side. (Production hardening — server-side session
/ short-lived token exchange — is a later TODO item.)

## Endpoints

| Method + path | Auth | Notes |
|---|---|---|
| `GET  /api/subside/healthz` | no | liveness |
| `POST /api/subside/login` | no | username/password → Tapis token |
| `POST /api/subside/aoi/frames` | no | frames intersecting an AOI (in-process, fast) |
| `POST /api/subside/products/search` | no | OPERA products for frames + dates (in-process) |
| `POST /api/subside/runs` | yes | stage inputs + submit a Tapis Workflows pipeline run; returns `runId` |
| `GET  /api/subside/runs/{runId}` | yes | normalized status: queued/running/completed/failed/cancelled |
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
| `main.py` | FastAPI app, routes, CORS, the `X-Tapis-Token` dependency |
| `tapis.py` | build a client from a token; password-grant login; username-from-JWT |
| `manager.py` | input staging, workflow submit/status/results, and archive lookup |
| `discovery.py` | in-process frames/products via `analysis` (lazy imports) |
| `db.py` | lazy psycopg pool + PostGIS/schema/registry bootstrap (`DbUnavailable` → 503) |
| `layers.py` | generic GeoJSON ingest, layer list/drop, GeoJSON read-back, MVT tiles |
| `models.py` | pydantic request/response models |
| `config.py` | base URL, staging system/path, CORS origins, DB/MVT settings (env-overridable) |
