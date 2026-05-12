"""widen billing_events_raw.source_type to VARCHAR(32)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-11

source_type was VARCHAR(16) which is too short for 'training_generated' (18)
and 'training_uploaded' (17).  Widen to VARCHAR(32) to accommodate all values.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "billing_events_raw",
        "source_type",
        type_=sa.String(32),
        existing_type=sa.String(16),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "billing_events_raw",
        "source_type",
        type_=sa.String(16),
        existing_type=sa.String(32),
        existing_nullable=False,
    )
