# Build context MUST be the repo root (subside/), e.g.:
#   docker build -f workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
# The COPY paths below are relative to that context, not to this directory.
#
# The conda environment is NOT baked into this image. run.sh downloads
# miniconda + materializes the env on first invocation under ENV_INSTALL_DIR
# (defaults to $WORK on TACC, /work locally). Subsequent runs reuse it.

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        bzip2 \
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

COPY subside_analysis /opt/subside/subside_analysis
COPY workflow_apps/werc/run.sh /tapis/run.sh
COPY workflow_apps/werc/environment.yaml /tapis/environment.yaml

RUN chmod 755 /tapis/run.sh

ENV PYTHONPATH=/opt/subside

WORKDIR /work

ENTRYPOINT ["/tapis/run.sh"]
