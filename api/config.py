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

# Tapis Workflows group used by the request-path API. Pipelines must already be
# registered there, typically with:
#   python tapis/workflows/register.py --pipelines-only --recreate-pipelines
SUBSIDE_WORKFLOW_GROUP = os.environ.get("SUBSIDE_WORKFLOW_GROUP", "subside-ops")

# Auto-provisioning on login: a NEW user can't add themselves, so the API acts
# as a dedicated SERVICE ACCOUNT that owns/admins the workflow group and is an
# admin of the CKAN org. On login the API idempotently (a) adds the user to
# SUBSIDE_WORKFLOW_GROUP and (b) makes them a CKAN org member at PROVISION_CKAN_ROLE.
# Because ckan.tacc accepts a Tapis JWT as a bearer token, the SAME service
# account covers both: SUBSIDE_CKAN_ADMIN_TOKEN is an OPTIONAL override; when
# unset, the CKAN add reuses the service account's own Tapis token. All optional —
# unset creds skip that step (logged) so login still works.
SUBSIDE_ADMIN_USERNAME = os.environ.get("SUBSIDE_ADMIN_USERNAME")
SUBSIDE_ADMIN_PASSWORD = os.environ.get("SUBSIDE_ADMIN_PASSWORD")
SUBSIDE_CKAN_ADMIN_TOKEN = os.environ.get("SUBSIDE_CKAN_ADMIN_TOKEN")
# CKAN org role granted to new users (editor = can create the run's dataset).
PROVISION_CKAN_ROLE = os.environ.get("SUBSIDE_PROVISION_CKAN_ROLE", "editor")
# Toggle the whole hook off without unsetting creds.
PROVISION_ON_LOGIN = os.environ.get("SUBSIDE_PROVISION_ON_LOGIN", "true").strip().lower() in (
    "1", "true", "yes", "on",
)

# Where the API stages run inputs (run-config, AOI, .netrc). cloud.data rootDir
# is "/", so the writable path is the user's $HOME minus the leading slash:
# /home/<user> -> home/<user>.
STAGING_SYSTEM = os.environ.get("SUBSIDE_STAGING_SYSTEM", "cloud.data")
STAGING_PREFIX = os.environ.get("SUBSIDE_STAGING_PREFIX", "home/{username}/subside-api")

# pipeline key -> pipeline YAML filename (sans .yaml).
PIPELINES = {"h2i": "h2i-opera", "werc": "werc-opera"}

# CKAN+STAC publishing runs inside the workflow's `stac-publish` task. The API
# passes these values as pipeline args when SUBSIDE_STAC_URL is configured.
SUBSIDE_STAC_URL = os.environ.get("SUBSIDE_STAC_URL", "")
SUBSIDE_STAC_TOKEN = os.environ.get("SUBSIDE_STAC_TOKEN", "")
SUBSIDE_STAC_COLLECTION = os.environ.get("SUBSIDE_STAC_COLLECTION", "subsidence-rates")
SUBSIDE_CKAN_URL = os.environ.get("SUBSIDE_CKAN_URL", "https://ckan.tacc.utexas.edu")
SUBSIDE_CKAN_ORG = os.environ.get("SUBSIDE_CKAN_ORG", "tacc-water")
SUBSIDE_CKAN_TOKEN = os.environ.get("SUBSIDE_CKAN_TOKEN", "")

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
