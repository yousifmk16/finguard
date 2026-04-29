"""Unit tests for ALT-03: cooldown windows."""

from datetime import UTC, datetime, timedelta

from app.alerts.cooldown import CooldownTracker


def _tracker(cooldown_seconds: int = 60) -> CooldownTracker:
    """Fresh tracker with injected clock."""
    now = [datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)]
    return CooldownTracker(cooldown_seconds=cooldown_seconds, now_fn=lambda: now[0]), now


class TestInitialState:
    def test_no_cooldown_initially(self):
        t, _ = _tracker()
        assert t.is_cooling_down("acct", "svc", "us") is False

    def test_different_series_independent(self):
        t, now = _tracker()
        t.record_alerted("acct", "svc-a", "us")
        assert t.is_cooling_down("acct", "svc-b", "us") is False


class TestCooldownActive:
    def test_immediately_after_alert(self):
        t, _ = _tracker(cooldown_seconds=3600)
        t.record_alerted("acct", "svc", "us")
        assert t.is_cooling_down("acct", "svc", "us") is True

    def test_still_active_before_window_expires(self):
        t, now = _tracker(cooldown_seconds=3600)
        t.record_alerted("acct", "svc", "us")
        now[0] += timedelta(seconds=3599)
        assert t.is_cooling_down("acct", "svc", "us") is True

    def test_expires_after_window(self):
        t, now = _tracker(cooldown_seconds=3600)
        t.record_alerted("acct", "svc", "us")
        now[0] += timedelta(seconds=3601)
        assert t.is_cooling_down("acct", "svc", "us") is False

    def test_exact_boundary_still_active(self):
        t, now = _tracker(cooldown_seconds=60)
        t.record_alerted("acct", "svc", "us")
        now[0] += timedelta(seconds=60)
        # elapsed == cooldown_seconds is NOT cooling down (strict <)
        assert t.is_cooling_down("acct", "svc", "us") is False


class TestReset:
    def test_reset_clears_series(self):
        t, _ = _tracker()
        t.record_alerted("acct", "svc", "us")
        t.reset("acct", "svc", "us")
        assert t.is_cooling_down("acct", "svc", "us") is False

    def test_reset_all_clears_everything(self):
        t, _ = _tracker()
        t.record_alerted("a", "s1", "r")
        t.record_alerted("a", "s2", "r")
        t.reset_all()
        assert t.is_cooling_down("a", "s1", "r") is False
        assert t.is_cooling_down("a", "s2", "r") is False

    def test_reset_nonexistent_is_noop(self):
        t, _ = _tracker()
        t.reset("unknown", "svc", "us")  # should not raise


class TestRecordUpdates:
    def test_re_alert_resets_window(self):
        t, now = _tracker(cooldown_seconds=60)
        t.record_alerted("acct", "svc", "us")
        now[0] += timedelta(seconds=61)  # expired
        assert t.is_cooling_down("acct", "svc", "us") is False
        t.record_alerted("acct", "svc", "us")  # re-alert
        assert t.is_cooling_down("acct", "svc", "us") is True
