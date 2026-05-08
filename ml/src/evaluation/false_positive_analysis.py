"""
MLQ-03: False-positive analysis.

Builds on top of MLQ-02. MLQ-02 freezes the *headline* recall / F1 / precision
numbers; MLQ-03 freezes the *failure-mode breakdown* — the question
"when the scorer is wrong, how is it wrong, and what would push it
further wrong?".

Why a separate workflow when MLQ-02 already prints precision
------------------------------------------------------------
MLQ-02's output is a single number per metric. Reviewers (and the sprint
demo) need more than that to trust the deployed threshold:

  * Which normals were flagged at the current cut-off (the realised FPs)?
  * Which normals are *closest* to flipping if the threshold drifts down
    (the borderline cases that decide precision robustness)?
  * How does the FP count and precision degrade across the threshold
    sweep, so we can quote the precision *margin*?
  * Are the borderline cases concentrated in a slice (account / service
    / region), which would suggest a per-slice threshold?
  * For completeness, where are the missed anomalies (FNs) sitting in
    score space — pure FP analysis is silent on misses, but the demo
    audience always asks the inverse question.

Defaults — what each thing pulls from
--------------------------------------
- **Validation set**: identical to MLQ-01 / MLQ-02 (same in-code
  generator config, seed = 42). Re-running here against a different
  set would invalidate any comparison with the headline metrics.
- **Threshold**: read from ``ml/artifacts/threshold_calibration.json``
  via the same resolver MLQ-02 uses. Falls back to ``0.55`` with a
  warning if the calibration JSON is missing.

Outputs
-------
``ml/reports/FALSE_POSITIVE_ANALYSIS.md``
    Frozen markdown summary suitable for the sprint review packet.

``ml/reports/false_positive_analysis.json``
    Full machine-readable analysis dict for dashboards / regression
    diffing.

Both filenames are stable (no timestamps) so re-running overwrites the
canonical artifact.

CLI
---
    python -m ml.src.evaluation.false_positive_analysis
    python -m ml.src.evaluation.false_positive_analysis --threshold 0.4
    python -m ml.src.evaluation.false_positive_analysis --top-k 25
    python -m ml.src.evaluation.false_positive_analysis --no-write
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

from ml.src.evaluation.run_evaluation import (
    _DEFAULT_CALIBRATION_FILE,
    _DEFAULT_REPORTS_DIR,
    resolve_threshold,
)
from ml.src.tuning.tune_thresholds import TuningConfig, build_validation_set


logger = logging.getLogger(__name__)


# Threshold sweep used to chart FP-count / precision degradation.
# Denser at the low end because that's where FPs first appear.
_DEFAULT_FP_SWEEP: tuple[float, ...] = (
    0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40,
    0.45, 0.50, 0.55, 0.60, 0.70, 0.80,
)

# How many cases to list in each "top-K" table by default.
_DEFAULT_TOP_K = 10


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class HeadlineCounts:
    """Confusion matrix at the current threshold."""

    threshold: float
    n_total: int
    n_normal: int
    n_anomaly: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    false_positive_rate: float


@dataclass
class CaseRow:
    """One row from a borderline / FP / FN table."""

    anomaly_score: float
    cost_amount: float
    account_id: str
    service: str
    region: str
    anomaly_type: str
    timestamp: str


@dataclass
class SweepRow:
    """One threshold along the FP-degradation curve."""

    threshold: float
    n_flagged: int
    fp: int
    tp: int
    precision: Optional[float]
    fp_rate: float


@dataclass
class SliceRow:
    """Per-dimension borderline-FP risk row."""

    dimension: str
    value: str
    n_normal: int
    fp_at_current: int
    mean_score_normal: float
    p95_score_normal: float
    max_score_normal: float


@dataclass
class FpAnalysis:
    """Full machine-readable MLQ-03 result."""

    generated_at: str
    threshold: float
    threshold_source: str
    n_rows: int
    headline: HeadlineCounts
    realised_false_positives: List[CaseRow]
    borderline_normals: List[CaseRow]
    sweep: List[SweepRow]
    slice_breakdowns: dict
    missed_detections_by_type: List[dict]
    near_threshold_misses: List[CaseRow]
    deeply_missed: List[CaseRow]

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "threshold": self.threshold,
            "threshold_source": self.threshold_source,
            "n_rows": self.n_rows,
            "headline": asdict(self.headline),
            "realised_false_positives": [asdict(r) for r in self.realised_false_positives],
            "borderline_normals": [asdict(r) for r in self.borderline_normals],
            "sweep": [asdict(r) for r in self.sweep],
            "slice_breakdowns": self.slice_breakdowns,
            "missed_detections_by_type": list(self.missed_detections_by_type),
            "near_threshold_misses": [asdict(r) for r in self.near_threshold_misses],
            "deeply_missed": [asdict(r) for r in self.deeply_missed],
        }


# ---------------------------------------------------------------------------
# Workflow config + output
# ---------------------------------------------------------------------------


@dataclass
class FpAnalysisConfig:
    """Knobs for one MLQ-03 run."""

    threshold: Optional[float] = None
    n_samples: Optional[int] = None
    top_k: int = _DEFAULT_TOP_K
    sweep_thresholds: tuple[float, ...] = _DEFAULT_FP_SWEEP
    output_dir: Path = _DEFAULT_REPORTS_DIR
    calibration_path: Path = _DEFAULT_CALIBRATION_FILE
    slice_dimensions: tuple[str, ...] = ("account_id", "service", "region")


@dataclass
class FpAnalysisOutput:
    """Everything the workflow produces."""

    threshold: float
    threshold_source: str
    n_samples: int
    n_false_positives: int
    n_false_negatives: int
    precision: float
    json_path: Optional[Path]
    md_path: Optional[Path]
    analysis: FpAnalysis = field(repr=False)


# ---------------------------------------------------------------------------
# Analysis primitives
# ---------------------------------------------------------------------------


def _confusion(df: pd.DataFrame, threshold: float) -> HeadlineCounts:
    """Build the headline confusion matrix at ``threshold``."""
    y_true = df["is_anomaly"].astype(int).to_numpy()
    y_pred = (df["anomaly_score"].astype(float) >= threshold).astype(int).to_numpy()

    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return HeadlineCounts(
        threshold=float(threshold),
        n_total=int(len(df)),
        n_normal=int((y_true == 0).sum()),
        n_anomaly=int((y_true == 1).sum()),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=round(precision, 6),
        recall=round(recall, 6),
        false_positive_rate=round(fpr, 6),
    )


def _to_case_rows(df: pd.DataFrame) -> List[CaseRow]:
    """Lift the dimensions we want to print into a list of CaseRow."""
    rows: List[CaseRow] = []
    for _, r in df.iterrows():
        rows.append(
            CaseRow(
                anomaly_score=round(float(r["anomaly_score"]), 6),
                cost_amount=round(float(r["cost_amount"]), 4),
                account_id=str(r.get("account_id", "")),
                service=str(r.get("service", "")),
                region=str(r.get("region", "")),
                anomaly_type=str(r.get("anomaly_type", "normal")),
                timestamp=str(r.get("timestamp", "")),
            )
        )
    return rows


def _realised_false_positives(
    df: pd.DataFrame, threshold: float, top_k: int
) -> List[CaseRow]:
    """Normals that *are* flagged at the current threshold, top-K by score."""
    mask = (df["is_anomaly"].astype(int) == 0) & (
        df["anomaly_score"].astype(float) >= threshold
    )
    fps = df.loc[mask].sort_values("anomaly_score", ascending=False).head(top_k)
    return _to_case_rows(fps)


def _borderline_normals(
    df: pd.DataFrame, threshold: float, top_k: int
) -> List[CaseRow]:
    """Highest-scoring true negatives — the normals closest to becoming FPs."""
    mask = (df["is_anomaly"].astype(int) == 0) & (
        df["anomaly_score"].astype(float) < threshold
    )
    near = df.loc[mask].sort_values("anomaly_score", ascending=False).head(top_k)
    return _to_case_rows(near)


def _sweep_curve(df: pd.DataFrame, thresholds: tuple[float, ...]) -> List[SweepRow]:
    """For each threshold, count flags / FPs / TPs and recompute precision."""
    y_true = df["is_anomaly"].astype(int).to_numpy()
    scores = df["anomaly_score"].astype(float).to_numpy()
    n_normal = int((y_true == 0).sum())
    rows: List[SweepRow] = []
    for t in thresholds:
        flagged = scores >= t
        tp = int((flagged & (y_true == 1)).sum())
        fp = int((flagged & (y_true == 0)).sum())
        n_flagged = int(flagged.sum())
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        fpr = fp / max(n_normal, 1)
        rows.append(
            SweepRow(
                threshold=round(float(t), 4),
                n_flagged=n_flagged,
                fp=fp,
                tp=tp,
                precision=round(precision, 6) if precision is not None else None,
                fp_rate=round(fpr, 6),
            )
        )
    return rows


def _slice_table(
    df: pd.DataFrame, dim: str, threshold: float
) -> List[SliceRow]:
    """Per-value risk row for one dimension, ordered by mean normal score."""
    if dim not in df.columns:
        return []
    normals = df.loc[df["is_anomaly"].astype(int) == 0]
    if normals.empty:
        return []

    rows: List[SliceRow] = []
    for value, group in normals.groupby(dim, sort=False):
        scores = group["anomaly_score"].astype(float)
        fp_at_current = int((scores >= threshold).sum())
        rows.append(
            SliceRow(
                dimension=dim,
                value=str(value),
                n_normal=int(len(group)),
                fp_at_current=fp_at_current,
                mean_score_normal=round(float(scores.mean()), 6),
                p95_score_normal=round(float(np.percentile(scores, 95)), 6)
                if len(scores) > 0 else 0.0,
                max_score_normal=round(float(scores.max()), 6),
            )
        )
    rows.sort(key=lambda r: r.mean_score_normal, reverse=True)
    return rows


def _missed_by_type(df: pd.DataFrame, threshold: float) -> List[dict]:
    """Per-anomaly-type miss table (FN count + miss rate + score stats)."""
    if "anomaly_type" not in df.columns:
        return []
    anomalies = df.loc[df["is_anomaly"].astype(int) == 1]
    if anomalies.empty:
        return []

    rows: List[dict] = []
    for atype, group in anomalies.groupby("anomaly_type", sort=False):
        if atype == "normal":
            continue  # generator never emits this for is_anomaly==1, guard anyway
        scores = group["anomaly_score"].astype(float)
        flagged = scores >= threshold
        n_total = int(len(group))
        n_missed = int((~flagged).sum())
        miss_rate = n_missed / max(n_total, 1)
        rows.append(
            {
                "anomaly_type": str(atype),
                "n_total": n_total,
                "n_missed": n_missed,
                "miss_rate": round(miss_rate, 6),
                "mean_score": round(float(scores.mean()), 6),
                "max_score": round(float(scores.max()), 6),
                "min_score": round(float(scores.min()), 6),
            }
        )
    rows.sort(key=lambda r: r["miss_rate"], reverse=True)
    return rows


def _near_threshold_misses(
    df: pd.DataFrame, threshold: float, top_k: int
) -> List[CaseRow]:
    """Anomalies just below threshold — highest-score FNs that almost flipped."""
    mask = (df["is_anomaly"].astype(int) == 1) & (
        df["anomaly_score"].astype(float) < threshold
    )
    rows = df.loc[mask].sort_values("anomaly_score", ascending=False).head(top_k)
    return _to_case_rows(rows)


def _deeply_missed(df: pd.DataFrame, threshold: float, top_k: int) -> List[CaseRow]:
    """Anomalies with the lowest scores — silent failures the scorer doesn't see at all."""
    mask = (df["is_anomaly"].astype(int) == 1) & (
        df["anomaly_score"].astype(float) < threshold
    )
    rows = df.loc[mask].sort_values("anomaly_score", ascending=True).head(top_k)
    return _to_case_rows(rows)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def analyse(df: pd.DataFrame, cfg: FpAnalysisConfig, threshold: float) -> FpAnalysis:
    """Pure analysis — takes a labeled scored frame, returns the result."""
    headline = _confusion(df, threshold)

    return FpAnalysis(
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        threshold=float(threshold),
        threshold_source="",  # filled in by run()
        n_rows=int(len(df)),
        headline=headline,
        realised_false_positives=_realised_false_positives(df, threshold, cfg.top_k),
        borderline_normals=_borderline_normals(df, threshold, cfg.top_k),
        sweep=_sweep_curve(df, cfg.sweep_thresholds),
        slice_breakdowns={
            dim: [asdict(r) for r in _slice_table(df, dim, threshold)]
            for dim in cfg.slice_dimensions
        },
        missed_detections_by_type=_missed_by_type(df, threshold),
        near_threshold_misses=_near_threshold_misses(df, threshold, cfg.top_k),
        deeply_missed=_deeply_missed(df, threshold, cfg.top_k),
    )


