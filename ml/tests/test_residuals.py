"""
TST-02: Unit tests for ml.src.models.residuals (TS-03).

Covers residual / z-score computation that bridges the time-series
baseline (TS-01/TS-02) into the ensemble (ENS-01) and the threshold
breach rule (RUL-01).

Targets:
  ResidualScorer.transform     – two calling styles + validation
  ResidualScorer.transform_with_baseline
  ResidualConfig               – defaults + ci_levels behavior
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ml.src.models.residuals import ResidualConfig, ResidualScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _df_actuals(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"total_cost": values})


def _df_forecast(
    means: list[float],
    stds: list[float],
    ci_lower_95: list[float] | None = None,
    ci_upper_95: list[float] | None = None,
) -> pd.DataFrame:
    df = pd.DataFrame({"forecast_mean": means, "forecast_std": stds})
    if ci_lower_95 is not None:
        df["ci_lower_95"] = ci_lower_95
    if ci_upper_95 is not None:
        df["ci_upper_95"] = ci_upper_95
    return df


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class TestOutputSchema:
    def test_all_core_columns_emitted(self) -> None:
        actuals = _df_actuals([100.0, 110.0, 120.0])
        forecast = _df_forecast([100.0] * 3, [10.0] * 3, [80.0] * 3, [120.0] * 3)
        out = ResidualScorer().transform(actuals, forecast)
        for col in ("residual", "abs_residual", "z_score", "abs_z_score", "is_outside_ci_95"):
            assert col in out.columns

    def test_output_columns_helper_matches(self) -> None:
        scorer = ResidualScorer()
        cols = scorer.output_columns()
        assert "residual" in cols
        assert "abs_residual" in cols
        assert "z_score" in cols
        assert "abs_z_score" in cols
        assert "is_outside_ci_95" in cols

    def test_no_ci_columns_when_disabled(self) -> None:
        scorer = ResidualScorer(ResidualConfig(ci_levels=[]))
        actuals = _df_actuals([100.0])
        forecast = _df_forecast([100.0], [10.0])
        out = scorer.transform(actuals, forecast)
        assert "is_outside_ci_95" not in out.columns
        assert scorer.output_columns() == ["residual", "abs_residual", "z_score", "abs_z_score"]

    def test_multiple_ci_levels_each_get_a_column(self) -> None:
        scorer = ResidualScorer(ResidualConfig(ci_levels=[90, 99]))
        actuals = _df_actuals([100.0])
        forecast = pd.DataFrame({
            "forecast_mean": [100.0],
            "forecast_std": [10.0],
            "ci_lower_90": [85.0],
            "ci_upper_90": [115.0],
            "ci_lower_99": [70.0],
            "ci_upper_99": [130.0],
        })
        out = scorer.transform(actuals, forecast)
        assert "is_outside_ci_90" in out.columns
        assert "is_outside_ci_99" in out.columns
        assert "is_outside_ci_95" not in out.columns


# ---------------------------------------------------------------------------
# Numerical correctness
# ---------------------------------------------------------------------------


class TestResidualMath:
    def test_residual_is_actual_minus_mean(self) -> None:
        actuals = _df_actuals([110.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["residual"].iloc[0] == 10.0

    def test_residual_signed_negative_when_under_forecast(self) -> None:
        actuals = _df_actuals([90.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["residual"].iloc[0] == -10.0

    def test_abs_residual_unsigned(self) -> None:
        actuals = _df_actuals([90.0, 110.0])
        forecast = _df_forecast([100.0] * 2, [5.0] * 2, [90.0] * 2, [110.0] * 2)
        out = ResidualScorer().transform(actuals, forecast)
        assert (out["abs_residual"] == 10.0).all()

    def test_z_score_dimensionless(self) -> None:
        actuals = _df_actuals([110.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        # (110 - 100) / 5 = 2
        assert math.isclose(out["z_score"].iloc[0], 2.0, rel_tol=1e-9)

    def test_z_score_clipped_at_configured_cap(self) -> None:
        # residual=1000, std=1 → raw z=1000; cap=10 → clipped to 10
        actuals = _df_actuals([1000.0])
        forecast = _df_forecast([0.0], [1.0], [-2.0], [2.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["z_score"].iloc[0] == 10.0
        assert out["abs_z_score"].iloc[0] == 10.0

    def test_z_score_unclipped_when_disabled(self) -> None:
        actuals = _df_actuals([1000.0])
        forecast = _df_forecast([0.0], [1.0], [-2.0], [2.0])
        out = ResidualScorer(ResidualConfig(clip_z_score=None)).transform(actuals, forecast)
        assert out["z_score"].iloc[0] == 1000.0

    def test_zero_std_handled_without_division_error(self) -> None:
        # forecast_std=0 must be floored to a tiny positive to avoid NaN/inf.
        actuals = _df_actuals([1.0])
        forecast = _df_forecast([1.0], [0.0], [0.5], [1.5])
        out = ResidualScorer().transform(actuals, forecast)
        assert math.isfinite(out["z_score"].iloc[0])
        assert out["z_score"].iloc[0] == 0.0  # residual=0 / floored_std

    def test_abs_z_score_matches_signed(self) -> None:
        actuals = _df_actuals([90.0, 110.0])
        forecast = _df_forecast([100.0] * 2, [5.0] * 2, [90.0] * 2, [110.0] * 2)
        out = ResidualScorer().transform(actuals, forecast)
        assert (out["abs_z_score"] == out["z_score"].abs()).all()


# ---------------------------------------------------------------------------
# CI breach flag
# ---------------------------------------------------------------------------


class TestCiBreachFlag:
    def test_inside_ci_yields_zero(self) -> None:
        actuals = _df_actuals([100.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["is_outside_ci_95"].iloc[0] == 0

    def test_above_ci_yields_one(self) -> None:
        actuals = _df_actuals([200.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["is_outside_ci_95"].iloc[0] == 1

    def test_below_ci_yields_one(self) -> None:
        actuals = _df_actuals([50.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["is_outside_ci_95"].iloc[0] == 1

    def test_at_ci_boundary_is_inside(self) -> None:
        # Boundary semantics: < lower OR > upper, so equal-to-boundary is INSIDE.
        actuals = _df_actuals([90.0, 110.0])
        forecast = _df_forecast([100.0] * 2, [5.0] * 2, [90.0] * 2, [110.0] * 2)
        out = ResidualScorer().transform(actuals, forecast)
        assert out["is_outside_ci_95"].tolist() == [0, 0]

    def test_dtype_is_int8(self) -> None:
        actuals = _df_actuals([200.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        assert out["is_outside_ci_95"].dtype == np.int8


# ---------------------------------------------------------------------------
# Calling styles
# ---------------------------------------------------------------------------


class TestCallingStyles:
    def test_pre_merged_dataframe_works(self) -> None:
        df = pd.DataFrame({
            "total_cost": [110.0],
            "forecast_mean": [100.0],
            "forecast_std": [5.0],
            "ci_lower_95": [90.0],
            "ci_upper_95": [110.0],
        })
        # Style 2: forecast columns already present, df_forecast=None
        out = ResidualScorer().transform(df)
        assert out["residual"].iloc[0] == 10.0

    def test_separate_dataframes_concatenated(self) -> None:
        actuals = _df_actuals([110.0])
        forecast = _df_forecast([100.0], [5.0], [90.0], [110.0])
        out = ResidualScorer().transform(actuals, forecast)
        # forecast columns are joined into the result
        assert "forecast_mean" in out.columns

    def test_overlapping_columns_keep_actuals(self) -> None:
        # If forecast carries a column also in actuals, actuals wins.
        actuals = pd.DataFrame({
            "total_cost": [110.0],
            "forecast_mean": [100.0],
            "forecast_std": [5.0],
            "ci_lower_95": [90.0],
            "ci_upper_95": [110.0],
        })
        forecast = _df_forecast([999.0], [99.0], [0.0], [1000.0])
        out = ResidualScorer().transform(actuals, forecast)
        # Forecast columns from actuals must win — residual reflects 100.0 not 999.0
        assert out["residual"].iloc[0] == 10.0

    def test_transform_with_baseline_invokes_predict(self) -> None:
        class _StubBaseline:
            def predict(self, df: pd.DataFrame) -> pd.DataFrame:
                n = len(df)
                return pd.DataFrame({
                    "forecast_mean": [100.0] * n,
                    "forecast_std": [5.0] * n,
                    "ci_lower_95": [90.0] * n,
                    "ci_upper_95": [110.0] * n,
                }, index=df.index)

        actuals = _df_actuals([110.0, 90.0])
        out = ResidualScorer().transform_with_baseline(_StubBaseline(), actuals)
        assert out["residual"].tolist() == [10.0, -10.0]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_target_col_raises(self) -> None:
        actuals = pd.DataFrame({"other_col": [1.0]})
        forecast = _df_forecast([1.0], [1.0], [0.0], [2.0])
        with pytest.raises(ValueError, match="missing required columns"):
            ResidualScorer().transform(actuals, forecast)

    def test_missing_forecast_mean_raises(self) -> None:
        actuals = _df_actuals([1.0])
        forecast = pd.DataFrame({
            "forecast_std": [1.0],
            "ci_lower_95": [0.0],
            "ci_upper_95": [2.0],
        })
        with pytest.raises(ValueError, match="missing required columns"):
            ResidualScorer().transform(actuals, forecast)

    def test_missing_ci_columns_raises(self) -> None:
        actuals = _df_actuals([1.0])
        forecast = _df_forecast([1.0], [1.0])  # no CI cols
        with pytest.raises(ValueError, match="ci_lower_95"):
            ResidualScorer().transform(actuals, forecast)

    def test_ci_disabled_does_not_validate_ci_cols(self) -> None:
        scorer = ResidualScorer(ResidualConfig(ci_levels=[]))
        actuals = _df_actuals([1.0])
        forecast = _df_forecast([1.0], [1.0])
        # Must not raise even though CI columns are absent.
        scorer.transform(actuals, forecast)
