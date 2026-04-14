"""
TS-03: Residual and z-score computation.

Consumes the actual `target_col` values alongside the forecast output
produced by TimeSeriesBaselineModel (TS-01 / TS-02) and emits per-row
anomaly signals:

    residual        – signed difference: actual − forecast_mean
    abs_residual    – |residual|
    z_score         – residual / forecast_std  (signed)
    abs_z_score     – |z_score|  (used for threshold comparisons)
    is_outside_ci_<pct> – 1 if actual falls outside [ci_lower, ci_upper],
                          0 otherwise; one column per configured CI level

These columns are the primary inputs consumed by:
  - ENS-01  (weighted score fusion)
  - RUL-01  (threshold breach rule)
  - EXP-01  (explanation generator — forecast vs actual)

Usage
-----
from ml.src.models.residuals import ResidualScorer, ResidualConfig

scorer  = ResidualScorer()                         # uses defaults
scored  = scorer.transform(df_actuals, df_forecast)

# Or with the combined helper that runs baseline + scoring in one shot:
scored  = scorer.transform_with_baseline(model, df)

Inputs
------
df_actuals:  DataFrame containing the real observed values.
             Must include ``target_col`` (default: "total_cost").

df_forecast: Output of TimeSeriesBaselineModel.predict() /
             .predict_group().  Must include:
                 forecast_mean
                 forecast_std
             and optionally:
                 ci_lower_<pct>, ci_upper_<pct>   (from TS-02)

Both DataFrames must share the same index (or be the same object with
forecast columns already appended).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from ml.src.features.extractor import FeatureFrame

# Minimum std to guard against division-by-zero when forecast_std is 0
_MIN_STD = 1e-9


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ResidualConfig:
    """
    Parameters for residual / z-score computation.

    Attributes
    ----------
    target_col:
        Actual observed column to compare against the forecast.
    forecast_mean_col:
        Column name for the forecast mean (output of TS-01).
    forecast_std_col:
        Column name for the forecast standard deviation (output of TS-01).
    ci_levels:
        Integer percentage suffixes of CI columns to check, e.g. [95] will
        look for ``ci_lower_95`` / ``ci_upper_95`` produced by TS-02 and
        emit an ``is_outside_ci_95`` flag.  Set to [] to skip CI flags.
    clip_z_score:
        Absolute value cap applied to z_score to prevent extreme outliers
        from dominating downstream models.  Set to None for no clipping.
    """

    target_col: str = "total_cost"
    forecast_mean_col: str = "forecast_mean"
    forecast_std_col: str = "forecast_std"
    ci_levels: List[int] = field(default_factory=lambda: [95])
    clip_z_score: float | None = 10.0


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class ResidualScorer:
    """
    Adds residual and z-score columns to a feature/forecast DataFrame.

    Two calling styles are supported:

    Style 1 — separate DataFrames
    ------------------------------
    scored = ResidualScorer().transform(df_actuals, df_forecast)

    Style 2 — pre-merged DataFrame (forecast columns already present)
    ------------------------------------------------------------------
    df_merged = pd.concat([df_actuals, df_forecast], axis=1)
    scored    = ResidualScorer().transform(df_merged)

    Style 3 — combined baseline + scoring in one call
    --------------------------------------------------
    scored = ResidualScorer().transform_with_baseline(baseline_model, df)
    """

    def __init__(self, config: ResidualConfig | None = None) -> None:
        self.config = config or ResidualConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(
        self,
        df_actuals: pd.DataFrame,
        df_forecast: pd.DataFrame | None = None,
    ) -> FeatureFrame:
        """
        Compute residuals and z-scores.

        Parameters
        ----------
        df_actuals:
            DataFrame containing ``target_col``.  May already contain
            forecast columns if ``df_forecast`` is omitted.
        df_forecast:
            Optional separate forecast DataFrame (same index as
            ``df_actuals``).  When provided, its columns are joined onto
            ``df_actuals`` before scoring.

        Returns
        -------
        Copy of ``df_actuals`` (merged with ``df_forecast`` if given) with
        the following columns appended:
            residual
            abs_residual
            z_score
            abs_z_score
            is_outside_ci_<pct>   (one per entry in config.ci_levels)
        """
        df = self._merge(df_actuals, df_forecast)
        self._validate(df)
        return self._score(df)

    def transform_with_baseline(
        self,
        model: object,
        df: pd.DataFrame,
    ) -> FeatureFrame:
        """
        Convenience wrapper: runs ``model.predict(df)`` then scores.

        Parameters
        ----------
        model:
            A fitted ``TimeSeriesBaselineModel`` instance.
        df:
            Input DataFrame passed directly to ``model.predict()``.

        Returns
        -------
        ``df`` extended with forecast columns from the model AND the
        residual / z-score columns from this scorer.
        """
        forecast = model.predict(df)
        return self.transform(df, forecast)

    def output_columns(self) -> list[str]:
        """Lists every column name this scorer will produce."""
        cols = ["residual", "abs_residual", "z_score", "abs_z_score"]
        for pct in self.config.ci_levels:
            cols.append(f"is_outside_ci_{pct}")
        return cols

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _merge(
        self,
        df_actuals: pd.DataFrame,
        df_forecast: pd.DataFrame | None,
    ) -> pd.DataFrame:
        if df_forecast is None:
            return df_actuals.copy()

        overlap = df_actuals.columns.intersection(df_forecast.columns).tolist()
        if overlap:
            # keep actuals columns; bring in only new forecast columns
            new_cols = df_forecast.columns.difference(df_actuals.columns)
            return pd.concat([df_actuals, df_forecast[new_cols]], axis=1)

        return pd.concat([df_actuals, df_forecast], axis=1)

    def _validate(self, df: pd.DataFrame) -> None:
        required = {
            self.config.target_col,
            self.config.forecast_mean_col,
            self.config.forecast_std_col,
        }
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"DataFrame is missing required columns: {missing}. "
                "Ensure TimeSeriesBaselineModel.predict() output is present."
            )

        for pct in self.config.ci_levels:
            lower = f"ci_lower_{pct}"
            upper = f"ci_upper_{pct}"
            if lower not in df.columns or upper not in df.columns:
                raise ValueError(
                    f"CI columns '{lower}' / '{upper}' not found. "
                    f"Either add {pct} to BaselineConfig.confidence_levels "
                    f"(TS-02) or remove {pct} from ResidualConfig.ci_levels."
                )

    def _score(self, df: pd.DataFrame) -> pd.DataFrame:
        actual = df[self.config.target_col].astype(float).to_numpy()
        mean = df[self.config.forecast_mean_col].astype(float).to_numpy()
        std = np.maximum(
            df[self.config.forecast_std_col].astype(float).to_numpy(),
            _MIN_STD,
        )

        residual = actual - mean
        z_score = residual / std

        if self.config.clip_z_score is not None:
            cap = abs(self.config.clip_z_score)
            z_score = np.clip(z_score, -cap, cap)

        result = df.copy()
        result["residual"] = residual
        result["abs_residual"] = np.abs(residual)
        result["z_score"] = z_score
        result["abs_z_score"] = np.abs(z_score)

        # TS-02 CI breach flags — 1 if actual is outside the interval
        for pct in self.config.ci_levels:
            lower = df[f"ci_lower_{pct}"].astype(float).to_numpy()
            upper = df[f"ci_upper_{pct}"].astype(float).to_numpy()
            result[f"is_outside_ci_{pct}"] = (
                (actual < lower) | (actual > upper)
            ).astype("int8")

        return result
