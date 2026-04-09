from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BillingEvent(BaseModel):
    """Canonical billing event schema (ARC-04)."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    provider: str
    account_id: str
    service: str
    region: str
    cost_amount: float = Field(ge=0.0)
    usage_amount: float = Field(ge=0.0)
    usage_unit: str
    tags: dict[str, str] = Field(default_factory=dict)
    source_type: Literal["synthetic", "live"] = "synthetic"


class IngestionReceipt(BaseModel):
    """Response returned after a successful event ingestion."""

    event_id: uuid.UUID
    status: Literal["accepted"] = "accepted"
