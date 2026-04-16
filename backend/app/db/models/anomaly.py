from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnomalyRow(Base):
    """ORM model for the anomalies table (DB-04 / ARC-05).

    One row per detected anomaly window.  Written by the detection service
    (DET-01) after ``OnlineScorer.score_group()`` + ``SeverityMapper``
    (ENS-02) have been applied to a 1-minute aggregate batch.

    Anomaly lifecycle states (REQ-09)
    ----------------------------------
    open          – newly detected, not yet reviewed
    acknowledged  – an operator has seen it
    resolved      – confirmed and closed
    suppressed    – intentionally silenced (false-positive / expected spike)
    """

    __tablename__ = "anomalies"

    anomaly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # Billing-series identity (mirrors OnlineScorer group_cols)
    account_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False)

    # The 1-minute window that was flagged
    bucket: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # ENS-01 ensemble score
    anomaly_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False
    )
    # ENS-02 severity
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )

    # EXP-03 full score breakdown (optional — null when breakdown not computed)
    score_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Anomaly lifecycle (REQ-09)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'open'"),
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
