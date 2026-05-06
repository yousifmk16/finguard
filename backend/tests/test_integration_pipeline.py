"""
TST-05: End-to-end integration test for the ingest → detect → alert → UI pipeline.

Drives the real FastAPI stack — routing, RBAC autouse, request validation,
response model serialization, error handlers — against stateful in-memory
repositories. Verifies that data flows through every layer with the same
identifiers visible to the UI:

    [ingest event] → [detect anomaly]
                          ↓
            [GET /anomalies] → [GET /anomalies/{id}]
                          ↓
                [PATCH /anomalies/{id}/status]
                          ↓
            [emit alert] → [GET /alerts] → [GET /kpi/summary]

The fakes replace the SQLAlchemy repositories at module level via
``app.api.<module>._repo`` so we don't need a live Postgres for the
integration assertions. The actual route handlers, schemas, and HTTP
machinery all run unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import alerts as alerts_api
from app.api import anomalies as anomalies_api
from app.api import kpi as kpi_api
from app.db.session import get_db
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Stateful fake row types
# ---------------------------------------------------------------------------


@dataclass
class _AnomalyRow:
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


@dataclass
class _AlertRow:
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


# ---------------------------------------------------------------------------
# Fake repositories — only the methods the API endpoints actually call
# ---------------------------------------------------------------------------


@dataclass
class _FakeAnomalyRepo:
    """In-memory stand-in for AnomalyRepository.

    Implements just enough of the public surface for the anomaly + KPI API
    routes to behave identically to production for an integration test.
    """

    rows: list[_AnomalyRow] = field(default_factory=list)

    # ----- API-01 list -----
    def list_anomalies(
        self,
        session: Any,
        *,
        account_id: str | None = None,
        service: str | None = None,
        region: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        from_bucket: datetime | None = None,
        to_bucket: datetime | None = None,
        sort: str = "detected_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[_AnomalyRow], int]:
        filtered = self.rows
        if account_id is not None:
            filtered = [r for r in filtered if r.account_id == account_id]
        if service is not None:
            filtered = [r for r in filtered if r.service == service]
        if region is not None:
            filtered = [r for r in filtered if r.region == region]
        if severity is not None:
            filtered = [r for r in filtered if r.severity == severity]
        if status is not None:
            filtered = [r for r in filtered if r.status == status]
        if from_bucket is not None:
            filtered = [r for r in filtered if r.bucket >= from_bucket]
        if to_bucket is not None:
            filtered = [r for r in filtered if r.bucket <= to_bucket]

        sort_attr = sort if sort in {"detected_at", "bucket", "anomaly_score", "severity"} else "detected_at"
        reverse = order != "asc"
        sorted_rows = sorted(
            filtered,
            key=lambda r: (getattr(r, sort_attr), str(r.anomaly_id)),
            reverse=reverse,
        )

        total = len(sorted_rows)
        start = (page - 1) * page_size
        return sorted_rows[start : start + page_size], total

    # ----- API-02 detail -----
    def get_by_id(self, session: Any, anomaly_id: uuid.UUID) -> _AnomalyRow | None:
        for row in self.rows:
            if row.anomaly_id == anomaly_id:
                return row
        return None

    # ----- API-03 status update -----
    def update_status(
        self, session: Any, anomaly_id: uuid.UUID, status: str
    ) -> _AnomalyRow | None:
        row = self.get_by_id(session, anomaly_id)
        if row is None:
            return None
        row.status = status
        return row

    # ----- API-05 KPI summary -----
    def kpi_summary(self, session: Any) -> dict:
        cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
        status_counts: dict[str, int] = {}
        severity_counts: dict[str, int] = {}
        service_counts: dict[str, int] = {}
        account_counts: dict[str, int] = {}
        last_24h = 0
        for r in self.rows:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
            severity_counts[r.severity] = severity_counts.get(r.severity, 0) + 1
            service_counts[r.service] = service_counts.get(r.service, 0) + 1
            account_counts[r.account_id] = account_counts.get(r.account_id, 0) + 1
            if r.detected_at >= cutoff:
                last_24h += 1
        top_services = [
            {"service": s, "count": n}
            for s, n in sorted(service_counts.items(), key=lambda kv: -kv[1])[:5]
        ]
        top_accounts = [
            {"account_id": a, "count": n}
            for a, n in sorted(account_counts.items(), key=lambda kv: -kv[1])[:5]
        ]
        return {
            "total_anomalies": len(self.rows),
            "open_count": status_counts.get("open", 0),
            "acknowledged_count": status_counts.get("acknowledged", 0),
            "resolved_count": status_counts.get("resolved", 0),
            "suppressed_count": status_counts.get("suppressed", 0),
            "high_severity_count": severity_counts.get("high", 0),
            "medium_severity_count": severity_counts.get("medium", 0),
            "low_severity_count": severity_counts.get("low", 0),
            "anomalies_last_24h": last_24h,
            "top_services": top_services,
            "top_accounts": top_accounts,
        }

    # ----- UI-06 trend -----
    def kpi_trend(self, session: Any, days: int) -> list[dict]:
        if days < 1:
            return []
        today = datetime.now(tz=UTC).date()
        counts: dict = {}
        for r in self.rows:
            day = r.detected_at.date()
            counts[day] = counts.get(day, 0) + 1
        return [
            {
                "day": today - timedelta(days=offset),
                "count": counts.get(today - timedelta(days=offset), 0),
            }
            for offset in range(days - 1, -1, -1)
        ]


@dataclass
class _FakeAlertRepo:
    rows: list[_AlertRow] = field(default_factory=list)

    def list_alerts(
        self,
        session: Any,
        *,
        account_id: str | None = None,
        service: str | None = None,
        region: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        channel: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[_AlertRow], int]:
        filtered = self.rows
        if account_id is not None:
            filtered = [r for r in filtered if r.account_id == account_id]
        if service is not None:
            filtered = [r for r in filtered if r.service == service]
        if region is not None:
            filtered = [r for r in filtered if r.region == region]
        if severity is not None:
            filtered = [r for r in filtered if r.severity == severity]
        if status is not None:
            filtered = [r for r in filtered if r.status == status]
        if channel is not None:
            filtered = [r for r in filtered if r.channel == channel]

        sorted_rows = sorted(filtered, key=lambda r: r.created_at, reverse=True)
        total = len(sorted_rows)
        start = (page - 1) * page_size
        return sorted_rows[start : start + page_size], total


# ---------------------------------------------------------------------------
# Fixture: wire fakes in + handle audit-log writes from API-03 status updates
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline():
    """Install fake repos + a no-op DB session for the duration of the test."""
    anomaly_repo = _FakeAnomalyRepo()
    alert_repo = _FakeAlertRepo()

    # Replace module-level singletons in each API module.
    real_anomaly_repo = anomalies_api._repo
    real_kpi_repo = kpi_api._repo
    real_alert_repo = alerts_api._repo

    anomalies_api._repo = anomaly_repo
    kpi_api._repo = anomaly_repo  # KPI uses the same repo class
    alerts_api._repo = alert_repo

    # API-03's status update path does an audit-log write through the
    # session, so give it a session that swallows everything quietly.
    fake_session = MagicMock()
    app.dependency_overrides[get_db] = lambda: fake_session

    try:
        yield anomaly_repo, alert_repo
    finally:
        anomalies_api._repo = real_anomaly_repo
        kpi_api._repo = real_kpi_repo
        alerts_api._repo = real_alert_repo
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)


def _ingest_event(account_id: str = "acct-001", service: str = "BigQuery") -> dict:
    """POST a valid billing event and return the JSON receipt."""
    payload = {
        "timestamp": _NOW.isoformat(),
        "provider": "gcp",
        "account_id": account_id,
        "service": service,
        "region": "us-central1",
        "cost_amount": 12.5,
        "usage_amount": 100.0,
        "usage_unit": "core-hours",
        "tags": {"env": "prod"},
        "source_type": "synthetic",
    }
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code in (202, 200), response.text
    return response.json()


def _simulate_detection(
    repo: _FakeAnomalyRepo,
    *,
    account_id: str = "acct-001",
    service: str = "BigQuery",
    region: str = "us-central1",
    severity: str = "high",
    score: float = 0.91,
) -> uuid.UUID:
    """Insert an anomaly as if the detection pipeline produced it."""
    aid = uuid.uuid4()
    repo.rows.append(_AnomalyRow(
        anomaly_id=aid,
        account_id=account_id,
        service=service,
        region=region,
        bucket=_NOW,
        anomaly_score=Decimal(str(score)),
        severity=severity,
        status="open",
        detected_at=_NOW,
        score_breakdown={"ts_signal": 0.8, "if_score": 0.7},
    ))
    return aid


def _simulate_alert(
    repo: _FakeAlertRepo,
    *,
    anomaly_id: uuid.UUID,
    account_id: str = "acct-001",
    service: str = "BigQuery",
    region: str = "us-central1",
    severity: str = "high",
    channel: str = "in_app",
    status: str = "sent",
) -> uuid.UUID:
    """Insert an alert as if the orchestrator produced it from the anomaly."""
    aid = uuid.uuid4()
    repo.rows.append(_AlertRow(
        alert_id=aid,
        anomaly_id=anomaly_id,
        account_id=account_id,
        service=service,
        region=region,
        severity=severity,
        channel=channel,
        status=status,
        dedup_key=f"{account_id}:{service}:{region}:{_NOW.isoformat()}",
        created_at=_NOW,
        sent_at=_NOW if status == "sent" else None,
    ))
    return aid


# ---------------------------------------------------------------------------
# The integration scenario
# ---------------------------------------------------------------------------


class TestIngestDetectAlertUI:
    """Walk a single anomaly through every layer of the public API."""

    def test_full_pipeline_happy_path(self, pipeline) -> None:
        anomaly_repo, alert_repo = pipeline

        # ----- Step 1: ingest several billing events (admin-only) -------
        receipts = [_ingest_event() for _ in range(3)]
        # Each receipt should be unique and well-formed.
        ids = {r["event_id"] for r in receipts}
        assert len(ids) == 3
        assert all(r["status"] == "accepted" for r in receipts)

        # ----- Step 2: simulate the detector flagging an anomaly --------
        anomaly_id = _simulate_detection(anomaly_repo)

        # ----- Step 3: UI loads the anomaly list (UI-03) ----------------
        list_response = client.get("/api/v1/anomalies?page_size=10").json()
        assert list_response["total"] == 1
        assert list_response["pages"] == 1
        assert list_response["items"][0]["anomaly_id"] == str(anomaly_id)

        # ----- Step 4: UI loads the detail page (UI-04) -----------------
        detail = client.get(f"/api/v1/anomalies/{anomaly_id}").json()
        assert detail["anomaly_id"] == str(anomaly_id)
        assert detail["severity"] == "high"
        assert detail["score_breakdown"] == {"ts_signal": 0.8, "if_score": 0.7}

        # ----- Step 5: operator acknowledges via status patch (UI-08) ---
        ack = client.patch(
            f"/api/v1/anomalies/{anomaly_id}/status",
            json={"status": "acknowledged"},
        )
        assert ack.status_code == 200
        assert ack.json()["status"] == "acknowledged"

        # The mutation must be visible on the next list read.
        re_listed = client.get("/api/v1/anomalies").json()
        assert re_listed["items"][0]["status"] == "acknowledged"

        # ----- Step 6: orchestrator emits an alert for the anomaly ------
        alert_id = _simulate_alert(alert_repo, anomaly_id=anomaly_id)

        # ----- Step 7: UI's Alert Center sees it (UI-07) ----------------
        alert_response = client.get("/api/v1/alerts").json()
        assert alert_response["total"] == 1
        alert_item = alert_response["items"][0]
        assert alert_item["alert_id"] == str(alert_id)
        # Critical: the alert must reference the same anomaly that the
        # operator just acknowledged — this is the cross-layer linkage.
        assert alert_item["anomaly_id"] == str(anomaly_id)

        # ----- Step 8: KPI summary reflects the anomaly (UI-06) ---------
        kpi = client.get("/api/v1/kpi/summary").json()
        assert kpi["total_anomalies"] == 1
        assert kpi["acknowledged_count"] == 1
        assert kpi["high_severity_count"] == 1
        assert {"service": "BigQuery", "count": 1} in kpi["top_services"]

    def test_ui_filter_links_resolve_to_correct_subset(self, pipeline) -> None:
        """The Dashboard's "Open" KPI card links to /anomalies?status=open;
        the Alert Center sidebar badge polls /alerts?status=pending.
        Verify the corresponding URL filters return the right rows."""
        anomaly_repo, alert_repo = pipeline

        # Three anomalies in mixed states.
        _simulate_detection(anomaly_repo, severity="high")
        open_id = _simulate_detection(anomaly_repo, severity="medium")
        resolved_id = _simulate_detection(anomaly_repo, severity="low")
        # Mark one resolved.
        for r in anomaly_repo.rows:
            if r.anomaly_id == resolved_id:
                r.status = "resolved"

        open_only = client.get("/api/v1/anomalies?status=open").json()
        assert open_only["total"] == 2
        for item in open_only["items"]:
            assert item["status"] == "open"

        high_only = client.get("/api/v1/anomalies?severity=high").json()
        assert high_only["total"] == 1

        # Two pending alerts, one already sent.
        _simulate_alert(alert_repo, anomaly_id=open_id, status="pending")
        _simulate_alert(alert_repo, anomaly_id=open_id, status="pending")
        _simulate_alert(alert_repo, anomaly_id=resolved_id, status="sent")

        pending_alerts = client.get("/api/v1/alerts?status=pending&page_size=1").json()
        # The sidebar badge polls page_size=1 and reads ``total`` for the count.
        assert pending_alerts["total"] == 2
        assert len(pending_alerts["items"]) == 1

    def test_unknown_anomaly_returns_404_through_full_stack(self, pipeline) -> None:
        # Even with the in-memory pipeline empty, a get-by-id miss should
        # propagate a 404 — not a 500 from a missing repo or a 200 with null.
        bogus = uuid.uuid4()
        r = client.get(f"/api/v1/anomalies/{bogus}")
        assert r.status_code == 404

    def test_status_update_to_unknown_returns_404(self, pipeline) -> None:
        bogus = uuid.uuid4()
        r = client.patch(
            f"/api/v1/anomalies/{bogus}/status",
            json={"status": "resolved"},
        )
        assert r.status_code == 404

    def test_pagination_total_matches_repo_count(self, pipeline) -> None:
        anomaly_repo, _ = pipeline
        for _ in range(7):
            _simulate_detection(anomaly_repo)

        body = client.get("/api/v1/anomalies?page=1&page_size=3").json()
        assert body["total"] == 7
        assert body["pages"] == ceil(7 / 3)
        assert len(body["items"]) == 3

        page2 = client.get("/api/v1/anomalies?page=2&page_size=3").json()
        assert len(page2["items"]) == 3
        # Page 2 items must not overlap page 1 items.
        page1_ids = {i["anomaly_id"] for i in body["items"]}
        page2_ids = {i["anomaly_id"] for i in page2["items"]}
        assert page1_ids.isdisjoint(page2_ids)
