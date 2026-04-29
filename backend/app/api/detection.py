"""
DET-03: Detection service health and metrics endpoints.

Two endpoints are exposed under /api/v1/detection/:

GET /api/v1/detection/health
    Returns the health status of the detection pipeline components:
      - db:      can the anomalies table be queried?
      - scorer:  are the baseline / IF models loaded?
      - emitter: what stream is configured?
    Overall status is "ok" when the DB is reachable; "degraded" otherwise.

GET /api/v1/detection/metrics
    Returns a JSON snapshot of the in-process DetectionMetrics counters:
    batches_processed, rows_scored, anomalies_detected, errors, etc.

Both endpoints are read-only and carry no side effects.

Scorer / emitter references
----------------------------
The detection pipeline registers its live OnlineScorer and AnomalyEventEmitter
with this module via ``register_scorer()`` / ``register_emitter()``.  When
nothing is registered the health response shows status "not_loaded" / "not_configured".
This avoids a global import of the ML model at startup when the scorer hasn't
been created yet.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/detection", tags=["detection"])

# ---------------------------------------------------------------------------
# Registry for live scorer / emitter references
# ---------------------------------------------------------------------------

_scorer: object | None = None
_emitter: object | None = None


def register_scorer(scorer: object) -> None:
    """Register the live OnlineScorer instance used by the detection pipeline."""
    global _scorer
    _scorer = scorer


def register_emitter(emitter: object) -> None:
    """Register the live AnomalyEventEmitter instance."""
    global _emitter
    _emitter = emitter


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _db_status(db: Session | None) -> dict[str, Any]:
    """
    Return a dict describing DB connectivity.

    Performs a lightweight SELECT 1 (pure connectivity check — avoids
    a table scan on every health poll).  On failure the error message is
    logged server-side only; the client receives a generic "database error"
    string to prevent leaking connection details.
    """
    if db is None:
        return {"status": "not_configured", "detail": "DATABASE_URL not set"}
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("DET-03: DB health check failed: %s", exc)
        return {"status": "error", "detail": "database error"}


def _scorer_status() -> dict[str, Any]:
    """Return a dict reflecting the live OnlineScorer's model load state."""
    if _scorer is None:
        return {"status": "not_loaded"}
    try:
        info = _scorer.status()  # type: ignore[union-attr]
        return {
            "status": "ok",
            "baseline_loaded": info.get("baseline_loaded", False),
            "if_loaded": info.get("if_loaded", False),
            "config": info.get("config", {}),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("DET-03: scorer status failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


def _emitter_status() -> dict[str, Any]:
    """Return a dict describing the configured anomaly event stream."""
    if _emitter is None:
        return {"status": "not_configured"}
    stream = getattr(_emitter, "stream_name", "unknown")
    include_bd = getattr(_emitter, "include_breakdown", False)
    return {
        "status": "configured",
        "stream_name": stream,
        "include_breakdown": include_bd,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health", summary="Detection service health check")
def detection_health(
    db: Session | None = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """
    DET-03 health endpoint.

    Returns component statuses for DB, scorer, and emitter.
    ``status`` at the top level is ``"ok"`` when the DB is reachable,
    ``"degraded"`` otherwise.

    Response shape::

        {
          "status": "ok" | "degraded",
          "components": {
            "db":      { "status": "ok", "anomaly_count": 42 },
            "scorer":  { "status": "ok", "baseline_loaded": true, ... },
            "emitter": { "status": "configured", "stream_name": "anomaly-events" }
          },
          "metrics": { ... }   // same payload as GET /metrics
        }
    """
    from services.detection.metrics import detection_metrics  # avoid circular at import

    db_info = _db_status(db)
    overall = "ok" if db_info["status"] == "ok" else "degraded"

    return {
        "status": overall,
        "components": {
            "db": db_info,
            "scorer": _scorer_status(),
            "emitter": _emitter_status(),
        },
        "metrics": detection_metrics.snapshot(),
    }


@router.get("/metrics", summary="Detection service metrics snapshot")
def detection_metrics_endpoint() -> dict[str, Any]:
    """
    DET-03 metrics endpoint.

    Returns a JSON snapshot of the in-process counter/gauge values written
    by the detection pipeline after each scored batch.

    Response shape::

        {
          "batches_processed": 150,
          "rows_scored": 7500,
          "anomalies_detected": 12,
          "anomalies_persisted": 12,
          "events_emitted": 12,
          "errors_scoring": 0,
          "errors_persist": 0,
          "errors_emit": 0,
          "last_batch_at": "2026-04-16T12:00:00+00:00",
          "last_batch_rows": 50,
          "last_batch_anomalies": 1
        }
    """
    from services.detection.metrics import detection_metrics

    return detection_metrics.snapshot()
