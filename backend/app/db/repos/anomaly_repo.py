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
from decimal import Decimal
from typing import List, Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.anomaly import AnomalyRow

logger = logging.getLogger(__name__)

# Column name written by ScoreBreakdownBuilder (EXP-03)
_BREAKDOWN_COL = "exp_breakdown"


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
    ) -> List[AnomalyRow]:
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

        saved: List[AnomalyRow] = []
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

    def _find_existing(
        self, session: Session, anomaly: AnomalyRow
    ) -> Optional[AnomalyRow]:
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
        anomaly_score = Decimal(str(float(row[score_col]))) if score_col in row.index else Decimal("0")

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
