"""SEC-04: admin-only audit log retrieval endpoint.

GET /api/v1/audit/logs
    Returns a paginated, filterable list of recorded audit events.
    Restricted to ``admin`` — analysts can act on anomalies but should
    not be able to read the audit trail of other operators.

Filters (combined with AND, all optional):
    event_type   – e.g. ``auth.login`` | ``ingest.event`` | ``anomaly.status_update``
    action       – e.g. ``login`` | ``ingest`` | ``status_update``
    outcome      – ``success`` | ``failure``
    user_id      – UUID of the actor whose actions to inspect
    from_time    – ISO-8601, inclusive lower bound on ``created_at``
    to_time      – ISO-8601, inclusive upper bound on ``created_at``

Pagination mirrors API-01 (``page``, ``page_size``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.rbac import require_admin
from app.db.repos.audit_log_repo import AuditLogRepository
from app.db.session import get_db
from app.schemas.audit import AuditLogListResponse, AuditLogResponse

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

_repo = AuditLogRepository()

_Outcome = Literal["success", "failure"]


@router.get(
    "/logs",
    response_model=AuditLogListResponse,
    summary="List audit log entries",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks the admin role"},
    },
    dependencies=[Depends(require_admin)],
)
def list_audit_logs(
    db: Session | None = Depends(get_db),  # noqa: B008
    event_type: str | None = Query(None, description="Filter by event type"),
    action: str | None = Query(None, description="Filter by action"),
    outcome: _Outcome | None = Query(None, description="Filter by outcome"),
    user_id: uuid.UUID | None = Query(None, description="Filter by actor user_id"),
    from_time: datetime | None = Query(
        None, description="Include rows with created_at >= this datetime (ISO-8601)"
    ),
    to_time: datetime | None = Query(
        None, description="Include rows with created_at <= this datetime (ISO-8601)"
    ),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page (max 200)"),
) -> AuditLogListResponse:
    """SEC-04: paginated audit log query (admin only)."""
    if db is None:
        return AuditLogListResponse(
            items=[], total=0, page=page, page_size=page_size, pages=0
        )

    rows, total = _repo.list_logs(
        db,
        event_type=event_type,
        action=action,
        outcome=outcome,
        user_id=user_id,
        from_time=from_time,
        to_time=to_time,
        page=page,
        page_size=page_size,
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 0,
    )
