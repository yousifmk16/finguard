<<<<<<< HEAD
=======
"""
GCP-specific event normalizer.

Translates raw GCP billing export fields into the FinGuard canonical
event schema (ARC-04) so that downstream services see a uniform shape.
"""

>>>>>>> d0178c5a379821724d9b4e14d1582788a88b0c73
from __future__ import annotations

from typing import Any

<<<<<<< HEAD
from services.normalizer.schema import (
    NormalizationError,
=======
from ..schema import (
>>>>>>> d0178c5a379821724d9b4e14d1582788a88b0c73
    coerce_non_negative_float,
    coerce_string,
    coerce_tags,
    ensure_event_id,
    parse_iso8601_timestamp,
)


<<<<<<< HEAD
def _extract_service(payload: dict[str, Any]) -> str:
    """Resolve service name from GCP billing export.

    Tries:
      1. ``service.description`` (BigQuery export nested dict)
      2. ``service_description`` (flattened export)
      3. ``service`` (pre-mapped field)
    """
    service_block = payload.get("service")
    if isinstance(service_block, dict):
        desc = service_block.get("description")
        if desc and str(desc).strip():
            return str(desc).strip()

    for key in ("service_description", "service"):
        val = payload.get(key)
        if val and str(val).strip():
            return str(val).strip()

    raise NormalizationError("GCP event is missing a resolvable 'service' field.")


def _extract_region(payload: dict[str, Any]) -> str:
    """Resolve region from GCP billing export.

    Tries:
      1. ``location.region`` (BigQuery nested dict)
      2. ``location.location`` (multi-region buckets like "US", "EU")
      3. ``location_region`` / ``region`` (flattened)
    Falls back to ``"global"`` if none are present.
    """
    location_block = payload.get("location")
    if isinstance(location_block, dict):
        region = location_block.get("region") or location_block.get("location")
        if region and str(region).strip():
            return str(region).strip()

    for key in ("location_region", "region"):
        val = payload.get(key)
        if val and str(val).strip():
            return str(val).strip()

    return "global"


def _extract_account_id(payload: dict[str, Any]) -> str:
    """Resolve account identifier from GCP billing export.

    Tries:
      1. ``billing_account_id`` (top-level, always present in exports)
      2. ``project.id`` (BigQuery nested dict)
      3. ``project_id`` (flattened)
      4. ``account_id`` (pre-mapped)
    """
    for key in ("billing_account_id", "account_id"):
        val = payload.get(key)
        if val and str(val).strip():
            return str(val).strip()

    project_block = payload.get("project")
    if isinstance(project_block, dict):
        proj_id = project_block.get("id")
        if proj_id and str(proj_id).strip():
            return str(proj_id).strip()

    val = payload.get("project_id")
    if val and str(val).strip():
        return str(val).strip()

    raise NormalizationError("GCP event is missing a resolvable account/project identifier.")


def _extract_timestamp(payload: dict[str, Any]) -> str:
    """Resolve event timestamp from GCP billing export.

    Tries ``usage_start_time`` first (most precise), then ``export_time``,
    then the generic ``timestamp`` field.
    """
    for key in ("usage_start_time", "export_time", "timestamp"):
        val = payload.get(key)
        if val is not None:
            return parse_iso8601_timestamp(val)

    raise NormalizationError("GCP event is missing a resolvable timestamp field.")


def _extract_usage(payload: dict[str, Any]) -> tuple[float, str]:
    """Resolve usage amount and unit.

    Tries:
      1. ``usage`` nested dict with ``amount`` / ``unit`` keys (BigQuery export)
      2. ``usage_amount`` / ``usage_unit`` flat keys
    """
    usage_block = payload.get("usage")
    if isinstance(usage_block, dict):
        amount = coerce_non_negative_float(
            usage_block.get("amount"), "usage.amount", default=0.0
        )
        unit = coerce_string(
            usage_block.get("unit"), "usage.unit", default="unit"
        )
        return amount, unit

    amount = coerce_non_negative_float(
        payload.get("usage_amount"), "usage_amount", default=0.0
    )
    unit = coerce_string(payload.get("usage_unit"), "usage_unit", default="unit")
    return amount, unit


def _extract_labels(payload: dict[str, Any]) -> dict[str, str] | None:
    """Resolve labels/tags from GCP billing export.

    GCP BigQuery export provides labels as a list of ``{"key": ..., "value": ...}``
    records.  A plain dict is also accepted (pre-mapped or synthetic events).
    """
    raw = payload.get("labels") or payload.get("tags")
    if raw is None:
        return None

    if isinstance(raw, list):
        result: dict[str, str] = {}
        for item in raw:
            if isinstance(item, dict):
                key = item.get("key")
                value = item.get("value", "")
                if key is not None:
                    result[str(key)] = str(value)
        return result or None

    return coerce_tags(raw)


def normalize_gcp_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a raw GCP billing export record to the canonical billing event schema.

    Supports both the BigQuery nested export format and simplified flat payloads.
    Raises ``NormalizationError`` for unresolvable required fields.
    """
    cost_amount = coerce_non_negative_float(
        payload.get("cost"), "cost", default=None
    ) if payload.get("cost") is not None else coerce_non_negative_float(
        payload.get("cost_amount"), "cost_amount"
    )

    usage_amount, usage_unit = _extract_usage(payload)

    return {
        "event_id": ensure_event_id(payload.get("event_id")),
        "timestamp": _extract_timestamp(payload),
        "provider": "gcp",
        "account_id": _extract_account_id(payload),
        "service": _extract_service(payload),
        "region": _extract_region(payload),
        "cost_amount": cost_amount,
        "usage_amount": usage_amount,
        "usage_unit": usage_unit,
        "tags": _extract_labels(payload),
        "source_type": str(payload.get("source_type", "live")),
=======
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
>>>>>>> d0178c5a379821724d9b4e14d1582788a88b0c73
    }
