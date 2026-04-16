"""
ENS-03: Final decision threshold calibration script.

Sweeps candidate ``anomaly_threshold`` values against a labeled scored
DataFrame and selects the cut-point that best satisfies a target metric
(F1 / precision / recall).  The recommendation is written to a JSON file
that ``OnlineScorer`` (ENS-01) and ``SeverityMapper`` (ENS-02) can consume
without retraining.

Scope vs ML-03
--------------
ML-03 (``AnomalyTuner``) tunes **both** IsolationForest contamination and
the ensemble threshold, requiring the full scored DataFrame including
``if_score``.  ENS-03 is focused exclusively on the **final binary decision
boundary**: it only needs ``anomaly_score`` and ground-truth labels.  This
makes it cheap to run whenever the label distribution shifts (e.g. a new
anomaly type is added to the generator) without touching the IF model.

Output
------
``threshold_calibration.json`` written to ``output_dir`` (default: ml/artifacts):

    {
        "generated_at":   "2026-04-16T10:00:00+00:00",
        "method":         "supervised",          // or "unsupervised"
        "target_metric":  "f1",
        "best_threshold": 0.52,
        "metrics_at_best": {
            "precision": 0.88,
            "recall":    0.91,
            "f1":        0.895,
            "tp": 91, "fp": 12, "fn": 9
        },
        "sweep": [
            {"threshold": 0.30, "precision": ..., "recall": ..., "f1": ..., ...},
            ...
        ]
    }

Programmatic usage
------------------
from ml.src.inference.calibrate import ThresholdCalibrator, CalibrationConfig

cal    = ThresholdCalibrator()
result = cal.calibrate(scored_df, y_true=scored_df["is_anomaly"])
print(result.report_text())
result.save("ml/artifacts")

# Apply immediately:
from ml.src.inference.scorer import ScoringConfig
new_scoring_cfg = ScoringConfig(anomaly_threshold=result.best_threshold)

CLI usage
---------
python -m ml.src.inference.calibrate --input scored.csv --metric f1
python -m ml.src.inference.calibrate --synthetic --metric recall --min-precision 0.70
python -m ml.src.inference.calibrate --input scored.csv --no-save
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_GRID = [
    0.30, 0.35, 0.40, 0.42, 0.45, 0.48,
    0.50, 0.52, 0.55, 0.58, 0.60, 0.65,
    0.70, 0.75, 0.80, 0.85, 0.90,
]


@dataclass
class CalibrationConfig:
    """
    Parameters for the threshold sweep.

    Attributes
    ----------
    threshold_grid:
        Sorted list of candidate ``anomaly_threshold`` values to evaluate.
        Each value must be in (0, 1).
    target_metric:
        Objective to maximise: ``"f1"`` | ``"precision"`` | ``"recall"``.
    min_recall:
        When ``target_metric == "precision"``, candidates with recall below
        this floor are excluded so the calibrator does not return a threshold
        that detects almost nothing.
    min_precision:
        When ``target_metric == "recall"``, candidates with precision below
        this floor are excluded to avoid flooding the alert queue.
    expected_anomaly_rate:
        Fallback for unsupervised mode (no labels): the calibrator sets the
        threshold to the ``(1 - rate)``-th percentile of the score
        distribution.
    anomaly_score_col:
        Column containing the ENS-01 ensemble score.
    label_col:
        Column containing 0/1 ground-truth labels (may be absent).
    output_dir:
        Directory where ``threshold_calibration.json`` is written.
    """

    threshold_grid: List[float] = field(default_factory=lambda: _DEFAULT_GRID.copy())
    target_metric: str = "f1"
    min_recall: float = 0.20
    min_precision: float = 0.10
    expected_anomaly_rate: float = 0.05
    anomaly_score_col: str = "anomaly_score"
    label_col: str = "is_anomaly"
    output_dir: str = "ml/artifacts"

    def __post_init__(self) -> None:
        for t in self.threshold_grid:
            if not (0.0 < t < 1.0):
                raise ValueError(
                    f"threshold_grid values must be in (0, 1); got {t}."
                )
        if self.target_metric not in ("f1", "precision", "recall"):
            raise ValueError(
                f"target_metric must be 'f1', 'precision', or 'recall'; "
                f"got '{self.target_metric}'."
            )
        if not (0.0 < self.expected_anomaly_rate < 0.5):
            raise ValueError(
                f"expected_anomaly_rate must be in (0, 0.5); "
                f"got {self.expected_anomaly_rate}."
            )


# ---------------------------------------------------------------------------
# Row and result types
# ---------------------------------------------------------------------------


@dataclass
class ThresholdRow:
    """Metrics evaluated at a single candidate threshold."""

    threshold: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    n_flagged: int
    flag_rate: float   # fraction of total rows flagged

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CalibrationResult:
    """
    Complete output of ``ThresholdCalibrator.calibrate()``.

    Attributes
    ----------
    best_threshold:
        Recommended value for ``ScoringConfig.anomaly_threshold``.
    metrics_at_best:
        Precision / recall / F1 / TP / FP / FN at ``best_threshold``.
    sweep:
        Full evaluation table across all candidate thresholds.
    method:
        ``"supervised"`` if labels were present, ``"unsupervised"`` otherwise.
    n_samples:
        Total rows evaluated.
    n_true_anomalies:
        Rows where ``y_true == 1`` (0 in unsupervised mode).
    target_metric:
        The metric that was maximised.
    generated_at:
        ISO-8601 timestamp when the calibration was run.
    """

    best_threshold: float
    metrics_at_best: ThresholdRow
    sweep: pd.DataFrame
    method: str
    n_samples: int
    n_true_anomalies: int
    target_metric: str
    generated_at: str

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "method": self.method,
            "target_metric": self.target_metric,
            "best_threshold": self.best_threshold,
            "n_samples": self.n_samples,
            "n_true_anomalies": self.n_true_anomalies,
            "metrics_at_best": self.metrics_at_best.to_dict(),
            "sweep": self.sweep.to_dict(orient="records"),
        }

    def report_text(self) -> str:
        """
        Render a human-readable calibration report for stdout / log files.
        """
        sep = "=" * 60
        lines = [
            sep,
            "  FinGuard — Threshold Calibration Report  (ENS-03)",
            f"  Generated  : {self.generated_at}",
            f"  Method     : {self.method}",
            f"  Target     : {self.target_metric}",
            f"  Samples    : {self.n_samples:,}  "
            f"({self.n_true_anomalies:,} labeled anomalies, "
            f"{100 * self.n_true_anomalies / max(self.n_samples, 1):.1f}%)",
            sep,
        ]

        # Sweep table
        lines.append("")
        lines.append(
            f"  {'threshold':>9}  {'precision':>9}  {'recall':>8}  "
            f"{'f1':>8}  {'tp':>6}  {'fp':>6}  {'fn':>6}  "
            f"{'flagged':>8}  {'flag%':>6}"
        )
        lines.append(
            f"  {'─'*9}  {'─'*9}  {'─'*8}  {'─'*8}  "
            f"{'─'*6}  {'─'*6}  {'─'*6}  {'─'*8}  {'─'*6}"
        )
        for _, row in self.sweep.iterrows():
            marker = " ◄" if abs(row["threshold"] - self.best_threshold) < 1e-9 else ""
            p = row["precision"]
            r = row["recall"]
            f = row["f1"]
            p_str = f"{p:.4f}" if not (isinstance(p, float) and np.isnan(p)) else "  n/a  "
            r_str = f"{r:.4f}" if not (isinstance(r, float) and np.isnan(r)) else "  n/a  "
            f_str = f"{f:.4f}" if not (isinstance(f, float) and np.isnan(f)) else "  n/a  "
            lines.append(
                f"  {row['threshold']:>9.3f}  {p_str:>9}  {r_str:>8}  "
                f"{f_str:>8}  {int(row['tp']):>6}  {int(row['fp']):>6}  "
                f"{int(row['fn']):>6}  {int(row['n_flagged']):>8}  "
                f"{row['flag_rate'] * 100:>5.1f}%{marker}"
            )

        # Recommendation
        m = self.metrics_at_best
        lines += [
            "",
            "  Recommendation",
            "  ─────────────",
            f"  anomaly_threshold = {self.best_threshold:.4f}",
        ]
        if self.method == "supervised":
            lines += [
                f"  Precision         = {m.precision:.4f}",
                f"  Recall            = {m.recall:.4f}",
                f"  F1                = {m.f1:.4f}",
                f"  TP / FP / FN      = {m.tp} / {m.fp} / {m.fn}",
            ]
        else:
            lines.append(
                f"  (unsupervised — {self.n_samples * self.best_threshold:.0f} "
                "rows flagged at recommended rate)"
            )

        lines += ["", sep]
        return "\n".join(lines)

    def save(self, output_dir: str | None = None) -> Path:
        """
        Write ``threshold_calibration.json`` to ``output_dir``.

        Returns the path of the written file.
        """
        out = Path(output_dir or "ml/artifacts")
        out.mkdir(parents=True, exist_ok=True)
        path = out / "threshold_calibration.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Calibration result saved to %s", path)
        return path


# ---------------------------------------------------------------------------
# Calibrator
# ---------------------------------------------------------------------------


class ThresholdCalibrator:
    """
    ENS-03: Finds the optimal ``anomaly_threshold`` for the final ensemble
    decision boundary via a full precision / recall / F1 sweep.

    Usage
    -----
    cal    = ThresholdCalibrator()
    result = cal.calibrate(scored_df, y_true=scored_df["is_anomaly"])
    print(result.report_text())
    result.save("ml/artifacts")

    # Apply immediately to a new scorer:
    scorer = OnlineScorer(ScoringConfig(anomaly_threshold=result.best_threshold))
    """

    def __init__(self, config: CalibrationConfig | None = None) -> None:
        self.config = config or CalibrationConfig()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def calibrate(
        self,
        scored_df: pd.DataFrame,
        y_true: Optional[pd.Series] = None,
    ) -> CalibrationResult:
        """
        Sweep the threshold grid and return the optimal cut-point.

        Parameters
        ----------
        scored_df:
            Output of ``OnlineScorer.score()`` / ``score_group()``.
            Must contain ``config.anomaly_score_col`` (default:
            ``"anomaly_score"``).  May contain a ground-truth label column.
        y_true:
            Optional binary 0/1 labels aligned to ``scored_df``.  When
            provided the calibrator uses supervised mode.  When omitted it
            looks for ``config.label_col`` in ``scored_df``; absent or
            all-NaN → unsupervised mode.

        Returns
        -------
        CalibrationResult with ``best_threshold``, ``sweep`` DataFrame, and
        ``metrics_at_best``.
        """
        cfg = self.config
        col = cfg.anomaly_score_col

        if col not in scored_df.columns:
            raise ValueError(
                f"Column '{col}' not found. "
                "Run OnlineScorer.score() before calling calibrate()."
            )

        scores = scored_df[col].astype(float).fillna(0.0).to_numpy()
        labels = self._resolve_labels(scored_df, y_true)
        method = "supervised" if labels is not None else "unsupervised"
        n_true = int(labels.sum()) if labels is not None else 0
        n = len(scores)

        logger.info(
            "ThresholdCalibrator: method=%s  samples=%d  true_anomalies=%d",
            method, n, n_true,
        )

        if labels is not None:
            sweep_rows = self._supervised_sweep(scores, labels.to_numpy(), n)
            best_thr = self._pick_best(sweep_rows)
        else:
            sweep_rows = self._unsupervised_sweep(scores, n)
            rate = cfg.expected_anomaly_rate
            best_thr = float(np.clip(
                np.percentile(scores, 100.0 * (1.0 - rate)), 0.01, 0.99
            ))

        sweep_df = pd.DataFrame([r.to_dict() for r in sweep_rows])
        best_row = self._get_row(sweep_rows, best_thr) or sweep_rows[0]

        return CalibrationResult(
            best_threshold=best_thr,
            metrics_at_best=best_row,
            sweep=sweep_df,
            method=method,
            n_samples=n,
            n_true_anomalies=n_true,
            target_metric=cfg.target_metric,
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Convenience: load a saved calibration and apply it
    # ------------------------------------------------------------------

    @classmethod
    def load_threshold(cls, calibration_json: str | Path) -> float:
        """
        Read ``best_threshold`` from a previously saved calibration JSON.

        Parameters
        ----------
        calibration_json:
            Path to ``threshold_calibration.json`` produced by
            ``CalibrationResult.save()``.

        Returns
        -------
        The ``best_threshold`` float value.

        Raises
        ------
        FileNotFoundError if the file does not exist.
        KeyError if the JSON does not contain ``best_threshold``.
        """
        path = Path(calibration_json)
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data["best_threshold"])

    # ------------------------------------------------------------------
    # Internal: sweep implementations
    # ------------------------------------------------------------------

    def _supervised_sweep(
        self,
        scores: np.ndarray,
        labels: np.ndarray,
        n: int,
    ) -> list[ThresholdRow]:
        rows = []
        for thr in self.config.threshold_grid:
            y_pred = (scores >= thr).astype(int)
            tp = int(((y_pred == 1) & (labels == 1)).sum())
            fp = int(((y_pred == 1) & (labels == 0)).sum())
            fn = int(((y_pred == 0) & (labels == 1)).sum())

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (
                2.0 * precision * recall / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )
            n_flagged = tp + fp
            rows.append(
                ThresholdRow(
                    threshold=thr,
                    precision=round(precision, 6),
                    recall=round(recall, 6),
                    f1=round(f1, 6),
                    tp=tp,
                    fp=fp,
                    fn=fn,
                    n_flagged=n_flagged,
                    flag_rate=round(n_flagged / max(n, 1), 6),
                )
            )
        return rows

    def _unsupervised_sweep(
        self,
        scores: np.ndarray,
        n: int,
    ) -> list[ThresholdRow]:
        """Informational sweep: counts flagged rows without true labels."""
        rows = []
        for thr in self.config.threshold_grid:
            n_flagged = int((scores >= thr).sum())
            rows.append(
                ThresholdRow(
                    threshold=thr,
                    precision=float("nan"),
                    recall=float("nan"),
                    f1=float("nan"),
                    tp=0,
                    fp=0,
                    fn=0,
                    n_flagged=n_flagged,
                    flag_rate=round(n_flagged / max(n, 1), 6),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Internal: best-candidate selection
    # ------------------------------------------------------------------

    def _pick_best(self, sweep: list[ThresholdRow]) -> float:
        """
        Select the threshold that maximises ``target_metric`` subject to
        the configured floor constraints.

        Tie-breaking: when multiple thresholds share the best metric value,
        the **higher** threshold is preferred (more conservative — fewer
        false positives) unless the target is recall, in which case the
        **lower** threshold wins.
        """
        if not sweep:
            return 0.55

        metric = self.config.target_metric
        min_recall = self.config.min_recall
        min_precision = self.config.min_precision

        candidates = [
            r for r in sweep
            if not np.isnan(r.f1)
            and not (metric == "precision" and r.recall < min_recall)
            and not (metric == "recall" and r.precision < min_precision)
        ]
        if not candidates:
            candidates = [r for r in sweep if not np.isnan(r.f1)]
        if not candidates:
            return sweep[-1].threshold  # all NaN → return last value

        if metric == "f1":
            best_val = max(r.f1 for r in candidates)
            tied = [r for r in candidates if abs(r.f1 - best_val) < 1e-9]
            return max(r.threshold for r in tied)  # prefer higher (conservative)
        if metric == "precision":
            best_val = max(r.precision for r in candidates)
            tied = [r for r in candidates if abs(r.precision - best_val) < 1e-9]
            return max(r.threshold for r in tied)
        if metric == "recall":
            best_val = max(r.recall for r in candidates)
            tied = [r for r in candidates if abs(r.recall - best_val) < 1e-9]
            return min(r.threshold for r in tied)  # prefer lower (most recall)

        raise ValueError(f"Unknown target_metric: '{metric}'")

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_row(
        sweep: list[ThresholdRow], threshold: float
    ) -> Optional[ThresholdRow]:
        for r in sweep:
            if abs(r.threshold - threshold) < 1e-9:
                return r
        return None

    def _resolve_labels(
        self,
        scored_df: pd.DataFrame,
        y_true: Optional[pd.Series],
    ) -> Optional[pd.Series]:
        if y_true is not None:
            s = y_true.astype(int).reindex(scored_df.index)
            if s.notna().any():
                return s
        col = self.config.label_col
        if col in scored_df.columns:
            candidate = scored_df[col].astype(float)
            if candidate.notna().any():
                return candidate.astype(int)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.inference.calibrate",
        description=(
            "ENS-03: Calibrate the final anomaly_threshold for OnlineScorer."
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--input",
        metavar="PATH",
        help=(
            "Path to a CSV with at least 'anomaly_score' and optionally "
            "'is_anomaly' columns (output of OnlineScorer)."
        ),
    )
    src.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate synthetic scored data for a quick self-contained demo.",
    )
    p.add_argument(
        "--metric",
        choices=["f1", "precision", "recall"],
        default="f1",
        help="Target metric to maximise (default: f1).",
    )
    p.add_argument(
        "--min-recall",
        type=float,
        default=0.20,
        metavar="FLOAT",
        help=(
            "Min recall floor when optimising for precision (default: 0.20). "
            "Candidates below this floor are excluded."
        ),
    )
    p.add_argument(
        "--min-precision",
        type=float,
        default=0.10,
        metavar="FLOAT",
        help=(
            "Min precision floor when optimising for recall (default: 0.10). "
            "Candidates below this floor are excluded."
        ),
    )
    p.add_argument(
        "--output",
        metavar="DIR",
        default="ml/artifacts",
        help="Directory to write threshold_calibration.json (default: ml/artifacts).",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="Print the report but do not write the JSON file.",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress report text from stdout (JSON file still written).",
    )
    return p


def _make_synthetic_df() -> pd.DataFrame:
    """
    Quick synthetic scored DataFrame for --synthetic mode.

    Builds ~500 rows with injected spike anomalies.  The scoring pipeline
    is not re-run here; instead a simple z-score proxy stands in for
    anomaly_score so the script can run without trained models.
    """
    rng = np.random.default_rng(0)
    n = 500
    cost = rng.exponential(scale=100.0, size=n)
    spike_idx = rng.choice(n, size=30, replace=False)
    cost[spike_idx] *= rng.uniform(5, 15, size=30)
    labels = np.zeros(n, dtype=int)
    labels[spike_idx] = 1

    # Simple score proxy: normalised z-score
    mu, sigma = cost.mean(), cost.std() + 1e-9
    z = (cost - mu) / sigma
    anomaly_score = np.clip(z / (z.max() + 1e-9), 0.0, 1.0)

    return pd.DataFrame({
        "anomaly_score": anomaly_score,
        "is_anomaly": labels,
    })


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── Load / generate data ───────────────────────────────────────────
    if args.synthetic:
        logger.info("Generating synthetic demo data...")
        df = _make_synthetic_df()
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"ERROR: input file not found: {path}", file=sys.stderr)
            return 1
        logger.info("Loading scored data from %s", path)
        df = pd.read_csv(path)

    # ── Calibrate ─────────────────────────────────────────────────────
    cfg = CalibrationConfig(
        target_metric=args.metric,
        min_recall=args.min_recall,
        min_precision=args.min_precision,
        output_dir=args.output,
    )
    cal = ThresholdCalibrator(cfg)
    result = cal.calibrate(df)

    # ── Output ─────────────────────────────────────────────────────────
    if not args.quiet:
        print(result.report_text())

    if not args.no_save:
        saved_path = result.save(args.output)
        logger.info("Saved calibration to %s", saved_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
