"""
Test that the Default FinGuard profile trains correctly on seeded GCP data
and produces valid anomaly scores through the full inference pipeline.

Exercises:
  1. GCP seed data generation (deterministic, 18,144 rows)
  2. Baseline model training (TS-01/02)
  3. Autoencoder training (ML-01b)
  4. Model save/load round-trip
  5. Full OnlineScorer (ENS-01) ensemble inference
  6. Score sanity checks (ranges, anomaly flags, severity)
"""

from __future__ import annotations

import math
import random
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# GCP seed constants (mirror backend/app/api/training.py)
# ---------------------------------------------------------------------------

_GCP_SEED_PROJECTS = {
    "finops-prod-01": {
        "Compute Engine": 85.0,
        "Cloud Storage": 12.0,
        "BigQuery": 35.0,
        "Cloud SQL": 42.0,
        "Kubernetes Engine": 68.0,
        "Cloud Functions": 5.5,
    },
    "finops-staging-01": {
        "Compute Engine": 28.0,
        "Cloud Storage": 4.5,
        "BigQuery": 8.0,
        "Cloud SQL": 14.0,
        "Kubernetes Engine": 22.0,
        "Cloud Functions": 2.0,
    },
    "analytics-prod-01": {
        "Compute Engine": 45.0,
        "Cloud Storage": 18.0,
        "BigQuery": 62.0,
        "Cloud SQL": 25.0,
        "Kubernetes Engine": 38.0,
        "Cloud Functions": 9.0,
    },
}

_GCP_SEED_REGIONS = ["us-central1", "us-east1", "europe-west1"]
_GCP_SEED_REGION_WEIGHTS = {"us-central1": 0.50, "us-east1": 0.30, "europe-west1": 0.20}

_GCP_SEED_USAGE = {
    "Compute Engine":    ("vCPU-hour",       150.0),
    "Cloud Storage":     ("gibibyte month",  500.0),
    "BigQuery":          ("tebibyte",          0.8),
    "Cloud SQL":         ("vCPU-hour",        48.0),
    "Kubernetes Engine": ("vCPU-hour",       210.0),
    "Cloud Functions":   ("invocations",  120000.0),
}


def _generate_seed_df() -> pd.DataFrame:
    """Generate the same 14-day GCP billing dataset used by the backend seeder.

    Returns a DataFrame matching the hourly-aggregated DB-02 schema that
    _load_billing_df would produce (already grouped by hour).
    """
    rng = random.Random(42)
    start = datetime.now(tz=UTC) - timedelta(days=14)
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = 14 * 24  # 336

    rows = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        hod = ts.hour
        dow = ts.weekday()

        daily = 1.0 + 0.30 * math.exp(-0.5 * ((hod - 13) / 4) ** 2)
        weekly = 0.60 if dow >= 5 else 1.0
        trend = 1.0 + 0.001 * h

        for project_id, services in _GCP_SEED_PROJECTS.items():
            for service, base_cost in services.items():
                for region in _GCP_SEED_REGIONS:
                    rw = _GCP_SEED_REGION_WEIGHTS[region]
                    unit, usage_base = _GCP_SEED_USAGE[service]

                    cost = base_cost * rw * daily * weekly * trend
                    cost *= 1.0 + rng.gauss(0, 0.08)
                    cost = max(0.01, round(cost, 6))

                    usage = usage_base * rw * daily * weekly
                    usage *= 1.0 + rng.gauss(0, 0.05)
                    usage = max(0.001, round(usage, 6))

                    rows.append({
                        "bucket": ts,
                        "account_id": project_id,
                        "service": service,
                        "region": region,
                        "total_cost": cost,
                        "total_usage": usage,
                        "event_count": 1,
                    })

    df = pd.DataFrame(rows)
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)

    # Aggregate to hourly buckets per group (mirrors _load_billing_df)
    df = (
        df.groupby(["bucket", "account_id", "service", "region"], as_index=False)
        .agg(total_cost=("total_cost", "sum"),
             total_usage=("total_usage", "sum"),
             event_count=("event_count", "sum"))
        .sort_values(["account_id", "service", "region", "bucket"])
        .reset_index(drop=True)
    )
    return df


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seed_df() -> pd.DataFrame:
    """Module-scoped GCP seed data so we only generate it once."""
    return _generate_seed_df()


