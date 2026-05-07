"""
OPS-04: End-to-end validation of the retry-and-failure workflow.

The unit tests in ``test_alert_retry.py`` cover ``RetryPolicy`` in isolation,
and ``test_alert_orchestrator.py`` covers individual dispatch branches.  This
file proves the *workflow* — the full chain of:

    transient channel failure → backoff → retry → eventual success

and the failure path:

    persistent channel failure → all retries exhausted →
        AlertRow persisted with status='failed' + error_detail truncated to
        the column limit → broker message acked (no infinite redelivery)

Validating the workflow means proving things like ordering, the link
between exception text and ``error_detail``, and the count of channel
attempts that actually fire — properties that are easy to break with a
small refactor and that no existing test pins down.

The tests use the same ``_FakeChannel`` / mocked-session pattern as
``test_alert_orchestrator.py`` so failures here point at workflow
regressions, not testbed drift.
"""

from __future__ import annotations

import json
import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# Match the redis-stub pattern used by other orchestrator tests.
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
# Shared fixtures / fakes
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
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


class _TransientChannel:
    """Fails ``fail_n`` times, then succeeds. Records every attempt."""

    def __init__(self, name: str, fail_n: int, exc: Exception | None = None) -> None:
        self.name = name
        self.fail_n = fail_n
        self.attempts = 0
        self.exc = exc or RuntimeError("transient")

    def send(self, _event) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_n:
            raise self.exc


def _make_orchestrator(
    *,
    channels: list,
    retry_policy: RetryPolicy,
    messages: list[BrokerMessage] | None = None,
    is_duplicate: bool = False,
) -> tuple[AlertOrchestrator, MagicMock, MagicMock, list]:
    broker = MagicMock()
    broker.consume.return_value = messages or [_message()]
    broker.ack = MagicMock()

    session = MagicMock()
    captured: list = []
    session.add.side_effect = captured.append

    repo = MagicMock()
    repo.is_duplicate.return_value = is_duplicate

    orch = AlertOrchestrator(
        broker=broker,
        session_factory=lambda: session,
        channels=channels,
        cooldown=CooldownTracker(cooldown_seconds=3600),
        retry_policy=retry_policy,
    )
    orch._repo = repo
    return orch, broker, session, captured


# ---------------------------------------------------------------------------
# 1. Retry succeeds after transient failure → row persisted as "sent"
# ---------------------------------------------------------------------------


class TestRetrySucceeds:
    def test_one_transient_failure_then_success(self) -> None:
        channel = _TransientChannel("in_app", fail_n=1)
        retry = RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        assert channel.attempts == 2  # one failure + one success
        assert captured[0].status == "sent"
        assert captured[0].error_detail is None
        assert captured[0].sent_at is not None

    def test_multiple_transient_failures_then_success(self) -> None:
        channel = _TransientChannel("in_app", fail_n=2)
        retry = RetryPolicy(max_attempts=5, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        assert channel.attempts == 3
        assert captured[0].status == "sent"


# ---------------------------------------------------------------------------
# 2. Persistent failure → all retries fire → "failed" row persisted
# ---------------------------------------------------------------------------


class TestRetryExhausted:
    def test_status_is_failed_after_all_attempts(self) -> None:
        channel = _TransientChannel(
            "email", fail_n=10, exc=RuntimeError("smtp connection refused")
        )
        retry = RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        assert channel.attempts == 3
        assert captured[0].status == "failed"
        assert captured[0].sent_at is None

    def test_error_detail_captures_exception_message(self) -> None:
        channel = _TransientChannel(
            "email", fail_n=10, exc=RuntimeError("smtp connection refused")
        )
        retry = RetryPolicy(max_attempts=2, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        assert "smtp connection refused" in (captured[0].error_detail or "")

    def test_error_detail_truncated_to_column_limit(self) -> None:
        # AlertRow.error_detail is VARCHAR(512). The orchestrator truncates
        # the exception text to 512 chars before persisting (validated here
        # so a future change to the message format doesn't blow up the DB).
        long_message = "X" * 1000
        channel = _TransientChannel("email", fail_n=10, exc=RuntimeError(long_message))
        retry = RetryPolicy(max_attempts=1, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        assert captured[0].error_detail is not None
        assert len(captured[0].error_detail) <= 512


# ---------------------------------------------------------------------------
# 3. Workflow integrity: even on failure, the message must be acked.
# ---------------------------------------------------------------------------


class TestWorkflowIntegrity:
    def test_broker_acks_message_after_retry_exhaustion(self) -> None:
        """The most important property — without this, a poison message
        gets re-delivered forever and blocks every other event."""
        channel = _TransientChannel("email", fail_n=10)
        retry = RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, broker, _, _ = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        broker.ack.assert_called_once_with("anomaly-events", "1000-1")

    def test_broker_acks_message_after_retry_success(self) -> None:
        channel = _TransientChannel("in_app", fail_n=1)
        retry = RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, broker, _, _ = _make_orchestrator(
            channels=[channel], retry_policy=retry
        )
        orch.process_once()

        broker.ack.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Per-channel isolation: one channel failing must not affect the other.
# ---------------------------------------------------------------------------


class TestChannelIsolation:
    def test_email_failure_does_not_block_in_app_success(self) -> None:
        in_app = _TransientChannel("in_app", fail_n=0)
        email = _TransientChannel("email", fail_n=10, exc=RuntimeError("smtp down"))
        retry = RetryPolicy(max_attempts=2, backoff_base=0.0, sleep_fn=lambda _: None)

        orch, _, _, captured = _make_orchestrator(
            channels=[in_app, email], retry_policy=retry
        )
        orch.process_once()

        # Two AlertRows persisted: one per channel.
        statuses = {row.channel: row.status for row in captured}
        assert statuses == {"in_app": "sent", "email": "failed"}


# ---------------------------------------------------------------------------
# 5. Backoff budget: total sleep budget is bounded.
# ---------------------------------------------------------------------------


class TestBackoffBudget:
    def test_total_sleep_budget_matches_geometric_series(self) -> None:
        """For an exhausted retry: total backoff = base * (1 + 2 + 4 + ...).

        This is a workflow-level invariant — if anyone changes the backoff
        function we want the dashboards/runbook to flag the new ceiling.
        """
        recorded: list[float] = []

        channel = _TransientChannel("email", fail_n=10)
        retry = RetryPolicy(
            max_attempts=4, backoff_base=2.0, sleep_fn=recorded.append
        )

        orch, _, _, _ = _make_orchestrator(channels=[channel], retry_policy=retry)
        orch.process_once()

        # 4 attempts → 3 inter-attempt sleeps: 2s, 4s, 8s = 14s total.
        assert recorded == [2.0, 4.0, 8.0]
        assert sum(recorded) == 14.0
