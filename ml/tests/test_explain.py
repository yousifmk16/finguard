"""
EXP-01: Unit tests for the forecast-vs-actual explanation generator.

Covers:
  ForecastExplanation  – dataclass fields and summary text
  ExplanationConfig    – defaults and custom column names
  ExplanationGenerator – explain_row() field correctness
  ExplanationGenerator – explain() DataFrame column output
  Edge cases           – zero forecast mean, missing forecast cols, NaN z-score
  CI breach detection  – via is_outside_ci_N flag and via raw ci_lower/ci_upper
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.src.inference.explain import (
    ExplanationConfig,
    ExplanationGenerator,
    ForecastExplanation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    actual: float = 150.0,
    forecast_mean: float = 100.0,
    forecast_std: float = 10.0,
    residual: float | None = None,
    z_score: float | None = None,
    ci_lower_95: float | None = None,
    ci_upper_95: float | None = None,
    is_outside_ci_95: int | None = None,
) -> pd.Series:
    """Build a minimal scored Series (one row) for explain_row()."""
    data: dict = {
        "bucket": datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        "total_cost": actual,
        "forecast_mean": forecast_mean,
        "forecast_std": forecast_std,
        "anomaly_score": 0.72,
        "is_anomaly": 1,
    }
    if residual is not None:
        data["residual"] = residual
    else:
        data["residual"] = actual - forecast_mean

    if z_score is not None:
        data["z_score"] = z_score
    else:
        data["z_score"] = data["residual"] / forecast_std if forecast_std != 0 else math.nan

    if ci_lower_95 is not None:
        data["ci_lower_95"] = ci_lower_95
    if ci_upper_95 is not None:
        data["ci_upper_95"] = ci_upper_95
    if is_outside_ci_95 is not None:
        data["is_outside_ci_95"] = is_outside_ci_95

    return pd.Series(data)


def _make_df(n: int = 5, actual: float = 150.0, forecast_mean: float = 100.0) -> pd.DataFrame:
    """Multi-row DataFrame with forecast + residual columns pre-filled."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "bucket": datetime(2026, 1, 5, 9, i, tzinfo=timezone.utc),
                "total_cost": actual + i,
                "forecast_mean": forecast_mean,
                "forecast_std": 10.0,
                "residual": (actual + i) - forecast_mean,
                "z_score": ((actual + i) - forecast_mean) / 10.0,
                "ci_lower_95": forecast_mean - 20.0,
                "ci_upper_95": forecast_mean + 20.0,
                "is_outside_ci_95": int(abs((actual + i) - forecast_mean) > 20.0),
                "anomaly_score": 0.72,
                "is_anomaly": 1,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# ForecastExplanation dataclass
# ---------------------------------------------------------------------------


class TestForecastExplanation:
    def test_fields_populated(self):
        exp = ForecastExplanation(
            actual=150.0,
            forecast_mean=100.0,
            forecast_std=10.0,
            residual=50.0,
            pct_deviation=50.0,
            z_score=5.0,
            direction="above",
            ci_breaches={95: True},
            summary="Actual is 50.0% above the forecast.",
        )
        assert exp.actual == 150.0
        assert exp.residual == 50.0
        assert exp.direction == "above"
        assert exp.ci_breaches[95] is True

    def test_default_ci_breaches_empty(self):
        exp = ForecastExplanation(
            actual=100.0,
            forecast_mean=100.0,
            forecast_std=5.0,
            residual=0.0,
            pct_deviation=0.0,
            z_score=0.0,
            direction="within",
        )
        assert exp.ci_breaches == {}
        assert exp.summary == ""


# ---------------------------------------------------------------------------
# ExplanationConfig
# ---------------------------------------------------------------------------


class TestExplanationConfig:
    def test_defaults(self):
        cfg = ExplanationConfig()
        assert cfg.target_col == "total_cost"
        assert cfg.forecast_mean_col == "forecast_mean"
        assert cfg.ci_levels == [95]
        assert cfg.output_prefix == "exp_"

    def test_custom_values(self):
        cfg = ExplanationConfig(target_col="spend", ci_levels=[90, 99], output_prefix="x_")
        assert cfg.target_col == "spend"
        assert cfg.ci_levels == [90, 99]
        assert cfg.output_prefix == "x_"


