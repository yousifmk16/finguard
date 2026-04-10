"""
FEA-05: Unit tests for the feature engineering pipeline.

Covers:
  FEA-01  RollingWindowExtractor
  FEA-02  GrowthRateFeatures
  FEA-03  VolatilityFeatures
  FEA-04  TimeContextFeatures
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.src.features.extractor import RollingWindowExtractor, WindowConfig
from ml.src.features.growth_rate import GrowthRateFeatures, GrowthRateConfig
from ml.src.features.volatility import VolatilityFeatures, VolatilityConfig
from ml.src.features.time_context import TimeContextFeatures, TimeContextConfig


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_df(
    n: int = 30,
    cost_values: list[float] | None = None,
    account_id: str = "acct-001",
    service: str = "compute",
    region: str = "us-central1",
    start: datetime | None = None,
) -> pd.DataFrame:
    """Build a minimal 1-minute aggregate DataFrame for testing."""
    if start is None:
        start = datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc)  # Monday 09:00

    buckets = [start + timedelta(minutes=i) for i in range(n)]
    costs = cost_values if cost_values is not None else [100.0 + i for i in range(n)]

    return pd.DataFrame(
        {
            "bucket": pd.to_datetime(buckets, utc=True),
            "account_id": account_id,
            "service": service,
            "region": region,
            "total_cost": costs,
            "total_usage": [10.0] * n,
            "event_count": [5] * n,
        }
    )


def _make_multi_df() -> pd.DataFrame:
    """Two series (different services) interleaved into one DataFrame."""
    df_a = _make_df(n=20, service="compute")
    df_b = _make_df(n=20, service="storage", cost_values=[50.0] * 20)
    return pd.concat([df_a, df_b], ignore_index=True)


# ===========================================================================
# FEA-01: RollingWindowExtractor
# ===========================================================================

class TestRollingWindowExtractor:

    def test_output_contains_all_expected_columns(self) -> None:
        cfg = WindowConfig(windows=[5, 15], agg_funcs=["mean", "std"])
        extractor = RollingWindowExtractor(cfg)
        df = extractor.transform(_make_df())

        for w in [5, 15]:
            for agg in ["mean", "std"]:
                assert f"total_cost_roll{w}_{agg}" in df.columns
            assert f"total_cost_roll{w}_zscore" in df.columns

    def test_original_columns_are_preserved(self) -> None:
        df_in = _make_df()
        df_out = RollingWindowExtractor().transform(df_in)
        for col in df_in.columns:
            assert col in df_out.columns

    def test_rolling_mean_correctness(self) -> None:
        costs = [10.0, 20.0, 30.0, 40.0, 50.0] + [50.0] * 25
        df = RollingWindowExtractor(WindowConfig(windows=[5])).transform(_make_df(cost_values=costs))
        # Row index 4 (0-based): mean of [10,20,30,40,50] = 30
        assert math.isclose(df["total_cost_roll5_mean"].iloc[4], 30.0, rel_tol=1e-6)

    def test_zscore_is_nan_for_constant_series(self) -> None:
        df = RollingWindowExtractor(WindowConfig(windows=[5])).transform(
            _make_df(cost_values=[100.0] * 30)
        )
        # std == 0 → division by zero → zscore must be NaN for every row
        assert df["total_cost_roll5_zscore"].isna().all()

    def test_zscore_positive_for_spike(self) -> None:
        costs = [100.0] * 10 + [1000.0] + [100.0] * 19
        df = RollingWindowExtractor(WindowConfig(windows=[5])).transform(
            _make_df(cost_values=costs)
        )
        spike_idx = 10
        assert df["total_cost_roll5_zscore"].iloc[spike_idx] > 0

    def test_transform_group_isolates_series(self) -> None:
        df_multi = _make_multi_df()
        extractor = RollingWindowExtractor(WindowConfig(windows=[5]))
        result = extractor.transform_group(df_multi)

        # Both groups should be present and have the same number of rows
        assert len(result) == len(df_multi)
        for service in ["compute", "storage"]:
            assert service in result["service"].values

    def test_missing_target_col_raises(self) -> None:
        df = _make_df().drop(columns=["total_cost"])
        with pytest.raises(ValueError, match="missing columns"):
            RollingWindowExtractor().transform(df)

    def test_empty_dataframe_raises(self) -> None:
        df = _make_df().iloc[0:0]
        with pytest.raises(ValueError, match="empty"):
            RollingWindowExtractor().transform(df)

    def test_unsupported_agg_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            RollingWindowExtractor(WindowConfig(agg_funcs=["median"]))

    def test_feature_columns_list_matches_output(self) -> None:
        cfg = WindowConfig(windows=[5, 15], agg_funcs=["mean", "max"])
        extractor = RollingWindowExtractor(cfg)
        df = extractor.transform(_make_df())
        for col in extractor.feature_columns():
            assert col in df.columns

    def test_window_values_length(self) -> None:
        df = _make_df(n=20)
        extractor = RollingWindowExtractor()
        vals = extractor.window_values(df, window=5)
        assert len(vals) == 5


# ===========================================================================
# FEA-02: GrowthRateFeatures
# ===========================================================================

class TestGrowthRateFeatures:

    def _base_df(self, costs: list[float] | None = None) -> pd.DataFrame:
        df = RollingWindowExtractor().transform(_make_df(cost_values=costs))
        return df

    def test_pct_change_columns_present(self) -> None:
        df = GrowthRateFeatures().transform(self._base_df())
        for lag in [1, 5, 15]:
            assert f"total_cost_pct_change_{lag}" in df.columns

    def test_log_return_columns_present(self) -> None:
        df = GrowthRateFeatures().transform(self._base_df())
        for lag in [1, 5, 15]:
            assert f"total_cost_log_return_{lag}" in df.columns

    def test_cagr_columns_present(self) -> None:
        df = GrowthRateFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_cagr_{w}" in df.columns

    def test_accel_column_present(self) -> None:
        df = GrowthRateFeatures().transform(self._base_df())
        assert "total_cost_accel" in df.columns

    def test_pct_change_correctness(self) -> None:
        costs = [100.0, 150.0] + [150.0] * 28
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(
            self._base_df(costs)
        )
        # Row 1: (150 - 100) / 100 = 0.5
        assert math.isclose(df["total_cost_pct_change_1"].iloc[1], 0.5, rel_tol=1e-6)

    def test_pct_change_clipped_at_5(self) -> None:
        costs = [1.0, 1000.0] + [1000.0] * 28   # 99 900 % increase → should clip at 5.0
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(
            self._base_df(costs)
        )
        assert df["total_cost_pct_change_1"].max() <= 5.0

    def test_log_return_is_zero_for_flat_series(self) -> None:
        costs = [100.0] * 30
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(
            self._base_df(costs)
        )
        assert (df["total_cost_log_return_1"].dropna() == 0.0).all()

    def test_log_return_positive_for_increase(self) -> None:
        costs = [100.0, 200.0] + [200.0] * 28
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(
            self._base_df(costs)
        )
        assert df["total_cost_log_return_1"].iloc[1] > 0

    def test_accel_zero_for_constant_growth(self) -> None:
        # Constant 10 % growth each step → pct_change_1 constant → accel ≈ 0
        costs = [100.0 * (1.1 ** i) for i in range(30)]
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(
            self._base_df(costs)
        )
        # Skip first two rows (NaN from diff / shift)
        accel = df["total_cost_accel"].dropna()
        assert (accel.abs() < 1e-6).all()

    def test_missing_target_col_raises(self) -> None:
        df = _make_df().drop(columns=["total_cost"])
        with pytest.raises(ValueError, match="target_col"):
            GrowthRateFeatures().transform(df)

    def test_feature_columns_list_matches_output(self) -> None:
        grf = GrowthRateFeatures()
        df = grf.transform(self._base_df())
        for col in grf.feature_columns():
            assert col in df.columns


# ===========================================================================
# FEA-03: VolatilityFeatures
# ===========================================================================

class TestVolatilityFeatures:

    def _base_df(self, costs: list[float] | None = None) -> pd.DataFrame:
        df = RollingWindowExtractor().transform(_make_df(cost_values=costs))
        df = GrowthRateFeatures().transform(df)
        return df

    def test_cv_columns_present(self) -> None:
        df = VolatilityFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_cv_{w}" in df.columns

    def test_range_columns_present(self) -> None:
        df = VolatilityFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_range_{w}" in df.columns

    def test_iqr_columns_present(self) -> None:
        df = VolatilityFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_iqr_{w}" in df.columns

    def test_bb_width_columns_present(self) -> None:
        df = VolatilityFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_bb_width_{w}" in df.columns

    def test_hist_vol_columns_present(self) -> None:
        df = VolatilityFeatures().transform(self._base_df())
        for w in [5, 15, 60]:
            assert f"total_cost_hist_vol_{w}" in df.columns

    def test_cv_zero_for_constant_series(self) -> None:
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(
            self._base_df([100.0] * 30)
        )
        # std = 0, cv = 0 / mean = 0
        assert (df["total_cost_cv_5"].dropna() == 0.0).all()

    def test_range_zero_for_constant_series(self) -> None:
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(
            self._base_df([100.0] * 30)
        )
        assert (df["total_cost_range_5"].dropna() == 0.0).all()

    def test_range_non_negative(self) -> None:
        costs = [abs(math.sin(i) * 200) + 50 for i in range(30)]
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(
            self._base_df(costs)
        )
        assert (df["total_cost_range_5"].dropna() >= 0).all()

    def test_iqr_non_negative(self) -> None:
        costs = [abs(math.sin(i) * 200) + 50 for i in range(30)]
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(
            self._base_df(costs)
        )
        assert (df["total_cost_iqr_5"].dropna() >= 0).all()

    def test_hist_vol_non_negative(self) -> None:
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(
            self._base_df()
        )
        assert (df["total_cost_hist_vol_5"].dropna() >= 0).all()

    def test_feature_columns_list_matches_output(self) -> None:
        vf = VolatilityFeatures()
        df = vf.transform(self._base_df())
        for col in vf.feature_columns():
            assert col in df.columns

    def test_missing_target_col_raises(self) -> None:
        df = _make_df().drop(columns=["total_cost"])
        with pytest.raises(ValueError, match="target_col"):
            VolatilityFeatures().transform(df)


# ===========================================================================
# FEA-04: TimeContextFeatures
# ===========================================================================

class TestTimeContextFeatures:

    def _base_df(self, start: datetime | None = None) -> pd.DataFrame:
        return _make_df(n=30, start=start)

    def test_calendar_columns_present(self) -> None:
        df = TimeContextFeatures().transform(self._base_df())
        for col in ["hour_of_day", "day_of_week", "day_of_month", "month"]:
            assert col in df.columns

    def test_flag_columns_present(self) -> None:
        df = TimeContextFeatures().transform(self._base_df())
        for col in ["is_weekend", "is_business_hour"]:
            assert col in df.columns

    def test_cyclical_columns_present(self) -> None:
        df = TimeContextFeatures().transform(self._base_df())
        for col in ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]:
            assert col in df.columns

    def test_hour_of_day_correct(self) -> None:
        start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["hour_of_day"].iloc[0] == 14

    def test_day_of_week_correct_monday(self) -> None:
        # 2026-01-05 is a Monday
        start = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["day_of_week"].iloc[0] == 0  # 0 = Monday

    def test_is_weekend_true_on_saturday(self) -> None:
        # 2026-01-03 is a Saturday
        start = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["is_weekend"].iloc[0] == 1

    def test_is_weekend_false_on_monday(self) -> None:
        start = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)  # Monday
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["is_weekend"].iloc[0] == 0

    def test_is_business_hour_true_during_work_hours(self) -> None:
        start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)  # Mon 10:00
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["is_business_hour"].iloc[0] == 1

    def test_is_business_hour_false_at_night(self) -> None:
        start = datetime(2026, 1, 5, 2, 0, tzinfo=timezone.utc)  # Mon 02:00
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["is_business_hour"].iloc[0] == 0

    def test_is_business_hour_false_on_weekend(self) -> None:
        start = datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc)  # Sat 10:00
        df = TimeContextFeatures().transform(self._base_df(start=start))
        assert df["is_business_hour"].iloc[0] == 0

    def test_cyclical_encoding_within_unit_circle(self) -> None:
        df = TimeContextFeatures().transform(self._base_df())
        for col in ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]:
            assert (df[col].abs() <= 1.0 + 1e-9).all(), f"{col} out of [-1, 1]"

    def test_cyclical_sin_cos_identity(self) -> None:
        """sin²+cos² must equal 1 for hour and day encodings."""
        df = TimeContextFeatures().transform(self._base_df())
        hour_norm = df["hour_sin"] ** 2 + df["hour_cos"] ** 2
        dow_norm  = df["dow_sin"]  ** 2 + df["dow_cos"]  ** 2
        assert (hour_norm - 1.0).abs().max() < 1e-9
        assert (dow_norm  - 1.0).abs().max() < 1e-9

    def test_missing_bucket_col_raises(self) -> None:
        df = _make_df().drop(columns=["bucket"])
        with pytest.raises(ValueError, match="bucket_col"):
            TimeContextFeatures().transform(df)

    def test_feature_columns_list_matches_output(self) -> None:
        tcf = TimeContextFeatures()
        df = tcf.transform(self._base_df())
        for col in tcf.feature_columns():
            assert col in df.columns


# ===========================================================================
# Pipeline integration: FEA-01 → FEA-02 → FEA-03 → FEA-04
# ===========================================================================

class TestFeaturePipelineIntegration:

    def test_full_pipeline_produces_no_extra_nan_in_first_window(self) -> None:
        """
        After the warmup period (window=5) every core feature should have a
        value; spot-check row 5 onward for a handful of columns.
        """
        df = _make_df(n=60)
        df = RollingWindowExtractor(WindowConfig(windows=[5])).transform(df)
        df = GrowthRateFeatures(GrowthRateConfig(lags=[1], cagr_windows=[5])).transform(df)
        df = VolatilityFeatures(VolatilityConfig(windows=[5])).transform(df)
        df = TimeContextFeatures().transform(df)

        spot_check = [
            "total_cost_roll5_mean",
            "total_cost_pct_change_1",
            "total_cost_cv_5",
            "hour_of_day",
            "is_weekend",
        ]
        tail = df.iloc[5:]
        for col in spot_check:
            assert col in df.columns
            assert tail[col].notna().all(), f"Unexpected NaN in '{col}' after warmup"

    def test_full_pipeline_row_count_preserved(self) -> None:
        n = 45
        df = _make_df(n=n)
        df = RollingWindowExtractor().transform(df)
        df = GrowthRateFeatures().transform(df)
        df = VolatilityFeatures().transform(df)
        df = TimeContextFeatures().transform(df)
        assert len(df) == n

    def test_multi_series_pipeline_no_bleed(self) -> None:
        """
        Growth-rate features for the 'storage' series should not be influenced
        by 'compute' costs when using transform_group.
        """
        df_multi = _make_multi_df()
        extractor = RollingWindowExtractor(WindowConfig(windows=[5]))
        df_out = extractor.transform_group(df_multi)
        df_out = GrowthRateFeatures(GrowthRateConfig(lags=[1])).transform(df_out)

        compute = df_out[df_out["service"] == "compute"]
        storage = df_out[df_out["service"] == "storage"]

        # Storage is flat at 50; compute grows linearly — their pct_change_1
        # values should differ
        assert not compute["total_cost_pct_change_1"].equals(
            storage["total_cost_pct_change_1"]
        )
