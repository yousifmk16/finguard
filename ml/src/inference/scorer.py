"""
ML-02: Online inference scoring pipeline (ENS-01 weighted score fusion).

Combines three complementary anomaly signals into a single per-row
`anomaly_score` [0, 1] and a binary `is_anomaly` decision flag:

    Signal          Source      Weight (default)
    ──────────────  ──────────  ────────────────
    ts_signal       TS-03       0.35   (z-score normalised to [0, 1])
    if_score        ML-01b      0.40   (Autoencoder reconstruction error)
    rule_score      RUL-01/03   0.25   (blended deterministic rules)

    anomaly_score = w_ts × ts_signal + w_if × if_score + w_rules × rule_score
    is_anomaly    = 1 if anomaly_score ≥ anomaly_threshold else 0

Design goals
------------
- **Online / low-latency**: operates on small DataFrames (one row up to a
  batch of recent minutes) without re-loading models per call.
- **Graceful degradation**: if a model artifact doesn't exist yet (e.g. the
  IF model hasn't been trained) the corresponding signal is zeroed and its
  weight redistributed automatically, so scoring still produces useful results.
- **Hot-swappable models**: `set_baseline()` / `set_detector()` can be wired
  as `on_success` callbacks in `RetrainConfig` so a background retrain
  atomically updates the live model reference without restarting the service.
- **Thread-safe**: all model reads/writes are protected by a reentrant lock.

Input
-----
A DataFrame with 1-minute aggregate rows that has already been passed through
the feature pipeline (FEA-01 + FEA-04).  Minimum required columns:

    bucket          datetime64[ns, UTC]
    account_id      str
    service         str
    region          str
    total_cost      float
    hour_of_day     int8            (FEA-04)
    day_of_week     int8            (FEA-04)
    total_cost_rollN_*              (FEA-01, optional — used by rules)

Call `score_group()` when the DataFrame contains multiple
(account_id, service, region) series; it processes each group independently
and reassembles the result on the original index.

Output columns appended to the input DataFrame
-----------------------------------------------
    ts_signal       float   Normalised z-score in [0, 1]; NaN if TS disabled.
    if_score        float   IF anomaly score in [0, 1]; NaN if IF disabled.
    if_anomaly      int8    Binary IF flag (1 = anomaly); NaN if IF disabled.
    rule_score      float   Blended rule score in [0, 1].
    anomaly_score   float   Final weighted ensemble score in [0, 1].
    is_anomaly      int8    1 if anomaly_score ≥ anomaly_threshold else 0.

Usage
-----
# Startup — load models once
scorer = OnlineScorer.from_artifacts(
    baseline_dir="ml/artifacts",
    if_dir="ml/artifacts",
)

# Per-event batch scoring (called by the stream consumer)
scored_df = scorer.score_group(feature_df)

# Hook into retrain pipeline for live model updates
config = RetrainConfig(
    db_url=os.environ["DATABASE_URL"],
    on_success=scorer.set_baseline,   # auto hot-swap after retrain
)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from ml.src.models.baseline import TimeSeriesBaselineModel
from ml.src.models.autoencoder import AutoencoderDetector
from ml.src.models.residuals import ResidualScorer, ResidualConfig
from ml.src.inference.severity import SeverityMapper, SeverityConfig
from services.rules.engine import (
    ThresholdBreachRule,
    SuddenJumpRule,
    SustainedIncreaseRule,
)
from services.rules.config import RULE_WEIGHTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of preceding rows used as the SuddenJumpRule window when no
# explicit rolling features are present.
_JUMP_LOOKBACK = 15

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ScoringConfig:
    """
    Parameters controlling the online scoring pipeline.

    Ensemble weights
    ----------------
    weight_ts, weight_if, weight_rules must sum to 1.0.  When a component
    is disabled (enable_ts / enable_if / enable_rules = False) the scorer
    automatically renormalises the remaining weights so they still sum to 1.

    Attributes
    ----------
    weight_ts:
        Contribution of the TS-03 z-score signal to the ensemble score.
    weight_if:
        Contribution of the ML-01 Isolation Forest signal.
    weight_rules:
        Contribution of the blended RUL-01/02/03 rule score.
    anomaly_threshold:
        Minimum anomaly_score to flip `is_anomaly` to 1.  Lower values
        increase recall at the expense of precision.
    z_score_cap:
        Value used to normalise `abs_z_score` to [0, 1].  Should match
        `ResidualConfig.clip_z_score` (default 10.0).
    enable_ts:
        Whether to run the time-series baseline + residual scorer.
        Disable if the baseline model has not yet been trained.
    enable_if:
        Whether to run the Isolation Forest detector.
    enable_rules:
        Whether to run the deterministic rule engine.
    target_col:
        Primary cost column name.
    group_cols:
        Columns that identify independent billing series.
    bucket_col:
        Name of the datetime bucket column.
    budget_limit:
        Override for RUL-01 ThresholdBreachRule budget ceiling.
        None → use RULE_THRESHOLDS default.
    jump_pct:
        Override for RUL-02 SuddenJumpRule percentage threshold.
    sustained_window:
        Override for RUL-03 SustainedIncreaseRule consecutive-period count.
    sustained_min_growth:
        Override for RUL-03 minimum per-period growth fraction.
    """

    # ENS-01 ensemble weights
    weight_ts: float = 0.35
    weight_if: float = 0.40
    weight_rules: float = 0.25

    # Final decision threshold
    anomaly_threshold: float = 0.55

    # Z-score normalisation cap (should match ResidualConfig.clip_z_score)
    z_score_cap: float = 10.0

    # Component toggles
    enable_ts: bool = True
    enable_if: bool = True
    enable_rules: bool = True

    # Column names
    target_col: str = "total_cost"
    group_cols: List[str] = field(
        default_factory=lambda: ["account_id", "service", "region"]
    )
    bucket_col: str = "bucket"

    # Rule threshold overrides (None → use services/rules/config.py defaults)
    budget_limit: Optional[float] = None
    jump_pct: Optional[float] = None
    sustained_window: Optional[int] = None
    sustained_min_growth: Optional[float] = None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class OnlineScorer:
    """
    ML-02: Real-time anomaly scoring via weighted fusion of TS, IF, and rules.

    Lifecycle
    ---------
    1. Instantiate with a ScoringConfig.
    2. Load model artifacts via `load_models()` or `from_artifacts()`.
    3. Call `score_group(df)` for each incoming batch of feature rows.
    4. Optionally hot-swap models via `set_baseline()` / `set_detector()`.

    Thread safety
    -------------
    Model references are protected by a reentrant lock.  A retrain thread can
    call `set_baseline()` or `set_detector()` while inference threads are
    active; each scoring call takes the lock only long enough to copy the
    model reference, so contention is minimal.
    """

    def __init__(
        self,
        config: ScoringConfig | None = None,
        severity_mapper: SeverityMapper | None = None,
    ) -> None:
        self.config = config or ScoringConfig()
        self._severity_mapper: Optional[SeverityMapper] = severity_mapper
        self._lock = threading.RLock()
        self._baseline: Optional[TimeSeriesBaselineModel] = None
        self._detector: Optional[AutoencoderDetector] = None
        self._residual_scorer = ResidualScorer(
            ResidualConfig(
                target_col=self.config.target_col,
                clip_z_score=self.config.z_score_cap,
            )
        )
        self._threshold_rule = ThresholdBreachRule(self.config.budget_limit)
        self._jump_rule = SuddenJumpRule(self.config.jump_pct)
        self._sustained_rule = SustainedIncreaseRule(
            self.config.sustained_window,
            self.config.sustained_min_growth,
        )

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_artifacts(
        cls,
        baseline_dir: str = "ml/artifacts",
        if_dir: str = "ml/artifacts",
        config: ScoringConfig | None = None,
        severity_mapper: SeverityMapper | None = None,
    ) -> "OnlineScorer":
        """
        Create a scorer and load both model artifacts in one call.

        Missing artifact directories are tolerated: the scorer will run
        with that component disabled and log a warning.

        Parameters
        ----------
        baseline_dir:
            Directory containing the TimeSeriesBaselineModel artifacts
            (baseline_config.json + baseline_seasonal_profile.json).
        if_dir:
            Directory containing the AutoencoderDetector artifacts
            (ae_model.pkl + ae_config.json + ae_meta.json).
        config:
            ScoringConfig instance.  Defaults to ScoringConfig().
        severity_mapper:
            Optional SeverityMapper (ENS-02).  When provided, every call to
            ``score()`` / ``score_group()`` appends a ``severity`` column.

        Returns
        -------
        Fully initialised OnlineScorer ready for inference.
        """
        scorer = cls(config, severity_mapper=severity_mapper)
        scorer.load_models(baseline_dir=baseline_dir, if_dir=if_dir)
        return scorer

    # ------------------------------------------------------------------
    # Model loading / hot-swap
    # ------------------------------------------------------------------

    def load_models(
        self,
        baseline_dir: str = "ml/artifacts",
        if_dir: str = "ml/artifacts",
    ) -> "OnlineScorer":
        """
        Load baseline and IF artifacts from disk.

        Errors are caught individually so a missing IF model does not
        prevent the baseline from loading (and vice versa).

        Returns self for chaining.
        """
        if self.config.enable_ts:
            try:
                model = TimeSeriesBaselineModel.load(baseline_dir)
                self.set_baseline(model)
                logger.info("Loaded baseline model from %s", baseline_dir)
            except FileNotFoundError:
                logger.warning(
                    "Baseline model not found at '%s'. "
                    "TS signal will be zero until the model is trained.",
                    baseline_dir,
                )

        if self.config.enable_if:
            try:
                detector = AutoencoderDetector.load(if_dir)
                self.set_detector(detector)
                logger.info("Loaded autoencoder detector from %s", if_dir)
            except FileNotFoundError:
                logger.warning(
                    "Autoencoder detector not found at '%s'. "
                    "AE signal will be zero until the model is trained.",
                    if_dir,
                )

        return self

    def set_baseline(self, model: TimeSeriesBaselineModel) -> None:
        """
        Atomically replace the live baseline model.

        Designed to be passed as `on_success` in RetrainConfig:

            RetrainConfig(db_url=..., on_success=scorer.set_baseline)
        """
        with self._lock:
            self._baseline = model
        logger.info("OnlineScorer: baseline model hot-swapped")

    def set_detector(self, detector: AutoencoderDetector) -> None:
        """
        Atomically replace the live autoencoder detector.

        Designed to be passed as `on_success` after an AE retrain job.
        """
        with self._lock:
            self._detector = detector
        logger.info("OnlineScorer: autoencoder detector hot-swapped")

    # ------------------------------------------------------------------
    # Public scoring API
    # ------------------------------------------------------------------

    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score a DataFrame that represents a **single** time series.

        Applies all enabled components and fuses scores into
        `anomaly_score` and `is_anomaly`.

        Parameters
        ----------
        df:
            Feature rows sorted ascending by `bucket_col`.  Must contain
            `target_col` and the FEA-04 time-context columns used by the
            baseline model.

        Returns
        -------
        Copy of `df` with additional columns (see module docstring).
        """
        with self._lock:
            baseline = self._baseline
            detector = self._detector

        result = df.copy()
        result = self._apply_ts(result, baseline)
        result = self._apply_if(result, detector)
        result = self._apply_rules(result)
        result = self._fuse(result)
        result = self._apply_severity(result)
        return result

    def score_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Score a multi-series DataFrame.

        Each (account_id, service, region) group is scored independently so
        that rule windows and rolling statistics don't bleed across series.
        The TS and IF models are shared across all groups.

        Returns
        -------
        Copy of `df` with score columns, preserving the original index.
        """
        group_keys = [k for k in self.config.group_cols if k in df.columns]

        if not group_keys:
            return self.score(df.sort_values(self.config.bucket_col))

        with self._lock:
            baseline = self._baseline
            detector = self._detector

        parts: list[pd.DataFrame] = []
        for _, group in df.groupby(group_keys, sort=False):
            group_sorted = group.sort_values(self.config.bucket_col)
            g = self._apply_ts(group_sorted, baseline)
            g = self._apply_if(g, detector)
            g = self._apply_rules(g)
            g = self._fuse(g)
            g = self._apply_severity(g)
            parts.append(g)

        return pd.concat(parts).reindex(df.index)

    # ------------------------------------------------------------------
    # Internal: TS-01/02/03 signal
    # ------------------------------------------------------------------

    def _apply_ts(
        self,
        df: pd.DataFrame,
        baseline: Optional[TimeSeriesBaselineModel],
    ) -> pd.DataFrame:
        """
        Run TimeSeriesBaselineModel → ResidualScorer → normalise abs_z_score
        into ts_signal [0, 1].

        If the baseline model is unavailable, ts_signal is set to NaN so
        ENS-01 can renormalise weights without it.
        """
        if not self.config.enable_ts or baseline is None:
            df["ts_signal"] = np.nan
            return df

        try:
            forecast = baseline.predict(df)
            scored = self._residual_scorer.transform(df, forecast)
            cap = max(self.config.z_score_cap, 1e-9)
            df["ts_signal"] = (
                scored["abs_z_score"].astype(float).clip(upper=cap) / cap
            )
        except Exception:
            logger.exception("TS scoring failed; ts_signal set to NaN")
            df["ts_signal"] = np.nan

        return df

    # ------------------------------------------------------------------
    # Internal: ML-01b Autoencoder signal
    # ------------------------------------------------------------------

    def _apply_if(
        self,
        df: pd.DataFrame,
        detector: Optional[AutoencoderDetector],
    ) -> pd.DataFrame:
        """
        Run AutoencoderDetector.predict().

        If the detector is unavailable, if_score and if_anomaly are NaN/0.
        """
        if not self.config.enable_if or detector is None:
            df["if_score"] = np.nan
            df["if_anomaly"] = np.int8(0)
            return df

        try:
            scored = detector.predict(df)
            df["if_score"] = scored["if_score"]
            df["if_anomaly"] = scored["if_anomaly"]
        except Exception:
            logger.exception("Autoencoder scoring failed; if_score set to NaN")
            df["if_score"] = np.nan
            df["if_anomaly"] = np.int8(0)

        return df

    # ------------------------------------------------------------------
    # Internal: Rule engine signal
    # ------------------------------------------------------------------

    def _apply_rules(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply RUL-01/02/03 to each row and produce a blended `rule_score`.

        Rules operate on the raw cost series so no pre-computed feature
        columns are required beyond `target_col`.
        """
        if not self.config.enable_rules:
            df["rule_score"] = 0.0
            return df

        try:
            df["rule_score"] = self._score_rules_vectorised(df)
        except Exception:
            logger.exception("Rule scoring failed; rule_score set to 0")
            df["rule_score"] = 0.0

        return df

    def _score_rules_vectorised(self, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate RUL-01/02/03 row-by-row on a time-ordered DataFrame.

        - RUL-01 (ThresholdBreachRule): scalar per row — vectorisable.
        - RUL-02 (SuddenJumpRule): uses `_JUMP_LOOKBACK` preceding rows
          as the comparison window.
        - RUL-03 (SustainedIncreaseRule): uses preceding `window + 1` rows.

        Returns a Series of blended scores aligned to `df.index`.
        """
        col = self.config.target_col
        costs = df[col].astype(float).to_list()
        n = len(costs)
        scores: list[float] = []

        w1 = RULE_WEIGHTS["threshold_breach"]
        w2 = RULE_WEIGHTS["sudden_jump"]
        w3 = RULE_WEIGHTS["sustained_increase"]

        sustained_lookback = self._sustained_rule.window

        for i in range(n):
            val = costs[i]

            # RUL-01
            r1 = self._threshold_rule.evaluate(val)

            # RUL-02: window = last _JUMP_LOOKBACK rows before current
            jump_window = costs[max(0, i - _JUMP_LOOKBACK):i]
            r2 = self._jump_rule.evaluate(val, jump_window)

            # RUL-03: series = rows [i-window .. i] inclusive
            sustained_series = costs[max(0, i - sustained_lookback):i + 1]
            r3 = self._sustained_rule.evaluate(sustained_series)

            blended = w1 * r1.score + w2 * r2.score + w3 * r3.score
            scores.append(blended)

        return pd.Series(scores, index=df.index, dtype=float)

    # ------------------------------------------------------------------
    # Internal: ENS-01 score fusion
    # ------------------------------------------------------------------

    def _fuse(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Weighted average of ts_signal, if_score, rule_score → anomaly_score.

        Components with NaN scores are excluded and the remaining weights
        are renormalised so they sum to 1.0.  If all components are NaN the
        anomaly_score falls back to 0.
        """
        cfg = self.config

        ts_vals = df.get("ts_signal", pd.Series(np.nan, index=df.index))
        if_vals = df.get("if_score", pd.Series(np.nan, index=df.index))
        rule_vals = df.get("rule_score", pd.Series(0.0, index=df.index))

        # Build component arrays and their weights
        components = [
            (ts_vals.astype(float), cfg.weight_ts if cfg.enable_ts else 0.0),
            (if_vals.astype(float), cfg.weight_if if cfg.enable_if else 0.0),
            (rule_vals.astype(float), cfg.weight_rules if cfg.enable_rules else 0.0),
        ]

        # Per-row weighted sum with dynamic NaN exclusion
        n = len(df)
        anomaly_scores = np.zeros(n, dtype=float)
        weight_sums = np.zeros(n, dtype=float)

        for values, weight in components:
            if weight == 0.0:
                continue
            arr = values.to_numpy()
            valid = ~np.isnan(arr)
            anomaly_scores = np.where(valid, anomaly_scores + weight * arr, anomaly_scores)
            weight_sums = np.where(valid, weight_sums + weight, weight_sums)

        # Renormalise where at least one component contributed
        safe_denom = np.where(weight_sums > 0.0, weight_sums, 1.0)
        anomaly_scores = np.where(weight_sums > 0.0, anomaly_scores / safe_denom, 0.0)

        df["anomaly_score"] = anomaly_scores
        df["is_anomaly"] = (anomaly_scores >= cfg.anomaly_threshold).astype("int8")
        return df

    # ------------------------------------------------------------------
    # Internal: ENS-02 severity mapping
    # ------------------------------------------------------------------

    def _apply_severity(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append a ``severity`` column if a SeverityMapper was configured.

        No-op when ``self._severity_mapper`` is None.
        """
        if self._severity_mapper is None:
            return df
        try:
            return self._severity_mapper.transform(df)
        except Exception:
            logger.exception("Severity mapping failed; severity column not added")
            return df

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def has_baseline(self) -> bool:
        """True if a baseline model has been loaded."""
        with self._lock:
            return self._baseline is not None

    @property
    def has_detector(self) -> bool:
        """True if an autoencoder detector has been loaded."""
        with self._lock:
            return self._detector is not None

    def status(self) -> dict:
        """
        Return a summary of the scorer's current state — useful for a
        health-check endpoint.

        Returns
        -------
        dict with keys: baseline_loaded, if_loaded, config (weights + threshold).
        """
        sev_cfg = self._severity_mapper.config if self._severity_mapper else None
        return {
            "baseline_loaded": self.has_baseline,
            "ae_loaded": self.has_detector,
            "config": {
                "weight_ts": self.config.weight_ts,
                "weight_if": self.config.weight_if,
                "weight_rules": self.config.weight_rules,
                "anomaly_threshold": self.config.anomaly_threshold,
                "enable_ts": self.config.enable_ts,
                "enable_if": self.config.enable_if,
                "enable_rules": self.config.enable_rules,
            },
            "severity": {
                "enabled": self._severity_mapper is not None,
                "low_medium_boundary": sev_cfg.low_medium_boundary if sev_cfg else None,
                "medium_high_boundary": sev_cfg.medium_high_boundary if sev_cfg else None,
            },
        }
