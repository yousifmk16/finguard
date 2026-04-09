from __future__ import annotations

from typing import Mapping

import numpy as np


def baseline_value(account_id: str, baseline_by_account: Mapping[str, float], default: float) -> float:
    """Return baseline cost for an account."""
    return float(baseline_by_account.get(account_id, default))


def build_usage_series(
    n: int,
    rng: np.random.Generator,
    mean: float = 100.0,
    std: float = 5.0,
) -> np.ndarray:
    """Build non-negative synthetic usage baseline series."""
    usage = rng.normal(loc=mean, scale=max(std, 1e-9), size=n)
    return np.clip(usage, 0.0, None)
