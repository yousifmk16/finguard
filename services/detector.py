"""
Legacy rolling-MAD anomaly detector.

Uses Median Absolute Deviation over a rolling window to flag cost outliers.
Kept as a lightweight standalone alternative to the full OnlineScorer pipeline
(ml/src/inference/scorer.py).
"""

import numpy as np
import pandas as pd


class AnomalyDetector:
    def __init__(self, threshold: float = 3.0) -> None:
        self.threshold = threshold

    def detect_rolling_mad(self, df: pd.DataFrame, window: int = 7) -> pd.DataFrame:
        """Flag anomalies based on rolling median absolute deviation.

        Adds columns ``median``, ``deviation``, ``mad``, and ``is_anomaly``
        to the input DataFrame.
        """
        df["median"] = df["cost_amount"].rolling(window=window, center=True).median()
        df["deviation"] = np.abs(df["cost_amount"] - df["median"])
        df["mad"] = df["deviation"].rolling(window=window, center=True).median()
        df["is_anomaly"] = df["deviation"] > (self.threshold * df["mad"])
        return df
