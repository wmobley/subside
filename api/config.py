"""Static configuration for the SUBSIDE API (env-overridable)."""

from __future__ import annotations

import os
from pathlib import Path

# subside/ — used to locate pipeline YAMLs and put subside_analysis on the path.
SUBSIDE_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = SUBSIDE_ROOT / "workflows" / "pipelines"

# Load subside/.env (copy from .env.sample) so local config + the Earthdata
# service account live outside the request path and outside git. No-op if
# python-dotenv isn't installed or the file is absent.
try:
    from dotenv import load_dotenv
    load_dotenv(SUBSIDE_ROOT / ".env")
except ImportError:
    pass

TAPIS_BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io").rstrip("/")

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

# CORS origins for the dev frontend (vite). Comma-separated env override.
CORS_ORIGINS = os.environ.get(
    "SUBSIDE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
