"""
OPS-03: Prometheus text exposition format renderer.

Combines the detection-pipeline metrics (``services.detection.metrics``)
and the HTTP metrics registry (``app.core.http_metrics``) into the
Prometheus 0.0.4 text exposition format that Prometheus scrapers and
Grafana ingest natively.

Format spec (excerpt)::

    # HELP <name> <one-line description>
    # TYPE <name> counter|gauge
    <name>{label="value",...} <number>

Reference: https://prometheus.io/docs/instrumenting/exposition_formats/

Label-value escaping
--------------------
Prometheus labels require backslashes, double-quotes, and newlines to be
escaped (\\\\, \\", \\n).  ``_escape_label`` handles this for the route
template — which already excludes user input — but we run it defensively
so a future addition with user-derived labels does not silently break the
exposition output.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.core.http_metrics import HttpMetrics
from services.detection.metrics import DetectionMetrics


# ---------------------------------------------------------------------------
# Detection-pipeline metric metadata
# ---------------------------------------------------------------------------
# Each tuple: (snapshot_key, prom_name, prom_type, help_text)
_DETECTION_COUNTERS: list[tuple[str, str, str, str]] = [
    ("batches_processed", "finguard_batches_processed_total", "counter",
     "Number of scoring batches completed by the detection pipeline."),
    ("rows_scored", "finguard_rows_scored_total", "counter",
     "Total DataFrame rows passed through the scorer."),
    ("anomalies_detected", "finguard_anomalies_detected_total", "counter",
     "Rows where is_anomaly=1 after scoring (before DB write)."),
    ("anomalies_persisted", "finguard_anomalies_persisted_total", "counter",
     "Rows successfully written to the anomalies table."),
    ("events_emitted", "finguard_events_emitted_total", "counter",
     "Anomaly events successfully published to the stream."),
    ("errors_scoring", "finguard_errors_scoring_total", "counter",
     "Exceptions raised inside the OnlineScorer."),
    ("errors_persist", "finguard_errors_persist_total", "counter",
     "Exceptions raised while persisting anomalies to the DB."),
    ("errors_emit", "finguard_errors_emit_total", "counter",
     "Exceptions raised while emitting events to the stream."),
]

_DETECTION_GAUGES: list[tuple[str, str, str, str]] = [
    ("last_batch_rows", "finguard_last_batch_rows", "gauge",
     "Row count of the most recent scoring batch."),
    ("last_batch_anomalies", "finguard_last_batch_anomalies", "gauge",
     "Anomaly count in the most recent scoring batch."),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: Iterable[tuple[str, str]]) -> str:
    inner = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels)
    return "{" + inner + "}" if inner else ""


def _emit_metric(
    name: str,
    metric_type: str,
    help_text: str,
    samples: Iterable[tuple[Iterable[tuple[str, str]], float]],
) -> list[str]:
    lines = [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {metric_type}",
    ]
    for labels, value in samples:
        lines.append(f"{name}{_format_labels(labels)} {value}")
    return lines


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_detection(metrics: DetectionMetrics) -> list[str]:
    snap = metrics.snapshot()
    out: list[str] = []
    for key, prom_name, prom_type, help_text in _DETECTION_COUNTERS + _DETECTION_GAUGES:
        out.extend(_emit_metric(prom_name, prom_type, help_text, [((), snap[key])]))
    return out


def _render_http(metrics: HttpMetrics) -> list[str]:
    snap = metrics.snapshot()
    out: list[str] = []

    out.extend(_emit_metric(
        "finguard_http_requests_total",
        "counter",
        "Total HTTP requests handled, by method, route template, and status.",
        (
            ((("method", m), ("path", p), ("status", s)), float(c))
            for (m, p, s), c in sorted(snap["requests_total"].items())
        ),
    ))

    out.extend(_emit_metric(
        "finguard_http_request_duration_seconds_sum",
        "counter",
        "Cumulative observed request latency in seconds, per route.",
        (
            ((("method", m), ("path", p)), float(v))
            for (m, p), v in sorted(snap["duration_sum"].items())
        ),
    ))

    out.extend(_emit_metric(
        "finguard_http_request_duration_seconds_count",
        "counter",
        "Total number of latency observations recorded, per route.",
        (
            ((("method", m), ("path", p)), float(v))
            for (m, p), v in sorted(snap["duration_count"].items())
        ),
    ))

    return out


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------


def render(
    detection: DetectionMetrics,
    http: HttpMetrics,
) -> str:
    """Return the full Prometheus exposition payload as a single string.

    The payload always ends with a trailing newline — Prometheus rejects
    payloads that do not end in one.
    """
    lines: list[str] = []
    lines.extend(_render_detection(detection))
    lines.extend(_render_http(http))
    return "\n".join(lines) + "\n"
