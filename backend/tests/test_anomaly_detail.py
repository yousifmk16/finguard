"""Unit tests for API-02: GET /api/v1/anomalies/{anomaly_id}"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_AID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@dataclass
class _FakeRow:
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


def _fake_row(**overrides) -> _FakeRow:
    defaults = dict(
        anomaly_id=_AID,
        account_id="acct-001",
        service="BigQuery",
        region="us-central1",
        bucket=_NOW,
        anomaly_score=Decimal("0.800000"),
        severity="high",
        status="open",
        detected_at=_NOW,
    )
    defaults.update(overrides)
    return _FakeRow(**defaults)


def _db_returning(row):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = row
    return db


# ---------------------------------------------------------------------------
# No DB
# ---------------------------------------------------------------------------

class TestAnomalyDetailNoDb:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_503(self):
        r = client.get(f"/api/v1/anomalies/{_AID}")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestAnomalyDetailFound:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: _db_returning(_fake_row())

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_200(self):
        assert client.get(f"/api/v1/anomalies/{_AID}").status_code == 200

    def test_fields_correct(self):
        body = client.get(f"/api/v1/anomalies/{_AID}").json()
        assert body["anomaly_id"] == str(_AID)
        assert body["account_id"] == "acct-001"
        assert body["severity"] == "high"
        assert body["status"] == "open"

    def test_score_is_float(self):
        body = client.get(f"/api/v1/anomalies/{_AID}").json()
        assert isinstance(body["anomaly_score"], float)


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

class TestAnomalyDetailNotFound:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: _db_returning(None)

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_404(self):
        assert client.get(f"/api/v1/anomalies/{_AID}").status_code == 404

    def test_error_detail_present(self):
        body = client.get(f"/api/v1/anomalies/{_AID}").json()
        assert "detail" in body


# ---------------------------------------------------------------------------
# Invalid UUID path param
# ---------------------------------------------------------------------------

def test_invalid_uuid_rejected():
    r = client.get("/api/v1/anomalies/not-a-uuid")
    assert r.status_code == 422
