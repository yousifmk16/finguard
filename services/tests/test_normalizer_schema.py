"""
TST-01: Unit tests for services.normalizer.schema.

Covers the canonical event coercion + validation primitives that ING-06
relies on:
    parse_iso8601_timestamp
    coerce_non_negative_float
    coerce_string
    coerce_tags
    ensure_event_id
    validate_canonical_event
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from services.normalizer.schema import (
    NormalizationError,
    coerce_non_negative_float,
    coerce_string,
    coerce_tags,
    ensure_event_id,
    parse_iso8601_timestamp,
    validate_canonical_event,
)


# ---------------------------------------------------------------------------
# parse_iso8601_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_z_suffix_accepted(self) -> None:
        out = parse_iso8601_timestamp("2026-01-01T12:00:00Z")
        assert out.endswith("+00:00")

    def test_offset_normalized_to_utc(self) -> None:
        out = parse_iso8601_timestamp("2026-01-01T08:00:00-04:00")
        # 08:00 in -04:00 is 12:00 UTC
        assert "12:00:00" in out
        assert out.endswith("+00:00")

    def test_naive_string_assumed_utc(self) -> None:
        out = parse_iso8601_timestamp("2026-01-01T12:00:00")
        assert "12:00:00" in out
        assert out.endswith("+00:00")

    def test_datetime_passed_through(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        assert parse_iso8601_timestamp(dt) == dt.isoformat()

    def test_naive_datetime_gets_utc(self) -> None:
        dt = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
        out = parse_iso8601_timestamp(dt)
        assert out.endswith("+00:00")

    def test_non_utc_datetime_converted(self) -> None:
        dt = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
        out = parse_iso8601_timestamp(dt)
        assert "12:00:00" in out

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="must not be empty"):
            parse_iso8601_timestamp("   ")

    def test_garbage_string_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="ISO-8601"):
            parse_iso8601_timestamp("not-a-date")

    def test_non_string_non_datetime_rejected(self) -> None:
        with pytest.raises(NormalizationError):
            parse_iso8601_timestamp(12345)


# ---------------------------------------------------------------------------
# coerce_non_negative_float
# ---------------------------------------------------------------------------


class TestCoerceNonNegativeFloat:
    def test_int_coerced(self) -> None:
        assert coerce_non_negative_float(5, "x") == 5.0

    def test_string_number_coerced(self) -> None:
        assert coerce_non_negative_float("3.14", "x") == pytest.approx(3.14)

    def test_zero_accepted(self) -> None:
        assert coerce_non_negative_float(0, "x") == 0.0

    def test_negative_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="non-negative"):
            coerce_non_negative_float(-0.01, "cost_amount")

    def test_non_numeric_string_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="numeric"):
            coerce_non_negative_float("abc", "cost_amount")

    def test_none_with_default_returns_default(self) -> None:
        assert coerce_non_negative_float(None, "x", default=2.0) == 2.0

    def test_none_without_default_raises(self) -> None:
        with pytest.raises(NormalizationError, match="required"):
            coerce_non_negative_float(None, "cost_amount")

    def test_field_name_in_error(self) -> None:
        with pytest.raises(NormalizationError, match="usage_amount"):
            coerce_non_negative_float(-1, "usage_amount")


# ---------------------------------------------------------------------------
# coerce_string
# ---------------------------------------------------------------------------


class TestCoerceString:
    def test_strips_whitespace(self) -> None:
        assert coerce_string("  hello  ", "x") == "hello"

    def test_non_string_stringified(self) -> None:
        assert coerce_string(42, "x") == "42"

    def test_none_with_default(self) -> None:
        assert coerce_string(None, "x", default="fallback") == "fallback"

    def test_none_without_default_raises(self) -> None:
        with pytest.raises(NormalizationError, match="required"):
            coerce_string(None, "service")

    def test_blank_with_default_returns_default(self) -> None:
        assert coerce_string("   ", "x", default="d") == "d"

    def test_blank_without_default_raises(self) -> None:
        with pytest.raises(NormalizationError, match="empty"):
            coerce_string("", "service")


# ---------------------------------------------------------------------------
# coerce_tags
# ---------------------------------------------------------------------------


class TestCoerceTags:
    def test_none_returns_none(self) -> None:
        assert coerce_tags(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert coerce_tags("") is None

    def test_empty_dict_returns_none(self) -> None:
        assert coerce_tags({}) is None

    def test_dict_passes_through(self) -> None:
        assert coerce_tags({"env": "prod"}) == {"env": "prod"}

    def test_values_stringified(self) -> None:
        assert coerce_tags({"count": 5, "enabled": True}) == {"count": "5", "enabled": "True"}

    def test_keys_stringified(self) -> None:
        assert coerce_tags({1: "one"}) == {"1": "one"}

    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="key-value mapping"):
            coerce_tags(["env", "prod"])


# ---------------------------------------------------------------------------
# ensure_event_id
# ---------------------------------------------------------------------------


class TestEnsureEventId:
    def test_passthrough_when_present(self) -> None:
        assert ensure_event_id("abc-123") == "abc-123"

    def test_generated_when_none(self) -> None:
        out = ensure_event_id(None)
        assert isinstance(uuid.UUID(out), uuid.UUID)

    def test_generated_when_empty(self) -> None:
        out = ensure_event_id("")
        assert isinstance(uuid.UUID(out), uuid.UUID)

    def test_generated_when_blank(self) -> None:
        out = ensure_event_id("   ")
        assert isinstance(uuid.UUID(out), uuid.UUID)

    def test_each_generated_id_unique(self) -> None:
        ids = {ensure_event_id(None) for _ in range(20)}
        assert len(ids) == 20


# ---------------------------------------------------------------------------
# validate_canonical_event
# ---------------------------------------------------------------------------


_BASE_PAYLOAD = {
    "timestamp": "2026-01-01T00:00:00Z",
    "provider": "gcp",
    "account_id": "acct-001",
    "service": "BigQuery",
    "region": "us-central1",
    "cost_amount": 12.5,
    "usage_amount": 100.0,
    "usage_unit": "core-hours",
    "tags": {"env": "prod"},
    "source_type": "live",
}


class TestValidateCanonicalEvent:
    def test_returns_all_canonical_fields(self) -> None:
        out = validate_canonical_event(_BASE_PAYLOAD)
        assert set(out.keys()) >= {
            "event_id", "timestamp", "provider", "account_id", "service",
            "region", "cost_amount", "usage_amount", "usage_unit", "tags",
            "source_type",
        }

    def test_generates_event_id_when_missing(self) -> None:
        out = validate_canonical_event(_BASE_PAYLOAD)
        assert isinstance(uuid.UUID(out["event_id"]), uuid.UUID)

    def test_preserves_provided_event_id(self) -> None:
        eid = str(uuid.uuid4())
        out = validate_canonical_event({**_BASE_PAYLOAD, "event_id": eid})
        assert out["event_id"] == eid

    def test_normalizes_timestamp_to_utc(self) -> None:
        out = validate_canonical_event(_BASE_PAYLOAD)
        assert out["timestamp"].endswith("+00:00")

    def test_default_provider_is_gcp(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "provider"}
        out = validate_canonical_event(payload)
        assert out["provider"] == "gcp"

    def test_default_region_is_global(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "region"}
        out = validate_canonical_event(payload)
        assert out["region"] == "global"

    def test_default_usage_amount_is_zero(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "usage_amount"}
        out = validate_canonical_event(payload)
        assert out["usage_amount"] == 0.0

    def test_default_source_type_is_stream(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "source_type"}
        out = validate_canonical_event(payload)
        assert out["source_type"] == "stream"

    def test_missing_account_id_raises(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "account_id"}
        with pytest.raises(NormalizationError, match="account_id"):
            validate_canonical_event(payload)

    def test_missing_service_raises(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "service"}
        with pytest.raises(NormalizationError, match="service"):
            validate_canonical_event(payload)

    def test_missing_cost_amount_raises(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "cost_amount"}
        with pytest.raises(NormalizationError, match="cost_amount"):
            validate_canonical_event(payload)

    def test_negative_cost_raises(self) -> None:
        with pytest.raises(NormalizationError, match="non-negative"):
            validate_canonical_event({**_BASE_PAYLOAD, "cost_amount": -1.0})

    def test_invalid_timestamp_raises(self) -> None:
        with pytest.raises(NormalizationError):
            validate_canonical_event({**_BASE_PAYLOAD, "timestamp": "not-a-date"})

    def test_tags_can_be_omitted(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "tags"}
        out = validate_canonical_event(payload)
        assert out["tags"] is None
