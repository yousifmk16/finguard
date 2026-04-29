"""
Unit tests for API-01: GET /api/v1/anomalies

No live DB required — the session dependency is overridden with mock objects.
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

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


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
    score_breakdown: dict | None = None


def _fake_row(**overrides) -> _FakeAnomalyRow:
    defaults = dict(
        anomaly_id=uuid.uuid4(),
        account_id="acct-001",
        service="BigQuery",
        region="us-central1",
        bucket=_NOW,
        anomaly_score=Decimal("0.750000"),
        severity="high",
        status="open",
        detected_at=_NOW,
        score_breakdown=None,
    )
    defaults.update(overrides)
    return _FakeAnomalyRow(**defaults)


def _mock_db(count: int = 0, rows: list | None = None) -> MagicMock:
    """
    Build a mock Session whose execute() returns count then rows on successive
    calls, matching list_anomalies' (COUNT query, rows query) call sequence.
    """
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
# No DB configured
# ---------------------------------------------------------------------------


class TestAnomalyListNoDb:
    def setup_method(self) -> None:
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_returns_200(self) -> None:
        assert client.get("/api/v1/anomalies").status_code == 200

    def test_returns_empty_items(self) -> None:
        body = client.get("/api/v1/anomalies").json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["pages"] == 0

    def test_pagination_fields_echoed(self) -> None:
        body = client.get("/api/v1/anomalies?page=2&page_size=25").json()
        assert body["page"] == 2
        assert body["page_size"] == 25


# ---------------------------------------------------------------------------
# Happy path with mock DB
# ---------------------------------------------------------------------------


class TestAnomalyListWithDb:
    def _use(self, db: MagicMock) -> None:
        app.dependency_overrides[get_db] = lambda: db

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_single_row_returned(self) -> None:
        self._use(_mock_db(count=1, rows=[_fake_row()]))
        body = client.get("/api/v1/anomalies").json()
        assert len(body["items"]) == 1
        assert body["total"] == 1

    def test_item_fields_mapped_correctly(self) -> None:
        aid = uuid.uuid4()
        row = _fake_row(anomaly_id=aid, account_id="acct-99", severity="low", status="resolved")
        self._use(_mock_db(count=1, rows=[row]))
        item = client.get("/api/v1/anomalies").json()["items"][0]
        assert item["anomaly_id"] == str(aid)
        assert item["account_id"] == "acct-99"
        assert item["severity"] == "low"
        assert item["status"] == "resolved"

    def test_anomaly_score_is_float(self) -> None:
        self._use(_mock_db(count=1, rows=[_fake_row(anomaly_score=Decimal("0.850000"))]))
        item = client.get("/api/v1/anomalies").json()["items"][0]
        assert item["anomaly_score"] == pytest.approx(0.85)

    def test_pages_calculated_correctly(self) -> None:
        self._use(_mock_db(count=105, rows=[]))
        body = client.get("/api/v1/anomalies?page_size=50").json()
        assert body["total"] == 105
        assert body["pages"] == 3  # ceil(105 / 50)

    def test_pages_exact_multiple(self) -> None:
        self._use(_mock_db(count=100, rows=[]))
        body = client.get("/api/v1/anomalies?page_size=50").json()
        assert body["pages"] == 2  # ceil(100 / 50)

    def test_pages_zero_when_empty(self) -> None:
        self._use(_mock_db(count=0, rows=[]))
        assert client.get("/api/v1/anomalies").json()["pages"] == 0

    def test_score_breakdown_null_by_default(self) -> None:
        self._use(_mock_db(count=1, rows=[_fake_row(score_breakdown=None)]))
        item = client.get("/api/v1/anomalies").json()["items"][0]
        assert item["score_breakdown"] is None

    def test_score_breakdown_included_when_present(self) -> None:
        bd = {"ts_signal": 0.8, "if_score": 0.7}
        self._use(_mock_db(count=1, rows=[_fake_row(score_breakdown=bd)]))
        item = client.get("/api/v1/anomalies").json()["items"][0]
        assert item["score_breakdown"] == bd

    def test_multiple_rows_returned_in_order(self) -> None:
        rows = [_fake_row(anomaly_id=uuid.uuid4()) for _ in range(3)]
        self._use(_mock_db(count=3, rows=rows))
        items = client.get("/api/v1/anomalies").json()["items"]
        assert len(items) == 3
        expected_ids = [str(r.anomaly_id) for r in rows]
        assert [i["anomaly_id"] for i in items] == expected_ids


# ---------------------------------------------------------------------------
# Query parameter validation
# ---------------------------------------------------------------------------


class TestAnomalyListQueryValidation:
    def setup_method(self) -> None:
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_page_zero_rejected(self) -> None:
        assert client.get("/api/v1/anomalies?page=0").status_code == 422

    def test_page_size_zero_rejected(self) -> None:
        assert client.get("/api/v1/anomalies?page_size=0").status_code == 422

    def test_page_size_over_max_rejected(self) -> None:
        assert client.get("/api/v1/anomalies?page_size=201").status_code == 422

    def test_page_size_at_max_accepted(self) -> None:
        assert client.get("/api/v1/anomalies?page_size=200").status_code == 200

    def test_invalid_severity_rejected(self) -> None:
        assert client.get("/api/v1/anomalies?severity=critical").status_code == 422

    def test_invalid_status_rejected(self) -> None:
        assert client.get("/api/v1/anomalies?status=deleted").status_code == 422

    def test_all_valid_severities_accepted(self) -> None:
        for sev in ("none", "low", "medium", "high"):
            r = client.get(f"/api/v1/anomalies?severity={sev}")
            assert r.status_code == 200, f"severity={sev!r} unexpectedly rejected"

    def test_all_valid_statuses_accepted(self) -> None:
        for st in ("open", "acknowledged", "resolved", "suppressed"):
            r = client.get(f"/api/v1/anomalies?status={st}")
            assert r.status_code == 200, f"status={st!r} unexpectedly rejected"

    def test_default_page_and_page_size(self) -> None:
        body = client.get("/api/v1/anomalies").json()
        assert body["page"] == 1
        assert body["page_size"] == 50

    def test_all_filters_accepted_together(self) -> None:
        r = client.get(
            "/api/v1/anomalies"
            "?account_id=acct-1&service=BigQuery&region=us-central1"
            "&severity=high&status=open"
            "&from_bucket=2026-01-01T00:00:00Z"
            "&to_bucket=2026-12-31T23:59:59Z"
            "&page=2&page_size=10"
        )
        assert r.status_code == 200
