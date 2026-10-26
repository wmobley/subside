"""Hermetic tests for the per-run Tapis token lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from api import config
from api.models import RunRequest
from api.services import manager, tapis, token_store


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class Files:
    def __init__(self):
        self.deleted = []

    def delete(self, **kwargs):
        self.deleted.append(kwargs)


class Client:
    def __init__(self):
        self.subside_access_token = "browser.jwt"
        self.username = "burner"
        self.files = Files()


@pytest.fixture
def configured_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_TOKEN_ENABLED", True)
    monkeypatch.setattr(config, "RUN_TOKEN_STORE_PATH", str(tmp_path / "leases.sqlite3"))
    monkeypatch.setattr(config, "RUN_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_store.validate_configuration()
    return tmp_path / "leases.sqlite3"


def test_mint_uses_verified_tokens_contract(monkeypatch):
    calls = []
    token = "header.payload.signature"

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(201, {"result": {"access_token": {
            "access_token": token, "expires_at": "2099-01-01T00:00:00Z", "expires_in": 3600,
        }}})

    monkeypatch.setattr("requests.post", post)
    result = tapis.mint_run_token("browser.jwt", "burner", "subside-run-abc", 3600)

    assert result["token"] == token
    assert calls[0][0].endswith("/v3/tokens")
    assert calls[0][1]["headers"]["X-Tapis-Token"] == "browser.jwt"
    assert calls[0][1]["json"] == {
        "token_tenant_id": "portals",
        "account_type": "user",
        "token_username": "burner",
        "target_site_id": "subside-run-abc",
        "access_token_ttl": 3600,
    }


def test_mint_rejects_nonpositive_ttl_before_network(monkeypatch):
    def post(*args, **kwargs):
        raise AssertionError("invalid TTL must not reach Tapis")

    monkeypatch.setattr("requests.post", post)
    with pytest.raises(tapis.TokenMintError, match="positive integer"):
        tapis.mint_run_token("browser.jwt", "burner", "subside-run-invalid", 0)


def test_refresh_user_token_uses_oauth_refresh_grant(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(200, {"result": {
            "access_token": {"access_token": "new-access", "expires_at": "2099-01-01T00:00:00Z"},
            "refresh_token": {"refresh_token": "rotated-refresh"},
        }})

    monkeypatch.setattr(config, "TAPIS_CLIENT_ID", "client-id")
    monkeypatch.setattr(config, "TAPIS_CLIENT_KEY", "client-key")
    monkeypatch.setattr("requests.post", post)
    result = tapis.refresh_user_token("old-refresh")

    assert result == {
        "token": "new-access",
        "expires_at": "2099-01-01T00:00:00Z",
        "refresh_token": "rotated-refresh",
    }
    assert calls[0][0].endswith("/v3/oauth2/tokens")
    assert calls[0][1]["auth"] == ("client-id", "client-key")
    assert calls[0][1]["json"] == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}


def test_password_login_returns_refresh_token(monkeypatch):
    def post(url, **kwargs):
        assert url.endswith("/v3/oauth2/tokens")
        assert kwargs["json"] == {
            "username": "burner", "password": "password", "grant_type": "password",
        }
        return Response(200, {"result": {
            "access_token": {"access_token": "access.jwt", "expires_at": "2099-01-01T00:00:00Z"},
            "refresh_token": {"refresh_token": "refresh.jwt"},
        }})

    monkeypatch.setattr("requests.post", post)
    result = tapis.login_with_tokens("burner", "password")

    assert result["token"] == "access.jwt"
    assert result["username"] == "burner"
    assert result["refresh_token"] == "refresh.jwt"


def test_revoke_uses_verified_contract_and_redacts_token(monkeypatch):
    calls = []
    token = "header.payload.secret-canary"

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response(503)

    monkeypatch.setattr("requests.post", post)
    with pytest.raises(tapis.TokenRevokeError) as excinfo:
        tapis.revoke_token("admin.jwt", token)

    assert calls[0][0].endswith("/v3/tokens/revoke")
    assert calls[0][1]["json"] == {"token": token}
    assert token not in str(excinfo.value)


def test_store_encrypts_raw_token_and_tracks_cleanup(configured_store):
    raw = "header.payload.secret-canary"
    token_store.create(
        "lease-1", token=raw, username="burner", target_site_id="subside-run-1",
        staging_path="home/burner/subside-api/lease-1", expires_at="2099-01-01T00:00:00Z",
    )
    assert raw not in Path(configured_store).read_bytes().decode("latin1")
    assert token_store.find_by_workflow("missing") is None
    token_store.bind_workflow("lease-1", "workflow-1")
    lease = token_store.find_by_workflow("workflow-1")
    assert lease and lease.token == raw


def test_ttl_is_walltime_plus_buffer_and_clamped(monkeypatch):
    monkeypatch.setattr(config, "RUN_TOKEN_TTL_BUFFER_SECONDS", 60)
    monkeypatch.setattr(config, "RUN_TOKEN_TTL_MIN_SECONDS", 300)
    monkeypatch.setattr(config, "RUN_TOKEN_TTL_MAX_SECONDS", 1000)
    assert manager._run_token_ttl(1) == 300
    assert manager._run_token_ttl(10) == 660
    assert manager._run_token_ttl(100) == 1000


def test_cleanup_revoke_is_atomic_and_removes_ciphertext(configured_store, monkeypatch):
    raw = "header.payload.secret-canary"
    token_store.create(
        "lease-2", token=raw, username="burner", target_site_id="subside-run-2",
        staging_path="home/burner/subside-api/lease-2", expires_at=None,
    )
    calls = []
    monkeypatch.setattr(tapis, "revoke_token", lambda auth, token: calls.append((auth, token)))
    client = Client()

    assert manager._cleanup_lease(client, "lease-2") is True
    assert calls == [("browser.jwt", raw)]
    assert client.files.deleted == [{"systemId": config.STAGING_SYSTEM, "path": "home/burner/subside-api/lease-2"}]
    assert token_store.find_by_workflow("missing") is None
    assert token_store.claim_cleanup("lease-2") is None


def test_restart_reconciliation_retries_only_cleanup_failed(configured_store, monkeypatch):
    token_store.create(
        "lease-retry", token="header.payload.retry", username="burner",
        target_site_id="subside-run-retry", staging_path="home/burner/retry",
        expires_at="2099-01-01T00:00:00Z",
    )
    token_store.mark_cleanup_failed("lease-retry", "temporary upstream failure")
    calls = []
    monkeypatch.setattr(tapis, "revoke_token", lambda auth, token: calls.append((auth, token)))

    assert manager.reconcile_run_tokens(Client()) == 1
    assert calls == [("browser.jwt", "header.payload.retry")]
    assert token_store.claim_cleanup("lease-retry") is None


def test_run_args_keep_explicit_publish_tokens_separate(monkeypatch):
    monkeypatch.setattr(config, "SUBSIDE_STAC_URL", "https://stac.example")
    monkeypatch.setattr(config, "SUBSIDE_CKAN_TOKEN", "ckan-secret")
    monkeypatch.setattr(config, "SUBSIDE_STAC_TOKEN", "stac-secret")
    req = type("Req", (), {
        "start_date": "2024-01-01", "end_date": "2024-02-01", "pipeline": "h2i",
        "num_workers": 4, "min_overlap_percent": 50.0, "update_conda_env": "false",
    })()
    args = manager._workflow_args(
        req, {"aoi_geojson_uri": "tapis://cloud/aoi", "earthdata_netrc_uri": ""},
        "alloc", "run-secret", username="burner", max_minutes=10,
    )
    assert args["tapis_token"]["value"] == "run-secret"
    assert args["ckan_token"]["value"] == "ckan-secret"
    assert args["stac_token"]["value"] == "stac-secret"


def test_submit_mints_and_submits_the_run_token(configured_store, monkeypatch):
    client = Client()
    captured = {}
    monkeypatch.setattr(config, "DEFAULT_ALLOCATION", "alloc")
    monkeypatch.setattr(config, "SUBSIDE_STAC_URL", "")
    monkeypatch.setattr(manager, "_stage", lambda *args: {
        "aoi_geojson_uri": "tapis://cloud/aoi",
        "earthdata_netrc_uri": "",
        "staging_path": "home/burner/subside-api/lease-3",
    })
    monkeypatch.setattr(manager, "_pick_run_queue", lambda req: None)
    monkeypatch.setattr(manager, "_resolve_walltime", lambda req: 10)
    monkeypatch.setattr(tapis, "mint_run_token", lambda *args: {
        "token": "run.jwt", "expires_at": "2099-01-01T00:00:00Z",
    })

    def trigger(_client, _pipeline, _name, run_args):
        captured.update(run_args)
        return "workflow-3"

    monkeypatch.setattr(manager, "_trigger_pipeline", trigger)
    req = RunRequest(
        start_date="2024-01-01", end_date="2024-02-01",
        aoi_geojson={"type": "Polygon", "coordinates": []},
    )
    result = manager.submit_run(client, req)

    assert result["uuid"] == "workflow-3"
    assert captured["tapis_token"]["value"] == "run.jwt"
    assert "browser.jwt" not in str(captured)
    lease = token_store.find_by_workflow("workflow-3")
    assert lease and lease.token == "run.jwt" and lease.submission_state == "submitted"


def test_refresh_broker_rotates_run_token_without_exposing_refresh_token(configured_store, monkeypatch):
    token_store.upsert_user_refresh_token("burner", "refresh-secret")
    token_store.create(
        "lease-refresh", token="old-run.jwt", username="burner",
        target_site_id="subside-run-refresh", staging_path="home/burner/refresh",
        expires_at="2020-01-01T00:00:00Z", broker_secret="opaque-broker-secret",
    )
    monkeypatch.setattr(tapis, "refresh_user_token", lambda token: {
        "token": "fresh-user.jwt", "expires_at": "2099-01-01T00:00:00Z",
        "refresh_token": "rotated-refresh-secret",
    })
    monkeypatch.setattr(tapis, "mint_run_token", lambda *args: {
        "token": "new-run.jwt", "expires_at": "2099-01-01T00:30:00Z",
    })
    revoked = []
    monkeypatch.setattr(tapis, "revoke_token", lambda auth, token: revoked.append((auth, token)))

    result = manager.refresh_run_token("lease-refresh", "opaque-broker-secret")
    lease = token_store.find_by_lease_credential("lease-refresh", "opaque-broker-secret")

    assert result["token"] == "new-run.jwt"
    assert lease and lease.token == "new-run.jwt"
    assert revoked == [("fresh-user.jwt", "old-run.jwt")]
    assert token_store.get_user_refresh_token("burner") == "rotated-refresh-secret"
    assert "refresh-secret" not in Path(configured_store).read_bytes().decode("latin1")


def test_refresh_broker_retry_reuses_stored_fresh_token(configured_store, monkeypatch):
    token_store.create(
        "lease-idempotent", token="fresh-run.jwt", username="burner",
        target_site_id="subside-run-idempotent", staging_path=None,
        expires_at="2099-01-01T00:00:00+00:00",
        hard_deadline_at="2099-01-02T00:00:00+00:00",
        broker_secret="opaque-idempotent-secret",
    )
    monkeypatch.setattr(
        tapis, "refresh_user_token",
        lambda _token: pytest.fail("a retry must not spend the rotated refresh token again"),
    )

    result = manager.refresh_run_token("lease-idempotent", "opaque-idempotent-secret")

    assert result == {
        "token": "fresh-run.jwt",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


def test_refresh_broker_rejects_past_hard_deadline(configured_store, monkeypatch):
    token_store.upsert_user_refresh_token("burner", "refresh-secret")
    token_store.create(
        "lease-deadline", token="old-run.jwt", username="burner",
        target_site_id="subside-run-deadline", staging_path=None,
        expires_at="2020-01-01T00:00:00+00:00",
        hard_deadline_at="2020-01-02T00:00:00+00:00",
        broker_secret="opaque-deadline-secret",
    )

    with pytest.raises(manager.RunTokenConfigurationError, match="hard deadline"):
        manager.refresh_run_token("lease-deadline", "opaque-deadline-secret")


def test_reconcile_failed_workflow_from_exact_job_name(configured_store, monkeypatch):
    class Workflows:
        def getPipelineRun(self, **kwargs):
            return {"uuid": "workflow-recover", "status": "FAILED"}

        def listTaskExecutions(self, **kwargs):
            return [{"task_id": "run", "status": "FAILED", "last_message": "Jobs API 504"}]

    class Jobs:
        def getJob(self, **kwargs):
            raise RuntimeError("not using task UUID")

    class RecoveryFiles(Files):
        def listFiles(self, **kwargs):
            return [{"path": "home/burner/archive/run-manifest.json", "type": "file"}]

    class RecoveryClient(Client):
        def __init__(self):
            super().__init__()
            self.workflows = Workflows()
            self.jobs = Jobs()
            self.files = RecoveryFiles()

    token_store.create(
        "lease-recover", token="run.jwt", username="burner", target_site_id="subside-run-recover",
        staging_path="home/burner/recover", expires_at="2099-01-01T00:00:00Z",
        pipeline_id="subside-h2i-opera", job_name_prefix="subside-h2i-opera-lease-recover",
    )
    token_store.bind_workflow("lease-recover", "workflow-recover")
    monkeypatch.setattr(tapis, "search_jobs", lambda *args, **kwargs: [{
        "uuid": "job-recovered", "name": "subside-h2i-opera-lease-recover",
        "owner": "burner", "appId": "subside-h2i-opera-analysis",
        "status": "FINISHED", "condition": "NORMAL_COMPLETION",
        "archiveSystemId": "ls6", "archiveSystemDir": "home/burner/archive",
    }])
    monkeypatch.setattr(tapis, "revoke_token", lambda *args: None)
    monkeypatch.setattr(config, "SUBSIDE_STAC_URL", "")

    result = manager.get_status(RecoveryClient(), "workflow-recover")

    assert result["status"] == "completed"
    assert result["recovered"] is True
    assert result["innerJobUuid"] == "job-recovered"
    assert result["computeStatus"] == "completed"
    assert result["publicationStatus"] == "not_configured"
    lease = token_store.find_by_workflow("workflow-recover")
    assert lease and lease.lease_state == "revoked" and lease.token is None
    assert manager.get_status(RecoveryClient(), "workflow-recover")["status"] == "completed"


def test_recovery_search_rejects_ambiguous_exact_name(configured_store, monkeypatch):
    token_store.create(
        "lease-ambiguous", token="run.jwt", username="burner", target_site_id="subside-run-ambiguous",
        staging_path="home/burner/ambiguous", expires_at="2099-01-01T00:00:00Z",
        pipeline_id="subside-h2i-opera", job_name_prefix="subside-h2i-opera-lease-ambiguous",
    )
    token_store.bind_workflow("lease-ambiguous", "workflow-ambiguous")
    lease = token_store.find_by_workflow("workflow-ambiguous")
    assert lease is not None
    monkeypatch.setattr(tapis, "search_jobs", lambda *args, **kwargs: [
        {"uuid": "job-1", "owner": "burner", "appId": "subside-h2i-opera-analysis"},
        {"uuid": "job-2", "owner": "burner", "appId": "subside-h2i-opera-analysis"},
    ])
    with pytest.raises(ValueError, match="Multiple exact-name"):
        manager._find_recovery_job(Client(), lease, "h2i")


def test_werc_recovery_prefers_attempt_two_only_after_oom(configured_store, monkeypatch):
    token_store.create(
        "lease-werc", token="run.jwt", username="burner", target_site_id="subside-run-werc",
        staging_path="home/burner/werc", expires_at="2099-01-01T00:00:00Z",
        pipeline_id="subside-werc-opera", job_name_prefix="subside-werc-opera-lease-werc",
    )
    token_store.bind_workflow("lease-werc", "workflow-werc")
    lease = token_store.find_by_workflow("workflow-werc")
    assert lease is not None

    def search(_client, *, name=None, **kwargs):
        if name.endswith("attempt-1"):
            return [{"uuid": "job-1", "owner": "burner", "appId": "subside-werc-opera-analysis",
                     "status": "FAILED", "remoteResultInfo": "OUT_OF_MEMORY"}]
        return [{"uuid": "job-2", "owner": "burner", "appId": "subside-werc-opera-analysis",
                 "status": "RUNNING"}]

    monkeypatch.setattr(tapis, "search_jobs", search)
    assert manager._find_recovery_job(Client(), lease, "werc")["uuid"] == "job-2"


def test_recovery_starts_publish_once_and_cleans_up_after_publish(configured_store, monkeypatch):
    class Workflows:
        def getPipelineRun(self, **kwargs):
            return {"uuid": "workflow-publish", "status": "FAILED"}

        def listTaskExecutions(self, **kwargs):
            return [{"task_id": "run", "status": "FAILED"}]

        def listPipelineRuns(self, **kwargs):
            return []

        def runPipeline(self, **kwargs):
            return {"uuid": "publish-1"}

    class PublishWorkflows:
        def listPipelineRuns(self, **kwargs):
            return []

        def runPipeline(self, **kwargs):
            return {"uuid": "publish-1"}

    class PublishClient:
        def __init__(self):
            self.workflows = PublishWorkflows()

    class Jobs:
        def getJob(self, **kwargs):
            raise RuntimeError("not using task UUID")

    class RecoveryFiles(Files):
        def listFiles(self, **kwargs):
            return [{"path": "home/burner/archive/werc-run-manifest.json", "type": "file"}]

    class RecoveryClient(Client):
        def __init__(self):
            super().__init__()
            self.workflows = Workflows()
            self.jobs = Jobs()
            self.files = RecoveryFiles()

    token_store.create(
        "lease-publish", token="run.jwt", username="burner", target_site_id="subside-run-publish",
        staging_path="home/burner/publish", expires_at="2099-01-01T00:00:00Z",
        pipeline_id="subside-h2i-opera", job_name_prefix="subside-h2i-opera-lease-publish",
    )
    token_store.bind_workflow("lease-publish", "workflow-publish")
    monkeypatch.setattr(tapis, "search_jobs", lambda *args, **kwargs: [{
        "uuid": "job-publish", "name": "subside-h2i-opera-lease-publish",
        "owner": "burner", "appId": "subside-h2i-opera-analysis",
        "status": "FINISHED", "condition": "NORMAL_COMPLETION",
        "archiveSystemId": "ls6", "archiveSystemDir": "home/burner/archive",
    }])
    monkeypatch.setattr(tapis, "client_from_token", lambda token: PublishClient())
    monkeypatch.setattr(tapis, "revoke_token", lambda *args: None)
    monkeypatch.setattr(config, "SUBSIDE_STAC_URL", "https://stac.example")

    first = manager.get_status(RecoveryClient(), "workflow-publish")
    assert first["status"] == "recovering"
    assert first["publicationStatus"] == "active"
    lease = token_store.find_by_workflow("workflow-publish")
    assert lease and lease.publish_workflow_uuid == "publish-1"

    monkeypatch.setattr(manager, "_publish_status", lambda lease: "completed")
    second = manager.get_status(RecoveryClient(), "workflow-publish")
    assert second["status"] == "completed"
    assert second["publicationStatus"] == "completed"
