"""Hermetic tests for register.py auth helpers."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace

WORKFLOW_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKFLOW_DIR))
import register  # noqa: E402


def _fake_jwt(claims: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'RS256'})}.{b64(claims)}.sig"


def test_jwt_username_prefers_tapis_claim():
    token = _fake_jwt({"sub": "someone@portals", "tapis/username": "wmobley"})
    assert register._jwt_username(token) == "wmobley"


def test_jwt_username_falls_back_to_sub():
    assert register._jwt_username(_fake_jwt({"sub": "wmobley@portals"})) == "wmobley"


def test_jwt_username_garbage_is_none():
    assert register._jwt_username("not-a-jwt") is None


def test_authenticate_fills_username_from_jwt(monkeypatch):
    """tapipy leaves ``username`` unset for JWT auth; staging paths need it."""
    token = _fake_jwt({"tapis/username": "wmobley"})
    monkeypatch.setenv("TAPIS_JWT", token)
    monkeypatch.delenv("TAPIS_USERNAME", raising=False)
    monkeypatch.delenv("TAPIS_PASSWORD", raising=False)

    class FakeTapis:
        def __init__(self, base_url, jwt):
            self.base_url, self.jwt, self.username = base_url, jwt, None

    monkeypatch.setattr(register, "_need", lambda _: SimpleNamespace(Tapis=FakeTapis))

    client = register._authenticate()
    assert client.username == "wmobley"
