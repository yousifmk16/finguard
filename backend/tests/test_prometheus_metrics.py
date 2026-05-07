"""
OPS-03: Tests for the Prometheus metrics surface.

Coverage:
  1. /metrics returns 200 with the Prometheus content type.
  2. /metrics contains required # HELP and # TYPE lines for every metric family.
  3. Detection-pipeline counters/gauges are reflected in the output.
  4. HTTP middleware records per-route metrics (method/path/status/duration).
  5. /metrics itself is excluded from the HTTP registry (no self-reference).
  6. Path templates (not raw URLs with IDs) are used as labels.
  7. Label values with backslashes/quotes are properly escaped.
  8. The Prometheus payload always ends with a trailing newline.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.http_metrics import http_metrics
from app.core.prometheus_text import _escape_label, render
from app.main import app
from services.detection.metrics import detection_metrics

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_metrics():
    detection_metrics.reset()
    http_metrics.reset()
    yield
    detection_metrics.reset()
    http_metrics.reset()


# ---------------------------------------------------------------------------
# 1. Endpoint shape
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200():
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_uses_prometheus_content_type():
    response = client.get("/metrics")
    assert response.headers["content-type"].startswith(
        "text/plain; version=0.0.4"
    )


def test_metrics_endpoint_payload_ends_with_newline():
    response = client.get("/metrics")
    assert response.text.endswith("\n")


# ---------------------------------------------------------------------------
# 2. HELP / TYPE annotations
# ---------------------------------------------------------------------------


_REQUIRED_FAMILIES = [
    "finguard_batches_processed_total",
    "finguard_rows_scored_total",
    "finguard_anomalies_detected_total",
    "finguard_anomalies_persisted_total",
    "finguard_events_emitted_total",
    "finguard_errors_scoring_total",
    "finguard_errors_persist_total",
    "finguard_errors_emit_total",
    "finguard_last_batch_rows",
    "finguard_last_batch_anomalies",
    "finguard_http_requests_total",
    "finguard_http_request_duration_seconds_sum",
    "finguard_http_request_duration_seconds_count",
]


@pytest.mark.parametrize("metric", _REQUIRED_FAMILIES)
def test_metrics_endpoint_has_help_line(metric):
    body = client.get("/metrics").text
    assert f"# HELP {metric} " in body, f"missing HELP for {metric}"


@pytest.mark.parametrize("metric", _REQUIRED_FAMILIES)
def test_metrics_endpoint_has_type_line(metric):
    body = client.get("/metrics").text
    assert re.search(rf"^# TYPE {metric} (counter|gauge)$", body, re.MULTILINE), (
        f"missing TYPE for {metric}"
    )


# ---------------------------------------------------------------------------
# 3. Detection pipeline metrics reflect snapshot
# ---------------------------------------------------------------------------


def test_metrics_reflect_detection_counters():
    detection_metrics.record_batch(
        rows_scored=50, anomalies_detected=3, anomalies_persisted=3, events_emitted=3
    )
    detection_metrics.record_error("scoring")

    body = client.get("/metrics").text

    assert "finguard_batches_processed_total 1" in body
    assert "finguard_rows_scored_total 50" in body
    assert "finguard_anomalies_detected_total 3" in body
    assert "finguard_errors_scoring_total 1" in body
    assert "finguard_last_batch_rows 50" in body
    assert "finguard_last_batch_anomalies 3" in body


# ---------------------------------------------------------------------------
# 4. HTTP middleware records per-route metrics
# ---------------------------------------------------------------------------


def test_middleware_records_request_count():
    client.get("/health")
    client.get("/health")
    client.get("/health")

    snap = http_metrics.snapshot()
    assert snap["requests_total"][("GET", "/health", "200")] == 3


def test_middleware_records_latency_observations():
    client.get("/health")
    snap = http_metrics.snapshot()
    assert snap["duration_count"][("GET", "/health")] == 1
    assert snap["duration_sum"][("GET", "/health")] >= 0.0


def test_middleware_records_status_code():
    # Hit a route that returns 401 (auth required, no admin override here)
    # Use /api/v1/audit-logs which requires admin
    response = client.get("/api/v1/audit/audit-logs")
    snap = http_metrics.snapshot()
    # We don't know the exact route template for an unmatched path, just that
    # *some* request was recorded for the status returned.
    statuses = {key[2] for key in snap["requests_total"].keys()}
    assert str(response.status_code) in statuses


def test_metrics_endpoint_renders_recorded_http_metrics():
    client.get("/health")
    client.get("/health")

    body = client.get("/metrics").text

    assert (
        'finguard_http_requests_total{method="GET",path="/health",status="200"} 2'
        in body
    )
    assert 'finguard_http_request_duration_seconds_count{method="GET",path="/health"} 2' in body


# ---------------------------------------------------------------------------
# 5. /metrics is excluded from the registry (no self-reference)
# ---------------------------------------------------------------------------


def test_metrics_endpoint_does_not_record_itself():
    client.get("/metrics")
    client.get("/metrics")
    client.get("/metrics")

    snap = http_metrics.snapshot()
    metrics_keys = [key for key in snap["requests_total"].keys() if key[1] == "/metrics"]
    assert metrics_keys == [], "/metrics requests should not appear in the HTTP registry"


# ---------------------------------------------------------------------------
# 6. Route template (not raw URL) used as label
# ---------------------------------------------------------------------------


def test_path_label_uses_route_template_not_raw_id():
    """A request to /api/v1/anomalies/{id} should record the template, not the id."""
    # Use a fabricated UUID that won't match any anomaly — the route template is
    # what matters for the label, not the response status.
    fake_id = "11111111-1111-1111-1111-111111111111"
    client.get(f"/api/v1/anomalies/{fake_id}")

    snap = http_metrics.snapshot()
    paths = {key[1] for key in snap["requests_total"].keys()}
    # The template form must appear; the raw uuid form must not.
    assert any("{anomaly_id}" in p for p in paths), (
        f"expected templated path with {{anomaly_id}}, got {paths}"
    )
    assert not any(fake_id in p for p in paths), (
        f"raw UUID leaked into path label: {paths}"
    )


# ---------------------------------------------------------------------------
# 7. Label escaping
# ---------------------------------------------------------------------------


def test_escape_label_handles_double_quote():
    assert _escape_label('foo"bar') == 'foo\\"bar'


def test_escape_label_handles_backslash():
    assert _escape_label("foo\\bar") == "foo\\\\bar"


def test_escape_label_handles_newline():
    assert _escape_label("foo\nbar") == "foo\\nbar"


def test_escape_label_passes_through_clean_value():
    assert _escape_label("/api/v1/anomalies") == "/api/v1/anomalies"


# ---------------------------------------------------------------------------
# 8. Renderer unit test — pure render() function
# ---------------------------------------------------------------------------


def test_render_returns_string_with_required_sections():
    detection_metrics.record_batch(
        rows_scored=10, anomalies_detected=1, anomalies_persisted=1, events_emitted=1
    )
    http_metrics.record("GET", "/health", 200, 0.001)

    body = render(detection_metrics, http_metrics)

    assert isinstance(body, str)
    assert body.endswith("\n")
    assert "# HELP finguard_batches_processed_total" in body
    assert "# TYPE finguard_http_requests_total counter" in body
    assert 'finguard_http_requests_total{method="GET",path="/health",status="200"} 1.0' in body


def test_render_with_empty_registries_emits_only_help_type_lines():
    body = render(detection_metrics, http_metrics)
    # Counters always emit at least the # HELP/# TYPE pair plus the zero value;
    # HTTP families have no samples when nothing has been recorded.
    assert "# HELP finguard_http_requests_total" in body
    # No data samples for http_requests_total because the registry is empty:
    assert 'finguard_http_requests_total{' not in body
