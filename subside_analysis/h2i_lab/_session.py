"""Earthdata-aware requests.Session.

The DAAC endpoints (cumulus.asf.earthdatacloud.nasa.gov,
data.lpdaac.earthdatacloud.nasa.gov, ...) all redirect unauthenticated
requests to ``urs.earthdata.nasa.gov/oauth/authorize`` to complete the
OAuth handshake. requests.Session strips the ``Authorization`` header
on cross-host redirects by default, which breaks the handshake and
yields a 401.

This subclass keeps Basic Auth attached when redirecting to or from
``urs.earthdata.nasa.gov`` so the same session can hand its credentials
to URS during the redirect chain. It mirrors the pattern NASA documents
for ``requests``-based Earthdata access without adding a third-party
dependency.
"""

from __future__ import annotations

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
