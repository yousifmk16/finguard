"""
FEA-03: Volatility features.

Adds rolling dispersion and spread columns to a FeatureFrame produced by
RollingWindowExtractor (FEA-01).  Volatility features capture *how erratic*
cost behaviour is inside a window, complementing the level/trend signals from
FEA-01 and FEA-02.

Produced columns (per configured window):
    {col}_cv_{window}           – coefficient of variation  (std / mean)
    {col}_range_{window}        – rolling max − rolling min
    {col}_iqr_{window}          – interquartile range (Q75 − Q25)
    {col}_bb_width_{window}     – Bollinger Band width  (4 × std / mean)
    {col}_hist_vol_{window}     – annualised historical volatility of log-returns
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from .extractor import FeatureFrame


@dataclass
class VolatilityConfig:
    """
    Parameters
    ----------
    windows:
        Rolling window sizes in minutes (must include the ones used by FEA-01
        if you want to reuse pre-computed mean/std columns).
    target_col:
        Column to measure dispersion on (default: "total_cost").
    min_periods:
        Minimum non-null observations required in a window before a value is
        emitted instead of NaN.
    minutes_per_year:
        Annualisation constant for historical volatility (525 600 = 60×24×365).
    """

    windows: List[int] = field(default_factory=lambda: [5, 15, 60])
    target_col: str = "total_cost"
    min_periods: int = 2          # need ≥2 points for std
    minutes_per_year: int = 525_600


class VolatilityFeatures:
    """
    Attaches volatility feature columns to a FeatureFrame.

    Usage
    -----
    from ml.src.features import RollingWindowExtractor, GrowthRateFeatures
    from ml.src.features.volatility import VolatilityFeatures

    df = RollingWindowExtractor().transform_group(df_1min_agg)
    df = GrowthRateFeatures().transform(df)   # FEA-02 log-returns needed for hist_vol
    df = VolatilityFeatures().transform(df)
    """

    def __init__(self, config: VolatilityConfig | None = None) -> None:
        self.config = config or VolatilityConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: FeatureFrame) -> FeatureFrame:
        col = self.config.target_col
        if col not in df.columns:
            raise ValueError(
                f"target_col '{col}' not found. "
                "Run RollingWindowExtractor.transform() first."
            )
        result = df.copy()
        result = self._coefficient_of_variation(result)
        result = self._rolling_range(result)
        result = self._rolling_iqr(result)
        result = self._bollinger_width(result)
        result = self._historical_volatility(result)
        return result

    def feature_columns(self) -> list[str]:
        col = self.config.target_col
        cols: list[str] = []
        for w in self.config.windows:
            cols.append(f"{col}_cv_{w}")
            cols.append(f"{col}_range_{w}")
            cols.append(f"{col}_iqr_{w}")
            cols.append(f"{col}_bb_width_{w}")
            cols.append(f"{col}_hist_vol_{w}")
        return cols

    # ------------------------------------------------------------------
    # Feature builders
    # ------------------------------------------------------------------

    def _coefficient_of_variation(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        CV = std / mean  (dimensionless relative dispersion).

        High CV means costs are all over the place relative to the average —
        useful for flagging noisy services even when the absolute level is low.
        NaN when mean == 0.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            roll = series.rolling(window=w, min_periods=self.config.min_periods)
            mean = roll.mean().replace(0.0, np.nan)
            std  = roll.std()
            df[f"{col}_cv_{w}"] = std / mean

        return df

    def _rolling_range(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Range = rolling_max − rolling_min.

        Reuses pre-computed columns from FEA-01 when available to avoid
        redundant passes over the data.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            max_col = f"{col}_roll{w}_max"
            min_col = f"{col}_roll{w}_min"

            if max_col in df.columns and min_col in df.columns:
                df[f"{col}_range_{w}"] = df[max_col] - df[min_col]
            else:
                roll = series.rolling(window=w, min_periods=self.config.min_periods)
                df[f"{col}_range_{w}"] = roll.max() - roll.min()

        return df

    def _rolling_iqr(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        IQR = Q75 − Q25 over the rolling window.

        More robust than range against single extreme outliers; useful as a
        complement to std when the distribution is skewed.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            q75 = series.rolling(window=w, min_periods=self.config.min_periods).quantile(0.75)
            q25 = series.rolling(window=w, min_periods=self.config.min_periods).quantile(0.25)
            df[f"{col}_iqr_{w}"] = q75 - q25

        return df

    def _bollinger_width(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bollinger Band width = 4 × std / mean  (i.e. upper − lower band,
        normalised by the mean so it's comparable across cost scales).

        A widening band signals increasing volatility — often precedes
        a detected anomaly by 1–3 periods, making it a useful leading indicator
        for ENS-01.
        """
        col = self.config.target_col
        series = df[col].astype(float)

        for w in self.config.windows:
            std_col  = f"{col}_roll{w}_std"
            mean_col = f"{col}_roll{w}_mean"

            if std_col in df.columns and mean_col in df.columns:
                std  = df[std_col]
                mean = df[mean_col].replace(0.0, np.nan)
            else:
                roll = series.rolling(window=w, min_periods=self.config.min_periods)
                std  = roll.std()
                mean = roll.mean().replace(0.0, np.nan)

            df[f"{col}_bb_width_{w}"] = (4.0 * std) / mean

        return df

    def _historical_volatility(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Annualised historical volatility = std(log_returns) × sqrt(minutes_per_year / window).

        Reuses FEA-02 log_return_1 when available; falls back to computing
        log-returns inline.
        """
        col = self.config.target_col
        log_ret_col = f"{col}_log_return_1"

        if log_ret_col in df.columns:
            log_returns = df[log_ret_col].astype(float)
        else:
            series = df[col].astype(float).clip(lower=1e-9)
            log_returns = np.log(series / series.shift(1))

        mpy = self.config.minutes_per_year

        for w in self.config.windows:
            roll_std = log_returns.rolling(
                window=w, min_periods=self.config.min_periods
            ).std()
            annualisation = np.sqrt(mpy / w)
            df[f"{col}_hist_vol_{w}"] = roll_std * annualisation

        return df
