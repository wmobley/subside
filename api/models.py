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


# --- runs ------------------------------------------------------------------
class RunRequest(BaseModel):
    pipeline: Literal["h2i", "werc"] = "h2i"
    start_date: str
    end_date: str
    aoi_geojson: dict[str, Any]
    allocation: str
    num_workers: int = 2
    min_overlap_percent: float = 50.0
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


class RunSubmitResponse(BaseModel):
    runId: str
    pipeline: str
    status: str
    tapisStatus: str
    name: str


class RunStatusResponse(BaseModel):
    runId: str
    status: str          # normalized: queued|running|completed|failed|cancelled|unknown
    tapisStatus: str
    lastMessage: Optional[str] = None
    archive: Optional[str] = None


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


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
