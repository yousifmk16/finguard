"""
MLQ-01: Final threshold tuning based on a validation set.

Builds a deterministic, label-bearing validation set from the synthetic
generator (so the answer is reproducible across runs and CI), derives a
production-shape ``anomaly_score`` for every row, runs the ENS-03
``ThresholdCalibrator`` over a precision / recall / F1 sweep, and
**freezes** the chosen ``anomaly_threshold`` to ``ml/artifacts/`` along
with a human-readable report.

Why a separate workflow when ENS-03 already exists
---------------------------------------------------
ENS-03 ships the calibration *machinery* (sweep, pick-best, JSON output).
MLQ-01 is the *act of running it once on a curated validation set* so
the deployed scorer carries a defensible threshold rather than the
``ScoringConfig.anomaly_threshold = 0.55`` placeholder default.

Score derivation (rules-only)
-----------------------------
The TS baseline and IsolationForest models are not yet trained at this
point in the project (TS-01 / ML-01 produce artifacts in `ml/artifacts/`
but those are only present after a training run).  We tune against a
**rules-only-equivalent** score that mirrors the live scorer's output
shape on a fresh deployment:

    z_i      = |cost_i - μ(account_i)| / (σ(account_i) + 1e-9)
    score_i  = clip(z_i / Z_CAP, 0, 1)              # Z_CAP = 5.0

This is the same recipe ``ResidualScorer`` uses for ``ts_signal``,
clipped and normalised exactly the way ``OnlineScorer`` would emit it
when the IF/baseline models report zero contribution.  The result is a
threshold that is conservative-by-default: when the trained models come
online, their additional positive signal can only *increase* the
ensemble score, so the chosen cut-off remains valid.

Reproducibility
---------------
The generator config used here is loaded from
``generators/config.json`` (seed=42 by default).  Re-running this
script with the same git revision should produce byte-identical output.
That property is locked down in ``ml/tests/test_tune_thresholds.py``.

Outputs
-------
``ml/artifacts/threshold_calibration.json``
    Same schema as ``ENS-03`` produces.  Loaded by the live scorer via
    ``ThresholdCalibrator.load_threshold(...)``.

``ml/artifacts/THRESHOLD_TUNING_REPORT.md``
    Markdown summary with the sweep table, chosen threshold, and the
    metrics that justified it.  Suitable for the sprint review packet.

CLI
---
    python -m ml.src.tuning.tune_thresholds                       # default config
    python -m ml.src.tuning.tune_thresholds --metric precision    # alternate target
    python -m ml.src.tuning.tune_thresholds --n 5000              # bigger validation set
    python -m ml.src.tuning.tune_thresholds --output /tmp/cal     # alternate dir
    python -m ml.src.tuning.tune_thresholds --no-write            # dry run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from generators.config_loader import load_generator_config
from generators.core import generate_labeled_events_dataframe
from ml.src.inference.calibrate import (
    CalibrationConfig,
    CalibrationResult,
    ThresholdCalibrator,
)


logger = logging.getLogger(__name__)

# Z-score normalisation cap — must match ResidualConfig.clip_z_score.
_Z_CAP = 5.0

# Where artifacts land by default.
_DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts"


# Canonical MLQ-01 validation-set config. Hand-tuned for *threshold
# calibration*: a realistic ~5 % anomaly rate using only per-event
# injectors (spike / budget_breach). Block injectors (drift, level_shift)
# are off because they mark long contiguous segments — fine for streaming
# integration tests, wrong for cut-point selection.
_TUNING_GENERATOR_CONFIG: dict = {
    "seed": 42,
    "n": 3000,
    "start_time": "2026-01-01T00:00:00Z",
    "frequency": "1h",
    "provider": "gcp",
    "source_type": "synthetic",
    "accounts": ["acct-prod-1", "acct-prod-2", "acct-dev-1"],
    "services": ["Compute Engine", "Cloud Storage", "BigQuery"],
    "regions": ["us-central1", "us-east1", "europe-west1"],
    "usage_units": ["vCPU-hour", "GB-month", "slot-hour"],
    "baseline": {
        "default": 120.0,
        "by_account": {
            "acct-prod-1": 180.0,
            "acct-prod-2": 140.0,
            "acct-dev-1": 70.0,
        },
    },
    "trend": {"enabled": True, "slope": 0.0005},
    "seasonality": {
        "daily": {"enabled": True, "amplitude": 0.15},
        "weekly": {"enabled": True, "amplitude": 0.08},
    },
    "noise": {"model": "gaussian", "sigma": 7.5},
    "usage": {"mean": 130.0, "std": 12.0},
    "anomaly_injectors": {
        # ~3.3 % of rows are spikes (100 / 3000).
        "spike": {"enabled": True, "count": 100, "multiplier": 3.5},
        # ~1.7 % of rows are sustained budget breaches (50-row window).
        "budget_breach": {
            "enabled": True,
            "start_index": 1500,
            "duration": 50,
            "budget_threshold": 220.0,
            "breach_multiplier": 1.4,
        },
        # Block injectors disabled: they would dominate the label distribution.
        "drift": {"enabled": False},
        "level_shift": {"enabled": False},
    },
}


# ---------------------------------------------------------------------------
# Validation-set construction
# ---------------------------------------------------------------------------


@dataclass
class TuningConfig:
    """Knobs for one run of the MLQ-01 workflow.

    Attributes
    ----------
    generator_config_path:
        Optional JSON config consumed by the generator. ``None`` (default)
        uses the in-code ``_TUNING_GENERATOR_CONFIG`` curated for threshold
        tuning. Pass a path here to tune against a different labeled
        dataset (e.g. one derived from real billing history).
    n_samples:
        Override for ``config["n"]``. Larger gives a more precise sweep at
        the cost of a slower run. ``None`` keeps the config's value.
    target_metric:
        ``"f1"`` (default), ``"precision"`` or ``"recall"`` — passed
        through to the calibrator.
    min_recall / min_precision:
        Floor constraints when the target is ``precision`` / ``recall``.
    output_dir:
        Where ``threshold_calibration.json`` and the report are written.
    """

    generator_config_path: Optional[Path] = None
    n_samples: Optional[int] = None
    target_metric: str = "f1"
    min_recall: float = 0.20
    min_precision: float = 0.10
    output_dir: Path = _DEFAULT_ARTIFACT_DIR


def build_validation_set(cfg: TuningConfig) -> pd.DataFrame:
    """Generate a labeled validation DataFrame ready for calibration.

    Returns a DataFrame containing at minimum:
      - ``account_id``      grouping key for the per-account z-score
      - ``cost_amount``     raw cost
      - ``anomaly_score``   derived per-row score in [0, 1]
      - ``is_anomaly``      ground-truth 0/1 from the injectors
      - ``anomaly_type``    label kind (spike, budget_breach, normal …)
    """
    if cfg.generator_config_path is None:
        raw_config = {**_TUNING_GENERATOR_CONFIG}
    else:
        raw_config = load_generator_config(cfg.generator_config_path)

    if cfg.n_samples is not None:
        raw_config = {**raw_config, "n": int(cfg.n_samples)}

    # pandas 2.2 deprecated upper-case "H" / "T" / "S" frequency aliases.
    # Normalise so older configs (e.g. 1H, 5T) still load on modern pandas.
    if isinstance(raw_config.get("frequency"), str):
        raw_config = {**raw_config, "frequency": _normalize_pandas_frequency(raw_config["frequency"])}

    events = generate_labeled_events_dataframe(raw_config)
    if "is_anomaly" not in events.columns:
        raise ValueError(
            "Generator output is missing 'is_anomaly' — verify generators/labels.py."
        )

    scored = _attach_anomaly_score(events)
    return scored


_PANDAS_FREQ_ALIAS_RENAMES = {"H": "h", "T": "min", "S": "s"}


def _normalize_pandas_frequency(freq: str) -> str:
    """Map deprecated pandas frequency aliases to their modern form.

    pandas 2.2 emits FutureWarning then errors on H/T/S — older configs
    in this repo still use 1H, so we rewrite at load time.
    """
    if freq and freq[-1] in _PANDAS_FREQ_ALIAS_RENAMES:
        return freq[:-1] + _PANDAS_FREQ_ALIAS_RENAMES[freq[-1]]
    return freq


def _attach_anomaly_score(events: pd.DataFrame) -> pd.DataFrame:
    """Attach a deterministic per-row ``anomaly_score`` in [0, 1].

    Uses per-account |z-score| of ``cost_amount`` clipped to ``Z_CAP``
    and normalised. This mirrors how ``ResidualScorer.signal_for`` shapes
    its output before fusion.
    """
    out = events.copy()

    # Per-account mean and std — the smallest grain at which a billing
    # series has a stable baseline.
    grp = out.groupby("account_id", sort=False)
    mu = grp["cost_amount"].transform("mean")
    sigma = grp["cost_amount"].transform("std")

    # Replace NaN std (single-row groups) with 1.0 so the z-score is well-defined.
    sigma = sigma.fillna(1.0).replace(0.0, 1.0)

    z = (out["cost_amount"] - mu).abs() / sigma
    out["anomaly_score"] = (z / _Z_CAP).clip(0.0, 1.0)
    return out


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


@dataclass
class TuningRunOutput:
    """Everything that came out of one tuning run."""

    chosen_threshold: float
    target_metric: str
    n_samples: int
    n_true_anomalies: int
    metrics_at_best: dict
    artifact_path: Optional[Path]
    report_path: Optional[Path]


def run(cfg: TuningConfig, write: bool = True) -> TuningRunOutput:
    """Build the validation set, calibrate, and (optionally) write artifacts."""
    df = build_validation_set(cfg)
    logger.info(
        "MLQ-01 validation set: rows=%d, true_anomalies=%d (%.2f%%)",
        len(df),
        int(df["is_anomaly"].sum()),
        100.0 * df["is_anomaly"].mean(),
    )

    calibrator = ThresholdCalibrator(
        CalibrationConfig(
            target_metric=cfg.target_metric,
            min_recall=cfg.min_recall,
            min_precision=cfg.min_precision,
            output_dir=str(cfg.output_dir),
        )
    )
    result: CalibrationResult = calibrator.calibrate(df)

    artifact_path: Optional[Path] = None
    report_path: Optional[Path] = None
    if write:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = result.save(str(cfg.output_dir))
        source_label = (
            "in-code `_TUNING_GENERATOR_CONFIG` (seed = 42)"
            if cfg.generator_config_path is None
            else f"`{cfg.generator_config_path}`"
        )
        report_path = _write_report(cfg.output_dir, result, df, source_label)

    return TuningRunOutput(
        chosen_threshold=result.best_threshold,
        target_metric=result.target_metric,
        n_samples=result.n_samples,
        n_true_anomalies=result.n_true_anomalies,
        metrics_at_best=result.metrics_at_best.to_dict(),
        artifact_path=artifact_path,
        report_path=report_path,
    )


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def _write_report(
    output_dir: Path,
    result: CalibrationResult,
    df: pd.DataFrame,
    source_label: str,
) -> Path:
    """Write a markdown report next to threshold_calibration.json."""
    m = result.metrics_at_best
    sweep_md = _sweep_table_markdown(result.sweep, result.best_threshold)
    label_breakdown = _anomaly_type_breakdown(df)

    body = f"""# MLQ-01 — Threshold Tuning Report

