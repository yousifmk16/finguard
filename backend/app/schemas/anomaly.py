"""
API-01: Response schemas for the anomaly query API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class AnomalyResponse(BaseModel):
    """Single anomaly record returned by the list endpoint."""

    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    bucket: datetime
    anomaly_score: float
    severity: str
    status: str
    detected_at: datetime
    score_breakdown: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class AnomalyStatusUpdate(BaseModel):
    """Request body for API-03: update an anomaly's lifecycle status."""

    status: Literal["open", "acknowledged", "resolved", "suppressed"]


class AnomalyListResponse(BaseModel):
    """Paginated list of anomaly records."""

    items: list[AnomalyResponse]
    total: int
    page: int
    page_size: int
    pages: int
