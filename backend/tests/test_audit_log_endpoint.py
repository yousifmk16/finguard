"""SEC-04: tests for GET /api/v1/audit/logs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from app.api.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.schemas.auth import CurrentUser
from fastapi.testclient import TestClient

client = TestClient(app)


def _row(
    *,
    event_type: str = "auth.login",
    action: str = "login",
    outcome: str = "success",
    user_id: uuid.UUID | None = None,
    actor_email: str | None = "u@example.com",
    actor_role: str | None = "admin",
    target_type: str | None = None,
    target_id: str | None = None,
    ip_address: str | None = "1.2.3.4",
    user_agent: str | None = "pytest",
    meta: dict | None = None,
    created_at: datetime | None = None,
):
    """Build a non-ORM stand-in for AuditLogRow that the response schema
    can validate via ``model_validate(from_attributes=True)``."""
    obj = MagicMock()
    obj.audit_id = uuid.uuid4()
    obj.event_type = event_type
    obj.action = action
    obj.outcome = outcome
    obj.user_id = user_id
    obj.actor_email = actor_email
    obj.actor_role = actor_role
    obj.target_type = target_type
    obj.target_id = target_id
    obj.ip_address = ip_address
    obj.user_agent = user_agent
    obj.meta = meta
    obj.created_at = created_at or datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    return obj


def _db_returning(rows: list, total: int):
    """Mock session whose list_logs equivalent yields ``(rows, total)``."""
    db = MagicMock()
    # AuditLogRepository.list_logs runs:
    #   total = session.execute(count_stmt).scalar_one()
    #   rows  = session.execute(rows_stmt).scalars().all()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = rows

    db.execute.side_effect = [count_result, rows_result]
    return db


@pytest.fixture
def as_admin():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=uuid.uuid4(),
        email="admin@example.com",
        role="admin",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def as_analyst():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=uuid.uuid4(),
        email="analyst@example.com",
        role="analyst",
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def no_auth():
    app.dependency_overrides.pop(get_current_user, None)
    yield


@pytest.fixture
def no_db():
    app.dependency_overrides[get_db] = lambda: None
    yield
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


class TestAuditEndpointRbac:
    @pytest.mark.usefixtures("no_auth", "no_db")
    def test_unauthenticated_returns_401(self) -> None:
        assert client.get("/api/v1/audit/logs").status_code == 401

    @pytest.mark.usefixtures("as_analyst", "no_db")
    def test_analyst_returns_403(self) -> None:
        r = client.get("/api/v1/audit/logs")
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden: requires role admin"

    @pytest.mark.usefixtures("as_admin", "no_db")
    def test_admin_with_no_db_returns_empty_page(self) -> None:
        r = client.get("/api/v1/audit/logs")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["pages"] == 0


# ---------------------------------------------------------------------------
# Listing + pagination
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("as_admin")
class TestAuditEndpointListing:
    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_returns_rows_and_pagination_metadata(self) -> None:
        rows = [_row(event_type="auth.login"), _row(event_type="ingest.event")]
        app.dependency_overrides[get_db] = lambda: _db_returning(rows, total=2)

        r = client.get("/api/v1/audit/logs")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["pages"] == 1
        assert len(body["items"]) == 2
        assert {item["event_type"] for item in body["items"]} == {
            "auth.login",
            "ingest.event",
        }

    def test_pagination_total_pages_computed(self) -> None:
        rows = [_row() for _ in range(50)]
        app.dependency_overrides[get_db] = lambda: _db_returning(rows, total=137)
        r = client.get("/api/v1/audit/logs?page_size=50")
        assert r.status_code == 200
        body = r.json()
        # ceil(137 / 50) == 3
        assert body["pages"] == 3
        assert body["page_size"] == 50
        assert body["total"] == 137

    def test_invalid_outcome_filter_rejected(self) -> None:
        app.dependency_overrides[get_db] = lambda: _db_returning([], 0)
        r = client.get("/api/v1/audit/logs?outcome=maybe")
        assert r.status_code == 422

    def test_filter_params_pass_through(self) -> None:
        # Smoke test: known event_type + outcome filter accepted, returns 200.
        app.dependency_overrides[get_db] = lambda: _db_returning([], 0)
        r = client.get(
            "/api/v1/audit/logs?event_type=auth.login&outcome=failure"
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0