# ---------------------------------------------------------------------------
# ExplanationGenerator.explain_row()
# ---------------------------------------------------------------------------


class TestExplainRow:
    def setup_method(self):
        self.gen = ExplanationGenerator()

    def test_direction_above(self):
        exp = self.gen.explain_row(_make_row(actual=150.0, forecast_mean=100.0))
        assert exp.direction == "above"

    def test_direction_below(self):
        exp = self.gen.explain_row(_make_row(actual=80.0, forecast_mean=100.0))
        assert exp.direction == "below"

    def test_direction_within(self):
        exp = self.gen.explain_row(_make_row(actual=100.0, forecast_mean=100.0))
        assert exp.direction == "within"

    def test_residual_computed_correctly(self):
        row = _make_row(actual=160.0, forecast_mean=100.0)
        exp = self.gen.explain_row(row)
        assert math.isclose(exp.residual, 60.0)

    def test_pct_deviation_above(self):
        exp = self.gen.explain_row(_make_row(actual=150.0, forecast_mean=100.0))
        assert math.isclose(exp.pct_deviation, 50.0)

    def test_pct_deviation_below(self):
        exp = self.gen.explain_row(_make_row(actual=70.0, forecast_mean=100.0))
        assert math.isclose(exp.pct_deviation, -30.0)

    def test_z_score_uses_precomputed_column(self):
        row = _make_row(actual=150.0, forecast_mean=100.0, forecast_std=10.0, z_score=99.0)
        exp = self.gen.explain_row(row)
        # should use the pre-computed value from the column, not recompute
        assert math.isclose(exp.z_score, 99.0)

    def test_z_score_fallback_computed(self):
        # No z_score column — generator should compute residual / std
        data = _make_row(actual=120.0, forecast_mean=100.0, forecast_std=10.0)
        data = data.drop("z_score")
        exp = self.gen.explain_row(data)
        assert math.isclose(exp.z_score, 2.0)

    def test_ci_breach_via_flag_column(self):
        row = _make_row(
            actual=130.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
            is_outside_ci_95=1,
        )
        exp = self.gen.explain_row(row)
        assert exp.ci_breaches[95] is True

    def test_ci_no_breach_via_flag_column(self):
        row = _make_row(
            actual=110.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
            is_outside_ci_95=0,
        )
        exp = self.gen.explain_row(row)
        assert exp.ci_breaches[95] is False

    def test_ci_breach_falls_back_to_bounds(self):
        # Provide ci_lower/ci_upper but NOT is_outside_ci_95
        row = _make_row(
            actual=130.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
        )
        # Drop the flag column so the generator must use bounds
        row = row.drop("is_outside_ci_95", errors="ignore")
        exp = self.gen.explain_row(row)
        assert exp.ci_breaches[95] is True

    def test_ci_no_breach_falls_back_to_bounds(self):
        row = _make_row(
            actual=110.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
        )
        row = row.drop("is_outside_ci_95", errors="ignore")
        exp = self.gen.explain_row(row)
        assert exp.ci_breaches[95] is False

    def test_no_ci_columns_returns_empty_breaches(self):
        row = _make_row(actual=150.0, forecast_mean=100.0)
        row = row.drop([c for c in row.index if c.startswith("ci_") or c.startswith("is_outside")], errors="ignore")
        exp = self.gen.explain_row(row)
        assert exp.ci_breaches == {}

    # ------------------------------------------------------------------
    # Summary text
    # ------------------------------------------------------------------

    def test_summary_contains_actual(self):
        exp = self.gen.explain_row(_make_row(actual=152.3, forecast_mean=100.0))
        assert "152.30" in exp.summary

    def test_summary_contains_forecast(self):
        exp = self.gen.explain_row(_make_row(actual=152.3, forecast_mean=100.0))
        assert "100.00" in exp.summary

    def test_summary_contains_direction_above(self):
        exp = self.gen.explain_row(_make_row(actual=152.3, forecast_mean=100.0))
        assert "above" in exp.summary

    def test_summary_contains_direction_below(self):
        exp = self.gen.explain_row(_make_row(actual=70.0, forecast_mean=100.0))
        assert "below" in exp.summary

    def test_summary_contains_ci_breach(self):
        row = _make_row(
            actual=150.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
            is_outside_ci_95=1,
        )
        exp = self.gen.explain_row(row)
        assert "95%" in exp.summary or "confidence" in exp.summary

    def test_summary_no_ci_mention_when_no_breach(self):
        row = _make_row(
            actual=110.0, forecast_mean=100.0,
            ci_lower_95=80.0, ci_upper_95=120.0,
            is_outside_ci_95=0,
        )
        exp = self.gen.explain_row(row)
        assert "confidence interval" not in exp.summary

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_zero_forecast_mean_pct_deviation_nan(self):
        row = _make_row(actual=50.0, forecast_mean=0.0, forecast_std=5.0)
        exp = self.gen.explain_row(row)
        assert math.isnan(exp.pct_deviation)

    def test_missing_forecast_cols_returns_nan_summary(self):
        row = pd.Series({"total_cost": 100.0, "anomaly_score": 0.8, "is_anomaly": 1})
        exp = self.gen.explain_row(row)
        assert math.isnan(exp.forecast_mean)
        assert "unavailable" in exp.summary.lower()

    def test_actual_equals_forecast_direction_within(self):
        exp = self.gen.explain_row(_make_row(actual=100.0, forecast_mean=100.0))
        assert exp.direction == "within"
        assert math.isclose(exp.residual, 0.0)
        assert math.isclose(exp.pct_deviation, 0.0)


