"""
RUL-04: Rule weights and configuration for the hybrid detection ensemble.

Weights are used by ENS-01 (weighted score fusion) to combine rule-based
scores with ML and time-series scores.  All weights across the ensemble
(rules + TS + ML) should sum to 1.0 — these cover the rule sub-total only.

Override at runtime by setting the FINGUARD_RULE_* environment variables
or by passing a custom dict to RuleEngine.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict

# ---------------------------------------------------------------------------
# Per-rule weights (contribution to ensemble score, 0.0 – 1.0)
# The three rule scores are blended according to these weights before being
# forwarded to the ensemble.  They must sum to 1.0.
# ---------------------------------------------------------------------------
RULE_WEIGHTS: Dict[str, float] = {
    "threshold_breach":   float(os.getenv("FINGUARD_WEIGHT_THRESHOLD",  "0.50")),
    "sudden_jump":        float(os.getenv("FINGUARD_WEIGHT_SUDDEN_JUMP","0.30")),
    "sustained_increase": float(os.getenv("FINGUARD_WEIGHT_SUSTAINED",  "0.20")),
}

# ---------------------------------------------------------------------------
# Per-rule detection thresholds
# ---------------------------------------------------------------------------
RULE_THRESHOLDS: Dict[str, float | int] = {
    # RUL-01: absolute budget ceiling (currency units); breaching this fires
    # the rule regardless of relative change.
    "threshold_breach_budget_limit": float(
        os.getenv("FINGUARD_THRESHOLD_BUDGET_LIMIT", "1000.0")
    ),

    # RUL-02: minimum % jump relative to the rolling window mean to be
    # considered a sudden spike (e.g. 0.50 → 50 % above the mean).
    "sudden_jump_pct": float(
        os.getenv("FINGUARD_THRESHOLD_SUDDEN_JUMP_PCT", "0.50")
    ),

    # RUL-03: number of consecutive periods that must show an upward trend
    # before the sustained-increase rule fires.
    "sustained_increase_window": int(
        os.getenv("FINGUARD_THRESHOLD_SUSTAINED_WINDOW", "3")
    ),
    # RUL-03: minimum per-period growth rate (fraction) for the trend to
    # qualify (e.g. 0.05 → each period must be at least 5 % higher than the
    # previous one).
    "sustained_increase_min_growth": float(
        os.getenv("FINGUARD_THRESHOLD_SUSTAINED_GROWTH", "0.05")
    ),
}


# ---------------------------------------------------------------------------
# Validation helper (called at import time so misconfiguration is loud)
# ---------------------------------------------------------------------------
def _validate() -> None:
    total = sum(RULE_WEIGHTS.values())
    if not (0.999 <= total <= 1.001):
        raise ValueError(
            f"RULE_WEIGHTS must sum to 1.0, got {total:.4f}. "
            "Check FINGUARD_WEIGHT_* environment variables."
        )
    for name, w in RULE_WEIGHTS.items():
        if not (0.0 <= w <= 1.0):
            raise ValueError(f"Weight for '{name}' must be in [0, 1], got {w}.")


_validate()
