"""
MLQ-04: Explainability quality examples.

EXP-01..04 ship the *machinery* that turns a scored row into a
structured, human-readable explanation:

    EXP-01  ForecastExplanation         – forecast vs actual gap (ML)
    EXP-02  RuleExplanation             – per-rule fired/score/reason (ML)
    EXP-03  ScoreBreakdown / to_dict()  – full payload (ML)
    EXP-04  AnomalyExplanationResponse  – Pydantic API schema (backend)

MLQ-04 is the *act of curating a frozen gallery of examples* run through
that machinery, vetted for quality, and committed to the repo. The
gallery serves three purposes:

  1. **Sprint-review evidence** that the explanation stack produces
     coherent output for representative anomaly types — not just that
     the code paths execute.
  2. **Regression fodder** for the EXP-04 Pydantic schema. Each example
     is round-tripped through ``format_explanation()`` so any future
     drift in ``ScoreBreakdown.to_dict()`` shape is caught here.
  3. **Demo material** for the user manual / API docs without needing a
     live deployment.

What the gallery covers
-----------------------
Cases are picked deterministically from the same validation set
MLQ-01 / MLQ-02 / MLQ-03 use (seed = 42). Picks are *labelled by intent*
so reviewers can see at a glance which quality axis each one exercises:

  * ``high_confidence_spike``
        TP with the highest score — the explanation must read decisively
        and the component breakdown must agree with the score.
  * ``sustained_budget_breach``
        Anomaly_type = budget_breach with rules fired — exercises the
        multi-rule narrative path in EXP-02.
  * ``borderline_normal``
        Highest-scoring true negative — the summary must NOT overclaim
        when the row is not flagged.
  * ``calm_normal``
        Lowest-scoring true negative — exercises the fully quiet path
        ("forecast holds; no rules fired").
  * ``missed_anomaly``
        Anomaly that fell below threshold — the explanation must remain
        honest ("not flagged") even when the label says it should be.

Score recipe
------------
TS-01 / ML-01 trained artifacts are not yet in the registry. To produce
explanations that are richer than rules-only, this script fabricates a
*conservative* forecast layer that matches the MLQ-01 score recipe
exactly: per-account mean / std of ``total_cost``, with z-score capped
at 5.0 and normalised to [0, 1] for ts_signal. ``if_score`` is left NaN
so the gallery also showcases the graceful-degradation path.

Each example is sent through the EXP-04 Pydantic schema; if any payload
fails ``AnomalyExplanationResponse.model_validate``, the whole script
errors out — the gallery is only published when the API contract holds.

Outputs
-------
``ml/reports/EXPLAINABILITY_EXAMPLES.md``
    Frozen markdown gallery suitable for the sprint review packet.

``ml/reports/explainability_examples.json``
    Machine-readable list of EXP-04 payloads, one per case.

Both filenames are stable (no timestamps) so re-running overwrites the
canonical artifact rather than accumulating dated copies.

CLI
---
    python -m ml.src.evaluation.explainability_examples
    python -m ml.src.evaluation.explainability_examples --threshold 0.4
    python -m ml.src.evaluation.explainability_examples --output /tmp/expq
    python -m ml.src.evaluation.explainability_examples --no-write
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.app.schemas.explanation import (
    AnomalyExplanationResponse,
    format_explanation,
)
from ml.src.evaluation.run_evaluation import (
    _DEFAULT_CALIBRATION_FILE,
    _DEFAULT_REPORTS_DIR,
    resolve_threshold,
)
from ml.src.inference.explain import ExplanationGenerator, ExplanationConfig
from ml.src.inference.rule_explain import RuleExplainer, RuleExplainerConfig
from ml.src.inference.score_breakdown import (
    ScoreBreakdown,
    ScoreBreakdownBuilder,
    ScoreBreakdownConfig,
)
from ml.src.inference.severity import SeverityConfig, SeverityMapper
from ml.src.tuning.tune_thresholds import TuningConfig, build_validation_set
from services.rules.config import RULE_WEIGHTS


logger = logging.getLogger(__name__)


# Z-score cap — must match MLQ-01 _Z_CAP and ResidualConfig.clip_z_score.
_Z_CAP = 5.0

# Default ensemble weights for the gallery (TS + rules; IF disabled).
_WEIGHT_TS = 0.35
_WEIGHT_IF = 0.40   # configured but inactive (if_score = NaN)
_WEIGHT_RULES = 0.25


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class CaseSelection:
    """A single curated example with the EXP-04 payload attached."""

    key: str
    intent: str  # one-line "what this case demonstrates"
    row_index: int
    label: int  # 1 = labeled anomaly, 0 = labeled normal
    anomaly_type: str
    flagged: bool
    payload: Dict  # output of AnomalyExplanationResponse.model_dump()


@dataclass
class GalleryConfig:
    """Knobs for one MLQ-04 run."""

    threshold: Optional[float] = None
    n_samples: Optional[int] = None
    output_dir: Path = _DEFAULT_REPORTS_DIR
    calibration_path: Path = _DEFAULT_CALIBRATION_FILE


@dataclass
class GalleryOutput:
    """Everything the workflow produces."""

    threshold: float
    threshold_source: str
    n_samples: int
    n_cases: int
    cases: List[CaseSelection] = field(repr=False)
    json_path: Optional[Path] = None
    md_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Score-recipe (mirrors MLQ-01) + manual fusion
# ---------------------------------------------------------------------------


def _attach_forecast_layer(df: pd.DataFrame) -> pd.DataFrame:
    """Add forecast / residual / ts_signal columns using MLQ-01's recipe.

    The aim is parity with the score MLQ-01..03 used so the threshold
    transfers directly. ``forecast_mean`` / ``forecast_std`` are simply
    the per-account mean / std of ``total_cost``.
    """
    out = df.copy()
    grp = out.groupby("account_id", sort=False)["total_cost"]
    mu = grp.transform("mean")
    sigma = grp.transform("std").fillna(1.0).replace(0.0, 1.0)

    out["forecast_mean"] = mu
    out["forecast_std"] = sigma
    out["residual"] = out["total_cost"] - mu
    out["z_score"] = out["residual"] / sigma
    out["abs_z_score"] = out["z_score"].abs()
    out["ci_lower_95"] = mu - 1.96 * sigma
    out["ci_upper_95"] = mu + 1.96 * sigma
    out["is_outside_ci_95"] = (
        (out["total_cost"] < out["ci_lower_95"])
        | (out["total_cost"] > out["ci_upper_95"])
    ).astype("int8")

    out["ts_signal"] = (out["abs_z_score"].clip(upper=_Z_CAP) / _Z_CAP).clip(0.0, 1.0)
    out["if_score"] = np.nan          # graceful-degradation showcase
    out["if_anomaly"] = np.int8(0)
    return out


def _blend_rule_score(df: pd.DataFrame) -> pd.Series:
    """Blend the three EXP-02 per-rule scores using ``RULE_WEIGHTS``.

    Mirrors the blend done inside ``OnlineScorer._score_rules_vectorised``
    so the gallery's component breakdown matches what production would
    produce.
    """
    return (
        RULE_WEIGHTS["threshold_breach"] * df["exp_rule_threshold_score"].astype(float)
        + RULE_WEIGHTS["sudden_jump"] * df["exp_rule_jump_score"].astype(float)
        + RULE_WEIGHTS["sustained_increase"] * df["exp_rule_sustained_score"].astype(float)
    )


def _fuse(ts: pd.Series, if_: pd.Series, rules: pd.Series) -> pd.Series:
    """Weight-renormalised ensemble fusion (matches OnlineScorer._fuse).

    Components with NaN are dropped from the denominator so the remaining
    weights still sum to 1. Used here because we feed in ``if_score = NaN``
    by design.
    """
    weights = {
        "ts": (_WEIGHT_TS, ts),
        "if": (_WEIGHT_IF, if_),
        "rules": (_WEIGHT_RULES, rules),
    }
    score = pd.Series(0.0, index=ts.index)
    denom = pd.Series(0.0, index=ts.index)
    for w, vals in weights.values():
        active = vals.notna()
        score = score.add(np.where(active, w * vals.fillna(0.0), 0.0), fill_value=0.0)
        denom = denom.add(np.where(active, w, 0.0), fill_value=0.0)
    return (score / denom.replace(0.0, np.nan)).fillna(0.0).clip(0.0, 1.0)


# ---------------------------------------------------------------------------
# End-to-end scoring pipeline used by the gallery
# ---------------------------------------------------------------------------


def _build_scored_frame(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Run the full EXP-01..03 pipeline on a labelled DataFrame.

    Returns a DataFrame with: ``ts_signal``, ``if_score``, ``rule_score``,
    ``anomaly_score``, ``is_anomaly``, ``severity``, ``exp_*``,
    ``exp_rule_*``, and ``exp_breakdown``.
    """
    # Map MLQ-01..03 column names to the EXP modules' canonical names.
    df = df.rename(columns={"cost_amount": "total_cost"})
    df["bucket"] = pd.to_datetime(df["timestamp"], utc=True)

    # Preserve the ground-truth label before the scoring pipeline overwrites
    # ``is_anomaly`` with the prediction. The picker logic uses
    # ``is_anomaly`` (prediction) for confusion-matrix semantics, but the
    # gallery rows need to display the *label* alongside the prediction.
    df["is_anomaly_label"] = df["is_anomaly"].astype("int8")

    df = _attach_forecast_layer(df)

    # EXP-02 per-rule explanation columns. ``explain_group`` re-orders the
    # frame by group; we reindex back so positional lookups remain stable.
    rule_explainer = RuleExplainer(RuleExplainerConfig())
    df = rule_explainer.explain_group(df).reindex(df.index)

    df["rule_score"] = _blend_rule_score(df)

    df["anomaly_score"] = _fuse(df["ts_signal"], df["if_score"], df["rule_score"])
    df["is_anomaly"] = (df["anomaly_score"] >= threshold).astype("int8")

    # Severity boundaries scale with the chosen threshold so that a row at
    # the threshold gets LOW, well above gets HIGH. Without this rescale
    # the SeverityConfig defaults (0.55 / 0.65 / 0.80) reject our 0.30
    # threshold via post-init validation.
    sev = SeverityMapper(SeverityConfig(
        anomaly_threshold=threshold,
        low_medium_boundary=min(0.65, threshold + (1 - threshold) * 0.4),
        medium_high_boundary=min(0.80, threshold + (1 - threshold) * 0.7),
    ))
    df = sev.transform(df)

    # EXP-01 forecast-vs-actual explanation columns.
    exp_gen = ExplanationGenerator(ExplanationConfig(
        target_col="total_cost",
        ci_levels=[95],
    ))
    df = exp_gen.explain(df)

    # EXP-03 score breakdown column. Threshold + weights match what we
    # used above so the breakdown's effective_weight numbers reproduce
    # _fuse() exactly.
    builder = ScoreBreakdownBuilder(ScoreBreakdownConfig(
        weight_ts=_WEIGHT_TS,
        weight_if=_WEIGHT_IF,
        weight_rules=_WEIGHT_RULES,
        anomaly_threshold=threshold,
        include_forecast_explanation=True,
        include_rule_explanation=True,
    ))
    df = builder.build(df)
    return df


