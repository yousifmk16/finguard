"""
Unit tests for the rule engine.

Covers:
  RUL-01  ThresholdBreachRule   – absolute budget-limit breach
  RUL-02  SuddenJumpRule        – single-period percentage spike
  RUL-03  SustainedIncreaseRule – consecutive-period upward trend
"""

from __future__ import annotations

import pytest

from services.rules.engine import (
    ThresholdBreachRule,
    SuddenJumpRule,
    SustainedIncreaseRule,
    RuleResult,
)
from services.rules.config import RULE_THRESHOLDS


# ---------------------------------------------------------------------------
# RUL-01: ThresholdBreachRule
# ---------------------------------------------------------------------------

class TestThresholdBreachRule:

    def _rule(self, limit: float = 1000.0) -> ThresholdBreachRule:
        return ThresholdBreachRule(budget_limit=limit)

    # --- fired / not-fired decisions ---

    def test_value_below_limit_does_not_fire(self) -> None:
        result = self._rule(1000.0).evaluate(500.0)
        assert result.fired is False

    def test_value_equal_to_limit_does_not_fire(self) -> None:
        result = self._rule(1000.0).evaluate(1000.0)
        assert result.fired is False

    def test_value_above_limit_fires(self) -> None:
        result = self._rule(1000.0).evaluate(1001.0)
        assert result.fired is True

    # --- score correctness ---

    def test_score_zero_when_not_fired(self) -> None:
        result = self._rule(1000.0).evaluate(999.99)
        assert result.score == 0.0

    def test_score_scales_with_overshoot(self) -> None:
        # 50 % overshoot → score = 0.50
        result = self._rule(1000.0).evaluate(1500.0)
        assert abs(result.score - 0.50) < 1e-9

    def test_score_capped_at_one_for_large_overshoot(self) -> None:
        # 200 % overshoot would be 2.0, but must be capped at 1.0
        result = self._rule(1000.0).evaluate(3000.0)
        assert result.score == 1.0

    def test_score_exactly_one_at_double_the_limit(self) -> None:
        # value = 2 × limit → overshoot = 100 % → score = 1.0
        result = self._rule(500.0).evaluate(1000.0)
        assert result.score == 1.0

    def test_score_is_fractional_for_small_overshoot(self) -> None:
        # 10 % overshoot → score = 0.10
        result = self._rule(1000.0).evaluate(1100.0)
        assert abs(result.score - 0.10) < 1e-9

    # --- RuleResult structure ---

    def test_result_is_rule_result(self) -> None:
        result = self._rule().evaluate(500.0)
        assert isinstance(result, RuleResult)

    def test_result_rule_name(self) -> None:
        result = self._rule().evaluate(500.0)
        assert result.rule == "threshold_breach"

    def test_reason_contains_value_and_limit_when_not_fired(self) -> None:
        result = self._rule(1000.0).evaluate(500.0)
        assert "500.00" in result.reason
        assert "1000.00" in result.reason

    def test_reason_contains_overshoot_percentage_when_fired(self) -> None:
        # 50 % overshoot
        result = self._rule(1000.0).evaluate(1500.0)
        assert "50.0%" in result.reason

    # --- default budget limit from config ---

    def test_default_budget_limit_comes_from_config(self) -> None:
        rule = ThresholdBreachRule()
        assert rule.budget_limit == RULE_THRESHOLDS["threshold_breach_budget_limit"]

    def test_default_limit_not_fired_at_zero(self) -> None:
        rule = ThresholdBreachRule()
        result = rule.evaluate(0.0)
        assert result.fired is False
        assert result.score == 0.0

    # --- edge cases ---

    def test_very_small_overshoot_fires(self) -> None:
        result = self._rule(1000.0).evaluate(1000.01)
        assert result.fired is True
        assert result.score > 0.0

    def test_negative_value_does_not_fire(self) -> None:
        result = self._rule(1000.0).evaluate(-500.0)
        assert result.fired is False
        assert result.score == 0.0

    def test_zero_limit_fires_for_positive_value(self) -> None:
        result = self._rule(0.0).evaluate(1.0)
        assert result.fired is True

    def test_score_in_valid_range_for_arbitrary_inputs(self) -> None:
        import random
        rng = random.Random(42)
        rule = self._rule(500.0)
        for _ in range(50):
            v = rng.uniform(0, 2000)
            r = rule.evaluate(v)
            assert 0.0 <= r.score <= 1.0, f"score {r.score} out of range for value {v}"


