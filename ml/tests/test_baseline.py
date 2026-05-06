"""
TST-02: Unit tests for ml.src.models.baseline (TS-01 / TS-02).

Covers the seasonal baseline model: SeasonalProfile lookup behavior,
fit/predict invariants, confidence-interval emission, save/load round-trip.
sklearn is intentionally not imported — this is a pure-numpy / pandas
model so the tests stay green even on environments without sklearn.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from ml.src.models.baseline import (
    BaselineConfig,
    SeasonalProfile,
    TimeSeriesBaselineModel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_training_df(
    n_days: int = 7,
    minutes_per_day: int = 60,
    base_cost: float = 100.0,
    noise_seed: int = 42,
) -> pd.DataFrame:
    """Build a deterministic minute-level training set."""
    rng = np.random.default_rng(noise_seed)
    start = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Monday
    rows = []
    for day in range(n_days):
        for minute in range(minutes_per_day):
            ts = start + timedelta(days=day, minutes=minute)
            rows.append({
                "bucket": ts,
                "account_id": "acct-1",
                "service": "compute",
                "region": "us-central1",
                "total_cost": base_cost + rng.normal(0, 5),
                "hour_of_day": ts.hour,
                "day_of_week": ts.weekday(),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# SeasonalProfile
# ---------------------------------------------------------------------------


class TestSeasonalProfile:
    def test_known_key_returns_stored_mean(self) -> None:
        profile = SeasonalProfile(
            means={"14,2": 250.0},
            stds={"14,2": 5.0},
            counts={"14,2": 10},
            global_mean=100.0,
            global_std=20.0,
        )
        assert profile.get_mean(14, 2) == 250.0
        assert profile.get_std(14, 2) == 5.0

    def test_unknown_key_falls_back_to_global(self) -> None:
        profile = SeasonalProfile(global_mean=42.0, global_std=1.5)
        assert profile.get_mean(0, 0) == 42.0
        assert profile.get_std(23, 6) == 1.5

    def test_round_trip_through_dict(self) -> None:
        original = SeasonalProfile(
            means={"9,1": 120.0},
            stds={"9,1": 12.5},
            counts={"9,1": 7},
            global_mean=100.0,
            global_std=10.0,
        )
        restored = SeasonalProfile.from_dict(original.to_dict())
        assert restored.get_mean(9, 1) == 120.0
        assert restored.get_std(9, 1) == 12.5
        assert restored.global_mean == 100.0

    def test_dict_keys_are_strings_for_json_safety(self) -> None:
        # Tuple keys would not survive a JSON round-trip; the profile must
        # use string keys like "14,2" instead.
        profile = SeasonalProfile(means={"14,2": 1.0}, stds={"14,2": 1.0}, counts={"14,2": 1})
        assert all(isinstance(k, str) for k in profile.means.keys())

    def test_key_helper_format(self) -> None:
        assert SeasonalProfile._key(14, 2) == "14,2"
        assert SeasonalProfile._key(0, 0) == "0,0"


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------


class TestFit:
    def test_fit_marks_model_as_fitted(self) -> None:
        model = TimeSeriesBaselineModel(BaselineConfig(min_train_rows=10))
        df = _build_training_df()
        model.fit(df)
        assert model.is_fitted is True
        assert model.profile is not None

    def test_fit_too_few_rows_raises(self) -> None:
        model = TimeSeriesBaselineModel(BaselineConfig(min_train_rows=100))
        df = _build_training_df(n_days=1, minutes_per_day=10)  # only 10 rows
        with pytest.raises(ValueError):
            model.fit(df)

    def test_fit_missing_target_col_raises(self) -> None:
        model = TimeSeriesBaselineModel(BaselineConfig(min_train_rows=10))
        df = _build_training_df().drop(columns=["total_cost"])
        with pytest.raises((KeyError, ValueError)):
            model.fit(df)

    def test_fit_group_equivalent_to_fit(self) -> None:
        # The docstring says fit_group pools all rows (same profile).
        cfg = BaselineConfig(min_train_rows=10)
        df = _build_training_df()
        m1 = TimeSeriesBaselineModel(cfg).fit(df)
        m2 = TimeSeriesBaselineModel(cfg).fit_group(df)
        assert m1.profile.global_mean == m2.profile.global_mean

    def test_predict_before_fit_raises(self) -> None:
        model = TimeSeriesBaselineModel()
        with pytest.raises((ValueError, RuntimeError)):
            model.predict(_build_training_df())


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------


class TestPredict:
    def _fitted(self) -> TimeSeriesBaselineModel:
        cfg = BaselineConfig(min_train_rows=10)
        return TimeSeriesBaselineModel(cfg).fit(_build_training_df())

    def test_output_has_forecast_columns(self) -> None:
        model = self._fitted()
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        assert "forecast_mean" in out.columns
        assert "forecast_std" in out.columns

    def test_default_ci_95_emitted(self) -> None:
        model = self._fitted()
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        assert "ci_lower_95" in out.columns
        assert "ci_upper_95" in out.columns

    def test_no_ci_columns_when_levels_empty(self) -> None:
        cfg = BaselineConfig(min_train_rows=10, confidence_levels=[])
        model = TimeSeriesBaselineModel(cfg).fit(_build_training_df())
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=10))
        # No ci_* columns should be present.
        assert not any(c.startswith("ci_lower_") for c in out.columns)
        assert not any(c.startswith("ci_upper_") for c in out.columns)

    def test_multiple_ci_levels_each_emit_columns(self) -> None:
        cfg = BaselineConfig(min_train_rows=10, confidence_levels=[0.90, 0.95, 0.99])
        model = TimeSeriesBaselineModel(cfg).fit(_build_training_df())
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=10))
        for pct in (90, 95, 99):
            assert f"ci_lower_{pct}" in out.columns
            assert f"ci_upper_{pct}" in out.columns

    def test_ci_lower_below_upper(self) -> None:
        model = self._fitted()
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        assert (out["ci_lower_95"] <= out["ci_upper_95"]).all()

    def test_ci_lower_clipped_at_zero(self) -> None:
        # Negative spend isn't meaningful — lower bound must never go below 0.
        model = self._fitted()
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        assert (out["ci_lower_95"] >= 0.0).all()

    def test_99_ci_wider_than_90_ci(self) -> None:
        cfg = BaselineConfig(min_train_rows=10, confidence_levels=[0.90, 0.99])
        model = TimeSeriesBaselineModel(cfg).fit(_build_training_df())
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        width_90 = (out["ci_upper_90"] - out["ci_lower_90"]).mean()
        width_99 = (out["ci_upper_99"] - out["ci_lower_99"]).mean()
        assert width_99 > width_90

    def test_forecast_std_is_non_negative(self) -> None:
        model = self._fitted()
        out = model.predict(_build_training_df(n_days=1, minutes_per_day=20))
        assert (out["forecast_std"] >= 0.0).all()

    def test_predict_index_preserved(self) -> None:
        model = self._fitted()
        df = _build_training_df(n_days=1, minutes_per_day=20)
        out = model.predict(df)
        assert list(out.index) == list(df.index)


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------


class TestSaveLoad:
    def test_save_writes_two_json_files(self, tmp_path) -> None:
        cfg = BaselineConfig(min_train_rows=10, artifact_dir=str(tmp_path))
        model = TimeSeriesBaselineModel(cfg).fit(_build_training_df())
        model.save()
        assert (tmp_path / "baseline_seasonal_profile.json").exists()
        assert (tmp_path / "baseline_config.json").exists()

    def test_save_unfitted_raises(self, tmp_path) -> None:
        model = TimeSeriesBaselineModel(BaselineConfig(artifact_dir=str(tmp_path)))
        with pytest.raises((ValueError, RuntimeError)):
            model.save()

    def test_round_trip_preserves_predictions(self, tmp_path) -> None:
        cfg = BaselineConfig(min_train_rows=10, artifact_dir=str(tmp_path))
        original = TimeSeriesBaselineModel(cfg).fit(_build_training_df())
        original.save()

        restored = TimeSeriesBaselineModel.load(str(tmp_path))
        assert restored.is_fitted is True

        df_pred = _build_training_df(n_days=1, minutes_per_day=10)
        out_orig = original.predict(df_pred)
        out_restored = restored.predict(df_pred)
        # Predictions must match exactly after a round-trip.
        np.testing.assert_allclose(
            out_orig["forecast_mean"].to_numpy(),
            out_restored["forecast_mean"].to_numpy(),
        )

    def test_load_missing_profile_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            TimeSeriesBaselineModel.load(str(tmp_path))

    def test_load_without_config_uses_defaults(self, tmp_path) -> None:
        # Write only the profile file — load() should fall back to default config.
        profile = SeasonalProfile(global_mean=10.0, global_std=2.0)
        (tmp_path / "baseline_seasonal_profile.json").write_text(
            json.dumps(profile.to_dict())
        )
        restored = TimeSeriesBaselineModel.load(str(tmp_path))
        assert restored.is_fitted is True
        # Default target_col is total_cost.
        assert restored.config.target_col == "total_cost"
