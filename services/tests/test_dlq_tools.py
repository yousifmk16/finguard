"""
OPS-04: Tests for ``services.stream.dlq_tools`` — DLQ inspection and replay.

The DLQ writer (``StreamConsumerService._write_dlq``) and these reader/replay
helpers are co-versioned; if either drifts the operator runbook breaks. These
tests pin the contract from the *consumer* side.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Stub redis (services.stream package re-exports the broker which imports it).
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


from services.stream.dlq_tools import (  # noqa: E402
    count,
    main,
    read,
    replay,
    validate_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _well_formed(idx: int) -> dict:
    return {
        "failed_at": "2026-05-08T12:00:00+00:00",
        "stream": "billing-events",
        "message_id": f"msg-{idx}",
        "error": "synthetic failure",
        "raw_payload": json.dumps({"event_id": f"evt-{idx}"}),
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for r in records:
            handle.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


class TestCount:
    def test_returns_zero_for_missing_file(self, tmp_path: Path) -> None:
        assert count(tmp_path / "does-not-exist.jsonl") == 0

    def test_counts_records(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(i) for i in range(5)])
        assert count(path) == 5

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        path.write_text(
            json.dumps(_well_formed(1)) + "\n\n\n" + json.dumps(_well_formed(2)) + "\n",
            encoding="utf-8",
        )
        assert count(path) == 2

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(0)])
        assert count(str(path)) == 1


# ---------------------------------------------------------------------------
# read()
# ---------------------------------------------------------------------------


class TestRead:
    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        assert read(tmp_path / "missing.jsonl") == []

    def test_returns_all_records_when_no_limit(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        records = [_well_formed(i) for i in range(3)]
        _write_jsonl(path, records)
        assert read(path) == records

    def test_limit_returns_most_recent_n(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        records = [_well_formed(i) for i in range(10)]
        _write_jsonl(path, records)

        result = read(path, limit=3)
        assert [r["message_id"] for r in result] == ["msg-7", "msg-8", "msg-9"]

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        path.write_text(
            json.dumps(_well_formed(1)) + "\n"
            + "not-json\n"
            + json.dumps(_well_formed(2)) + "\n",
            encoding="utf-8",
        )
        result = read(path)
        assert len(result) == 2
        assert [r["message_id"] for r in result] == ["msg-1", "msg-2"]

    def test_skips_non_object_records(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        path.write_text(
            "[1,2,3]\n" + json.dumps(_well_formed(1)) + "\n",
            encoding="utf-8",
        )
        result = read(path)
        assert len(result) == 1
        assert result[0]["message_id"] == "msg-1"


# ---------------------------------------------------------------------------
# validate_record()
# ---------------------------------------------------------------------------


class TestValidateRecord:
    def test_well_formed_record_returns_empty_list(self) -> None:
        assert validate_record(_well_formed(1)) == []

    def test_missing_field_listed(self) -> None:
        record = _well_formed(1)
        del record["raw_payload"]
        assert validate_record(record) == ["raw_payload"]

    def test_multiple_missing_fields_listed(self) -> None:
        record = {"failed_at": "x"}
        missing = validate_record(record)
        assert "stream" in missing
        assert "message_id" in missing
        assert "error" in missing
        assert "raw_payload" in missing


# ---------------------------------------------------------------------------
# replay()
# ---------------------------------------------------------------------------


class TestReplay:
    def test_publishes_each_record(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(i) for i in range(3)])

        broker = MagicMock()
        broker.publish = MagicMock(return_value="ok")

        published = replay(path, broker)

        assert published == 3
        assert broker.publish.call_count == 3

    def test_uses_original_stream_per_record(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        records = [
            {**_well_formed(0), "stream": "stream-A"},
            {**_well_formed(1), "stream": "stream-B"},
        ]
        _write_jsonl(path, records)

        broker = MagicMock()
        replay(path, broker)

        streams = [c.args[0] for c in broker.publish.call_args_list]
        assert "stream-A" in streams
        assert "stream-B" in streams

    def test_stream_override_redirects_all_records(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(0), _well_formed(1)])

        broker = MagicMock()
        replay(path, broker, stream_override="new-stream")

        streams = {c.args[0] for c in broker.publish.call_args_list}
        assert streams == {"new-stream"}

    def test_passes_raw_payload_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        record = _well_formed(0)
        record["raw_payload"] = '{"event_id":"my-evt-123"}'
        _write_jsonl(path, [record])

        broker = MagicMock()
        replay(path, broker)

        sent_payload = broker.publish.call_args_list[0].args[1]
        assert sent_payload == '{"event_id":"my-evt-123"}'

    def test_skips_records_missing_required_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        valid = _well_formed(0)
        invalid = {"failed_at": "x"}
        _write_jsonl(path, [valid, invalid])

        broker = MagicMock()
        published = replay(path, broker)

        assert published == 1
        assert broker.publish.call_count == 1

    def test_limit_caps_publishes(self, tmp_path: Path) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(i) for i in range(10)])

        broker = MagicMock()
        published = replay(path, broker, limit=3)

        assert published == 3
        assert broker.publish.call_count == 3

    def test_replay_on_missing_file_is_noop(self, tmp_path: Path) -> None:
        broker = MagicMock()
        published = replay(tmp_path / "nope.jsonl", broker)
        assert published == 0
        broker.publish.assert_not_called()


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------


class TestCli:
    def test_count_command_prints_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(0), _well_formed(1)])

        rc = main(["--path", str(path), "count"])
        captured = capsys.readouterr()

        assert rc == 0
        assert captured.out.strip() == "2"

    def test_tail_command_prints_records_as_jsonl(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "dlq.jsonl"
        _write_jsonl(path, [_well_formed(i) for i in range(5)])

        rc = main(["--path", str(path), "tail", "-n", "2"])
        captured = capsys.readouterr()

        assert rc == 0
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 2
        # Each line must parse as JSON.
        for line in lines:
            parsed = json.loads(line)
            assert "message_id" in parsed
        # Should be the *last* two records.
        ids = [json.loads(line)["message_id"] for line in lines]
        assert ids == ["msg-3", "msg-4"]

    def test_count_command_on_missing_file_returns_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["--path", str(tmp_path / "missing.jsonl"), "count"])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "0"
