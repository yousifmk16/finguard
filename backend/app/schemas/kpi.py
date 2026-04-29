"""API-05: Response schema for the KPI summary endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class ServiceCount(BaseModel):
    service: str
    count: int


class AccountCount(BaseModel):
    account_id: str
    count: int


class KpiSummaryResponse(BaseModel):
    """Aggregated anomaly statistics for the dashboard KPI cards."""

    total_anomalies: int
    open_count: int
    acknowledged_count: int
    resolved_count: int
    suppressed_count: int
    high_severity_count: int
    medium_severity_count: int
    low_severity_count: int
    anomalies_last_24h: int
    top_services: list[ServiceCount]
    top_accounts: list[AccountCount]
