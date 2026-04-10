"""create billing_events_raw table

Revision ID: 0001
Revises:
Create Date: 2026-04-10

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_events_raw",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("service", sa.String(255), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("usage_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("usage_unit", sa.String(64), nullable=False),
        sa.Column(
            "tags",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_billing_events_raw_account_id", "billing_events_raw", ["account_id"]
    )
    op.create_index(
        "ix_billing_events_raw_timestamp", "billing_events_raw", ["timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_billing_events_raw_timestamp", table_name="billing_events_raw")
    op.drop_index("ix_billing_events_raw_account_id", table_name="billing_events_raw")
    op.drop_table("billing_events_raw")
