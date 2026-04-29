from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Clock-skew tolerance for future timestamps (seconds).
_MAX_FUTURE_SKEW_SECONDS = 300

# Tags payload limits — prevent oversized ingestion payloads.
_MAX_TAGS = 50
_MAX_TAG_KEY_LEN = 64
_MAX_TAG_VALUE_LEN = 256

Provider = Literal["gcp", "aws", "azure"]


class BillingEvent(BaseModel):
    """Canonical billing event schema (ARC-04).

    ``event_id`` is auto-generated when omitted. To support idempotent
    re-submission the caller should generate the ID client-side and include it
    in every attempt; omitting it makes each request appear unique.
    """

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

    @field_validator("tags", mode="after")
    @classmethod
    def tags_within_limits(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > _MAX_TAGS:
            raise ValueError(
                f"tags must not exceed {_MAX_TAGS} entries; got {len(value)}"
            )
        for k, v in value.items():
            if len(k) > _MAX_TAG_KEY_LEN:
                raise ValueError(
                    f"tag key '{k[:20]}...' exceeds {_MAX_TAG_KEY_LEN} characters"
                )
            if len(v) > _MAX_TAG_VALUE_LEN:
                raise ValueError(
                    f"tag value for key '{k}' exceeds {_MAX_TAG_VALUE_LEN} characters"
                )
        return value

    @field_validator("timestamp", mode="after")
    @classmethod
    def timestamp_not_in_far_future(cls, value: datetime) -> datetime:
        now = datetime.now(tz=UTC)
        # Normalize to UTC so naive timestamps (no tz) are comparable.
        ts = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if ts > now + timedelta(seconds=_MAX_FUTURE_SKEW_SECONDS):
            raise ValueError(
                f"timestamp is more than {_MAX_FUTURE_SKEW_SECONDS}s in the future"
            )
        return ts


class IngestionReceipt(BaseModel):
    """Response returned after a successful event ingestion."""

    event_id: uuid.UUID
    status: Literal["accepted"] = "accepted"
    duplicate: bool = False
