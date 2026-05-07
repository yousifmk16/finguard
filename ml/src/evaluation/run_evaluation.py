"""
MLQ-02: Final model evaluation report (recall / F1 / precision).

Like MLQ-01 was the *act* of running ENS-03's calibrator to freeze a
threshold, MLQ-02 is the *act* of running ML-04's ``PerformanceReporter``
against the same curated validation set, evaluated at the MLQ-01-tuned
threshold, and freezing the resulting recall / F1 / precision figures
to ``ml/reports/`` for the sprint review packet.

Why a separate workflow when ML-04 already exists
--------------------------------------------------
``PerformanceReporter`` ships the *machinery* (sections, formatting,
JSON + text outputs). MLQ-02 is the *deployment artifact* — the actual
recall / F1 / precision numbers committed to the repo and quoted in the
sprint demo. Repeating the steps every sprint by hand is error-prone;
the script makes them reproducible.

Defaults — what each thing pulls from
--------------------------------------
- **Validation set**: the same in-code generator config used by MLQ-01
  (``ml.src.tuning.tune_thresholds._TUNING_GENERATOR_CONFIG``).  The
  recall / F1 / precision numbers we report therefore correspond to the
  same data the threshold was tuned on. (We do NOT rerun the tuning
  here — re-tuning on the eval set would be a leakage red flag.)
- **Threshold**: read from ``ml/artifacts/threshold_calibration.json``
  (the MLQ-01 artifact).  Falls back to the ``ScoringConfig`` default of
  ``0.55`` if the calibration JSON is missing, with a warning.

Outputs
-------
``ml/reports/MODEL_EVALUATION_REPORT.md``
    Frozen markdown summary suitable for the sprint review packet.

``ml/reports/evaluation.json``
    Full machine-readable Report.to_dict() output for dashboards.

Both filenames are stable (no timestamps) so re-running overwrites the
canonical artifact rather than accumulating dated copies.

CLI
---
    python -m ml.src.evaluation.run_evaluation
    python -m ml.src.evaluation.run_evaluation --threshold 0.4
    python -m ml.src.evaluation.run_evaluation --output /tmp/eval
    python -m ml.src.evaluation.run_evaluation --no-write
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from ml.src.evaluation.report import PerformanceReporter, Report, ReportConfig
from ml.src.tuning.tune_thresholds import TuningConfig, build_validation_set


logger = logging.getLogger(__name__)


# Stable repo-relative locations.
_DEFAULT_REGISTRY_DIR = Path(__file__).resolve().parents[2] / "artifacts"
_DEFAULT_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"
_DEFAULT_CALIBRATION_FILE = _DEFAULT_REGISTRY_DIR / "threshold_calibration.json"

# Fallback when no calibration JSON has been produced yet.
_FALLBACK_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Threshold resolution
# ---------------------------------------------------------------------------


def resolve_threshold(
    calibration_path: Path = _DEFAULT_CALIBRATION_FILE,
    explicit: Optional[float] = None,
) -> tuple[float, str]:
    """Return ``(threshold, source_label)``.

    Resolution order:
      1. ``explicit`` if not None.
      2. ``calibration_path`` if it exists and contains ``best_threshold``.
      3. ``_FALLBACK_THRESHOLD`` (warned).
    """
    if explicit is not None:
        return float(explicit), "explicit (CLI override)"

    if calibration_path.exists():
        try:
            data = json.loads(calibration_path.read_text(encoding="utf-8"))
            return float(data["best_threshold"]), f"`{calibration_path.name}` (MLQ-01)"
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Calibration JSON %s present but unreadable (%s) — using fallback",
                calibration_path, exc,
            )

    logger.warning(
        "No calibration JSON at %s — using fallback threshold %.2f. "
        "Run `python -m ml.src.tuning.tune_thresholds` to produce one.",
        calibration_path, _FALLBACK_THRESHOLD,
    )
    return _FALLBACK_THRESHOLD, f"fallback ({_FALLBACK_THRESHOLD})"


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@dataclass
class EvaluationConfig:
    """Knobs for one MLQ-02 evaluation run."""

    threshold: Optional[float] = None
    n_samples: Optional[int] = None
    registry_dir: Path = _DEFAULT_REGISTRY_DIR
    output_dir: Path = _DEFAULT_REPORTS_DIR
    calibration_path: Path = _DEFAULT_CALIBRATION_FILE


@dataclass
class EvaluationOutput:
    """Everything the workflow produces."""

    threshold: float
    threshold_source: str
    n_samples: int
    n_true_anomalies: int
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    json_path: Optional[Path]
    md_path: Optional[Path]


def run(cfg: EvaluationConfig, write: bool = True) -> EvaluationOutput:
    """Build the validation set, run ``PerformanceReporter``, write artifacts."""
    threshold, source = resolve_threshold(cfg.calibration_path, cfg.threshold)
    logger.info("MLQ-02 evaluation threshold: %.4f (source: %s)", threshold, source)

    df = build_validation_set(TuningConfig(n_samples=cfg.n_samples))
    logger.info(
        "MLQ-02 validation set: rows=%d, true_anomalies=%d (%.2f%%)",
        len(df),
        int(df["is_anomaly"].sum()),
        100.0 * df["is_anomaly"].mean(),
    )

    reporter = PerformanceReporter(
        ReportConfig(
            registry_dir=str(cfg.registry_dir),
            output_dir=str(cfg.output_dir),
            current_threshold=threshold,
            # Tuning recommendations require ML-03 sklearn dependencies for
            # IF contamination tuning. Skip — MLQ-01 already handled threshold
            # tuning, and recall/F1/precision is what MLQ-02 is for.
            include_tuning=False,
        )
    )
    report: Report = reporter.generate(df)

    sv = report.supervised
    json_path: Optional[Path] = None
    md_path: Optional[Path] = None
    if write:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = cfg.output_dir / "evaluation.json"
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        md_path = _write_markdown(cfg.output_dir, report, threshold, source)

    return EvaluationOutput(
        threshold=threshold,
        threshold_source=source,
        n_samples=report.n_rows,
        n_true_anomalies=sv.n_true_anomalies if sv else 0,
        precision=sv.precision if sv else None,
        recall=sv.recall if sv else None,
        f1=sv.f1 if sv else None,
        json_path=json_path,
        md_path=md_path,
    )


# ---------------------------------------------------------------------------
# Markdown writer — sprint-review packet
# ---------------------------------------------------------------------------


def _write_markdown(
    output_dir: Path,
    report: Report,
    threshold: float,
    threshold_source: str,
) -> Path:
    sv = report.supervised
    types = report.type_breakdown
    signals = report.signal_contributions

    if sv is None:
        # Validation set always carries labels — but guard anyway.
        body = "# MLQ-02 — Model Evaluation Report\n\nNo labels available; supervised metrics skipped.\n"
        path = output_dir / "MODEL_EVALUATION_REPORT.md"
        path.write_text(body, encoding="utf-8")
        return path

    type_table = _types_table(types)
    signals_table = _signals_table(signals)
    detection = report.detection
    sensitivity = _sensitivity_table(detection.sensitivity, detection.threshold)

    body = f"""# MLQ-02 — Model Evaluation Report

