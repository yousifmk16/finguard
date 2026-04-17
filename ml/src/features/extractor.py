"""
FEA-01: Rolling window feature extractor.

Consumes a pandas DataFrame whose rows correspond to 1-minute aggregates
(DB-02) and produces a feature DataFrame ready for:
  - TS-01  (time-series baseline model)
  - ML-01  (Isolation Forest)
  - RUL-*  (rule engine — via the raw window values)

Expected input columns (matches DB-02 schema):
    bucket          datetime64[ns, UTC]  – 1-minute time bucket
    account_id      str
    service         str
    region          str
    total_cost      float
    total_usage     float
    event_count     int

FEA-02, FEA-03, and FEA-04 import this module and call
`extractor.add_*` helpers to attach their own feature columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, TypeAlias

import numpy as np
import pandas as pd

# A DataFrame that has already been feature-engineered
FeatureFrame: TypeAlias = pd.DataFrame


@dataclass
class WindowConfig:
    """
    Configures which rolling windows (in minutes) are computed and which
    aggregate functions are applied per window.

    Attributes
    ----------
    windows:
        List of window sizes in *minutes* (number of 1-min rows to include).
    agg_funcs:
        Aggregate functions applied to `total_cost` within each window.
        Supported: "mean", "std", "min", "max", "sum".
    target_col:
        Primary numeric column to roll over (default: "total_cost").
    min_periods:
        Minimum non-null rows required in a window; shorter windows produce
        NaN rather than a potentially misleading statistic.
    """

    windows: List[int] = field(default_factory=lambda: [5, 15, 60])
    agg_funcs: List[str] = field(
        default_factory=lambda: ["mean", "std", "min", "max", "sum"]
    )
    target_col: str = "total_cost"
    min_periods: int = 1


class RollingWindowExtractor:
    """
    Builds a feature matrix from 1-minute billing aggregate rows.

    Usage
    -----
    extractor = RollingWindowExtractor(WindowConfig())
    features  = extractor.transform(df_1min_agg)

    The returned DataFrame keeps all original columns and appends one column
    per (window, agg_func) combination, e.g.:
        cost_roll5_mean, cost_roll5_std, …, cost_roll60_sum
    plus a z-score column per window:
        cost_roll5_zscore, cost_roll15_zscore, cost_roll60_zscore
    """

    # Supported aggregation functions mapped to pandas rolling methods
    _SUPPORTED_AGGS = {"mean", "std", "min", "max", "sum"}

    def __init__(self, config: WindowConfig | None = None) -> None:
        self.config = config or WindowConfig()
        unknown = set(self.config.agg_funcs) - self._SUPPORTED_AGGS
        if unknown:
            raise ValueError(
                f"Unsupported agg_funcs: {unknown}. "
                f"Choose from {self._SUPPORTED_AGGS}."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: pd.DataFrame) -> FeatureFrame:
        """
        Parameters
        ----------
        df:
            1-minute aggregate DataFrame sorted by (account_id, service,
            region, bucket) ascending.  The caller is responsible for
            sorting and grouping; call `transform_group` to handle
            multi-series DataFrames automatically.

        Returns
        -------
        FeatureFrame with original columns plus rolling feature columns.
        """
        self._validate_input(df)
        result = df.copy()
        result = self._compute_rolling_features(result)
        result = self._compute_zscores(result)
        return result

    def transform_group(self, df: pd.DataFrame) -> FeatureFrame:
        """
        Convenience method for DataFrames that contain multiple
        (account_id, service, region) time series.  Features are computed
        independently per group so that one series does not bleed into
        another.
        """
        self._validate_input(df)
        group_keys = ["account_id", "service", "region"]
        present_keys = [k for k in group_keys if k in df.columns]

        if not present_keys:
            return self.transform(df.sort_values("bucket"))

        parts = []
        sorted_df = df.sort_values(present_keys + ["bucket"])
        for _, group_df in sorted_df.groupby(present_keys, sort=False):
            parts.append(self.transform(group_df))
        return pd.concat(parts, ignore_index=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_input(self, df: pd.DataFrame) -> None:
        required = {"bucket", self.config.target_col}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Input DataFrame missing columns: {missing}")
        if df.empty:
            raise ValueError("Input DataFrame is empty.")

    def _compute_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            rolled = series.rolling(window=w, min_periods=self.config.min_periods)
            for agg in self.config.agg_funcs:
                feature_name = f"{col}_roll{w}_{agg}"
                df[feature_name] = getattr(rolled, agg)()

        return df

    def _compute_zscores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Z-score of the current value relative to the rolling mean and std.
        A large |z-score| is the primary signal used by RUL-01 / TS-03.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            mean_col = f"{col}_roll{w}_mean"
            std_col = f"{col}_roll{w}_std"

            if mean_col not in df.columns or std_col not in df.columns:
                continue

            zscore_col = f"{col}_roll{w}_zscore"
            std = df[std_col].replace(0.0, np.nan)
            df[zscore_col] = (series - df[mean_col]) / std

        return df

    # ------------------------------------------------------------------
    # Accessors used by downstream modules (FEA-02 / FEA-03 / FEA-04)
    # ------------------------------------------------------------------

    def feature_columns(self) -> list[str]:
        """Returns the list of column names this extractor will produce."""
        col = self.config.target_col
        has_zscore = "mean" in self.config.agg_funcs and "std" in self.config.agg_funcs
        cols: list[str] = []
        for w in self.config.windows:
            for agg in self.config.agg_funcs:
                cols.append(f"{col}_roll{w}_{agg}")
            if has_zscore:
                cols.append(f"{col}_roll{w}_zscore")
        return cols

    def window_values(self, df: pd.DataFrame, window: int) -> pd.Series:
        """
        Returns the raw `target_col` series sliced to the last `window` rows.
        Used by RUL-02 (SuddenJumpRule) and RUL-03 (SustainedIncreaseRule)
        to access the underlying cost values directly.
        """
        return df[self.config.target_col].iloc[-window:].astype(float)