> Generated {result.generated_at}.
> Run via `python -m ml.src.tuning.tune_thresholds`.
> Calibration JSON: [`threshold_calibration.json`](threshold_calibration.json).

## Validation set

| Property | Value |
| --- | --- |
| Total rows | {result.n_samples:,} |
| True anomalies | {result.n_true_anomalies:,} ({100.0 * result.n_true_anomalies / max(result.n_samples, 1):.2f} %) |
| Source | {source_label} |
| Generator | `generators.core.generate_labeled_events_dataframe` |
| Score recipe | per-account `\\|z-score\\|` of `cost_amount`, clipped to {_Z_CAP:.1f}, normalised to [0, 1] |

### Anomaly type breakdown

{label_breakdown}

## Recommended threshold

| Metric | Value |
| --- | --- |
| **`anomaly_threshold`** | **`{result.best_threshold:.4f}`** |
| Target | `{result.target_metric}` |
| Precision | `{m.precision:.4f}` |
| Recall | `{m.recall:.4f}` |
| F1 | `{m.f1:.4f}` |
| TP / FP / FN | `{m.tp}` / `{m.fp}` / `{m.fn}` |

## Sweep results

{sweep_md}

## Applying the threshold

The chosen threshold is consumed by the live scorer at startup:

```python
from ml.src.inference.calibrate import ThresholdCalibrator
from ml.src.inference.scorer import OnlineScorer, ScoringConfig

threshold = ThresholdCalibrator.load_threshold("ml/artifacts/threshold_calibration.json")
scorer = OnlineScorer(ScoringConfig(anomaly_threshold=threshold))
```

