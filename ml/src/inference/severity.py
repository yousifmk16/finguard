"""
ENS-02: Severity mapping — converts a continuous anomaly_score to a discrete
severity label and adds it as a column to the scored DataFrame.

Severity levels
---------------
    NONE    – row is not an anomaly (is_anomaly == 0)
    LOW     – anomaly score in [threshold, low_high_boundary)
    MEDIUM  – anomaly score in [low_high_boundary, medium_high_boundary)
    HIGH    – anomaly score in [medium_high_boundary, 1.0]

Default boundaries align with the three-tier policy defined in the
architecture baseline ("low | medium | high"):

    threshold            0.55   (matches ScoringConfig.anomaly_threshold)
    low_medium_boundary  0.65
    medium_high_boundary 0.80

These can be overridden at runtime via SeverityConfig or environment
variables (FINGUARD_SEV_*).

Usage
-----
# Standalone — apply after OnlineScorer.score()
mapper = SeverityMapper()
scored_df = mapper.transform(scored_df)

# Or pass to OnlineScorer at construction (applied automatically inside score())
scorer = OnlineScorer(config, severity_mapper=SeverityMapper())

Output
------
Adds one column to the DataFrame:
    severity    str   "none" | "low" | "medium" | "high"
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Severity level enum
# ---------------------------------------------------------------------------


class SeverityLevel(str, Enum):
    """Ordered anomaly severity levels.

    Inherits from ``str`` so values serialise cleanly to JSON / DB without
    extra conversion (e.g. ``SeverityLevel.HIGH == "high"`` is True).
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def __lt__(self, other: "SeverityLevel") -> bool:  # type: ignore[override]
        return _SEVERITY_ORDER[self] < _SEVERITY_ORDER[other]

    def __le__(self, other: "SeverityLevel") -> bool:  # type: ignore[override]
        return _SEVERITY_ORDER[self] <= _SEVERITY_ORDER[other]

    def __gt__(self, other: "SeverityLevel") -> bool:  # type: ignore[override]
        return _SEVERITY_ORDER[self] > _SEVERITY_ORDER[other]

    def __ge__(self, other: "SeverityLevel") -> bool:  # type: ignore[override]
        return _SEVERITY_ORDER[self] >= _SEVERITY_ORDER[other]


