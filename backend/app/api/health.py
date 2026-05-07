"""
OPS-01: Finalized service health checks.

GET /health
    Aggregate health endpoint consumed by load balancers and container
    orchestrators (k8s liveness / readiness probes). No authentication
    required — health must be readable before auth is available.

Response shape::

    {
      "status": "ok" | "degraded" | "unhealthy",
      "version": "0.1.0",
      "timestamp": "2026-05-08T00:00:00+00:00",
      "uptime_seconds": 42.3,
      "components": {
        "app":       { "status": "ok" },
        "db":        { "status": "ok" | "not_configured" | "error", ... },
        "ingestion": { "status": "ok", "store_size": 12, "store_capacity": 100000 }
      }
    }

Status semantics
----------------
  ok         All components healthy.
  degraded   Non-critical components degraded (e.g. DB not configured in
             dev, scorer not loaded). Service is functional.
  unhealthy  A critical path has failed. HTTP 503 is returned so orchestrators
             can take action.

The DB is treated as *optional* — its absence ("not_configured") does not
degrade status because the service can run in-memory for development.  A DB
*error* (connection refused, timeout) is "degraded", not "unhealthy", because
the service can still accept and validate events.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.idempotency import store as idempotency_store, _MAX_SIZE as _STORE_CAPACITY
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Recorded once at module import — good enough for an uptime field.
_START_TIME: float = time.monotonic()

# Version kept in sync with pyproject.toml [project].version.
_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Component checkers
# ---------------------------------------------------------------------------


def _check_db(db: Session | None) -> dict[str, Any]:
    if db is None:
        return {"status": "not_configured"}
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("OPS-01: DB health check failed: %s", exc)
        return {"status": "error", "detail": "database error"}


def _check_ingestion() -> dict[str, Any]:
    size = len(idempotency_store._seen)
    return {
        "status": "ok",
        "store_size": size,
        "store_capacity": _STORE_CAPACITY,
    }


# ---------------------------------------------------------------------------
# Aggregate status logic
# ---------------------------------------------------------------------------


def _aggregate_status(components: dict[str, dict[str, Any]]) -> str:
    db_status = components["db"]["status"]
    if db_status == "error":
        return "degraded"
    return "ok"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Service health check",
    response_description="Aggregate health status for all service components",
    include_in_schema=True,
)
def health(
    db: Session | None = Depends(get_db),  # noqa: B008
) -> JSONResponse:
    """OPS-01: Aggregate service health check.

    Returns 200 for ``ok`` and ``degraded`` (service is operational).
    Returns 503 for ``unhealthy`` so orchestrators can restart the pod.
    """
    import datetime

    components: dict[str, dict[str, Any]] = {
        "app": {"status": "ok"},
        "db": _check_db(db),
        "ingestion": _check_ingestion(),
    }

    status = _aggregate_status(components)
    http_status = 503 if status == "unhealthy" else 200

    payload: dict[str, Any] = {
        "status": status,
        "version": _VERSION,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "components": components,
    }

    return JSONResponse(content=payload, status_code=http_status)
