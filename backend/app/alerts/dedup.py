"""
ALT-02: Dedup key strategy.

One alert row is allowed per (anomaly, channel) pair.  Using the anomaly_id
directly as the key component guarantees idempotency across service restarts:
if the orchestrator re-processes the same Redis message after a crash, the
DB unique constraint on ``dedup_key`` (backed by ``AlertRepository.is_duplicate``)
prevents a second alert from being emitted.

Key format: ``{anomaly_id}:{channel}``
"""

from __future__ import annotations


def build_dedup_key(anomaly_id: str, channel: str) -> str:
    """
    Return a string that uniquely identifies one alert-delivery attempt.

    Parameters
    ----------
    anomaly_id:
        String representation of the anomaly UUID.
    channel:
        Delivery channel name (``"in_app"`` or ``"email"``).

    Examples
    --------
    >>> build_dedup_key("abc-123", "in_app")
    'abc-123:in_app'
    """
    return f"{anomaly_id}:{channel}"
