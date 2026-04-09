from __future__ import annotations

from typing import Any

import numpy as np


def apply_level_shift(series: np.ndarray, cfg: dict[str, Any] | None) -> tuple[np.ndarray, np.ndarray]:
    """Inject persistent level shift from start index."""
    n = len(series)
    mask = np.zeros(n, dtype=bool)
    if not cfg or not cfg.get("enabled", False):
        return series, mask

    start_index = int(cfg.get("start_index", 0))
    shift = float(cfg.get("shift", 0.0))
    if n == 0 or start_index >= n:
        return series, mask

    start_index = max(0, start_index)
    series[start_index:] += shift
    mask[start_index:] = True
    return series, mask
