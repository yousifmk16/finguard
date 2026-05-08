"""
REL-04: Final smoke tests — fast sanity checks on the critical path.

Run with:  pytest -m smoke -v
No live DB or external services required.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)

_VALID_EVENT = {
    "timestamp": "2026-01-01T00:00:00Z",
    "provider": "aws",
    "account_id": "acct-smoke-001",
    "service": "EC2",
    "region": "us-east-1",
    "cost_amount": 10.0,
    "usage_amount": 80.0,
    "usage_unit": "Hrs",
    "tags": {"env": "prod"},
    "source_type": "synthetic",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeAnomalyRow:
    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    bucket: datetime
    anomaly_score: Decimal
    severity: str
    status: str
    detected_at: datetime


@dataclass
class _FakeAlertRow:
    alert_id: uuid.UUID
    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    severity: str
    channel: str
    status: str
    dedup_key: str
    created_at: datetime
    sent_at: datetime | None = None
    error_detail: str | None = None


def _mock_db_empty() -> MagicMock:
    db = MagicMock()
    db.execute.return_value.scalar_one.return_value = 0
    db.execute.return_value.scalar_one_or_none.return_value = None
    db.execute.return_value.scalars.return_value.all.return_value = []
    db.execute.return_value.mappings.return_value.all.return_value = []
    return db


def _mock_db_one_anomaly() -> MagicMock:
    now = datetime(2026, 4, 1, 2, 0, 0, tzinfo=timezone.utc)
    row = _FakeAnomalyRow(
        anomaly_id=uuid.UUID("cccccccc-0001-0001-0001-cccccccccccc"),
        account_id="acct-002",
        service="VirtualMachines",
        region="eastus",
        bucket=now,
        anomaly_score=Decimal("0.921000"),
        severity="critical",
        status="open",
        detected_at=now,
    )
    db = MagicMock()
    db.execute.return_value.scalar_one.return_value = 1
    db.execute.return_value.scalars.return_value.all.return_value = [row]
    db.execute.return_value.mappings.return_value.all.return_value = []
    return db


def _mock_db_one_alert() -> MagicMock:
    now = datetime(2026, 4, 1, 2, 10, 0, tzinfo=timezone.utc)
    row = _FakeAlertRow(
        alert_id=uuid.UUID("dddddddd-0001-0001-0001-dddddddddddd"),
        anomaly_id=uuid.UUID("cccccccc-0001-0001-0001-cccccccccccc"),
        account_id="acct-002",
        service="VirtualMachines",
        region="eastus",
        severity="critical",
        channel="in_app",
        status="sent",
        dedup_key="acct-002:VirtualMachines:eastus:critical:2026-04-01T02",
        created_at=now,
        sent_at=now,
    )
    db = MagicMock()
    db.execute.return_value.scalar_one.return_value = 1
    db.execute.return_value.scalars.return_value.all.return_value = [row]
    return db


# ---------------------------------------------------------------------------
# SMK-01: Service health
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_health_200():
    r = client.get("/health")
    assert r.status_code == 200


@pytest.mark.smoke
def test_smoke_health_status_ok():
    r = client.get("/health")
    assert r.json()["status"] in ("ok", "degraded")


@pytest.mark.smoke
def test_smoke_health_has_version():
    r = client.get("/health")
    assert r.json().get("version")


# ---------------------------------------------------------------------------
# SMK-02: Event ingestion
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_ingest_accepted():
    r = client.post("/api/v1/events", json=_VALID_EVENT)
    assert r.status_code == 202


@pytest.mark.smoke
def test_smoke_ingest_returns_event_id():
    r = client.post("/api/v1/events", json=_VALID_EVENT)
    body = r.json()
    assert body["status"] == "accepted"
    assert uuid.UUID(body["event_id"])


@pytest.mark.smoke
def test_smoke_ingest_rejects_invalid_payload():
    r = client.post("/api/v1/events", json={"bad": "data"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# SMK-03: Anomaly list
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_anomaly_list_200():
    app.dependency_overrides[get_db] = lambda: _mock_db_empty()
    try:
        r = client.get("/api/v1/anomalies")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.smoke
def test_smoke_anomaly_list_returns_list():
    app.dependency_overrides[get_db] = lambda: _mock_db_one_anomaly()
    try:
        r = client.get("/api/v1/anomalies")
        body = r.json()
        assert isinstance(body.get("items", body), list)
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# SMK-04: Alert list
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_alert_list_200():
    app.dependency_overrides[get_db] = lambda: _mock_db_empty()
    try:
        r = client.get("/api/v1/alerts")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.smoke
def test_smoke_alert_list_returns_list():
    app.dependency_overrides[get_db] = lambda: _mock_db_one_alert()
    try:
        r = client.get("/api/v1/alerts")
        body = r.json()
        assert isinstance(body.get("items", body), list)
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# SMK-05: KPI summary
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_kpi_summary_200():
    app.dependency_overrides[get_db] = lambda: _mock_db_empty()
    try:
        r = client.get("/api/v1/kpi/summary")
        assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.smoke
def test_smoke_kpi_summary_has_total_anomalies():
    app.dependency_overrides[get_db] = lambda: _mock_db_empty()
    try:
        r = client.get("/api/v1/kpi/summary")
        assert "total_anomalies" in r.json()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# SMK-06: Auth — unauthenticated access blocked on protected routes
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_auth_login_bad_credentials_rejected():
    from app.db.session import get_db as _get_db

    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    app.dependency_overrides[_get_db] = lambda: db
    try:
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong"},
        )
        assert r.status_code in (401, 422)
    finally:
        app.dependency_overrides.pop(_get_db, None)


@pytest.mark.smoke
def test_smoke_protected_route_requires_auth():
    from app.api.auth import get_current_user
    from fastapi import HTTPException

    app.dependency_overrides[get_current_user] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=401, detail="Not authenticated")
    )
    try:
        r = client.get("/api/v1/anomalies")
        assert r.status_code == 401
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# SMK-07: Prometheus metrics endpoint reachable
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_metrics_endpoint_200():
    r = client.get("/metrics")
    assert r.status_code == 200
