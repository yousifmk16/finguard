"""Unit tests for UI-06: GET /api/v1/kpi/trend"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)


def _mock_db_with_rows(rows: list[tuple[date, int]]) -> MagicMock:
    """Build a mock session whose execute() returns one rowset for kpi_trend."""
    result = MagicMock()
    result.all.return_value = rows
    db = MagicMock()
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# No DB
# ---------------------------------------------------------------------------


class TestTrendNoDb:
    def setup_method(self) -> None:
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_returns_200(self) -> None:
        assert client.get("/api/v1/kpi/trend").status_code == 200

    def test_default_days_echoed(self) -> None:
        body = client.get("/api/v1/kpi/trend").json()
        assert body["days"] == 14
        assert body["points"] == []

    def test_custom_days_echoed(self) -> None:
        body = client.get("/api/v1/kpi/trend?days=30").json()
        assert body["days"] == 30


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestTrendValidation:
    def setup_method(self) -> None:
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_zero_days_rejected(self) -> None:
        assert client.get("/api/v1/kpi/trend?days=0").status_code == 422

    def test_over_max_rejected(self) -> None:
        assert client.get("/api/v1/kpi/trend?days=91").status_code == 422

    def test_max_accepted(self) -> None:
        assert client.get("/api/v1/kpi/trend?days=90").status_code == 200


# ---------------------------------------------------------------------------
# Happy path with mock DB
# ---------------------------------------------------------------------------


class TestTrendWithDb:
    def _use(self, db: MagicMock) -> None:
        app.dependency_overrides[get_db] = lambda: db

    def teardown_method(self) -> None:
        app.dependency_overrides.pop(get_db, None)

    def test_returns_one_point_per_day(self) -> None:
        self._use(_mock_db_with_rows([]))
        body = client.get("/api/v1/kpi/trend?days=7").json()
        assert len(body["points"]) == 7

    def test_zero_filled_when_no_data(self) -> None:
        self._use(_mock_db_with_rows([]))
        body = client.get("/api/v1/kpi/trend?days=3").json()
        assert all(p["count"] == 0 for p in body["points"])

    def test_points_in_chronological_order(self) -> None:
        self._use(_mock_db_with_rows([]))
        body = client.get("/api/v1/kpi/trend?days=5").json()
        days = [p["day"] for p in body["points"]]
        assert days == sorted(days)

    def test_db_counts_merged_into_response(self) -> None:
        # Use the same UTC "today" as the repo to keep the test deterministic
        # across local timezones.
        today = datetime.now(tz=UTC).date()
        rows = [(today - timedelta(days=1), 4), (today, 7)]
        self._use(_mock_db_with_rows(rows))
        body = client.get("/api/v1/kpi/trend?days=3").json()
        last_two = {p["day"]: p["count"] for p in body["points"][-2:]}
        assert last_two[(today - timedelta(days=1)).isoformat()] == 4
        assert last_two[today.isoformat()] == 7
