"""Earthdata authentication helpers shared across SUBSIDE analyses.

* ``EarthdataSession`` / ``earthdata_session`` — ``requests.Session``
  subclass that survives the cumulus.asf → urs.earthdata OAuth redirect
  (plain ``requests`` strips Authorization on cross-host redirects and
  returns 401). Works for any URS-protected DAAC, not just ASF.
* ``earthdata_credentials`` — resolve a ``(username, password)`` pair
  from ``EARTHDATA_USERNAME`` / ``EARTHDATA_PASSWORD`` env vars or a
  standard ``~/.netrc`` entry for ``urs.earthdata.nasa.gov``.
"""

from __future__ import annotations

import os
from netrc import netrc
from urllib.parse import urlparse

import requests


URS_HOST = "urs.earthdata.nasa.gov"


class EarthdataSession(requests.Session):
    def rebuild_auth(self, prepared_request, response):
        headers = prepared_request.headers
        if "Authorization" not in headers:
            return
        redirect_host = urlparse(prepared_request.url).hostname
        original_host = urlparse(response.request.url).hostname
        if redirect_host == original_host:
            return
        if URS_HOST in (redirect_host, original_host):
            return
        del headers["Authorization"]


def earthdata_session(username: str, password: str) -> EarthdataSession:
    session = EarthdataSession()
    session.auth = (username, password)
    return session


def earthdata_credentials() -> tuple[str, str]:
    """Return ``(username, password)`` from env vars or ``~/.netrc``.

    Raises ``RuntimeError`` with an actionable message when neither source
    is configured.
    """

    username = os.environ.get("EARTHDATA_USERNAME", "").strip()
    password = os.environ.get("EARTHDATA_PASSWORD", "").strip()
    if username and password:
        return username, password

    try:
        auth = netrc().authenticators(URS_HOST)
    except Exception as exc:
        raise RuntimeError(
            f"Missing Earthdata credentials. Set EARTHDATA_USERNAME and "
            f"EARTHDATA_PASSWORD or stage a protected .netrc file for {URS_HOST}."
        ) from exc
    if not auth:
        raise RuntimeError(f"No {URS_HOST} entry found in .netrc.")
    username, _account, password = auth
    return username, password
