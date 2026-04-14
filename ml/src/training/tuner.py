"""
ML-03: Contamination and anomaly-threshold tuning.

Finds the optimal values for two parameters that directly control how
sensitive the detection pipeline is:

    IsolationForestConfig.contamination
        The expected fraction of anomalies in the training set.  Controls the
        internal decision boundary inside sklearn's IsolationForest (the
        ``offset_`` attribute).  A value that is too low misses real anomalies
        (high false-negative rate); too high causes excessive false positives.

    ScoringConfig.anomaly_threshold
        The minimum ``anomaly_score`` (ENS-01 ensemble output, [0, 1]) required
        for a row to be flagged as ``is_anomaly = 1``.  Lower thresholds
        increase recall at the expense of precision.

Two tuning modes are supported
-------------------------------
Supervised (recommended — uses ground-truth labels):
    Provide a ``y_true`` Series of 0/1 labels alongside the scored DataFrame.
    The tuner sweeps a grid of parameter values, evaluates precision / recall /
    F1 at each point, and returns the value that maximises the target metric.
    Ground-truth labels are produced by the synthetic data generator
    (``generators.core.generate_labeled_events_dataframe``).

Unsupervised (fallback — no labels required):
    The tuner uses the expected anomaly rate (``TuningConfig.expected_anomaly_rate``)
    to pick parameters consistent with that rate:
      * contamination  → set directly to the expected rate.
      * anomaly_threshold → set to the ``(1 - rate)``-th percentile of the
        observed ``anomaly_score`` distribution on the supplied data.

Contamination tuning — score-based approach
-------------------------------------------
Refitting IsolationForest for every candidate contamination value is
computationally expensive and rarely necessary.  Because sklearn's
``score_samples()`` output is independent of the ``contamination`` parameter
(it only affects ``offset_``), each contamination value ``c`` is equivalent
to classifying the top ``c`` fraction of ``if_score`` as anomalies.  The
tuner therefore sweeps contamination candidates by varying the ``if_score``
percentile threshold **without refitting**, then selects the contamination
value whose threshold achieves the best label-agreement (supervised) or
matches the expected rate (unsupervised).

Outputs
-------
``TuningResult`` contains:
  best_contamination  – recommended value for IsolationForestConfig
  best_threshold      – recommended value for ScoringConfig.anomaly_threshold
  contamination_sweep – full DataFrame of metrics at each contamination step
  threshold_sweep     – full DataFrame of metrics at each threshold step
  if_config_patch     – dict ready to pass to IsolationForestConfig(**patch)
  scoring_config_patch– dict ready to pass to ScoringConfig(**patch)

Usage — supervised
------------------
from ml.src.training.tuner import AnomalyTuner, TuningConfig

tuner  = AnomalyTuner(TuningConfig(target_metric="f1"))
result = tuner.tune(scored_df, y_true=scored_df["is_anomaly"])

print(result.best_contamination)   # e.g. 0.05
print(result.best_threshold)       # e.g. 0.52
print(result.threshold_sweep)      # DataFrame with precision/recall/f1 at each step

# Apply to existing config objects
new_if_cfg      = IsolationForestConfig(**result.if_config_patch)
new_scoring_cfg = ScoringConfig(**result.scoring_config_patch)

Usage — unsupervised
--------------------
result = tuner.tune(scored_df)     # no y_true argument
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class TuningConfig:
    """
    Parameters controlling the tuning sweep.

    Attributes
    ----------
    contamination_grid:
        Candidate contamination fractions to evaluate.  Each value ``c``
        is interpreted as "the top ``c`` fraction of ``if_score`` values
        are anomalies."  Must be in (0, 0.5].
    threshold_grid:
        Candidate ``anomaly_threshold`` values for the ENS-01 ensemble
        score.  Swept against the ``anomaly_score`` column in the scored
        DataFrame.
    target_metric:
        Metric to maximise during supervised tuning.
        One of ``"f1"`` | ``"precision"`` | ``"recall"``.
    min_recall:
        When ``target_metric`` is ``"precision"``, the tuner ignores
        parameter values whose recall falls below this floor to avoid
        trivially high precision with zero detections.
    min_precision:
        When ``target_metric`` is ``"recall"``, the tuner ignores parameter
        values whose precision falls below this floor.
    expected_anomaly_rate:
        Used in unsupervised mode as both the contamination value and the
        denominator for the threshold percentile.
        Example: 0.05 → flag the top 5 % of anomaly scores, set
        contamination = 0.05.
    label_col:
        Name of the ground-truth binary column in the scored DataFrame
        (matches the synthetic generator's output: ``"is_anomaly"``).
    if_score_col:
        Column name of the Isolation Forest score in the scored DataFrame.
    anomaly_score_col:
        Column name of the ensemble anomaly score in the scored DataFrame.
    """

    contamination_grid: List[float] = field(
        default_factory=lambda: [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
    )
    threshold_grid: List[float] = field(
        default_factory=lambda: [
            0.30, 0.35, 0.40, 0.42, 0.45, 0.48,
            0.50, 0.52, 0.55, 0.58, 0.60, 0.65,
            0.70, 0.75, 0.80,
        ]
    )
    target_metric: str = "f1"
    min_recall: float = 0.20
    min_precision: float = 0.10
    expected_anomaly_rate: float = 0.05
    label_col: str = "is_anomaly"
    if_score_col: str = "if_score"
    anomaly_score_col: str = "anomaly_score"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MetricRow:
    """
    Evaluation metrics at a single parameter value during a sweep.

    Attributes
    ----------
    param_value:
        The contamination fraction or threshold value evaluated.
    precision:
        TP / (TP + FP).  0.0 if no anomalies were predicted.
    recall:
        TP / (TP + FN).  0.0 if there are no true anomalies.
    f1:
        Harmonic mean of precision and recall.
    tp, fp, fn:
        Confusion matrix counts.
    n_predicted_anomaly:
        Total rows predicted as anomalous at this parameter value.
    """

    param_value: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    n_predicted_anomaly: int

    def to_dict(self) -> dict:
        return {
            "param_value": self.param_value,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "n_predicted_anomaly": self.n_predicted_anomaly,
        }


@dataclass
class TuningResult:
    """
    Complete output of an AnomalyTuner.tune() call.

    Attributes
    ----------
    best_contamination:
        Recommended value for ``IsolationForestConfig.contamination``.
    best_threshold:
        Recommended value for ``ScoringConfig.anomaly_threshold``.
    contamination_sweep:
        DataFrame with precision / recall / F1 at each contamination step.
        Columns: param_value, precision, recall, f1, tp, fp, fn,
                 n_predicted_anomaly.
    threshold_sweep:
        Same structure for the anomaly_score threshold sweep.
    method:
        ``"supervised"`` if labels were supplied, ``"unsupervised"``
        otherwise.
    n_samples:
        Total rows evaluated.
    n_true_anomalies:
        Rows where ``y_true == 1`` (0 in unsupervised mode).
    if_config_patch:
        Ready-to-use dict: ``IsolationForestConfig(**result.if_config_patch)``.
    scoring_config_patch:
        Ready-to-use dict: ``ScoringConfig(**result.scoring_config_patch)``.
    """

    best_contamination: float
    best_threshold: float
    contamination_sweep: pd.DataFrame
    threshold_sweep: pd.DataFrame
    method: str
    n_samples: int
    n_true_anomalies: int
    if_config_patch: dict
    scoring_config_patch: dict

    def summary(self) -> str:
        """
        One-paragraph human-readable summary of the tuning result.
        """
        lines = [
            f"Tuning method : {self.method}",
            f"Samples       : {self.n_samples:,}",
            f"True anomalies: {self.n_true_anomalies:,}  "
            f"({100 * self.n_true_anomalies / max(self.n_samples, 1):.1f}%)",
            f"Best contamin.: {self.best_contamination:.4f}",
            f"Best threshold: {self.best_threshold:.4f}",
        ]
        if not self.threshold_sweep.empty:
            best_row = self.threshold_sweep.loc[
                self.threshold_sweep["param_value"] == self.best_threshold
            ]
            if not best_row.empty:
                r = best_row.iloc[0]
                lines.append(
                    f"Metrics @ best: P={r['precision']:.3f}  "
                    f"R={r['recall']:.3f}  F1={r['f1']:.3f}"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tuner
# ---------------------------------------------------------------------------


class AnomalyTuner:
    """
    ML-03: Sweeps contamination and anomaly-threshold grids to find
    parameter values that best match observed anomaly behaviour.

    The tuner is stateless — it does not modify any model or config objects.
    All recommendations are returned in ``TuningResult``.

    Typical usage
    -------------
    # After scoring a labeled dataset with OnlineScorer:
    tuner  = AnomalyTuner()
    result = tuner.tune(scored_df, y_true=scored_df["is_anomaly"])

    # Apply recommendations:
    from ml.src.models.isolation_forest import IsolationForestConfig
    from ml.src.inference.scorer import ScoringConfig

    if_cfg      = IsolationForestConfig(**result.if_config_patch)
    scoring_cfg = ScoringConfig(**result.scoring_config_patch)
    """

    def __init__(self, config: TuningConfig | None = None) -> None:
        self.config = config or TuningConfig()
        _validate_config(self.config)

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def tune(
        self,
        scored_df: pd.DataFrame,
        y_true: Optional[pd.Series] = None,
    ) -> TuningResult:
        """
        Run contamination and threshold sweeps and return a TuningResult.

        Parameters
        ----------
        scored_df:
            Output of ``OnlineScorer.score()`` / ``score_group()``.  Must
            contain ``if_score_col`` and ``anomaly_score_col`` (see
            TuningConfig).  May contain a ground-truth label column.
        y_true:
            Optional binary 0/1 labels aligned to ``scored_df``.  When
            provided, supervised tuning is used.  When omitted, the tuner
            checks for a ``label_col`` column in ``scored_df``; if absent
            or all-NaN, unsupervised mode is used.

        Returns
        -------
        TuningResult with recommendations and full sweep DataFrames.
        """
        labels = self._resolve_labels(scored_df, y_true)
        method = "supervised" if labels is not None else "unsupervised"
        n_true = int(labels.sum()) if labels is not None else 0

        logger.info(
            "AnomalyTuner.tune: method=%s  samples=%d  true_anomalies=%d",
            method,
            len(scored_df),
            n_true,
        )

        # -- Contamination sweep -----------------------------------------
        if_scores = scored_df.get(self.config.if_score_col)
        cont_sweep, best_cont = self._sweep_contamination(if_scores, labels)

        # -- Threshold sweep ---------------------------------------------
        a_scores = scored_df.get(self.config.anomaly_score_col)
        thr_sweep, best_thr = self._sweep_threshold(a_scores, labels)

        return TuningResult(
            best_contamination=best_cont,
            best_threshold=best_thr,
            contamination_sweep=pd.DataFrame([r.to_dict() for r in cont_sweep]),
            threshold_sweep=pd.DataFrame([r.to_dict() for r in thr_sweep]),
            method=method,
            n_samples=len(scored_df),
            n_true_anomalies=n_true,
            if_config_patch={"contamination": best_cont},
            scoring_config_patch={"anomaly_threshold": best_thr},
        )

    # ------------------------------------------------------------------
    # Contamination tuning
    # ------------------------------------------------------------------

    def tune_contamination(
        self,
        if_scores: pd.Series,
        y_true: Optional[pd.Series] = None,
    ) -> tuple[float, pd.DataFrame]:
        """
        Find the best ``contamination`` value for IsolationForestConfig.

        Uses the score-based equivalence: contamination ``c`` corresponds to
        classifying the top ``c`` fraction of ``if_score`` as anomalies.
        No model refitting is needed.

        Parameters
        ----------
        if_scores:
            ``if_score`` column from a scored DataFrame (values in [0, 1],
            higher = more anomalous).
        y_true:
            Optional ground-truth labels (0/1).  If None, unsupervised
            tuning is used.

        Returns
        -------
        (best_contamination, sweep_df)
        """
        sweep, best = self._sweep_contamination(if_scores, y_true)
        return best, pd.DataFrame([r.to_dict() for r in sweep])

    # ------------------------------------------------------------------
    # Threshold tuning
    # ------------------------------------------------------------------

    def tune_threshold(
        self,
        anomaly_scores: pd.Series,
        y_true: Optional[pd.Series] = None,
    ) -> tuple[float, pd.DataFrame]:
        """
        Find the best ``anomaly_threshold`` for ScoringConfig.

        Parameters
        ----------
        anomaly_scores:
            ``anomaly_score`` column from a scored DataFrame (values in
            [0, 1]).
        y_true:
            Optional ground-truth labels.  If None, unsupervised tuning
            is used.

        Returns
        -------
        (best_threshold, sweep_df)
        """
        sweep, best = self._sweep_threshold(anomaly_scores, y_true)
        return best, pd.DataFrame([r.to_dict() for r in sweep])

    # ------------------------------------------------------------------
    # Internal: sweep implementations
    # ------------------------------------------------------------------

    def _sweep_contamination(
        self,
        if_scores: Optional[pd.Series],
        y_true: Optional[pd.Series],
    ) -> tuple[list[MetricRow], float]:
        """
        Sweep contamination grid.  Each value ``c`` is evaluated by
        thresholding ``if_score`` at ``percentile(if_score, 100*(1-c))``.
        """
        if if_scores is None or if_scores.isna().all():
            logger.warning(
                "if_score column missing or all-NaN. "
                "Returning expected_anomaly_rate as contamination."
            )
            return [], self.config.expected_anomaly_rate

        scores = if_scores.astype(float).fillna(0.0).to_numpy()

        if y_true is None:
            # Unsupervised: return expected rate directly
            best = self.config.expected_anomaly_rate
            sweep = self._build_unsupervised_contamination_sweep(scores)
            return sweep, float(np.clip(best, 0.001, 0.499))

        labels = y_true.astype(int).to_numpy()
        sweep: list[MetricRow] = []

        for c in self.config.contamination_grid:
            # Equivalent threshold: top c% of if_score are anomalies
            percentile_pct = 100.0 * (1.0 - c)
            cutoff = float(np.percentile(scores, percentile_pct))
            y_pred = (scores >= cutoff).astype(int)
            row = self._compute_metrics(c, labels, y_pred)
            sweep.append(row)

        best_c = self._pick_best(sweep)
        logger.info(
            "Contamination sweep: best=%.4f (P=%.3f R=%.3f F1=%.3f)",
            best_c,
            next(r.precision for r in sweep if r.param_value == best_c),
            next(r.recall for r in sweep if r.param_value == best_c),
            next(r.f1 for r in sweep if r.param_value == best_c),
        )
        return sweep, best_c

    def _sweep_threshold(
        self,
        anomaly_scores: Optional[pd.Series],
        y_true: Optional[pd.Series],
    ) -> tuple[list[MetricRow], float]:
        """
        Sweep anomaly_score threshold grid.
        """
        if anomaly_scores is None or anomaly_scores.isna().all():
            logger.warning(
                "anomaly_score column missing or all-NaN. "
                "Returning 0.55 as default threshold."
            )
            return [], 0.55

        scores = anomaly_scores.astype(float).fillna(0.0).to_numpy()

        if y_true is None:
            # Unsupervised: threshold at (1 - expected_rate) percentile
            rate = self.config.expected_anomaly_rate
            best_thr = float(np.percentile(scores, 100.0 * (1.0 - rate)))
            best_thr = float(np.clip(best_thr, 0.01, 0.99))
            sweep = self._build_unsupervised_threshold_sweep(scores)
            return sweep, best_thr

        labels = y_true.astype(int).to_numpy()
        sweep: list[MetricRow] = []

        for thr in self.config.threshold_grid:
            y_pred = (scores >= thr).astype(int)
            row = self._compute_metrics(thr, labels, y_pred)
            sweep.append(row)

        best_thr = self._pick_best(sweep)
        logger.info(
            "Threshold sweep: best=%.4f (P=%.3f R=%.3f F1=%.3f)",
            best_thr,
            next(r.precision for r in sweep if r.param_value == best_thr),
            next(r.recall for r in sweep if r.param_value == best_thr),
            next(r.f1 for r in sweep if r.param_value == best_thr),
        )
        return sweep, best_thr

    # ------------------------------------------------------------------
    # Internal: unsupervised sweep builders (produce informational rows)
    # ------------------------------------------------------------------

    def _build_unsupervised_contamination_sweep(
        self, scores: np.ndarray
    ) -> list[MetricRow]:
        """
        In unsupervised mode, return a sweep showing how many rows would be
        flagged at each contamination value (no precision/recall available).
        """
        rows = []
        for c in self.config.contamination_grid:
            cutoff = float(np.percentile(scores, 100.0 * (1.0 - c)))
            n_flagged = int((scores >= cutoff).sum())
            rows.append(
                MetricRow(
                    param_value=c,
                    precision=float("nan"),
                    recall=float("nan"),
                    f1=float("nan"),
                    tp=0,
                    fp=0,
                    fn=0,
                    n_predicted_anomaly=n_flagged,
                )
            )
        return rows

    def _build_unsupervised_threshold_sweep(
        self, scores: np.ndarray
    ) -> list[MetricRow]:
        """
        In unsupervised mode, return a sweep showing how many rows would be
        flagged at each threshold.
        """
        rows = []
        for thr in self.config.threshold_grid:
            n_flagged = int((scores >= thr).sum())
            rows.append(
                MetricRow(
                    param_value=thr,
                    precision=float("nan"),
                    recall=float("nan"),
                    f1=float("nan"),
                    tp=0,
                    fp=0,
                    fn=0,
                    n_predicted_anomaly=n_flagged,
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Internal: metric computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_metrics(
        param_value: float,
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> MetricRow:
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2.0 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return MetricRow(
            param_value=param_value,
            precision=precision,
            recall=recall,
            f1=f1,
            tp=tp,
            fp=fp,
            fn=fn,
            n_predicted_anomaly=tp + fp,
        )

    def _pick_best(self, sweep: list[MetricRow]) -> float:
        """
        Select the parameter value that maximises ``target_metric``,
        subject to the configured floor constraints.
        """
        if not sweep:
            return self.config.expected_anomaly_rate

        metric = self.config.target_metric
        min_recall = self.config.min_recall
        min_precision = self.config.min_precision

        # Filter by floor constraints
        candidates = [
            r for r in sweep
            if not (metric == "precision" and r.recall < min_recall)
            and not (metric == "recall" and r.precision < min_precision)
        ]
        if not candidates:
            # All candidates violate constraints — relax and take global best
            candidates = sweep

        if metric == "f1":
            best = max(candidates, key=lambda r: r.f1)
        elif metric == "precision":
            best = max(candidates, key=lambda r: r.precision)
        elif metric == "recall":
            best = max(candidates, key=lambda r: r.recall)
        else:
            raise ValueError(
                f"Unknown target_metric '{metric}'. "
                "Choose from 'f1', 'precision', 'recall'."
            )
        return best.param_value

    # ------------------------------------------------------------------
    # Internal: label resolution
    # ------------------------------------------------------------------

    def _resolve_labels(
        self,
        scored_df: pd.DataFrame,
        y_true: Optional[pd.Series],
    ) -> Optional[pd.Series]:
        """
        Determine which labels to use.

        Priority:
        1. Explicit ``y_true`` argument.
        2. Column ``label_col`` in ``scored_df`` (if present and not all-NaN).
        3. None → unsupervised mode.
        """
        if y_true is not None:
            labels = y_true.astype(int).reindex(scored_df.index)
            if labels.notna().any():
                return labels

        col = self.config.label_col
        if col in scored_df.columns:
            candidate = scored_df[col].astype(float)
            if candidate.notna().any():
                return candidate.astype(int)

        return None


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _validate_config(cfg: TuningConfig) -> None:
    for c in cfg.contamination_grid:
        if not (0.0 < c <= 0.5):
            raise ValueError(
                f"contamination_grid values must be in (0, 0.5]; got {c}."
            )
    for t in cfg.threshold_grid:
        if not (0.0 < t < 1.0):
            raise ValueError(
                f"threshold_grid values must be in (0, 1); got {t}."
            )
    if cfg.target_metric not in ("f1", "precision", "recall"):
        raise ValueError(
            f"target_metric must be 'f1', 'precision', or 'recall'; "
            f"got '{cfg.target_metric}'."
        )
    if not (0.0 < cfg.expected_anomaly_rate < 0.5):
        raise ValueError(
            "expected_anomaly_rate must be in (0, 0.5); "
            f"got {cfg.expected_anomaly_rate}."
        )
