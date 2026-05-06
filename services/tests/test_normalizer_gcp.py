"""
TST-01: Unit tests for services.normalizer.providers.gcp.

Covers GCP BigQuery export normalization — both the nested export shape
(``service.description``, ``location.region``, ``usage.amount``, label list)
and the simplified flat shape used by tests / synthetic generators.
"""

from __future__ import annotations

import pytest

from services.normalizer.providers.gcp import normalize_gcp_event
from services.normalizer.schema import NormalizationError


def _flat_payload(**overrides):
    base = {
        "billing_account_id": "acct-001",
        "service_description": "BigQuery",
        "location_region": "us-central1",
        "usage_start_time": "2026-01-01T00:00:00Z",
        "cost": 5.0,
        "usage_amount": 100.0,
        "usage_unit": "core-hours",
    }
    base.update(overrides)
    return base


def _nested_payload(**overrides):
    base = {
        "service": {"description": "Compute Engine"},
        "project": {"id": "proj-123"},
        "location": {"region": "europe-west1"},
        "usage_start_time": "2026-01-01T00:00:00Z",
        "cost": 9.5,
        "usage": {"amount": 42.0, "unit": "byte-seconds"},
        "labels": [{"key": "env", "value": "prod"}, {"key": "team", "value": "data"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Service resolution
# ---------------------------------------------------------------------------


class TestServiceResolution:
    def test_nested_service_description(self) -> None:
        out = normalize_gcp_event(_nested_payload())
        assert out["service"] == "Compute Engine"

    def test_flat_service_description(self) -> None:
        out = normalize_gcp_event(_flat_payload())
        assert out["service"] == "BigQuery"

    def test_pre_mapped_service_string(self) -> None:
        # When `service` is already a string (not a dict), it's pre-mapped.
        out = normalize_gcp_event(
            _flat_payload(service="Cloud SQL", service_description=None)
        )
        assert out["service"] == "Cloud SQL"

    def test_missing_service_raises(self) -> None:
        payload = _flat_payload()
        del payload["service_description"]
        with pytest.raises(NormalizationError, match="service"):
            normalize_gcp_event(payload)


# ---------------------------------------------------------------------------
# Region resolution
# ---------------------------------------------------------------------------


class TestRegionResolution:
    def test_nested_region(self) -> None:
        out = normalize_gcp_event(_nested_payload())
        assert out["region"] == "europe-west1"

    def test_nested_multi_region(self) -> None:
        out = normalize_gcp_event(_nested_payload(location={"location": "EU"}))
        assert out["region"] == "EU"

    def test_flat_region(self) -> None:
        out = normalize_gcp_event(_flat_payload())
        assert out["region"] == "us-central1"

    def test_missing_region_falls_back_to_global(self) -> None:
        payload = _flat_payload()
        del payload["location_region"]
        out = normalize_gcp_event(payload)
        assert out["region"] == "global"


# ---------------------------------------------------------------------------
# Account resolution
# ---------------------------------------------------------------------------


class TestAccountResolution:
    def test_billing_account_id_preferred(self) -> None:
        out = normalize_gcp_event(_flat_payload())
        assert out["account_id"] == "acct-001"

    def test_nested_project_id(self) -> None:
        out = normalize_gcp_event(_nested_payload())
        assert out["account_id"] == "proj-123"

    def test_flat_project_id(self) -> None:
        payload = {
            "service_description": "BigQuery",
            "location_region": "us-central1",
            "usage_start_time": "2026-01-01T00:00:00Z",
            "cost": 1.0,
            "project_id": "proj-456",
        }
        out = normalize_gcp_event(payload)
        assert out["account_id"] == "proj-456"

    def test_missing_account_raises(self) -> None:
        payload = _flat_payload()
        del payload["billing_account_id"]
        with pytest.raises(NormalizationError, match="account/project"):
            normalize_gcp_event(payload)


# ---------------------------------------------------------------------------
# Timestamp resolution
# ---------------------------------------------------------------------------


class TestTimestampResolution:
    def test_usage_start_time_preferred(self) -> None:
        out = normalize_gcp_event(_flat_payload(export_time="2027-01-01T00:00:00Z"))
        assert "2026-01-01" in out["timestamp"]

    def test_falls_back_to_export_time(self) -> None:
        payload = _flat_payload()
        del payload["usage_start_time"]
        payload["export_time"] = "2026-06-15T10:00:00Z"
        out = normalize_gcp_event(payload)
        assert "2026-06-15" in out["timestamp"]

    def test_falls_back_to_generic_timestamp(self) -> None:
        payload = _flat_payload()
        del payload["usage_start_time"]
        payload["timestamp"] = "2026-07-01T00:00:00Z"
        out = normalize_gcp_event(payload)
        assert "2026-07-01" in out["timestamp"]

    def test_missing_all_timestamps_raises(self) -> None:
        payload = _flat_payload()
        del payload["usage_start_time"]
        with pytest.raises(NormalizationError, match="timestamp"):
            normalize_gcp_event(payload)


# ---------------------------------------------------------------------------
# Usage resolution
# ---------------------------------------------------------------------------


class TestUsageResolution:
    def test_nested_usage_block(self) -> None:
        out = normalize_gcp_event(_nested_payload())
        assert out["usage_amount"] == 42.0
        assert out["usage_unit"] == "byte-seconds"

    def test_flat_usage_fields(self) -> None:
        out = normalize_gcp_event(_flat_payload())
        assert out["usage_amount"] == 100.0
        assert out["usage_unit"] == "core-hours"

    def test_missing_usage_amount_defaults_to_zero(self) -> None:
        payload = _flat_payload()
        del payload["usage_amount"]
        out = normalize_gcp_event(payload)
        assert out["usage_amount"] == 0.0

    def test_missing_usage_unit_defaults_to_unit(self) -> None:
        payload = _flat_payload()
        del payload["usage_unit"]
        out = normalize_gcp_event(payload)
        assert out["usage_unit"] == "unit"


# ---------------------------------------------------------------------------
# Cost resolution
# ---------------------------------------------------------------------------


class TestCostResolution:
    def test_cost_field_preferred(self) -> None:
        out = normalize_gcp_event(_flat_payload(cost=7.5, cost_amount=99.0))
        assert out["cost_amount"] == 7.5

    def test_falls_back_to_cost_amount(self) -> None:
        payload = _flat_payload()
        del payload["cost"]
        payload["cost_amount"] = 3.5
        out = normalize_gcp_event(payload)
        assert out["cost_amount"] == 3.5

    def test_missing_both_raises(self) -> None:
        payload = _flat_payload()
        del payload["cost"]
        with pytest.raises(NormalizationError):
            normalize_gcp_event(payload)


# ---------------------------------------------------------------------------
# Labels / tags
# ---------------------------------------------------------------------------


class TestLabels:
    def test_nested_label_list(self) -> None:
        out = normalize_gcp_event(_nested_payload())
        assert out["tags"] == {"env": "prod", "team": "data"}

    def test_dict_tags_passed_through(self) -> None:
        out = normalize_gcp_event(_flat_payload(tags={"env": "staging"}))
        assert out["tags"] == {"env": "staging"}

    def test_missing_labels_returns_none(self) -> None:
        out = normalize_gcp_event(_flat_payload())
        assert out["tags"] is None

    def test_label_list_with_missing_value(self) -> None:
        out = normalize_gcp_event(_flat_payload(labels=[{"key": "env"}]))
        assert out["tags"] == {"env": ""}

    def test_empty_label_list_returns_none(self) -> None:
        out = normalize_gcp_event(_flat_payload(labels=[]))
        assert out["tags"] is None


# ---------------------------------------------------------------------------
# Provider hardcoded
# ---------------------------------------------------------------------------


def test_provider_always_gcp() -> None:
    out = normalize_gcp_event(_flat_payload(provider="aws"))
    assert out["provider"] == "gcp"


def test_source_type_default_is_live() -> None:
    out = normalize_gcp_event(_flat_payload())
    assert out["source_type"] == "live"


def test_source_type_passed_through() -> None:
    out = normalize_gcp_event(_flat_payload(source_type="synthetic"))
    assert out["source_type"] == "synthetic"