_SEVERITY_ORDER: dict[SeverityLevel, int] = {
    SeverityLevel.NONE: 0,
    SeverityLevel.LOW: 1,
    SeverityLevel.MEDIUM: 2,
    SeverityLevel.HIGH: 3,
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SeverityConfig:
    """
    Thresholds for converting ``anomaly_score`` to a severity label.

    Attributes
    ----------
    anomaly_threshold:
        Minimum score for a row to be considered an anomaly at all.
        Should match ``ScoringConfig.anomaly_threshold`` so that
        ``is_anomaly == 1`` rows always receive a non-NONE severity.
    low_medium_boundary:
        Scores in [anomaly_threshold, low_medium_boundary) → LOW.
    medium_high_boundary:
        Scores in [low_medium_boundary, medium_high_boundary) → MEDIUM.
        Scores in [medium_high_boundary, 1.0] → HIGH.
    score_col:
        Name of the anomaly score column produced by ENS-01.
    is_anomaly_col:
        Name of the binary anomaly flag column produced by ENS-01.
    severity_col:
        Name of the output severity column.
    """

    anomaly_threshold: float = float(
        os.getenv("FINGUARD_SEV_THRESHOLD", "0.55")
    )
    low_medium_boundary: float = float(
        os.getenv("FINGUARD_SEV_LOW_MEDIUM", "0.65")
    )
    medium_high_boundary: float = float(
        os.getenv("FINGUARD_SEV_MEDIUM_HIGH", "0.80")
    )

    score_col: str = "anomaly_score"
    is_anomaly_col: str = "is_anomaly"
    severity_col: str = "severity"

    def __post_init__(self) -> None:
        if not (0.0 <= self.anomaly_threshold < self.low_medium_boundary):
            raise ValueError(
                f"anomaly_threshold ({self.anomaly_threshold}) must be "
                f"< low_medium_boundary ({self.low_medium_boundary})."
            )
        if not (self.low_medium_boundary < self.medium_high_boundary <= 1.0):
            raise ValueError(
                f"low_medium_boundary ({self.low_medium_boundary}) must be "
                f"< medium_high_boundary ({self.medium_high_boundary}) ≤ 1.0."
            )


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------


class SeverityMapper:
    """
    ENS-02: Maps a continuous ``anomaly_score`` column to a discrete
    ``severity`` label.

    Calling styles
    --------------
    # Vectorised DataFrame transform (main use-case)
    mapper = SeverityMapper()
    df = mapper.transform(scored_df)          # adds "severity" column

    # Single-value helper (useful in tests / business-logic callers)
    level = mapper.map_score(0.75, is_anomaly=1)  # → SeverityLevel.MEDIUM
    """

    def __init__(self, config: SeverityConfig | None = None) -> None:
        self.config = config or SeverityConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add a ``severity`` column to ``df``.

        Parameters
        ----------
        df:
            Output of ``OnlineScorer.score()`` or ``score_group()``.
            Must contain ``score_col`` and optionally ``is_anomaly_col``.

        Returns
        -------
        Copy of ``df`` with the ``severity_col`` column appended.

        Notes
        -----
        If ``is_anomaly_col`` is absent, severity is derived solely from
        ``score_col`` using ``anomaly_threshold`` as the NONE boundary.
        """
        cfg = self.config
        self._validate(df)

        scores = df[cfg.score_col].astype(float).to_numpy()

        if cfg.is_anomaly_col in df.columns:
            is_anomaly = df[cfg.is_anomaly_col].astype(int).to_numpy()
        else:
            is_anomaly = (scores >= cfg.anomaly_threshold).astype(int)

        labels = self._vectorised_map(scores, is_anomaly)

        result = df.copy()
        result[cfg.severity_col] = labels
        return result

    def map_score(self, score: float, is_anomaly: int = -1) -> SeverityLevel:
        """
        Map a single score to a SeverityLevel.

        Parameters
        ----------
        score:
            Anomaly score in [0, 1].
        is_anomaly:
            Pass 1 to force anomaly treatment, 0 to force NONE.
            Pass -1 (default) to derive from ``config.anomaly_threshold``.

        Returns
        -------
        SeverityLevel
        """
        cfg = self.config
        if is_anomaly == -1:
            is_anomaly = int(score >= cfg.anomaly_threshold)
        return self._classify(score, is_anomaly)

    def severity_col_name(self) -> str:
        """Name of the column this mapper writes."""
        return self.config.severity_col

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate(self, df: pd.DataFrame) -> None:
        if self.config.score_col not in df.columns:
            raise ValueError(
                f"Column '{self.config.score_col}' not found in DataFrame. "
                "Run OnlineScorer.score() before applying SeverityMapper."
            )

    def _classify(self, score: float, is_anomaly: int) -> SeverityLevel:
        """Map a single (score, is_anomaly) pair to a SeverityLevel."""
        if not is_anomaly:
            return SeverityLevel.NONE
        cfg = self.config
        if score >= cfg.medium_high_boundary:
            return SeverityLevel.HIGH
        if score >= cfg.low_medium_boundary:
            return SeverityLevel.MEDIUM
        return SeverityLevel.LOW

    def _vectorised_map(
        self,
        scores: np.ndarray,
        is_anomaly: np.ndarray,
    ) -> np.ndarray:
        """
        Vectorised classification using np.select for efficiency.

        Condition precedence (first match wins):
          1. not an anomaly         → "none"
          2. score ≥ medium_high    → "high"
          3. score ≥ low_medium     → "medium"
          4. otherwise (anomaly)    → "low"
        """
        cfg = self.config
        not_anomaly = is_anomaly == 0

        conditions = [
            not_anomaly,
            scores >= cfg.medium_high_boundary,
            scores >= cfg.low_medium_boundary,
        ]
        choices = [
            SeverityLevel.NONE.value,
            SeverityLevel.HIGH.value,
            SeverityLevel.MEDIUM.value,
        ]
        return np.select(conditions, choices, default=SeverityLevel.LOW.value)
