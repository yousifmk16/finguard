"""
DET-01: Persist anomaly records to DB.

``AnomalyRepository`` converts the output of ``OnlineScorer.score_group()``
(after ENS-02 severity mapping) into ``AnomalyRow`` records and writes them
to the ``anomalies`` table in a single transaction.

Typical call sequence
---------------------
1. Feature pipeline produces a 1-minute aggregate DataFrame.
2. ``OnlineScorer.score_group(df)`` appends score + severity columns.
3. (Optional) ``ScoreBreakdownBuilder.build(df)`` appends ``exp_breakdown``.
4. ``AnomalyRepository.persist_from_df(session, df)`` filters rows where
   ``is_anomaly == 1`` and upserts each as an ``AnomalyRow``.

Duplicate handling
------------------
(account_id, service, region, bucket) is treated as a natural key.  If a
row already exists the severity and score_breakdown are updated; this lets
the detection service be re-run on the same window without creating phantom
duplicates.

Usage
-----
from app.db.repos.anomaly_repo import AnomalyRepository

repo = AnomalyRepository()
saved = repo.persist_from_df(db_session, scored_df)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models.anomaly import AnomalyRow

logger = logging.getLogger(__name__)

# Column name written by ScoreBreakdownBuilder (EXP-03)
_BREAKDOWN_COL = "exp_breakdown"

# UI-05: whitelist of sortable columns. Severity is mapped through a CASE
# expression so high > medium > low > none orders intuitively rather than
# alphabetically (where "high" would sort below "low").
_SORT_COLUMNS = {
    "detected_at": AnomalyRow.detected_at,
    "bucket": AnomalyRow.bucket,
    "anomaly_score": AnomalyRow.anomaly_score,
    "severity": case(
        (AnomalyRow.severity == "high", 3),
        (AnomalyRow.severity == "medium", 2),
        (AnomalyRow.severity == "low", 1),
        else_=0,
    ),
}


class AnomalyRepository:
    """
    DET-01: Write anomaly records produced by the detection pipeline to the DB.

    All public methods accept a SQLAlchemy ``Session`` as their first argument
    so the caller controls transaction boundaries.  Nothing is committed here —
    callers should call ``session.commit()`` (or rely on a context manager)
    after the batch is complete.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def persist_from_df(
        self,
        session: Session,
        df: pd.DataFrame,
        is_anomaly_col: str = "is_anomaly",
        score_col: str = "anomaly_score",
        severity_col: str = "severity",
        bucket_col: str = "bucket",
    ) -> list[AnomalyRow]:
        """
        Persist all anomalous rows from a scored DataFrame.

        Filters rows where ``is_anomaly_col == 1``, converts each to an
        ``AnomalyRow``, and upserts via :meth:`save`.

        Parameters
        ----------
        session:
            Active SQLAlchemy session.  The caller owns commit/rollback.
        df:
            Output of ``OnlineScorer.score_group()``, optionally extended
            with EXP-03 ``exp_breakdown`` column.
        is_anomaly_col:
            Binary flag column (1 = anomaly).
        score_col:
            Ensemble anomaly score column.
        severity_col:
            Severity label column written by ENS-02.
        bucket_col:
            Datetime column identifying the 1-minute window.

        Returns
        -------
        List of ``AnomalyRow`` instances added/updated in this call.
        """
        if is_anomaly_col not in df.columns:
            logger.warning(
                "Column '%s' not in DataFrame; no anomalies persisted.",
                is_anomaly_col,
            )
            return []

        anomalous = df[df[is_anomaly_col].astype(int) == 1]
        if anomalous.empty:
            return []

        saved: list[AnomalyRow] = []
        for _, row in anomalous.iterrows():
            anomaly_row = self._row_to_orm(
                row,
                score_col=score_col,
                severity_col=severity_col,
                bucket_col=bucket_col,
            )
            saved.append(self.save(session, anomaly_row))

        logger.info(
            "DET-01: persisted %d anomaly record(s) to DB.", len(saved)
        )
        return saved

    def list_anomalies(
        self,
        session: Session,
        *,
        account_id: str | None = None,
        service: str | None = None,
        region: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        from_bucket: datetime | None = None,
        to_bucket: datetime | None = None,
        sort: str = "detected_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AnomalyRow], int]:
        """
        API-01: Return a filtered, paginated page of anomaly records.

        Parameters
        ----------
        session:
            Active SQLAlchemy session.
        account_id, service, region, severity, status:
            Optional equality filters.
        from_bucket, to_bucket:
            Optional inclusive range filter on the ``bucket`` datetime column.
        sort:
            Column to sort by. Must be one of ``_SORT_COLUMNS`` keys; unknown
            values fall back to ``detected_at`` so a stale URL never 500s.
        order:
            ``asc`` or ``desc``; anything else falls back to ``desc``.
        page:
            1-indexed page number.
        page_size:
            Rows per page.

        Returns
        -------
        (rows, total) where ``rows`` is the current page and ``total`` is the
        count of all matching rows (used to compute ``pages``).
        """
        filters = []
        if account_id is not None:
            filters.append(AnomalyRow.account_id == account_id)
        if service is not None:
            filters.append(AnomalyRow.service == service)
        if region is not None:
            filters.append(AnomalyRow.region == region)
        if severity is not None:
            filters.append(AnomalyRow.severity == severity)
        if status is not None:
            filters.append(AnomalyRow.status == status)
        if from_bucket is not None:
            filters.append(AnomalyRow.bucket >= from_bucket)
        if to_bucket is not None:
            filters.append(AnomalyRow.bucket <= to_bucket)

        count_stmt = select(func.count()).select_from(AnomalyRow)
        rows_stmt = select(AnomalyRow)
        if filters:
            count_stmt = count_stmt.where(*filters)
            rows_stmt = rows_stmt.where(*filters)

        total: int = session.execute(count_stmt).scalar_one()

        sort_col = _SORT_COLUMNS.get(sort, AnomalyRow.detected_at)
        direction = sort_col.asc() if order == "asc" else sort_col.desc()
        # Tiebreak on anomaly_id so paging is stable when many rows share
        # the primary sort value (common for severity sort).
        rows_stmt = (
            rows_stmt
            .order_by(direction, AnomalyRow.anomaly_id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list(session.execute(rows_stmt).scalars().all())

        return rows, total

    def save(self, session: Session, anomaly: AnomalyRow) -> AnomalyRow:
        """
        Upsert a single ``AnomalyRow``.

        If a record with the same (account_id, service, region, bucket)
        already exists its ``anomaly_score``, ``severity``, and
        ``score_breakdown`` are updated.  Otherwise a new row is inserted.

        Parameters
        ----------
        session:
            Active SQLAlchemy session.
        anomaly:
            Populated ``AnomalyRow`` instance.

        Returns
        -------
        The persisted (or updated) ``AnomalyRow``.
        """
        existing = self._find_existing(session, anomaly)
        if existing is not None:
            existing.anomaly_score = anomaly.anomaly_score
            existing.severity = anomaly.severity
            existing.score_breakdown = anomaly.score_breakdown
            return existing

        session.add(anomaly)
        return anomaly

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def get_by_id(
        self, session: Session, anomaly_id: uuid.UUID
    ) -> AnomalyRow | None:
        """API-02: Return a single AnomalyRow by primary key, or None."""
        return session.execute(
            select(AnomalyRow).where(AnomalyRow.anomaly_id == anomaly_id)
        ).scalar_one_or_none()

    def update_status(
        self, session: Session, anomaly_id: uuid.UUID, status: str
    ) -> AnomalyRow | None:
        """
        API-03: Update the lifecycle status of an anomaly.

        Returns the updated row, or None if not found.
        The caller owns the transaction (commit/rollback).
        """
        row = self.get_by_id(session, anomaly_id)
        if row is None:
            return None
        row.status = status
        return row

    def kpi_trend(self, session: Session, days: int) -> list[dict]:
        """
        UI-06: Daily anomaly counts for the trailing ``days`` days, ending today.

        Returns a list of ``{day, count}`` dicts, one per day in chronological
        order. Days with zero anomalies are included (count = 0) so the front
        end can render a continuous sparkline without gap-filling itself.
        """
        if days < 1:
            return []

        today = datetime.now(tz=UTC).date()
        start_dt = datetime.combine(
            today - timedelta(days=days - 1), datetime.min.time(), tzinfo=UTC
        )

        day_col = func.date(AnomalyRow.detected_at).label("day")
        rows = session.execute(
            select(day_col, func.count())
            .where(AnomalyRow.detected_at >= start_dt)
            .group_by(day_col)
        ).all()

        counts: dict = {row[0]: row[1] for row in rows}
        return [
            {"day": today - timedelta(days=offset), "count": counts.get(today - timedelta(days=offset), 0)}
            for offset in range(days - 1, -1, -1)
        ]

    def kpi_summary(self, session: Session) -> dict:
        """
        API-05: Aggregate KPI statistics from the anomalies table.

        Runs six lightweight queries:
          1. total count
          2. per-status counts
          3. per-severity counts
          4. count in the last 24 h
          5. top-5 services by anomaly count
          6. top-5 accounts by anomaly count
        """
        total: int = session.execute(
            select(func.count()).select_from(AnomalyRow)
        ).scalar_one()

        status_counts: dict[str, int] = dict(
            session.execute(
                select(AnomalyRow.status, func.count()).group_by(AnomalyRow.status)
            ).all()
        )

        severity_counts: dict[str, int] = dict(
            session.execute(
                select(AnomalyRow.severity, func.count()).group_by(AnomalyRow.severity)
            ).all()
        )

        cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
        last_24h: int = session.execute(
            select(func.count())
            .select_from(AnomalyRow)
            .where(AnomalyRow.detected_at >= cutoff)
        ).scalar_one()

        cnt = func.count().label("cnt")
        top_services = [
            {"service": svc, "count": n}
            for svc, n in session.execute(
                select(AnomalyRow.service, cnt)
                .group_by(AnomalyRow.service)
                .order_by(cnt.desc())
                .limit(5)
            ).all()
        ]

        top_accounts = [
            {"account_id": aid, "count": n}
            for aid, n in session.execute(
                select(AnomalyRow.account_id, cnt)
                .group_by(AnomalyRow.account_id)
                .order_by(cnt.desc())
                .limit(5)
            ).all()
        ]

        # 30-day daily average
        trend_30d = self.kpi_trend(session, 30)
        daily_avg = round(
            sum(d["count"] for d in trend_30d) / max(len(trend_30d), 1), 1
        )

        # MTT-ACK: p50 / p95 of (now - detected_at) for acknowledged anomalies
        # Used as a proxy until a dedicated acknowledged_at column is added.
        ack_rows = session.execute(
            select(AnomalyRow.detected_at)
            .where(AnomalyRow.status == "acknowledged")
            .order_by(AnomalyRow.detected_at.desc())
            .limit(200)
        ).scalars().all()

        mtt_ack_p50: float | None = None
        mtt_ack_p95: float | None = None
        if ack_rows:
            now_utc = datetime.now(tz=UTC)
            lags = sorted(
                abs((now_utc - (r if r.tzinfo else r.replace(tzinfo=UTC))).total_seconds())
                for r in ack_rows
            )
            p50_idx = max(0, int(len(lags) * 0.50) - 1)
            p95_idx = max(0, int(len(lags) * 0.95) - 1)
            mtt_ack_p50 = round(lags[p50_idx], 1)
            mtt_ack_p95 = round(lags[p95_idx], 1)

        return {
            "total_anomalies": total,
            "open_count": status_counts.get("open", 0),
            "acknowledged_count": status_counts.get("acknowledged", 0),
            "resolved_count": status_counts.get("resolved", 0),
            "suppressed_count": status_counts.get("suppressed", 0),
            "high_severity_count": severity_counts.get("high", 0),
            "medium_severity_count": severity_counts.get("medium", 0),
            "low_severity_count": severity_counts.get("low", 0),
            "anomalies_last_24h": last_24h,
            "daily_avg": daily_avg,
            "mtt_ack_p50_seconds": mtt_ack_p50,
            "mtt_ack_p95_seconds": mtt_ack_p95,
            "top_services": top_services,
            "top_accounts": top_accounts,
        }

    def _find_existing(
        self, session: Session, anomaly: AnomalyRow
    ) -> AnomalyRow | None:
        """Return an existing row matching the natural key, or None."""
        stmt = select(AnomalyRow).where(
            AnomalyRow.account_id == anomaly.account_id,
            AnomalyRow.service == anomaly.service,
            AnomalyRow.region == anomaly.region,
            AnomalyRow.bucket == anomaly.bucket,
        )
        return session.execute(stmt).scalar_one_or_none()

    def _row_to_orm(
        self,
        row: pd.Series,
        score_col: str,
        severity_col: str,
        bucket_col: str,
    ) -> AnomalyRow:
        """Convert a single scored DataFrame row to an ``AnomalyRow``."""
        score_breakdown: dict | None = None
        if _BREAKDOWN_COL in row.index:
            breakdown_obj = row[_BREAKDOWN_COL]
            if breakdown_obj is not None and hasattr(breakdown_obj, "to_dict"):
                score_breakdown = breakdown_obj.to_dict()

        severity = str(row[severity_col]) if severity_col in row.index else "none"
        anomaly_score = (
            Decimal(str(float(row[score_col])))
            if score_col in row.index
            else Decimal("0")
        )

        return AnomalyRow(
            anomaly_id=uuid.uuid4(),
            account_id=str(row["account_id"]),
            service=str(row["service"]),
            region=str(row["region"]),
            bucket=row[bucket_col],
            anomaly_score=anomaly_score,
            severity=severity,
            score_breakdown=score_breakdown,
            status="open",
        )
