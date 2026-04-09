from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


CANONICAL_FIELDS = [
    "event_id",
    "timestamp",
    "provider",
    "account_id",
    "service",
    "region",
    "cost_amount",
    "usage_amount",
    "usage_unit",
    "tags",
    "source_type",
]


class NormalizationError(ValueError):
    """Raised when an event cannot be normalized into canonical schema."""


def parse_iso8601_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            raise NormalizationError("timestamp must not be empty.")
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise NormalizationError("timestamp must be a valid ISO-8601 value.") from exc
    else:
        raise NormalizationError("timestamp must be a datetime or ISO-8601 string.")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return dt.isoformat()


def coerce_non_negative_float(value: Any, field_name: str, default: float | None = None) -> float:
    if value is None:
        if default is None:
            raise NormalizationError(f"{field_name} is required.")
        return float(default)

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{field_name} must be numeric.") from exc

    if result < 0:
        raise NormalizationError(f"{field_name} must be non-negative.")
    return result


def coerce_string(value: Any, field_name: str, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise NormalizationError(f"{field_name} is required.")
        return default

    text = str(value).strip()
    if not text:
        if default is None:
            raise NormalizationError(f"{field_name} must not be empty.")
        return default
    return text


def coerce_tags(value: Any) -> dict[str, str] | None:
    if value in (None, "", {}):
        return None
    if not isinstance(value, Mapping):
        raise NormalizationError("tags must be a key-value mapping.")
    return {str(key): str(inner_value) for key, inner_value in value.items()}


def ensure_event_id(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return str(uuid.uuid4())
    return str(value)


def validate_canonical_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    canonical = {
        "event_id": ensure_event_id(payload.get("event_id")),
        "timestamp": parse_iso8601_timestamp(payload.get("timestamp")),
        "provider": coerce_string(payload.get("provider"), "provider", default="gcp"),
        "account_id": coerce_string(payload.get("account_id"), "account_id"),
        "service": coerce_string(payload.get("service"), "service"),
        "region": coerce_string(payload.get("region"), "region", default="global"),
        "cost_amount": coerce_non_negative_float(payload.get("cost_amount"), "cost_amount"),
        "usage_amount": coerce_non_negative_float(payload.get("usage_amount"), "usage_amount", default=0.0),
        "usage_unit": coerce_string(payload.get("usage_unit"), "usage_unit", default="unit"),
        "tags": coerce_tags(payload.get("tags")),
        "source_type": coerce_string(payload.get("source_type"), "source_type", default="stream"),
    }
    return canonical