# ---------------------------------------------------------------------------
# RUL-02: SuddenJumpRule
# ---------------------------------------------------------------------------

class TestSuddenJumpRule:
    """
    jump_pct=0.50 means the current value must be > 50 % above the window mean
    to fire.  Score formula: min((actual_pct - jump_pct) / jump_pct, 1.0).
    """

    def _rule(self, jump_pct: float = 0.50) -> SuddenJumpRule:
        return SuddenJumpRule(jump_pct=jump_pct)

    # --- fired / not-fired decisions ---

    def test_empty_window_does_not_fire(self) -> None:
        result = self._rule().evaluate(1000.0, [])
        assert result.fired is False
        assert result.score == 0.0

    def test_zero_mean_positive_current_fires_max(self) -> None:
        # Any positive spend from a zero-cost baseline is maximally anomalous.
        result = self._rule().evaluate(100.0, [0.0, 0.0, 0.0])
        assert result.fired is True
        assert result.score == 1.0

    def test_zero_mean_zero_current_does_not_fire(self) -> None:
        result = self._rule().evaluate(0.0, [0.0, 0.0, 0.0])
        assert result.fired is False
        assert result.score == 0.0

    def test_value_at_threshold_does_not_fire(self) -> None:
        # mean=100, jump_pct=0.50 → threshold = 150; value=150 should NOT fire
        result = self._rule(0.50).evaluate(150.0, [100.0, 100.0, 100.0])
        assert result.fired is False

    def test_value_below_threshold_does_not_fire(self) -> None:
        result = self._rule(0.50).evaluate(120.0, [100.0, 100.0, 100.0])
        assert result.fired is False

    def test_value_just_above_threshold_fires(self) -> None:
        # mean=100, threshold=150; value=150.01 fires
        result = self._rule(0.50).evaluate(150.01, [100.0, 100.0, 100.0])
        assert result.fired is True

    def test_large_spike_fires(self) -> None:
        result = self._rule(0.50).evaluate(500.0, [100.0, 100.0, 100.0])
        assert result.fired is True

    def test_drop_below_mean_does_not_fire(self) -> None:
        result = self._rule(0.50).evaluate(50.0, [100.0, 100.0, 100.0])
        assert result.fired is False

    # --- score correctness ---

    def test_score_zero_when_not_fired(self) -> None:
        result = self._rule(0.50).evaluate(100.0, [100.0, 100.0, 100.0])
        assert result.score == 0.0

    def test_score_at_double_threshold_excess(self) -> None:
        # actual_pct = 1.50 (150% above mean=100, value=250)
        # jump_pct   = 0.50
        # score = min((1.50 - 0.50) / 0.50, 1.0) = min(2.0, 1.0) = 1.0
        result = self._rule(0.50).evaluate(250.0, [100.0] * 5)
        assert result.score == 1.0

    def test_score_fractional_for_moderate_spike(self) -> None:
        # mean=100, value=175 → actual_pct=0.75, jump_pct=0.50
        # score = (0.75 - 0.50) / 0.50 = 0.50
        result = self._rule(0.50).evaluate(175.0, [100.0] * 5)
        assert abs(result.score - 0.50) < 1e-9

    def test_score_capped_at_one(self) -> None:
        result = self._rule(0.50).evaluate(10_000.0, [100.0] * 5)
        assert result.score == 1.0

    # --- mean computation ---

    def test_uses_mean_of_window(self) -> None:
        # window mean = (100+200+300) / 3 = 200; 50% threshold → fires at > 300
        result = self._rule(0.50).evaluate(350.0, [100.0, 200.0, 300.0])
        assert result.fired is True

    def test_single_element_window_allowed(self) -> None:
        result = self._rule(0.50).evaluate(200.0, [100.0])
        assert result.fired is True  # 100% jump > 50% threshold

    # --- RuleResult structure ---

    def test_result_rule_name(self) -> None:
        result = self._rule().evaluate(50.0, [100.0])
        assert result.rule == "sudden_jump"

    def test_reason_mentions_threshold_when_not_fired(self) -> None:
        result = self._rule(0.50).evaluate(120.0, [100.0] * 3)
        assert "50.0%" in result.reason

    def test_reason_mentions_jump_and_mean_when_fired(self) -> None:
        result = self._rule(0.50).evaluate(200.0, [100.0] * 3)
        assert "100.0%" in result.reason   # actual jump % in reason
        assert "100.00" in result.reason   # window mean in reason

    def test_reason_for_empty_window(self) -> None:
        result = self._rule().evaluate(100.0, [])
        assert "Insufficient" in result.reason

    def test_reason_for_zero_mean(self) -> None:
        result = self._rule().evaluate(100.0, [0.0])
        assert "zero" in result.reason.lower()

    # --- default config wiring ---

    def test_default_jump_pct_comes_from_config(self) -> None:
        rule = SuddenJumpRule()
        assert rule.jump_pct == RULE_THRESHOLDS["sudden_jump_pct"]

    # --- score range invariant ---

    def test_score_in_valid_range_for_arbitrary_inputs(self) -> None:
        import random
        rng = random.Random(7)
        rule = self._rule(0.50)
        window = [rng.uniform(50, 200) for _ in range(10)]
        for _ in range(50):
            v = rng.uniform(0, 600)
            r = rule.evaluate(v, window)
            assert 0.0 <= r.score <= 1.0, f"score {r.score} out of range for value {v}"