@pytest.fixture(scope="module")
def artifact_dir(tmp_path_factory) -> Path:
    """Temporary artifact directory shared across all tests in this module."""
    return tmp_path_factory.mktemp("default_profile")


# ---------------------------------------------------------------------------
# 1. Seed data quality
# ---------------------------------------------------------------------------


class TestSeedData:
    def test_row_count(self, seed_df: pd.DataFrame) -> None:
        """14 days × 24 h × 3 projects × 6 services × 3 regions = 18,144 rows."""
        assert len(seed_df) == 18_144

    def test_no_nulls(self, seed_df: pd.DataFrame) -> None:
        assert seed_df.isna().sum().sum() == 0

    def test_positive_costs(self, seed_df: pd.DataFrame) -> None:
        assert (seed_df["total_cost"] > 0).all()

    def test_positive_usage(self, seed_df: pd.DataFrame) -> None:
        assert (seed_df["total_usage"] > 0).all()

    def test_expected_projects(self, seed_df: pd.DataFrame) -> None:
        assert set(seed_df["account_id"].unique()) == set(_GCP_SEED_PROJECTS.keys())

    def test_expected_regions(self, seed_df: pd.DataFrame) -> None:
        assert set(seed_df["region"].unique()) == set(_GCP_SEED_REGIONS)

    def test_expected_services(self, seed_df: pd.DataFrame) -> None:
        all_services = set()
        for svc_map in _GCP_SEED_PROJECTS.values():
            all_services.update(svc_map.keys())
        assert set(seed_df["service"].unique()) == all_services

    def test_spans_14_days(self, seed_df: pd.DataFrame) -> None:
        span = seed_df["bucket"].max() - seed_df["bucket"].min()
        assert span >= timedelta(days=13)  # 14 days minus 1 hour


# ---------------------------------------------------------------------------
# 2. Baseline model (TS-01 / TS-02)
# ---------------------------------------------------------------------------


class TestBaselineTraining:
    def test_fit_and_predict(self, seed_df: pd.DataFrame, artifact_dir: Path) -> None:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.baseline import BaselineConfig, TimeSeriesBaselineModel

        df = TimeContextFeatures().transform(seed_df)

        cfg = BaselineConfig(artifact_dir=str(artifact_dir), min_train_rows=60)
        model = TimeSeriesBaselineModel(cfg)
        model.fit_group(df)

        assert model.is_fitted
        assert model.profile is not None
        assert model.profile.global_mean > 0

        # Predict on the same data
        forecast = model.predict_group(df)
        assert "forecast_mean" in forecast.columns
        assert "forecast_std" in forecast.columns
        assert "ci_lower_95" in forecast.columns
        assert "ci_upper_95" in forecast.columns

        # Forecast values should be positive (billing costs)
        assert (forecast["forecast_mean"] > 0).all()
        assert (forecast["forecast_std"] >= 0).all()
        assert (forecast["ci_lower_95"] >= 0).all()
        assert (forecast["ci_lower_95"] <= forecast["ci_upper_95"]).all()

        # Save artifacts
        model.save(str(artifact_dir))
        assert (artifact_dir / "baseline_seasonal_profile.json").exists()
        assert (artifact_dir / "baseline_config.json").exists()

    def test_load_and_predict_matches(self, seed_df: pd.DataFrame, artifact_dir: Path) -> None:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.baseline import TimeSeriesBaselineModel

        model = TimeSeriesBaselineModel.load(str(artifact_dir))
        assert model.is_fitted

        df = TimeContextFeatures().transform(seed_df)
        forecast = model.predict_group(df)
        assert len(forecast) == len(df)
        assert (forecast["forecast_mean"] > 0).all()

    def test_seasonal_profile_has_all_hour_day_buckets(self, artifact_dir: Path) -> None:
        from ml.src.models.baseline import TimeSeriesBaselineModel

        model = TimeSeriesBaselineModel.load(str(artifact_dir))
        profile = model.profile

        # With 14 days of data, all 24 hours × 7 days should be populated
        populated = len(profile.means)
        assert populated == 24 * 7, f"Expected 168 seasonal buckets, got {populated}"


