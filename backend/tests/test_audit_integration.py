"""SEC-04: integration tests verifying audit rows are written by the
auth and admin-action endpoints.

We instrument ``Session.add`` via a recording stub so we can assert what
audit rows the handler emits without standing up a Postgres database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from app.api.auth import get_current_user
from app.core.security import hash_password
from app.db.models.audit_log import AuditLogRow
from app.db.session import get_db
from app.main import app
from app.schemas.auth import CurrentUser
from fastapi.testclient import TestClient

client = TestClient(app)

_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000010")
_ANOMALY_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000010")


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeUser:
    user_id: uuid.UUID
    email: str
    hashed_password: str
    role: str
    is_active: bool = True


@dataclass
class _FakeAnomaly:
    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    bucket: datetime
    anomaly_score: Decimal
    severity: str
    status: str
    detected_at: datetime
    score_breakdown: dict | None = None


class _RecordingDB:
    """Session stand-in that captures add()/commit() calls.

    ``scalar`` is the value returned for repository lookups
    (``execute(...).scalar_one_or_none()``). Multiple lookups in a single
    request all see the same value — sufficient for these endpoints.
    """

    def __init__(self, scalar: object = None) -> None:
        self.added: list[object] = []
        self.commits = 0
        self._scalar = scalar

    def add(self, row: object) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def refresh(self, row: object) -> None:  # noqa: ARG002
        pass

    def execute(self, _stmt):
        m = MagicMock()
        m.scalar_one_or_none.return_value = self._scalar
        return m

    def audit_rows(self) -> list[AuditLogRow]:
        return [r for r in self.added if isinstance(r, AuditLogRow)]


def _override_db(db: _RecordingDB) -> None:
    app.dependency_overrides[get_db] = lambda: db


def _clear_db_override() -> None:
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Auth login — success and failure paths both audit
# ---------------------------------------------------------------------------


class TestAuthLoginAuditing:
    """The autouse admin override resolves *get_current_user*, but login
    runs before that dependency — so login tests work normally."""

    def teardown_method(self) -> None:
        _clear_db_override()

    def test_successful_login_records_success_row(self) -> None:
        user = _FakeUser(
            user_id=_USER_ID,
            email="ok@example.com",
            hashed_password=hash_password("hunter2"),
            role="admin",
        )
        db = _RecordingDB(scalar=user)
        _override_db(db)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "ok@example.com", "password": "hunter2"},
        )
        assert r.status_code == 200

        rows = db.audit_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == "auth.login"
        assert row.outcome == "success"
        assert row.user_id == _USER_ID
        assert row.actor_email == "ok@example.com"
        assert row.actor_role == "admin"

    def test_unknown_email_records_failure_with_null_user_id(self) -> None:
        db = _RecordingDB(scalar=None)  # user lookup returns None
        _override_db(db)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "x"},
        )
        assert r.status_code == 401

        rows = db.audit_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.outcome == "failure"
        assert row.user_id is None
        assert row.actor_email == "missing@example.com"
        assert row.meta == {"reason": "unknown_or_inactive_user"}
        # autocommit ensures the row survives the 401 raise
        assert db.commits == 1

    def test_wrong_password_records_failure_with_user_id(self) -> None:
        user = _FakeUser(
            user_id=_USER_ID,
            email="user@example.com",
            hashed_password=hash_password("right"),
            role="analyst",
        )
        db = _RecordingDB(scalar=user)
        _override_db(db)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )
        assert r.status_code == 401

        rows = db.audit_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.outcome == "failure"
        assert row.user_id == _USER_ID
        assert row.actor_email == "user@example.com"
        assert row.actor_role == "analyst"
        assert row.meta == {"reason": "wrong_password"}

    def test_inactive_user_records_failure(self) -> None:
        user = _FakeUser(
            user_id=_USER_ID,
            email="user@example.com",
            hashed_password=hash_password("ok"),
            role="analyst",
            is_active=False,
        )
        db = _RecordingDB(scalar=user)
        _override_db(db)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "ok"},
        )
        assert r.status_code == 401

        rows = db.audit_rows()
        assert len(rows) == 1
        # inactive users are still identifiable by user_id
        assert rows[0].user_id == _USER_ID
        assert rows[0].meta == {"reason": "unknown_or_inactive_user"}

    def test_no_db_does_not_audit(self) -> None:
        app.dependency_overrides[get_db] = lambda: None
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "y"},
        )
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Ingest event — admin action audit
# ---------------------------------------------------------------------------


_VALID_EVENT = {
    "timestamp": "2026-01-01T00:00:00Z",
    "provider": "gcp",
    "account_id": "acct-001",
    "service": "compute",
    "region": "us-central1",
    "cost_amount": 12.50,
    "usage_amount": 100.0,
    "usage_unit": "core-hours",
    "tags": {"env": "prod"},
    "source_type": "synthetic",
}


class TestIngestAuditing:
    """Conftest's autouse admin override supplies the actor identity."""

    def teardown_method(self) -> None:
        _clear_db_override()

    def test_successful_ingest_records_admin_action(self) -> None:
        db = _RecordingDB()
        _override_db(db)

        event_id = str(uuid.uuid4())
        r = client.post(
            "/api/v1/events",
            json={**_VALID_EVENT, "event_id": event_id},
        )
        assert r.status_code == 202

        rows = db.audit_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == "ingest.event"
        assert row.action == "ingest"
        assert row.outcome == "success"
        assert row.actor_role == "admin"
        assert row.target_type == "billing_event"
        assert row.target_id == event_id
        assert row.meta is not None
        assert row.meta["provider"] == "gcp"
        assert row.meta["account_id"] == "acct-001"

    def test_no_db_does_not_audit(self) -> None:
        app.dependency_overrides[get_db] = lambda: None
        r = client.post(
            "/api/v1/events",
            json={**_VALID_EVENT, "event_id": str(uuid.uuid4())},
        )
        assert r.status_code == 202


