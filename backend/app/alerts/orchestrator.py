"""
ALT-01: Alert orchestration service.

Consumes anomaly events from the ``anomaly-events`` Redis Stream (published by
DET-02 ``AnomalyEventEmitter``) and dispatches delivery to one or more alert
channels.

Responsibilities
----------------
ALT-01  Consume → parse → dispatch loop
ALT-02  Dedup check via ``AlertRepository.is_duplicate`` before each delivery
ALT-03  Per-series cooldown via ``CooldownTracker``
ALT-04  Persist in-app alerts (DB write = delivery)
ALT-05  Email delivery via ``EmailChannel``
ALT-06  Retry transient failures via ``RetryPolicy``

Usage
-----
# Startup (e.g. in a background thread or separate worker process)
orchestrator = AlertOrchestrator.from_env(session_factory)
orchestrator.serve_forever()

# Or process one batch manually (useful in tests)
orchestrator.process_once(batch_size=10)

# Graceful shutdown (from another thread)
orchestrator.stop()
"""

from __future__ import annotations

import json
import logging
import signal
import threading
import uuid
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy.orm import Session

from app.alerts.channels.email import EmailChannel
from app.alerts.channels.in_app import InAppChannel
from app.alerts.cooldown import CooldownTracker
from app.alerts.dedup import build_dedup_key
from app.alerts.retry import RetryPolicy
from app.db.models.alert import AlertRow
from app.db.repos.alert_repo import AlertRepository
from services.detection.anomaly_emitter import AnomalyEvent
from services.stream.broker_interface import BrokerMessage, EventBroker, RedisStreamBroker

logger = logging.getLogger(__name__)

_DEFAULT_STREAM = "anomaly-events"