# ---------------------------------------------------------------------------
# Case selection
# ---------------------------------------------------------------------------


def _pick_high_confidence_spike(df: pd.DataFrame) -> Optional[int]:
    mask = (df["is_anomaly"] == 1) & (df["anomaly_type"] == "spike")
    candidates = df.loc[mask].sort_values("anomaly_score", ascending=False)
    return int(candidates.index[0]) if not candidates.empty else None


def _pick_sustained_budget_breach(df: pd.DataFrame) -> Optional[int]:
    """Budget_breach row that triggered any rule (ideal multi-signal demo)."""
    mask = (df["anomaly_type"] == "budget_breach") & (
        df["exp_rule_triggered_rules"].astype(str).str.len() > 0
    )
    candidates = df.loc[mask].sort_values("anomaly_score", ascending=False)
    if not candidates.empty:
        return int(candidates.index[0])
    # Fall back to the highest-scoring breach even if no rule fired —
    # the example will demonstrate the "no rule fired but z-score is high"
    # path, which is itself a quality property to showcase.
    fallback = df.loc[df["anomaly_type"] == "budget_breach"].sort_values(
        "anomaly_score", ascending=False
    )
    return int(fallback.index[0]) if not fallback.empty else None


def _pick_borderline_normal(df: pd.DataFrame, threshold: float) -> Optional[int]:
    mask = (df["is_anomaly"] == 0) & (df["anomaly_type"] == "normal")
    candidates = df.loc[mask].sort_values("anomaly_score", ascending=False)
    return int(candidates.index[0]) if not candidates.empty else None


