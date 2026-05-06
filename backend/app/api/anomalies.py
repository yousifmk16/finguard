"""
API-01: Anomaly list endpoint with pagination and filtering.
API-02: Anomaly detail endpoint.
API-03: Anomaly status update endpoint.
SEC-04: Status updates are recorded to ``audit_logs`` (privileged
operator action — read-only list/detail are not audited).

GET /api/v1/anomalies
    Returns a paginated, optionally filtered list of anomaly records.

Filters (all optional, combined with AND):
    account_id   – exact match on billing account
    service      – exact match on cloud service name
    region       – exact match on region
    severity     – one of: none | low | medium | high
    status       – one of: open | acknowledged | resolved | suppressed
    from_bucket  – include anomalies with bucket >= this datetime (ISO-8601)
    to_bucket    – include anomalies with bucket <= this datetime (ISO-8601)

Pagination:
    page         – 1-indexed page number (default 1)
    page_size    – rows per page, 1–200 (default 50)

Response shape:
    {
      "items":     [...],   // AnomalyResponse objects for the current page
      "total":     150,     // total matching records across all pages
      "page":      1,
      "page_size": 50,
      "pages":     3        // ceil(total / page_size), 0 when total == 0
    }
"""

from __future__ import annotations

import uuid
from datetime import datetime
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.rbac import require_analyst_or_admin
from app.audit import (
    EVENT_ANOMALY_STATUS_UPDATE,
    OUTCOME_SUCCESS,
    record_admin_action,
    request_context,
)
from app.db.repos.anomaly_repo import AnomalyRepository
from app.db.session import get_db
from app.schemas.anomaly import (
    AnomalyListResponse,
    AnomalyResponse,
    AnomalyStatusUpdate,
)
from app.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["anomalies"])

_repo = AnomalyRepository()

_Severity = Literal["none", "low", "medium", "high"]
_Status = Literal["open", "acknowledged", "resolved", "suppressed"]


@router.get(
    "/anomalies",
    response_model=AnomalyListResponse,
    summary="List anomalies",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
    },
    dependencies=[Depends(require_analyst_or_admin)],
)
def list_anomalies(
    db: Session | None = Depends(get_db),  # noqa: B008
    account_id: str | None = Query(None, description="Filter by account ID"),
    service: str | None = Query(None, description="Filter by service name"),
    region: str | None = Query(None, description="Filter by region"),
    severity: _Severity | None = Query(None, description="Filter by severity level"),
    status: _Status | None = Query(None, description="Filter by lifecycle status"),
    from_bucket: datetime | None = Query(
        None, description="Include buckets at or after this datetime (ISO-8601)"
    ),
    to_bucket: datetime | None = Query(
        None, description="Include buckets at or before this datetime (ISO-8601)"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page (max 200)"),
) -> AnomalyListResponse:
    """
    API-01: Paginated anomaly list.

    When DATABASE_URL is not configured the endpoint returns an empty list
    rather than raising — consistent with the rest of the detection API.
    """
    if db is None:
        return AnomalyListResponse(
            items=[], total=0, page=page, page_size=page_size, pages=0
        )

    rows, total = _repo.list_anomalies(
        db,
        account_id=account_id,
        service=service,
        region=region,
        severity=severity,
        status=status,
        from_bucket=from_bucket,
        to_bucket=to_bucket,
        page=page,
        page_size=page_size,
    )

    return AnomalyListResponse(
        items=[AnomalyResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 0,
    )


@router.get(
    "/anomalies/{anomaly_id}",
    response_model=AnomalyResponse,
    summary="Get anomaly detail",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
        404: {"description": "Anomaly not found"},
    },
    dependencies=[Depends(require_analyst_or_admin)],
)
def get_anomaly(
    anomaly_id: uuid.UUID,
    db: Session | None = Depends(get_db),  # noqa: B008
) -> AnomalyResponse:
    """API-02: Return a single anomaly record by ID."""
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    row = _repo.get_by_id(db, anomaly_id)
    if row is None:
        raise HTTPException(status_code=404, detail="anomaly not found")
    return AnomalyResponse.model_validate(row)


@router.patch(
    "/anomalies/{anomaly_id}/status",
    response_model=AnomalyResponse,
    summary="Update anomaly status",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
        404: {"description": "Anomaly not found"},
    },
)
def update_anomaly_status(
    anomaly_id: uuid.UUID,
    body: AnomalyStatusUpdate,
    request: Request,
    actor: CurrentUser = Depends(require_analyst_or_admin),  # noqa: B008
    db: Session | None = Depends(get_db),  # noqa: B008
) -> AnomalyResponse:
    """API-03: Transition an anomaly to a new lifecycle status."""
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    row = _repo.update_status(db, anomaly_id, body.status)
    if row is None:
        raise HTTPException(status_code=404, detail="anomaly not found")

    ip, ua = request_context(request)
    record_admin_action(
        db,
        event_type=EVENT_ANOMALY_STATUS_UPDATE,
        action="status_update",
        actor=actor,
        target_type="anomaly",
        target_id=str(anomaly_id),
        outcome=OUTCOME_SUCCESS,
        ip_address=ip,
        user_agent=ua,
        meta={"new_status": body.status},
    )

    db.commit()
    db.refresh(row)
    return AnomalyResponse.model_validate(row)
