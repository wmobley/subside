# Build context MUST be the repo root (subside/), e.g.:
#   docker build -f workflow_apps/werc/Dockerfile -t subside-werc-opera-analysis:dev .
# The COPY paths below are relative to that context, not to this directory.

FROM mambaorg/micromamba:1.5.10

USER root

COPY workflow_apps/werc/environment.yaml /tmp/environment.yaml
RUN micromamba install -y -n base -f /tmp/environment.yaml && \
    micromamba clean -a -y

COPY subside_analysis /opt/subside/subside_analysis
COPY workflow_apps/werc/run.sh /tapis/run.sh

RUN chmod 755 /tapis/run.sh

ENV PYTHONPATH=/opt/subside

WORKDIR /work

ENTRYPOINT ["/tapis/run.sh"]
