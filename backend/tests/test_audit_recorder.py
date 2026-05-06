"""SEC-04: unit tests for the audit recorder helpers."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from app.audit import recorder
from app.audit.recorder import (
    EVENT_AUTH_LOGIN,
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    record_admin_action,
    record_event,
    record_login_failure,
    record_login_success,
    request_context,
)
from app.db.models.audit_log import AuditLogRow
from app.schemas.auth import CurrentUser

# ---------------------------------------------------------------------------
# Recording session double — captures add()/commit() calls
# ---------------------------------------------------------------------------


class _Recorder:
    """Minimal Session stand-in that tracks add()/commit()/rollback()."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def db() -> _Recorder:
    return _Recorder()


# ---------------------------------------------------------------------------
# request_context
# ---------------------------------------------------------------------------


class TestRequestContext:
    def test_none_request_returns_none_pair(self) -> None:
        assert request_context(None) == (None, None)

    def test_extracts_client_host_and_ua(self) -> None:
        req = MagicMock()
        req.client.host = "10.0.0.5"
        req.headers = {"user-agent": "pytest/1.0"}
        ip, ua = request_context(req)
        assert ip == "10.0.0.5"
        assert ua == "pytest/1.0"

    def test_x_forwarded_for_takes_precedence(self) -> None:
        req = MagicMock()
        req.client.host = "10.0.0.5"
        req.headers = {
            "x-forwarded-for": "203.0.113.7, 10.0.0.1",
            "user-agent": "pytest/1.0",
        }
        ip, _ = request_context(req)
        assert ip == "203.0.113.7"

    def test_long_user_agent_truncated(self) -> None:
        req = MagicMock()
        req.client.host = "10.0.0.5"
        req.headers = {"user-agent": "x" * 1024}
        _, ua = request_context(req)
        assert ua is not None and len(ua) == 512


# ---------------------------------------------------------------------------
# record_event
# ---------------------------------------------------------------------------


class TestRecordEvent:
    def test_none_session_is_noop(self) -> None:
        assert (
            record_event(
                None,
                event_type=EVENT_AUTH_LOGIN,
                action="login",
                outcome=OUTCOME_SUCCESS,
            )
            is None
        )

    def test_writes_audit_row_with_all_fields(self, db: _Recorder) -> None:
        uid = uuid.uuid4()
        row = record_event(
            db,
            event_type=EVENT_AUTH_LOGIN,
            action="login",
            outcome=OUTCOME_SUCCESS,
            user_id=uid,
            actor_email="a@example.com",
            actor_role="admin",
            target_type="anomaly",
            target_id="abc-123",
            ip_address="10.0.0.5",
            user_agent="pytest/1.0",
            meta={"k": "v"},
        )
        assert isinstance(row, AuditLogRow)
        assert db.added == [row]
        assert row.event_type == EVENT_AUTH_LOGIN
        assert row.action == "login"
        assert row.outcome == OUTCOME_SUCCESS
        assert row.user_id == uid
        assert row.actor_email == "a@example.com"
        assert row.actor_role == "admin"
        assert row.target_type == "anomaly"
        assert row.target_id == "abc-123"
        assert row.ip_address == "10.0.0.5"
        assert row.user_agent == "pytest/1.0"
        assert row.meta == {"k": "v"}

    def test_autocommit_commits(self, db: _Recorder) -> None:
        record_event(
            db,
            event_type=EVENT_AUTH_LOGIN,
            action="login",
            outcome=OUTCOME_FAILURE,
            autocommit=True,
        )
        assert db.commits == 1

    def test_no_autocommit_leaves_caller_in_charge(self, db: _Recorder) -> None:
        record_event(
            db,
            event_type=EVENT_AUTH_LOGIN,
            action="login",
            outcome=OUTCOME_SUCCESS,
        )
        assert db.commits == 0

    def test_swallows_exceptions(self) -> None:
        bad = MagicMock()
        bad.add.side_effect = RuntimeError("boom")
        # Must not propagate; returns None and logs.
        assert (
            record_event(
                bad,
                event_type=EVENT_AUTH_LOGIN,
                action="login",
                outcome=OUTCOME_SUCCESS,
            )
            is None
        )

    def test_autocommit_failure_triggers_rollback(self) -> None:
        bad = MagicMock()
        bad.add.side_effect = RuntimeError("boom")
        record_event(
            bad,
            event_type=EVENT_AUTH_LOGIN,
            action="login",
            outcome=OUTCOME_FAILURE,
            autocommit=True,
        )
        bad.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


class TestLoginHelpers:
    def test_record_login_success_sets_fields(self, db: _Recorder) -> None:
        uid = uuid.uuid4()
        row = record_login_success(
            db,
            user_id=uid,
            email="user@example.com",
            role="analyst",
            ip_address="1.2.3.4",
            user_agent="ua",
        )
        assert isinstance(row, AuditLogRow)
        assert row.event_type == EVENT_AUTH_LOGIN
        assert row.outcome == OUTCOME_SUCCESS
        assert row.user_id == uid
        assert row.actor_email == "user@example.com"
        assert row.actor_role == "analyst"
        assert row.ip_address == "1.2.3.4"
        # success path defers commit to caller
        assert db.commits == 0

    def test_record_login_failure_unknown_user_has_null_user_id(
        self, db: _Recorder
    ) -> None:
        row = record_login_failure(
            db,
            attempted_email="nope@example.com",
            reason="unknown_or_inactive_user",
        )
        assert isinstance(row, AuditLogRow)
        assert row.outcome == OUTCOME_FAILURE
        assert row.user_id is None
        assert row.actor_email == "nope@example.com"
        assert row.meta == {"reason": "unknown_or_inactive_user"}
        # failure path autocommits so the row survives the upcoming raise
        assert db.commits == 1

    def test_record_login_failure_known_user_records_id(self, db: _Recorder) -> None:
        uid = uuid.uuid4()
        row = record_login_failure(
            db,
            attempted_email="user@example.com",
            reason="wrong_password",
            user_id=uid,
            role="admin",
        )
        assert row is not None
        assert row.user_id == uid
        assert row.actor_role == "admin"
        assert row.meta == {"reason": "wrong_password"}


class TestAdminActionHelper:
    def test_admin_action_uses_actor_identity(self, db: _Recorder) -> None:
        actor = CurrentUser(
            user_id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000099"),
            email="admin@example.com",
            role="admin",
        )
        row = record_admin_action(
            db,
            event_type="anomaly.status_update",
            action="status_update",
            actor=actor,
            target_type="anomaly",
            target_id="anom-1",
            meta={"new_status": "resolved"},
        )
        assert row is not None
        assert row.user_id == actor.user_id
        assert row.actor_email == actor.email
        assert row.actor_role == "admin"
        assert row.target_type == "anomaly"
        assert row.target_id == "anom-1"
        assert row.outcome == OUTCOME_SUCCESS
        assert row.meta == {"new_status": "resolved"}


# Verify the recorder package re-exports stay aligned with recorder.py
def test_module_reexports_match() -> None:
    import app.audit as pkg

    for name in (
        "EVENT_AUTH_LOGIN",
        "EVENT_INGEST_EVENT",
        "EVENT_ANOMALY_STATUS_UPDATE",
        "OUTCOME_SUCCESS",
        "OUTCOME_FAILURE",
        "record_event",
        "record_login_success",
        "record_login_failure",
        "record_admin_action",
        "request_context",
    ):
        assert getattr(pkg, name) is getattr(recorder, name)
