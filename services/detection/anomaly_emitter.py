"""
DET-02: Emit anomaly events for the alert service.

After DET-01 persists anomaly records to the ``anomalies`` table,
``AnomalyEventEmitter`` publishes a lightweight JSON event for each new
anomaly onto a dedicated Redis Stream so the downstream alert service
(ALT-01) can consume and orchestrate alerts without polling the database.

Event schema
------------
Each message published to the stream contains a JSON object:

    {
        "anomaly_id":    "uuid",          // AnomalyRow.anomaly_id
        "account_id":    "string",
        "service":       "string",
        "region":        "string",
        "bucket":        "ISO-8601 UTC",  // 1-minute window that was flagged
        "anomaly_score": 0.75,            // float in [0, 1]
        "severity":      "high",          // none | low | medium | high
        "status":        "open",
        "detected_at":   "ISO-8601 UTC",
        "score_breakdown": {...} | null   // only when include_breakdown=True
    }

Stream name
-----------
Default: ``anomaly-events`` (override via ``ANOMALY_STREAM_NAME`` env var or
the constructor argument).

Usage
-----
from services.detection import AnomalyEventEmitter
from services.stream import RedisStreamBroker

broker = RedisStreamBroker.from_env()
emitter = AnomalyEventEmitter(broker)

# Emit a list of AnomalyRow objects (returned by AnomalyRepository.persist_from_df)
message_ids = emitter.emit_rows(anomaly_rows)

# Or emit directly from the raw AnomalyEvent dataclass (useful in tests)
event = AnomalyEvent.from_row(anomaly_row)
message_id = emitter.emit(event)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from services.stream.broker_interface import EventBroker

logger = logging.getLogger(__name__)

_DEFAULT_STREAM = "anomaly-events"


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass
class AnomalyEvent:
    """
    Immutable value object representing a single anomaly event payload.

    Constructed from an ``AnomalyRow`` via :meth:`from_row`, or built
    manually in tests.
    """

    anomaly_id: str
    account_id: str
    service: str
    region: str
    bucket: str                         # ISO-8601 UTC string
    anomaly_score: float
    severity: str
    status: str
    detected_at: str                    # ISO-8601 UTC string
    score_breakdown: Optional[Dict[str, Any]] = field(default=None)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_row(
        cls,
        row: object,
        include_breakdown: bool = False,
    ) -> "AnomalyEvent":
        """
        Build an ``AnomalyEvent`` from an ``AnomalyRow`` ORM instance.

        Parameters
        ----------
        row:
            An ``AnomalyRow`` returned by ``AnomalyRepository.persist_from_df``.
        include_breakdown:
            When True the ``score_breakdown`` JSONB column is embedded in the
            event payload.  Defaults to False because the breakdown can be
            several KB and the alert service only needs the summary fields to
            decide routing/dedup.

        Returns
        -------
        AnomalyEvent
        """
        bucket_val = getattr(row, "bucket", None)
        detected_val = getattr(row, "detected_at", None)

        return cls(
            anomaly_id=str(getattr(row, "anomaly_id", "")),
            account_id=str(getattr(row, "account_id", "")),
            service=str(getattr(row, "service", "")),
            region=str(getattr(row, "region", "")),
            bucket=_to_iso(bucket_val),
            anomaly_score=float(getattr(row, "anomaly_score", 0.0)),
            severity=str(getattr(row, "severity", "none")),
            status=str(getattr(row, "status", "open")),
            detected_at=_to_iso(detected_val),
            score_breakdown=(
                getattr(row, "score_breakdown", None) if include_breakdown else None
            ),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (``None`` values included)."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialise to a compact JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


class AnomalyEventEmitter:
    """
    DET-02: Publish anomaly events to the configured stream broker.

    Parameters
    ----------
    broker:
        Any object satisfying the ``EventBroker`` protocol — typically a
        ``RedisStreamBroker`` in production, or a mock in tests.
    stream_name:
        Redis Stream key to publish on.  Defaults to the
        ``ANOMALY_STREAM_NAME`` env var, falling back to ``"anomaly-events"``.
    include_breakdown:
        When True every emitted event includes the full ``score_breakdown``
        JSONB payload.  Off by default to keep message size small.
    """

    def __init__(
        self,
        broker: EventBroker,
        stream_name: Optional[str] = None,
        include_breakdown: bool = False,
    ) -> None:
        self.broker = broker
        self.stream_name = stream_name or os.getenv(
            "ANOMALY_STREAM_NAME", _DEFAULT_STREAM
        )
        self.include_breakdown = include_breakdown

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, include_breakdown: bool = False) -> "AnomalyEventEmitter":
        """Create an emitter backed by ``RedisStreamBroker.from_env()``."""
        from services.stream.broker_interface import RedisStreamBroker  # lazy — needs redis
        return cls(
            broker=RedisStreamBroker.from_env(),
            include_breakdown=include_breakdown,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(self, event: AnomalyEvent) -> str:
        """
        Publish a single ``AnomalyEvent`` to the stream.

        Parameters
        ----------
        event:
            Pre-built ``AnomalyEvent`` instance.

        Returns
        -------
        The Redis stream message ID assigned to this entry.
        """
        payload = event.to_json()
        message_id = self.broker.publish(self.stream_name, payload)
        logger.info(
            "DET-02: emitted anomaly event",
            extra={
                "stream": self.stream_name,
                "anomaly_id": event.anomaly_id,
                "account_id": event.account_id,
                "severity": event.severity,
                "message_id": message_id,
            },
        )
        return message_id

    def emit_rows(self, rows: List[object]) -> List[str]:
        """
        Emit one event per ``AnomalyRow`` in ``rows``.

        This is the primary integration point with DET-01:

            saved_rows = repo.persist_from_df(session, scored_df)
            session.commit()
            message_ids = emitter.emit_rows(saved_rows)

        Parameters
        ----------
        rows:
            A list of ``AnomalyRow`` instances as returned by
            ``AnomalyRepository.persist_from_df``.

        Returns
        -------
        List of stream message IDs, one per emitted event, in order.
        """
        message_ids: List[str] = []
        for row in rows:
            event = AnomalyEvent.from_row(row, include_breakdown=self.include_breakdown)
            message_ids.append(self.emit(event))
        return message_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_iso(value: object) -> str:
    """
    Coerce a datetime (or None) to a UTC ISO-8601 string.

    Falls back to the current UTC time when ``value`` is None — this
    happens when an ``AnomalyRow`` is emitted before its ``detected_at``
    server-default has been loaded back from the DB.  Call
    ``db.refresh(row)`` before ``emit_rows()`` to avoid the fallback.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if value is not None:
        return str(value)
    logger.warning(
        "_to_iso: datetime value is None — falling back to current UTC time. "
        "Call db.refresh(row) before emit_rows() to emit the correct timestamp."
    )
    return datetime.now(tz=timezone.utc).isoformat()
