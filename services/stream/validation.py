from __future__ import annotations

from typing import Any

from services.normalizer.schema import CANONICAL_FIELDS, NormalizationError, validate_canonical_event


REQUIRED_CANONICAL_FIELDS = tuple(field for field in CANONICAL_FIELDS if field != "tags")


def ensure_mapping(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NormalizationError("Event payload must be a JSON object.")
    return payload


def validate_required_canonical_fields(payload: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_CANONICAL_FIELDS if field not in payload]
    if missing:
        raise NormalizationError(f"Missing required canonical fields: {', '.join(missing)}")


def validate_publisher_event(payload: dict[str, Any]) -> dict[str, Any]:
    validate_required_canonical_fields(payload)
    return validate_canonical_event(payload)