class AlertOrchestrator:
    """
    ALT-01: Consume anomaly events and orchestrate alert delivery.

    Parameters
    ----------
    broker:
        ``EventBroker`` implementation (``RedisStreamBroker`` in production).
    session_factory:
        Zero-argument callable that returns a fresh SQLAlchemy ``Session``.
    channels:
        List of delivery channels to dispatch to.  Defaults to
        ``[InAppChannel()]``.
    cooldown:
        ``CooldownTracker`` for per-series suppression (ALT-03).
    retry_policy:
        ``RetryPolicy`` wrapping each channel's ``send()`` call (ALT-06).
    stream_name:
        Redis Stream key to consume from.
    """

    def __init__(
        self,
        broker: EventBroker,
        session_factory: Callable[[], Session],
        channels: list | None = None,
        cooldown: CooldownTracker | None = None,
        retry_policy: RetryPolicy | None = None,
        stream_name: str = _DEFAULT_STREAM,
    ) -> None:
        self._broker = broker
        self._session_factory = session_factory
        self._channels = channels if channels is not None else [InAppChannel()]
        self._cooldown = cooldown or CooldownTracker()
        self._retry = retry_policy or RetryPolicy()
        self._stream = stream_name
        self._repo = AlertRepository()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        session_factory: Callable[[], Session],
        include_email: bool = True,
    ) -> "AlertOrchestrator":
        """
        Create an orchestrator wired to Redis and env-configured channels.

        Parameters
        ----------
        session_factory:
            Callable that returns a fresh SQLAlchemy ``Session``.  Typically
            ``lambda: _SessionLocal()`` from ``app.db.session``.
        include_email:
            Whether to include the ``EmailChannel`` (requires SMTP_HOST).
        """
        channels: list = [InAppChannel()]
        if include_email:
            channels.append(EmailChannel.from_env())
        return cls(
            broker=RedisStreamBroker.from_env(),
            session_factory=session_factory,
            channels=channels,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def serve_forever(self, batch_size: int = 10, block_ms: int = 5_000) -> None:
        """Consume and dispatch in a loop until ``stop()`` is called."""
        self._install_signal_handlers()
        logger.info("ALT-01: alert orchestrator started on stream '%s'", self._stream)
        while not self._stop_event.is_set():
            try:
                self.process_once(batch_size=batch_size, block_ms=block_ms)
            except Exception:
                logger.exception("ALT-01: unexpected error in consume loop; continuing")

    def stop(self) -> None:
        """Request a graceful shutdown after the current batch finishes."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def process_once(self, batch_size: int = 10, block_ms: int = 5_000) -> int:
        """
        Consume up to ``batch_size`` messages and dispatch alerts.

        Returns the number of messages processed.
        """
        messages = self._broker.consume(self._stream, batch_size=batch_size, block_ms=block_ms)
        for msg in messages:
            self._handle_message(msg)
        return len(messages)

    def _handle_message(self, message: BrokerMessage) -> None:
        """Parse one message, dispatch alerts, and ack."""
        try:
            event = self._parse_event(message.payload)
        except Exception as exc:
            logger.warning(
                "ALT-01: malformed anomaly event discarded (message_id=%s): %s",
                message.message_id,
                exc,
            )
            self._broker.ack(message.stream, message.message_id)
            return

        session = self._session_factory()
        try:
            self._dispatch(session, event)
            session.commit()
        except Exception:
            session.rollback()
            logger.exception(
                "ALT-01: dispatch failed for anomaly %s; changes rolled back",
                event.anomaly_id,
            )
        finally:
            session.close()

        self._broker.ack(message.stream, message.message_id)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, session: Session, event: AnomalyEvent) -> None:
        """Decide which alerts to fire and persist the results."""
        in_cooldown = self._cooldown.is_cooling_down(
            event.account_id, event.service, event.region
        )

        for channel in self._channels:
            dedup_key = build_dedup_key(event.anomaly_id, channel.name)

            # ALT-02: skip if already delivered (restart-safe idempotency)
            if self._repo.is_duplicate(session, dedup_key):
                logger.debug(
                    "ALT-02: duplicate skipped (key=%s)", dedup_key
                )
                continue

            # ALT-03: suppress during cooldown
            if in_cooldown:
                self._persist_alert(
                    session, event, channel.name, dedup_key, "suppressed"
                )
                logger.info(
                    "ALT-03: alert suppressed (cooldown active) — %s/%s/%s via %s",
                    event.account_id,
                    event.service,
                    event.region,
                    channel.name,
                )
                continue

            # ALT-05/ALT-06: attempt delivery with retry
            status = "failed"
            error_detail: str | None = None
            sent_at: datetime | None = None

            try:
                ch = channel  # capture for lambda
                ev = event
                self._retry.execute(lambda: ch.send(ev))
                status = "sent"
                sent_at = datetime.now(tz=UTC)
            except Exception as exc:
                error_detail = str(exc)[:512]
                logger.error(
                    "ALT-06: all retries exhausted for %s via %s: %s",
                    event.anomaly_id,
                    channel.name,
                    exc,
                )

            self._persist_alert(
                session, event, channel.name, dedup_key, status, sent_at, error_detail
            )

        # ALT-03: start cooldown window after first dispatch cycle
        if not in_cooldown:
            self._cooldown.record_alerted(event.account_id, event.service, event.region)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_event(payload: bytes | str) -> AnomalyEvent:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        data = json.loads(payload)
        return AnomalyEvent(**data)

    def _persist_alert(
        self,
        session: Session,
        event: AnomalyEvent,
        channel: str,
        dedup_key: str,
        status: str,
        sent_at: datetime | None = None,
        error_detail: str | None = None,
    ) -> AlertRow:
        row = AlertRow(
            alert_id=uuid.uuid4(),
            anomaly_id=uuid.UUID(event.anomaly_id),
            account_id=event.account_id,
            service=event.service,
            region=event.region,
            severity=event.severity,
            channel=channel,
            status=status,
            dedup_key=dedup_key,
            sent_at=sent_at,
            error_detail=error_detail,
        )
        session.add(row)
        return row

    def _install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda s, _: self.stop())
