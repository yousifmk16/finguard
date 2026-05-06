"""
TST-01: Unit tests for services.stream.validation.

The publisher (ING-04) calls ``validate_publisher_event`` to enforce that
every message hitting the broker carries the full canonical schema. Tags
are the one optional field; everything else must be present.
"""

from __future__ import annotations

import sys
import types
import uuid

# services/stream/__init__.py re-exports the broker interface which depends
# on the optional ``redis`` package. Stub it out before the package import
# so this module remains a pure unit test (no external broker dependency).
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

import pytest  # noqa: E402

from services.normalizer.schema import NormalizationError  # noqa: E402
from services.stream.validation import (  # noqa: E402
    REQUIRED_CANONICAL_FIELDS,
    ensure_mapping,
    validate_publisher_event,
    validate_required_canonical_fields,
)


_BASE_PAYLOAD = {
    "event_id": str(uuid.uuid4()),
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


# ---------------------------------------------------------------------------
# ensure_mapping
# ---------------------------------------------------------------------------


class TestEnsureMapping:
    def test_dict_passes(self) -> None:
        assert ensure_mapping({"a": 1}) == {"a": 1}

    def test_list_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="JSON object"):
            ensure_mapping([1, 2, 3])

    def test_string_rejected(self) -> None:
        with pytest.raises(NormalizationError):
            ensure_mapping("not a dict")

    def test_none_rejected(self) -> None:
        with pytest.raises(NormalizationError):
            ensure_mapping(None)


# ---------------------------------------------------------------------------
# validate_required_canonical_fields
# ---------------------------------------------------------------------------


class TestValidateRequiredCanonicalFields:
    def test_full_payload_passes(self) -> None:
        # No exception expected.
        validate_required_canonical_fields(_BASE_PAYLOAD)

    def test_tags_field_is_optional(self) -> None:
        assert "tags" not in REQUIRED_CANONICAL_FIELDS

    def test_missing_account_id_listed_in_error(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "account_id"}
        with pytest.raises(NormalizationError, match="account_id"):
            validate_required_canonical_fields(payload)

    def test_multiple_missing_fields_all_listed(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k not in {"service", "region"}}
        with pytest.raises(NormalizationError) as exc:
            validate_required_canonical_fields(payload)
        msg = str(exc.value)
        assert "service" in msg
        assert "region" in msg


# ---------------------------------------------------------------------------
# validate_publisher_event
# ---------------------------------------------------------------------------


class TestValidatePublisherEvent:
    def test_full_payload_returns_canonical(self) -> None:
        out = validate_publisher_event(_BASE_PAYLOAD)
        assert out["account_id"] == "acct-001"
        assert out["service"] == "BigQuery"

    def test_missing_required_field_raises(self) -> None:
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "service"}
        with pytest.raises(NormalizationError, match="service"):
            validate_publisher_event(payload)

    def test_invalid_timestamp_raises(self) -> None:
        with pytest.raises(NormalizationError):
            validate_publisher_event({**_BASE_PAYLOAD, "timestamp": "not-a-date"})

    def test_negative_cost_raises(self) -> None:
        with pytest.raises(NormalizationError, match="non-negative"):
            validate_publisher_event({**_BASE_PAYLOAD, "cost_amount": -5.0})

    def test_tags_optional(self) -> None:
        # Required list excludes tags — payload without tags must succeed.
        out = validate_publisher_event(_BASE_PAYLOAD)
        assert out["tags"] is None

    def test_normalizes_timestamp_to_utc(self) -> None:
        out = validate_publisher_event({**_BASE_PAYLOAD, "timestamp": "2026-01-01T08:00:00-04:00"})
        assert out["timestamp"].endswith("+00:00")
