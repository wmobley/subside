"""SUBSIDE_LEGACY_RUNS: the deprecated run routes return 410 when the flag is off."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config
from api.main import app

RUN_ROUTES = [
    ("post", "/api/subside/runs"),
    ("get", "/api/subside/runs"),
    ("get", "/api/subside/runs/abc"),
    ("get", "/api/subside/runs/abc/results"),
    ("get", "/api/subside/runs/abc/file?path=x"),
]


@pytest.fixture
def client():
    return TestClient(app)


def test_flag_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("SUBSIDE_LEGACY_RUNS", raising=False)
    assert config._env_bool("SUBSIDE_LEGACY_RUNS", True) is True
    monkeypatch.setenv("SUBSIDE_LEGACY_RUNS", "false")
    assert config._env_bool("SUBSIDE_LEGACY_RUNS", True) is False


@pytest.mark.parametrize("method,path", RUN_ROUTES)
def test_run_routes_return_410_when_flag_off(client, monkeypatch, method, path):
    monkeypatch.setattr(config, "SUBSIDE_LEGACY_RUNS", False)
    # no token and (for POST) no body: the flag check must win over auth and validation
    resp = getattr(client, method)(path)
    assert resp.status_code == 410
    detail = resp.json()["detail"]
    assert detail["code"] == "RUNS_MOVED_TO_DYNAMO"
    assert "DYNAMO" in detail["message"]


@pytest.mark.parametrize("method,path", RUN_ROUTES)
def test_run_routes_unchanged_when_flag_on(client, monkeypatch, method, path):
    monkeypatch.setattr(config, "SUBSIDE_LEGACY_RUNS", True)
    resp = getattr(client, method)(path)
    # past the flag check: the auth dependency (or body validation) answers instead
    assert resp.status_code in (401, 422)


def test_estimate_and_healthz_unaffected_when_flag_off(client, monkeypatch):
    monkeypatch.setattr(config, "SUBSIDE_LEGACY_RUNS", False)
    assert client.get("/api/subside/healthz").status_code == 200
    # /runs/estimate keeps validating its body (422), it is not retired
    assert client.post("/api/subside/runs/estimate", json={}).status_code == 422


def test_openapi_marks_run_routes_deprecated_not_estimate(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/subside/runs"]["post"]["deprecated"] is True
    assert paths["/api/subside/runs"]["get"]["deprecated"] is True
    assert paths["/api/subside/runs/{run_id}"]["get"]["deprecated"] is True
    assert paths["/api/subside/runs/{run_id}/results"]["get"]["deprecated"] is True
    assert paths["/api/subside/runs/{run_id}/file"]["get"]["deprecated"] is True
    assert "deprecated" not in paths["/api/subside/runs/estimate"]["post"]
    assert "410" in paths["/api/subside/runs"]["post"]["responses"]
