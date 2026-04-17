"""
Unit tests for DET-03: detection health and metrics endpoints.

No live DB or Redis required — the DB session is overridden via FastAPI's
dependency-injection system, and scorer/emitter are registered with stubs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.api.detection import register_emitter, register_scorer
from app.main import app
from fastapi.testclient import TestClient
from services.detection.metrics import detection_metrics


@pytest.fixture(autouse=True)
def reset_state():
    """Reset metrics and scorer/emitter stubs before every test."""
    detection_metrics.reset()
    register_scorer(None)
    register_emitter(None)
    yield
    detection_metrics.reset()
    register_scorer(None)
    register_emitter(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_db_ok():
    """Return a mock Session that reports 5 anomalies in the table."""
    db = MagicMock()
    db.execute.return_value.scalar_one.return_value = 5
    return db


def _stub_db_error():
    """Return a mock Session whose execute() raises."""
    db = MagicMock()
    db.execute.side_effect = Exception("connection refused")
    return db


def _override_db(stub):
    from app.db.session import get_db
    app.dependency_overrides[get_db] = lambda: stub
    yield
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /api/v1/detection/health — DB not configured
# ---------------------------------------------------------------------------


class TestDetectionHealthNoDb:
    def setup_method(self):
        from app.db.session import get_db
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        from app.db.session import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_status_code_200(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.status_code == 200

    def test_overall_status_degraded_when_db_not_configured(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["status"] == "degraded"

    def test_db_component_not_configured(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["components"]["db"]["status"] == "not_configured"

    def test_scorer_component_not_loaded(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["components"]["scorer"]["status"] == "not_loaded"

    def test_emitter_component_not_configured(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["components"]["emitter"]["status"] == "not_configured"

    def test_metrics_block_present(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert "metrics" in r.json()


# ---------------------------------------------------------------------------
# GET /api/v1/detection/health — DB ok
# ---------------------------------------------------------------------------


class TestDetectionHealthDbOk:
    def setup_method(self):
        from app.db.session import get_db
        app.dependency_overrides[get_db] = lambda: _stub_db_ok()

    def teardown_method(self):
        from app.db.session import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_overall_status_ok(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["status"] == "ok"

    def test_db_component_ok(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        db_info = r.json()["components"]["db"]
        assert db_info["status"] == "ok"
        assert db_info["anomaly_count"] == 5


# ---------------------------------------------------------------------------
# GET /api/v1/detection/health — DB error
# ---------------------------------------------------------------------------


class TestDetectionHealthDbError:
    def setup_method(self):
        from app.db.session import get_db
        app.dependency_overrides[get_db] = lambda: _stub_db_error()

    def teardown_method(self):
        from app.db.session import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_overall_status_degraded(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["status"] == "degraded"

    def test_db_component_error(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["components"]["db"]["status"] == "error"
        assert "detail" in r.json()["components"]["db"]


# ---------------------------------------------------------------------------
# Scorer / emitter registration reflected in health
# ---------------------------------------------------------------------------


class TestDetectionHealthWithScorerEmitter:
    def setup_method(self):
        from app.db.session import get_db
        app.dependency_overrides[get_db] = lambda: None

    def teardown_method(self):
        from app.db.session import get_db
        app.dependency_overrides.pop(get_db, None)

    def test_registered_scorer_shown_in_health(self):
        scorer = MagicMock()
        scorer.status.return_value = {
            "baseline_loaded": True,
            "if_loaded": False,
            "config": {"anomaly_threshold": 0.55},
        }
        register_scorer(scorer)

        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        scorer_info = r.json()["components"]["scorer"]
        assert scorer_info["status"] == "ok"
        assert scorer_info["baseline_loaded"] is True
        assert scorer_info["if_loaded"] is False

    def test_registered_emitter_shown_in_health(self):
        emitter = MagicMock()
        emitter.stream_name = "anomaly-events"
        emitter.include_breakdown = False
        register_emitter(emitter)

        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        em_info = r.json()["components"]["emitter"]
        assert em_info["status"] == "configured"
        assert em_info["stream_name"] == "anomaly-events"

    def test_scorer_status_error_caught(self):
        scorer = MagicMock()
        scorer.status.side_effect = RuntimeError("model corrupted")
        register_scorer(scorer)

        client = TestClient(app)
        r = client.get("/api/v1/detection/health")
        assert r.json()["components"]["scorer"]["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/v1/detection/metrics
# ---------------------------------------------------------------------------


class TestDetectionMetricsEndpoint:
    def test_status_code_200(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        assert r.status_code == 200

    def test_all_counter_keys_present(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        payload = r.json()
        expected_keys = {
            "batches_processed", "rows_scored", "anomalies_detected",
            "anomalies_persisted", "events_emitted",
            "errors_scoring", "errors_persist", "errors_emit",
            "last_batch_at", "last_batch_rows", "last_batch_anomalies",
        }
        assert expected_keys.issubset(payload.keys())

    def test_zero_values_on_fresh_start(self):
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        payload = r.json()
        assert payload["batches_processed"] == 0
        assert payload["rows_scored"] == 0
        assert payload["last_batch_at"] is None

    def test_metrics_reflect_recorded_batch(self):
        detection_metrics.record_batch(
            rows_scored=100,
            anomalies_detected=4,
            anomalies_persisted=4,
            events_emitted=4,
        )
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        payload = r.json()
        assert payload["batches_processed"] == 1
        assert payload["rows_scored"] == 100
        assert payload["anomalies_detected"] == 4
        assert payload["last_batch_rows"] == 100

    def test_metrics_accumulate_across_batches(self):
        for _ in range(3):
            detection_metrics.record_batch(
                rows_scored=50, anomalies_detected=2,
                anomalies_persisted=2, events_emitted=2,
            )
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        payload = r.json()
        assert payload["batches_processed"] == 3
        assert payload["rows_scored"] == 150
        assert payload["anomalies_detected"] == 6

    def test_errors_reflected_in_metrics(self):
        detection_metrics.record_error("scoring")
        detection_metrics.record_error("persist")
        detection_metrics.record_error("emit")
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        payload = r.json()
        assert payload["errors_scoring"] == 1
        assert payload["errors_persist"] == 1
        assert payload["errors_emit"] == 1

    def test_last_batch_at_set_after_batch(self):
        detection_metrics.record_batch(
            rows_scored=10, anomalies_detected=1,
            anomalies_persisted=1, events_emitted=1,
        )
        client = TestClient(app)
        r = client.get("/api/v1/detection/metrics")
        assert r.json()["last_batch_at"] is not None


# ---------------------------------------------------------------------------
# DetectionMetrics unit tests (no HTTP)
# ---------------------------------------------------------------------------


class TestDetectionMetricsUnit:
    def test_initial_snapshot_all_zero(self):
        snap = detection_metrics.snapshot()
        assert snap["batches_processed"] == 0
        assert snap["rows_scored"] == 0
        assert snap["last_batch_at"] is None

    def test_record_batch_increments_counters(self):
        detection_metrics.record_batch(
            rows_scored=20, anomalies_detected=3,
            anomalies_persisted=3, events_emitted=3,
        )
        snap = detection_metrics.snapshot()
        assert snap["batches_processed"] == 1
        assert snap["rows_scored"] == 20
        assert snap["anomalies_detected"] == 3
        assert snap["anomalies_persisted"] == 3
        assert snap["events_emitted"] == 3

    def test_record_error_unknown_component_ignored(self):
        detection_metrics.record_error("unknown_component")
        snap = detection_metrics.snapshot()
        assert snap["errors_scoring"] == 0
        assert snap["errors_persist"] == 0
        assert snap["errors_emit"] == 0

    def test_total_errors_sums_all_error_counters(self):
        detection_metrics.record_error("scoring")
        detection_metrics.record_error("scoring")
        detection_metrics.record_error("emit")
        assert detection_metrics.total_errors == 3

    def test_reset_clears_all_state(self):
        detection_metrics.record_batch(
            rows_scored=50, anomalies_detected=1,
            anomalies_persisted=1, events_emitted=1,
        )
        detection_metrics.reset()
        snap = detection_metrics.snapshot()
        assert snap["batches_processed"] == 0
        assert snap["last_batch_at"] is None
