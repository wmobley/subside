"""Pod environment for the run backend (SUBSIDE runs through DYNAMO)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TAPIS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TAPIS_DIR))
import register_pods  # noqa: E402

SCRIPT = TAPIS_DIR.parent / "ui" / "docker-entrypoint.d" / "40-runtime-config.sh"


def _runtime_config(tmp_path, env):
    out = tmp_path / "runtime-config.js"
    subprocess.run(["sh", str(SCRIPT)], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "RUNTIME_CONFIG_PATH": str(out), **env})
    return out.read_text()


def test_ui_env_forwards_the_run_backend_only_when_set(monkeypatch):
    for key in ("SUBSIDE_RUN_BACKEND", "SUBSIDE_DYNAMO_API_BASE"):
        monkeypatch.delenv(key, raising=False)
    assert "SUBSIDE_RUN_BACKEND" not in register_pods._ui_env("https://api.example")
    monkeypatch.setenv("SUBSIDE_RUN_BACKEND", "dynamo")
    monkeypatch.setenv("SUBSIDE_DYNAMO_API_BASE", "https://em.example/v1")
    env = register_pods._ui_env("https://api.example")
    assert env["SUBSIDE_RUN_BACKEND"] == "dynamo"
    assert env["SUBSIDE_DYNAMO_API_BASE"] == "https://em.example/v1"
    assert env["SUBSIDE_API_BASE"] == "https://api.example"


def test_api_env_carries_the_legacy_runs_switch():
    assert "SUBSIDE_LEGACY_RUNS" in register_pods.API_ENV_KEYS


def test_runtime_config_maps_the_run_backend_to_the_vite_keys(tmp_path):
    text = _runtime_config(tmp_path, {
        "SUBSIDE_RUN_BACKEND": "dynamo", "SUBSIDE_DYNAMO_API_BASE": "https://em.example/v1"})
    assert 'VITE_RUN_BACKEND = "dynamo"' in text
    assert 'VITE_DYNAMO_API_BASE = "https://em.example/v1"' in text


def test_runtime_config_emits_nothing_for_unset_run_backend_keys(tmp_path):
    text = _runtime_config(tmp_path, {"SUBSIDE_API_BASE": "https://api.example"})
    assert "VITE_RUN_BACKEND" not in text and "VITE_DYNAMO_API_BASE" not in text
    assert 'VITE_SUBSIDE_API_BASE = "https://api.example"' in text
