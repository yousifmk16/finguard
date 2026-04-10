"""
FEA-02: Growth-rate features.

Adds period-over-period and rolling compound growth-rate columns to a
FeatureFrame produced by RollingWindowExtractor (FEA-01).

Produced columns (per configured lag / window):
    {col}_pct_change_{lag}      – simple % change vs `lag` periods ago
    {col}_log_return_{lag}      – log return vs `lag` periods ago
    {col}_cagr_{window}         – compound annual growth rate over `window` mins
    {col}_accel                 – acceleration: change in the 1-period pct change
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from .extractor import FeatureFrame


@dataclass
class GrowthRateConfig:
    """
    Parameters
    ----------
    lags:
        Periods-back for simple pct-change and log-return (default: 1, 5, 15).
    cagr_windows:
        Window sizes (in minutes) over which CAGR is annualised.
        Must be a subset of WindowConfig.windows in FEA-01 if you want the
        rolling-mean column to already exist; otherwise raw values are used.
    target_col:
        Column to differentiate (default: "total_cost").
    minutes_per_year:
        Annualisation constant: 60 min × 24 h × 365 d = 525 600.
    """

    lags: List[int] = field(default_factory=lambda: [1, 5, 15])
    cagr_windows: List[int] = field(default_factory=lambda: [5, 15, 60])
    target_col: str = "total_cost"
    minutes_per_year: int = 525_600


class GrowthRateFeatures:
    """
    Attaches growth-rate feature columns to a FeatureFrame in-place.

    Usage
    -----
    from ml.src.features.extractor import RollingWindowExtractor
    from ml.src.features.growth_rate import GrowthRateFeatures

    df = RollingWindowExtractor().transform(df_1min_agg)
    df = GrowthRateFeatures().transform(df)
    """

    def __init__(self, config: GrowthRateConfig | None = None) -> None:
        self.config = config or GrowthRateConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: FeatureFrame) -> FeatureFrame:
        """
        Appends growth-rate columns to *df* and returns it.

        Parameters
        ----------
        df:
            Output of RollingWindowExtractor.transform() / transform_group().
            Must contain `target_col` and be sorted ascending by time within
            each (account_id, service, region) group.
        """
        col = self.config.target_col
        if col not in df.columns:
            raise ValueError(
                f"target_col '{col}' not found. "
                "Run RollingWindowExtractor.transform() first."
            )
        result = df.copy()
        result = self._pct_change(result)
        result = self._log_return(result)
        result = self._cagr(result)
        result = self._acceleration(result)
        return result

    def feature_columns(self) -> list[str]:
        """Lists every column name this class will produce."""
        col = self.config.target_col
        cols: list[str] = []
        for lag in self.config.lags:
            cols.append(f"{col}_pct_change_{lag}")
            cols.append(f"{col}_log_return_{lag}")
        for w in self.config.cagr_windows:
            cols.append(f"{col}_cagr_{w}")
        cols.append(f"{col}_accel")
        return cols

    # ------------------------------------------------------------------
    # Feature builders
    # ------------------------------------------------------------------

    def _pct_change(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Simple percentage change vs `lag` periods ago.

            pct_change = (current - prev) / |prev|

        NaN when prev == 0 to avoid division-by-zero; clipped to [-5, 5]
        (±500 %) so extreme injected anomalies don't distort the feature space.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for lag in self.config.lags:
            prev = series.shift(lag)
            pct = (series - prev) / prev.abs().replace(0.0, np.nan)
            df[f"{col}_pct_change_{lag}"] = pct.clip(-5.0, 5.0)

        return df

    def _log_return(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Logarithmic return vs `lag` periods ago.

            log_return = ln(current / prev)

        Log returns are additive, symmetric, and better-behaved than simple
        pct changes for downstream ML models.  NaN when either value ≤ 0.
        """
        col = self.config.target_col
        series = df[col].astype(float).clip(lower=1e-9)  # guard against log(0)

        for lag in self.config.lags:
            prev = series.shift(lag).clip(lower=1e-9)
            df[f"{col}_log_return_{lag}"] = np.log(series / prev)

        return df

    def _cagr(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compound Annual Growth Rate over a rolling `window` of minutes.

            CAGR = (end / start) ^ (minutes_per_year / window) - 1

        Uses the raw target_col value at the start and end of each window.
        Clipped to [-10, 10] (±1 000 %) for the same stability reason as pct.
        """
        col = self.config.target_col
        series = df[col].astype(float).clip(lower=1e-9)
        mpy = self.config.minutes_per_year

        for w in self.config.cagr_windows:
            start = series.shift(w).clip(lower=1e-9)
            exponent = mpy / w
            cagr = (series / start) ** exponent - 1.0
            df[f"{col}_cagr_{w}"] = cagr.clip(-10.0, 10.0)

        return df

    def _acceleration(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Acceleration: second-order difference of the 1-period pct-change.

            accel = pct_change[t] - pct_change[t-1]

        A large positive acceleration signals a cost that is *speeding up*
        its growth — a strong signal for ENS-01 / RUL-03 (sustained increase).
        Requires _pct_change() to have already been called.
        """
        col = self.config.target_col
        pct1_col = f"{col}_pct_change_1"

        if pct1_col not in df.columns:
            # fallback: compute on the spot from raw series
            series = df[col].astype(float)
            prev = series.shift(1)
            pct1 = (series - prev) / prev.abs().replace(0.0, np.nan)
        else:
            pct1 = df[pct1_col]

        df[f"{col}_accel"] = pct1.diff(1)
        return df
