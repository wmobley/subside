# SUBSIDE API

FastAPI gateway in front of Tapis. Turns portal concepts (AOI, frames, products,
runs, results) into stable UI responses, and submits the OPERA analysis as Tapis
**Jobs run as the calling user** — the same identity that makes
[`workflows/orchestrate.py`](../workflows/orchestrate.py) work, so it inherits
the restricted-Workflows-service bypass.

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
| `POST /api/subside/runs` | yes | stage inputs + submit one monolithic `run` job; returns `runId` |
| `GET  /api/subside/runs/{runId}` | yes | normalized status: queued/running/completed/failed/cancelled |
| `GET  /api/subside/runs/{runId}/results` | yes | manifest + artifact download URLs once completed |

`runId` is the Tapis job uuid. Submission is **non-blocking** — poll the status
endpoint; fetch results when `status == "completed"`.

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
| `manager.py` | run-config build, input staging, job submit/status/results (request-driven cousin of `orchestrate.py`) |
| `discovery.py` | in-process frames/products via `subside_analysis` (lazy imports) |
| `models.py` | pydantic request/response models |
| `config.py` | base URL, staging system/path, CORS origins (env-overridable) |