def _pick_calm_normal(df: pd.DataFrame) -> Optional[int]:
    mask = df["anomaly_type"] == "normal"
    candidates = df.loc[mask].sort_values("anomaly_score", ascending=True)
    return int(candidates.index[0]) if not candidates.empty else None


def _pick_missed_anomaly(df: pd.DataFrame) -> Optional[int]:
    """Lowest-score true anomaly — score recipe gap, not threshold gap."""
    mask = (df["is_anomaly"] == 0) & (df["anomaly_type"] != "normal")
    candidates = df.loc[mask].sort_values("anomaly_score", ascending=True)
    return int(candidates.index[0]) if not candidates.empty else None


# Order matters in the gallery — start with the strongest case so the
# reader gets the headline before the edge cases.
_CASE_PICKERS: List[Tuple[str, str, callable]] = [
    (
        "high_confidence_spike",
        "Strongest TP. Verifies the headline summary, component "
        "contributions, and severity all agree at the top of the score range.",
        lambda df, _t: _pick_high_confidence_spike(df),
    ),
    (
        "sustained_budget_breach",
        "Budget_breach row with at least one rule fired — exercises the "
        "multi-rule narrative path in EXP-02 and the rule-driven score "
        "contribution in EXP-03.",
        lambda df, _t: _pick_sustained_budget_breach(df),
    ),
    (
        "borderline_normal",
        "Highest-scoring true negative. Verifies the explanation does not "
        "overclaim when ``is_anomaly = 0`` but the score is non-trivial.",
        lambda df, t: _pick_borderline_normal(df, t),
    ),
    (
        "calm_normal",
        "Lowest-scoring normal. Verifies the quiet path ('forecast holds; "
        "no rules fired') still produces a coherent payload.",
        lambda df, _t: _pick_calm_normal(df),
    ),
    (
        "missed_anomaly",
        "True anomaly with the lowest score — verifies the explanation "
        "remains honest about ``is_anomaly = 0`` even when the label says "
        "the row should have been caught.",
        lambda df, _t: _pick_missed_anomaly(df),
    ),
]


