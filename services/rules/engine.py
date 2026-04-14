"""
Rule engine for the FinGuard detection pipeline.

RUL-01  ThresholdBreachRule   – absolute budget-limit breach
RUL-02  SuddenJumpRule        – single-period percentage spike
RUL-03  SustainedIncreaseRule – consecutive-period upward trend

Each rule returns a RuleResult with:
  - fired (bool)   : whether the rule triggered
  - score (float)  : confidence in [0.0, 1.0]
  - reason (str)   : human-readable explanation for EXP-02
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .config import RULE_THRESHOLDS


@dataclass
class RuleResult:
    rule: str
    fired: bool
    score: float          # 0.0 = definitely normal, 1.0 = definitely anomalous
    reason: str


# ---------------------------------------------------------------------------
# RUL-01: Threshold Breach Rule
# ---------------------------------------------------------------------------

class ThresholdBreachRule:
    """
    Fires when a single cost observation exceeds the configured budget limit.
    Score scales linearly with how far the value overshoots the limit,
    capped at 1.0.
    """

    name = "threshold_breach"

    def __init__(self, budget_limit: float | None = None) -> None:
        self.budget_limit: float = (
            budget_limit
            if budget_limit is not None
            else RULE_THRESHOLDS["threshold_breach_budget_limit"]
        )

    def evaluate(self, value: float) -> RuleResult:
        if value <= self.budget_limit:
            return RuleResult(
                rule=self.name,
                fired=False,
                score=0.0,
                reason=f"Value {value:.2f} within budget limit {self.budget_limit:.2f}.",
            )

        if self.budget_limit == 0.0:
            overshoot = 1.0
        else:
            overshoot = (value - self.budget_limit) / self.budget_limit
        score = min(overshoot, 1.0)
        return RuleResult(
            rule=self.name,
            fired=True,
            score=score,
            reason=(
                f"Value {value:.2f} exceeds budget limit {self.budget_limit:.2f} "
                f"by {overshoot * 100:.1f}%."
            ),
        )


# ---------------------------------------------------------------------------
# RUL-02: Sudden Jump Rule
# ---------------------------------------------------------------------------

class SuddenJumpRule:
    """
    Fires when the latest observation is more than `jump_pct` above the
    rolling-window mean of preceding observations.

    score = min((actual_pct - jump_pct) / jump_pct, 1.0)  when fired.
    """

    name = "sudden_jump"

    def __init__(self, jump_pct: float | None = None) -> None:
        self.jump_pct: float = (
            jump_pct
            if jump_pct is not None
            else RULE_THRESHOLDS["sudden_jump_pct"]
        )

    def evaluate(self, current: float, window: Sequence[float]) -> RuleResult:
        if len(window) == 0:
            return RuleResult(
                rule=self.name,
                fired=False,
                score=0.0,
                reason="Insufficient history for sudden-jump evaluation.",
            )

        mean = float(np.mean(window))
        if mean == 0.0:
            return RuleResult(
                rule=self.name,
                fired=False,
                score=0.0,
                reason="Window mean is zero; cannot compute relative jump.",
            )

        actual_pct = (current - mean) / mean

        if actual_pct <= self.jump_pct:
            return RuleResult(
                rule=self.name,
                fired=False,
                score=0.0,
                reason=(
                    f"Jump of {actual_pct * 100:.1f}% is below threshold "
                    f"{self.jump_pct * 100:.1f}%."
                ),
            )

        score = min((actual_pct - self.jump_pct) / self.jump_pct, 1.0)
        return RuleResult(
            rule=self.name,
            fired=True,
            score=score,
            reason=(
                f"Sudden jump of {actual_pct * 100:.1f}% detected "
                f"(threshold {self.jump_pct * 100:.1f}%, window mean {mean:.2f})."
            ),
        )


# ---------------------------------------------------------------------------
# RUL-03: Sustained Increase Rule
# ---------------------------------------------------------------------------

class SustainedIncreaseRule:
    """
    Fires when `window` consecutive observations each grow by at least
    `min_growth` relative to the previous observation.

    score = proportion of pairs in the window that satisfy the growth
    condition (so a perfect run scores 1.0).
    """

    name = "sustained_increase"

    def __init__(
        self,
        window: int | None = None,
        min_growth: float | None = None,
    ) -> None:
        self.window: int = (
            window
            if window is not None
            else RULE_THRESHOLDS["sustained_increase_window"]
        )
        self.min_growth: float = (
            min_growth
            if min_growth is not None
            else RULE_THRESHOLDS["sustained_increase_min_growth"]
        )

    def evaluate(self, series: Sequence[float]) -> RuleResult:
        """
        Parameters
        ----------
        series:
            Time-ordered observations; the *last* `window + 1` values are
            examined (the +1 gives us `window` consecutive pairs).
        """
        if len(series) < self.window + 1:
            return RuleResult(
                rule=self.name,
                fired=False,
                score=0.0,
                reason=(
                    f"Need at least {self.window + 1} observations, "
                    f"got {len(series)}."
                ),
            )

        tail = list(series[-(self.window + 1):])
        passing = 0
        for prev, curr in zip(tail, tail[1:]):
            if prev == 0.0:
                # Zero-value period: treat a positive jump as growth, otherwise
                # it cannot satisfy the threshold so the score stays lower.
                if curr > 0:
                    passing += 1
                continue
            growth = (curr - prev) / abs(prev)
            if growth >= self.min_growth:
                passing += 1

        score = passing / self.window if self.window > 0 else 0.0
        fired = passing == self.window

        if fired:
            reason = (
                f"All {self.window} consecutive periods grew by ≥"
                f"{self.min_growth * 100:.1f}% — sustained upward trend detected."
            )
        else:
            reason = (
                f"Only {passing}/{self.window} periods met the "
                f"{self.min_growth * 100:.1f}% growth threshold."
            )

        return RuleResult(rule=self.name, fired=fired, score=score, reason=reason)