# ---------------------------------------------------------------------------
# ExplanationGenerator.explain()
# ---------------------------------------------------------------------------


class TestExplainDataFrame:
    def setup_method(self):
        self.gen = ExplanationGenerator()

    def test_output_columns_present(self):
        df = _make_df(n=3)
        result = self.gen.explain(df)
        for col in ["exp_direction", "exp_pct_deviation", "exp_z_score", "exp_ci_breach", "exp_summary"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_original_columns_preserved(self):
        df = _make_df(n=3)
        result = self.gen.explain(df)
        for col in df.columns:
            assert col in result.columns

    def test_input_not_mutated(self):
        df = _make_df(n=3)
        original_cols = list(df.columns)
        _ = self.gen.explain(df)
        assert list(df.columns) == original_cols

    def test_row_count_unchanged(self):
        df = _make_df(n=7)
        result = self.gen.explain(df)
        assert len(result) == 7

    def test_direction_column_values(self):
        df = _make_df(n=5, actual=150.0, forecast_mean=100.0)
        result = self.gen.explain(df)
        assert all(d == "above" for d in result["exp_direction"])

    def test_ci_breach_boolean(self):
        df = _make_df(n=3, actual=150.0, forecast_mean=100.0)
        # actual=150 > ci_upper=120 → breach expected
        result = self.gen.explain(df)
        assert all(result["exp_ci_breach"])

    def test_no_ci_breach(self):
        df = _make_df(n=3, actual=105.0, forecast_mean=100.0)
        # actual=105 is within [80, 120]
        result = self.gen.explain(df)
        assert not any(result["exp_ci_breach"])

    def test_custom_prefix(self):
        gen = ExplanationGenerator(ExplanationConfig(output_prefix="x_"))
        df = _make_df(n=2)
        result = gen.explain(df)
        assert "x_direction" in result.columns
        assert "exp_direction" not in result.columns

    def test_pct_deviation_correct(self):
        df = _make_df(n=1, actual=150.0, forecast_mean=100.0)
        result = self.gen.explain(df)
        assert math.isclose(result["exp_pct_deviation"].iloc[0], 50.0)

    def test_z_score_column_correct(self):
        df = _make_df(n=1, actual=120.0, forecast_mean=100.0)
        # residual=20, std=10 → z=2.0
        result = self.gen.explain(df)
        assert math.isclose(result["exp_z_score"].iloc[0], 2.0)

    def test_summary_is_string(self):
        df = _make_df(n=4)
        result = self.gen.explain(df)
        assert all(isinstance(s, str) for s in result["exp_summary"])
        assert all(len(s) > 0 for s in result["exp_summary"])
