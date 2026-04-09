from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from typing import Protocol

from redis import Redis
from redis.exceptions import ResponseError, RedisError


LOGGER = logging.getLogger(__name__)


class BrokerError(RuntimeError):
    """Base broker error."""


class BrokerPublishError(BrokerError):
    """Raised when publishing fails."""


class BrokerConsumeError(BrokerError):
    """Raised when consuming fails."""


@dataclass(frozen=True)
class BrokerMessage:
    stream: str
    message_id: str
    payload: bytes


class EventBroker(Protocol):
    def publish(self, stream_name: str, payload: str) -> str:
        ...

    def consume(self, stream_name: str, batch_size: int = 10, block_ms: int = 5000) -> list[BrokerMessage]:
        ...

    def ack(self, stream_name: str, message_id: str) -> None:
        ...


class RedisStreamBroker:
    """Minimal Redis Streams wrapper with consumer-group ack semantics."""

    def __init__(
        self,
        redis_url: str,
        group_name: str,
        consumer_name: str,
        payload_field: str = "payload",
    ) -> None:
        self.redis_url = redis_url
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.payload_field = payload_field
        self.client = Redis.from_url(redis_url, decode_responses=False)

    @classmethod
    def from_env(cls) -> "RedisStreamBroker":
        host_identity = socket.gethostname() or "consumer"
        consumer_name = os.getenv("STREAM_CONSUMER_NAME", f"{host_identity}-worker")
        return cls(
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            group_name=os.getenv("STREAM_CONSUMER_GROUP", "billing-stream-consumers"),
            consumer_name=consumer_name,
        )

    def _ensure_group(self, stream_name: str) -> None:
        try:
            self.client.xgroup_create(name=stream_name, groupname=self.group_name, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise BrokerConsumeError(
                    f"Unable to create consumer group '{self.group_name}' for '{stream_name}'."
                ) from exc

    def publish(self, stream_name: str, payload: str) -> str:
        try:
            message_id = self.client.xadd(stream_name, {self.payload_field: payload.encode("utf-8")})
        except RedisError as exc:
            raise BrokerPublishError(f"Failed to publish to stream '{stream_name}'.") from exc

        if isinstance(message_id, bytes):
            return message_id.decode("utf-8")
        return str(message_id)

    def consume(self, stream_name: str, batch_size: int = 10, block_ms: int = 5000) -> list[BrokerMessage]:
        self._ensure_group(stream_name)
        try:
            entries = self.client.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_name,
                streams={stream_name: ">"},
                count=batch_size,
                block=block_ms,
            )
        except RedisError as exc:
            raise BrokerConsumeError(f"Failed to consume from stream '{stream_name}'.") from exc

        messages: list[BrokerMessage] = []
        for raw_stream, raw_records in entries:
            stream_key = raw_stream.decode("utf-8") if isinstance(raw_stream, bytes) else str(raw_stream)
            for raw_id, fields in raw_records:
                payload = fields.get(self.payload_field.encode("utf-8")) or fields.get(self.payload_field)
                if payload is None:
                    LOGGER.warning("Skipping stream message without payload field", extra={"stream": stream_key})
                    continue
                message_id = raw_id.decode("utf-8") if isinstance(raw_id, bytes) else str(raw_id)
                messages.append(BrokerMessage(stream=stream_key, message_id=message_id, payload=payload))
        return messages

    def ack(self, stream_name: str, message_id: str) -> None:
        try:
            self.client.xack(stream_name, self.group_name, message_id)
        except RedisError as exc:
            raise BrokerConsumeError(
                f"Failed to acknowledge message '{message_id}' on stream '{stream_name}'."
            ) from exc
