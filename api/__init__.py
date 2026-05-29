"""SUBSIDE API facade — FastAPI gateway in front of Tapis.

Translates portal concepts (AOI, frame discovery, OPERA product search, run
submission, result manifests) into stable UI responses, and submits the
OPERA analysis as Tapis Jobs *as the calling user* (token pass-through) — the
same identity that makes workflows/orchestrate.py work, so it inherits the
restricted-Workflows-service bypass.

See subside/TAPIS_WORKFLOW_TODO.md "API Facade" for the endpoint contract.
"""
