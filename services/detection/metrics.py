"""
DET-03: Detection service metrics registry.

Provides a thread-safe, in-process metrics store that the detection
pipeline writes to after each scored batch.  The FastAPI health/metrics
endpoints read from the same singleton to expose current state.

Counters (monotonically increasing)
------------------------------------
    batches_processed       Number of scoring batches completed.
    rows_scored             Total DataFrame rows passed through the scorer.
    anomalies_detected      Rows where is_anomaly == 1 (before DB write).
    anomalies_persisted     Rows successfully written to the anomalies table.
    events_emitted          Events successfully published to the stream.
    errors_scoring          Exceptions raised inside OnlineScorer.
    errors_persist          Exceptions raised inside AnomalyRepository.
    errors_emit             Exceptions raised inside AnomalyEventEmitter.

Gauges (point-in-time values)
-------------------------------
    last_batch_at           ISO-8601 UTC timestamp of the most recent batch,
                            or None if no batch has been processed yet.
    last_batch_rows         Row count of the most recent batch.
    last_batch_anomalies    Anomaly count in the most recent batch.

Usage
-----
# Detection pipeline (write path)
from services.detection.metrics import detection_metrics

detection_metrics.record_batch(rows_scored=50, anomalies_detected=3,
                                anomalies_persisted=3, events_emitted=3)
detection_metrics.record_error("scoring")

# Health endpoint (read path)
snapshot = detection_metrics.snapshot()
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Metrics dataclass (internal mutable state)
# ---------------------------------------------------------------------------


@dataclass
class _State:
    batches_processed: int = 0
    rows_scored: int = 0
    anomalies_detected: int = 0
    anomalies_persisted: int = 0
    events_emitted: int = 0
    errors_scoring: int = 0
    errors_persist: int = 0
    errors_emit: int = 0
    last_batch_at: Optional[str] = None
    last_batch_rows: int = 0
    last_batch_anomalies: int = 0


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------


class DetectionMetrics:
    """
    Thread-safe in-process metrics registry for the detection pipeline.

    A single module-level instance (``detection_metrics``) is shared between
    the detection pipeline and the health/metrics API endpoints.

    All write operations acquire a reentrant lock.  ``snapshot()`` returns a
    plain dict copy so callers never hold the lock while serialising.
    """

    def __init__(self) -> None:
        self._state = _State()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Write API (used by the detection pipeline)
    # ------------------------------------------------------------------

    def record_batch(
        self,
        rows_scored: int,
        anomalies_detected: int,
        anomalies_persisted: int,
        events_emitted: int,
    ) -> None:
        """
        Record the outcome of one completed scoring batch.

        Parameters
        ----------
        rows_scored:
            Total rows in the input DataFrame for this batch.
        anomalies_detected:
            Rows where ``is_anomaly == 1`` after scoring.
        anomalies_persisted:
            Rows successfully written to the ``anomalies`` DB table.
        events_emitted:
            Events successfully published to the anomaly stream.
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._lock:
            s = self._state
            s.batches_processed += 1
            s.rows_scored += rows_scored
            s.anomalies_detected += anomalies_detected
            s.anomalies_persisted += anomalies_persisted
            s.events_emitted += events_emitted
            s.last_batch_at = now
            s.last_batch_rows = rows_scored
            s.last_batch_anomalies = anomalies_detected

    def record_error(self, component: str) -> None:
        """
        Increment the error counter for a named pipeline component.

        Parameters
        ----------
        component:
            One of ``"scoring"``, ``"persist"``, or ``"emit"``.
            Unknown names are silently ignored.
        """
        with self._lock:
            s = self._state
            if component == "scoring":
                s.errors_scoring += 1
            elif component == "persist":
                s.errors_persist += 1
            elif component == "emit":
                s.errors_emit += 1

    def reset(self) -> None:
        """Reset all counters to zero (intended for tests only)."""
        with self._lock:
            self._state = _State()

    # ------------------------------------------------------------------
    # Read API (used by health / metrics endpoints)
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, object]:
        """
        Return a point-in-time copy of all metric values as a plain dict.

        The dict is safe to serialise to JSON without holding any lock.
        """
        with self._lock:
            s = self._state
            return {
                "batches_processed": s.batches_processed,
                "rows_scored": s.rows_scored,
                "anomalies_detected": s.anomalies_detected,
                "anomalies_persisted": s.anomalies_persisted,
                "events_emitted": s.events_emitted,
                "errors_scoring": s.errors_scoring,
                "errors_persist": s.errors_persist,
                "errors_emit": s.errors_emit,
                "last_batch_at": s.last_batch_at,
                "last_batch_rows": s.last_batch_rows,
                "last_batch_anomalies": s.last_batch_anomalies,
            }

    @property
    def total_errors(self) -> int:
        """Sum of all error counters — convenience for health-check degradation check."""
        with self._lock:
            s = self._state
            return s.errors_scoring + s.errors_persist + s.errors_emit


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

detection_metrics: DetectionMetrics = DetectionMetrics()
