from __future__ import annotations

from typing import Any

import numpy as np


def apply_budget_breach(
    series: np.ndarray,
    cfg: dict[str, Any] | None,
    budget: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Force a window to exceed budget threshold."""
    n = len(series)
    mask = np.zeros(n, dtype=bool)
    if not cfg or not cfg.get("enabled", False):
        return series, mask

    if n == 0:
        return series, mask

    start_index = int(cfg.get("start_index", 0))
    duration = int(cfg.get("duration", 1))
    breach_multiplier = float(cfg.get("breach_multiplier", 1.1))

    start_index = min(max(start_index, 0), n - 1)
    end_index = min(start_index + max(duration, 1), n)
    threshold = max(0.0, budget * breach_multiplier)

    window = series[start_index:end_index]
    series[start_index:end_index] = np.maximum(window, threshold)
    mask[start_index:end_index] = True
    return series, mask