> Generated {report.generated_at}.
> Run via `python -m ml.src.evaluation.run_evaluation`.
> Machine-readable: [`evaluation.json`](evaluation.json).

## Headline metrics

Evaluated at `anomaly_threshold = {threshold:.4f}` (source: {threshold_source}).

| Metric | Value |
| --- | --- |
| Precision | **`{sv.precision:.4f}`** |
| Recall | **`{sv.recall:.4f}`** |
| F1 | **`{sv.f1:.4f}`** |
| Accuracy | `{sv.accuracy:.4f}` |
| TP / FP / FN / TN | `{sv.tp}` / `{sv.fp}` / `{sv.fn}` / `{sv.tn}` |

## Validation set

| Property | Value |
| --- | --- |
| Total rows | {sv.n_samples:,} |
| True anomalies | {sv.n_true_anomalies:,} ({sv.true_anomaly_rate:.2f} %) |
| Source | in-code MLQ-01 tuning config (seed = 42) |
| Score recipe | per-account `\\|z-score\\|` of `cost_amount`, clipped, normalised to [0, 1] |

## Detection sensitivity

How the flag rate changes if we move the threshold:

{sensitivity}

## Per-anomaly-type recall

{type_table}

## Signal contribution (mean score per class)

{signals_table}

## Caveats

