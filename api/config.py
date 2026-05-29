"""Static configuration for the SUBSIDE API (env-overridable)."""

from __future__ import annotations

import os
from pathlib import Path

# subside/ — used to locate pipeline YAMLs and put subside_analysis on the path.
SUBSIDE_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = SUBSIDE_ROOT / "workflows" / "pipelines"

TAPIS_BASE_URL = os.environ.get("TAPIS_BASE_URL", "https://portals.tapis.io").rstrip("/")

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
