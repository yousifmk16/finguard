"""
API-05: Response schema for the KPI summary endpoint.
UI-06: Response schema for the KPI trend endpoint.
"""

from __future__ import annotations

from datetime import date

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
    # 30-day average daily anomaly count (for "vs N daily avg" sub-text)
    daily_avg: float
    # Mean-time-to-acknowledge in seconds (p50 / p95); null when no data
    mtt_ack_p50_seconds: float | None
    mtt_ack_p95_seconds: float | None
    top_services: list[ServiceCount]
    top_accounts: list[AccountCount]


class TrendPoint(BaseModel):
    """One day in the daily anomaly-count trend."""

    day: date
    count: int


class KpiTrendResponse(BaseModel):
    """UI-06: Daily anomaly counts for the trend sparkline."""

    days: int
    points: list[TrendPoint]
