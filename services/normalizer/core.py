from __future__ import annotations

from typing import Any, Callable

from .providers.gcp import normalize_gcp_event
from .schema import NormalizationError, validate_canonical_event


ProviderNormalizer = Callable[[dict[str, Any]], dict[str, Any]]


PROVIDER_NORMALIZERS: dict[str, ProviderNormalizer] = {
    "gcp": normalize_gcp_event,
}


def normalize_event(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "gcp").strip().lower()
    if _looks_canonical(payload):
        return validate_canonical_event(payload)

    normalizer = PROVIDER_NORMALIZERS.get(provider)
    if normalizer is None:
        raise NormalizationError(f"Unsupported provider '{provider}'.")
    normalized = normalizer(payload)
    return validate_canonical_event(normalized)


def _looks_canonical(payload: dict[str, Any]) -> bool:
    canonical_keys = {
        "event_id",
        "timestamp",
        "provider",
        "account_id",
        "service",
        "region",
        "cost_amount",
        "usage_amount",
        "usage_unit",
        "source_type",
    }
    return canonical_keys.issubset(payload.keys())
