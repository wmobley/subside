"""Static configuration for the SUBSIDE API (env-overridable)."""

from __future__ import annotations

import os
from pathlib import Path

# subside/ — used to locate pipeline YAMLs and put the analysis package on the path.
SUBSIDE_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = SUBSIDE_ROOT / "tapis" / "workflows" / "pipelines"

# Load subside/.env (copy from .env.sample) so local config + the Earthdata
# service account live outside the request path and outside git. No-op if
# python-dotenv isn't installed or the file is absent.
try:
    from dotenv import load_dotenv
    load_dotenv(SUBSIDE_ROOT / ".env")
except ImportError:
    pass

TAPIS_BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io").rstrip("/")

# OAuth2 authorization-code (3-legged) login. Register a Tapis OAuth client whose
# callback_url EXACTLY matches TAPIS_OAUTH_CALLBACK_URL (see
# workflows/register_oauth_client.py). The client_id is public; the client_key is
# a server-side secret used only to exchange the auth code for a token. When
# unset, the /auth/* endpoints return 503 (the password-grant /login endpoint
# still exists for scripts/dev).
TAPIS_CLIENT_ID = os.environ.get("TAPIS_CLIENT_ID")
TAPIS_CLIENT_KEY = os.environ.get("TAPIS_CLIENT_KEY")
TAPIS_OAUTH_CALLBACK_URL = os.environ.get(
    "TAPIS_OAUTH_CALLBACK_URL", "http://127.0.0.1:5174/"
)

# NASA Earthdata service account used to build the .netrc for download jobs,
# so credentials never transit the API request body. Set in .env.
EARTHDATA_USERNAME = os.environ.get("EARTHDATA_USERNAME")
EARTHDATA_PASSWORD = os.environ.get("EARTHDATA_PASSWORD")

# Optional default TACC allocation, used when a run request omits one.
DEFAULT_ALLOCATION = os.environ.get("SUBSIDE_DEFAULT_ALLOCATION")

# Where the API stages run inputs (run-config, AOI, .netrc). cloud.data rootDir
# is "/", so the writable path is the user's $HOME minus the leading slash:
# /home/<user> -> home/<user>.
STAGING_SYSTEM = os.environ.get("SUBSIDE_STAGING_SYSTEM", "cloud.data")
STAGING_PREFIX = os.environ.get("SUBSIDE_STAGING_PREFIX", "home/{username}/subside-api")

# pipeline key -> pipeline YAML filename (sans .yaml).
PIPELINES = {"h2i": "h2i-opera", "werc": "werc-opera"}

# NOTE: CKAN+STAC publishing is the `stac-publish` function task in the Tapis
# Workflows pipeline (tapis/workflows/orchestrate.py reads STAC_*/CKAN_* /
# SUBSIDE_STAC_* from the environment there) — it is no longer driven from the
# request-path API, so no STAC config lives in this module.

# --- PostGIS vector layers (GeoJSON ingest + MVT tiles) --------------------
# Postgres *wire* endpoint behind the PostGIS database (NOT the PostgREST HTTP
# URL — psycopg speaks the postgres protocol, not HTTP). On Tapis this is the
# postgres pod reached over the pods 443 TLS-SNI tunnel, e.g.:
#   postgresql://USER:PASS@subsidepostgres.pods.portals.tapis.io:443/DBNAME?sslmode=require&sslnegotiation=direct
# The sslnegotiation=direct (libpq >= 17) is REQUIRED — the pods SNI tunnel needs
# TLS negotiated immediately; without it libpq fails with "SSL error: unexpected
# eof while reading". Unset -> the /layers and /tiles endpoints return 503.
DATABASE_URL = os.environ.get("SUBSIDE_DATABASE_URL")

# Dedicated schema the API owns for ingested layers + its registry table.
MVT_SCHEMA = os.environ.get("SUBSIDE_MVT_SCHEMA", "subside")
# Mapbox Vector Tile geometry params. Layers are stored in EPSG:4326 and
# reprojected to web-mercator (3857) per tile via ST_TileEnvelope.
MVT_SRID = int(os.environ.get("SUBSIDE_MVT_SRID", "3857"))
MVT_EXTENT = int(os.environ.get("SUBSIDE_MVT_EXTENT", "4096"))
MVT_BUFFER = int(os.environ.get("SUBSIDE_MVT_BUFFER", "64"))

# CORS origins for the dev frontend (vite, port 5174). Comma-separated env
# override. Includes the subside.local hostname for local-DNS dev; only matters
# if the browser calls the API cross-origin (the default Vite proxy is same-origin).
CORS_ORIGINS = os.environ.get(
    "SUBSIDE_CORS_ORIGINS",
    "https://subside.local:5174,http://subside.local:5174,"
    "http://localhost:5174,https://localhost:5174",
).split(",")
