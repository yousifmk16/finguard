"""
EXP-03: Score breakdown payload.

Aggregates every signal produced by the detection pipeline into a single
structured payload per row.  This is the canonical "why was this flagged?"
object consumed by EXP-04 (API formatting) and any downstream alerting or
audit service.

Relationship to the EXP-* stack
--------------------------------
    EXP-01  explain.py            – forecast vs actual gap (ForecastExplanation)
    EXP-02  rule_explain.py       – per-rule fired/score/reason (RuleExplanation)
    EXP-03  score_breakdown.py    – full score breakdown payload  (this file)
    EXP-04                        – API-facing formatting

What this module adds
---------------------
For each scored row the ``ScoreBreakdownBuilder`` produces a
``ScoreBreakdown`` that contains:

  components         List[ComponentBreakdown]
      One entry per ensemble component (ts_signal, if_score, rule_score).
      Each entry carries:
          name                    "ts_signal" | "if_score" | "rule_score"
          label                   Human-readable label
          raw_score               The component value as stored on the row
          configured_weight       Weight from ScoringConfig
          effective_weight        Weight after NaN-renormalisation (matches
                                  the weight actually used by _fuse())
          weighted_contribution   effective_weight × raw_score (or 0 if NaN)
          active                  False when raw_score is NaN (model absent)

  anomaly_score      float        Final weighted ensemble score [0, 1]
  anomaly_threshold  float        Threshold used to set is_anomaly
  is_anomaly         bool         True when anomaly_score ≥ threshold
  severity           str | None   "none" | "low" | "medium" | "high" | None

  forecast_explanation   ForecastExplanation | None   (from EXP-01 columns)
  rule_explanation       RuleExplanation | None        (from EXP-02 columns)

The ``to_dict()`` method returns a plain nested dict safe for JSON
serialisation, ready for EXP-04.

DataFrame transform
-------------------
``ScoreBreakdownBuilder.build(df)`` adds a single column
``exp_breakdown`` (configurable via ``output_col``) whose values are
``ScoreBreakdown`` instances.  Call ``row.to_dict()`` to get the
JSON-ready payload.

Usage
-----
# Minimal — just the scorer output
builder = ScoreBreakdownBuilder(
    ScoreBreakdownConfig(
        weight_ts=0.35,
        weight_if=0.40,
        weight_rules=0.25,
        anomaly_threshold=0.55,
    )
)
breakdown: ScoreBreakdown = builder.build_row(scored_df.iloc[0])
payload: dict = breakdown.to_dict()

# Including EXP-01/02 sub-explanations
explained_df = ExplanationGenerator().explain(scored_df)
explained_df = RuleExplainer().explain_series(explained_df)
breakdown_df = builder.build(explained_df)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ml.src.inference.explain import ForecastExplanation, ExplanationGenerator
from ml.src.inference.rule_explain import RuleExplanation, RuleExplainer

# ---------------------------------------------------------------------------
# Component labels
# ---------------------------------------------------------------------------

_COMPONENT_LABELS: Dict[str, str] = {
    "ts_signal": "Time-Series Signal",
    "if_score": "Isolation Forest",
    "rule_score": "Rule Engine",
}


# ---------------------------------------------------------------------------
# ComponentBreakdown
# ---------------------------------------------------------------------------


@dataclass
class ComponentBreakdown:
    """
    Score contribution of a single ensemble component.

    Attributes
    ----------
    name : str
        Column name as it appears on the scored DataFrame.
        One of: ``"ts_signal"``, ``"if_score"``, ``"rule_score"``.
    label : str
        Human-readable label (e.g. "Time-Series Signal").
    raw_score : float
        The value of the component column.  NaN when the component was
        unavailable (model not loaded, component disabled).
    configured_weight : float
        The nominal weight from ``ScoringConfig`` (or 0 when disabled).
    effective_weight : float
        The weight actually used after renormalising for any NaN components.
        Matches the denominator logic in ``OnlineScorer._fuse()``.
    weighted_contribution : float
        ``effective_weight × raw_score``; 0.0 when ``raw_score`` is NaN.
    active : bool
        ``True`` when ``raw_score`` is a finite number (component contributed
        to the final score).
    """

    name: str
    label: str
    raw_score: float
    configured_weight: float
    effective_weight: float
    weighted_contribution: float
    active: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "raw_score": None if math.isnan(self.raw_score) else round(self.raw_score, 6),
            "configured_weight": round(self.configured_weight, 6),
            "effective_weight": round(self.effective_weight, 6),
            "weighted_contribution": round(self.weighted_contribution, 6),
            "active": self.active,
        }


# ---------------------------------------------------------------------------
# ScoreBreakdown
# ---------------------------------------------------------------------------


@dataclass
class ScoreBreakdown:
    """
    Full score breakdown payload for a single scored row.

    Attributes
    ----------
    components : list[ComponentBreakdown]
        One entry per ensemble component, ordered ts_signal → if_score →
        rule_score.
    anomaly_score : float
        Final weighted ensemble score in [0, 1].
    anomaly_threshold : float
        Threshold at which ``is_anomaly`` flips to ``True``.
    is_anomaly : bool
        ``True`` when ``anomaly_score ≥ anomaly_threshold``.
    severity : str | None
        Severity label from ENS-02, or ``None`` if not available.
    forecast_explanation : ForecastExplanation | None
        EXP-01 forecast-vs-actual explanation, or ``None`` when not computed.
    rule_explanation : RuleExplanation | None
        EXP-02 per-rule detail, or ``None`` when not computed.
    """

    components: List[ComponentBreakdown]
    anomaly_score: float
    anomaly_threshold: float
    is_anomaly: bool
    severity: Optional[str]
    forecast_explanation: Optional[ForecastExplanation] = None
    rule_explanation: Optional[RuleExplanation] = None

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def component(self, name: str) -> Optional[ComponentBreakdown]:
        """Return the ComponentBreakdown for ``name``, or None if absent."""
        for c in self.components:
            if c.name == name:
                return c
        return None

    @property
    def active_components(self) -> List[ComponentBreakdown]:
        """Components that contributed a finite score."""
        return [c for c in self.components if c.active]

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Return a plain nested dict suitable for JSON serialisation.

        ``ForecastExplanation`` and ``RuleExplanation`` fields are rendered
        as dicts; NaN floats are mapped to ``None`` for JSON compatibility.
        """
        payload: Dict[str, Any] = {
            "anomaly_score": round(self.anomaly_score, 6),
            "anomaly_threshold": round(self.anomaly_threshold, 6),
            "is_anomaly": self.is_anomaly,
            "severity": self.severity,
            "components": [c.to_dict() for c in self.components],
        }

        if self.forecast_explanation is not None:
            fe = self.forecast_explanation
            payload["forecast_explanation"] = {
                "actual": round(fe.actual, 6),
                "forecast_mean": (
                    None if math.isnan(fe.forecast_mean)
                    else round(fe.forecast_mean, 6)
                ),
                "forecast_std": (
                    None if math.isnan(fe.forecast_std)
                    else round(fe.forecast_std, 6)
                ),
                "residual": (
                    None if math.isnan(fe.residual) else round(fe.residual, 6)
                ),
                "pct_deviation": (
                    None if math.isnan(fe.pct_deviation)
                    else round(fe.pct_deviation, 4)
                ),
                "z_score": (
                    None if math.isnan(fe.z_score) else round(fe.z_score, 4)
                ),
                "direction": fe.direction,
                "ci_breaches": {str(k): v for k, v in fe.ci_breaches.items()},
                "summary": fe.summary,
            }

        if self.rule_explanation is not None:
            re = self.rule_explanation

            def _result_dict(r) -> Dict[str, Any]:
                return {
                    "rule": r.rule,
                    "fired": r.fired,
                    "score": round(r.score, 6),
                    "reason": r.reason,
                }

            payload["rule_explanation"] = {
                "threshold_breach": _result_dict(re.threshold_result),
                "sudden_jump": _result_dict(re.jump_result),
                "sustained_increase": _result_dict(re.sustained_result),
                "triggered_rules": re.triggered_rules,
                "summary": re.summary,
            }

        return payload


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ScoreBreakdownConfig:
    """
    Parameters required to reconstruct the ensemble weight logic from the
    scored DataFrame.

    These must match the ``ScoringConfig`` values used by ``OnlineScorer``
    when the DataFrame was scored.

    Attributes
    ----------
    weight_ts : float
        Configured weight for the time-series signal.
    weight_if : float
        Configured weight for the Isolation Forest signal.
    weight_rules : float
        Configured weight for the rule-engine signal.
    anomaly_threshold : float
        Score threshold used by ``OnlineScorer._fuse()``.
    enable_ts : bool
        Whether TS was enabled when scoring; False → configured_weight = 0.
    enable_if : bool
        Whether IF was enabled; False → configured_weight = 0.
    enable_rules : bool
        Whether rules were enabled; False → configured_weight = 0.
    ts_col : str
        Column name for the time-series signal.
    if_col : str
        Column name for the Isolation Forest score.
    rule_col : str
        Column name for the blended rule score.
    anomaly_score_col : str
        Column name for the final ensemble score.
    is_anomaly_col : str
        Column name for the binary anomaly flag.
    severity_col : str
        Column name for the severity label.  Missing → None in payload.
    include_forecast_explanation : bool
        When True, attempt to read EXP-01 columns and embed a
        ``ForecastExplanation`` in the payload.
    include_rule_explanation : bool
        When True, attempt to read EXP-02 columns and embed a
        ``RuleExplanation`` in the payload.
    output_col : str
        Name of the column written by ``build()``.
    """

    weight_ts: float = 0.35
    weight_if: float = 0.40
    weight_rules: float = 0.25
    anomaly_threshold: float = 0.55

    enable_ts: bool = True
    enable_if: bool = True
    enable_rules: bool = True

    ts_col: str = "ts_signal"
    if_col: str = "if_score"
    rule_col: str = "rule_score"
    anomaly_score_col: str = "anomaly_score"
    is_anomaly_col: str = "is_anomaly"
    severity_col: str = "severity"

    include_forecast_explanation: bool = True
    include_rule_explanation: bool = True

    output_col: str = "exp_breakdown"

    @classmethod
    def from_scoring_config(cls, scoring_config: object) -> "ScoreBreakdownConfig":
        """
        Build a ScoreBreakdownConfig from an existing ``ScoringConfig``.

        Parameters
        ----------
        scoring_config :
            A ``ScoringConfig`` instance (from ``ml.src.inference.scorer``).

        Returns
        -------
        ScoreBreakdownConfig with matching weights, threshold, and toggles.
        """
        sc = scoring_config
        return cls(
            weight_ts=sc.weight_ts,          # type: ignore[attr-defined]
            weight_if=sc.weight_if,          # type: ignore[attr-defined]
            weight_rules=sc.weight_rules,    # type: ignore[attr-defined]
            anomaly_threshold=sc.anomaly_threshold,  # type: ignore[attr-defined]
            enable_ts=sc.enable_ts,          # type: ignore[attr-defined]
            enable_if=sc.enable_if,          # type: ignore[attr-defined]
            enable_rules=sc.enable_rules,    # type: ignore[attr-defined]
        )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ScoreBreakdownBuilder:
    """
    EXP-03: Assemble a ScoreBreakdown payload for each scored row.

    Calling styles
    --------------
    # Single-row payload
    builder = ScoreBreakdownBuilder(config)
    breakdown = builder.build_row(scored_df.iloc[0])

    # Whole-DataFrame transform (adds ``exp_breakdown`` column)
    df_with_breakdown = builder.build(scored_df)

    # Including EXP-01 / EXP-02 sub-explanations (must be pre-computed)
    df = ExplanationGenerator().explain(scored_df)
    df = RuleExplainer().explain_series(df)
    df_with_breakdown = builder.build(df)
    """

    def __init__(self, config: Optional[ScoreBreakdownConfig] = None) -> None:
        self.config = config or ScoreBreakdownConfig()

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_scorer(cls, scorer: object) -> "ScoreBreakdownBuilder":
        """
        Create a builder whose weights and threshold match an ``OnlineScorer``.

        Parameters
        ----------
        scorer :
            A configured ``OnlineScorer`` instance.

        Returns
        -------
        ScoreBreakdownBuilder with matching ScoreBreakdownConfig.
        """
        cfg = ScoreBreakdownConfig.from_scoring_config(scorer.config)  # type: ignore[attr-defined]
        return cls(cfg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_row(self, row: pd.Series) -> ScoreBreakdown:
        """
        Build a ScoreBreakdown for a single scored row.

        Parameters
        ----------
        row :
            A row from the output of ``OnlineScorer.score()`` /
            ``score_group()``.  May optionally contain EXP-01 and EXP-02
            explanation columns.

        Returns
        -------
        ScoreBreakdown
        """
        cfg = self.config

        # ---- component raw scores ----------------------------------------
        ts_raw = _read_float(row, cfg.ts_col)
        if_raw = _read_float(row, cfg.if_col)
        rule_raw = _read_float(row, cfg.rule_col, default=0.0)

        # ---- configured weights (0 when disabled) ------------------------
        w_ts = cfg.weight_ts if cfg.enable_ts else 0.0
        w_if = cfg.weight_if if cfg.enable_if else 0.0
        w_rules = cfg.weight_rules if cfg.enable_rules else 0.0

        # ---- effective weights (mirror _fuse NaN-renormalisation) --------
        raw_scores = [ts_raw, if_raw, rule_raw]
        conf_weights = [w_ts, w_if, w_rules]
        eff_weights = _effective_weights(raw_scores, conf_weights)

        # ---- component breakdown objects ---------------------------------
        names = [cfg.ts_col, cfg.if_col, cfg.rule_col]
        components: List[ComponentBreakdown] = []
        for name, raw, cw, ew in zip(names, raw_scores, conf_weights, eff_weights):
            active = not math.isnan(raw) and cw > 0.0
            contribution = ew * raw if active else 0.0
            components.append(
                ComponentBreakdown(
                    name=name,
                    label=_COMPONENT_LABELS.get(name, name),
                    raw_score=raw,
                    configured_weight=cw,
                    effective_weight=ew,
                    weighted_contribution=contribution,
                    active=active,
                )
            )

        # ---- final decision fields ----------------------------------------
        anomaly_score = _read_float(row, cfg.anomaly_score_col, default=0.0)
        is_anomaly = bool(int(row[cfg.is_anomaly_col])) if cfg.is_anomaly_col in row.index else (
            anomaly_score >= cfg.anomaly_threshold
        )
        severity = str(row[cfg.severity_col]) if cfg.severity_col in row.index else None

        # ---- optional sub-explanations -----------------------------------
        forecast_exp: Optional[ForecastExplanation] = None
        if cfg.include_forecast_explanation:
            forecast_exp = _read_forecast_explanation(row)

        rule_exp: Optional[RuleExplanation] = None
        if cfg.include_rule_explanation:
            rule_exp = _read_rule_explanation(row)

        return ScoreBreakdown(
            components=components,
            anomaly_score=anomaly_score,
            anomaly_threshold=cfg.anomaly_threshold,
            is_anomaly=is_anomaly,
            severity=severity,
            forecast_explanation=forecast_exp,
            rule_explanation=rule_exp,
        )

    def build(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add a ``ScoreBreakdown`` column to a scored (and optionally explained)
        DataFrame.

        Parameters
        ----------
        df :
            Output of ``OnlineScorer.score()`` or ``score_group()``, optionally
            extended by EXP-01 (``ExplanationGenerator.explain()``) and/or
            EXP-02 (``RuleExplainer.explain_series()``).

        Returns
        -------
        Copy of ``df`` with one additional column:

            ``exp_breakdown``   object   ScoreBreakdown instance per row.
                                         Call ``.to_dict()`` for JSON payload.
        """
        result = df.copy()
        result[self.config.output_col] = [
            self.build_row(row) for _, row in df.iterrows()
        ]
        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _read_float(row: pd.Series, col: str, default: float = math.nan) -> float:
    """Return the float value of ``col`` in ``row``, or ``default`` if absent."""
    if col not in row.index:
        return default
    val = row[col]
    try:
        f = float(val)
        return default if math.isnan(f) and not math.isnan(default) else f
    except (TypeError, ValueError):
        return default


def _effective_weights(
    raw_scores: List[float],
    conf_weights: List[float],
) -> List[float]:
    """
    Reproduce the per-component effective weight after NaN-renormalisation,
    matching ``OnlineScorer._fuse()`` exactly.

    A component is excluded from the denominator when its raw_score is NaN
    OR its configured_weight is 0.  The remaining weights are scaled so they
    sum to 1.0.

    Returns a list of effective weights in the same order as the inputs.
    """
    active_weight_sum = sum(
        w for s, w in zip(raw_scores, conf_weights)
        if not math.isnan(s) and w > 0.0
    )

    if active_weight_sum == 0.0:
        return [0.0] * len(conf_weights)

    eff: List[float] = []
    for s, w in zip(raw_scores, conf_weights):
        if not math.isnan(s) and w > 0.0:
            eff.append(w / active_weight_sum)
        else:
            eff.append(0.0)
    return eff


def _read_forecast_explanation(row: pd.Series) -> Optional[ForecastExplanation]:
    """
    Reconstruct a ForecastExplanation from EXP-01 columns already present on
    ``row``.  Returns None when the required columns are absent.

    Requires (from ExplanationGenerator.explain() output):
        exp_direction, exp_pct_deviation, exp_z_score, exp_summary
    and the raw columns written by the scorer / ResidualScorer:
        total_cost, forecast_mean, forecast_std, residual
    """
    required = {"exp_direction", "exp_summary"}
    if not required.issubset(row.index):
        return None

    # Re-read raw values (already on the row from the scorer pipeline)
    actual = _read_float(row, "total_cost")
    forecast_mean = _read_float(row, "forecast_mean")
    forecast_std = _read_float(row, "forecast_std")
    residual = _read_float(row, "residual")

    pct_deviation = _read_float(row, "exp_pct_deviation")
    z_score = _read_float(row, "exp_z_score")
    direction = str(row["exp_direction"])
    summary = str(row["exp_summary"])

    # Reconstruct ci_breaches from the exp_ci_breach boolean and the
    # is_outside_ci_* flags if available.
    ci_breaches: Dict[str, bool] = {}
    for col in row.index:
        if col.startswith("is_outside_ci_"):
            pct = col[len("is_outside_ci_"):]
            ci_breaches[pct] = bool(int(row[col]))

    return ForecastExplanation(
        actual=actual,
        forecast_mean=forecast_mean,
        forecast_std=forecast_std,
        residual=residual,
        pct_deviation=pct_deviation,
        z_score=z_score,
        direction=direction,
        ci_breaches={int(k): v for k, v in ci_breaches.items()},
        summary=summary,
    )


def _read_rule_explanation(row: pd.Series) -> Optional[RuleExplanation]:
    """
    Reconstruct a RuleExplanation from EXP-02 columns already present on
    ``row``.  Returns None when the required columns are absent.

    Requires (from RuleExplainer.explain_series() output):
        exp_rule_threshold_fired/score/reason
        exp_rule_jump_fired/score/reason
        exp_rule_sustained_fired/score/reason
        exp_rule_triggered_rules, exp_rule_summary
    """
    from services.rules.engine import RuleResult

    required = {
        "exp_rule_threshold_fired",
        "exp_rule_jump_fired",
        "exp_rule_sustained_fired",
    }
    if not required.issubset(row.index):
        return None

    def _result(prefix: str, rule_name: str) -> "RuleResult":
        fired = bool(row[f"{prefix}_fired"])
        score = float(row[f"{prefix}_score"]) if f"{prefix}_score" in row.index else 0.0
        reason = str(row[f"{prefix}_reason"]) if f"{prefix}_reason" in row.index else ""
        return RuleResult(rule=rule_name, fired=fired, score=score, reason=reason)

    threshold_result = _result("exp_rule_threshold", "threshold_breach")
    jump_result = _result("exp_rule_jump", "sudden_jump")
    sustained_result = _result("exp_rule_sustained", "sustained_increase")

    triggered_raw = row.get("exp_rule_triggered_rules", "")
    triggered = [t.strip() for t in str(triggered_raw).split(",") if t.strip()] if triggered_raw else []
    summary = str(row.get("exp_rule_summary", ""))

    return RuleExplanation(
        threshold_result=threshold_result,
        jump_result=jump_result,
        sustained_result=sustained_result,
        triggered_rules=triggered,
        summary=summary,
    )
