from __future__ import annotations

from typing import Any

import numpy as np


def build_gaussian_noise(
    n: int,
    noise_cfg: dict[str, Any] | None,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate additive gaussian noise."""
    if not noise_cfg:
        return np.zeros(n, dtype=float)

    if noise_cfg.get("model", "gaussian") != "gaussian":
        raise ValueError("Only gaussian noise model is supported.")

    sigma = float(noise_cfg.get("sigma", 0.0))
    if sigma <= 0:
        return np.zeros(n, dtype=float)
    return rng.normal(loc=0.0, scale=sigma, size=n)
