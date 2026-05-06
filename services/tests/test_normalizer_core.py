"""
TST-01: Unit tests for services.normalizer.core.

Covers the provider-routing layer that decides whether an incoming
payload is already canonical or needs provider-specific normalization
before validation.
"""

from __future__ import annotations

import uuid

import pytest

from services.normalizer.core import normalize_event
from services.normalizer.schema import NormalizationError


_CANONICAL = {
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

_RAW_GCP = {
    "billing_account_id": "acct-001",
    "service_description": "BigQuery",
    "location_region": "us-central1",
    "usage_start_time": "2026-01-01T00:00:00Z",
    "cost": 1.0,
    "usage_amount": 1.0,
    "usage_unit": "byte-seconds",
    "provider": "gcp",
}


class TestProviderRouting:
    def test_canonical_payload_validated_directly(self) -> None:
        out = normalize_event(_CANONICAL)
        assert out["account_id"] == "acct-001"
        assert out["service"] == "BigQuery"

    def test_canonical_preserves_event_id(self) -> None:
        out = normalize_event(_CANONICAL)
        assert out["event_id"] == _CANONICAL["event_id"]

    def test_raw_gcp_routed_through_normalizer(self) -> None:
        out = normalize_event(_RAW_GCP)
        # The GCP normalizer should resolve service/account from the raw fields.
        assert out["service"] == "BigQuery"
        assert out["account_id"] == "acct-001"
        assert out["region"] == "us-central1"

    def test_default_provider_is_gcp(self) -> None:
        # Drop the provider field — core defaults to gcp routing.
        payload = {k: v for k, v in _RAW_GCP.items() if k != "provider"}
        out = normalize_event(payload)
        assert out["provider"] == "gcp"

    def test_unsupported_provider_raises(self) -> None:
        with pytest.raises(NormalizationError, match="Unsupported provider"):
            normalize_event({**_RAW_GCP, "provider": "oracle"})

    def test_provider_case_normalized(self) -> None:
        # "GCP" / "Gcp" / extra spaces should all route to the same handler.
        out = normalize_event({**_RAW_GCP, "provider": "  GCP  "})
        assert out["provider"] == "gcp"
