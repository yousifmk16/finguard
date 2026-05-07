"""
OPS-04: Validation tests for the stream consumer's dead-letter workflow.

The ingestion stream consumer (``StreamConsumerService``) writes one JSON
object per line to ``logs/dlq.jsonl`` whenever it cannot decode, validate,
or normalize an inbound message.  This test file proves end-to-end that:

  * Bad JSON, malformed envelopes, and normalization errors all land in
    the DLQ.
  * The DLQ record always carries the documented fields with the right
    types, so the operator runbook and ``dlq_tools`` reader keep working.
  * Successful messages never touch the DLQ (no false positives).
  * The DLQ file appends across multiple failures (does not overwrite).
  * The DLQ path can be redirected via the ``STREAM_DLQ_PATH`` env var.
  * The original broker message is acked even when it dead-letters,
    preventing infinite redelivery.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Stub redis so importing services.stream.broker_interface (and consumer.py)
# does not require the actual redis client. Same pattern as test_alert_orchestrator.
if "redis" not in sys.modules:
    redis_stub = types.ModuleType("redis")
    redis_stub.Redis = type("Redis", (), {})  # type: ignore[attr-defined]
    exceptions_stub = types.ModuleType("redis.exceptions")
    exceptions_stub.RedisError = type("RedisError", (Exception,), {})  # type: ignore[attr-defined]
    exceptions_stub.ResponseError = type(  # type: ignore[attr-defined]
        "ResponseError", (exceptions_stub.RedisError,), {}
    )
    redis_stub.exceptions = exceptions_stub  # type: ignore[attr-defined]
    sys.modules["redis"] = redis_stub
    sys.modules["redis.exceptions"] = exceptions_stub


from services.stream.broker_interface import BrokerMessage  # noqa: E402
from services.stream.consumer import StreamConsumerService  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_VALID_PAYLOAD = {
    "event_id": "11111111-1111-1111-1111-111111111111",
    "timestamp": "2026-01-01T00:00:00Z",
    "provider": "gcp",
    "account_id": "acct-001",
    "service": "BigQuery",
    "region": "us-central1",
    "cost_amount": 1.0,
    "usage_amount": 1.0,
    "usage_unit": "core-hours",
    "source_type": "live",
}


def _msg(payload: bytes, msg_id: str = "1000-0", stream: str = "billing-events") -> BrokerMessage:
    return BrokerMessage(stream=stream, message_id=msg_id, payload=payload)


def _make_consumer(
    tmp_path: Path,
    messages: list[BrokerMessage],
) -> tuple[StreamConsumerService, MagicMock, Path]:
    broker = MagicMock()
    broker.consume.return_value = messages
    broker.ack = MagicMock()

    dlq_path = tmp_path / "dlq.jsonl"
    consumer = StreamConsumerService(
        broker=broker,
        stream_name="billing-events",
        dlq_path=dlq_path,
    )
    return consumer, broker, dlq_path


def _read_dlq(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. Bad JSON → DLQ
# ---------------------------------------------------------------------------


class TestBadJson:
    def test_invalid_json_writes_dlq_record(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b"not-json")])
        consumer.consume_once()

        records = _read_dlq(dlq_path)
        assert len(records) == 1

    def test_invalid_json_message_is_acked(self, tmp_path: Path) -> None:
        consumer, broker, _ = _make_consumer(tmp_path, [_msg(b"not-json")])
        consumer.consume_once()
        broker.ack.assert_called_once_with("billing-events", "1000-0")


# ---------------------------------------------------------------------------
# 2. Malformed envelope (JSON parses but isn't a dict) → DLQ
# ---------------------------------------------------------------------------


class TestMalformedEnvelope:
    def test_top_level_array_dead_letters(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b'[1,2,3]')])
        consumer.consume_once()
        assert len(_read_dlq(dlq_path)) == 1

    def test_top_level_string_dead_letters(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b'"just a string"')])
        consumer.consume_once()
        assert len(_read_dlq(dlq_path)) == 1


# ---------------------------------------------------------------------------
# 3. Normalization failure → DLQ
# ---------------------------------------------------------------------------


class TestNormalizationFailure:
    def test_missing_required_field_dead_letters(self, tmp_path: Path) -> None:
        bad = {k: v for k, v in _VALID_PAYLOAD.items() if k != "account_id"}
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(json.dumps(bad).encode())])
        consumer.consume_once()

        records = _read_dlq(dlq_path)
        assert len(records) == 1
        # The exact error wording is owned by the normalizer; OPS-04 only
        # asserts that *some* error is captured.
        assert records[0]["error"]

    def test_negative_cost_dead_letters(self, tmp_path: Path) -> None:
        bad = {**_VALID_PAYLOAD, "cost_amount": -10.0}
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(json.dumps(bad).encode())])
        consumer.consume_once()
        assert len(_read_dlq(dlq_path)) == 1


# ---------------------------------------------------------------------------
# 4. DLQ record shape
# ---------------------------------------------------------------------------


class TestDlqRecordShape:
    def test_record_has_all_required_fields(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(
            tmp_path,
            [_msg(b"not-json", msg_id="abc-1", stream="billing-events")],
        )
        consumer.consume_once()

        record = _read_dlq(dlq_path)[0]
        for field in ("failed_at", "stream", "message_id", "error", "raw_payload"):
            assert field in record, f"missing DLQ field: {field}"

    def test_failed_at_is_iso_8601(self, tmp_path: Path) -> None:
        from datetime import datetime

        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b"oops")])
        consumer.consume_once()
        record = _read_dlq(dlq_path)[0]

        # Must parse as ISO 8601 datetime.
        parsed = datetime.fromisoformat(record["failed_at"])
        assert parsed.tzinfo is not None  # must be UTC-aware

    def test_record_preserves_message_id_and_stream(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(
            tmp_path,
            [_msg(b"oops", msg_id="42-7", stream="billing-events")],
        )
        consumer.consume_once()
        record = _read_dlq(dlq_path)[0]
        assert record["message_id"] == "42-7"
        assert record["stream"] == "billing-events"

    def test_raw_payload_preserved_as_string(self, tmp_path: Path) -> None:
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b"the-original-bytes")])
        consumer.consume_once()
        record = _read_dlq(dlq_path)[0]
        assert record["raw_payload"] == "the-original-bytes"

    def test_non_utf8_payload_does_not_crash(self, tmp_path: Path) -> None:
        # 0xff is not valid UTF-8 — the DLQ writer must use errors="replace"
        consumer, _, dlq_path = _make_consumer(tmp_path, [_msg(b"\xff\xfe")])
        consumer.consume_once()
        # File must be created and readable
        record = _read_dlq(dlq_path)[0]
        assert "raw_payload" in record


# ---------------------------------------------------------------------------
# 5. Multiple failures append (do not overwrite)
# ---------------------------------------------------------------------------


def test_multiple_failures_append_records(tmp_path: Path) -> None:
    messages = [
        _msg(b"first-bad", msg_id="1"),
        _msg(b"second-bad", msg_id="2"),
        _msg(b"third-bad", msg_id="3"),
    ]
    consumer, _, dlq_path = _make_consumer(tmp_path, messages)
    consumer.consume_once()

    records = _read_dlq(dlq_path)
    assert len(records) == 3
    assert [r["message_id"] for r in records] == ["1", "2", "3"]


def test_dlq_appends_across_separate_consume_calls(tmp_path: Path) -> None:
    consumer, broker, dlq_path = _make_consumer(tmp_path, [_msg(b"bad-1", msg_id="x1")])
    consumer.consume_once()

    broker.consume.return_value = [_msg(b"bad-2", msg_id="x2")]
    consumer.consume_once()

    records = _read_dlq(dlq_path)
    assert len(records) == 2


# ---------------------------------------------------------------------------
# 6. Successful messages do NOT go to the DLQ (no false positives)
# ---------------------------------------------------------------------------


def test_valid_message_does_not_dead_letter(tmp_path: Path) -> None:
    consumer, broker, dlq_path = _make_consumer(
        tmp_path,
        [_msg(json.dumps(_VALID_PAYLOAD).encode())],
    )
    consumer.consume_once()

    assert _read_dlq(dlq_path) == []
    broker.ack.assert_called_once()  # message still acked on success


def test_mixed_batch_only_bad_messages_dead_letter(tmp_path: Path) -> None:
    good = _msg(json.dumps(_VALID_PAYLOAD).encode(), msg_id="g1")
    bad = _msg(b"junk", msg_id="b1")
    consumer, broker, dlq_path = _make_consumer(tmp_path, [good, bad])
    consumer.consume_once()

    records = _read_dlq(dlq_path)
    assert len(records) == 1
    assert records[0]["message_id"] == "b1"
    # Both messages still get acked.
    assert broker.ack.call_count == 2


# ---------------------------------------------------------------------------
# 7. STREAM_DLQ_PATH env var overrides default location
# ---------------------------------------------------------------------------


def test_dlq_path_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_path = tmp_path / "custom" / "my-dlq.jsonl"
    monkeypatch.setenv("STREAM_DLQ_PATH", str(custom_path))

    broker = MagicMock()
    broker.consume.return_value = [_msg(b"oops")]
    broker.ack = MagicMock()
    consumer = StreamConsumerService(broker=broker, stream_name="billing-events")
    consumer.consume_once()

    assert custom_path.exists()
    assert len(_read_dlq(custom_path)) == 1


def test_dlq_creates_parent_directories(tmp_path: Path) -> None:
    nested_path = tmp_path / "deep" / "nested" / "dlq.jsonl"
    consumer, _, _ = _make_consumer(tmp_path, [_msg(b"oops")])
    consumer.dlq_path = nested_path
    consumer.consume_once()

    assert nested_path.exists()
    assert nested_path.parent.is_dir()
