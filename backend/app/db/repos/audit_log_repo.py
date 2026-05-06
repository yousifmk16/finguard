"""SEC-04: read/write repository for ``audit_logs``.

The recorder helpers in :mod:`app.audit.recorder` are the only writers in
the request path; the list method backs the admin retrieval endpoint
(``GET /api/v1/audit/logs``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLogRow


class AuditLogRepository:
    def insert(
        self,
        session: Session,
        *,
        event_type: str,
        action: str,
        outcome: str,
        user_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        actor_role: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditLogRow:
        """Stage a new ``AuditLogRow`` on ``session``.

        The caller owns the transaction — nothing is committed here so the
        audit row lives or dies with the action it describes.
        """
        row = AuditLogRow(
            event_type=event_type,
            action=action,
            outcome=outcome,
            user_id=user_id,
            actor_email=actor_email,
            actor_role=actor_role,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta=meta,
        )
        session.add(row)
        return row

    def list_logs(
        self,
        session: Session,
        *,
        event_type: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        user_id: uuid.UUID | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuditLogRow], int]:
        """Return ``(rows, total)`` for the filtered, paginated query."""
        filters = []
        if event_type is not None:
            filters.append(AuditLogRow.event_type == event_type)
        if action is not None:
            filters.append(AuditLogRow.action == action)
        if outcome is not None:
            filters.append(AuditLogRow.outcome == outcome)
        if user_id is not None:
            filters.append(AuditLogRow.user_id == user_id)
        if from_time is not None:
            filters.append(AuditLogRow.created_at >= from_time)
        if to_time is not None:
            filters.append(AuditLogRow.created_at <= to_time)

        count_stmt = select(func.count()).select_from(AuditLogRow)
        rows_stmt = select(AuditLogRow)
        if filters:
            count_stmt = count_stmt.where(*filters)
            rows_stmt = rows_stmt.where(*filters)

        total: int = session.execute(count_stmt).scalar_one()

        rows_stmt = (
            rows_stmt.order_by(AuditLogRow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list(session.execute(rows_stmt).scalars().all())
        return rows, total
