from __future__ import annotations

from typing import Any

import numpy as np


def apply_spike(
    series: np.ndarray,
    cfg: dict[str, Any] | None,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Inject isolated spikes."""
    n = len(series)
    mask = np.zeros(n, dtype=bool)
    if not cfg or not cfg.get("enabled", False):
        return series, mask

    count = int(cfg.get("count", 0))
    multiplier = float(cfg.get("multiplier", 2.0))
    if count <= 0 or n == 0:
        return series, mask

    count = min(count, n)
    indices = rng.choice(n, size=count, replace=False)
    series[indices] *= multiplier
    mask[indices] = True
    return series, mask
