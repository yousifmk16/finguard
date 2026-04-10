from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Clock-skew tolerance for future timestamps (seconds).
_MAX_FUTURE_SKEW_SECONDS = 300

Provider = Literal["gcp", "aws", "azure"]


class BillingEvent(BaseModel):
    """Canonical billing event schema (ARC-04)."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    provider: Provider
    account_id: str
    service: str
    region: str
    cost_amount: Decimal = Field(ge=0, decimal_places=6)
    usage_amount: Decimal = Field(ge=0, decimal_places=6)
    usage_unit: str
    tags: dict[str, str] = Field(default_factory=dict)
    source_type: Literal["synthetic", "live"] = "synthetic"

    @field_validator("account_id", "service", "region", "usage_unit", mode="before")
    @classmethod
    def must_be_non_empty(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("timestamp", mode="after")
    @classmethod
    def timestamp_not_in_far_future(cls, value: datetime) -> datetime:
        now = datetime.now(tz=timezone.utc)
        # Normalize to UTC so naive timestamps (no tz) are comparable.
        ts = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if ts > now + timedelta(seconds=_MAX_FUTURE_SKEW_SECONDS):
            raise ValueError(
                f"timestamp is more than {_MAX_FUTURE_SKEW_SECONDS}s in the future"
            )
        return value


class IngestionReceipt(BaseModel):
    """Response returned after a successful event ingestion."""

    event_id: uuid.UUID
    status: Literal["accepted"] = "accepted"
    duplicate: bool = False
