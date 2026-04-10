"""
FEA-04: Time-context features (hour / day).

Adds calendar and cyclical encoding columns to a FeatureFrame produced by
RollingWindowExtractor (FEA-01).  These features give ML and rule models
awareness of *when* a cost spike is occurring — a 3× jump at 03:00 UTC on a
Sunday is far more suspicious than the same jump at 14:00 on a Monday.

Produced columns:
    hour_of_day         – integer 0-23
    day_of_week         – integer 0 (Mon) – 6 (Sun)
    day_of_month        – integer 1-31
    month               – integer 1-12
    is_weekend          – 1 if Sat/Sun, else 0
    is_business_hour    – 1 if Mon-Fri 09:00-17:00 UTC, else 0
    hour_sin / hour_cos – cyclical encoding of hour (period = 24)
    dow_sin  / dow_cos  – cyclical encoding of day-of-week (period = 7)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .extractor import FeatureFrame


@dataclass
class TimeContextConfig:
    """
    Parameters
    ----------
    bucket_col:
        Name of the datetime column (default: "bucket").
    business_hour_start:
        Start of business hours in UTC (inclusive, default: 9).
    business_hour_end:
        End of business hours in UTC (exclusive, default: 17).
    tz:
        Timezone to interpret the bucket in before extracting calendar fields.
        Costs are usually logged in UTC; change only if the source is local.
    """

    bucket_col: str = "bucket"
    business_hour_start: int = 9
    business_hour_end: int = 17
    tz: str = "UTC"


class TimeContextFeatures:
    """
    Attaches time-context feature columns to a FeatureFrame.

    Usage
    -----
    from ml.src.features import RollingWindowExtractor
    from ml.src.features.time_context import TimeContextFeatures

    df = RollingWindowExtractor().transform_group(df_1min_agg)
    df = TimeContextFeatures().transform(df)
    """

    def __init__(self, config: TimeContextConfig | None = None) -> None:
        self.config = config or TimeContextConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: FeatureFrame) -> FeatureFrame:
        col = self.config.bucket_col
        if col not in df.columns:
            raise ValueError(
                f"bucket_col '{col}' not found in DataFrame. "
                "Ensure the 1-minute aggregate table includes a 'bucket' column."
            )
        result = df.copy()
        dt = self._as_datetime(result[col])
        result = self._calendar_fields(result, dt)
        result = self._binary_flags(result, dt)
        result = self._cyclical_encoding(result, dt)
        return result

    def feature_columns(self) -> list[str]:
        return [
            "hour_of_day",
            "day_of_week",
            "day_of_month",
            "month",
            "is_weekend",
            "is_business_hour",
            "hour_sin",
            "hour_cos",
            "dow_sin",
            "dow_cos",
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _as_datetime(self, series: pd.Series) -> pd.Series:
        """Coerce to DatetimeTZDtype in the configured timezone."""
        if not pd.api.types.is_datetime64_any_dtype(series):
            series = pd.to_datetime(series, utc=True)
        if series.dt.tz is None:
            series = series.dt.tz_localize(self.config.tz)
        else:
            series = series.dt.tz_convert(self.config.tz)
        return series

    def _calendar_fields(self, df: pd.DataFrame, dt: pd.Series) -> pd.DataFrame:
        """Raw calendar integers — interpretable by rule engine and tree models."""
        df["hour_of_day"]  = dt.dt.hour.astype("int8")
        df["day_of_week"]  = dt.dt.dayofweek.astype("int8")   # 0=Mon … 6=Sun
        df["day_of_month"] = dt.dt.day.astype("int8")
        df["month"]        = dt.dt.month.astype("int8")
        return df

    def _binary_flags(self, df: pd.DataFrame, dt: pd.Series) -> pd.DataFrame:
        """Boolean indicators useful for rule-based thresholds."""
        dow = dt.dt.dayofweek
        hour = dt.dt.hour

        df["is_weekend"] = (dow >= 5).astype("int8")

        bh_start = self.config.business_hour_start
        bh_end   = self.config.business_hour_end
        df["is_business_hour"] = (
            (dow < 5) & (hour >= bh_start) & (hour < bh_end)
        ).astype("int8")

        return df

    def _cyclical_encoding(self, df: pd.DataFrame, dt: pd.Series) -> pd.DataFrame:
        """
        Sine/cosine encoding so that distance-based models (e.g. Isolation
        Forest) treat hour 23 as close to hour 0, and Sunday as close to
        Monday.
        """
        hour = dt.dt.hour.astype(float)
        dow  = dt.dt.dayofweek.astype(float)

        df["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        df["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        df["dow_sin"]  = np.sin(2 * np.pi * dow  / 7)
        df["dow_cos"]  = np.cos(2 * np.pi * dow  / 7)

        return df
