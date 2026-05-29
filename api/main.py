"""SUBSIDE API — FastAPI gateway in front of Tapis.

Run (dev)::

    cd subside
    pip install -r api/requirements.txt
    uvicorn api.main:app --reload --port 8000

Auth: the frontend logs in (POST /api/subside/login) to get a Tapis token,
then sends it on every other call as the ``X-Tapis-Token`` header. The API
acts as that user — so job submission goes through as the user and dodges the
restricted Workflows service.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import discovery, manager, tapis
from .config import CORS_ORIGINS
from .models import (
    FramesRequest, FramesResponse, LoginRequest, LoginResponse,
    ProductsSearchRequest, ProductsSearchResponse, RunRequest,
    RunResultsResponse, RunStatusResponse, RunSubmitResponse,
)

app = FastAPI(title="SUBSIDE API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_client(x_tapis_token: str = Header(None, alias="X-Tapis-Token")):
    """FastAPI dependency: build a per-request tapipy client from the user token."""
    if not x_tapis_token:
        raise HTTPException(status_code=401, detail="Missing X-Tapis-Token header.")
    try:
        return tapis.client_from_token(x_tapis_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Tapis token: {exc}") from exc


@app.get("/api/subside/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/subside/login", response_model=LoginResponse)
def login(body: LoginRequest):
    try:
        token = tapis.login(body.username, body.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Login failed: {exc}") from exc
    return LoginResponse(token=token, username=body.username)


# --- discovery (fast, in-process; no Tapis job) ----------------------------
@app.post("/api/subside/aoi/frames", response_model=FramesResponse)
def aoi_frames(body: FramesRequest):
    try:
        result = discovery.find_frames(body.aoi_geojson, body.min_overlap_percent)
    except discovery.DiscoveryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Frame discovery failed: {exc}") from exc
    return FramesResponse(**result)


@app.post("/api/subside/products/search", response_model=ProductsSearchResponse)
def products_search(body: ProductsSearchRequest):
    try:
        result = discovery.search_products(body.frame_ids, body.start_date, body.end_date)
    except discovery.DiscoveryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Product search failed: {exc}") from exc
    return ProductsSearchResponse(**result)


# --- runs (Tapis jobs, as the user) ----------------------------------------
@app.post("/api/subside/runs", response_model=RunSubmitResponse)
def submit_run(body: RunRequest, client=Depends(require_client)):
    try:
        info = manager.submit_run(client, body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Run submission failed: {exc}") from exc
    if not info.get("uuid"):
        raise HTTPException(status_code=502, detail="Tapis did not return a job uuid.")
    return RunSubmitResponse(
        runId=info["uuid"], pipeline=body.pipeline, name=info["name"],
        tapisStatus=info["tapisStatus"], status=manager.normalize_status(info["tapisStatus"]),
    )


@app.get("/api/subside/runs/{run_id}", response_model=RunStatusResponse)
def run_status(run_id: str, client=Depends(require_client)):
    try:
        st = manager.get_status(client, run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {exc}") from exc
    return RunStatusResponse(runId=run_id, **st)


@app.get("/api/subside/runs/{run_id}/results", response_model=RunResultsResponse)
def run_results(run_id: str, client=Depends(require_client)):
    try:
        res = manager.get_results(client, run_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Results lookup failed: {exc}") from exc
    return RunResultsResponse(runId=run_id, **res)
