"""
GCP-specific event normalizer.

Translates raw GCP billing export fields into the FinGuard canonical
event schema (ARC-04) so that downstream services see a uniform shape.
"""

from __future__ import annotations

from typing import Any

from ..schema import (
    coerce_non_negative_float,
    coerce_string,
    coerce_tags,
    ensure_event_id,
    parse_iso8601_timestamp,
)


def normalize_gcp_event(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Map a GCP billing export record to the canonical schema.

    GCP billing exports use field names like ``cost``, ``project.id``,
    ``sku.description``, ``location.region``, and ``usage.amount`` /
    ``usage.unit``.  This function re-keys and coerces those into the
    canonical fields expected by ``validate_canonical_event``.
    """
    project = raw.get("project", {}) if isinstance(raw.get("project"), dict) else {}
    sku = raw.get("sku", {}) if isinstance(raw.get("sku"), dict) else {}
    location = raw.get("location", {}) if isinstance(raw.get("location"), dict) else {}
    usage = raw.get("usage", {}) if isinstance(raw.get("usage"), dict) else {}

    return {
        "event_id": ensure_event_id(raw.get("event_id")),
        "timestamp": parse_iso8601_timestamp(
            raw.get("usage_start_time") or raw.get("timestamp")
        ),
        "provider": "gcp",
        "account_id": coerce_string(
            raw.get("billing_account_id") or project.get("id"),
            "account_id",
        ),
        "service": coerce_string(
            raw.get("service", {}).get("description")
            if isinstance(raw.get("service"), dict)
            else raw.get("service") or sku.get("description"),
            "service",
        ),
        "region": coerce_string(
            location.get("region") or raw.get("region"),
            "region",
            default="global",
        ),
        "cost_amount": coerce_non_negative_float(
            raw.get("cost") or raw.get("cost_amount"), "cost_amount"
        ),
        "usage_amount": coerce_non_negative_float(
            usage.get("amount") or raw.get("usage_amount"),
            "usage_amount",
            default=0.0,
        ),
        "usage_unit": coerce_string(
            usage.get("unit") or raw.get("usage_unit"),
            "usage_unit",
            default="unit",
        ),
        "tags": coerce_tags(raw.get("labels") or raw.get("tags")),
        "source_type": coerce_string(
            raw.get("source_type"), "source_type", default="stream"
        ),
    }
