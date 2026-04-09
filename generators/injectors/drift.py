from __future__ import annotations

from typing import Any

import numpy as np


def apply_drift(series: np.ndarray, cfg: dict[str, Any] | None) -> tuple[np.ndarray, np.ndarray]:
    """Inject a gradual multiplicative drift from start index."""
    n = len(series)
    mask = np.zeros(n, dtype=bool)
    if not cfg or not cfg.get("enabled", False):
        return series, mask

    start_index = int(cfg.get("start_index", 0))
    slope = float(cfg.get("slope", 0.0))
    if n == 0 or start_index >= n:
        return series, mask

    start_index = max(0, start_index)
    drift_steps = np.arange(n - start_index, dtype=float)
    multiplier = np.maximum(0.0, 1.0 + slope * drift_steps)
    series[start_index:] *= multiplier
    mask[start_index:] = True
    return series, mask
