"""
EXP-02: Unit tests for triggered-rule explanation details.

Covers:
  RuleExplanation        – dataclass fields
  RuleExplainerConfig    – defaults and overrides
  RuleExplainer          – explain_series() column output
  RuleExplainer          – explain_row() single-row access
  RuleExplainer          – explain_group() multi-series isolation
  RuleExplainer          – from_scorer() factory
  Rule firing cases      – RUL-01 fires, RUL-02 fires, RUL-03 fires, none fire
  Summary text           – no-trigger / single / multi trigger messages
  Window isolation       – RUL-02/03 context doesn't bleed across series
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from ml.src.inference.rule_explain import (
    RuleExplainer,
    RuleExplainerConfig,
    RuleExplanation,
)
from services.rules.engine import RuleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)


def _make_df(
    costs: list[float],
    account_id: str = "acct-001",
    service: str = "compute",
    region: str = "us-east1",
) -> pd.DataFrame:
    """Minimal time-ordered cost DataFrame."""
    n = len(costs)
    buckets = [_START + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame(
        {
            "bucket": pd.to_datetime(buckets, utc=True),
            "account_id": account_id,
            "service": service,
            "region": region,
            "total_cost": costs,
        }
    )


def _explainer(
    budget_limit: float = 1000.0,
    jump_pct: float = 0.5,
    sustained_window: int = 3,
    sustained_min_growth: float = 0.05,
) -> RuleExplainer:
    """RuleExplainer with explicit thresholds (avoids env-var side-effects)."""
    cfg = RuleExplainerConfig(
        budget_limit=budget_limit,
        jump_pct=jump_pct,
        sustained_window=sustained_window,
        sustained_min_growth=sustained_min_growth,
    )
    return RuleExplainer(cfg)


# ---------------------------------------------------------------------------
# RuleExplanation dataclass
# ---------------------------------------------------------------------------


class TestRuleExplanation:
    def _make_result(self, rule: str, fired: bool) -> RuleResult:
        return RuleResult(rule=rule, fired=fired, score=0.5 if fired else 0.0, reason="reason")

    def test_fields_present(self):
        exp = RuleExplanation(
            threshold_result=self._make_result("threshold_breach", True),
            jump_result=self._make_result("sudden_jump", False),
            sustained_result=self._make_result("sustained_increase", False),
            triggered_rules=["threshold_breach"],
            summary="1 rule triggered: threshold_breach — reason",
        )
        assert exp.threshold_result.fired == True
        assert exp.triggered_rules == ["threshold_breach"]

    def test_default_triggered_empty(self):
        exp = RuleExplanation(
            threshold_result=self._make_result("threshold_breach", False),
            jump_result=self._make_result("sudden_jump", False),
            sustained_result=self._make_result("sustained_increase", False),
        )
        assert exp.triggered_rules == []
        assert exp.summary == ""


# ---------------------------------------------------------------------------
# RuleExplainerConfig
# ---------------------------------------------------------------------------


class TestRuleExplainerConfig:
    def test_defaults(self):
        cfg = RuleExplainerConfig()
        assert cfg.target_col == "total_cost"
        assert cfg.jump_lookback == 15
        assert cfg.output_prefix == "exp_rule_"

    def test_custom_prefix(self):
        cfg = RuleExplainerConfig(output_prefix="r_")
        assert cfg.output_prefix == "r_"


# ---------------------------------------------------------------------------
# RuleExplainer.explain_series() — output columns
# ---------------------------------------------------------------------------


class TestExplainSeriesColumns:
    def test_all_columns_present(self):
        gen = _explainer()
        df = _make_df([100.0] * 5)
        result = gen.explain_series(df)
        expected = [
            "exp_rule_threshold_fired", "exp_rule_threshold_score", "exp_rule_threshold_reason",
            "exp_rule_jump_fired", "exp_rule_jump_score", "exp_rule_jump_reason",
            "exp_rule_sustained_fired", "exp_rule_sustained_score", "exp_rule_sustained_reason",
            "exp_rule_triggered_rules", "exp_rule_summary",
        ]
        for col in expected:
            assert col in result.columns, f"Missing: {col}"

    def test_row_count_unchanged(self):
        gen = _explainer()
        df = _make_df([100.0] * 10)
        assert len(gen.explain_series(df)) == 10

    def test_original_columns_preserved(self):
        gen = _explainer()
        df = _make_df([100.0] * 4)
        result = gen.explain_series(df)
        for col in df.columns:
            assert col in result.columns

    def test_input_df_not_mutated(self):
        gen = _explainer()
        df = _make_df([100.0] * 4)
        original_cols = list(df.columns)
        gen.explain_series(df)
        assert list(df.columns) == original_cols

    def test_custom_prefix_applied(self):
        gen = RuleExplainer(RuleExplainerConfig(output_prefix="x_"))
        df = _make_df([100.0] * 3)
        result = gen.explain_series(df)
        assert "x_threshold_fired" in result.columns
        assert "exp_rule_threshold_fired" not in result.columns


# ---------------------------------------------------------------------------
# RUL-01: ThresholdBreachRule fires
# ---------------------------------------------------------------------------


class TestThresholdRule:
    def test_fires_when_above_budget(self):
        # budget = 1000; last row = 1200 → should fire
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([100.0] * 4 + [1200.0])
        result = gen.explain_series(df)
        assert result["exp_rule_threshold_fired"].iloc[-1] == True

    def test_does_not_fire_when_within_budget(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([100.0] * 5)
        result = gen.explain_series(df)
        assert not result["exp_rule_threshold_fired"].any()

    def test_score_positive_when_fired(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1200.0])
        result = gen.explain_series(df)
        assert result["exp_rule_threshold_score"].iloc[0] > 0.0

    def test_score_zero_when_not_fired(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([500.0])
        result = gen.explain_series(df)
        assert result["exp_rule_threshold_score"].iloc[0] == 0.0

    def test_reason_is_non_empty_string(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1200.0])
        result = gen.explain_series(df)
        reason = result["exp_rule_threshold_reason"].iloc[0]
        assert isinstance(reason, str) and len(reason) > 0

    def test_reason_mentions_value_and_limit(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1500.0])
        result = gen.explain_series(df)
        reason = result["exp_rule_threshold_reason"].iloc[0]
        assert "1500" in reason or "1,500" in reason
        assert "1000" in reason or "limit" in reason.lower()


# ---------------------------------------------------------------------------
# RUL-02: SuddenJumpRule fires
# ---------------------------------------------------------------------------


class TestJumpRule:
    def test_fires_on_large_spike(self):
        # Window mean ≈ 100; spike = 200 (100% jump > 50% threshold)
        gen = _explainer(jump_pct=0.5)
        costs = [100.0] * 15 + [200.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        assert result["exp_rule_jump_fired"].iloc[-1] == True

    def test_does_not_fire_below_threshold(self):
        # Jump of 20% is below the 50% threshold
        gen = _explainer(jump_pct=0.5)
        costs = [100.0] * 15 + [120.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        assert result["exp_rule_jump_fired"].iloc[-1] == False

    def test_no_fire_without_history(self):
        # First row has no window — rule cannot fire
        gen = _explainer(jump_pct=0.5)
        df = _make_df([999.0])
        result = gen.explain_series(df)
        assert result["exp_rule_jump_fired"].iloc[0] == False

    def test_reason_mentions_jump_percentage(self):
        gen = _explainer(jump_pct=0.5)
        costs = [100.0] * 15 + [200.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        reason = result["exp_rule_jump_reason"].iloc[-1]
        assert "%" in reason or "jump" in reason.lower()


# ---------------------------------------------------------------------------
# RUL-03: SustainedIncreaseRule fires
# ---------------------------------------------------------------------------


class TestSustainedRule:
    def test_fires_on_sustained_growth(self):
        # window=3, min_growth=0.05 → need 3 consecutive 5%+ increases
        gen = _explainer(sustained_window=3, sustained_min_growth=0.05)
        # Build a series with clear sustained increase at the end
        costs = [100.0, 100.0, 100.0, 100.0, 106.0, 113.0, 120.0, 128.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        assert result["exp_rule_sustained_fired"].iloc[-1] == True

    def test_does_not_fire_without_enough_rows(self):
        # window=3 requires 4 rows; provide only 2
        gen = _explainer(sustained_window=3, sustained_min_growth=0.05)
        df = _make_df([100.0, 110.0])
        result = gen.explain_series(df)
        assert not result["exp_rule_sustained_fired"].any()

    def test_does_not_fire_on_flat_series(self):
        gen = _explainer(sustained_window=3, sustained_min_growth=0.05)
        df = _make_df([100.0] * 8)
        result = gen.explain_series(df)
        assert not result["exp_rule_sustained_fired"].any()

    def test_reason_is_non_empty(self):
        gen = _explainer(sustained_window=3, sustained_min_growth=0.05)
        costs = [100.0, 100.0, 100.0, 100.0, 106.0, 113.0, 120.0, 128.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        reason = result["exp_rule_sustained_reason"].iloc[-1]
        assert isinstance(reason, str) and len(reason) > 0


# ---------------------------------------------------------------------------
# triggered_rules and summary columns
# ---------------------------------------------------------------------------


class TestTriggeredRulesColumn:
    def test_no_rules_fired_empty_string(self):
        gen = _explainer(budget_limit=1000.0, jump_pct=0.5)
        df = _make_df([100.0] * 5)
        result = gen.explain_series(df)
        assert all(v == "" for v in result["exp_rule_triggered_rules"])

    def test_threshold_in_triggered_when_fired(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1200.0])
        result = gen.explain_series(df)
        assert "threshold_breach" in result["exp_rule_triggered_rules"].iloc[0]

    def test_multiple_rules_comma_separated(self):
        # Both threshold breach AND sudden jump should fire on this row
        gen = _explainer(budget_limit=1000.0, jump_pct=0.5)
        costs = [100.0] * 15 + [1500.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        triggered = result["exp_rule_triggered_rules"].iloc[-1]
        assert "threshold_breach" in triggered
        assert "sudden_jump" in triggered
        assert "," in triggered

    def test_summary_no_trigger(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([100.0] * 3)
        result = gen.explain_series(df)
        assert result["exp_rule_summary"].iloc[0] == "No rules triggered."

    def test_summary_single_trigger(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1200.0])
        result = gen.explain_series(df)
        summary = result["exp_rule_summary"].iloc[0]
        assert "1 rule triggered" in summary
        assert "threshold_breach" in summary

    def test_summary_multi_trigger_count(self):
        gen = _explainer(budget_limit=1000.0, jump_pct=0.5)
        costs = [100.0] * 15 + [1500.0]
        df = _make_df(costs)
        result = gen.explain_series(df)
        summary = result["exp_rule_summary"].iloc[-1]
        assert "2 rules triggered" in summary


# ---------------------------------------------------------------------------
# RuleExplainer.explain_row()
# ---------------------------------------------------------------------------


class TestExplainRow:
    def test_returns_rule_explanation(self):
        gen = _explainer()
        df = _make_df([100.0] * 5)
        exp = gen.explain_row(0, df)
        assert isinstance(exp, RuleExplanation)

    def test_row_index_respected(self):
        # Only last row exceeds budget
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([100.0, 100.0, 1200.0])
        exp_last = gen.explain_row(2, df)
        exp_first = gen.explain_row(0, df)
        assert exp_last.threshold_result.fired == True
        assert exp_first.threshold_result.fired == False

    def test_triggered_rules_list(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([1200.0])
        exp = gen.explain_row(0, df)
        assert "threshold_breach" in exp.triggered_rules

    def test_no_trigger_empty_list(self):
        gen = _explainer(budget_limit=1000.0)
        df = _make_df([50.0])
        exp = gen.explain_row(0, df)
        assert exp.triggered_rules == []


# ---------------------------------------------------------------------------
# RuleExplainer.explain_group() — multi-series isolation
# ---------------------------------------------------------------------------


class TestExplainGroup:
    def test_group_columns_present(self):
        gen = _explainer()
        df1 = _make_df([100.0] * 5, account_id="A", service="s1", region="r1")
        df2 = _make_df([100.0] * 5, account_id="B", service="s1", region="r1")
        df = pd.concat([df1, df2], ignore_index=True)
        result = gen.explain_group(df)
        assert "exp_rule_threshold_fired" in result.columns
        assert len(result) == 10

    def test_window_does_not_bleed_across_groups(self):
        # Group A: 15 low-cost rows, then a spike → jump rule fires
        # Group B: only 1 row (spike) with no window → jump rule must NOT fire
        gen = _explainer(jump_pct=0.5)
        grp_a = _make_df([100.0] * 15 + [200.0], account_id="A", service="s", region="r")
        grp_b = _make_df([200.0], account_id="B", service="s", region="r")
        df = pd.concat([grp_a, grp_b], ignore_index=True)
        result = gen.explain_group(df)

        a_last = result[result["account_id"] == "A"].iloc[-1]
        b_last = result[result["account_id"] == "B"].iloc[-1]

        assert a_last["exp_rule_jump_fired"] == True
        assert b_last["exp_rule_jump_fired"] == False

    def test_index_preserved(self):
        gen = _explainer()
        df1 = _make_df([100.0] * 3, account_id="A", service="s", region="r")
        df2 = _make_df([100.0] * 3, account_id="B", service="s", region="r")
        df = pd.concat([df1, df2], ignore_index=True)
        result = gen.explain_group(df)
        assert list(result.index) == list(df.index)


# ---------------------------------------------------------------------------
# RuleExplainer.from_scorer() factory
# ---------------------------------------------------------------------------


class TestFromScorer:
    def test_creates_explainer_from_mock_scorer(self):
        mock_config = MagicMock()
        mock_config.target_col = "total_cost"
        mock_config.group_cols = ["account_id", "service", "region"]
        mock_config.budget_limit = 500.0
        mock_config.jump_pct = 0.3
        mock_config.sustained_window = 2
        mock_config.sustained_min_growth = 0.1

        mock_scorer = MagicMock()
        mock_scorer.config = mock_config

        explainer = RuleExplainer.from_scorer(mock_scorer)
        assert isinstance(explainer, RuleExplainer)
        assert explainer._threshold_rule.budget_limit == 500.0
        assert explainer._jump_rule.jump_pct == 0.3
        assert explainer._sustained_rule.window == 2

    def test_from_scorer_budget_threshold_fires(self):
        mock_config = MagicMock()
        mock_config.target_col = "total_cost"
        mock_config.group_cols = ["account_id", "service", "region"]
        mock_config.budget_limit = 200.0   # low limit
        mock_config.jump_pct = None
        mock_config.sustained_window = None
        mock_config.sustained_min_growth = None

        mock_scorer = MagicMock()
        mock_scorer.config = mock_config

        explainer = RuleExplainer.from_scorer(mock_scorer)
        df = _make_df([300.0])          # 300 > 200 → should fire
        result = explainer.explain_series(df)
        assert result["exp_rule_threshold_fired"].iloc[0] == True
