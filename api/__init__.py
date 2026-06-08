"""SUBSIDE API facade — FastAPI gateway in front of Tapis.

Translates portal concepts (AOI, frame discovery, OPERA product search, run
submission, result manifests) into stable UI responses, and submits the
OPERA analysis as Tapis Workflows pipeline runs *as the calling user*
(token pass-through). The workflow's `run` task owns the heavy analysis job.

See subside/TAPIS_WORKFLOW_TODO.md "API Facade" for the endpoint contract.
"""
