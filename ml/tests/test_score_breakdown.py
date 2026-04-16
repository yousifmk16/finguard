"""
EXP-03: Unit tests for the score breakdown payload.

Covers:
  ComponentBreakdown  – fields, to_dict() NaN handling
  ScoreBreakdown      – fields, component(), active_components, to_dict()
  ScoreBreakdownConfig – defaults, from_scoring_config()
  _effective_weights  – NaN renormalisation mirrors OnlineScorer._fuse()
  ScoreBreakdownBuilder.build_row()
      – all-components active
      – TS component missing (NaN ts_signal) → weight redistributed
      – IF component missing
      – no components active → anomaly_score 0, is_anomaly False
      – is_anomaly derived when column absent
      – severity present / absent
      – forecast_explanation embedded when EXP-01 columns present
      – rule_explanation embedded when EXP-02 columns present
      – include_forecast_explanation=False suppresses sub-explanation
  ScoreBreakdownBuilder.build()
      – output column present, row count preserved, input not mutated
  ScoreBreakdownBuilder.from_scorer()
  Integration: EXP-01 + EXP-02 + EXP-03 on the same DataFrame
  to_dict() JSON safety (no NaN floats, no numpy types)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from ml.src.inference.score_breakdown import (
    ComponentBreakdown,
    ScoreBreakdown,
    ScoreBreakdownBuilder,
    ScoreBreakdownConfig,
    _effective_weights,
)
from ml.src.inference.explain import ExplanationGenerator, ExplanationConfig
from ml.src.inference.rule_explain import RuleExplainer, RuleExplainerConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)

_DEFAULT_CFG = ScoreBreakdownConfig(
    weight_ts=0.35,
    weight_if=0.40,
    weight_rules=0.25,
    anomaly_threshold=0.55,
)


def _make_row(
    ts_signal: float = 0.6,
    if_score: float = 0.7,
    rule_score: float = 0.5,
    anomaly_score: float = 0.62,
    is_anomaly: int = 1,
    severity: str = "medium",
    actual: float = 150.0,
    forecast_mean: float = 100.0,
    forecast_std: float = 10.0,
    include_forecast_cols: bool = False,
    include_rule_cols: bool = False,
) -> pd.Series:
    """Minimal scored row for build_row() tests."""
    data: dict = {
        "bucket": _START,
        "total_cost": actual,
        "ts_signal": ts_signal,
        "if_score": if_score,
        "rule_score": rule_score,
        "anomaly_score": anomaly_score,
        "is_anomaly": is_anomaly,
        "severity": severity,
        "forecast_mean": forecast_mean,
        "forecast_std": forecast_std,
        "residual": actual - forecast_mean,
        "z_score": (actual - forecast_mean) / forecast_std,
        "ci_lower_95": forecast_mean - 20,
        "ci_upper_95": forecast_mean + 20,
        "is_outside_ci_95": int(abs(actual - forecast_mean) > 20),
    }
    if include_forecast_cols:
        pct = (actual - forecast_mean) / abs(forecast_mean) * 100
        data["exp_direction"] = "above" if actual > forecast_mean else "below"
        data["exp_pct_deviation"] = pct
        data["exp_z_score"] = (actual - forecast_mean) / forecast_std
        data["exp_ci_breach"] = abs(actual - forecast_mean) > 20
        data["exp_summary"] = f"Actual total_cost ({actual:.2f}) is above the forecast."
    if include_rule_cols:
        data["exp_rule_threshold_fired"] = False
        data["exp_rule_threshold_score"] = 0.0
        data["exp_rule_threshold_reason"] = "Within budget."
        data["exp_rule_jump_fired"] = True
        data["exp_rule_jump_score"] = 0.8
        data["exp_rule_jump_reason"] = "Sudden jump of 100.0% detected."
        data["exp_rule_sustained_fired"] = False
        data["exp_rule_sustained_score"] = 0.0
        data["exp_rule_sustained_reason"] = "Not enough consecutive growth."
        data["exp_rule_triggered_rules"] = "sudden_jump"
        data["exp_rule_summary"] = "1 rule triggered: sudden_jump — Sudden jump."
    return pd.Series(data)


def _make_df(n: int = 5, **kwargs) -> pd.DataFrame:
    rows = [_make_row(**kwargs) for _ in range(n)]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _effective_weights helper
# ---------------------------------------------------------------------------


class TestEffectiveWeights:
    def test_all_active_sums_to_one(self):
        eff = _effective_weights([0.5, 0.6, 0.4], [0.35, 0.40, 0.25])
        assert abs(sum(eff) - 1.0) < 1e-9

    def test_proportional_to_configured_weights(self):
        eff = _effective_weights([0.5, 0.6, 0.4], [0.35, 0.40, 0.25])
        # Ratios should match the original weights
        assert abs(eff[0] / eff[1] - 0.35 / 0.40) < 1e-9

    def test_nan_component_excluded(self):
        # ts_signal is NaN → its weight redistributed to if and rules
        eff = _effective_weights([math.nan, 0.6, 0.4], [0.35, 0.40, 0.25])
        assert eff[0] == 0.0
        assert abs(sum(eff) - 1.0) < 1e-9
        # Remaining two weights should be proportional to 0.40 and 0.25
        assert abs(eff[1] / eff[2] - 0.40 / 0.25) < 1e-9

    def test_zero_weight_component_excluded(self):
        eff = _effective_weights([0.5, 0.6, 0.4], [0.0, 0.40, 0.25])
        assert eff[0] == 0.0
        assert abs(sum(eff) - 1.0) < 1e-9

    def test_all_nan_returns_zeros(self):
        eff = _effective_weights([math.nan, math.nan, math.nan], [0.35, 0.40, 0.25])
        assert eff == [0.0, 0.0, 0.0]

    def test_single_active_gets_full_weight(self):
        eff = _effective_weights([math.nan, 0.7, math.nan], [0.35, 0.40, 0.25])
        assert eff[1] == 1.0
        assert eff[0] == 0.0
        assert eff[2] == 0.0


# ---------------------------------------------------------------------------
# ComponentBreakdown
# ---------------------------------------------------------------------------


class TestComponentBreakdown:
    def _make(self, **kwargs) -> ComponentBreakdown:
        defaults = dict(
            name="ts_signal",
            label="Time-Series Signal",
            raw_score=0.6,
            configured_weight=0.35,
            effective_weight=0.35,
            weighted_contribution=0.21,
            active=True,
        )
        defaults.update(kwargs)
        return ComponentBreakdown(**defaults)

    def test_to_dict_keys(self):
        d = self._make().to_dict()
        for key in ["name", "label", "raw_score", "configured_weight",
                    "effective_weight", "weighted_contribution", "active"]:
            assert key in d

    def test_to_dict_nan_raw_score_is_none(self):
        d = self._make(raw_score=math.nan, active=False).to_dict()
        assert d["raw_score"] is None

    def test_to_dict_finite_raw_score_is_float(self):
        d = self._make(raw_score=0.6).to_dict()
        assert isinstance(d["raw_score"], float)

    def test_to_dict_values_rounded(self):
        d = self._make(raw_score=0.123456789).to_dict()
        assert d["raw_score"] == round(0.123456789, 6)


# ---------------------------------------------------------------------------
# ScoreBreakdown
# ---------------------------------------------------------------------------


class TestScoreBreakdown:
    def _make_bd(self) -> ScoreBreakdown:
        comps = [
            ComponentBreakdown("ts_signal", "TS", 0.6, 0.35, 0.35, 0.21, True),
            ComponentBreakdown("if_score", "IF", 0.7, 0.40, 0.40, 0.28, True),
            ComponentBreakdown("rule_score", "Rules", 0.5, 0.25, 0.25, 0.125, True),
        ]
        return ScoreBreakdown(
            components=comps,
            anomaly_score=0.615,
            anomaly_threshold=0.55,
            is_anomaly=True,
            severity="medium",
        )

    def test_component_by_name(self):
        bd = self._make_bd()
        c = bd.component("ts_signal")
        assert c is not None
        assert c.name == "ts_signal"

    def test_component_missing_returns_none(self):
        bd = self._make_bd()
        assert bd.component("nonexistent") is None

    def test_active_components(self):
        bd = self._make_bd()
        assert len(bd.active_components) == 3

    def test_active_components_excludes_inactive(self):
        bd = self._make_bd()
        bd.components[0] = ComponentBreakdown("ts_signal", "TS", math.nan, 0.35, 0.0, 0.0, False)
        assert len(bd.active_components) == 2

    def test_to_dict_structure(self):
        d = self._make_bd().to_dict()
        assert "anomaly_score" in d
        assert "components" in d
        assert isinstance(d["components"], list)
        assert len(d["components"]) == 3

    def test_to_dict_no_sub_explanations_by_default(self):
        d = self._make_bd().to_dict()
        assert "forecast_explanation" not in d
        assert "rule_explanation" not in d

    def test_to_dict_json_serialisable(self):
        d = self._make_bd().to_dict()
        # Should not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# ScoreBreakdownConfig
# ---------------------------------------------------------------------------


class TestScoreBreakdownConfig:
    def test_defaults(self):
        cfg = ScoreBreakdownConfig()
        assert cfg.weight_ts == 0.35
        assert cfg.weight_if == 0.40
        assert cfg.weight_rules == 0.25
        assert cfg.anomaly_threshold == 0.55
        assert cfg.output_col == "exp_breakdown"

    def test_from_scoring_config(self):
        mock_sc = MagicMock()
        mock_sc.weight_ts = 0.3
        mock_sc.weight_if = 0.5
        mock_sc.weight_rules = 0.2
        mock_sc.anomaly_threshold = 0.6
        mock_sc.enable_ts = True
        mock_sc.enable_if = True
        mock_sc.enable_rules = False

        cfg = ScoreBreakdownConfig.from_scoring_config(mock_sc)
        assert cfg.weight_ts == 0.3
        assert cfg.weight_if == 0.5
        assert cfg.anomaly_threshold == 0.6
        assert cfg.enable_rules == False


# ---------------------------------------------------------------------------
# ScoreBreakdownBuilder.build_row()
# ---------------------------------------------------------------------------


class TestBuildRow:
    def test_three_components_present(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row())
        assert len(bd.components) == 3

    def test_component_names(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row())
        names = [c.name for c in bd.components]
        assert names == ["ts_signal", "if_score", "rule_score"]

    def test_component_labels(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row())
        assert bd.components[0].label == "Time-Series Signal"
        assert bd.components[1].label == "Isolation Forest"
        assert bd.components[2].label == "Rule Engine"

    def test_anomaly_score_read_from_row(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row(anomaly_score=0.72))
        assert math.isclose(bd.anomaly_score, 0.72)

    def test_is_anomaly_true(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row(is_anomaly=1))
        assert bd.is_anomaly is True

    def test_is_anomaly_false(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row(is_anomaly=0, anomaly_score=0.3))
        assert bd.is_anomaly is False

    def test_is_anomaly_derived_when_col_absent(self):
        row = _make_row(anomaly_score=0.72, is_anomaly=1)
        row = row.drop("is_anomaly")
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.is_anomaly is True

    def test_severity_read(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row(severity="high"))
        assert bd.severity == "high"

    def test_severity_none_when_absent(self):
        row = _make_row()
        row = row.drop("severity")
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.severity is None

    def test_threshold_from_config(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(_make_row())
        assert math.isclose(bd.anomaly_threshold, 0.55)

    # ------------------------------------------------------------------
    # NaN renormalisation
    # ------------------------------------------------------------------

    def test_nan_ts_signal_active_false(self):
        row = _make_row(ts_signal=float("nan"))
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        ts = bd.component("ts_signal")
        assert ts.active is False

    def test_nan_ts_signal_weight_redistributed(self):
        row = _make_row(ts_signal=float("nan"))
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        eff_weights = [c.effective_weight for c in bd.components]
        assert eff_weights[0] == 0.0                    # ts disabled
        assert abs(sum(eff_weights) - 1.0) < 1e-9      # remaining sum to 1

    def test_nan_ts_remaining_ratio_preserved(self):
        row = _make_row(ts_signal=float("nan"))
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        w_if = bd.component("if_score").effective_weight
        w_rules = bd.component("rule_score").effective_weight
        assert abs(w_if / w_rules - 0.40 / 0.25) < 1e-9

    def test_all_nan_components_is_anomaly_false(self):
        row = _make_row(
            ts_signal=float("nan"),
            if_score=float("nan"),
            rule_score=0.0,
            anomaly_score=0.0,
            is_anomaly=0,
        )
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.is_anomaly is False

    def test_weighted_contribution_correct(self):
        # All three active; check ts contribution = eff_weight_ts * ts_raw
        row = _make_row(ts_signal=0.6, if_score=0.7, rule_score=0.5)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        ts = bd.component("ts_signal")
        expected = ts.effective_weight * 0.6
        assert math.isclose(ts.weighted_contribution, expected, rel_tol=1e-9)

    # ------------------------------------------------------------------
    # Optional sub-explanations
    # ------------------------------------------------------------------

    def test_forecast_explanation_embedded_when_exp01_cols_present(self):
        row = _make_row(include_forecast_cols=True)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.forecast_explanation is not None
        assert bd.forecast_explanation.direction in ("above", "below", "within")

    def test_forecast_explanation_none_when_cols_absent(self):
        row = _make_row(include_forecast_cols=False)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.forecast_explanation is None

    def test_forecast_explanation_suppressed_by_config(self):
        cfg = ScoreBreakdownConfig(include_forecast_explanation=False)
        row = _make_row(include_forecast_cols=True)
        builder = ScoreBreakdownBuilder(cfg)
        bd = builder.build_row(row)
        assert bd.forecast_explanation is None

    def test_rule_explanation_embedded_when_exp02_cols_present(self):
        row = _make_row(include_rule_cols=True)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.rule_explanation is not None
        assert bd.rule_explanation.jump_result.fired is True

    def test_rule_explanation_none_when_cols_absent(self):
        row = _make_row(include_rule_cols=False)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        bd = builder.build_row(row)
        assert bd.rule_explanation is None

    def test_rule_explanation_suppressed_by_config(self):
        cfg = ScoreBreakdownConfig(include_rule_explanation=False)
        row = _make_row(include_rule_cols=True)
        builder = ScoreBreakdownBuilder(cfg)
        bd = builder.build_row(row)
        assert bd.rule_explanation is None

    # ------------------------------------------------------------------
    # to_dict completeness
    # ------------------------------------------------------------------

    def test_to_dict_includes_forecast_when_present(self):
        row = _make_row(include_forecast_cols=True)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        d = builder.build_row(row).to_dict()
        assert "forecast_explanation" in d
        fe = d["forecast_explanation"]
        assert "actual" in fe
        assert "direction" in fe
        assert "summary" in fe

    def test_to_dict_includes_rule_when_present(self):
        row = _make_row(include_rule_cols=True)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        d = builder.build_row(row).to_dict()
        assert "rule_explanation" in d
        re = d["rule_explanation"]
        assert "sudden_jump" in re
        assert re["sudden_jump"]["fired"] is True

    def test_to_dict_json_safe_no_nan(self):
        row = _make_row(ts_signal=float("nan"))
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        d = builder.build_row(row).to_dict()
        # Should not raise — all NaN values must be None
        json_str = json.dumps(d)
        assert "NaN" not in json_str

    def test_to_dict_no_numpy_types(self):
        row = _make_row()
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        d = builder.build_row(row).to_dict()
        # Recursively check for numpy scalars
        def _check(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    _check(v)
            elif isinstance(obj, list):
                for v in obj:
                    _check(v)
            else:
                assert not isinstance(obj, (np.integer, np.floating, np.bool_)), (
                    f"Numpy type found in payload: {type(obj)}"
                )
        _check(d)


# ---------------------------------------------------------------------------
# ScoreBreakdownBuilder.build() — DataFrame transform
# ---------------------------------------------------------------------------


class TestBuildDataFrame:
    def test_output_column_added(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        df = _make_df(n=3)
        result = builder.build(df)
        assert "exp_breakdown" in result.columns

    def test_row_count_unchanged(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        df = _make_df(n=7)
        assert len(builder.build(df)) == 7

    def test_original_columns_preserved(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        df = _make_df(n=3)
        result = builder.build(df)
        for col in df.columns:
            assert col in result.columns

    def test_input_not_mutated(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        df = _make_df(n=3)
        original_cols = list(df.columns)
        builder.build(df)
        assert list(df.columns) == original_cols

    def test_each_cell_is_score_breakdown(self):
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        df = _make_df(n=4)
        result = builder.build(df)
        for bd in result["exp_breakdown"]:
            assert isinstance(bd, ScoreBreakdown)

    def test_custom_output_col(self):
        cfg = ScoreBreakdownConfig(output_col="breakdown")
        builder = ScoreBreakdownBuilder(cfg)
        df = _make_df(n=2)
        result = builder.build(df)
        assert "breakdown" in result.columns
        assert "exp_breakdown" not in result.columns


# ---------------------------------------------------------------------------
# ScoreBreakdownBuilder.from_scorer()
# ---------------------------------------------------------------------------


class TestFromScorer:
    def test_weights_copied(self):
        mock_sc = MagicMock()
        mock_sc.weight_ts = 0.3
        mock_sc.weight_if = 0.5
        mock_sc.weight_rules = 0.2
        mock_sc.anomaly_threshold = 0.6
        mock_sc.enable_ts = True
        mock_sc.enable_if = True
        mock_sc.enable_rules = True

        mock_scorer = MagicMock()
        mock_scorer.config = mock_sc

        builder = ScoreBreakdownBuilder.from_scorer(mock_scorer)
        assert math.isclose(builder.config.weight_ts, 0.3)
        assert math.isclose(builder.config.weight_if, 0.5)
        assert math.isclose(builder.config.anomaly_threshold, 0.6)

    def test_builds_valid_breakdown(self):
        mock_sc = MagicMock()
        mock_sc.weight_ts = 0.35
        mock_sc.weight_if = 0.40
        mock_sc.weight_rules = 0.25
        mock_sc.anomaly_threshold = 0.55
        mock_sc.enable_ts = True
        mock_sc.enable_if = True
        mock_sc.enable_rules = True

        mock_scorer = MagicMock()
        mock_scorer.config = mock_sc

        builder = ScoreBreakdownBuilder.from_scorer(mock_scorer)
        bd = builder.build_row(_make_row())
        assert isinstance(bd, ScoreBreakdown)


# ---------------------------------------------------------------------------
# Integration: EXP-01 + EXP-02 + EXP-03 on the same DataFrame
# ---------------------------------------------------------------------------


class TestIntegration:
    def _build_full_df(self, n: int = 5) -> pd.DataFrame:
        """Run ExplanationGenerator and RuleExplainer before the builder."""
        from datetime import datetime, timezone, timedelta

        costs = [150.0 + i for i in range(n)]
        rows = []
        for i, c in enumerate(costs):
            rows.append({
                "bucket": pd.Timestamp(_START + timedelta(minutes=i)),
                "account_id": "acct-1",
                "service": "compute",
                "region": "us-east1",
                "total_cost": c,
                "forecast_mean": 100.0,
                "forecast_std": 10.0,
                "residual": c - 100.0,
                "z_score": (c - 100.0) / 10.0,
                "abs_z_score": abs(c - 100.0) / 10.0,
                "ci_lower_95": 80.0,
                "ci_upper_95": 120.0,
                "is_outside_ci_95": int(abs(c - 100.0) > 20),
                "ts_signal": min(abs(c - 100.0) / 100.0, 1.0),
                "if_score": 0.65,
                "if_anomaly": 1,
                "rule_score": 0.4,
                "anomaly_score": 0.62,
                "is_anomaly": 1,
                "severity": "medium",
            })
        df = pd.DataFrame(rows)

        # EXP-01
        exp_cfg = ExplanationConfig()
        df = ExplanationGenerator(exp_cfg).explain(df)

        # EXP-02
        rule_cfg = RuleExplainerConfig(budget_limit=1000.0, jump_pct=0.5)
        df = RuleExplainer(rule_cfg).explain_series(df)

        return df

    def test_breakdown_column_present(self):
        df = self._build_full_df()
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        result = builder.build(df)
        assert "exp_breakdown" in result.columns

    def test_forecast_explanation_populated(self):
        df = self._build_full_df()
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        result = builder.build(df)
        bd: ScoreBreakdown = result["exp_breakdown"].iloc[0]
        assert bd.forecast_explanation is not None
        assert bd.forecast_explanation.direction == "above"

    def test_rule_explanation_populated(self):
        df = self._build_full_df()
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        result = builder.build(df)
        bd: ScoreBreakdown = result["exp_breakdown"].iloc[0]
        assert bd.rule_explanation is not None

    def test_to_dict_fully_populated_json_safe(self):
        df = self._build_full_df()
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        result = builder.build(df)
        bd: ScoreBreakdown = result["exp_breakdown"].iloc[0]
        d = bd.to_dict()
        json_str = json.dumps(d)
        assert "forecast_explanation" in d
        assert "rule_explanation" in d
        assert "NaN" not in json_str

    def test_all_rows_have_three_components(self):
        df = self._build_full_df(n=5)
        builder = ScoreBreakdownBuilder(_DEFAULT_CFG)
        result = builder.build(df)
        for bd in result["exp_breakdown"]:
            assert len(bd.components) == 3
