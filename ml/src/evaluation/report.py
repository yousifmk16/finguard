"""
ML-04: Model performance report.

Produces a structured, human-readable performance report for the FinGuard
anomaly detection pipeline.  The report analyses the output of OnlineScorer
(ML-02) and covers seven sections:

    1. Model registry metadata   — versions, training dates, row counts
    2. Score distribution        — percentile stats for every signal column
    3. Detection summary         — flags at current threshold + sensitivity table
    4. Supervised metrics        — precision / recall / F1 (when labels exist)
    5. Anomaly-type breakdown    — per-type recall using synthetic generator labels
    6. Signal contributions      — mean signal for normals vs anomalies
    7. Tuning recommendations    — best contamination + threshold from ML-03

The report is saved as two files:
    <output_dir>/report_<timestamp>.txt   — human-readable text
    <output_dir>/report_<timestamp>.json  — machine-readable JSON for dashboards

Typical usage — from scored data
---------------------------------
from ml.src.evaluation.report import PerformanceReporter, ReportConfig

reporter = PerformanceReporter(ReportConfig(registry_dir="ml/artifacts"))
report   = reporter.generate(scored_df)       # scored_df from OnlineScorer
paths    = reporter.save(report, "ml/reports")
print(report.to_text())

CLI usage (standalone script)
-----------------------------
# Score a labeled CSV and generate a report:
python -m ml.src.evaluation.report --input data/labeled.csv --output ml/reports

# Generate synthetic data, score it, then report (no external files needed):
python -m ml.src.evaluation.report --synthetic --output ml/reports
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


@dataclass
class ReportConfig:
    """
    Parameters controlling what the reporter analyses and where it writes.

    Attributes
    ----------
    registry_dir:
        Root directory of ModelVersionRegistry (TS-05).  Used to pull
        model metadata for Section 1.
    output_dir:
        Directory where report files are written.
    current_threshold:
        The anomaly_threshold currently in use by OnlineScorer (shown in
        Section 3 and used as the reference point in Section 7).
    current_contamination:
        The contamination value currently in IsolationForestConfig.
    sensitivity_thresholds:
        Threshold values included in the Section 3 sensitivity table.
    label_col:
        Column in the scored DataFrame containing 0/1 ground-truth labels.
        Set to None to skip supervised sections (4, 5, 6).
    anomaly_type_col:
        Column produced by the synthetic generator with per-type labels
        (spike / drift / level_shift / budget_breach / normal).
        Used by Section 5.
    include_tuning:
        Whether to run ML-03 AnomalyTuner and include Section 7.
    tuner_metric:
        Target metric for the tuner sweep (``"f1"`` | ``"precision"`` |
        ``"recall"``).
    signal_cols:
        Score columns to include in the distribution and contribution
        sections.  Absent columns are silently skipped.
    """

    registry_dir: str = "ml/artifacts"
    output_dir: str = "ml/reports"
    current_threshold: float = 0.55
    current_contamination: float | str = "auto"
    sensitivity_thresholds: List[float] = field(
        default_factory=lambda: [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80]
    )
    label_col: Optional[str] = "is_anomaly"
    anomaly_type_col: Optional[str] = "anomaly_type"
    include_tuning: bool = True
    tuner_metric: str = "f1"
    signal_cols: List[str] = field(
        default_factory=lambda: [
            "ts_signal",
            "if_score",
            "rule_score",
            "anomaly_score",
        ]
    )


# ---------------------------------------------------------------------------
# Report data model
# ---------------------------------------------------------------------------


@dataclass
class ModelMeta:
    latest_version: Optional[str]
    trained_at: Optional[str]
    train_rows: int
    lookback_days: int
    n_versions: int
    baseline_loaded: bool
    if_loaded: bool


@dataclass
class ScoreStats:
    col: str
    n_valid: int
    mean: float
    std: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    max: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThresholdRow:
    threshold: float
    n_flagged: int
    pct_flagged: float


@dataclass
class DetectionSummary:
    n_total: int
    n_flagged: int
    pct_flagged: float
    threshold: float
    sensitivity: List[ThresholdRow]


@dataclass
class SupervisedMetrics:
    n_samples: int
    n_true_anomalies: int
    true_anomaly_rate: float
    precision: float
    recall: float
    f1: float
    accuracy: float
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass
class TypeRow:
    anomaly_type: str
    n_total: int
    n_detected: int
    recall: float


@dataclass
class SignalRow:
    signal: str
    mean_normal: float
    mean_anomaly: float
    separation: float


@dataclass
class TuningReco:
    current_contamination: float | str
    recommended_contamination: float
    current_threshold: float
    recommended_threshold: float
    f1_at_recommended: Optional[float]
    method: str


@dataclass
class Report:
    """
    Fully structured report output from PerformanceReporter.generate().

    Sections that could not be computed (e.g. supervised metrics with no
    labels) are set to None.
    """

    generated_at: str
    n_rows: int
    model_meta: ModelMeta
    score_stats: List[ScoreStats]
    detection: DetectionSummary
    supervised: Optional[SupervisedMetrics]
    type_breakdown: List[TypeRow]
    signal_contributions: List[SignalRow]
    tuning: Optional[TuningReco]
    config: ReportConfig

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = {
            "generated_at": self.generated_at,
            "n_rows": self.n_rows,
            "model_meta": asdict(self.model_meta),
            "score_stats": [s.to_dict() for s in self.score_stats],
            "detection": {
                "n_total": self.detection.n_total,
                "n_flagged": self.detection.n_flagged,
                "pct_flagged": self.detection.pct_flagged,
                "threshold": self.detection.threshold,
                "sensitivity": [asdict(r) for r in self.detection.sensitivity],
            },
            "supervised": asdict(self.supervised) if self.supervised else None,
            "type_breakdown": [asdict(r) for r in self.type_breakdown],
            "signal_contributions": [asdict(r) for r in self.signal_contributions],
            "tuning": asdict(self.tuning) if self.tuning else None,
        }
        return d

    def to_text(self) -> str:
        """Render a multi-section human-readable report."""
        lines: List[str] = []
        sep = "=" * 60

        def h(title: str) -> None:
            lines.append("")
            lines.append(title)
            lines.append("-" * len(title))

        lines.append(sep)
        lines.append("  FinGuard — Model Performance Report")
        lines.append(f"  Generated : {self.generated_at}")
        lines.append(f"  Rows      : {self.n_rows:,}")
        lines.append(sep)

        # ── Section 1: Model registry ──────────────────────────────────
        h("[ 1 ]  MODEL REGISTRY")
        m = self.model_meta
        lines.append(f"  Versions registered : {m.n_versions}")
        lines.append(f"  Latest version      : {m.latest_version or 'none'}")
        lines.append(f"  Trained at          : {m.trained_at or '—'}")
        lines.append(f"  Training rows       : {m.train_rows:,}")
        lines.append(f"  Lookback days       : {m.lookback_days}")
        lines.append(
            f"  Baseline loaded     : {'YES' if m.baseline_loaded else 'NO  (model not found)'}"
        )
        lines.append(
            f"  IF loaded           : {'YES' if m.if_loaded else 'NO  (model not found)'}"
        )

        # ── Section 2: Score distribution ─────────────────────────────
        h("[ 2 ]  SCORE DISTRIBUTION")
        if self.score_stats:
            hdr = f"  {'signal':<18}  {'n':>6}  {'mean':>6}  {'std':>6}  {'p50':>6}  {'p90':>6}  {'p95':>6}  {'p99':>6}  {'max':>6}"
            lines.append(hdr)
            lines.append("  " + "─" * (len(hdr) - 2))
            for s in self.score_stats:
                lines.append(
                    f"  {s.col:<18}  {s.n_valid:>6,}  "
                    f"{s.mean:>6.3f}  {s.std:>6.3f}  "
                    f"{s.p50:>6.3f}  {s.p90:>6.3f}  "
                    f"{s.p95:>6.3f}  {s.p99:>6.3f}  {s.max:>6.3f}"
                )
        else:
            lines.append("  No score columns found.")

        # ── Section 3: Detection summary ───────────────────────────────
        h("[ 3 ]  DETECTION SUMMARY")
        d = self.detection
        lines.append(f"  Total rows     : {d.n_total:,}")
        lines.append(
            f"  Flagged        : {d.n_flagged:,}  ({d.pct_flagged:.2f}%)  "
            f"at threshold = {d.threshold:.3f}"
        )
        if d.sensitivity:
            lines.append("")
            lines.append(f"  {'threshold':>10}  {'flagged':>10}  {'pct':>8}")
            lines.append(f"  {'─'*10}  {'─'*10}  {'─'*8}")
            for row in d.sensitivity:
                marker = " ←" if abs(row.threshold - d.threshold) < 1e-9 else ""
                lines.append(
                    f"  {row.threshold:>10.3f}  {row.n_flagged:>10,}  "
                    f"{row.pct_flagged:>7.2f}%{marker}"
                )

        # ── Section 4: Supervised metrics ─────────────────────────────
        h("[ 4 ]  SUPERVISED METRICS")
        if self.supervised is None:
            lines.append("  No ground-truth labels available (unsupervised mode).")
        else:
            sv = self.supervised
            lines.append(f"  Labeled samples    : {sv.n_samples:,}")
            lines.append(
                f"  True anomalies     : {sv.n_true_anomalies:,}  "
                f"({sv.true_anomaly_rate:.2f}%)"
            )
            lines.append("")
            lines.append(f"  {'Metric':<14}  {'Value':>8}")
            lines.append(f"  {'─'*14}  {'─'*8}")
            lines.append(f"  {'Precision':<14}  {sv.precision:>8.4f}")
            lines.append(f"  {'Recall':<14}  {sv.recall:>8.4f}")
            lines.append(f"  {'F1':<14}  {sv.f1:>8.4f}")
            lines.append(f"  {'Accuracy':<14}  {sv.accuracy:>8.4f}")
            lines.append("")
            lines.append(f"  Confusion matrix   TP={sv.tp:,}  FP={sv.fp:,}  "
                         f"FN={sv.fn:,}  TN={sv.tn:,}")

        # ── Section 5: Anomaly-type breakdown ──────────────────────────
        h("[ 5 ]  ANOMALY-TYPE BREAKDOWN")
        if not self.type_breakdown:
            lines.append("  No anomaly_type column or no labeled rows.")
        else:
            lines.append(
                f"  {'type':<18}  {'total':>8}  {'detected':>9}  {'recall':>8}"
            )
            lines.append(f"  {'─'*18}  {'─'*8}  {'─'*9}  {'─'*8}")
            for r in self.type_breakdown:
                lines.append(
                    f"  {r.anomaly_type:<18}  {r.n_total:>8,}  "
                    f"{r.n_detected:>9,}  {r.recall:>8.3f}"
                )

        # ── Section 6: Signal contributions ───────────────────────────
        h("[ 6 ]  SIGNAL CONTRIBUTIONS  (mean score per class)")
        if not self.signal_contributions:
            lines.append("  No labels available for signal analysis.")
        else:
            lines.append(
                f"  {'signal':<18}  {'normal':>8}  {'anomaly':>8}  {'sep.':>8}"
            )
            lines.append(f"  {'─'*18}  {'─'*8}  {'─'*8}  {'─'*8}")
            for r in self.signal_contributions:
                lines.append(
                    f"  {r.signal:<18}  {r.mean_normal:>8.4f}  "
                    f"{r.mean_anomaly:>8.4f}  {r.separation:>8.4f}"
                )

        # ── Section 7: Tuning recommendations ─────────────────────────
        h("[ 7 ]  TUNING RECOMMENDATIONS")
        if self.tuning is None:
            lines.append("  Tuning not run (include_tuning=False).")
        else:
            t = self.tuning
            lines.append(f"  Method              : {t.method}")
            lines.append(
                f"  Contamination       : {t.current_contamination!s:<8}  →  "
                f"recommended {t.recommended_contamination:.4f}"
            )
            lines.append(
                f"  Anomaly threshold   : {t.current_threshold:.4f}      →  "
                f"recommended {t.recommended_threshold:.4f}"
            )
            if t.f1_at_recommended is not None:
                lines.append(f"  F1 at recommended   : {t.f1_at_recommended:.4f}")

        lines.append("")
        lines.append(sep)
        return "\n".join(lines)

    def save(self, output_dir: str | None = None) -> dict[str, Path]:
        """
        Write ``report_<timestamp>.txt`` and ``report_<timestamp>.json``
        to ``output_dir``.

        Returns
        -------
        dict with keys ``"text"`` and ``"json"`` mapping to the written Paths.
        """
        out = Path(output_dir or self.config.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        txt_path = out / f"report_{ts}.txt"
        json_path = out / f"report_{ts}.json"

        txt_path.write_text(self.to_text(), encoding="utf-8")
        json_path.write_text(
            json.dumps(self.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Report written to %s and %s", txt_path, json_path)
        return {"text": txt_path, "json": json_path}


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


class PerformanceReporter:
    """
    ML-04: Generates a full model performance report from a scored DataFrame.

    Usage
    -----
    reporter = PerformanceReporter(ReportConfig())
    report   = reporter.generate(scored_df)
    print(report.to_text())
    reporter.save(report)
    """

    def __init__(self, config: ReportConfig | None = None) -> None:
        self.config = config or ReportConfig()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def generate(
        self,
        scored_df: pd.DataFrame,
        y_true: Optional[pd.Series] = None,
    ) -> Report:
        """
        Analyse ``scored_df`` and produce a Report.

        Parameters
        ----------
        scored_df:
            Output of OnlineScorer.score() / score_group().  Expected columns:
            ``anomaly_score``, ``is_anomaly``, and optionally ``ts_signal``,
            ``if_score``, ``rule_score``.
        y_true:
            Optional ground-truth labels.  If None the reporter looks for
            ``config.label_col`` in ``scored_df``; if absent, supervised
            sections are skipped.
        """
        labels = self._resolve_labels(scored_df, y_true)

        meta = self._build_model_meta()
        stats = self._build_score_stats(scored_df)
        detection = self._build_detection(scored_df)
        supervised = self._build_supervised(scored_df, labels)
        type_breakdown = self._build_type_breakdown(scored_df, labels)
        signals = self._build_signal_contributions(scored_df, labels)
        tuning = self._build_tuning(scored_df, labels) if self.config.include_tuning else None

        return Report(
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            n_rows=len(scored_df),
            model_meta=meta,
            score_stats=stats,
            detection=detection,
            supervised=supervised,
            type_breakdown=type_breakdown,
            signal_contributions=signals,
            tuning=tuning,
            config=self.config,
        )

    # ------------------------------------------------------------------
    # Section 1: Model registry metadata
    # ------------------------------------------------------------------

    def _build_model_meta(self) -> ModelMeta:
        try:
            from ml.src.training.versioning import ModelVersionRegistry  # noqa: PLC0415

            registry = ModelVersionRegistry(self.config.registry_dir)
            versions = registry.list_versions()
            latest = versions[-1] if versions else None
            baseline_loaded = (
                Path(self.config.registry_dir) / "latest" / "baseline_seasonal_profile.json"
            ).exists()
            if_loaded = (
                Path(self.config.registry_dir) / "latest" / "if_model.pkl"
            ).exists()
            return ModelMeta(
                latest_version=latest.version if latest else None,
                trained_at=latest.trained_at if latest else None,
                train_rows=latest.train_rows if latest else 0,
                lookback_days=latest.lookback_days if latest else 0,
                n_versions=len(versions),
                baseline_loaded=baseline_loaded,
                if_loaded=if_loaded,
            )
        except Exception as exc:
            logger.debug("Could not read model registry: %s", exc)
            return ModelMeta(
                latest_version=None,
                trained_at=None,
                train_rows=0,
                lookback_days=0,
                n_versions=0,
                baseline_loaded=False,
                if_loaded=False,
            )

    # ------------------------------------------------------------------
    # Section 2: Score distribution
    # ------------------------------------------------------------------

    def _build_score_stats(self, df: pd.DataFrame) -> List[ScoreStats]:
        stats = []
        for col in self.config.signal_cols:
            if col not in df.columns:
                continue
            s = df[col].astype(float)
            valid = s.dropna()
            if valid.empty:
                continue
            pcts = np.percentile(valid, [25, 50, 75, 90, 95, 99])
            stats.append(
                ScoreStats(
                    col=col,
                    n_valid=len(valid),
                    mean=float(valid.mean()),
                    std=float(valid.std(ddof=1)) if len(valid) > 1 else 0.0,
                    p25=float(pcts[0]),
                    p50=float(pcts[1]),
                    p75=float(pcts[2]),
                    p90=float(pcts[3]),
                    p95=float(pcts[4]),
                    p99=float(pcts[5]),
                    max=float(valid.max()),
                )
            )
        return stats

    # ------------------------------------------------------------------
    # Section 3: Detection summary
    # ------------------------------------------------------------------

    def _build_detection(self, df: pd.DataFrame) -> DetectionSummary:
        n = len(df)
        thr = self.config.current_threshold

        anomaly_col = "anomaly_score" if "anomaly_score" in df.columns else None
        if anomaly_col is None:
            # fall back to is_anomaly binary if no continuous score
            is_anom = df.get("is_anomaly", pd.Series(dtype=int))
        else:
            is_anom = (df[anomaly_col].astype(float) >= thr).astype(int)

        n_flagged = int(is_anom.sum())
        pct = 100.0 * n_flagged / max(n, 1)

        sensitivity: List[ThresholdRow] = []
        if anomaly_col:
            scores = df[anomaly_col].astype(float)
            for t in self.config.sensitivity_thresholds:
                nf = int((scores >= t).sum())
                sensitivity.append(
                    ThresholdRow(
                        threshold=t,
                        n_flagged=nf,
                        pct_flagged=100.0 * nf / max(n, 1),
                    )
                )

        return DetectionSummary(
            n_total=n,
            n_flagged=n_flagged,
            pct_flagged=round(pct, 4),
            threshold=thr,
            sensitivity=sensitivity,
        )

    # ------------------------------------------------------------------
    # Section 4: Supervised metrics
    # ------------------------------------------------------------------

    def _build_supervised(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series],
    ) -> Optional[SupervisedMetrics]:
        if labels is None:
            return None

        thr = self.config.current_threshold
        anomaly_col = "anomaly_score" if "anomaly_score" in df.columns else "is_anomaly"

        if anomaly_col == "anomaly_score":
            y_pred = (df[anomaly_col].astype(float) >= thr).astype(int).to_numpy()
        else:
            y_pred = df[anomaly_col].fillna(0).astype(int).to_numpy()

        y_true = labels.astype(int).to_numpy()

        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        tn = int(((y_pred == 0) & (y_true == 0)).sum())

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        accuracy = (tp + tn) / max(len(y_true), 1)
        n_true = int(y_true.sum())

        return SupervisedMetrics(
            n_samples=len(y_true),
            n_true_anomalies=n_true,
            true_anomaly_rate=round(100.0 * n_true / max(len(y_true), 1), 4),
            precision=round(precision, 6),
            recall=round(recall, 6),
            f1=round(f1, 6),
            accuracy=round(accuracy, 6),
            tp=tp,
            fp=fp,
            fn=fn,
            tn=tn,
        )

    # ------------------------------------------------------------------
    # Section 5: Anomaly-type breakdown
    # ------------------------------------------------------------------

    def _build_type_breakdown(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series],
    ) -> List[TypeRow]:
        type_col = self.config.anomaly_type_col
        if labels is None or type_col is None or type_col not in df.columns:
            return []

        thr = self.config.current_threshold
        if "anomaly_score" in df.columns:
            y_pred = (df["anomaly_score"].astype(float) >= thr).astype(int)
        else:
            y_pred = df.get("is_anomaly", pd.Series(0, index=df.index)).astype(int)

        rows: List[TypeRow] = []
        anomaly_types = df.loc[labels == 1, type_col].unique()
        for atype in sorted(anomaly_types):
            if atype == "normal":
                continue
            mask = df[type_col] == atype
            total = int(mask.sum())
            detected = int((y_pred[mask] == 1).sum())
            recall = detected / total if total > 0 else 0.0
            rows.append(
                TypeRow(
                    anomaly_type=str(atype),
                    n_total=total,
                    n_detected=detected,
                    recall=round(recall, 6),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Section 6: Signal contributions
    # ------------------------------------------------------------------

    def _build_signal_contributions(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series],
    ) -> List[SignalRow]:
        if labels is None:
            return []

        rows: List[SignalRow] = []
        label_arr = labels.astype(int)
        normal_mask = label_arr == 0
        anomaly_mask = label_arr == 1

        for col in self.config.signal_cols:
            if col not in df.columns:
                continue
            vals = df[col].astype(float)
            mean_normal = float(vals[normal_mask].mean()) if normal_mask.any() else float("nan")
            mean_anomaly = float(vals[anomaly_mask].mean()) if anomaly_mask.any() else float("nan")
            sep = (
                mean_anomaly - mean_normal
                if not (np.isnan(mean_normal) or np.isnan(mean_anomaly))
                else float("nan")
            )
            rows.append(
                SignalRow(
                    signal=col,
                    mean_normal=round(mean_normal, 6),
                    mean_anomaly=round(mean_anomaly, 6),
                    separation=round(sep, 6),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Section 7: Tuning recommendations
    # ------------------------------------------------------------------

    def _build_tuning(
        self,
        df: pd.DataFrame,
        labels: Optional[pd.Series],
    ) -> Optional[TuningReco]:
        try:
            from ml.src.training.tuner import AnomalyTuner, TuningConfig  # noqa: PLC0415

            tuner = AnomalyTuner(
                TuningConfig(target_metric=self.config.tuner_metric)
            )
            result = tuner.tune(df, y_true=labels)

            f1_at_best: Optional[float] = None
            if not result.threshold_sweep.empty and "f1" in result.threshold_sweep.columns:
                row = result.threshold_sweep.loc[
                    result.threshold_sweep["param_value"] == result.best_threshold
                ]
                if not row.empty:
                    val = float(row["f1"].iloc[0])
                    f1_at_best = None if np.isnan(val) else round(val, 6)

            return TuningReco(
                current_contamination=self.config.current_contamination,
                recommended_contamination=round(result.best_contamination, 6),
                current_threshold=self.config.current_threshold,
                recommended_threshold=round(result.best_threshold, 6),
                f1_at_recommended=f1_at_best,
                method=result.method,
            )
        except Exception as exc:
            logger.warning("Tuning section skipped: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_labels(
        self,
        df: pd.DataFrame,
        y_true: Optional[pd.Series],
    ) -> Optional[pd.Series]:
        if y_true is not None:
            s = y_true.astype(int).reindex(df.index)
            if s.notna().any():
                return s
        col = self.config.label_col
        if col and col in df.columns:
            candidate = df[col].astype(float)
            if candidate.notna().any():
                return candidate.astype(int)
        return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.evaluation.report",
        description="Generate a FinGuard model performance report.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--input",
        metavar="PATH",
        help=(
            "Path to a CSV file containing a pre-scored DataFrame "
            "(output of OnlineScorer) or a labeled feature DataFrame. "
            "Must include at least 'anomaly_score' or 'is_anomaly' columns."
        ),
    )
    src.add_argument(
        "--synthetic",
        action="store_true",
        help=(
            "Generate synthetic data, run the full feature + scoring pipeline, "
            "and report on the result.  No external files required."
        ),
    )
    p.add_argument(
        "--output",
        metavar="DIR",
        default="ml/reports",
        help="Directory to write report files to (default: ml/reports).",
    )
    p.add_argument(
        "--registry",
        metavar="DIR",
        default="ml/artifacts",
        help="Model artifact registry directory (default: ml/artifacts).",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=0.55,
        help="Current anomaly_threshold to evaluate against (default: 0.55).",
    )
    p.add_argument(
        "--no-tuning",
        action="store_true",
        help="Skip ML-03 tuning recommendations (faster).",
    )
    p.add_argument(
        "--metric",
        choices=["f1", "precision", "recall"],
        default="f1",
        help="Target metric for tuning recommendations (default: f1).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress report text output to stdout.",
    )
    return p


def _run_synthetic_pipeline() -> pd.DataFrame:
    """
    Generate synthetic data, run features + scoring, return a scored DataFrame.
    Intended for quick self-contained demos and CI validation.
    """
    import os  # noqa: PLC0415

    # Inline minimal synthetic data — avoids requiring generators config file
    rng = np.random.default_rng(42)
    n = 500
    buckets = pd.date_range("2026-01-01", periods=n, freq="1min", tz="UTC")
    cost = rng.exponential(scale=100.0, size=n)
    # Inject a handful of spikes
    spike_idx = rng.choice(n, size=25, replace=False)
    cost[spike_idx] *= rng.uniform(5, 15, size=25)
    labels = np.zeros(n, dtype=int)
    labels[spike_idx] = 1

    df = pd.DataFrame(
        {
            "bucket": buckets,
            "account_id": "acct-demo",
            "service": "compute",
            "region": "us-east-1",
            "total_cost": cost,
            "total_usage": rng.uniform(10, 200, n),
            "event_count": rng.integers(1, 20, n),
            "is_anomaly": labels,
            "anomaly_type": np.where(labels == 1, "spike", "normal"),
        }
    )

    # Feature engineering
    try:
        from ml.src.features.extractor import RollingWindowExtractor  # noqa: PLC0415
        from ml.src.features.time_context import TimeContextFeatures  # noqa: PLC0415

        df = RollingWindowExtractor().transform_group(df)
        df = TimeContextFeatures().transform(df)
    except Exception as exc:
        logger.warning("Feature pipeline failed: %s — scoring on raw data.", exc)

    # Scoring — produce signal columns even if models are absent
    try:
        from ml.src.inference.scorer import OnlineScorer  # noqa: PLC0415

        scorer = OnlineScorer.from_artifacts()
        df = scorer.score_group(df)
    except Exception as exc:
        logger.warning("OnlineScorer failed: %s — adding placeholder scores.", exc)
        # Provide minimal scored columns so the report still runs
        df["anomaly_score"] = (df["total_cost"] - df["total_cost"].mean()) / (
            df["total_cost"].std() + 1e-9
        )
        df["anomaly_score"] = (
            df["anomaly_score"].clip(lower=0).pipe(
                lambda s: s / s.max() if s.max() > 0 else s
            )
        )
        df["is_anomaly"] = (df["anomaly_score"] >= 0.55).astype("int8")
        df["ts_signal"] = np.nan
        df["if_score"] = np.nan
        df["rule_score"] = 0.0

    return df


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── Load or generate data ──────────────────────────────────────────
    if args.synthetic:
        logger.info("Generating synthetic demo data...")
        scored_df = _run_synthetic_pipeline()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
            return 1
        logger.info("Loading scored data from %s", input_path)
        scored_df = pd.read_csv(input_path)

    # ── Build report ───────────────────────────────────────────────────
    cfg = ReportConfig(
        registry_dir=args.registry,
        output_dir=args.output,
        current_threshold=args.threshold,
        include_tuning=not args.no_tuning,
        tuner_metric=args.metric,
    )
    reporter = PerformanceReporter(cfg)
    report = reporter.generate(scored_df)

    # ── Output ─────────────────────────────────────────────────────────
    if not args.quiet:
        print(report.to_text())

    paths = report.save()
    logger.info("Saved: %s", "  |  ".join(str(p) for p in paths.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
