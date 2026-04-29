"""
API-05: KPI summary endpoint.

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

When DATABASE_URL is not configured all counts are 0 and the top-* lists
are empty.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.repos.anomaly_repo import AnomalyRepository
from app.db.session import get_db
from app.schemas.kpi import KpiSummaryResponse

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
    # TODO AUTH-01: unauthenticated — add middleware before production.
)
def kpi_summary(
    db: Session | None = Depends(get_db),  # noqa: B008
) -> KpiSummaryResponse:
    """API-05: Aggregated anomaly statistics for dashboard KPI cards."""
    if db is None:
        return _ZERO_KPI
    data = _repo.kpi_summary(db)
    return KpiSummaryResponse(**data)
