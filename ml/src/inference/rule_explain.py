"""
EXP-02: Triggered-rule explanation details.

For each scored row this module re-evaluates the three deterministic rules
(RUL-01/02/03) and surfaces which rules fired, their individual confidence
scores, and the human-readable reason strings already produced by each rule.

Relationship to the EXP-* stack
--------------------------------
    EXP-01  explain.py       – forecast vs actual gap
    EXP-02  rule_explain.py  – triggered-rule details  (this file)
    EXP-03                   – full score breakdown payload

Why re-evaluate instead of reading from the scored DataFrame?
--------------------------------------------------------------
``OnlineScorer._score_rules_vectorised()`` blends the three rule scores into
a single ``rule_score`` column but discards the individual ``RuleResult``
objects.  EXP-02 needs fired/score/reason per rule, so it mirrors the same
loop — using the same rule instances and window constants — to recover those
details from the cost series.

Input
-----
A time-ordered DataFrame for a **single** (account_id, service, region) group.
For multi-series DataFrames call ``explain_group(df)`` which splits by group
and reassembles.

Required column: ``target_col`` (default ``total_cost``).
Optional columns consumed by EXP-01: ``forecast_mean``, ``rule_score``, etc.

Output columns (prefix controlled by ``RuleExplainerConfig.output_prefix``)
---------------------------------------------------------------------------
    <prefix>threshold_fired    bool    True when RUL-01 fired
    <prefix>threshold_score    float   RUL-01 confidence [0, 1]
    <prefix>threshold_reason   str     RUL-01 human-readable reason

    <prefix>jump_fired         bool    True when RUL-02 fired
    <prefix>jump_score         float   RUL-02 confidence [0, 1]
    <prefix>jump_reason        str     RUL-02 human-readable reason

    <prefix>sustained_fired    bool    True when RUL-03 fired
    <prefix>sustained_score    float   RUL-03 confidence [0, 1]
    <prefix>sustained_reason   str     RUL-03 human-readable reason

    <prefix>triggered_rules    str     Comma-separated names of fired rules
                                       (empty string when none fired)
    <prefix>summary            str     Human-readable sentence

Usage
-----
# Single-series DataFrame
explainer = RuleExplainer()
explained_df = explainer.explain_series(scored_df)

# Multi-series DataFrame (splits by group_cols, reassembles)
explained_df = explainer.explain_group(scored_df)

# Build from an existing OnlineScorer so configs are in sync
explainer = RuleExplainer.from_scorer(scorer)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from services.rules.engine import (
    RuleResult,
    ThresholdBreachRule,
    SuddenJumpRule,
    SustainedIncreaseRule,
)
from services.rules.config import RULE_THRESHOLDS

# Must match _JUMP_LOOKBACK in scorer.py — the window of preceding rows used
# by SuddenJumpRule when no pre-computed rolling feature is available.
_JUMP_LOOKBACK = 15


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RuleExplanation:
    """
    Per-row explanation of the three deterministic rules.

    Attributes
    ----------
    threshold_result : RuleResult
        Output of RUL-01 (ThresholdBreachRule) for this row.
    jump_result : RuleResult
        Output of RUL-02 (SuddenJumpRule) for this row.
    sustained_result : RuleResult
        Output of RUL-03 (SustainedIncreaseRule) for this row.
    triggered_rules : list[str]
        Names of rules that fired (``fired == True``).  Empty when no rule
        triggered.
    summary : str
        Human-readable one-sentence description of which rules triggered.
    """

    threshold_result: RuleResult
    jump_result: RuleResult
    sustained_result: RuleResult
    triggered_rules: List[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RuleExplainerConfig:
    """
    Parameters for the rule explanation layer.

    Mirrors the rule-related fields of ``ScoringConfig`` so that an explainer
    can be created independently of the scorer or kept in sync via
    ``RuleExplainer.from_scorer()``.

    Attributes
    ----------
    target_col : str
        Cost column to evaluate rules against.
    group_cols : list[str]
        Columns that identify independent billing series (used by
        ``explain_group``).
    jump_lookback : int
        Number of preceding rows used as the window for SuddenJumpRule.
        Must match ``_JUMP_LOOKBACK`` in ``scorer.py``.
    budget_limit : float | None
        Override for RUL-01 budget ceiling.  ``None`` → use config default.
    jump_pct : float | None
        Override for RUL-02 percentage threshold.  ``None`` → default.
    sustained_window : int | None
        Override for RUL-03 consecutive-period count.  ``None`` → default.
    sustained_min_growth : float | None
        Override for RUL-03 minimum per-period growth fraction.  ``None`` →
        default.
    output_prefix : str
        Column name prefix written by ``explain_series()`` /
        ``explain_group()``.
    """

    target_col: str = "total_cost"
    group_cols: List[str] = field(
        default_factory=lambda: ["account_id", "service", "region"]
    )
    jump_lookback: int = _JUMP_LOOKBACK

    # Rule overrides — None means "use services/rules/config.py defaults"
    budget_limit: Optional[float] = None
    jump_pct: Optional[float] = None
    sustained_window: Optional[int] = None
    sustained_min_growth: Optional[float] = None

    output_prefix: str = "exp_rule_"


# ---------------------------------------------------------------------------
# Explainer
# ---------------------------------------------------------------------------


class RuleExplainer:
    """
    EXP-02: Re-evaluate RUL-01/02/03 and surface per-rule fired/score/reason.

    Mirrors the evaluation loop inside ``OnlineScorer._score_rules_vectorised``
    but stores every ``RuleResult`` rather than blending them into a single
    ``rule_score``.

    Lifecycle
    ---------
    1. Instantiate (optionally pass a ``RuleExplainerConfig``).
    2. Call ``explain_series(df)`` for a single time-series group.
    3. Or call ``explain_group(df)`` for a multi-series DataFrame.

    Factory helpers
    ---------------
    ``RuleExplainer.from_scorer(scorer)`` creates an explainer whose rule
    thresholds exactly match those already loaded into an ``OnlineScorer``
    instance.
    """

    def __init__(self, config: Optional[RuleExplainerConfig] = None) -> None:
        self.config = config or RuleExplainerConfig()
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
    def from_scorer(cls, scorer: object) -> "RuleExplainer":
        """
        Build a RuleExplainer whose thresholds match an existing OnlineScorer.

        Parameters
        ----------
        scorer :
            A configured ``OnlineScorer`` instance.  Its ``config`` attribute
            (``ScoringConfig``) supplies budget_limit, jump_pct,
            sustained_window, and sustained_min_growth.

        Returns
        -------
        RuleExplainer with matching rule configuration.
        """
        sc = scorer.config  # type: ignore[attr-defined]
        cfg = RuleExplainerConfig(
            target_col=sc.target_col,
            group_cols=list(sc.group_cols),
            budget_limit=sc.budget_limit,
            jump_pct=sc.jump_pct,
            sustained_window=sc.sustained_window,
            sustained_min_growth=sc.sustained_min_growth,
        )
        return cls(cfg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add rule explanation columns to a **single-series** DataFrame.

        Parameters
        ----------
        df :
            Time-ordered rows for one (account_id, service, region) group.
            Must contain ``config.target_col``.

        Returns
        -------
        Copy of ``df`` with the ``exp_rule_*`` columns appended.
        """
        explanations = self._evaluate_series(df)
        return self._attach_columns(df, explanations)

    def explain_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add rule explanation columns to a **multi-series** DataFrame.

        Each (account_id, service, region) group is explained independently
        so that rule windows don't bleed across series.

        Parameters
        ----------
        df :
            Multi-series DataFrame (output of ``OnlineScorer.score_group()``
            or a raw feature DataFrame).

        Returns
        -------
        Copy of ``df`` with ``exp_rule_*`` columns, preserving the original
        index order.
        """
        group_keys = [k for k in self.config.group_cols if k in df.columns]

        if not group_keys:
            return self.explain_series(df.sort_values(self.config.target_col))

        parts: list[pd.DataFrame] = []
        for _, group in df.groupby(group_keys, sort=False):
            group_sorted = group.sort_values(
                group.columns[0] if "bucket" not in group.columns else "bucket"
            )
            parts.append(self.explain_series(group_sorted))

        return pd.concat(parts).reindex(df.index)

    def explain_row(self, idx: int, df: pd.DataFrame) -> RuleExplanation:
        """
        Return a ``RuleExplanation`` for a single row by position.

        Parameters
        ----------
        idx :
            Zero-based integer position of the row within ``df`` (after any
            required time-ordering).
        df :
            The full time-ordered single-series DataFrame.  Window context
            for RUL-02/03 is drawn from rows preceding ``idx``.

        Returns
        -------
        RuleExplanation
        """
        explanations = self._evaluate_series(df)
        return explanations[idx]

    # ------------------------------------------------------------------
    # Internal evaluation loop
    # ------------------------------------------------------------------

    def _evaluate_series(self, df: pd.DataFrame) -> list[RuleExplanation]:
        """
        Re-run RUL-01/02/03 for every row and return a list of
        ``RuleExplanation`` objects aligned to ``df``'s row order.
        """
        col = self.config.target_col
        costs = df[col].astype(float).to_list()
        n = len(costs)
        sustained_lookback = self._sustained_rule.window
        results: list[RuleExplanation] = []

        for i in range(n):
            val = costs[i]

            # RUL-01 — absolute threshold
            r1 = self._threshold_rule.evaluate(val)

            # RUL-02 — sudden jump vs rolling window mean
            jump_window = costs[max(0, i - self.config.jump_lookback):i]
            r2 = self._jump_rule.evaluate(val, jump_window)

            # RUL-03 — sustained upward trend
            sustained_series = costs[max(0, i - sustained_lookback):i + 1]
            r3 = self._sustained_rule.evaluate(sustained_series)

            triggered = [
                r.rule for r in (r1, r2, r3) if r.fired
            ]
            summary = _build_rule_summary(r1, r2, r3, triggered)

            results.append(
                RuleExplanation(
                    threshold_result=r1,
                    jump_result=r2,
                    sustained_result=r3,
                    triggered_rules=triggered,
                    summary=summary,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Column attachment
    # ------------------------------------------------------------------

    def _attach_columns(
        self,
        df: pd.DataFrame,
        explanations: list[RuleExplanation],
    ) -> pd.DataFrame:
        """Write per-rule fields into a copy of ``df``."""
        p = self.config.output_prefix
        result = df.copy()

        result[f"{p}threshold_fired"] = [e.threshold_result.fired for e in explanations]
        result[f"{p}threshold_score"] = [e.threshold_result.score for e in explanations]
        result[f"{p}threshold_reason"] = [e.threshold_result.reason for e in explanations]

        result[f"{p}jump_fired"] = [e.jump_result.fired for e in explanations]
        result[f"{p}jump_score"] = [e.jump_result.score for e in explanations]
        result[f"{p}jump_reason"] = [e.jump_result.reason for e in explanations]

        result[f"{p}sustained_fired"] = [e.sustained_result.fired for e in explanations]
        result[f"{p}sustained_score"] = [e.sustained_result.score for e in explanations]
        result[f"{p}sustained_reason"] = [e.sustained_result.reason for e in explanations]

        result[f"{p}triggered_rules"] = [
            ", ".join(e.triggered_rules) for e in explanations
        ]
        result[f"{p}summary"] = [e.summary for e in explanations]

        return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_rule_summary(
    r1: RuleResult,
    r2: RuleResult,
    r3: RuleResult,
    triggered: list[str],
) -> str:
    """
    Compose a human-readable sentence describing which rules fired.

    Examples
    --------
    "No rules triggered."
    "1 rule triggered: threshold_breach — Value 1200.00 exceeds budget limit…"
    "2 rules triggered: threshold_breach; sudden_jump — …; …"
    """
    if not triggered:
        return "No rules triggered."

    fired_results = [r for r in (r1, r2, r3) if r.fired]
    count = len(fired_results)
    label = "1 rule triggered" if count == 1 else f"{count} rules triggered"

    detail = "; ".join(
        f"{r.rule} — {r.reason}" for r in fired_results
    )
    return f"{label}: {detail}"
