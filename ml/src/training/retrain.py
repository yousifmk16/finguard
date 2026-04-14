"""
TS-04: Retrain scheduler job for the time-series baseline model.

Periodically re-fits TimeSeriesBaselineModel (TS-01) on a rolling lookback
window of 1-minute aggregate data from the DB-02 table and saves the updated
artifact to disk.  The scheduler is designed to run inside the ML service
container as a background thread alongside the inference path.

Retrain flow
------------
1. Query DB-02 (cost_1min_agg) for rows in the lookback window.
2. Apply FEA-04 (TimeContextFeatures) to add hour_of_day / day_of_week.
3. Call TimeSeriesBaselineModel.fit_group(df).
4. Persist artifacts via model.save() (TS-05 versioning hooks into this).
5. Log outcome (row count, duration, artifact path).

Components
----------
RetrainConfig        – all tuneable parameters in one dataclass
RetrainJob           – stateless callable; can be invoked directly or by
                       the scheduler
RetrainScheduler     – wraps APScheduler BackgroundScheduler; starts /
                       stops with the container lifecycle

Standalone entry point
----------------------
Run a one-shot retrain (e.g. from a K8s CronJob):

    python -m ml.src.training.retrain

Scheduler entry point (embedded in ML service):

    from ml.src.training.retrain import RetrainScheduler, RetrainConfig
    scheduler = RetrainScheduler(RetrainConfig(db_url=os.environ["DATABASE_URL"]))
    scheduler.start()           # non-blocking background thread
    ...
    scheduler.stop()
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ml.src.features.time_context import TimeContextFeatures
from ml.src.models.baseline import BaselineConfig, TimeSeriesBaselineModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RetrainConfig:
    """
    Parameters controlling when and how the baseline model is retrained.

    Attributes
    ----------
    db_url:
        SQLAlchemy-compatible connection string for the PostgreSQL database.
        If None the scheduler falls back to a DataFrame supplied directly to
        RetrainJob.run_from_dataframe().  Set via DATABASE_URL env var.
    agg_table:
        Name of the 1-minute aggregate table (DB-02).
    lookback_days:
        How many calendar days of aggregate rows to use as the training
        window.  Longer windows give more stable seasonal profiles but
        react more slowly to structural spend shifts.
    interval_hours:
        How often (in hours) to trigger a full retrain.  Default: 24 h.
    artifact_dir:
        Directory where model artifacts are written.  Passed through to
        BaselineConfig and model.save().
    min_train_rows:
        Minimum rows the query must return before attempting a fit.
        If fewer rows are present the job logs a warning and skips.
    baseline_config:
        Optional override for the BaselineConfig used when fitting.
        Defaults to BaselineConfig(artifact_dir=artifact_dir).
    on_success:
        Optional callback invoked after a successful retrain with the
        fitted model as the sole argument.  Use this to hot-swap the
        model reference in a running inference service.
    """

    db_url: Optional[str] = field(
        default_factory=lambda: os.environ.get("DATABASE_URL")
    )
    agg_table: str = "cost_1min_agg"
    lookback_days: int = 30
    interval_hours: int = 24
    artifact_dir: str = "ml/artifacts"
    min_train_rows: int = 60
    baseline_config: Optional[BaselineConfig] = None
    on_success: Optional[Callable[[TimeSeriesBaselineModel], None]] = None


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


class RetrainJob:
    """
    Stateless unit of work that re-fits and persists the baseline model.

    Separate from the scheduler so it can be unit-tested or invoked
    directly in scripts without starting a background thread.
    """

    def __init__(self, config: RetrainConfig) -> None:
        self.config = config
        self._baseline_cfg = config.baseline_config or BaselineConfig(
            artifact_dir=config.artifact_dir,
            min_train_rows=config.min_train_rows,
        )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def run(self) -> TimeSeriesBaselineModel:
        """
        Full pipeline: query DB → fit → save.

        Returns
        -------
        The newly fitted TimeSeriesBaselineModel.

        Raises
        ------
        RuntimeError  if db_url is not configured.
        ValueError    if the query returns fewer rows than min_train_rows.
        """
        if not self.config.db_url:
            raise RuntimeError(
                "RetrainConfig.db_url is not set. "
                "Provide a DATABASE_URL environment variable or pass "
                "db_url explicitly in RetrainConfig."
            )
        df = self._load_from_db()
        return self._fit_and_save(df)

    def run_from_dataframe(self, df: pd.DataFrame) -> TimeSeriesBaselineModel:
        """
        Fit on a pre-loaded DataFrame (testing / backfill use-cases).

        Parameters
        ----------
        df:
            1-minute aggregate rows with at least:
            bucket, account_id, service, region, total_cost.
        """
        return self._fit_and_save(df)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_from_db(self) -> pd.DataFrame:
        """Query DB-02 for the rolling lookback window."""
        # Import here so SQLAlchemy is only required when using DB mode
        from sqlalchemy import create_engine, text  # noqa: PLC0415

        cutoff = datetime.now(tz=timezone.utc) - timedelta(
            days=self.config.lookback_days
        )
        query = text(
            f"""
            SELECT
                bucket,
                account_id,
                service,
                region,
                total_cost,
                total_usage,
                event_count
            FROM {self.config.agg_table}
            WHERE bucket >= :cutoff
            ORDER BY account_id, service, region, bucket
            """
        )

        engine = create_engine(self.config.db_url)
        logger.info(
            "Querying %s for rows since %s",
            self.config.agg_table,
            cutoff.isoformat(),
        )
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"cutoff": cutoff})

        logger.info("Loaded %d rows from DB for retrain", len(df))
        return df

    def _fit_and_save(self, df: pd.DataFrame) -> TimeSeriesBaselineModel:
        """Apply FEA-04, fit model, persist artifact."""
        n = len(df)
        if n < self.config.min_train_rows:
            raise ValueError(
                f"Retrain skipped: only {n} rows available "
                f"(need >= {self.config.min_train_rows}).  "
                "Increase lookback_days or wait for more data."
            )

        # Attach hour_of_day / day_of_week via FEA-04
        df = TimeContextFeatures().transform(df)

        model = TimeSeriesBaselineModel(self._baseline_cfg)

        t0 = time.monotonic()
        model.fit_group(df)
        elapsed = time.monotonic() - t0

        artifact_path = model.save()
        logger.info(
            "Retrain complete: %d rows, fit in %.2fs, artifacts at %s",
            n,
            elapsed,
            artifact_path,
        )

        if self.config.on_success is not None:
            try:
                self.config.on_success(model)
            except Exception:
                logger.exception("on_success callback raised an exception")

        return model


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class RetrainScheduler:
    """
    Wraps APScheduler to run RetrainJob on a fixed interval.

    Lifecycle
    ---------
    scheduler = RetrainScheduler(config)
    scheduler.start()   # spawns a daemon background thread
    ...                 # inference service runs normally
    scheduler.stop()    # graceful shutdown (waits for running job to finish)

    The scheduler also exposes `trigger_now()` for on-demand retrains
    (e.g. after a bulk data load or from an admin API endpoint).

    Job overlap
    -----------
    APScheduler's default `max_instances=1` ensures a slow retrain does not
    stack up multiple concurrent jobs.  A missed trigger is dropped, not
    queued, which is the correct behaviour for a periodic fit job.
    """

    JOB_ID = "baseline_retrain"

    def __init__(self, config: RetrainConfig) -> None:
        self.config = config
        self._job = RetrainJob(config)
        self._scheduler = BackgroundScheduler(
            job_defaults={"max_instances": 1, "misfire_grace_time": 3600}
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler and schedule the retrain job."""
        trigger = IntervalTrigger(hours=self.config.interval_hours)
        self._scheduler.add_job(
            func=self._safe_run,
            trigger=trigger,
            id=self.JOB_ID,
            name="Baseline model retrain",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "RetrainScheduler started: interval=%dh, lookback=%dd, "
            "artifact_dir=%s",
            self.config.interval_hours,
            self.config.lookback_days,
            self.config.artifact_dir,
        )

    def stop(self, wait: bool = True) -> None:
        """Shut down the scheduler, optionally waiting for in-flight jobs."""
        self._scheduler.shutdown(wait=wait)
        logger.info("RetrainScheduler stopped")

    def trigger_now(self) -> None:
        """
        Fire the retrain job immediately, independent of the schedule.
        Useful for on-demand retrains triggered by an admin API call.
        """
        logger.info("RetrainScheduler: manual trigger requested")
        self._scheduler.add_job(
            func=self._safe_run,
            id=f"{self.JOB_ID}_manual",
            replace_existing=True,
        )

    @property
    def is_running(self) -> bool:
        return self._scheduler.running

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _safe_run(self) -> None:
        """
        Wrapper that catches all exceptions so a failed retrain never
        crashes the APScheduler thread (which would stop future runs).
        """
        logger.info("Retrain job starting")
        try:
            self._job.run()
        except Exception:
            logger.exception(
                "Retrain job failed — model artifact unchanged, "
                "inference continues with the previous version"
            )


# ---------------------------------------------------------------------------
# CLI entry point (one-shot retrain for K8s CronJob / manual backfill)
# ---------------------------------------------------------------------------


def _cli_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = RetrainConfig()
    job = RetrainJob(config)
    logger.info("One-shot retrain starting")
    try:
        model = job.run()
        logger.info("One-shot retrain succeeded, artifact: %s", model.config.artifact_dir)
    except Exception as exc:
        logger.error("One-shot retrain failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    _cli_main()
