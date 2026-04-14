"""
ENS-01: Unit tests for the weighted score fusion pipeline (OnlineScorer).

Covers:
  ENS-01  _fuse()                  – weighted average with NaN exclusion
  ENS-01  score() / score_group()  – end-to-end scoring with mocked models
  ENS-01  ScoringConfig            – weight defaults and component toggles
  ENS-01  graceful degradation     – missing models → zero / NaN fallback
  ENS-01  weight renormalisation   – disabled components excluded cleanly
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from ml.src.inference.scorer import OnlineScorer, ScoringConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_df(
    n: int = 20,
    cost_values: list[float] | None = None,
    account_id: str = "acct-001",
    service: str = "compute",
    region: str = "us-central1",
    start: datetime | None = None,
) -> pd.DataFrame:
    """Minimal 1-minute aggregate DataFrame with time-context columns."""
    if start is None:
        start = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)  # Monday 09:00
    buckets = [start + timedelta(minutes=i) for i in range(n)]
    costs = cost_values if cost_values is not None else [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "bucket": pd.to_datetime(buckets, utc=True),
            "account_id": account_id,
            "service": service,
            "region": region,
            "total_cost": costs,
            "hour_of_day": [b.hour for b in buckets],
            "day_of_week": [b.weekday() for b in buckets],
        }
    )


def _make_forecast_df(df: pd.DataFrame, mean_offset: float = 0.0, std: float = 10.0) -> pd.DataFrame:
    """Fake forecast DataFrame aligned to ``df``."""
    return pd.DataFrame(
        {
            "forecast_mean": df["total_cost"].values + mean_offset,
            "forecast_std": std,
            "ci_lower_95": df["total_cost"].values + mean_offset - 2 * std,
            "ci_upper_95": df["total_cost"].values + mean_offset + 2 * std,
        },
        index=df.index,
    )


def _make_baseline_mock(df: pd.DataFrame, mean_offset: float = 0.0, std: float = 10.0):
    """Mock TimeSeriesBaselineModel whose predict() returns a forecast DataFrame."""
    mock = MagicMock()
    mock.predict.side_effect = lambda d: _make_forecast_df(d, mean_offset=mean_offset, std=std)
    return mock


def _make_if_mock(df: pd.DataFrame, if_score_value: float = 0.1):
    """Mock IsolationForestDetector whose predict() returns fixed scores."""
    mock = MagicMock()
    def _predict(d):
        return d.assign(
            if_score=if_score_value,
            if_anomaly=np.int8(0),
        )
    mock.predict.side_effect = _predict
    return mock


# ---------------------------------------------------------------------------
# ScoringConfig defaults
# ---------------------------------------------------------------------------

class TestScoringConfig:

    def test_default_weights_sum_to_one(self) -> None:
        cfg = ScoringConfig()
        total = cfg.weight_ts + cfg.weight_if + cfg.weight_rules
        assert abs(total - 1.0) < 1e-9

    def test_default_weights(self) -> None:
        cfg = ScoringConfig()
        assert cfg.weight_ts == 0.35
        assert cfg.weight_if == 0.40
        assert cfg.weight_rules == 0.25

    def test_default_threshold(self) -> None:
        cfg = ScoringConfig()
        assert cfg.anomaly_threshold == 0.55

    def test_all_components_enabled_by_default(self) -> None:
        cfg = ScoringConfig()
        assert cfg.enable_ts is True
        assert cfg.enable_if is True
        assert cfg.enable_rules is True

    def test_default_group_cols(self) -> None:
        cfg = ScoringConfig()
        assert cfg.group_cols == ["account_id", "service", "region"]


# ---------------------------------------------------------------------------
# _fuse() — core ENS-01 logic tested via score() with mocked models
# ---------------------------------------------------------------------------

class TestFuse:
    """
    Test the _fuse() logic by setting up an OnlineScorer with known ts_signal,
    if_score, and rule_score values, then asserting anomaly_score math.
    """

    def _scorer_no_models(self, **cfg_kwargs) -> OnlineScorer:
        """Scorer with all components disabled → _fuse gets zeros/NaNs."""
        defaults = dict(enable_ts=False, enable_if=False, enable_rules=False)
        defaults.update(cfg_kwargs)
        return OnlineScorer(ScoringConfig(**defaults))

    def test_all_nan_components_produce_zero_anomaly_score(self) -> None:
        cfg = ScoringConfig(enable_ts=False, enable_if=False, enable_rules=False)
        scorer = OnlineScorer(cfg)
        df = _make_df(n=5)
        result = scorer.score(df)
        assert (result["anomaly_score"] == 0.0).all()

    def test_weighted_average_correctness(self) -> None:
        """
        Inject ts_signal≈0.8, if_score=0.4, enable_rules=False (weight zeroed).
        _fuse() renormalises over the active weights only, so:
            active_weights = w_ts + w_if = 0.35 + 0.40 = 0.75
            score = (0.35 * 0.8 + 0.40 * 0.4) / 0.75
                  = (0.28 + 0.16) / 0.75 ≈ 0.5867
        """
        df = _make_df(n=5)

        # Drive ts_signal to 0.8: set residual = 0.8 * z_cap (absolute)
        z_cap = 10.0
        target_z = 0.8 * z_cap  # abs_z_score = 8.0 → ts_signal = 0.8
        std = 1.0
        mean_offset = -(target_z * std)  # actual − mean = +target_z * std

        baseline_mock = _make_baseline_mock(df, mean_offset=mean_offset, std=std)
        if_mock = _make_if_mock(df, if_score_value=0.4)

        scorer = OnlineScorer(ScoringConfig(
            weight_ts=0.35,
            weight_if=0.40,
            weight_rules=0.25,
            enable_rules=False,  # weight becomes 0 → renorm over ts + if only
            z_score_cap=z_cap,
        ))
        scorer.set_baseline(baseline_mock)
        scorer.set_detector(if_mock)

        result = scorer.score(df)
        w_ts, w_if = 0.35, 0.40
        denom = w_ts + w_if
        expected = (w_ts * 0.8 + w_if * 0.4) / denom
        assert (result["anomaly_score"] - expected).abs().max() < 1e-4

    def test_nan_ts_signal_excluded_and_weights_renormalised(self) -> None:
        """
        With TS disabled (ts_signal=NaN), remaining weights (IF + rules) must
        renormalise so they sum to 1.  Expected score:
            if_score=0.6, rule_score=0.0 (rules enabled but no breach)
            renorm = 0.40 / (0.40 + 0.25) = 0.6154...
            score ≈ 0.6154 * 0.6 = 0.3692...
        """
        df = _make_df(n=5)
        if_mock = _make_if_mock(df, if_score_value=0.6)

        scorer = OnlineScorer(ScoringConfig(
            weight_ts=0.35,
            weight_if=0.40,
            weight_rules=0.25,
            enable_ts=False,       # ts_signal will be NaN
        ))
        scorer.set_detector(if_mock)

        result = scorer.score(df)
        w_if = 0.40
        w_rules = 0.25
        denom = w_if + w_rules
        expected = (w_if * 0.6 + w_rules * 0.0) / denom
        assert (result["anomaly_score"] - expected).abs().max() < 1e-4

    def test_nan_if_score_excluded_and_weights_renormalised(self) -> None:
        """IF disabled: only TS and rules contribute."""
        df = _make_df(n=5)

        # ts_signal = 1.0 (large residual)
        z_cap = 10.0
        std = 1.0
        mean_offset = -(z_cap * std)
        baseline_mock = _make_baseline_mock(df, mean_offset=mean_offset, std=std)

        scorer = OnlineScorer(ScoringConfig(
            weight_ts=0.35,
            weight_if=0.40,
            weight_rules=0.25,
            enable_if=False,
            enable_rules=False,
            z_score_cap=z_cap,
        ))
        scorer.set_baseline(baseline_mock)

        result = scorer.score(df)
        # Only TS contributes; renorm = 0.35 / 0.35 = 1.0 → score = 1.0 * ts_signal
        assert (result["anomaly_score"] - 1.0).abs().max() < 1e-4

    def test_anomaly_score_in_zero_one_range(self) -> None:
        df = _make_df(n=10)
        baseline_mock = _make_baseline_mock(df, mean_offset=-50.0, std=5.0)
        if_mock = _make_if_mock(df, if_score_value=0.9)

        scorer = OnlineScorer()
        scorer.set_baseline(baseline_mock)
        scorer.set_detector(if_mock)

        result = scorer.score(df)
        assert (result["anomaly_score"] >= 0.0).all()
        assert (result["anomaly_score"] <= 1.0).all()


# ---------------------------------------------------------------------------
# is_anomaly threshold
# ---------------------------------------------------------------------------

class TestAnomalyDecision:

    def test_is_anomaly_true_when_score_meets_threshold(self) -> None:
        df = _make_df(n=5)

        # Force a very large z-score so ts_signal → 1.0, ensuring score ≥ threshold
        z_cap = 10.0
        std = 1.0
        mean_offset = -(z_cap * std)
        baseline_mock = _make_baseline_mock(df, mean_offset=mean_offset, std=std)
        if_mock = _make_if_mock(df, if_score_value=1.0)

        scorer = OnlineScorer(ScoringConfig(anomaly_threshold=0.50))
        scorer.set_baseline(baseline_mock)
        scorer.set_detector(if_mock)

        result = scorer.score(df)
        assert (result["is_anomaly"] == 1).all()

    def test_is_anomaly_false_when_score_below_threshold(self) -> None:
        df = _make_df(n=5)

        # Force ts_signal ≈ 0 (perfect forecast), if_score = 0
        baseline_mock = _make_baseline_mock(df, mean_offset=0.0, std=1000.0)
        if_mock = _make_if_mock(df, if_score_value=0.0)

        scorer = OnlineScorer(ScoringConfig(anomaly_threshold=0.55))
        scorer.set_baseline(baseline_mock)
        scorer.set_detector(if_mock)

        result = scorer.score(df)
        assert (result["is_anomaly"] == 0).all()

    def test_is_anomaly_dtype_is_int8(self) -> None:
        df = _make_df(n=5)
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False, enable_rules=False))
        result = scorer.score(df)
        assert result["is_anomaly"].dtype == np.dtype("int8")


# ---------------------------------------------------------------------------
# Output columns
# ---------------------------------------------------------------------------

class TestOutputColumns:

    def test_score_adds_all_expected_columns(self) -> None:
        df = _make_df(n=5)
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False, enable_rules=False))
        result = scorer.score(df)
        for col in ["ts_signal", "if_score", "rule_score", "anomaly_score", "is_anomaly"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_original_columns_preserved(self) -> None:
        df = _make_df(n=5)
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score(df)
        for col in df.columns:
            assert col in result.columns

    def test_row_count_preserved(self) -> None:
        n = 15
        df = _make_df(n=n)
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score(df)
        assert len(result) == n


# ---------------------------------------------------------------------------
# score_group(): multi-series isolation
# ---------------------------------------------------------------------------

class TestScoreGroup:

    def _multi_df(self) -> pd.DataFrame:
        df_a = _make_df(n=15, service="compute")
        df_b = _make_df(n=15, service="storage", cost_values=[50.0] * 15)
        return pd.concat([df_a, df_b], ignore_index=True)

    def test_score_group_returns_same_row_count(self) -> None:
        df = self._multi_df()
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score_group(df)
        assert len(result) == len(df)

    def test_score_group_preserves_original_index(self) -> None:
        df = self._multi_df()
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score_group(df)
        assert list(result.index) == list(df.index)

    def test_score_group_adds_anomaly_score_column(self) -> None:
        df = self._multi_df()
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score_group(df)
        assert "anomaly_score" in result.columns

    def test_score_group_series_scores_differ(self) -> None:
        """Compute (growing) and storage (flat) should get different scores."""
        df_a = _make_df(n=20, service="compute", cost_values=[100.0 * (1.2 ** i) for i in range(20)])
        df_b = _make_df(n=20, service="storage", cost_values=[50.0] * 20)
        df = pd.concat([df_a, df_b], ignore_index=True)

        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score_group(df)

        compute_score = result[result["service"] == "compute"]["anomaly_score"].mean()
        storage_score = result[result["service"] == "storage"]["anomaly_score"].mean()
        assert compute_score != storage_score

    def test_score_group_no_group_cols_falls_back_to_score(self) -> None:
        """When no group columns present, score_group falls back to score()."""
        df = _make_df(n=10).drop(columns=["account_id", "service", "region"])
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score_group(df)
        assert "anomaly_score" in result.columns
        assert len(result) == 10


# ---------------------------------------------------------------------------
# Graceful degradation — no models loaded
# ---------------------------------------------------------------------------

class TestGracefulDegradation:

    def test_no_models_still_produces_anomaly_score(self) -> None:
        """Scorer with models enabled but not loaded must not raise."""
        scorer = OnlineScorer(ScoringConfig(enable_ts=True, enable_if=True, enable_rules=True))
        df = _make_df(n=5)
        result = scorer.score(df)
        assert "anomaly_score" in result.columns

    def test_no_models_ts_signal_is_nan(self) -> None:
        scorer = OnlineScorer(ScoringConfig(enable_ts=True))
        df = _make_df(n=5)
        result = scorer.score(df)
        assert result["ts_signal"].isna().all()

    def test_no_models_if_score_is_nan(self) -> None:
        scorer = OnlineScorer(ScoringConfig(enable_if=True))
        df = _make_df(n=5)
        result = scorer.score(df)
        assert result["if_score"].isna().all()

    def test_no_models_anomaly_score_in_valid_range(self) -> None:
        scorer = OnlineScorer()
        df = _make_df(n=10)
        result = scorer.score(df)
        assert (result["anomaly_score"] >= 0.0).all()
        assert (result["anomaly_score"] <= 1.0).all()


# ---------------------------------------------------------------------------
# Status / introspection helpers
# ---------------------------------------------------------------------------

class TestStatusHelpers:

    def test_has_baseline_false_initially(self) -> None:
        scorer = OnlineScorer()
        assert scorer.has_baseline is False

    def test_has_detector_false_initially(self) -> None:
        scorer = OnlineScorer()
        assert scorer.has_detector is False

    def test_has_baseline_true_after_set(self) -> None:
        scorer = OnlineScorer()
        scorer.set_baseline(_make_baseline_mock(_make_df(n=2)))
        assert scorer.has_baseline is True

    def test_has_detector_true_after_set(self) -> None:
        scorer = OnlineScorer()
        scorer.set_detector(_make_if_mock(_make_df(n=2)))
        assert scorer.has_detector is True

    def test_status_returns_expected_keys(self) -> None:
        scorer = OnlineScorer()
        s = scorer.status()
        assert "baseline_loaded" in s
        assert "if_loaded" in s
        assert "config" in s

    def test_status_config_reflects_scoring_config(self) -> None:
        cfg = ScoringConfig(weight_ts=0.5, weight_if=0.3, weight_rules=0.2, anomaly_threshold=0.6)
        scorer = OnlineScorer(cfg)
        s = scorer.status()["config"]
        assert s["weight_ts"] == 0.5
        assert s["weight_if"] == 0.3
        assert s["weight_rules"] == 0.2
        assert s["anomaly_threshold"] == 0.6


# ---------------------------------------------------------------------------
# Rule engine integration via score() — no ML models needed
# ---------------------------------------------------------------------------

class TestRuleEngineIntegration:

    def test_large_spike_produces_positive_rule_score(self) -> None:
        """A cost 10× above budget_limit should produce a non-zero rule_score."""
        budget = 100.0
        costs = [budget * 10] * 10  # way above budget
        df = _make_df(n=10, cost_values=costs)

        scorer = OnlineScorer(ScoringConfig(
            enable_ts=False,
            enable_if=False,
            enable_rules=True,
            budget_limit=budget,
        ))
        result = scorer.score(df)
        assert (result["rule_score"] > 0.0).all()

    def test_normal_costs_produce_low_rule_score(self) -> None:
        """Costs well within all thresholds → rule_score should stay low."""
        costs = [10.0] * 20  # far below default budget_limit=1000
        df = _make_df(n=20, cost_values=costs)

        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        result = scorer.score(df)
        assert (result["rule_score"] < 0.5).all()

    def test_sustained_growth_increases_rule_score_over_time(self) -> None:
        """Costs that double every step → sustained rule fires → score rises."""
        costs = [50.0 * (2.0 ** i) for i in range(20)]
        df = _make_df(n=20, cost_values=costs)

        scorer = OnlineScorer(ScoringConfig(
            enable_ts=False,
            enable_if=False,
            sustained_window=3,
            sustained_min_growth=0.05,
            budget_limit=1e9,   # disable threshold rule
            jump_pct=100.0,     # disable jump rule effectively
        ))
        result = scorer.score(df)
        # After the warmup window, rule_score should be non-zero
        late_scores = result["rule_score"].iloc[5:]
        assert (late_scores > 0.0).any()
