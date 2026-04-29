"""create alerts table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29

DB-05: alerts table written by the alert orchestration service (ALT-01).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column(
            "alert_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("anomaly_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("service", sa.String(255), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("dedup_key", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.String(512), nullable=True),
        sa.UniqueConstraint("dedup_key", name="uq_alerts_dedup_key"),
    )
    op.create_index("ix_alerts_anomaly_id", "alerts", ["anomaly_id"])
    op.create_index("ix_alerts_account_id", "alerts", ["account_id"])
    op.create_index("ix_alerts_status", "alerts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_alerts_status", table_name="alerts")
    op.drop_index("ix_alerts_account_id", table_name="alerts")
    op.drop_index("ix_alerts_anomaly_id", table_name="alerts")
    op.drop_table("alerts")
