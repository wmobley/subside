# Build context MUST be the repo root (subside/), e.g.:
#   docker build -f workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
# The COPY paths below are relative to that context, not to this directory.
#
# The conda environment IS baked into this image at build time via micromamba.
# run.sh just activates it and runs — no runtime miniconda download, no
# `conda env create` inside the job (which was taking tens of minutes on the
# first invocation). Updating dependencies now means editing environment.yaml
# and rebuilding the image (the env layer is cached unless that file changes).

FROM mambaorg/micromamba:1.5.10

# apt deps need root; the micromamba base runs as 'mambauser' by default.
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        locales && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

ENV LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8

# Solve + materialize the env at build time. chmod a+rX so the env stays
# readable when Singularity runs the container as the invoking TACC user
# (not the build-time mambauser).
COPY workflow_apps/werc/environment.yaml /tmp/environment.yaml
RUN micromamba create -y -n subside-werc-opera -f /tmp/environment.yaml && \
    micromamba clean --all --yes && \
    chmod -R a+rX /opt/conda

# Code + entrypoint.
COPY subside_analysis /opt/subside/subside_analysis
COPY workflow_apps/werc/run.sh /tapis/run.sh
RUN chmod 755 /tapis/run.sh

ENV PYTHONPATH=/opt/subside

WORKDIR /work

ENTRYPOINT ["/tapis/run.sh"]
