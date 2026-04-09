from __future__ import annotations

import json
import logging
import os
from typing import Any

from .broker_interface import EventBroker, RedisStreamBroker
from .validation import validate_publisher_event


LOGGER = logging.getLogger(__name__)


class EventPublisher:
    """Publish canonical billing events to the configured broker."""

    def __init__(self, broker: EventBroker, stream_name: str | None = None) -> None:
        self.broker = broker
        self.stream_name = stream_name or os.getenv("STREAM_NAME", "billing-events")

    @classmethod
    def from_env(cls) -> "EventPublisher":
        return cls(broker=RedisStreamBroker.from_env())

    def publish_event(self, event: dict[str, Any]) -> str:
        canonical_event = validate_publisher_event(event)
        payload = json.dumps(canonical_event, ensure_ascii=True, separators=(",", ":"))
        message_id = self.broker.publish(self.stream_name, payload)
        LOGGER.info(
            "Published billing event",
            extra={
                "stream": self.stream_name,
                "event_id": canonical_event["event_id"],
                "account_id": canonical_event["account_id"],
                "provider": canonical_event["provider"],
            },
        )
        return message_id

    def publish_for_provider(self, event: dict[str, Any]) -> str:
        canonical_event = validate_publisher_event(event)
        provider_stream = f"{self.stream_name}.provider.{canonical_event['provider']}"
        payload = json.dumps(canonical_event, ensure_ascii=True, separators=(",", ":"))
        return self.broker.publish(provider_stream, payload)

    def publish_for_account(self, event: dict[str, Any]) -> str:
        canonical_event = validate_publisher_event(event)
        account_stream = f"{self.stream_name}.account.{canonical_event['account_id']}"
        payload = json.dumps(canonical_event, ensure_ascii=True, separators=(",", ":"))
        return self.broker.publish(account_stream, payload)

    def publish_all_scopes(self, event: dict[str, Any]) -> dict[str, str]:
        canonical_event = validate_publisher_event(event)
        return {
            "global": self.publish_event(canonical_event),
            "provider": self.publish_for_provider(canonical_event),
            "account": self.publish_for_account(canonical_event),
        }
