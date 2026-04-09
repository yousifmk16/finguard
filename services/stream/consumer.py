from __future__ import annotations

import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.normalizer.core import normalize_event
from services.normalizer.schema import NormalizationError

from .broker_interface import BrokerMessage, EventBroker, RedisStreamBroker
from .validation import ensure_mapping


LOGGER = logging.getLogger(__name__)


def process_event(event: dict[str, Any]) -> None:
    """Placeholder for future DB/anomaly-detection handoff."""
    LOGGER.info(
        "Processed billing event",
        extra={
            "event_id": event["event_id"],
            "account_id": event["account_id"],
            "cost_amount": event["cost_amount"],
            "timestamp": event["timestamp"],
        },
    )


class StreamConsumerService:
    """Consume broker messages, normalize them, and hand off valid events."""

    def __init__(
        self,
        broker: EventBroker,
        stream_name: str | None = None,
        dlq_path: str | Path | None = None,
    ) -> None:
        self.broker = broker
        self.stream_name = stream_name or os.getenv("STREAM_NAME", "billing-events")
        self.dlq_path = Path(dlq_path or os.getenv("STREAM_DLQ_PATH", "logs/dlq.jsonl"))
        self.stop_event = threading.Event()

    @classmethod
    def from_env(cls) -> "StreamConsumerService":
        return cls(broker=RedisStreamBroker.from_env())

    def serve_forever(self, batch_size: int = 10, block_ms: int = 5000) -> None:
        self._install_signal_handlers()
        while not self.stop_event.is_set():
            self.consume_once(batch_size=batch_size, block_ms=block_ms)

    def consume_once(self, batch_size: int = 10, block_ms: int = 5000) -> int:
        messages = self.broker.consume(self.stream_name, batch_size=batch_size, block_ms=block_ms)
        for message in messages:
            self._handle_message(message)
        return len(messages)

    def _handle_message(self, message: BrokerMessage) -> None:
        try:
            raw_payload = message.payload.decode("utf-8")
            decoded = json.loads(raw_payload)
            raw_event = ensure_mapping(decoded)
            normalized = normalize_event(raw_event)
            process_event(normalized)
            self.broker.ack(message.stream, message.message_id)
        except (UnicodeDecodeError, json.JSONDecodeError, NormalizationError, TypeError, ValueError) as exc:
            self._write_dlq(message=message, error=str(exc))
            LOGGER.warning("Rejected billing event", extra={"message_id": message.message_id, "error": str(exc)})
            self.broker.ack(message.stream, message.message_id)

    def _write_dlq(self, message: BrokerMessage, error: str) -> None:
        self.dlq_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "stream": message.stream,
            "message_id": message.message_id,
            "error": error,
            "raw_payload": message.payload.decode("utf-8", errors="replace"),
        }
        with self.dlq_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")

    def _install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self._request_stop)

    def _request_stop(self, signum: int, _frame: Any) -> None:
        LOGGER.info("Stopping stream consumer", extra={"signal": signum})
        self.stop_event.set()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    StreamConsumerService.from_env().serve_forever()
