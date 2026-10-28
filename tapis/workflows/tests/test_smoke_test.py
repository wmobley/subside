"""Hermetic tests for the direct Tapis Jobs smoke-test harness."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKFLOW_DIR))
import smoke_test  # noqa: E402


def test_direct_job_overrides_queue_and_walltime(monkeypatch):
    monkeypatch.setattr(smoke_test, "_load_pipeline", lambda _: {"tasks": [{"id": "run"}]})
    run_args = smoke_test._build_args("h2i", "tapis://cloud.data/aoi.geojson", None, "ALLOC")

    body = smoke_test._direct_job_body(
        "h2i", run_args, "ALLOC", queue="development", max_minutes=60, job_name="smoke-123"
    )

    assert body["execSystemLogicalQueue"] == "development"
    assert body["maxMinutes"] == 60
    assert body["name"] == "smoke-123"


def test_direct_job_rejects_nonpositive_walltime():
    with pytest.raises(ValueError, match="positive"):
        smoke_test._direct_job_body("h2i", {}, "ALLOC", max_minutes=0)


class _Files:
    def __init__(self):
        self.deleted = []

    def delete(self, **kwargs):
        self.deleted.append(kwargs)


def _cleanup_args():
    return SimpleNamespace(staging_system="cloud.data", staging_path="home/test/run")


def test_cleanup_deletes_the_run_staging_directory():
    files = _Files()
    smoke_test._cleanup_staging(SimpleNamespace(files=files), _cleanup_args())
    assert files.deleted == [{"systemId": "cloud.data", "path": "home/test/run"}]


def test_ambiguous_submission_retains_staging_for_reconciliation(monkeypatch):
    files = _Files()
    client = SimpleNamespace(username="test", files=files)
    monkeypatch.setattr(smoke_test.register, "_authenticate", lambda: client)
    monkeypatch.setattr(smoke_test, "_stage_inputs", lambda _client, _args: ("aoi", None))
    monkeypatch.setattr(
        smoke_test,
        "_direct_job_body",
        lambda *args, **kwargs: {"appId": "app", "appVersion": "1", "name": "smoke"},
    )
    monkeypatch.setattr(
        smoke_test,
        "_submit_direct_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("submit failed")),
    )

    with pytest.raises(RuntimeError, match="submit failed"):
        smoke_test.main([
            "--direct-jobs",
            "--pipeline",
            "h2i",
            "--allocation",
            "ALLOC",
            "--staging-path",
            "home/test/run",
        ])

    assert files.deleted == []


@pytest.mark.parametrize(("status", "expected_code"), [("finished", 0), ("failed", 1)])
def test_terminal_result_cleans_up(monkeypatch, status, expected_code):
    files = _Files()
    client = SimpleNamespace(username="test", files=files)
    monkeypatch.setattr(smoke_test.register, "_authenticate", lambda: client)
    monkeypatch.setattr(smoke_test, "_stage_inputs", lambda _client, _args: ("aoi", None))
    monkeypatch.setattr(
        smoke_test,
        "_direct_job_body",
        lambda *args, **kwargs: {"appId": "app", "appVersion": "1", "name": "smoke"},
    )
    monkeypatch.setattr(smoke_test, "_submit_direct_job", lambda *_args, **_kwargs: "job-123")
    monkeypatch.setattr(smoke_test, "_poll_direct_job", lambda *_args, **_kwargs: status)

    result = smoke_test.main([
        "--direct-jobs",
        "--pipeline",
        "h2i",
        "--allocation",
        "ALLOC",
        "--staging-path",
        "home/test/run",
    ])

    assert result == expected_code
    assert files.deleted == [{"systemId": "cloud.data", "path": "home/test/run"}]
