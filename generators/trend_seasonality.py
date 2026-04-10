from __future__ import annotations

from typing import Any

import numpy as np


def build_trend_component(n: int, trend_cfg: dict[str, Any] | None) -> np.ndarray:
    """Linear multiplicative trend centered at 1.0."""
    if not trend_cfg or not trend_cfg.get("enabled", False):
        return np.ones(n, dtype=float)

    slope = float(trend_cfg.get("slope", 0.0))
    t = np.arange(n, dtype=float)
    return np.maximum(0.0, 1.0 + slope * t)


def build_seasonality_component(
    n: int,
    seasonality_cfg: dict[str, Any] | None,
    steps_per_day: int,
) -> np.ndarray:
    """Combined daily and weekly multiplicative seasonality centered at 1.0."""
    if not seasonality_cfg:
        return np.ones(n, dtype=float)

    t = np.arange(n, dtype=float)
    component = np.ones(n, dtype=float)

    if seasonality_cfg.get("daily", {}).get("enabled", False):
        daily_amp = float(seasonality_cfg["daily"].get("amplitude", 0.0))
        daily_period = max(float(steps_per_day), 1.0)
        component += daily_amp * np.sin((2.0 * np.pi * t) / daily_period)

    if seasonality_cfg.get("weekly", {}).get("enabled", False):
        weekly_amp = float(seasonality_cfg["weekly"].get("amplitude", 0.0))
        weekly_period = max(float(steps_per_day * 7), 1.0)
        component += weekly_amp * np.sin((2.0 * np.pi * t) / weekly_period)

    return np.maximum(0.0, component)
