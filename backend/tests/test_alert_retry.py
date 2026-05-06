"""
TST-03: Unit tests for app.alerts.retry (ALT-06).

``RetryPolicy`` is the wrapper used by the alert orchestrator to retry
flaky channel sends with exponential backoff. ``sleep_fn`` is injectable
so these tests run instantly without real delays.
"""

from __future__ import annotations

from typing import Callable

import pytest

from app.alerts.retry import RetryPolicy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Counter:
    """Stub callable that fails N times before succeeding."""

    def __init__(self, fail_n: int, exc: Exception | None = None) -> None:
        self.fail_n = fail_n
        self.calls = 0
        self.exc = exc or RuntimeError("boom")

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.fail_n:
            raise self.exc
        return "ok"


def _record_sleeps() -> tuple[list[float], Callable[[float], None]]:
    """Return (recorded list, no-delay sleep stub) for inspection."""
    recorded: list[float] = []

    def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    return recorded, fake_sleep


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_returns_value_on_first_attempt(self) -> None:
        policy = RetryPolicy(max_attempts=3, sleep_fn=lambda _: None)
        assert policy.execute(lambda: 42) == 42

    def test_first_attempt_does_not_sleep(self) -> None:
        recorded, fake_sleep = _record_sleeps()
        policy = RetryPolicy(max_attempts=3, sleep_fn=fake_sleep)
        policy.execute(lambda: "ok")
        assert recorded == []

    def test_calls_function_exactly_once_when_succeeds(self) -> None:
        counter = _Counter(fail_n=0)
        policy = RetryPolicy(max_attempts=5, sleep_fn=lambda _: None)
        policy.execute(counter)
        assert counter.calls == 1


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


class TestRetry:
    def test_succeeds_after_transient_failures(self) -> None:
        counter = _Counter(fail_n=2)
        policy = RetryPolicy(max_attempts=3, sleep_fn=lambda _: None)
        assert policy.execute(counter) == "ok"
        assert counter.calls == 3

    def test_calls_max_attempts_times_when_all_fail(self) -> None:
        counter = _Counter(fail_n=10)
        policy = RetryPolicy(max_attempts=4, sleep_fn=lambda _: None)
        with pytest.raises(RuntimeError):
            policy.execute(counter)
        assert counter.calls == 4

    def test_reraises_last_exception(self) -> None:
        unique_exc = ValueError("fourth-attempt")
        counter = _Counter(fail_n=10, exc=unique_exc)
        policy = RetryPolicy(max_attempts=3, sleep_fn=lambda _: None)
        with pytest.raises(ValueError, match="fourth-attempt"):
            policy.execute(counter)


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_exponential_doubling(self) -> None:
        # base=1.0 → sleeps before attempts 2..5 are 1, 2, 4, 8
        recorded, fake_sleep = _record_sleeps()
        counter = _Counter(fail_n=10)
        policy = RetryPolicy(max_attempts=5, backoff_base=1.0, sleep_fn=fake_sleep)
        with pytest.raises(RuntimeError):
            policy.execute(counter)
        # Sleeps occur between failed attempts only — last failure has no sleep.
        assert recorded == [1.0, 2.0, 4.0, 8.0]

    def test_backoff_scales_with_base(self) -> None:
        recorded, fake_sleep = _record_sleeps()
        counter = _Counter(fail_n=10)
        policy = RetryPolicy(max_attempts=4, backoff_base=0.5, sleep_fn=fake_sleep)
        with pytest.raises(RuntimeError):
            policy.execute(counter)
        # 0.5, 1.0, 2.0
        assert recorded == [0.5, 1.0, 2.0]

    def test_no_sleep_after_final_failure(self) -> None:
        # Even when all attempts fail, the loop must not sleep after the last
        # one — the caller should fail fast and surface the exception.
        recorded, fake_sleep = _record_sleeps()
        policy = RetryPolicy(max_attempts=2, backoff_base=10.0, sleep_fn=fake_sleep)
        with pytest.raises(RuntimeError):
            policy.execute(_Counter(fail_n=10))
        # Two attempts → exactly one sleep between them.
        assert recorded == [10.0]

    def test_no_sleep_when_succeeds_on_retry(self) -> None:
        # Two attempts, fails once → one sleep, then succeeds, no further sleep.
        recorded, fake_sleep = _record_sleeps()
        policy = RetryPolicy(max_attempts=3, backoff_base=2.0, sleep_fn=fake_sleep)
        policy.execute(_Counter(fail_n=1))
        assert recorded == [2.0]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_max_attempts_zero_raises(self) -> None:
        policy = RetryPolicy(max_attempts=0, sleep_fn=lambda _: None)
        with pytest.raises(ValueError, match="max_attempts"):
            policy.execute(lambda: "never")

    def test_negative_max_attempts_raises(self) -> None:
        policy = RetryPolicy(max_attempts=-1, sleep_fn=lambda _: None)
        with pytest.raises(ValueError, match="max_attempts"):
            policy.execute(lambda: "never")

    def test_single_attempt_no_retries(self) -> None:
        recorded, fake_sleep = _record_sleeps()
        counter = _Counter(fail_n=10)
        policy = RetryPolicy(max_attempts=1, sleep_fn=fake_sleep)
        with pytest.raises(RuntimeError):
            policy.execute(counter)
        assert counter.calls == 1
        assert recorded == []  # never sleeps

    def test_does_not_swallow_keyboard_interrupt(self) -> None:
        # KeyboardInterrupt is a BaseException, not Exception — RetryPolicy
        # only catches Exception so an interrupt must propagate immediately.
        def raise_interrupt() -> None:
            raise KeyboardInterrupt()

        policy = RetryPolicy(max_attempts=5, sleep_fn=lambda _: None)
        with pytest.raises(KeyboardInterrupt):
            policy.execute(raise_interrupt)

    def test_default_sleep_is_time_sleep(self) -> None:
        # Just check it's set without invoking it (so the test stays fast).
        import time
        policy = RetryPolicy()
        assert policy.sleep_fn is time.sleep

    def test_function_return_value_preserved(self) -> None:
        sentinel = {"ok": True, "id": 42}
        policy = RetryPolicy(max_attempts=2, sleep_fn=lambda _: None)
        assert policy.execute(lambda: sentinel) is sentinel
