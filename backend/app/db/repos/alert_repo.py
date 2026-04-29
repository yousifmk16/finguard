"""API-04 / DB-05: Alert repository."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.alert import AlertRow

logger = logging.getLogger(__name__)

_Channel = str | None
_Status = str | None


class AlertRepository:
    def list_alerts(
        self,
        session: Session,
        *,
        account_id: str | None = None,
        service: str | None = None,
        region: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        channel: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AlertRow], int]:
        """Return a filtered, paginated page of alert records and the total count."""
        filters = []
        if account_id is not None:
            filters.append(AlertRow.account_id == account_id)
        if service is not None:
            filters.append(AlertRow.service == service)
        if region is not None:
            filters.append(AlertRow.region == region)
        if severity is not None:
            filters.append(AlertRow.severity == severity)
        if status is not None:
            filters.append(AlertRow.status == status)
        if channel is not None:
            filters.append(AlertRow.channel == channel)

        count_stmt = select(func.count()).select_from(AlertRow)
        rows_stmt = select(AlertRow)
        if filters:
            count_stmt = count_stmt.where(*filters)
            rows_stmt = rows_stmt.where(*filters)

        total: int = session.execute(count_stmt).scalar_one()

        rows_stmt = (
            rows_stmt
            .order_by(AlertRow.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list(session.execute(rows_stmt).scalars().all())
        return rows, total

    def is_duplicate(self, session: Session, dedup_key: str) -> bool:
        """
        ALT-02: Return True if an alert with this dedup_key already exists.

        Used by the orchestrator to skip re-processing after a restart.
        """
        return (
            session.execute(
                select(func.count())
                .select_from(AlertRow)
                .where(AlertRow.dedup_key == dedup_key)
            ).scalar_one()
            > 0
        )