def run(cfg: FpAnalysisConfig, write: bool = True) -> FpAnalysisOutput:
    """Build the validation set, analyse it, write artifacts."""
    threshold, source = resolve_threshold(cfg.calibration_path, cfg.threshold)
    logger.info("MLQ-03 analysis threshold: %.4f (source: %s)", threshold, source)

    df = build_validation_set(TuningConfig(n_samples=cfg.n_samples))
    logger.info(
        "MLQ-03 validation set: rows=%d, true_anomalies=%d (%.2f%%)",
        len(df),
        int(df["is_anomaly"].sum()),
        100.0 * df["is_anomaly"].mean(),
    )

    analysis = analyse(df, cfg, threshold)
    analysis.threshold_source = source

    json_path: Optional[Path] = None
    md_path: Optional[Path] = None
    if write:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = cfg.output_dir / "false_positive_analysis.json"
        json_path.write_text(
            json.dumps(analysis.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        md_path = _write_markdown(cfg.output_dir, analysis)

    return FpAnalysisOutput(
        threshold=analysis.threshold,
        threshold_source=source,
        n_samples=analysis.n_rows,
        n_false_positives=analysis.headline.fp,
        n_false_negatives=analysis.headline.fn,
        precision=analysis.headline.precision,
        json_path=json_path,
        md_path=md_path,
        analysis=analysis,
    )


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------


def _write_markdown(output_dir: Path, a: FpAnalysis) -> Path:
    h = a.headline
    body = f"""# MLQ-03 — False-Positive Analysis

> Generated {a.generated_at}.
> Run via `python -m ml.src.evaluation.false_positive_analysis`.
> Machine-readable: [`false_positive_analysis.json`](false_positive_analysis.json).
> Headline metrics live in [`MODEL_EVALUATION_REPORT.md`](MODEL_EVALUATION_REPORT.md) (MLQ-02).

## Headline counts

Evaluated at `anomaly_threshold = {h.threshold:.4f}` (source: {a.threshold_source}).

| Metric | Value |
| --- | --- |
| Precision | **`{h.precision:.4f}`** |
| Recall | `{h.recall:.4f}` |
| False positive rate | **`{h.false_positive_rate:.4f}`** |
| TP / FP / FN / TN | `{h.tp}` / **`{h.fp}`** / `{h.fn}` / `{h.tn}` |
| Normals (n) / Anomalies (n) | `{h.n_normal:,}` / `{h.n_anomaly:,}` |

{_fp_summary_line(h)}

## Realised false positives at current threshold

{_case_table(a.realised_false_positives, "_(none — precision is 1.0 at this threshold)_")}

## Borderline normals (closest to flipping into FPs)

These are the **highest-scoring true negatives**. They are the rows that
would convert into false positives first if the threshold drifted down.
The gap between their scores and the current threshold is the precision
margin.

{_case_table(a.borderline_normals, "_(no normals in the validation set)_")}

## False-positive curve under threshold sweep

How FP count and precision evolve as the threshold moves. Use this to
quote the *precision margin*: the lowest threshold at which precision is
still acceptable.

{_sweep_table(a.sweep, h.threshold)}

## False-positive risk by slice

For each dimension, ranked by mean `anomaly_score` *over normals only*.
Slices with high mean / p95 normal scores are where a future FP is most
likely to appear if anything shifts upstream.

{_slice_section(a.slice_breakdowns)}

## Missed detections (false-negative complement)

A pure FP-only view is misleading when FP=0 by construction; the inverse
side of the same threshold is the FN set. This section is provided for
audit completeness and for triaging which anomaly types deserve a
score-recipe upgrade.

### Per-anomaly-type miss rate

{_miss_type_table(a.missed_detections_by_type)}

### Near-threshold misses (just below the cut-off)

These anomalies almost flipped — they are the cheapest wins for any
recall-improving change.

{_case_table(a.near_threshold_misses, "_(no near-threshold misses)_")}

### Deeply missed anomalies (lowest scores)

These anomalies are nowhere near the threshold and indicate a *score
recipe* gap, not a *threshold* gap.

{_case_table(a.deeply_missed, "_(no missed anomalies)_")}

## Caveats

- The validation set and threshold are identical to MLQ-02. Re-run this
  analysis whenever MLQ-02 is re-run so the two reports stay aligned.
- Score recipe is rules / residual-only. Once TS-01 / ML-01 trained
  models contribute, the *score distribution* on this exact validation
  set will shift; the FP curve below should be re-derived rather than
  carried over.
- Validation set is fully synthetic. Re-run from a labeled production
  sample once available — the workflow is unchanged.
"""

    path = output_dir / "FALSE_POSITIVE_ANALYSIS.md"
    path.write_text(body, encoding="utf-8")
    logger.info("MLQ-03 markdown report saved to %s", path)
    return path


def _fp_summary_line(h: HeadlineCounts) -> str:
    if h.fp == 0:
        return (
            "_No false positives at the current threshold. The borderline "
            "section below shows how much margin the threshold has._"
        )
    return (
        f"_**{h.fp} false positives** at the current threshold "
        f"(false-positive rate = {h.false_positive_rate:.4%}). The table "
        f"below lists the top-scoring ones._"
    )


def _case_table(rows: List[CaseRow], empty_text: str) -> str:
    if not rows:
        return empty_text
    header = (
        "| # | score | cost | account | service | region | type | timestamp |\n"
        "|---|---|---|---|---|---|---|---|"
    )
    lines = [header]
    for i, r in enumerate(rows, start=1):
        lines.append(
            f"| {i} | `{r.anomaly_score:.4f}` | `{r.cost_amount:,.2f}` | "
            f"`{r.account_id}` | `{r.service}` | `{r.region}` | "
            f"`{r.anomaly_type}` | `{r.timestamp}` |"
        )
    return "\n".join(lines)


def _sweep_table(rows: List[SweepRow], current: float) -> str:
    if not rows:
        return "_(no sweep produced)_"
    lines = [
        "| Threshold | Flagged | FP | TP | Precision | FP rate (vs normals) |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        marker = " ← current" if abs(r.threshold - current) < 1e-9 else ""
        prec = f"`{r.precision:.4f}`" if r.precision is not None else "`—`"
        lines.append(
            f"| `{r.threshold:.3f}` | {r.n_flagged:,} | {r.fp} | {r.tp} | "
            f"{prec} | `{r.fp_rate:.4f}`{marker} |"
        )
    return "\n".join(lines)


def _slice_section(slice_breakdowns: dict) -> str:
    if not slice_breakdowns:
        return "_(no slice dimensions configured)_"
    sections: List[str] = []
    for dim, rows in slice_breakdowns.items():
        if not rows:
            sections.append(f"### `{dim}`\n\n_(column not present in validation set)_")
            continue
        body = [
            f"### `{dim}`",
            "",
            "| value | n (normal) | FP @ current | mean score | p95 score | max score |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            body.append(
                f"| `{r['value']}` | {r['n_normal']:,} | {r['fp_at_current']} | "
                f"`{r['mean_score_normal']:.4f}` | `{r['p95_score_normal']:.4f}` | "
                f"`{r['max_score_normal']:.4f}` |"
            )
        sections.append("\n".join(body))
    return "\n\n".join(sections)


def _miss_type_table(rows: list) -> str:
    if not rows:
        return "_(no anomaly_type breakdown available)_"
    lines = [
        "| Type | Total | Missed | Miss rate | Mean score | Min score | Max score |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['anomaly_type']}` | {r['n_total']:,} | {r['n_missed']:,} | "
            f"`{r['miss_rate']:.4f}` | `{r['mean_score']:.4f}` | "
            f"`{r['min_score']:.4f}` | `{r['max_score']:.4f}` |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.evaluation.false_positive_analysis",
        description="MLQ-03: Frozen false-positive analysis.",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Override the analysis threshold. Default reads "
            "best_threshold from ml/artifacts/threshold_calibration.json."
        ),
    )
    p.add_argument(
        "--n",
        type=int,
        default=0,
        metavar="ROWS",
        help="Override validation set size (0 = use the canonical config).",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=_DEFAULT_TOP_K,
        help=f"Rows per case-listing table (default {_DEFAULT_TOP_K}).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_REPORTS_DIR,
        help="Directory for the JSON + markdown artifacts.",
    )
    p.add_argument(
        "--calibration",
        type=Path,
        default=_DEFAULT_CALIBRATION_FILE,
        help="Path to MLQ-01 calibration JSON.",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="Print the analysis summary; do not write files.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    cfg = FpAnalysisConfig(
        threshold=args.threshold,
        n_samples=None if args.n == 0 else args.n,
        top_k=args.top_k,
        output_dir=args.output,
        calibration_path=args.calibration,
    )

    out = run(cfg, write=not args.no_write)
    print(json.dumps({
        "threshold": out.threshold,
        "threshold_source": out.threshold_source,
        "n_samples": out.n_samples,
        "n_false_positives": out.n_false_positives,
        "n_false_negatives": out.n_false_negatives,
        "precision": out.precision,
        "json_path": str(out.json_path) if out.json_path else None,
        "md_path": str(out.md_path) if out.md_path else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