def _select_cases(df: pd.DataFrame, threshold: float) -> List[CaseSelection]:
    """Run every picker; format the chosen rows through EXP-04."""
    cases: List[CaseSelection] = []
    for key, intent, picker in _CASE_PICKERS:
        idx = picker(df, threshold)
        if idx is None:
            logger.warning("MLQ-04: could not find a case for %s — skipping.", key)
            continue
        row = df.loc[idx]
        breakdown: ScoreBreakdown = row["exp_breakdown"]
        # Pydantic round-trip — this is the EXP-04 contract gate.
        response: AnomalyExplanationResponse = format_explanation(breakdown)
        cases.append(
            CaseSelection(
                key=key,
                intent=intent,
                row_index=int(idx),
                label=int(row["is_anomaly_label"]) if "is_anomaly_label" in row.index else 0,
                anomaly_type=str(row.get("anomaly_type", "normal")),
                flagged=bool(int(row["is_anomaly"])),
                payload=response.model_dump(mode="json"),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def run(cfg: GalleryConfig, write: bool = True) -> GalleryOutput:
    """Build the validation set, score it, curate cases, write artifacts."""
    threshold, source = resolve_threshold(cfg.calibration_path, cfg.threshold)
    logger.info("MLQ-04 gallery threshold: %.4f (source: %s)", threshold, source)

    df = build_validation_set(TuningConfig(n_samples=cfg.n_samples))
    logger.info(
        "MLQ-04 validation set: rows=%d, true_anomalies=%d (%.2f%%)",
        len(df),
        int(df["is_anomaly"].sum()),
        100.0 * df["is_anomaly"].mean(),
    )

    scored = _build_scored_frame(df, threshold)
    cases = _select_cases(scored, threshold)

    json_path: Optional[Path] = None
    md_path: Optional[Path] = None
    if write:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = cfg.output_dir / "explainability_examples.json"
        json_path.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                    "threshold": threshold,
                    "threshold_source": source,
                    "n_rows": int(len(scored)),
                    "cases": [
                        {
                            "key": c.key,
                            "intent": c.intent,
                            "row_index": c.row_index,
                            "label": c.label,
                            "anomaly_type": c.anomaly_type,
                            "flagged": c.flagged,
                            "payload": c.payload,
                        }
                        for c in cases
                    ],
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        md_path = _write_markdown(cfg.output_dir, scored, cases, threshold, source)

    return GalleryOutput(
        threshold=threshold,
        threshold_source=source,
        n_samples=int(len(scored)),
        n_cases=len(cases),
        cases=cases,
        json_path=json_path,
        md_path=md_path,
    )


# ---------------------------------------------------------------------------
# Markdown writer — sprint-review packet
# ---------------------------------------------------------------------------


def _write_markdown(
    output_dir: Path,
    scored: pd.DataFrame,
    cases: List[CaseSelection],
    threshold: float,
    threshold_source: str,
) -> Path:
    body = [
        "# MLQ-04 — Explainability Quality Examples",
        "",
        f"> Generated {datetime.now(tz=timezone.utc).isoformat()}.",
        "> Run via `python -m ml.src.evaluation.explainability_examples`.",
        "> Machine-readable: [`explainability_examples.json`](explainability_examples.json).",
        f"> Threshold {threshold:.4f} (source: {threshold_source}). Validation set "
        "matches MLQ-01 / MLQ-02 / MLQ-03 (seed = 42).",
        "",
        "## What this gallery proves",
        "",
        "Each case below is a real row from the validation set, scored",
        "through the EXP-01..03 pipeline and round-tripped through the",
        "EXP-04 Pydantic schema. A run is only published when *every*",
        "payload validates — that round-trip is the contract gate.",
        "",
        "Quality axes the gallery exercises:",
        "",
        "1. **Numeric / narrative agreement** — the one-line summary must",
        "   match the signed residual, z-score, and CI-breach flags.",
        "2. **Multi-rule narrative** — when ≥ 2 rules fire, the rule",
        "   explanation must enumerate them coherently.",
        "3. **Graceful degradation** — `if_score` is intentionally NaN",
        "   here; the component breakdown must surface that as `active=false`",
        "   without polluting the final score.",
        "4. **Honest non-detection** — when `is_anomaly = 0`, the summary",
        "   must NOT claim an anomaly even if the score is non-trivial.",
        "",
        "## Cases",
        "",
    ]

    for case in cases:
        row = scored.loc[case.row_index]
        body.append(_render_case(case, row))
        body.append("")

    body.append("## Caveats")
    body.append("")
    body.append(
        "- TS-01 / ML-01 trained models are not yet in the registry. The"
        " forecast layer here is the same per-account μ/σ recipe MLQ-01"
        " used; replace with a real `TimeSeriesBaselineModel` once one is"
        " trained, and re-run."
    )
    body.append(
        "- `if_score` is intentionally NaN to demonstrate the"
        " graceful-degradation path. Once ML-01 is loaded, the breakdown"
        " for the same rows will gain an active IF component."
    )
    body.append(
        "- Re-run after every EXP-01..04 change so this gallery and the"
        " API contract stay in sync — the Pydantic round-trip is the gate."
    )

    text = "\n".join(body) + "\n"
    path = output_dir / "EXPLAINABILITY_EXAMPLES.md"
    path.write_text(text, encoding="utf-8")
    logger.info("MLQ-04 markdown gallery saved to %s", path)
    return path


def _render_case(case: CaseSelection, row: pd.Series) -> str:
    p = case.payload
    lines: List[str] = []
    lines.append(f"### `{case.key}`")
    lines.append("")
    lines.append(f"_{case.intent}_")
    lines.append("")

    # Row context
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Row index | `{case.row_index}` |")
    lines.append(f"| Label | `{'anomaly' if case.label else 'normal'}` |")
    lines.append(f"| Anomaly type | `{case.anomaly_type}` |")
    lines.append(f"| Account / Service / Region | "
                 f"`{row.get('account_id', '')}` / `{row.get('service', '')}` / "
                 f"`{row.get('region', '')}` |")
    lines.append(f"| Timestamp | `{row.get('timestamp', '')}` |")
    lines.append(f"| Cost (actual) | `{float(row['total_cost']):,.2f}` |")
    lines.append(f"| Forecast mean ± std | "
                 f"`{float(row['forecast_mean']):,.2f}` ± `{float(row['forecast_std']):,.2f}` |")
    lines.append(f"| Anomaly score | **`{p['anomaly_score']:.4f}`** "
                 f"(threshold `{p['anomaly_threshold']:.4f}`) |")
    lines.append(f"| Verdict | `{'FLAGGED' if p['is_anomaly'] else 'NOT flagged'}` "
                 f"(severity `{p.get('severity') or 'none'}`) |")
    lines.append("")

    # EXP-01 forecast summary
    fe = p.get("forecast_explanation")
    lines.append("**Forecast vs actual (EXP-01)**")
    lines.append("")
    if fe:
        lines.append(f"> {fe['summary']}")
    else:
        lines.append("> _(no forecast explanation produced)_")
    lines.append("")

    # EXP-02 rule summary
    re = p.get("rule_explanation")
    lines.append("**Triggered rules (EXP-02)**")
    lines.append("")
    if re:
        lines.append(f"> {re['summary']}")
        if re["triggered_rules"]:
            lines.append("")
            lines.append("| Rule | Fired | Score | Reason |")
            lines.append("| --- | --- | --- | --- |")
            for rule_key in ("threshold_breach", "sudden_jump", "sustained_increase"):
                rr = re[rule_key]
                lines.append(
                    f"| `{rr['rule']}` | "
                    f"{'✓' if rr['fired'] else '·'} | "
                    f"`{rr['score']:.4f}` | {rr['reason'] or '—'} |"
                )
    else:
        lines.append("> _(no rule explanation produced)_")
    lines.append("")

    # EXP-03 component breakdown
    lines.append("**Component breakdown (EXP-03)**")
    lines.append("")
    lines.append("| Component | Active | Raw score | Configured weight | Effective weight | Contribution |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for comp in p["components"]:
        raw = "—" if comp["raw_score"] is None else f"`{comp['raw_score']:.4f}`"
        lines.append(
            f"| `{comp['name']}` ({comp['label']}) | "
            f"{'✓' if comp['active'] else '·'} | "
            f"{raw} | `{comp['configured_weight']:.4f}` | "
            f"`{comp['effective_weight']:.4f}` | "
            f"`{comp['weighted_contribution']:.4f}` |"
        )
    lines.append("")

    # EXP-04 raw payload — useful for API doc readers
    lines.append("**EXP-04 payload (validated)**")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(p, indent=2, default=str))
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m ml.src.evaluation.explainability_examples",
        description="MLQ-04: Frozen explainability quality examples.",
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
        help="Override validation set size (0 = canonical config).",
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
        help="Print the gallery summary; do not write files.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    cfg = GalleryConfig(
        threshold=args.threshold,
        n_samples=None if args.n == 0 else args.n,
        output_dir=args.output,
        calibration_path=args.calibration,
    )

    out = run(cfg, write=not args.no_write)
    print(json.dumps({
        "threshold": out.threshold,
        "threshold_source": out.threshold_source,
        "n_samples": out.n_samples,
        "n_cases": out.n_cases,
        "case_keys": [c.key for c in out.cases],
        "json_path": str(out.json_path) if out.json_path else None,
        "md_path": str(out.md_path) if out.md_path else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
