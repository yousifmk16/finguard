"""Unit tests for ALT-02: dedup key strategy."""

from app.alerts.dedup import build_dedup_key


def test_key_format():
    assert build_dedup_key("abc-123", "in_app") == "abc-123:in_app"


def test_different_channels_produce_different_keys():
    k1 = build_dedup_key("abc-123", "in_app")
    k2 = build_dedup_key("abc-123", "email")
    assert k1 != k2


def test_different_anomalies_produce_different_keys():
    k1 = build_dedup_key("aaa-111", "in_app")
    k2 = build_dedup_key("bbb-222", "in_app")
    assert k1 != k2


def test_key_is_deterministic():
    assert build_dedup_key("x", "y") == build_dedup_key("x", "y")


def test_key_is_string():
    assert isinstance(build_dedup_key("id", "chan"), str)
