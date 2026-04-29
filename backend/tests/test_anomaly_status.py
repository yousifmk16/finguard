"""Unit tests for API-03: PATCH /api/v1/anomalies/{anomaly_id}/status"""

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
_AID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


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


def _fake_row(status: str = "open") -> _FakeRow:
    return _FakeRow(
        anomaly_id=_AID,
        account_id="acct-001",
        service="Compute",
        region="us-east1",
        bucket=_NOW,
        anomaly_score=Decimal("0.700000"),
        severity="medium",
        status=status,
        detected_at=_NOW,
    )


def _db_for_update(row):
    """Mock session where get_by_id returns `row` and commit/refresh are no-ops."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = row
    # refresh updates the row's status to reflect the committed value
    def _refresh(r):
        pass  # row was already mutated in-memory by update_status
    db.refresh.side_effect = _refresh
    return db


# ---------------------------------------------------------------------------
# No DB
# ---------------------------------------------------------------------------

class TestStatusUpdateNoDb:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_503(self):
        r = client.patch(f"/api/v1/anomalies/{_AID}/status", json={"status": "acknowledged"})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestStatusUpdateFound:
    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def _use(self, row):
        app.dependency_overrides[get_db] = lambda: _db_for_update(row)

    def test_returns_200(self):
        self._use(_fake_row("open"))
        r = client.patch(f"/api/v1/anomalies/{_AID}/status", json={"status": "acknowledged"})
        assert r.status_code == 200

    def test_response_contains_anomaly_id(self):
        self._use(_fake_row("open"))
        body = client.patch(
            f"/api/v1/anomalies/{_AID}/status", json={"status": "resolved"}
        ).json()
        assert body["anomaly_id"] == str(_AID)

    def test_all_valid_statuses_accepted(self):
        for st in ("open", "acknowledged", "resolved", "suppressed"):
            self._use(_fake_row())
            r = client.patch(
                f"/api/v1/anomalies/{_AID}/status", json={"status": st}
            )
            assert r.status_code == 200, f"status={st!r} unexpectedly rejected"


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------

class TestStatusUpdateNotFound:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: _db_for_update(None)

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_404(self):
        r = client.patch(f"/api/v1/anomalies/{_AID}/status", json={"status": "resolved"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestStatusUpdateValidation:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_invalid_status_rejected(self):
        r = client.patch(f"/api/v1/anomalies/{_AID}/status", json={"status": "deleted"})
        assert r.status_code == 422

    def test_missing_body_rejected(self):
        r = client.patch(f"/api/v1/anomalies/{_AID}/status")
        assert r.status_code == 422

    def test_invalid_uuid_in_path_rejected(self):
        r = client.patch("/api/v1/anomalies/not-a-uuid/status", json={"status": "open"})
        assert r.status_code == 422
