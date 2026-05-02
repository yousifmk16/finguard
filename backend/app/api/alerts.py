"""
API-04: Alert list endpoint with pagination and filtering.

GET /api/v1/alerts
    Returns a paginated, optionally filtered list of alert records.

Filters (all optional, combined with AND):
    account_id  – exact match
    service     – exact match
    region      – exact match
    severity    – none | low | medium | high
    status      – pending | sent | failed | suppressed
    channel     – in_app | email

Pagination:
    page        – 1-indexed (default 1)
    page_size   – 1-200 (default 50)
"""

from __future__ import annotations

from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.rbac import require_analyst_or_admin
from app.db.repos.alert_repo import AlertRepository
from app.db.session import get_db
from app.schemas.alert import AlertListResponse, AlertResponse

router = APIRouter(prefix="/api/v1", tags=["alerts"])

_repo = AlertRepository()

_Severity = Literal["none", "low", "medium", "high"]
_AlertStatus = Literal["pending", "sent", "failed", "suppressed"]
_Channel = Literal["in_app", "email"]


@router.get(
    "/alerts",
    response_model=AlertListResponse,
    summary="List alerts",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
    },
    dependencies=[Depends(require_analyst_or_admin)],
)
def list_alerts(
    db: Session | None = Depends(get_db),  # noqa: B008
    account_id: str | None = Query(None, description="Filter by account ID"),
    service: str | None = Query(None, description="Filter by service name"),
    region: str | None = Query(None, description="Filter by region"),
    severity: _Severity | None = Query(None, description="Filter by severity level"),
    status: _AlertStatus | None = Query(None, description="Filter by delivery status"),
    channel: _Channel | None = Query(None, description="Filter by delivery channel"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page (max 200)"),
) -> AlertListResponse:
    """API-04: Paginated alert list."""
    if db is None:
        return AlertListResponse(
            items=[], total=0, page=page, page_size=page_size, pages=0
        )

    rows, total = _repo.list_alerts(
        db,
        account_id=account_id,
        service=service,
        region=region,
        severity=severity,
        status=status,
        channel=channel,
        page=page,
        page_size=page_size,
    )

    return AlertListResponse(
        items=[AlertResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 0,
    )
