"""
ALT-03: Per-series cooldown window.

After an alert fires for an (account_id, service, region) combination, all
subsequent anomalies for the same series are suppressed until the cooldown
window expires.  This prevents alert storms during prolonged cost spikes.

Current implementation is in-process memory (sufficient for a single-worker
orchestrator).  Replace ``_last_alerted`` with a Redis hash for multi-worker
deployments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

_DEFAULT_COOLDOWN_SECONDS = 3_600  # 1 hour


class CooldownTracker:
    """
    Track per-series alert cooldown.

    Parameters
    ----------
    cooldown_seconds:
        Minimum gap between consecutive alerts for the same
        (account_id, service, region) triple.  Defaults to 1 hour.
    now_fn:
        Callable returning the current UTC datetime.  Injectable for testing.
    """

    def __init__(
        self,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._now: Callable[[], datetime] = now_fn or (lambda: datetime.now(tz=UTC))
        self._last_alerted: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_cooling_down(self, account_id: str, service: str, region: str) -> bool:
        """Return True if this series is still within its cooldown window."""
        key = self._key(account_id, service, region)
        last = self._last_alerted.get(key)
        if last is None:
            return False
        elapsed = (self._now() - last).total_seconds()
        return elapsed < self.cooldown_seconds

    def record_alerted(self, account_id: str, service: str, region: str) -> None:
        """Mark the series as just alerted, starting a new cooldown window."""
        self._last_alerted[self._key(account_id, service, region)] = self._now()

    def reset(self, account_id: str, service: str, region: str) -> None:
        """Remove the cooldown entry for a series (useful in tests)."""
        self._last_alerted.pop(self._key(account_id, service, region), None)

    def reset_all(self) -> None:
        """Clear all cooldown state."""
        self._last_alerted.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _key(account_id: str, service: str, region: str) -> str:
        return f"{account_id}:{service}:{region}"
