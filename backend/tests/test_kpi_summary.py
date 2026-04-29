"""Unit tests for API-05: GET /api/v1/kpi/summary"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app

client = TestClient(app)

_EXPECTED_KEYS = {
    "total_anomalies",
    "open_count",
    "acknowledged_count",
    "resolved_count",
    "suppressed_count",
    "high_severity_count",
    "medium_severity_count",
    "low_severity_count",
    "anomalies_last_24h",
    "top_services",
    "top_accounts",
}


def _mock_db_for_kpi(
    total: int = 0,
    status_rows: list = None,
    severity_rows: list = None,
    last_24h: int = 0,
    top_services: list = None,
    top_accounts: list = None,
) -> MagicMock:
    """
    Build a mock session whose execute() returns the six results expected by
    AnomalyRepository.kpi_summary() in call order:
      1. total count
      2. status group-by
      3. severity group-by
      4. last-24h count
      5. top services
      6. top accounts
    """
    if status_rows is None:
        status_rows = []
    if severity_rows is None:
        severity_rows = []
    if top_services is None:
        top_services = []
    if top_accounts is None:
        top_accounts = []

    def _make(scalar_one=None, all_rows=None):
        r = MagicMock()
        r.scalar_one.return_value = scalar_one
        r.all.return_value = all_rows or []
        return r

    db = MagicMock()
    db.execute.side_effect = [
        _make(scalar_one=total),           # 1. total count
        _make(all_rows=status_rows),       # 2. status group-by
        _make(all_rows=severity_rows),     # 3. severity group-by
        _make(scalar_one=last_24h),        # 4. last 24h count
        _make(all_rows=top_services),      # 5. top services
        _make(all_rows=top_accounts),      # 6. top accounts
    ]
    return db


# ---------------------------------------------------------------------------
# No DB
# ---------------------------------------------------------------------------

class TestKpiNoDb:
    def setup_method(self):
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_returns_200(self):
        assert client.get("/api/v1/kpi/summary").status_code == 200

    def test_all_counts_zero(self):
        body = client.get("/api/v1/kpi/summary").json()
        for key in _EXPECTED_KEYS - {"top_services", "top_accounts"}:
            assert body[key] == 0, f"{key} should be 0 with no DB"

    def test_top_lists_empty(self):
        body = client.get("/api/v1/kpi/summary").json()
        assert body["top_services"] == []
        assert body["top_accounts"] == []

    def test_all_expected_keys_present(self):
        body = client.get("/api/v1/kpi/summary").json()
        assert _EXPECTED_KEYS.issubset(body.keys())


# ---------------------------------------------------------------------------
# Happy path with mock DB
# ---------------------------------------------------------------------------

class TestKpiWithDb:
    def _use(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_total_anomalies_returned(self):
        self._use(_mock_db_for_kpi(total=42))
        assert client.get("/api/v1/kpi/summary").json()["total_anomalies"] == 42

    def test_status_counts_mapped(self):
        self._use(
            _mock_db_for_kpi(
                total=10,
                status_rows=[("open", 6), ("resolved", 4)],
            )
        )
        body = client.get("/api/v1/kpi/summary").json()
        assert body["open_count"] == 6
        assert body["resolved_count"] == 4
        assert body["acknowledged_count"] == 0  # not in rows → defaults to 0

    def test_severity_counts_mapped(self):
        self._use(
            _mock_db_for_kpi(
                severity_rows=[("high", 3), ("medium", 5), ("low", 2)],
            )
        )
        body = client.get("/api/v1/kpi/summary").json()
        assert body["high_severity_count"] == 3
        assert body["medium_severity_count"] == 5
        assert body["low_severity_count"] == 2

    def test_last_24h_count(self):
        self._use(_mock_db_for_kpi(last_24h=7))
        assert client.get("/api/v1/kpi/summary").json()["anomalies_last_24h"] == 7

    def test_top_services_returned(self):
        self._use(
            _mock_db_for_kpi(
                top_services=[("BigQuery", 30), ("Compute", 15)],
            )
        )
        body = client.get("/api/v1/kpi/summary").json()
        assert body["top_services"] == [
            {"service": "BigQuery", "count": 30},
            {"service": "Compute", "count": 15},
        ]

    def test_top_accounts_returned(self):
        self._use(
            _mock_db_for_kpi(
                top_accounts=[("acct-001", 20), ("acct-002", 10)],
            )
        )
        body = client.get("/api/v1/kpi/summary").json()
        assert body["top_accounts"] == [
            {"account_id": "acct-001", "count": 20},
            {"account_id": "acct-002", "count": 10},
        ]
