"""create anomalies table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16

DB-04 / ARC-05: anomalies table persisted by DET-01.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anomalies",
        sa.Column(
            "anomaly_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("service", sa.String(255), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anomaly_score", sa.Numeric(8, 6), nullable=False),
        sa.Column(
            "severity",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        sa.Column("score_breakdown", JSONB, nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_anomalies_account_id", "anomalies", ["account_id"])
    op.create_index("ix_anomalies_bucket", "anomalies", ["bucket"])
    op.create_index("ix_anomalies_status", "anomalies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_anomalies_status", table_name="anomalies")
    op.drop_index("ix_anomalies_bucket", table_name="anomalies")
    op.drop_index("ix_anomalies_account_id", table_name="anomalies")
    op.drop_table("anomalies")
