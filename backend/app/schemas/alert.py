"""API-04: Response schemas for the alert query API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AlertResponse(BaseModel):
    alert_id: uuid.UUID
    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    severity: str
    channel: str
    status: str
    dedup_key: str
    created_at: datetime
    sent_at: datetime | None = None
    error_detail: str | None = None

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
    total: int
    page: int
    page_size: int
    pages: int
