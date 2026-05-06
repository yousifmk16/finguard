"""Unit tests for ALT-01: AlertOrchestrator.

No Redis or DB required — broker, session, channels and cooldown are all
injected as mocks or stubs. ``redis`` is itself an optional dependency
that the broker module imports unconditionally; we install a tiny stub in
``sys.modules`` so these tests run in any environment.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest


# TST-03: stub the optional ``redis`` package so importing
# ``services.stream.broker_interface`` (and anything that re-exports from
# ``services.stream``) does not require an actual Redis client install.
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


from app.alerts.cooldown import CooldownTracker  # noqa: E402
from app.alerts.orchestrator import AlertOrchestrator  # noqa: E402
from app.alerts.retry import RetryPolicy  # noqa: E402
from services.stream.broker_interface import BrokerMessage  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
_AID = "aaaaaaaa-0000-0000-0000-000000000001"


def _event_payload(**overrides) -> bytes:
    data = dict(
        anomaly_id=_AID,
        account_id="acct-001",
        service="BigQuery",
        region="us-central1",
        bucket=_NOW.isoformat(),
        anomaly_score=0.85,
        severity="high",
        status="open",
        detected_at=_NOW.isoformat(),
        score_breakdown=None,
    )
    data.update(overrides)
    return json.dumps(data).encode()


def _message(payload: bytes | None = None, msg_id: str = "1000-1") -> BrokerMessage:
    return BrokerMessage(
        stream="anomaly-events",
        message_id=msg_id,
        payload=payload or _event_payload(),
    )


class _FakeChannel:
    """Controllable channel stub."""

    def __init__(self, name: str = "in_app", raises: Exception | None = None):
        self.name = name
        self._raises = raises
        self.calls: list = []

    def send(self, event):
        self.calls.append(event)
        if self._raises:
            raise self._raises


def _make_orchestrator(
    messages: list[BrokerMessage],
    channels: list | None = None,
    cooldown: CooldownTracker | None = None,
    is_duplicate: bool = False,
) -> tuple[AlertOrchestrator, MagicMock, MagicMock]:
    """Return (orchestrator, mock_broker, mock_session)."""
    broker = MagicMock()
    broker.consume.return_value = messages
    broker.ack = MagicMock()

    session = MagicMock()

    # Alert repo is_duplicate check
    repo_mock = MagicMock()
    repo_mock.is_duplicate.return_value = is_duplicate

    no_sleep = RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

    orch = AlertOrchestrator(
        broker=broker,
        session_factory=lambda: session,
        channels=channels or [_FakeChannel("in_app")],
        cooldown=cooldown or CooldownTracker(cooldown_seconds=3600),
        retry_policy=no_sleep,
    )
    orch._repo = repo_mock  # inject mock repo

    return orch, broker, session


# ---------------------------------------------------------------------------
# process_once
# ---------------------------------------------------------------------------

class TestProcessOnce:
    def test_returns_message_count(self):
        msgs = [_message(), _message(msg_id="1000-2")]
        orch, _, _ = _make_orchestrator(msgs)
        assert orch.process_once(batch_size=10) == 2

    def test_acks_every_message(self):
        msgs = [_message(msg_id="1000-1"), _message(msg_id="1000-2")]
        orch, broker, _ = _make_orchestrator(msgs)
        orch.process_once()
        assert broker.ack.call_count == 2

    def test_empty_batch_returns_zero(self):
        orch, _, _ = _make_orchestrator([])
        assert orch.process_once() == 0


# ---------------------------------------------------------------------------
# Happy path dispatch
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_channel_send_called(self):
        ch = _FakeChannel("in_app")
        orch, _, session = _make_orchestrator([_message()], channels=[ch])
        orch.process_once()
        assert len(ch.calls) == 1

    def test_alert_row_added_to_session(self):
        orch, _, session = _make_orchestrator([_message()])
        orch.process_once()
        session.add.assert_called_once()

    def test_session_committed(self):
        orch, _, session = _make_orchestrator([_message()])
        orch.process_once()
        session.commit.assert_called_once()

    def test_two_channels_both_sent(self):
        ch1 = _FakeChannel("in_app")
        ch2 = _FakeChannel("email")
        orch, _, session = _make_orchestrator([_message()], channels=[ch1, ch2])
        orch.process_once()
        assert len(ch1.calls) == 1
        assert len(ch2.calls) == 1
        assert session.add.call_count == 2

    def test_persisted_alert_status_is_sent(self):
        captured: list = []
        session = MagicMock()
        session.add.side_effect = captured.append

        ch = _FakeChannel("in_app")
        broker = MagicMock()
        broker.consume.return_value = [_message()]
        no_sleep = RetryPolicy(sleep_fn=lambda _: None)
        orch = AlertOrchestrator(
            broker=broker,
            session_factory=lambda: session,
            channels=[ch],
            retry_policy=no_sleep,
        )
        orch._repo = MagicMock()
        orch._repo.is_duplicate.return_value = False

        orch.process_once()
        assert captured[0].status == "sent"


# ---------------------------------------------------------------------------
# Cooldown (ALT-03)
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_suppressed_during_cooldown(self):
        from datetime import UTC
        now = [datetime.now(UTC)]
        cooldown = CooldownTracker(cooldown_seconds=3600, now_fn=lambda: now[0])
        cooldown.record_alerted("acct-001", "BigQuery", "us-central1")

        captured: list = []
        session = MagicMock()
        session.add.side_effect = captured.append

        ch = _FakeChannel("in_app")
        broker = MagicMock()
        broker.consume.return_value = [_message()]
        no_sleep = RetryPolicy(sleep_fn=lambda _: None)
        orch = AlertOrchestrator(
            broker=broker,
            session_factory=lambda: session,
            channels=[ch],
            cooldown=cooldown,
            retry_policy=no_sleep,
        )
        orch._repo = MagicMock()
        orch._repo.is_duplicate.return_value = False

        orch.process_once()
        assert len(ch.calls) == 0
        assert captured[0].status == "suppressed"

    def test_cooldown_recorded_after_dispatch(self):
        from datetime import UTC
        cooldown = CooldownTracker(cooldown_seconds=3600)
        orch, _, _ = _make_orchestrator([_message()], cooldown=cooldown)
        orch.process_once()
        assert cooldown.is_cooling_down("acct-001", "BigQuery", "us-central1")


# ---------------------------------------------------------------------------
# Dedup (ALT-02)
# ---------------------------------------------------------------------------

class TestDedup:
    def test_duplicate_skips_send(self):
        ch = _FakeChannel("in_app")
        orch, _, session = _make_orchestrator([_message()], channels=[ch], is_duplicate=True)
        orch.process_once()
        assert len(ch.calls) == 0
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Failure handling (ALT-06)
# ---------------------------------------------------------------------------

class TestFailureHandling:
    def test_failed_delivery_persists_failed_status(self):
        captured: list = []
        session = MagicMock()
        session.add.side_effect = captured.append

        ch = _FakeChannel("email", raises=RuntimeError("smtp timeout"))
        broker = MagicMock()
        broker.consume.return_value = [_message()]
        no_sleep = RetryPolicy(max_attempts=1, sleep_fn=lambda _: None)
        orch = AlertOrchestrator(
            broker=broker,
            session_factory=lambda: session,
            channels=[ch],
            retry_policy=no_sleep,
        )
        orch._repo = MagicMock()
        orch._repo.is_duplicate.return_value = False

        orch.process_once()
        assert captured[0].status == "failed"
        assert "smtp timeout" in (captured[0].error_detail or "")

    def test_message_still_acked_after_failed_delivery(self):
        ch = _FakeChannel("in_app", raises=RuntimeError("oops"))
        orch, broker, _ = _make_orchestrator([_message()], channels=[ch])
        orch.process_once()
        broker.ack.assert_called_once()

    def test_session_rolled_back_on_db_error(self):
        broker = MagicMock()
        broker.consume.return_value = [_message()]
        session = MagicMock()
        session.commit.side_effect = RuntimeError("db gone")

        no_sleep = RetryPolicy(sleep_fn=lambda _: None)
        orch = AlertOrchestrator(
            broker=broker,
            session_factory=lambda: session,
            channels=[_FakeChannel("in_app")],
            retry_policy=no_sleep,
        )
        orch._repo = MagicMock()
        orch._repo.is_duplicate.return_value = False

        orch.process_once()  # must not raise
        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Malformed messages
# ---------------------------------------------------------------------------

class TestMalformedMessages:
    def test_invalid_json_is_discarded(self):
        msg = BrokerMessage(stream="s", message_id="1", payload=b"not-json{{{")
        orch, broker, session = _make_orchestrator([msg])
        orch.process_once()
        broker.ack.assert_called_once()
        session.add.assert_not_called()

    def test_missing_field_is_discarded(self):
        bad = json.dumps({"anomaly_id": "x"}).encode()  # missing required fields
        msg = BrokerMessage(stream="s", message_id="1", payload=bad)
        orch, broker, session = _make_orchestrator([msg])
        orch.process_once()
        broker.ack.assert_called_once()
        session.add.assert_not_called()