# ---------------------------------------------------------------------------
# RUL-03: SustainedIncreaseRule
# ---------------------------------------------------------------------------

class TestSustainedIncreaseRule:
    """
    window=3, min_growth=0.05 means all 3 consecutive pairs in the tail
    must each grow by ≥ 5 % for the rule to fire.
    Score = passing_pairs / window  (0.0 – 1.0).
    """

    def _rule(self, window: int = 3, min_growth: float = 0.05) -> SustainedIncreaseRule:
        return SustainedIncreaseRule(window=window, min_growth=min_growth)

    # --- insufficient data ---

    def test_too_short_series_does_not_fire(self) -> None:
        # window=3 requires 4 observations; only 3 provided
        result = self._rule(window=3).evaluate([100.0, 110.0, 121.0])
        assert result.fired is False
        assert result.score == 0.0

    def test_empty_series_does_not_fire(self) -> None:
        result = self._rule(window=3).evaluate([])
        assert result.fired is False

    def test_reason_mentions_required_length_when_too_short(self) -> None:
        result = self._rule(window=3).evaluate([100.0, 110.0])
        assert "4" in result.reason   # needs window+1 = 4

    # --- fired / not-fired decisions ---

    def test_perfect_growth_run_fires(self) -> None:
        # Each step grows by exactly 10 % (> 5 % threshold)
        series = [100.0, 110.0, 121.0, 133.1]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert result.fired is True

    def test_one_period_below_threshold_does_not_fire(self) -> None:
        # Third step grows by only 1 % — below 5 % threshold
        series = [100.0, 110.0, 121.0, 122.21]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert result.fired is False

    def test_flat_series_does_not_fire(self) -> None:
        result = self._rule(window=3, min_growth=0.05).evaluate([100.0] * 4)
        assert result.fired is False

    def test_declining_series_does_not_fire(self) -> None:
        result = self._rule(window=3, min_growth=0.05).evaluate(
            [200.0, 180.0, 160.0, 140.0]
        )
        assert result.fired is False

    def test_exact_min_growth_fires(self) -> None:
        # Each step grows by exactly min_growth (0.05)
        series = [100.0, 105.0, 110.25, 115.7625]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert result.fired is True

    # --- only the tail window is examined ---

    def test_only_tail_matters_old_bad_data_ignored(self) -> None:
        # First half is flat, last 4 observations grow steadily
        flat = [100.0] * 10
        growing = [200.0, 220.0, 242.0, 266.2]   # 10 % each step
        result = self._rule(window=3, min_growth=0.05).evaluate(flat + growing)
        assert result.fired is True

    def test_old_good_data_cannot_rescue_bad_tail(self) -> None:
        # First half grows perfectly, last 4 are flat
        growing = [100.0 * (1.10 ** i) for i in range(10)]
        flat_tail = [growing[-1]] * 4
        result = self._rule(window=3, min_growth=0.05).evaluate(growing + flat_tail)
        assert result.fired is False

    # --- score correctness ---

    def test_score_one_for_perfect_run(self) -> None:
        series = [100.0, 110.0, 121.0, 133.1]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert result.score == 1.0

    def test_score_zero_for_no_passing_periods(self) -> None:
        result = self._rule(window=3, min_growth=0.05).evaluate([100.0] * 4)
        assert result.score == 0.0

    def test_score_partial_for_mixed_periods(self) -> None:
        # window=3: pair1 +10% (pass), pair2 +10% (pass), pair3 +1% (fail)
        # score = 2/3
        series = [100.0, 110.0, 121.0, 122.21]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert abs(result.score - 2 / 3) < 1e-9

    def test_score_one_third_for_one_passing_period(self) -> None:
        # pair1 +10% (pass), pair2 flat (fail), pair3 flat (fail)
        series = [100.0, 110.0, 110.0, 110.0]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert abs(result.score - 1 / 3) < 1e-9

    # --- zero-value period handling ---

    def test_zero_prev_with_positive_curr_counts_as_passing(self) -> None:
        # prev=0, curr=50 → treated as growth (passes)
        series = [100.0, 110.0, 0.0, 50.0]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        # pair1: 100→110 (+10%, pass), pair2: 110→0 (-100%, fail), pair3: 0→50 (pass)
        # score = 2/3, fired = False
        assert result.fired is False
        assert abs(result.score - 2 / 3) < 1e-9

    def test_zero_prev_with_zero_curr_does_not_pass(self) -> None:
        series = [100.0, 110.0, 0.0, 0.0]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        # pair3: 0→0 does NOT pass
        assert result.fired is False

    # --- window parameter ---

    def test_window_one_fires_on_single_growth_step(self) -> None:
        result = self._rule(window=1, min_growth=0.05).evaluate([100.0, 110.0])
        assert result.fired is True

    def test_window_one_does_not_fire_on_flat(self) -> None:
        result = self._rule(window=1, min_growth=0.05).evaluate([100.0, 100.0])
        assert result.fired is False

    # --- RuleResult structure ---

    def test_result_rule_name(self) -> None:
        result = self._rule().evaluate([100.0] * 10)
        assert result.rule == "sustained_increase"

    def test_reason_mentions_all_periods_when_fired(self) -> None:
        series = [100.0, 110.0, 121.0, 133.1]
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert "3" in result.reason
        assert "5.0%" in result.reason

    def test_reason_shows_passing_count_when_not_fired(self) -> None:
        series = [100.0, 110.0, 121.0, 122.21]   # 2 of 3 pass
        result = self._rule(window=3, min_growth=0.05).evaluate(series)
        assert "2/3" in result.reason

    # --- default config wiring ---

    def test_default_params_come_from_config(self) -> None:
        rule = SustainedIncreaseRule()
        assert rule.window    == RULE_THRESHOLDS["sustained_increase_window"]
        assert rule.min_growth == RULE_THRESHOLDS["sustained_increase_min_growth"]

    # --- score range invariant ---

    def test_score_always_in_valid_range(self) -> None:
        import random
        rng = random.Random(99)
        rule = self._rule(window=3, min_growth=0.05)
        for _ in range(50):
            series = [rng.uniform(50, 300) for _ in range(rng.randint(1, 12))]
            r = rule.evaluate(series)
            assert 0.0 <= r.score <= 1.0, f"score {r.score} out of range for series {series}"