# ---------------------------------------------------------------------------
# Anomaly status update — privileged operator action audit
# ---------------------------------------------------------------------------


class TestAnomalyStatusUpdateAuditing:
    def teardown_method(self) -> None:
        _clear_db_override()

    def test_status_update_records_audit(self) -> None:
        anomaly = _FakeAnomaly(
            anomaly_id=_ANOMALY_ID,
            account_id="acct-001",
            service="Compute",
            region="us-east1",
            bucket=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            anomaly_score=Decimal("0.7"),
            severity="medium",
            status="open",
            detected_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        )
        db = _RecordingDB(scalar=anomaly)
        _override_db(db)

        r = client.patch(
            f"/api/v1/anomalies/{_ANOMALY_ID}/status",
            json={"status": "resolved"},
        )
        assert r.status_code == 200

        rows = db.audit_rows()
        assert len(rows) == 1
        row = rows[0]
        assert row.event_type == "anomaly.status_update"
        assert row.action == "status_update"
        assert row.outcome == "success"
        assert row.target_type == "anomaly"
        assert row.target_id == str(_ANOMALY_ID)
        assert row.actor_role == "admin"
        assert row.meta == {"new_status": "resolved"}

    def test_not_found_does_not_audit(self) -> None:
        db = _RecordingDB(scalar=None)  # repo returns None for the anomaly
        _override_db(db)

        r = client.patch(
            f"/api/v1/anomalies/{_ANOMALY_ID}/status",
            json={"status": "resolved"},
        )
        assert r.status_code == 404
        assert db.audit_rows() == []


# ---------------------------------------------------------------------------
# Auth failures upstream of the handler should not trigger audit rows
# ---------------------------------------------------------------------------


@pytest.fixture
def no_auth():
    """Strip the autouse admin override so requests look anonymous."""
    app.dependency_overrides.pop(get_current_user, None)
    yield


class TestAuthFailuresDontAuditAdminEndpoints:
    def teardown_method(self) -> None:
        _clear_db_override()

    @pytest.mark.usefixtures("no_auth")
    def test_unauthenticated_ingest_records_no_audit(self) -> None:
        db = _RecordingDB()
        _override_db(db)
        r = client.post("/api/v1/events", json=_VALID_EVENT)
        assert r.status_code == 401
        assert db.audit_rows() == []

    def test_analyst_blocked_from_ingest_records_no_audit(self) -> None:
        analyst = CurrentUser(
            user_id=uuid.uuid4(),
            email="analyst@example.com",
            role="analyst",
        )
        app.dependency_overrides[get_current_user] = lambda: analyst
        try:
            db = _RecordingDB()
            _override_db(db)
            r = client.post("/api/v1/events", json=_VALID_EVENT)
            assert r.status_code == 403
            assert db.audit_rows() == []
        finally:
            app.dependency_overrides.pop(get_current_user, None)
