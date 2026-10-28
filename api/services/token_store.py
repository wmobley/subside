"""Encrypted, restart-safe lease records for per-run Tapis tokens.

The raw JWT is required by the Tapis revoke contract, so it is stored only as
an authenticated-encrypted value.  The store is intentionally single-instance
in Phase 1; deployments that scale the API must replace it with a shared store.
"""

from __future__ import annotations

import sqlite3
import threading
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config


class TokenStoreConfigurationError(RuntimeError):
    """The encrypted lease store is not configured safely."""


class TokenStoreError(RuntimeError):
    """A lease could not be read or updated."""


_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cipher():
    key = config.RUN_TOKEN_ENCRYPTION_KEY
    if not key:
        raise TokenStoreConfigurationError(
            "SUBSIDE_RUN_TOKEN_ENCRYPTION_KEY is required when per-run tokens are enabled."
        )
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise TokenStoreConfigurationError(
            "SUBSIDE_RUN_TOKEN_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def validate_configuration() -> None:
    """Validate lifecycle settings without creating the database."""
    if not config.RUN_TOKEN_ENABLED:
        return
    _cipher()
    if config.RUN_TOKEN_TTL_MIN_SECONDS < 1:
        raise TokenStoreConfigurationError("RUN_TOKEN_TTL_MIN_SECONDS must be positive.")
    if config.RUN_TOKEN_TTL_MAX_SECONDS < config.RUN_TOKEN_TTL_MIN_SECONDS:
        raise TokenStoreConfigurationError("RUN_TOKEN_TTL_MAX_SECONDS must be >= the minimum.")
    if config.RUN_TOKEN_TTL_BUFFER_SECONDS < 0:
        raise TokenStoreConfigurationError("RUN_TOKEN_TTL_BUFFER_SECONDS cannot be negative.")
    if config.RUN_TOKEN_QUEUE_BUDGET_SECONDS < 0:
        raise TokenStoreConfigurationError("RUN_TOKEN_QUEUE_BUDGET_SECONDS cannot be negative.")
    if config.SUBSIDE_TOKEN_BROKER_URL and not (
        config.TAPIS_CLIENT_ID and config.TAPIS_CLIENT_KEY
    ):
        raise TokenStoreConfigurationError(
            "TAPIS_CLIENT_ID and TAPIS_CLIENT_KEY are required when the token refresh broker is enabled."
        )
    if config.RUN_RECOVERY_GRACE_SECONDS < 0:
        raise TokenStoreConfigurationError("RUN_RECOVERY_GRACE_SECONDS cannot be negative.")
    if config.RUN_RECOVERY_CLEANUP_STALE_SECONDS < 1:
        raise TokenStoreConfigurationError("RUN_RECOVERY_CLEANUP_STALE_SECONDS must be positive.")


def _connect() -> sqlite3.Connection:
    validate_configuration()
    path = Path(config.RUN_TOKEN_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_token_leases (
            lease_id TEXT PRIMARY KEY,
            workflow_uuid TEXT,
            username TEXT NOT NULL,
            target_site_id TEXT NOT NULL,
            staging_path TEXT,
            token_ciphertext BLOB,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            submission_state TEXT NOT NULL,
            lease_state TEXT NOT NULL,
            cleanup_attempts INTEGER NOT NULL DEFAULT 0,
            last_cleanup_error TEXT,
            updated_at TEXT NOT NULL,
            pipeline_id TEXT,
            job_name_prefix TEXT,
            compute_job_uuid TEXT,
            recovery_state TEXT NOT NULL DEFAULT 'none',
            publish_workflow_uuid TEXT,
            recovery_attempts INTEGER NOT NULL DEFAULT 0,
            recovery_last_error TEXT,
            recovery_updated_at TEXT,
            hard_deadline_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_oauth_tokens (
            username TEXT PRIMARY KEY,
            refresh_token_ciphertext BLOB NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_token_leases)")}
    additions = {
        "pipeline_id": "TEXT",
        "job_name_prefix": "TEXT",
        "compute_job_uuid": "TEXT",
        "recovery_state": "TEXT NOT NULL DEFAULT 'none'",
        "publish_workflow_uuid": "TEXT",
        "recovery_attempts": "INTEGER NOT NULL DEFAULT 0",
        "recovery_last_error": "TEXT",
        "recovery_updated_at": "TEXT",
        "hard_deadline_at": "TEXT",
        "broker_secret_hash": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE run_token_leases ADD COLUMN {name} {definition}")
    conn.commit()
    return conn


@dataclass(frozen=True)
class Lease:
    lease_id: str
    workflow_uuid: str | None
    username: str
    target_site_id: str
    staging_path: str | None
    token: str | None
    created_at: str
    expires_at: str | None
    submission_state: str
    lease_state: str
    cleanup_attempts: int
    last_cleanup_error: str | None
    pipeline_id: str | None = None
    job_name_prefix: str | None = None
    compute_job_uuid: str | None = None
    recovery_state: str = "none"
    publish_workflow_uuid: str | None = None
    recovery_attempts: int = 0
    recovery_last_error: str | None = None
    recovery_updated_at: str | None = None
    hard_deadline_at: str | None = None


def _row_to_lease(row: sqlite3.Row, decrypt: bool = True) -> Lease:
    token = None
    if decrypt and row["token_ciphertext"] is not None:
        try:
            token = _cipher().decrypt(bytes(row["token_ciphertext"])).decode("utf-8")
        except Exception as exc:
            raise TokenStoreError("Could not decrypt a stored run-token lease.") from exc
    return Lease(
        lease_id=row["lease_id"], workflow_uuid=row["workflow_uuid"],
        username=row["username"], target_site_id=row["target_site_id"],
        staging_path=row["staging_path"], token=token,
        created_at=row["created_at"], expires_at=row["expires_at"],
        submission_state=row["submission_state"], lease_state=row["lease_state"],
        cleanup_attempts=row["cleanup_attempts"],
        last_cleanup_error=row["last_cleanup_error"],
        pipeline_id=row["pipeline_id"] if "pipeline_id" in row.keys() else None,
        job_name_prefix=row["job_name_prefix"] if "job_name_prefix" in row.keys() else None,
        compute_job_uuid=row["compute_job_uuid"] if "compute_job_uuid" in row.keys() else None,
        recovery_state=(row["recovery_state"] if "recovery_state" in row.keys() else None) or "none",
        publish_workflow_uuid=row["publish_workflow_uuid"] if "publish_workflow_uuid" in row.keys() else None,
        recovery_attempts=(row["recovery_attempts"] if "recovery_attempts" in row.keys() else None) or 0,
        recovery_last_error=row["recovery_last_error"] if "recovery_last_error" in row.keys() else None,
        recovery_updated_at=row["recovery_updated_at"] if "recovery_updated_at" in row.keys() else None,
        hard_deadline_at=row["hard_deadline_at"] if "hard_deadline_at" in row.keys() else None,
    )


def create(lease_id: str, *, token: str, username: str, target_site_id: str,
           staging_path: str | None, expires_at: str | None,
           pipeline_id: str | None = None, job_name_prefix: str | None = None,
           hard_deadline_at: str | None = None,
           broker_secret: str | None = None) -> Lease:
    """Persist a token before any workflow submission is attempted."""
    ciphertext = _cipher().encrypt(token.encode("utf-8"))
    now = _now()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO run_token_leases
                    (lease_id, username, target_site_id, staging_path, token_ciphertext,
                     created_at, expires_at, submission_state, lease_state, updated_at,
                     pipeline_id, job_name_prefix, hard_deadline_at, recovery_updated_at,
                     broker_secret_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'not_submitted', 'active', ?, ?, ?, ?, ?, ?)
                """,
                (lease_id, username, target_site_id, staging_path, ciphertext, now, expires_at, now,
                 pipeline_id, job_name_prefix, hard_deadline_at, now,
                 hashlib.sha256(broker_secret.encode()).hexdigest() if broker_secret else None),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM run_token_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            return _row_to_lease(row)
        finally:
            conn.close()


def upsert_user_refresh_token(username: str, refresh_token: str | None) -> None:
    """Store the OAuth refresh token encrypted and keyed to the Tapis user."""
    if not refresh_token:
        return
    ciphertext = _cipher().encrypt(str(refresh_token).encode("utf-8"))
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """INSERT INTO user_oauth_tokens(username, refresh_token_ciphertext, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(username) DO UPDATE SET
                     refresh_token_ciphertext = excluded.refresh_token_ciphertext,
                     updated_at = excluded.updated_at""",
                (username, ciphertext, _now()),
            )
            conn.commit()
        finally:
            conn.close()


def get_user_refresh_token(username: str) -> str | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT refresh_token_ciphertext FROM user_oauth_tokens WHERE username = ?",
                (username,),
            ).fetchone()
            if not row:
                return None
            try:
                return _cipher().decrypt(bytes(row[0])).decode("utf-8")
            except Exception as exc:
                raise TokenStoreError("Could not decrypt the stored OAuth refresh token.") from exc
        finally:
            conn.close()


def find_by_lease_credential(lease_id: str, credential: str) -> Lease | None:
    if not lease_id or not credential:
        return None
    expected = hashlib.sha256(credential.encode()).hexdigest()
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM run_token_leases WHERE lease_id = ? AND broker_secret_hash = ?",
                (lease_id, expected),
            ).fetchone()
            return _row_to_lease(row) if row else None
        finally:
            conn.close()


def replace_token(lease_id: str, token: str, expires_at: str | None) -> None:
    ciphertext = _cipher().encrypt(token.encode("utf-8"))
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """UPDATE run_token_leases
                   SET token_ciphertext = ?, expires_at = ?, lease_state = 'active',
                       updated_at = ?, recovery_last_error = NULL
                 WHERE lease_id = ? AND lease_state = 'active'""",
                (ciphertext, expires_at, _now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def bind_workflow(lease_id: str, workflow_uuid: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET workflow_uuid = ?, submission_state = 'submitted', updated_at = ? WHERE lease_id = ?",
                (workflow_uuid, _now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def mark_submission_unknown(lease_id: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET submission_state = 'unknown', updated_at = ? WHERE lease_id = ?",
                (_now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def record_compute_job(lease_id: str, job_uuid: str) -> None:
    """Persist the inner Jobs UUID as soon as a pipeline discovers it."""
    now = _now()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET compute_job_uuid = ?, recovery_state = 'reconciling', recovery_updated_at = ?, updated_at = ? WHERE lease_id = ?",
                (job_uuid, now, now, lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_recovery_state(lease_id: str, state: str, *, error: str | None = None,
                       publish_workflow_uuid: str | None = None) -> None:
    """Advance recovery state without storing credentials or raw responses."""
    safe = str(error or "")[:500] or None
    now = _now()
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                """UPDATE run_token_leases
                   SET recovery_state = ?, recovery_last_error = ?,
                       publish_workflow_uuid = COALESCE(?, publish_workflow_uuid),
                       recovery_attempts = recovery_attempts + 1,
                       recovery_updated_at = ?, updated_at = ?
                 WHERE lease_id = ?""",
                (state, safe, publish_workflow_uuid, now, now, lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def active_recovery_candidates() -> list[Lease]:
    """Return runs that may need reconciliation after an API restart."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """SELECT * FROM run_token_leases
                   WHERE lease_state = 'active'
                     AND (workflow_uuid IS NOT NULL OR submission_state = 'unknown')
                     AND recovery_state NOT IN ('completed', 'failed')"""
            ).fetchall()
            return [_row_to_lease(row) for row in rows]
        finally:
            conn.close()


def find_by_workflow(workflow_uuid: str) -> Lease | None:
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM run_token_leases WHERE workflow_uuid = ?", (workflow_uuid,)
            ).fetchone()
            return _row_to_lease(row) if row else None
        finally:
            conn.close()


def claim_cleanup(lease_id: str) -> Lease | None:
    """Atomically claim a lease so concurrent status/reconcile calls do not race."""
    with _lock:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            stale_cutoff = (
                datetime.now(timezone.utc)
                - timedelta(seconds=config.RUN_RECOVERY_CLEANUP_STALE_SECONDS)
            ).isoformat()
            cur = conn.execute(
                """
                UPDATE run_token_leases
                   SET lease_state = 'revoke_pending',
                       cleanup_attempts = cleanup_attempts + 1,
                       updated_at = ?
                 WHERE lease_id = ?
                   AND (lease_state NOT IN ('revoke_pending', 'revoked', 'expired')
                        OR (lease_state = 'revoke_pending' AND updated_at <= ?))
                """,
                (_now(), lease_id, stale_cutoff),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None
            row = conn.execute(
                "SELECT * FROM run_token_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            conn.commit()
            return _row_to_lease(row)
        finally:
            conn.close()


def mark_revoked(lease_id: str) -> None:
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET token_ciphertext = NULL, lease_state = 'revoked', last_cleanup_error = NULL, updated_at = ? WHERE lease_id = ?",
                (_now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def mark_expired(lease_id: str) -> None:
    """Drop ciphertext after the server-issued expiry is past."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET token_ciphertext = NULL, lease_state = 'expired', updated_at = ? WHERE lease_id = ?",
                (_now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def mark_cleanup_failed(lease_id: str, error: str) -> None:
    safe = str(error or "cleanup failed")[:500]
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE run_token_leases SET lease_state = 'cleanup_failed', last_cleanup_error = ?, updated_at = ? WHERE lease_id = ?",
                (safe, _now(), lease_id),
            )
            conn.commit()
        finally:
            conn.close()


def cleanup_candidates() -> list[Lease]:
    """Return only leases safe to retry; active submitted leases are excluded."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM run_token_leases WHERE lease_state IN ('cleanup_failed', 'revoke_pending')"
            ).fetchall()
            return [_row_to_lease(row) for row in rows]
        finally:
            conn.close()


def expired_candidates() -> list[Lease]:
    """Return non-revoked leases whose server-issued expiry has passed."""
    now = _now()
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM run_token_leases
                 WHERE lease_state NOT IN ('revoked', 'expired')
                   AND COALESCE(hard_deadline_at, expires_at) IS NOT NULL
                   AND COALESCE(hard_deadline_at, expires_at) <= ?
                   AND recovery_state NOT IN ('reconciling', 'compute_active', 'publish_submitting', 'publish_active')
                """,
                (now,),
            ).fetchall()
            return [_row_to_lease(row, decrypt=False) for row in rows]
        finally:
            conn.close()
