"""
EXP-01: Explanation generator — forecast vs actual deviation.

For each scored row this module produces a structured explanation that
describes *why* a row deviated from the time-series forecast.  It is the
first layer of the EXP-* explanation stack:

    EXP-01  (this file)  – forecast vs actual gap
    EXP-02               – triggered-rule details
    EXP-03               – full score breakdown payload

Input
-----
A DataFrame that has been processed by:
  1. TimeSeriesBaselineModel.predict()   (adds forecast_mean, forecast_std,
                                          ci_lower_<pct>, ci_upper_<pct>)
  2. ResidualScorer.transform()          (adds residual, z_score, abs_z_score,
                                          is_outside_ci_<pct>)
  3. OnlineScorer.score() or score_group() (adds anomaly_score, is_anomaly)

All three steps are performed inside OnlineScorer; the output DataFrame
already contains all required columns.

Output — structured dataclass
------------------------------
explain_row() returns a ForecastExplanation per row.

Output — DataFrame columns (explain() method)
----------------------------------------------
    exp_direction       str     "above" | "below" | "within"
    exp_pct_deviation   float   signed % deviation from forecast mean
    exp_z_score         float   signed z-score (residual / forecast_std)
    exp_ci_breach       bool    True if actual is outside the primary CI band
    exp_summary         str     One human-readable sentence

Usage
-----
# Row-level explanation
gen = ExplanationGenerator()
exp = gen.explain_row(scored_df.iloc[0])
print(exp.summary)

# DataFrame-level (adds explanation columns in-place via copy)
explained_df = gen.explain(scored_df)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ForecastExplanation:
    """
    Structured explanation for the deviation of a single row from its
    time-series forecast.

    Attributes
    ----------
    actual : float
        Observed value (``total_cost`` or the configured target column).
    forecast_mean : float
        Predicted mean from the time-series baseline model.
    forecast_std : float
        Predicted standard deviation (used to compute z_score).
    residual : float
        Signed difference: ``actual − forecast_mean``.
    pct_deviation : float
        Signed percentage deviation: ``residual / |forecast_mean| × 100``.
        NaN when ``forecast_mean`` is zero.
    z_score : float
        Signed z-score: ``residual / forecast_std``.
    direction : str
        "above" if actual > forecast_mean,
        "below" if actual < forecast_mean,
        "within" if actual == forecast_mean.
    ci_breaches : dict[int, bool]
        Maps each configured CI level (e.g. 95) to whether the actual value
        fell outside that interval.  Empty dict when no CI columns are present.
    summary : str
        Human-readable one-sentence explanation.
    """

    actual: float
    forecast_mean: float
    forecast_std: float
    residual: float
    pct_deviation: float       # signed %; NaN when forecast_mean == 0
    z_score: float
    direction: str             # "above" | "below" | "within"
    ci_breaches: Dict[int, bool] = field(default_factory=dict)
    summary: str = ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ExplanationConfig:
    """
    Parameters controlling how explanations are generated.

    Attributes
    ----------
    target_col : str
        Column name for the observed value.
    forecast_mean_col : str
        Column name for the forecast mean.
    forecast_std_col : str
        Column name for the forecast standard deviation.
    z_score_col : str
        Column name for the pre-computed z-score (from ResidualScorer).
        When absent, z-score is recomputed from residual / forecast_std.
    residual_col : str
        Column name for the pre-computed residual (from ResidualScorer).
        When absent, residual is computed as actual − forecast_mean.
    ci_levels : list[int]
        CI percentage levels to check for breaches.
        For each level N the generator looks for ``ci_lower_N`` /
        ``ci_upper_N`` columns (written by TS-02) and / or
        ``is_outside_ci_N`` flags (written by ResidualScorer).
    output_prefix : str
        Prefix for the columns written by explain().
    """

    target_col: str = "total_cost"
    forecast_mean_col: str = "forecast_mean"
    forecast_std_col: str = "forecast_std"
    z_score_col: str = "z_score"
    residual_col: str = "residual"
    ci_levels: List[int] = field(default_factory=lambda: [95])
    output_prefix: str = "exp_"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class ExplanationGenerator:
    """
    EXP-01: Build forecast-vs-actual explanations from a scored DataFrame.

    Two calling styles
    ------------------
    # 1. Per-row structured result
    gen = ExplanationGenerator()
    exp: ForecastExplanation = gen.explain_row(scored_df.iloc[3])

    # 2. Whole-DataFrame transform (adds ``exp_*`` columns)
    explained_df = gen.explain(scored_df)
    """

    def __init__(self, config: Optional[ExplanationConfig] = None) -> None:
        self.config = config or ExplanationConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_row(self, row: pd.Series) -> ForecastExplanation:
        """
        Build a ForecastExplanation for a single scored row.

        Parameters
        ----------
        row :
            A row from the output of OnlineScorer.score() / score_group().
            Must contain the target column and at least one of:
            - forecast_mean_col + forecast_std_col, or
            - residual_col + z_score_col (pre-computed by ResidualScorer).

        Returns
        -------
        ForecastExplanation
        """
        cfg = self.config

        actual = float(row[cfg.target_col])
        forecast_mean = float(row[cfg.forecast_mean_col]) if cfg.forecast_mean_col in row.index else math.nan
        forecast_std = float(row[cfg.forecast_std_col]) if cfg.forecast_std_col in row.index else math.nan

        # Residual — prefer pre-computed column, fall back to recompute
        if cfg.residual_col in row.index and not _isnan(row[cfg.residual_col]):
            residual = float(row[cfg.residual_col])
        elif not math.isnan(forecast_mean):
            residual = actual - forecast_mean
        else:
            residual = math.nan

        # Z-score — prefer pre-computed column, fall back to recompute
        if cfg.z_score_col in row.index and not _isnan(row[cfg.z_score_col]):
            z_score = float(row[cfg.z_score_col])
        elif not math.isnan(forecast_std) and forecast_std != 0.0:
            z_score = residual / forecast_std
        else:
            z_score = math.nan

        # Percentage deviation relative to |forecast_mean|
        if not math.isnan(forecast_mean) and forecast_mean != 0.0:
            pct_deviation = (residual / abs(forecast_mean)) * 100.0
        else:
            pct_deviation = math.nan

        direction = _direction(residual)

        ci_breaches = self._ci_breaches(row, actual)

        summary = _build_summary(
            actual=actual,
            forecast_mean=forecast_mean,
            pct_deviation=pct_deviation,
            z_score=z_score,
            direction=direction,
            ci_breaches=ci_breaches,
            target_col=cfg.target_col,
        )

        return ForecastExplanation(
            actual=actual,
            forecast_mean=forecast_mean,
            forecast_std=forecast_std,
            residual=residual,
            pct_deviation=pct_deviation,
            z_score=z_score,
            direction=direction,
            ci_breaches=ci_breaches,
            summary=summary,
        )

    def explain(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add explanation columns to a scored DataFrame.

        Parameters
        ----------
        df :
            Output of OnlineScorer.score() or score_group().

        Returns
        -------
        Copy of ``df`` with the following columns appended
        (prefix controlled by ExplanationConfig.output_prefix):

            exp_direction       str     "above" | "below" | "within"
            exp_pct_deviation   float   signed % deviation from forecast mean
            exp_z_score         float   signed z-score
            exp_ci_breach       bool    True if primary CI was breached
            exp_summary         str     Human-readable sentence
        """
        cfg = self.config
        p = cfg.output_prefix

        result = df.copy()

        directions: list[str] = []
        pct_devs: list[float] = []
        z_scores: list[float] = []
        ci_breaches: list[bool] = []
        summaries: list[str] = []

        for _, row in df.iterrows():
            exp = self.explain_row(row)
            directions.append(exp.direction)
            pct_devs.append(exp.pct_deviation)
            z_scores.append(exp.z_score)
            # Primary CI level (first configured); False when no CI data
            primary_ci = cfg.ci_levels[0] if cfg.ci_levels else None
            ci_breaches.append(exp.ci_breaches.get(primary_ci, False) if primary_ci else False)
            summaries.append(exp.summary)

        result[f"{p}direction"] = directions
        result[f"{p}pct_deviation"] = pct_devs
        result[f"{p}z_score"] = z_scores
        result[f"{p}ci_breach"] = ci_breaches
        result[f"{p}summary"] = summaries

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ci_breaches(
        self, row: pd.Series, actual: float
    ) -> Dict[int, bool]:
        """
        Determine which CI bands the actual value breached.

        Prefers the ``is_outside_ci_<pct>`` flag written by ResidualScorer;
        falls back to checking ``ci_lower_<pct>`` / ``ci_upper_<pct>``
        directly when available.
        """
        breaches: Dict[int, bool] = {}
        for pct in self.config.ci_levels:
            flag_col = f"is_outside_ci_{pct}"
            lower_col = f"ci_lower_{pct}"
            upper_col = f"ci_upper_{pct}"

            if flag_col in row.index and not _isnan(row[flag_col]):
                breaches[pct] = bool(int(row[flag_col]))
            elif lower_col in row.index and upper_col in row.index:
                lower = float(row[lower_col])
                upper = float(row[upper_col])
                breaches[pct] = actual < lower or actual > upper
        return breaches


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _isnan(value: object) -> bool:
    """Return True if value is a float NaN; False for non-numeric types."""
    try:
        return math.isnan(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def _direction(residual: float) -> str:
    """Map a signed residual to a human-readable direction label."""
    if math.isnan(residual):
        return "unknown"
    if residual > 0:
        return "above"
    if residual < 0:
        return "below"
    return "within"


def _build_summary(
    actual: float,
    forecast_mean: float,
    pct_deviation: float,
    z_score: float,
    direction: str,
    ci_breaches: Dict[int, bool],
    target_col: str,
) -> str:
    """
    Compose a single human-readable sentence that summarises the deviation.

    Examples
    --------
    "Actual cost (152.30) is 52.3% above the forecast (100.00),
     a deviation of 3.2 standard deviations, breaching the 95% CI."

    "Actual cost (95.00) is 5.0% below the forecast (100.00)
     (0.5 standard deviations)."

    "Forecast data unavailable; actual cost was 120.00."
    """
    if math.isnan(forecast_mean):
        return f"Forecast data unavailable; actual {target_col} was {actual:.2f}."

    # Core deviation sentence
    if math.isnan(pct_deviation):
        # forecast_mean was 0 — describe in absolute terms
        abs_residual = abs(actual - forecast_mean)
        core = (
            f"Actual {target_col} ({actual:.2f}) is {direction} the forecast "
            f"({forecast_mean:.2f}) by {abs_residual:.2f} units"
        )
    else:
        core = (
            f"Actual {target_col} ({actual:.2f}) is "
            f"{abs(pct_deviation):.1f}% {direction} the forecast "
            f"({forecast_mean:.2f})"
        )

    # Z-score qualification
    if not math.isnan(z_score):
        core += f", a deviation of {abs(z_score):.1f} standard deviations"

    # CI breach detail
    breached = [pct for pct, hit in ci_breaches.items() if hit]
    if breached:
        ci_str = ", ".join(f"{p}%" for p in sorted(breached))
        core += f", breaching the {ci_str} confidence interval"

    return core + "."
