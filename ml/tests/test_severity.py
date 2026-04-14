"""
ENS-02: Unit tests for severity mapping.

Covers:
  SeverityLevel  – enum values, ordering, str identity
  SeverityConfig – validation of boundary ordering
  SeverityMapper – map_score(), transform(), edge cases
  Integration    – SeverityMapper wired into OnlineScorer
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from ml.src.inference.severity import (
    SeverityLevel,
    SeverityConfig,
    SeverityMapper,
)
from ml.src.inference.scorer import OnlineScorer, ScoringConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_scored_df(
    n: int = 10,
    anomaly_scores: list[float] | None = None,
    is_anomaly: list[int] | None = None,
) -> pd.DataFrame:
    """Minimal post-scoring DataFrame with the columns SeverityMapper needs."""
    scores = anomaly_scores if anomaly_scores is not None else [0.3] * n
    flags = is_anomaly if is_anomaly is not None else [int(s >= 0.55) for s in scores]
    return pd.DataFrame(
        {
            "anomaly_score": scores,
            "is_anomaly": flags,
        }
    )


def _make_feature_df(n: int = 20) -> pd.DataFrame:
    """Minimal feature DataFrame for OnlineScorer integration tests."""
    start = datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)
    buckets = [start + timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame(
        {
            "bucket": pd.to_datetime(buckets, utc=True),
            "account_id": "acct-001",
            "service": "compute",
            "region": "us-central1",
            "total_cost": [50.0] * n,
            "hour_of_day": [b.hour for b in buckets],
            "day_of_week": [b.weekday() for b in buckets],
        }
    )


# ---------------------------------------------------------------------------
# SeverityLevel
# ---------------------------------------------------------------------------


class TestSeverityLevel:

    def test_string_values(self) -> None:
        assert SeverityLevel.NONE == "none"
        assert SeverityLevel.LOW == "low"
        assert SeverityLevel.MEDIUM == "medium"
        assert SeverityLevel.HIGH == "high"

    def test_str_identity(self) -> None:
        """SeverityLevel inherits str so JSON serialisation works directly."""
        assert isinstance(SeverityLevel.HIGH, str)

    def test_ordering_none_is_lowest(self) -> None:
        assert SeverityLevel.NONE < SeverityLevel.LOW

    def test_ordering_low_medium_high(self) -> None:
        assert SeverityLevel.LOW < SeverityLevel.MEDIUM < SeverityLevel.HIGH

    def test_ordering_ge(self) -> None:
        assert SeverityLevel.HIGH >= SeverityLevel.MEDIUM
        assert SeverityLevel.MEDIUM >= SeverityLevel.MEDIUM

    def test_ordering_le(self) -> None:
        assert SeverityLevel.LOW <= SeverityLevel.HIGH
        assert SeverityLevel.HIGH <= SeverityLevel.HIGH

    def test_all_four_levels_exist(self) -> None:
        levels = {s.value for s in SeverityLevel}
        assert levels == {"none", "low", "medium", "high"}


# ---------------------------------------------------------------------------
# SeverityConfig validation
# ---------------------------------------------------------------------------


class TestSeverityConfig:

    def test_default_thresholds_are_ordered(self) -> None:
        cfg = SeverityConfig()
        assert cfg.anomaly_threshold < cfg.low_medium_boundary < cfg.medium_high_boundary

    def test_default_values(self) -> None:
        cfg = SeverityConfig()
        assert cfg.anomaly_threshold == 0.55
        assert cfg.low_medium_boundary == 0.65
        assert cfg.medium_high_boundary == 0.80

    def test_custom_thresholds_accepted(self) -> None:
        cfg = SeverityConfig(
            anomaly_threshold=0.40,
            low_medium_boundary=0.60,
            medium_high_boundary=0.75,
        )
        assert cfg.anomaly_threshold == 0.40

    def test_invalid_threshold_above_low_medium_raises(self) -> None:
        with pytest.raises(ValueError, match="anomaly_threshold"):
            SeverityConfig(anomaly_threshold=0.70, low_medium_boundary=0.65)

    def test_invalid_low_medium_above_medium_high_raises(self) -> None:
        with pytest.raises(ValueError, match="low_medium_boundary"):
            SeverityConfig(low_medium_boundary=0.90, medium_high_boundary=0.80)

    def test_medium_high_at_one_is_valid(self) -> None:
        cfg = SeverityConfig(medium_high_boundary=1.0)
        assert cfg.medium_high_boundary == 1.0


# ---------------------------------------------------------------------------
# SeverityMapper.map_score()
# ---------------------------------------------------------------------------


class TestMapScore:

    def _mapper(self, **kwargs) -> SeverityMapper:
        return SeverityMapper(SeverityConfig(**kwargs))

    # --- NONE ---

    def test_score_below_threshold_is_none(self) -> None:
        result = self._mapper().map_score(0.30, is_anomaly=0)
        assert result == SeverityLevel.NONE

    def test_is_anomaly_zero_always_none(self) -> None:
        result = self._mapper().map_score(0.99, is_anomaly=0)
        assert result == SeverityLevel.NONE

    def test_auto_detect_below_threshold_is_none(self) -> None:
        result = self._mapper().map_score(0.50)  # < 0.55
        assert result == SeverityLevel.NONE

    # --- LOW ---

    def test_score_at_threshold_is_low(self) -> None:
        result = self._mapper().map_score(0.55, is_anomaly=1)
        assert result == SeverityLevel.LOW

    def test_score_just_below_low_medium_is_low(self) -> None:
        result = self._mapper().map_score(0.649, is_anomaly=1)
        assert result == SeverityLevel.LOW

    def test_auto_detect_just_above_threshold_is_low(self) -> None:
        result = self._mapper().map_score(0.60)  # ≥ 0.55, < 0.65
        assert result == SeverityLevel.LOW

    # --- MEDIUM ---

    def test_score_at_low_medium_boundary_is_medium(self) -> None:
        result = self._mapper().map_score(0.65, is_anomaly=1)
        assert result == SeverityLevel.MEDIUM

    def test_score_just_below_medium_high_is_medium(self) -> None:
        result = self._mapper().map_score(0.799, is_anomaly=1)
        assert result == SeverityLevel.MEDIUM

    def test_auto_detect_medium_range(self) -> None:
        result = self._mapper().map_score(0.72)
        assert result == SeverityLevel.MEDIUM

    # --- HIGH ---

    def test_score_at_medium_high_boundary_is_high(self) -> None:
        result = self._mapper().map_score(0.80, is_anomaly=1)
        assert result == SeverityLevel.HIGH

    def test_score_at_one_is_high(self) -> None:
        result = self._mapper().map_score(1.0, is_anomaly=1)
        assert result == SeverityLevel.HIGH

    def test_auto_detect_high(self) -> None:
        result = self._mapper().map_score(0.95)
        assert result == SeverityLevel.HIGH

    # --- custom config ---

    def test_custom_boundaries_respected(self) -> None:
        mapper = self._mapper(
            anomaly_threshold=0.40,
            low_medium_boundary=0.55,
            medium_high_boundary=0.70,
        )
        assert mapper.map_score(0.45, is_anomaly=1) == SeverityLevel.LOW
        assert mapper.map_score(0.60, is_anomaly=1) == SeverityLevel.MEDIUM
        assert mapper.map_score(0.75, is_anomaly=1) == SeverityLevel.HIGH


# ---------------------------------------------------------------------------
# SeverityMapper.transform()
# ---------------------------------------------------------------------------


class TestTransform:

    def _mapper(self) -> SeverityMapper:
        return SeverityMapper()

    def test_adds_severity_column(self) -> None:
        df = _make_scored_df(n=5)
        result = self._mapper().transform(df)
        assert "severity" in result.columns

    def test_does_not_modify_input(self) -> None:
        df = _make_scored_df(n=5)
        original_cols = list(df.columns)
        self._mapper().transform(df)
        assert list(df.columns) == original_cols

    def test_row_count_preserved(self) -> None:
        n = 8
        df = _make_scored_df(n=n)
        result = self._mapper().transform(df)
        assert len(result) == n

    def test_non_anomaly_rows_are_none(self) -> None:
        df = _make_scored_df(
            anomaly_scores=[0.30, 0.20, 0.10],
            is_anomaly=[0, 0, 0],
        )
        result = self._mapper().transform(df)
        assert (result["severity"] == "none").all()

    def test_all_severity_levels_produced(self) -> None:
        df = _make_scored_df(
            anomaly_scores=[0.20, 0.58, 0.70, 0.90],
            is_anomaly=[0, 1, 1, 1],
        )
        result = self._mapper().transform(df)
        assert result["severity"].tolist() == ["none", "low", "medium", "high"]

    def test_missing_score_col_raises(self) -> None:
        df = pd.DataFrame({"is_anomaly": [0, 1]})
        with pytest.raises(ValueError, match="anomaly_score"):
            self._mapper().transform(df)

    def test_missing_is_anomaly_col_derives_from_score(self) -> None:
        """When is_anomaly column absent, mapper derives flag from score."""
        df = pd.DataFrame({"anomaly_score": [0.30, 0.90]})
        result = self._mapper().transform(df)
        assert result["severity"].iloc[0] == "none"
        assert result["severity"].iloc[1] == "high"

    def test_severity_values_are_strings(self) -> None:
        df = _make_scored_df(
            anomaly_scores=[0.60, 0.75, 0.85],
            is_anomaly=[1, 1, 1],
        )
        result = self._mapper().transform(df)
        # Pandas 2+ may infer StringDtype; what matters is every value is a str
        assert all(isinstance(v, str) for v in result["severity"])

    def test_custom_severity_col_name(self) -> None:
        cfg = SeverityConfig()
        cfg.severity_col = "risk_level"
        mapper = SeverityMapper(cfg)
        df = _make_scored_df(n=3)
        result = mapper.transform(df)
        assert "risk_level" in result.columns

    def test_exact_boundary_values(self) -> None:
        """Scores exactly at each boundary should land in the upper bucket."""
        df = _make_scored_df(
            anomaly_scores=[0.55, 0.65, 0.80],
            is_anomaly=[1, 1, 1],
        )
        result = self._mapper().transform(df)
        assert result["severity"].tolist() == ["low", "medium", "high"]

    def test_large_dataframe_performance(self) -> None:
        """transform() should handle 10k rows without error."""
        n = 10_000
        scores = np.linspace(0.0, 1.0, n).tolist()
        flags = [int(s >= 0.55) for s in scores]
        df = _make_scored_df(n=n, anomaly_scores=scores, is_anomaly=flags)
        result = self._mapper().transform(df)
        assert len(result) == n
        assert "severity" in result.columns


# ---------------------------------------------------------------------------
# Integration: SeverityMapper inside OnlineScorer
# ---------------------------------------------------------------------------


class TestOnlineScorerSeverityIntegration:

    def _scorer_with_severity(self, **severity_cfg_kwargs) -> OnlineScorer:
        return OnlineScorer(
            config=ScoringConfig(enable_ts=False, enable_if=False),
            severity_mapper=SeverityMapper(SeverityConfig(**severity_cfg_kwargs)),
        )

    def test_severity_column_present_when_mapper_configured(self) -> None:
        scorer = self._scorer_with_severity()
        df = _make_feature_df()
        result = scorer.score(df)
        assert "severity" in result.columns

    def test_severity_column_absent_when_no_mapper(self) -> None:
        scorer = OnlineScorer(ScoringConfig(enable_ts=False, enable_if=False))
        df = _make_feature_df()
        result = scorer.score(df)
        assert "severity" not in result.columns

    def test_severity_values_valid(self) -> None:
        scorer = self._scorer_with_severity()
        df = _make_feature_df()
        result = scorer.score(df)
        valid = {"none", "low", "medium", "high"}
        assert set(result["severity"].unique()).issubset(valid)

    def test_score_group_also_adds_severity(self) -> None:
        scorer = self._scorer_with_severity()
        df_a = _make_feature_df(n=10)
        df_b = _make_feature_df(n=10)
        df_b["service"] = "storage"
        df = pd.concat([df_a, df_b], ignore_index=True)
        result = scorer.score_group(df)
        assert "severity" in result.columns
        assert len(result) == len(df)

    def test_status_includes_severity_section(self) -> None:
        scorer = self._scorer_with_severity()
        s = scorer.status()
        assert "severity" in s
        assert s["severity"]["enabled"] is True

    def test_status_severity_disabled_when_no_mapper(self) -> None:
        scorer = OnlineScorer()
        s = scorer.status()
        assert s["severity"]["enabled"] is False

    def test_from_artifacts_accepts_severity_mapper(self) -> None:
        mapper = SeverityMapper()
        scorer = OnlineScorer.from_artifacts(severity_mapper=mapper)
        assert scorer._severity_mapper is mapper