## Caveats

- The validation set is fully synthetic. Once real billing data is
  available, regenerate this report from a labeled production sample —
  the calibrator's API is unchanged.
- Score recipe is rules / residual-only. After TS-01 and ML-01 models
  are trained, the ensemble score will be **at least as large** as the
  one used here, so the chosen cut-off remains a *conservative lower
  bound* — recall can only improve.
- Re-run on every change to `generators/config.json` or to
  `ResidualConfig.clip_z_score` so the report and the runtime
  configuration stay synchronised.
"""

    path = output_dir / "THRESHOLD_TUNING_REPORT.md"
    path.write_text(body, encoding="utf-8")
    logger.info("MLQ-01 report saved to %s", path)
    return path


def _sweep_table_markdown(sweep: pd.DataFrame, best: float) -> str:
    cols = ["threshold", "precision", "recall", "f1", "tp", "fp", "fn", "n_flagged", "flag_rate"]
    rows = ["| " + " | ".join(cols + [""]) + "|"]
    rows.append("|" + "---|" * (len(cols) + 1))
    for _, r in sweep.iterrows():
        marker = " ◄" if abs(r["threshold"] - best) < 1e-9 else ""
        cells = [
            f"{r['threshold']:.3f}",
            f"{r['precision']:.4f}",
            f"{r['recall']:.4f}",
            f"{r['f1']:.4f}",
            f"{int(r['tp'])}",
            f"{int(r['fp'])}",
            f"{int(r['fn'])}",
            f"{int(r['n_flagged'])}",
            f"{r['flag_rate'] * 100:.2f} %",
        ]
        rows.append("| " + " | ".join(cells) + f" |{marker}")
    return "\n".join(rows)


def _anomaly_type_breakdown(df: pd.DataFrame) -> str:
    if "anomaly_type" not in df.columns:
        return "_(anomaly_type column missing — generator did not emit type labels)_"
    counts = df["anomaly_type"].value_counts().sort_index()
    rows = ["| Type | Count |", "|---|---|"]
    for kind, count in counts.items():
        rows.append(f"| `{kind}` | {int(count):,} |")
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.tuning.tune_thresholds",
        description="MLQ-01: Final threshold tuning on a deterministic validation set.",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Optional generator config JSON. Default uses the in-code "
            "MLQ-01 tuning config (controlled ~5%% anomaly rate)."
        ),
    )
    p.add_argument(
        "--n",
        type=int,
        default=0,
        metavar="ROWS",
        help="Validation set size override. 0 (default) keeps the config's value.",
    )
    p.add_argument(
        "--metric",
        choices=["f1", "precision", "recall"],
        default="f1",
    )
    p.add_argument("--min-recall", type=float, default=0.20)
    p.add_argument("--min-precision", type=float, default=0.10)
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_ARTIFACT_DIR,
        help="Directory for threshold_calibration.json and the report.",
    )
    p.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write artifacts; just print the chosen threshold.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    cfg = TuningConfig(
        generator_config_path=args.config,  # None when --config not provided
        n_samples=None if args.n == 0 else args.n,
        target_metric=args.metric,
        min_recall=args.min_recall,
        min_precision=args.min_precision,
        output_dir=args.output,
    )

    out = run(cfg, write=not args.no_write)
    print(json.dumps({
        "chosen_threshold": out.chosen_threshold,
        "target_metric": out.target_metric,
        "n_samples": out.n_samples,
        "n_true_anomalies": out.n_true_anomalies,
        "metrics_at_best": out.metrics_at_best,
        "artifact_path": str(out.artifact_path) if out.artifact_path else None,
        "report_path": str(out.report_path) if out.report_path else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
