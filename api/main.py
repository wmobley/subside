"""SUBSIDE API — FastAPI gateway in front of Tapis.

Run (dev)::

    cd subside
    pip install -r api/requirements.txt
    uvicorn api.main:app --reload --port 8000

Auth: the frontend logs in (POST /api/subside/login) to get a Tapis token,
then sends it on every other call as the ``X-Tapis-Token`` header. The API
acts as that user for Tapis Workflows pipeline submission and archive reads.
"""

from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from . import availability, db, discovery, forecast, layers, manager, tapis
from .config import CORS_ORIGINS
from .models import (
    AuthCodeRequest, AuthConfigResponse, AuthTokenResponse,
    AvailabilityItem, AvailabilityResponse, ForecastRequest, ForecastResponse,
    FramesRequest, FramesResponse,
    LayerLoadRequest, LayerLoadResponse, LayerInfo, LayersResponse,
    LoginRequest, LoginResponse, ProductsSearchRequest, ProductsSearchResponse,
    RunListItem, RunListResponse, RunRequest, RunResultsResponse,
    RunStatusResponse, RunSubmitResponse,
)

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"

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
    """Password-grant login. Retained for scripts/dev; the web app uses the
    OAuth2 redirect flow (/auth/config + /auth/token) instead."""
    try:
        token = tapis.login(body.username, body.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Login failed: {exc}") from exc
    return LoginResponse(token=token, username=body.username)


# --- OAuth2 authorization-code login (Log in with TACC) --------------------
@app.get("/api/subside/auth/config", response_model=AuthConfigResponse)
def auth_config():
    """Non-secret bits the browser needs to start the redirect login."""
    cfg = tapis.oauth_public_config()
    if not cfg:
        raise HTTPException(
            status_code=503,
            detail="OAuth login is not configured (set TAPIS_CLIENT_ID/KEY).",
        )
    return AuthConfigResponse(**cfg)


@app.post("/api/subside/auth/token", response_model=AuthTokenResponse)
def auth_token(body: AuthCodeRequest):
    """Exchange the OAuth2 authorization code for a Tapis token (client_key
    stays server-side). CSRF `state` is validated client-side before this call."""
    try:
        res = tapis.exchange_code(body.code)
    except tapis.OAuthNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token exchange failed: {exc}") from exc
    return AuthTokenResponse(token=res["token"], username=res["username"], expires_at=res.get("expires_at"))


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


# --- forecast (potential subsidence screening, fast in-process; no Tapis job)
@app.post("/api/subside/forecast", response_model=ForecastResponse)
def forecast_run(body: ForecastRequest):
    """Run the potential-subsidence screening model and return a 0-10 risk score
    plus an annual projection. Pure computation — no Tapis job, no auth."""
    try:
        result = forecast.compute(body.scenario)
    except forecast.ForecastUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Forecast failed: {exc}") from exc
    return ForecastResponse(**result)


@app.get("/api/subside/forecast/template")
def forecast_template():
    """A starter scenario (visible Excel-style labels) the UI can prefill/edit."""
    try:
        return {"scenario": forecast.template()}
    except forecast.ForecastUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --- availability (viewport-lazy DISP-S1 cache, no Tapis job) --------------
@app.get("/api/subside/availability", response_model=AvailabilityResponse)
def frame_availability(
    background: BackgroundTasks,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat (EPSG:4326)."),
    layer: str = Query("satellite", description="Loaded frame-footprint layer name."),
    frame_id_column: str = Query("frame_id", description="Frame-id column in that layer."),
    ttl_hours: int = Query(24, ge=1, description="Cache freshness; frames older than this refresh in the background."),
    start_date: str = Query(None, description="Optional window start YYYY-MM-DD; adds in-window counts from the cached timeline."),
    end_date: str = Query(None, description="Optional window end YYYY-MM-DD."),
    refresh: bool = Query(True, description="Schedule a background refresh of stale/missing in-view frames."),
    max_refresh: int = Query(50, ge=0, le=500, description="Cap on frames refreshed per request, to bound the background task."),
):
    """Availability for every frame intersecting the viewport, served from the
    cache. Stale/missing frames refresh in the background so the next poll is
    populated — ASF is never queried on this request's critical path."""
    try:
        box = [float(v) for v in bbox.split(",")]
        if len(box) != 4:
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox must be 'minLon,minLat,maxLon,maxLat'.")
    try:
        items, stale = availability.availability_for_bbox(
            box, layer=layer, frame_id_column=frame_id_column, ttl_hours=ttl_hours,
            start_date=start_date, end_date=end_date,
        )
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    to_refresh = stale[:max_refresh] if refresh else []
    if to_refresh:
        background.add_task(availability.refresh_frames, to_refresh)
    return AvailabilityResponse(
        layer=layer, bbox=box, ttl_hours=ttl_hours, frame_count=len(items),
        refreshing=to_refresh, items=[AvailabilityItem(**it) for it in items],
    )


# --- runs (Tapis Workflows pipelines, as the user) --------------------------
@app.post("/api/subside/runs", response_model=RunSubmitResponse)
def submit_run(body: RunRequest, client=Depends(require_client)):
    try:
        info = manager.submit_run(client, body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Run submission failed: {exc}") from exc
    if not info.get("uuid"):
        raise HTTPException(status_code=502, detail="Tapis did not return a workflow run uuid.")
    return RunSubmitResponse(
        runId=info["uuid"], pipeline=body.pipeline, name=info["name"],
        pipelineId=info.get("pipelineId"), groupId=info.get("groupId"),
        tapisStatus=info["tapisStatus"], status=manager.normalize_status(info["tapisStatus"]),
    )


@app.get("/api/subside/runs", response_model=RunListResponse)
def list_runs(client=Depends(require_client),
              all: bool = Query(False, description="Diagnostics placeholder; the API lists configured SUBSIDE pipelines.")):
    """The caller's Tapis Workflows history for configured SUBSIDE pipelines."""
    try:
        runs = manager.list_runs(client, include_all=all)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list runs: {exc}") from exc
    return RunListResponse(runs=[RunListItem(**r) for r in runs])


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


@app.get("/api/subside/runs/{run_id}/file")
def run_file(run_id: str, path: str = Query(..., description="Archive-relative file path from results artifacts."),
             client=Depends(require_client)):
    """Proxy one pipeline-run archive file (image/COG/zip/manifest)."""
    try:
        data, name, ctype = manager.fetch_file(client, run_id, path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"File fetch failed: {exc}") from exc
    return Response(content=data, media_type=ctype,
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# --- vector layers (PostGIS GeoJSON ingest + MVT tiles) --------------------
@app.get("/api/subside/layers", response_model=LayersResponse)
def list_layers():
    try:
        rows = layers.list_layers()
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LayersResponse(layers=[LayerInfo(**r) for r in rows])


@app.post("/api/subside/layers/{layer}", response_model=LayerLoadResponse)
def load_layer(layer: str, body: LayerLoadRequest):
    try:
        info = layers.create_or_load(layer, body.geojson, body.mode)
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LayerLoadResponse(**info)


@app.delete("/api/subside/layers/{layer}")
def delete_layer(layer: str):
    try:
        existed = layers.drop_layer(layer)
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not existed:
        raise HTTPException(status_code=404, detail=f"Layer {layer!r} not found.")
    return {"deleted": layer}


@app.get("/api/subside/layers/{layer}.geojson")
def layer_geojson(layer: str, bbox: str = Query(None, description="minLon,minLat,maxLon,maxLat"),
                  limit: int = Query(5000, ge=1, le=100000)):
    box = None
    if bbox:
        try:
            box = [float(v) for v in bbox.split(",")]
            if len(box) != 4:
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be 'minLon,minLat,maxLon,maxLat'.")
    try:
        return layers.read_geojson(layer, box, limit)
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/subside/tiles/{layer}/{z}/{x}/{y}.mvt")
def layer_tile(layer: str, z: int, x: int, y: int):
    try:
        tile = layers.mvt_tile(layer, z, x, y)
    except db.DbUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # 204 for an empty tile lets clients skip caching a 0-byte body.
    if not tile:
        return Response(status_code=204, media_type=MVT_MEDIA_TYPE)
    return Response(content=tile, media_type=MVT_MEDIA_TYPE)
