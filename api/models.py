"""Pydantic request/response models for the SUBSIDE API."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# --- discovery -------------------------------------------------------------
class FramesRequest(BaseModel):
    aoi_geojson: dict[str, Any] = Field(..., description="GeoJSON FeatureCollection/Feature/geometry for the AOI.")
    min_overlap_percent: float = 50.0


class FramesResponse(BaseModel):
    frame_ids: list[int]
    frames: list[dict[str, Any]]
    bbox: Optional[list[float]] = None


class ProductsSearchRequest(BaseModel):
    frame_ids: list[int]
    start_date: str
    end_date: str


class ProductsSearchResponse(BaseModel):
    product_count: int
    product_urls: list[str]


# --- availability (viewport-lazy DISP-S1 cache) ----------------------------
class AvailabilityItem(BaseModel):
    frame_id: int
    product_count: int = 0
    latest_date: Optional[str] = None       # most recent product (ISO date)
    timeline: list[str] = []                # all distinct product dates (ISO)
    checked_at: Optional[str] = None        # when this frame was last refreshed
    stale: bool = False                     # missing or older than ttl_hours
    cached: bool = False                    # False = no cache row yet (refreshing)
    bbox: Optional[list[float]] = None      # frame footprint [w, s, e, n] (AOI on click)
    count_in_window: Optional[int] = None   # set only when a date window is given
    available_in_window: Optional[bool] = None


class AvailabilityResponse(BaseModel):
    layer: str
    bbox: list[float]
    ttl_hours: int
    frame_count: int
    refreshing: list[int] = []              # frames scheduled for background refresh
    items: list[AvailabilityItem] = []


# --- forecast (potential subsidence — in-process, no Tapis job) ------------
class ForecastRequest(BaseModel):
    scenario: dict[str, Any] = Field(
        default_factory=dict,
        description="Aquifer/water-level inputs (visible Excel labels or snake_case, "
                    "or a {'inputs': {...}} object). Missing fields use model defaults.",
    )


class ForecastProjection(BaseModel):
    start_year: int
    final_year: Optional[int] = None
    final_subsidence_min_ft: Optional[float] = None
    final_subsidence_max_ft: Optional[float] = None
    final_drawdown_ft: Optional[float] = None


class ForecastResponse(BaseModel):
    scenario_id: str = ""
    aquifer: str = ""
    water_level_method: str = ""
    risk_score: Optional[float] = None              # 0-10 weighted screening risk
    risk_factors: dict[str, Any] = {}               # the six named sub-factors
    projection: ForecastProjection
    annual: list[dict[str, Any]] = []               # per-year subsidence series
    resolved_inputs: dict[str, Any] = {}            # inputs actually used (after defaults)


# --- runs ------------------------------------------------------------------
class RunRequest(BaseModel):
    pipeline: Literal["h2i", "werc"] = "h2i"
    start_date: str
    end_date: str
    aoi_geojson: dict[str, Any]
    allocation: Optional[str] = None   # falls back to SUBSIDE_DEFAULT_ALLOCATION (.env)
    num_workers: int = 8
    min_overlap_percent: float = 50.0
    # Optional job walltime (minutes). Omitted -> API estimates it from the
    # product count (capped at 24 h); provided -> clamped server-side.
    max_minutes: Optional[int] = None
    # werc-only
    reference_mode: Literal["auto", "manual", "none"] = "auto"
    reference_lat: Optional[float] = None
    reference_lon: Optional[float] = None
    anchor_radius_m: int = 5000
    n_reference_pixels: int = 25
    update_conda_env: str = "false"
    # Earthdata: prefer a pre-staged .netrc URI. Inline creds are accepted but
    # discouraged (they transit the request body) — see TODO security section.
    earthdata_netrc_uri: Optional[str] = None
    earthdata_username: Optional[str] = None
    earthdata_password: Optional[str] = None


class RunEstimateResponse(BaseModel):
    product_count: int
    pipeline: str
    num_workers: int
    estimated_minutes: float
    estimated_human: str             # e.g. "~3 min", "~1 h 20 min"
    walltime_minutes: int            # what the job will request as maxMinutes
    may_exceed_walltime: bool        # true only for implausibly large requests
    assumptions: dict[str, Any] = {}
    warning: Optional[str] = None


class RunSubmitResponse(BaseModel):
    runId: str
    pipeline: str
    pipelineId: Optional[str] = None
    groupId: Optional[str] = None
    status: str
    tapisStatus: str
    name: str


class RunTaskStatus(BaseModel):
    taskId: Optional[str] = None
    status: str
    tapisStatus: str
    lastMessage: Optional[str] = None


class RunStatusResponse(BaseModel):
    runId: str
    pipeline: Optional[str] = None
    pipelineId: Optional[str] = None
    status: str          # normalized: queued|running|completed|failed|cancelled|unknown
    tapisStatus: str
    lastMessage: Optional[str] = None
    archive: Optional[str] = None
    tasks: list[RunTaskStatus] = []


class RunListItem(BaseModel):
    runId: str
    name: Optional[str] = None
    pipeline: Optional[str] = None
    pipelineId: Optional[str] = None
    appId: Optional[str] = None
    status: str            # normalized
    tapisStatus: str
    created: Optional[str] = None


class RunListResponse(BaseModel):
    runs: list[RunListItem] = []


class Artifact(BaseModel):
    name: str
    path: str
    sizeBytes: Optional[int] = None
    url: str


class RunResultsResponse(BaseModel):
    runId: str
    status: str
    manifest: Optional[dict[str, Any]] = None
    artifacts: list[Artifact] = []


# --- vector layers (GeoJSON ingest + MVT tiles) ----------------------------
class LayerLoadRequest(BaseModel):
    geojson: dict[str, Any] = Field(..., description="GeoJSON FeatureCollection/Feature/geometry to load.")
    mode: Literal["replace", "append"] = "replace"


class LayerInfo(BaseModel):
    name: str
    geom_type: str
    srid: int
    columns: dict[str, Any] = {}
    feature_count: int = 0
    bbox: Optional[list[float]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LayersResponse(BaseModel):
    layers: list[LayerInfo] = []


class LayerLoadResponse(LayerInfo):
    loaded: int
    mode: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


# --- OAuth2 authorization-code login ---------------------------------------
class AuthConfigResponse(BaseModel):
    base_url: str
    client_id: str
    callback_url: str
    authorize_url: str


class AuthCodeRequest(BaseModel):
    code: str
    state: Optional[str] = None   # echoed by Tapis; CSRF check happens client-side


class AuthTokenResponse(BaseModel):
    token: str
    username: str
    expires_at: Optional[str] = None
