"""
API-05: KPI summary endpoint.
UI-06: KPI trend endpoint (daily anomaly counts for the dashboard sparkline).

GET /api/v1/kpi/summary
    Returns aggregated anomaly statistics for the dashboard KPI cards.

Response shape:
    {
      "total_anomalies":      150,
      "open_count":           12,
      "acknowledged_count":    5,
      "resolved_count":       130,
      "suppressed_count":       3,
      "high_severity_count":    8,
      "medium_severity_count": 20,
      "low_severity_count":    50,
      "anomalies_last_24h":     4,
      "top_services":   [{"service": "BigQuery", "count": 42}, ...],
      "top_accounts":   [{"account_id": "acct-001", "count": 35}, ...]
    }

GET /api/v1/kpi/trend?days=14
    Returns daily anomaly counts over the trailing ``days`` days (1–90).
    Days with no anomalies are included with count = 0 so the front-end
    sparkline does not need to gap-fill. Points are in chronological order.

When DATABASE_URL is not configured all counts are 0, the top-* lists are
empty, and the trend points list is empty.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.rbac import require_analyst_or_admin
from app.db.repos.anomaly_repo import AnomalyRepository
from app.db.session import get_db
from app.schemas.kpi import KpiSummaryResponse, KpiTrendResponse, TrendPoint

router = APIRouter(prefix="/api/v1", tags=["kpi"])

_repo = AnomalyRepository()

_ZERO_KPI = KpiSummaryResponse(
    total_anomalies=0,
    open_count=0,
    acknowledged_count=0,
    resolved_count=0,
    suppressed_count=0,
    high_severity_count=0,
    medium_severity_count=0,
    low_severity_count=0,
    anomalies_last_24h=0,
    top_services=[],
    top_accounts=[],
)


@router.get(
    "/kpi/summary",
    response_model=KpiSummaryResponse,
    summary="KPI summary",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
    },
    dependencies=[Depends(require_analyst_or_admin)],
)
def kpi_summary(
    db: Session | None = Depends(get_db),  # noqa: B008
) -> KpiSummaryResponse:
    """API-05: Aggregated anomaly statistics for dashboard KPI cards."""
    if db is None:
        return _ZERO_KPI
    data = _repo.kpi_summary(db)
    return KpiSummaryResponse(**data)


@router.get(
    "/kpi/trend",
    response_model=KpiTrendResponse,
    summary="KPI daily trend",
    responses={
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks an analyst/admin role"},
    },
    dependencies=[Depends(require_analyst_or_admin)],
)
def kpi_trend(
    days: int = Query(
        14, ge=1, le=90, description="Number of trailing days to include"
    ),
    db: Session | None = Depends(get_db),  # noqa: B008
) -> KpiTrendResponse:
    """UI-06: Daily anomaly counts for the dashboard sparkline."""
    if db is None:
        return KpiTrendResponse(days=days, points=[])
    rows = _repo.kpi_trend(db, days)
    return KpiTrendResponse(
        days=days,
        points=[TrendPoint(**row) for row in rows],
    )
