"""
TS-01 / TS-02: Time-series baseline model with confidence interval output.

Learns a seasonal profile (per hour-of-day × day-of-week bucket) from
historical 1-minute aggregate data and produces a per-row expected-value
forecast together with symmetric Gaussian confidence intervals.

Output feeds directly into:
  - TS-03  (residual / z-score computation)
  - ENS-01 (weighted score fusion)

Model architecture — deliberately minimal ("baseline"):
  1. Seasonal profile:  mean and std of `target_col` per (hour_of_day,
     day_of_week) bucket, estimated on the training set.
  2. EWMA smoothing:    an exponentially weighted moving average of the
     target column, computed per (account_id, service, region) group during
     inference to capture recent trend on top of the seasonal profile.
  3. Combined forecast: weighted blend of the seasonal mean and the EWMA.

Confidence intervals (TS-02):
  For each configured confidence level α (e.g. 0.95) the predict output
  includes two extra columns:
      ci_lower_<pct>  – lower bound  (e.g. ci_lower_95)
      ci_upper_<pct>  – upper bound  (e.g. ci_upper_95)

  Bounds are computed as:
      ci_lower = max(0, forecast_mean - z_α * forecast_std)
      ci_upper = forecast_mean + z_α * forecast_std

  where z_α = Φ⁻¹((1 + α) / 2) from the standard normal distribution
  (e.g. 1.96 for α = 0.95).  Costs are clipped at 0 since negative spend
  is not meaningful.

Expected input columns (produced by FEA-01 + FEA-04, or raw DB-02):
    bucket          datetime64[ns, UTC]
    account_id      str
    service         str
    region          str
    total_cost      float          (or whatever target_col is set to)
    hour_of_day     int8           (from FEA-04, or computed internally)
    day_of_week     int8           (from FEA-04, or computed internally)

Artifacts stored by `save()` / loaded by `load()`:
    <artifact_dir>/baseline_seasonal_profile.json
    <artifact_dir>/baseline_config.json
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ml.src.features.extractor import FeatureFrame

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEASONAL_KEY = ("hour_of_day", "day_of_week")
_FALLBACK_STD = 1e-6  # used when a seasonal bucket has a single training point


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BaselineConfig:
    """
    Hyper-parameters for the time-series baseline model.

    Attributes
    ----------
    target_col:
        Column to forecast (default: "total_cost").
    ewma_alpha:
        Decay factor for the EWMA trend component (0 < alpha ≤ 1).
        Higher alpha makes the trend react faster to recent data.
    seasonal_weight:
        How much to blend the seasonal profile into the forecast.
        forecast = seasonal_weight * seasonal_mean
                 + (1 - seasonal_weight) * ewma_value
        Set to 1.0 to use a pure seasonal model (no trend smoothing).
    min_train_rows:
        Minimum rows required in the training set before fitting.
        Raises ValueError if the training data is smaller.
    group_cols:
        Columns used to identify independent time series when calling
        `fit_group` / `predict_group`.
    bucket_col:
        Name of the datetime bucket column.
    artifact_dir:
        Default directory for `save()` / `load()`.
    confidence_levels:
        List of confidence levels for interval output (TS-02).
        Each value α must satisfy 0 < α < 1.  Common choices:
        0.90, 0.95, 0.99.  Column names in the predict output are
        ``ci_lower_<pct>`` and ``ci_upper_<pct>`` where ``<pct>`` is
        the integer percentage (e.g. 95 for α = 0.95).
        Pass an empty list to suppress CI output entirely.
    """

    target_col: str = "total_cost"
    ewma_alpha: float = 0.3
    seasonal_weight: float = 0.6
    min_train_rows: int = 60
    group_cols: List[str] = field(
        default_factory=lambda: ["account_id", "service", "region"]
    )
    bucket_col: str = "bucket"
    artifact_dir: str = "ml/artifacts"
    # TS-02: one or more confidence levels (e.g. [0.90, 0.95, 0.99]).
    # Each level produces ci_lower_<pct> / ci_upper_<pct> columns in
    # the predict output.  Set to [] to suppress CI columns entirely.
    confidence_levels: List[float] = field(default_factory=lambda: [0.95])


# ---------------------------------------------------------------------------
# Seasonal profile (pure data, JSON-serialisable)
# ---------------------------------------------------------------------------


@dataclass
class SeasonalProfile:
    """
    Lookup table: (hour_of_day, day_of_week) → (mean, std, count).

    Keys are stored as comma-joined strings ("14,2") so they survive a
    JSON round-trip without requiring tuple keys.
    """

    means: Dict[str, float] = field(default_factory=dict)
    stds: Dict[str, float] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    global_mean: float = 0.0
    global_std: float = 1.0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SeasonalProfile":
        return cls(**d)

    # ------------------------------------------------------------------
    # Look-up helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(hour: int, dow: int) -> str:
        return f"{int(hour)},{int(dow)}"

    def get_mean(self, hour: int, dow: int) -> float:
        return self.means.get(self._key(hour, dow), self.global_mean)

    def get_std(self, hour: int, dow: int) -> float:
        return self.stds.get(self._key(hour, dow), self.global_std)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class TimeSeriesBaselineModel:
    """
    Fits a seasonal baseline model and produces per-row forecasts.

    Usage — training
    ----------------
    from ml.src.models.baseline import TimeSeriesBaselineModel, BaselineConfig

    model = TimeSeriesBaselineModel(BaselineConfig())
    model.fit(df_historical)          # single series
    model.fit_group(df_historical)    # multiple series, grouped automatically

    Usage — inference
    -----------------
    forecast_df = model.predict(df_current)
    # forecast_df columns: forecast_mean, forecast_std,
    #                       ci_lower_95, ci_upper_95  (per configured level)

    Usage — persistence
    -------------------
    model.save("ml/artifacts")
    model2 = TimeSeriesBaselineModel.load("ml/artifacts")
    """

    def __init__(self, config: BaselineConfig | None = None) -> None:
        self.config = config or BaselineConfig()
        self._profile: Optional[SeasonalProfile] = None
        self._fitted: bool = False

    # ------------------------------------------------------------------
    # Fit
    # ------------------------------------------------------------------

    def fit(self, df: pd.DataFrame) -> "TimeSeriesBaselineModel":
        """
        Learn seasonal statistics from a single sorted time series.

        Parameters
        ----------
        df:
            Historical 1-minute aggregate rows for one (account, service,
            region) combination, sorted ascending by bucket.
            Must contain `target_col` and either `hour_of_day` /
            `day_of_week` columns (FEA-04) or a parseable `bucket_col`.
        """
        self._validate_train(df)
        df_work = self._ensure_time_context(df)
        self._profile = self._build_profile(df_work)
        self._fitted = True
        return self

    def fit_group(self, df: pd.DataFrame) -> "TimeSeriesBaselineModel":
        """
        Learn seasonal statistics from a DataFrame that contains multiple
        (account_id, service, region) series.  Statistics are pooled across
        all groups to produce a single shared seasonal profile.

        This is the recommended method when you have training data from
        many services and want a single deployable model artifact.
        """
        self._validate_train(df)
        df_work = self._ensure_time_context(df)
        self._profile = self._build_profile(df_work)
        self._fitted = True
        return self

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Produce per-row forecasts for a *single* time series.

        Returns
        -------
        pd.DataFrame with columns:
            forecast_mean       – blended seasonal + EWMA expected value
            forecast_std        – expected standard deviation
            ci_lower_<pct>      – lower bound of confidence interval (TS-02)
            ci_upper_<pct>      – upper bound of confidence interval (TS-02)

        One ci_lower / ci_upper pair is emitted per entry in
        ``BaselineConfig.confidence_levels``.  The returned DataFrame has
        the same index as `df`.
        """
        self._check_fitted()
        df_work = self._ensure_time_context(df)
        return self._make_forecast(df_work)

    def predict_group(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Produce forecasts for a multi-series DataFrame.  EWMA smoothing is
        applied independently per (account_id, service, region) group so
        that different services don't bleed into each other's trend.

        Returns
        -------
        pd.DataFrame with the same index as `df` plus columns:
            forecast_mean, forecast_std, ci_lower_<pct>, ci_upper_<pct>
        """
        self._check_fitted()
        df_work = self._ensure_time_context(df)
        group_keys = [k for k in self.config.group_cols if k in df_work.columns]

        if not group_keys:
            return self._make_forecast(df_work)

        results: List[pd.DataFrame] = []
        for _, group in df_work.groupby(group_keys, sort=False):
            group_sorted = group.sort_values(self.config.bucket_col)
            forecast = self._make_forecast(group_sorted)
            results.append(forecast)

        return pd.concat(results).reindex(df.index)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, artifact_dir: str | None = None) -> Path:
        """
        Persist the fitted model to JSON files.

        Files written
        -------------
        <artifact_dir>/baseline_seasonal_profile.json
        <artifact_dir>/baseline_config.json

        Note
        ----
        For versioned saves (TS-05), use ModelVersionRegistry.register()
        instead of calling this method directly.  The registry calls
        save() internally and wraps it with version tagging, manifest
        tracking, and latest-snapshot management.

        Returns
        -------
        Path to the artifact directory.
        """
        self._check_fitted()
        out_dir = Path(artifact_dir or self.config.artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        profile_path = out_dir / "baseline_seasonal_profile.json"
        config_path = out_dir / "baseline_config.json"

        with profile_path.open("w") as f:
            json.dump(self._profile.to_dict(), f, indent=2)

        with config_path.open("w") as f:
            json.dump(asdict(self.config), f, indent=2)

        return out_dir

    @classmethod
    def load(cls, artifact_dir: str) -> "TimeSeriesBaselineModel":
        """
        Restore a previously saved model.

        Parameters
        ----------
        artifact_dir:
            Directory that contains ``baseline_seasonal_profile.json`` and
            ``baseline_config.json``.
        """
        in_dir = Path(artifact_dir)
        profile_path = in_dir / "baseline_seasonal_profile.json"
        config_path = in_dir / "baseline_config.json"

        if not profile_path.exists():
            raise FileNotFoundError(
                f"Seasonal profile not found at {profile_path}. "
                "Run TimeSeriesBaselineModel.fit() and .save() first."
            )

        with profile_path.open() as f:
            profile = SeasonalProfile.from_dict(json.load(f))

        config = BaselineConfig()
        if config_path.exists():
            with config_path.open() as f:
                config = BaselineConfig(**json.load(f))

        model = cls(config)
        model._profile = profile
        model._fitted = True
        return model

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    @property
    def profile(self) -> Optional[SeasonalProfile]:
        """Exposes the seasonal profile for inspection / TS-05 versioning."""
        return self._profile

    # ------------------------------------------------------------------
    # Internal: profile fitting
    # ------------------------------------------------------------------

    def _build_profile(self, df: pd.DataFrame) -> SeasonalProfile:
        """
        Compute mean and std of target_col for each (hour_of_day,
        day_of_week) bucket.  Unknown buckets at inference time fall back
        to global statistics.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        global_mean = float(series.mean())
        global_std = float(series.std(ddof=1)) if len(series) > 1 else _FALLBACK_STD
        if np.isnan(global_std) or global_std == 0.0:
            global_std = _FALLBACK_STD

        profile = SeasonalProfile(global_mean=global_mean, global_std=global_std)

        grouped = df.groupby(["hour_of_day", "day_of_week"])[col]
        for (hour, dow), bucket_vals in grouped:
            key = SeasonalProfile._key(hour, dow)
            vals = bucket_vals.astype(float).dropna()
            n = len(vals)
            profile.means[key] = float(vals.mean()) if n >= 1 else global_mean
            profile.stds[key] = (
                float(vals.std(ddof=1)) if n >= 2 else global_std
            )
            if np.isnan(profile.stds[key]) or profile.stds[key] == 0.0:
                profile.stds[key] = _FALLBACK_STD
            profile.counts[key] = n

        return profile

    # ------------------------------------------------------------------
    # Internal: forecast generation
    # ------------------------------------------------------------------

    def _make_forecast(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Blend seasonal profile with EWMA trend to produce forecast_mean,
        forecast_std, and per-level confidence interval columns (TS-02).
        """
        col = self.config.target_col
        alpha = self.config.ewma_alpha
        sw = self.config.seasonal_weight

        hours = df["hour_of_day"].astype(int)
        dows = df["day_of_week"].astype(int)

        seasonal_means = np.array(
            [self._profile.get_mean(h, d) for h, d in zip(hours, dows)],
            dtype=float,
        )
        seasonal_stds = np.array(
            [self._profile.get_std(h, d) for h, d in zip(hours, dows)],
            dtype=float,
        )

        # EWMA of the actual cost column (causal — no look-ahead)
        cost_series = df[col].astype(float)
        ewma_values = cost_series.ewm(alpha=alpha, adjust=False).mean().to_numpy()

        forecast_mean = sw * seasonal_means + (1.0 - sw) * ewma_values
        # std scales with the blend: seasonal component dominates when sw is high
        forecast_std = seasonal_stds * (sw + (1.0 - sw) * alpha)
        forecast_std = np.maximum(forecast_std, _FALLBACK_STD)

        result = pd.DataFrame(
            {"forecast_mean": forecast_mean, "forecast_std": forecast_std},
            index=df.index,
        )

        # TS-02 — confidence interval columns
        _normal = NormalDist()
        for level in self.config.confidence_levels:
            if not (0.0 < level < 1.0):
                raise ValueError(
                    f"confidence_levels entries must be in (0, 1); got {level}."
                )
            z = _normal.inv_cdf((1.0 + level) / 2.0)
            pct = int(round(level * 100))
            half_width = z * forecast_std
            result[f"ci_lower_{pct}"] = np.maximum(0.0, forecast_mean - half_width)
            result[f"ci_upper_{pct}"] = forecast_mean + half_width

        return result

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    def _ensure_time_context(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        If FEA-04 columns are absent, extract hour_of_day and day_of_week
        from the bucket column on the fly.
        """
        if "hour_of_day" in df.columns and "day_of_week" in df.columns:
            return df

        bucket_col = self.config.bucket_col
        if bucket_col not in df.columns:
            raise ValueError(
                f"Neither 'hour_of_day'/'day_of_week' nor '{bucket_col}' "
                "found in DataFrame. Run FEA-04 (TimeContextFeatures) or "
                f"ensure the '{bucket_col}' column is present."
            )

        warnings.warn(
            "hour_of_day / day_of_week not found. "
            "Extracting from bucket column. "
            "For best results run FEA-04 (TimeContextFeatures) first.",
            stacklevel=3,
        )

        result = df.copy()
        dt = pd.to_datetime(result[bucket_col], utc=True)
        result["hour_of_day"] = dt.dt.hour.astype("int8")
        result["day_of_week"] = dt.dt.dayofweek.astype("int8")
        return result

    def _validate_train(self, df: pd.DataFrame) -> None:
        if df.empty:
            raise ValueError("Training DataFrame is empty.")
        col = self.config.target_col
        if col not in df.columns:
            raise ValueError(
                f"target_col '{col}' not found in training DataFrame."
            )
        if len(df) < self.config.min_train_rows:
            raise ValueError(
                f"Training set has only {len(df)} rows; "
                f"need at least {self.config.min_train_rows} "
                "(adjust BaselineConfig.min_train_rows if intentional)."
            )

    def _check_fitted(self) -> None:
        if not self._fitted or self._profile is None:
            raise RuntimeError(
                "Model is not fitted. Call fit() or fit_group() first, "
                "or load a saved model with TimeSeriesBaselineModel.load()."
            )