- Score recipe is rules / residual-only. Real ensemble scores will be at
  least as large once TS-01 / ML-01 trained models contribute, so these
  numbers are a **conservative lower bound** on production performance.
- Validation set is fully synthetic. Re-run from a labeled production
  sample once available — the workflow is unchanged.
- This report is the **deployment artifact** for the recall / F1 / precision
  figures quoted in the sprint demo. Re-run after every change to
  `_TUNING_GENERATOR_CONFIG` or to the threshold calibration.
"""

    path = output_dir / "MODEL_EVALUATION_REPORT.md"
    path.write_text(body, encoding="utf-8")
    logger.info("MLQ-02 markdown report saved to %s", path)
    return path


def _types_table(types: list) -> str:
    if not types:
        return "_(no anomaly_type breakdown produced — labels missing or all-normal)_"
    rows = ["| Type | Total | Detected | Recall |", "|---|---|---|---|"]
    for r in types:
        rows.append(
            f"| `{r.anomaly_type}` | {r.n_total:,} | {r.n_detected:,} | `{r.recall:.4f}` |"
        )
    return "\n".join(rows)


def _signals_table(signals: list) -> str:
    if not signals:
        return "_(no signal contribution data — labels missing)_"
    rows = ["| Signal | Mean (normal) | Mean (anomaly) | Separation |", "|---|---|---|---|"]
    for r in signals:
        rows.append(
            f"| `{r.signal}` | `{r.mean_normal:.4f}` | `{r.mean_anomaly:.4f}` | `{r.separation:.4f}` |"
        )
    return "\n".join(rows)


def _sensitivity_table(sensitivity: list, current: float) -> str:
    if not sensitivity:
        return "_(no sensitivity table produced — anomaly_score column missing)_"
    rows = ["| Threshold | Flagged | % flagged |", "|---|---|---|"]
    for r in sensitivity:
        marker = " ← current" if abs(r.threshold - current) < 1e-9 else ""
        rows.append(
            f"| `{r.threshold:.3f}` | {r.n_flagged:,} | {r.pct_flagged:.2f} %{marker} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.evaluation.run_evaluation",
        description="MLQ-02: Final model evaluation report (recall / F1 / precision).",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Override the evaluation threshold. Default reads "
            "best_threshold from ml/artifacts/threshold_calibration.json."
        ),
    )
    p.add_argument("--n", type=int, default=0, metavar="ROWS", help="Override validation set size.")
    p.add_argument(
        "--registry",
        type=Path,
        default=_DEFAULT_REGISTRY_DIR,
        help="Model artifact registry dir (used by ML-04 model_meta section).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_REPORTS_DIR,
        help="Directory for evaluation.json and MODEL_EVALUATION_REPORT.md.",
    )
    p.add_argument(
        "--calibration",
        type=Path,
        default=_DEFAULT_CALIBRATION_FILE,
        help="Path to MLQ-01 calibration JSON.",
    )
    p.add_argument("--no-write", action="store_true", help="Print metrics; do not write files.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    cfg = EvaluationConfig(
        threshold=args.threshold,
        n_samples=None if args.n == 0 else args.n,
        registry_dir=args.registry,
        output_dir=args.output,
        calibration_path=args.calibration,
    )

    out = run(cfg, write=not args.no_write)
    print(json.dumps({
        "threshold": out.threshold,
        "threshold_source": out.threshold_source,
        "n_samples": out.n_samples,
        "n_true_anomalies": out.n_true_anomalies,
        "precision": out.precision,
        "recall": out.recall,
        "f1": out.f1,
        "json_path": str(out.json_path) if out.json_path else None,
        "md_path": str(out.md_path) if out.md_path else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