# ---------------------------------------------------------------------------
# 3. Autoencoder model (ML-01b)
# ---------------------------------------------------------------------------


class TestAutoencoderTraining:
    def test_fit_and_predict(self, seed_df: pd.DataFrame, artifact_dir: Path) -> None:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.autoencoder import AutoencoderConfig, AutoencoderDetector

        df = TimeContextFeatures().transform(seed_df)

        # NOTE: No rolling window features — must match what OnlineScorer provides at inference
        cfg = AutoencoderConfig(
            artifact_dir=str(artifact_dir),
            min_train_rows=60,
            random_state=42,
            hidden_dim=10,
            max_iter=1000,
            exclude_cols=["event_count"],
        )
        detector = AutoencoderDetector(cfg)
        detector.fit(df)

        assert detector.is_fitted
        assert len(detector.feature_cols) > 0

        # Predict
        scored = detector.predict(df)
        assert "if_score" in scored.columns
        assert "if_anomaly" in scored.columns

        # Scores in [0, 1]
        assert (scored["if_score"] >= 0).all()
        assert (scored["if_score"] <= 1).all()

        # Anomaly flags are 0 or 1
        assert set(scored["if_anomaly"].unique()).issubset({0, 1})

        # Most training data should be normal (not anomalous)
        anomaly_rate = scored["if_anomaly"].mean()
        assert anomaly_rate < 0.20, f"Too many anomalies on training data: {anomaly_rate:.2%}"

        # Median if_score on training data should be low (model learned normality)
        median_score = scored["if_score"].median()
        assert median_score < 0.40, (
            f"Median if_score on training data is {median_score:.3f} — "
            "should be < 0.40 for a well-trained autoencoder"
        )

        # Save
        detector.save(str(artifact_dir))
        assert (artifact_dir / "ae_model.pkl").exists()
        assert (artifact_dir / "ae_meta.json").exists()

    def test_load_and_predict(self, seed_df: pd.DataFrame, artifact_dir: Path) -> None:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.autoencoder import AutoencoderDetector

        detector = AutoencoderDetector.load(str(artifact_dir))
        assert detector.is_fitted

        df = TimeContextFeatures().transform(seed_df)
        scored = detector.predict(df)
        assert (scored["if_score"] >= 0).all()
        assert (scored["if_score"] <= 1).all()


# ---------------------------------------------------------------------------
# 4. Full ensemble scorer (ENS-01)
# ---------------------------------------------------------------------------


