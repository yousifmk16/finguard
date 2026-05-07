"""
OPS-01: Finalized service health check tests.

Covers:
  1. Happy path — no DB configured (dev environment).
  2. DB configured and reachable.
  3. DB configured but unreachable (connection error) → "degraded".
  4. Response shape: required keys present and typed correctly.
  5. HTTP status codes: 200 for ok/degraded, 503 for unhealthy.
  6. Ingestion store stats reflected in the response.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.idempotency import store as idempotency_store
from app.db.session import get_db
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_idempotency_store():
    idempotency_store._seen.clear()
    yield
    idempotency_store._seen.clear()


def _db_ok():
    db = MagicMock()
    return db


def _db_error():
    db = MagicMock()
    db.execute.side_effect = OperationalError("conn refused", None, None)
    return db


# ---------------------------------------------------------------------------
# 1. No DATABASE_URL configured (default dev setup)
# ---------------------------------------------------------------------------


def test_health_no_db_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_no_db_status_ok():
    response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"


def test_health_no_db_component_not_configured():
    response = client.get("/health")
    assert response.json()["components"]["db"]["status"] == "not_configured"


# ---------------------------------------------------------------------------
# 2. DB configured and reachable
# ---------------------------------------------------------------------------


def test_health_db_ok_returns_200():
    app.dependency_overrides[get_db] = lambda: _db_ok()
    try:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["components"]["db"]["status"] == "ok"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_health_db_ok_status_ok():
    app.dependency_overrides[get_db] = lambda: _db_ok()
    try:
        body = client.get("/health").json()
        assert body["status"] == "ok"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 3. DB configured but unreachable → degraded
# ---------------------------------------------------------------------------


def test_health_db_error_returns_200_degraded():
    app.dependency_overrides[get_db] = lambda: _db_error()
    try:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["components"]["db"]["status"] == "error"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 4. Response shape
# ---------------------------------------------------------------------------


def test_health_response_has_required_top_level_keys():
    body = client.get("/health").json()
    for key in ("status", "version", "timestamp", "uptime_seconds", "components"):
        assert key in body, f"missing key: {key}"


def test_health_response_has_required_component_keys():
    body = client.get("/health").json()
    for component in ("app", "db", "ingestion"):
        assert component in body["components"], f"missing component: {component}"


def test_health_app_component_always_ok():
    body = client.get("/health").json()
    assert body["components"]["app"]["status"] == "ok"


def test_health_uptime_is_non_negative_float():
    body = client.get("/health").json()
    assert isinstance(body["uptime_seconds"], float)
    assert body["uptime_seconds"] >= 0.0


def test_health_version_is_string():
    body = client.get("/health").json()
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0


def test_health_timestamp_is_iso_string():
    from datetime import datetime, timezone

    body = client.get("/health").json()
    ts = body["timestamp"]
    assert isinstance(ts, str)
    # Must parse without error
    datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# 5. Ingestion store stats reflected
# ---------------------------------------------------------------------------


def test_health_ingestion_store_size_zero_when_empty():
    body = client.get("/health").json()
    assert body["components"]["ingestion"]["store_size"] == 0


def test_health_ingestion_store_size_reflects_registrations():
    for _ in range(5):
        idempotency_store.register(uuid.uuid4())

    body = client.get("/health").json()
    assert body["components"]["ingestion"]["store_size"] == 5


def test_health_ingestion_store_capacity_present():
    body = client.get("/health").json()
    assert body["components"]["ingestion"]["store_capacity"] == 100_000


# ---------------------------------------------------------------------------
# 6. HTTP 503 for unhealthy — patch _aggregate_status directly
# ---------------------------------------------------------------------------


def test_health_returns_503_when_unhealthy():
    with patch("app.api.health._aggregate_status", return_value="unhealthy"):
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# 7. Unauthenticated access allowed
# ---------------------------------------------------------------------------


def test_health_accessible_without_auth():
    """Health endpoint must be reachable before any auth header is present."""
    app.dependency_overrides.pop(get_db, None)  # ensure no leftover overrides
    response = TestClient(app).get("/health", headers={})
    assert response.status_code in (200, 503)
