"""Unit tests for ALT-04 (InAppChannel), ALT-05 (EmailChannel), ALT-06 (RetryPolicy)."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.alerts.channels.email import EmailChannel
from app.alerts.channels.in_app import InAppChannel
from app.alerts.retry import RetryPolicy
from services.detection.anomaly_emitter import AnomalyEvent

_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


def _event(**overrides) -> AnomalyEvent:
    defaults = dict(
        anomaly_id="aaaaaaaa-0000-0000-0000-000000000001",
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
    defaults.update(overrides)
    return AnomalyEvent(**defaults)


# ---------------------------------------------------------------------------
# ALT-04: InAppChannel
# ---------------------------------------------------------------------------

class TestInAppChannel:
    def test_send_does_not_raise(self):
        InAppChannel().send(_event())

    def test_name_is_in_app(self):
        assert InAppChannel.name == "in_app"


# ---------------------------------------------------------------------------
# ALT-05: EmailChannel
# ---------------------------------------------------------------------------

class TestEmailChannelStubMode:
    """No SMTP_HOST → stub mode: logs and does not raise."""

    def test_send_without_host_does_not_raise(self):
        ch = EmailChannel(smtp_host=None, recipients=[])
        ch.send(_event())  # must not raise

    def test_name_is_email(self):
        assert EmailChannel.name == "email"

    def test_send_no_recipients_logs_warning(self, caplog):
        import logging
        ch = EmailChannel(smtp_host="smtp.example.com", recipients=[])
        with caplog.at_level(logging.WARNING, logger="app.alerts.channels.email"):
            ch.send(_event())
        assert any("ALERT_RECIPIENTS" in r.message for r in caplog.records)


class TestEmailChannelSMTPMode:
    def test_smtp_send_called_with_host(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user=None,
            smtp_password=None,
            from_address="alerts@finguard.io",
            recipients=["ops@example.com"],
        )
        with patch("smtplib.SMTP") as MockSMTP:
            instance = MockSMTP.return_value.__enter__.return_value
            ch.send(_event())
            instance.send_message.assert_called_once()

    def test_smtp_raises_on_connection_error(self):
        ch = EmailChannel(
            smtp_host="bad-host",
            recipients=["ops@example.com"],
        )
        with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            with pytest.raises(OSError):
                ch.send(_event())

    def test_message_subject_contains_severity_and_service(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            recipients=["ops@example.com"],
        )
        built: list = []
        original_build = ch._build_message

        def capture(ev):
            msg = original_build(ev)
            built.append(msg)
            return msg

        ch._build_message = capture
        with patch("smtplib.SMTP") as MockSMTP:
            MockSMTP.return_value.__enter__.return_value = MagicMock()
            ch.send(_event(severity="high", service="Compute"))

        assert built
        assert "High" in built[0]["Subject"]
        assert "Compute" in built[0]["Subject"]

    def test_login_called_when_credentials_set(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_user="user",
            smtp_password="pass",
            recipients=["x@example.com"],
        )
        with patch("smtplib.SMTP") as MockSMTP:
            instance = MockSMTP.return_value.__enter__.return_value
            ch.send(_event())
            instance.login.assert_called_once_with("user", "pass")

    def test_no_login_without_credentials(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_user=None,
            smtp_password=None,
            recipients=["x@example.com"],
        )
        with patch("smtplib.SMTP") as MockSMTP:
            instance = MockSMTP.return_value.__enter__.return_value
            ch.send(_event())
            instance.login.assert_not_called()


# ---------------------------------------------------------------------------
# ALT-06: RetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def _no_sleep(self) -> RetryPolicy:
        return RetryPolicy(max_attempts=3, backoff_base=0.0, sleep_fn=lambda _: None)

    def test_succeeds_on_first_try(self):
        results = []
        RetryPolicy(sleep_fn=lambda _: None).execute(lambda: results.append(1))
        assert results == [1]

    def test_retries_on_failure_then_succeeds(self):
        calls = [0]

        def flaky():
            calls[0] += 1
            if calls[0] < 3:
                raise RuntimeError("transient")

        self._no_sleep().execute(flaky)
        assert calls[0] == 3

    def test_raises_after_max_attempts(self):
        policy = self._no_sleep()
        with pytest.raises(RuntimeError, match="always fails"):
            policy.execute(lambda: (_ for _ in ()).throw(RuntimeError("always fails")))

    def test_max_attempts_one_no_retry(self):
        policy = RetryPolicy(max_attempts=1, sleep_fn=lambda _: None)
        calls = [0]

        def boom():
            calls[0] += 1
            raise ValueError("immediate fail")

        with pytest.raises(ValueError):
            policy.execute(boom)
        assert calls[0] == 1

    def test_sleep_called_between_attempts(self):
        slept: list[float] = []
        policy = RetryPolicy(max_attempts=3, backoff_base=2.0, sleep_fn=slept.append)
        calls = [0]

        def fail_twice():
            calls[0] += 1
            if calls[0] < 3:
                raise RuntimeError("retry me")

        policy.execute(fail_twice)
        assert len(slept) == 2      # slept twice (before attempt 2 and 3)
        assert slept[0] == pytest.approx(2.0)   # 2.0 * 2^0
        assert slept[1] == pytest.approx(4.0)   # 2.0 * 2^1

    def test_invalid_max_attempts_raises(self):
        with pytest.raises(ValueError):
            RetryPolicy(max_attempts=0, sleep_fn=lambda _: None).execute(lambda: None)

    def test_returns_value_from_fn(self):
        result = RetryPolicy(sleep_fn=lambda _: None).execute(lambda: 42)
        assert result == 42
