from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


PRIORITY_ORDER = ("spike", "drift", "level_shift", "budget_breach")


def build_labels(injector_masks: Mapping[str, np.ndarray], n: int) -> pd.DataFrame:
    """Build anomaly labels from injector masks."""
    labels = pd.DataFrame(
        {
            "is_anomaly": np.zeros(n, dtype=int),
            "anomaly_type": np.full(n, "normal", dtype=object),
        }
    )

    for anomaly_type in PRIORITY_ORDER:
        mask = injector_masks.get(anomaly_type)
        if mask is None:
            continue
        labels.loc[mask, "is_anomaly"] = 1
        labels.loc[mask, "anomaly_type"] = anomaly_type

    return labels
