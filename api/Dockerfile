# SUBSIDE API image for Tapis pods.
#
# Carries the full geo + scientific stack (baked conda env via micromamba) so
# every endpoint works in the pod: auth, runs, forecast, layers/tiles, AND frame
# discovery + availability shading (geopandas + opera-utils + disp-xr). The env
# layer is cached unless api/environment.yaml changes, so code-only rebuilds are
# fast.
#
# Build context is the repo root (subside/): `docker build -f api/Dockerfile .`
FROM mambaorg/micromamba:1.5.10

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends bash ca-certificates curl git locales && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && locale-gen
ENV LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 LANGUAGE=en_US.UTF-8

# Solve + materialize the env at build time (chmod so it stays readable if the
# pod runs the container as a non-build user).
COPY api/environment.yaml /tmp/environment.yaml
RUN micromamba create -y -n subside-api -f /tmp/environment.yaml && \
    micromamba clean --all --yes && \
    chmod -R a+rX /opt/conda

WORKDIR /app

# App code the API imports at runtime:
#   api/      — the FastAPI app
#   analysis/ — discovery/availability/forecast import analysis.*
#   tapis/workflows/pipelines/ — YAMLs the run manager reads (PIPELINE_DIR)
COPY api /app/api
COPY analysis /app/analysis
COPY tapis/workflows/pipelines /app/tapis/workflows/pipelines

# /app on the path so `import api` / `import analysis` resolve; the baked env on
# PATH so `uvicorn`/`python` are the env's.
ENV PYTHONPATH=/app \
    PATH=/opt/conda/envs/subside-api/bin:$PATH

EXPOSE 8000

# Config comes from the pod environment (SUBSIDE_DATABASE_URL, TAPIS_CLIENT_*,
# EARTHDATA_*, SUBSIDE_CORS_ORIGINS, …). No .env is baked into the image.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
