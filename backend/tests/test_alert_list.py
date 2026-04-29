"""Unit tests for API-04: GET /api/v1/alerts"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


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


def _fake_alert(**overrides) -> _FakeAlertRow:
    defaults = dict(
        alert_id=uuid.uuid4(),
        anomaly_id=uuid.uuid4(),
        account_id="acct-001",
        service="BigQuery",
        region="us-central1",
        severity="high",
        channel="in_app",
        status="sent",
        dedup_key=f"acct-001:BigQuery:us-central1:{_NOW.isoformat()}:in_app",
        created_at=_NOW,
        sent_at=_NOW,
        error_detail=None,
    )
    defaults.update(overrides)
    return _FakeAlertRow(**defaults)


def _mock_db(count: int = 0, rows: list | None = None) -> MagicMock:
    if rows is None:
        rows = []
    count_result = MagicMock()
    count_result.scalar_one.return_value = count
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = rows
    db = MagicMock()
    db.execute.side_effect = [count_result, rows_result]
    return db


# ---------------------------------------------------------------------------
# No DB
# ---------------------------------------------------------------------------

class TestAlertListNoDb:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_200(self):
        assert client.get("/api/v1/alerts").status_code == 200

    def test_returns_empty_list(self):
        body = client.get("/api/v1/alerts").json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["pages"] == 0


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestAlertListWithDb:
    def _use(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_items(self):
        self._use(_mock_db(count=1, rows=[_fake_alert()]))
        body = client.get("/api/v1/alerts").json()
        assert len(body["items"]) == 1
        assert body["total"] == 1

    def test_item_fields_present(self):
        row = _fake_alert(channel="email", status="sent")
        self._use(_mock_db(count=1, rows=[row]))
        item = client.get("/api/v1/alerts").json()["items"][0]
        assert item["channel"] == "email"
        assert item["status"] == "sent"
        assert "dedup_key" in item

    def test_pages_calculated(self):
        self._use(_mock_db(count=75, rows=[]))
        body = client.get("/api/v1/alerts?page_size=50").json()
        assert body["pages"] == 2  # ceil(75/50)

    def test_sent_at_null_when_pending(self):
        row = _fake_alert(status="pending", sent_at=None)
        self._use(_mock_db(count=1, rows=[row]))
        item = client.get("/api/v1/alerts").json()["items"][0]
        assert item["sent_at"] is None


# ---------------------------------------------------------------------------
# Query parameter validation
# ---------------------------------------------------------------------------

class TestAlertListValidation:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_invalid_severity_rejected(self):
        assert client.get("/api/v1/alerts?severity=critical").status_code == 422

    def test_invalid_status_rejected(self):
        assert client.get("/api/v1/alerts?status=deleted").status_code == 422

    def test_invalid_channel_rejected(self):
        assert client.get("/api/v1/alerts?channel=sms").status_code == 422

    def test_page_zero_rejected(self):
        assert client.get("/api/v1/alerts?page=0").status_code == 422

    def test_page_size_over_max_rejected(self):
        assert client.get("/api/v1/alerts?page_size=201").status_code == 422

    def test_valid_channels_accepted(self):
        for ch in ("in_app", "email"):
            assert client.get(f"/api/v1/alerts?channel={ch}").status_code == 200

    def test_valid_statuses_accepted(self):
        for st in ("pending", "sent", "failed", "suppressed"):
            assert client.get(f"/api/v1/alerts?status={st}").status_code == 200

    def test_default_pagination(self):
        body = client.get("/api/v1/alerts").json()
        assert body["page"] == 1
        assert body["page_size"] == 50
