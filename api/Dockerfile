# SUBSIDE API — slim FastAPI image for Tapis pods.
#
# Builds only what the FastAPI app needs (no heavy geo/conda stack like the
# OPERA batch apps). Working in this image: auth, runs, forecast, layers/tiles.
# Endpoints needing the geo stack (frame discovery, availability shading) return
# 503 here — add geopandas/disp-xr if you need them in the pod.
#
# Build context is the repo root (subside/): `docker build -f api/Dockerfile .`
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Core FastAPI deps (api/requirements.txt) + the light extras the shipped
# endpoints use: numpy/pandas (forecast) and psycopg (layers/tiles). All wheels,
# no system build deps required.
COPY api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt \
 && pip install "psycopg[binary]" psycopg-pool numpy pandas

# App code the API imports at runtime:
#   api/      — the FastAPI app
#   analysis/ — the forecast model (analysis.subsidence) the /forecast route uses
#   tapis/workflows/pipelines/ — YAMLs the run manager reads (PIPELINE_DIR)
COPY api /app/api
COPY analysis /app/analysis
COPY tapis/workflows/pipelines /app/tapis/workflows/pipelines

EXPOSE 8000

# Config comes from the pod's environment (EARTHDATA_*, SUBSIDE_DATABASE_URL,
# TAPIS_CLIENT_*, SUBSIDE_CORS_ORIGINS, …). No .env is baked into the image.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
