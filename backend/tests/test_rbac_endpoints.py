"""SEC-03: integration tests for role-protected endpoints.

Verifies the RBAC matrix wired in app/api/{ingestion,anomalies,alerts,kpi}.py:

    POST   /api/v1/events                       admin only
    GET    /api/v1/anomalies                    analyst or admin
    GET    /api/v1/anomalies/{id}               analyst or admin
    PATCH  /api/v1/anomalies/{id}/status        analyst or admin
    GET    /api/v1/alerts                       analyst or admin
    GET    /api/v1/kpi/summary                  analyst or admin

For each endpoint we assert:
    * 401 when no bearer token is presented (autouse admin override cleared).
    * 403 when an authenticated user lacks the required role.
    * 2xx when the right role is presented.

Public endpoints (login, app health, detection health/metrics) are also
spot-checked to confirm they remain reachable without auth.
"""

from __future__ import annotations

import uuid

import pytest
from app.api.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.schemas.auth import CurrentUser
from fastapi.testclient import TestClient

client = TestClient(app)

_ANOMALY_ID = uuid.uuid4()


def _as(role: str) -> CurrentUser:
    return CurrentUser(
        user_id=uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003"),
        email=f"{role}@example.com",
        role=role,
    )


@pytest.fixture
def no_auth():
    """Strip the autouse admin override so requests look anonymous."""
    app.dependency_overrides.pop(get_current_user, None)
    yield
    # The autouse fixture's teardown will run after this; nothing to restore.


@pytest.fixture
def as_analyst():
    app.dependency_overrides[get_current_user] = lambda: _as("analyst")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def as_admin():
    app.dependency_overrides[get_current_user] = lambda: _as("admin")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def no_db():
    app.dependency_overrides[get_db] = lambda: None
    yield
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 401 — every protected endpoint rejects unauthenticated requests
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


@pytest.mark.usefixtures("no_auth", "no_db")
class TestUnauthenticated:
    def test_post_events_returns_401(self):
        r = client.post("/api/v1/events", json=_VALID_EVENT)
        assert r.status_code == 401

    def test_list_anomalies_returns_401(self):
        assert client.get("/api/v1/anomalies").status_code == 401

    def test_get_anomaly_returns_401(self):
        assert client.get(f"/api/v1/anomalies/{_ANOMALY_ID}").status_code == 401

    def test_patch_anomaly_status_returns_401(self):
        r = client.patch(
            f"/api/v1/anomalies/{_ANOMALY_ID}/status",
            json={"status": "acknowledged"},
        )
        assert r.status_code == 401

    def test_list_alerts_returns_401(self):
        assert client.get("/api/v1/alerts").status_code == 401

    def test_kpi_summary_returns_401(self):
        assert client.get("/api/v1/kpi/summary").status_code == 401


# ---------------------------------------------------------------------------
# 403 — analyst is forbidden from admin-only ingestion
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("as_analyst", "no_db")
class TestAnalystForbiddenFromAdminOnly:
    def test_post_events_returns_403_for_analyst(self):
        r = client.post("/api/v1/events", json=_VALID_EVENT)
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden: requires role admin"


# ---------------------------------------------------------------------------
# 2xx — analyst can hit every analyst-or-admin endpoint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("as_analyst", "no_db")
class TestAnalystAccess:
    def test_list_anomalies_ok(self):
        # no_db short-circuits to an empty list rather than 503
        assert client.get("/api/v1/anomalies").status_code == 200

    def test_get_anomaly_returns_503_when_no_db(self):
        # Auth passes, then the endpoint reports DB unavailability — the
        # important thing is we got past the RBAC gate (not 401/403).
        r = client.get(f"/api/v1/anomalies/{_ANOMALY_ID}")
        assert r.status_code == 503

    def test_patch_anomaly_status_returns_503_when_no_db(self):
        r = client.patch(
            f"/api/v1/anomalies/{_ANOMALY_ID}/status",
            json={"status": "acknowledged"},
        )
        assert r.status_code == 503

    def test_list_alerts_ok(self):
        assert client.get("/api/v1/alerts").status_code == 200

    def test_kpi_summary_ok(self):
        assert client.get("/api/v1/kpi/summary").status_code == 200


# ---------------------------------------------------------------------------
# 2xx — admin can hit ingestion (and everything else, by superset)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("as_admin", "no_db")
class TestAdminAccess:
    def test_post_events_accepted(self):
        r = client.post("/api/v1/events", json={**_VALID_EVENT, "event_id": str(uuid.uuid4())})
        assert r.status_code == 202

    def test_list_anomalies_ok(self):
        assert client.get("/api/v1/anomalies").status_code == 200

    def test_list_alerts_ok(self):
        assert client.get("/api/v1/alerts").status_code == 200

    def test_kpi_summary_ok(self):
        assert client.get("/api/v1/kpi/summary").status_code == 200


# ---------------------------------------------------------------------------
# Public endpoints stay public — no auth needed
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("no_auth")
class TestPublicEndpoints:
    def test_app_health_open(self):
        assert client.get("/health").status_code == 200

    def test_detection_health_open(self):
        # Returns 200 even with no DB configured — see DET-03.
        app.dependency_overrides[get_db] = lambda: None
        try:
            assert client.get("/api/v1/detection/health").status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_detection_metrics_open(self):
        assert client.get("/api/v1/detection/metrics").status_code == 200

    def test_login_endpoint_reachable_without_auth(self):
        # Reaches the handler (returns 503 because no DB) rather than 401.
        app.dependency_overrides[get_db] = lambda: None
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": "x@example.com", "password": "y"},
            )
            assert r.status_code == 503
        finally:
            app.dependency_overrides.pop(get_db, None)