class TestEnsembleScoring:
    def test_full_pipeline_produces_valid_scores(
        self, seed_df: pd.DataFrame, artifact_dir: Path
    ) -> None:
        from ml.src.features.extractor import RollingWindowExtractor
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.inference.scorer import OnlineScorer, ScoringConfig

        df = TimeContextFeatures().transform(seed_df)

        # Load scorer from trained artifacts
        scorer = OnlineScorer.from_artifacts(
            baseline_dir=str(artifact_dir),
            if_dir=str(artifact_dir),
        )

        assert scorer.has_baseline, "Baseline model should be loaded"
        assert scorer.has_detector, "Autoencoder model should be loaded"

        # Score a single group to keep it fast
        group = df[
            (df["account_id"] == "finops-prod-01")
            & (df["service"] == "Compute Engine")
            & (df["region"] == "us-central1")
        ].sort_values("bucket").copy()

        assert len(group) > 100, f"Expected >100 rows for test group, got {len(group)}"

        scored = scorer.score(group)

        # Required output columns
        for col in ["ts_signal", "if_score", "rule_score", "anomaly_score", "is_anomaly"]:
            assert col in scored.columns, f"Missing output column: {col}"

        # ts_signal in [0, 1] (NaN allowed if TS disabled, but shouldn't be here)
        ts_vals = scored["ts_signal"].dropna()
        assert len(ts_vals) == len(scored), "ts_signal should not have NaN values"
        assert (ts_vals >= 0).all() and (ts_vals <= 1).all()

        # if_score in [0, 1]
        if_vals = scored["if_score"].dropna()
        assert len(if_vals) == len(scored), "if_score should not have NaN values"
        assert (if_vals >= 0).all() and (if_vals <= 1).all()

        # rule_score in [0, 1]
        assert (scored["rule_score"] >= 0).all()
        assert (scored["rule_score"] <= 1).all()

        # anomaly_score in [0, 1]
        assert (scored["anomaly_score"] >= 0).all()
        assert (scored["anomaly_score"] <= 1).all()

        # is_anomaly should be 0 or 1
        assert set(scored["is_anomaly"].unique()).issubset({0, 1})

    def test_score_group_multi_series(
        self, seed_df: pd.DataFrame, artifact_dir: Path
    ) -> None:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.inference.scorer import OnlineScorer

        df = TimeContextFeatures().transform(seed_df)

        scorer = OnlineScorer.from_artifacts(
            baseline_dir=str(artifact_dir),
            if_dir=str(artifact_dir),
        )

        # Score a subset (3 groups) to keep fast
        subset = df[df["account_id"] == "finops-prod-01"].copy()
        scored = scorer.score_group(subset)

        assert len(scored) == len(subset)
        assert "anomaly_score" in scored.columns
        assert (scored["anomaly_score"] >= 0).all()
        assert (scored["anomaly_score"] <= 1).all()

    def test_normal_data_mostly_not_anomalous(
        self, seed_df: pd.DataFrame, artifact_dir: Path
    ) -> None:
        """Training data is normal — the ensemble should flag < 30 % as anomalous."""
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.inference.scorer import OnlineScorer

        df = TimeContextFeatures().transform(seed_df)

        scorer = OnlineScorer.from_artifacts(
            baseline_dir=str(artifact_dir),
            if_dir=str(artifact_dir),
        )

        group = df[
            (df["account_id"] == "finops-prod-01")
            & (df["service"] == "Compute Engine")
            & (df["region"] == "us-central1")
        ].sort_values("bucket").copy()

        scored = scorer.score(group)
        anomaly_rate = scored["is_anomaly"].mean()
        assert anomaly_rate < 0.30, (
            f"Anomaly rate on normal training data is too high: {anomaly_rate:.2%}. "
            "The model may not have learned the patterns correctly."
        )


# ---------------------------------------------------------------------------
# 5. Anomaly injection — model should detect obvious spikes
# ---------------------------------------------------------------------------


class TestAnomalyDetection:
    def test_spike_raises_anomaly_score(
        self, seed_df: pd.DataFrame, artifact_dir: Path
    ) -> None:
        """Inject a 10× cost spike and verify the model flags it."""
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.inference.scorer import OnlineScorer

        df = TimeContextFeatures().transform(seed_df)

        scorer = OnlineScorer.from_artifacts(
            baseline_dir=str(artifact_dir),
            if_dir=str(artifact_dir),
        )

        group = df[
            (df["account_id"] == "finops-prod-01")
            & (df["service"] == "Compute Engine")
            & (df["region"] == "us-central1")
        ].sort_values("bucket").copy()

        # Inject a spike at the last 5 rows
        spike_idx = group.index[-5:]
        normal_mean = group["total_cost"].mean()
        group.loc[spike_idx, "total_cost"] = normal_mean * 10

        scored = scorer.score(group)

        # The spiked rows should have notably higher anomaly scores
        spike_scores = scored.loc[spike_idx, "anomaly_score"]
        normal_scores = scored.drop(spike_idx)["anomaly_score"]

        avg_spike = spike_scores.mean()
        avg_normal = normal_scores.mean()

        assert avg_spike > avg_normal, (
            f"Spike avg score ({avg_spike:.3f}) should exceed "
            f"normal avg score ({avg_normal:.3f})"
        )

        # At least some spiked rows should be flagged
        spike_flagged = scored.loc[spike_idx, "is_anomaly"].sum()
        assert spike_flagged >= 1, "At least 1 of 5 spiked rows should be flagged as anomaly"
