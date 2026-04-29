"""DB-05: Alert records written by the alert orchestration service (ALT-01)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertRow(Base):
    """One row per alert delivery attempt for a detected anomaly.

    Lifecycle states
    ----------------
    pending    – created, awaiting delivery
    sent       – successfully delivered via ``channel``
    failed     – delivery failed; ``error_detail`` explains why
    suppressed – skipped due to cooldown or dedup (ALT-02/03)
    """

    __tablename__ = "alerts"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    # FK to the anomaly that triggered this alert (denormalised for fast list queries)
    anomaly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    # Delivery channel: in_app | email
    channel: Mapped[str] = mapped_column(String(16), nullable=False)

    # Delivery status
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )

    # ALT-02 dedup key — unique constraint prevents duplicate alert rows.
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
