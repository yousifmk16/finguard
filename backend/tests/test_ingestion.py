import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_EVENT = {
    "timestamp": "2026-01-01T00:00:00Z",
    "provider": "gcp",
    "account_id": "acct-001",
    "service": "compute",
    "region": "us-central1",
    "cost_amount": 12.50,
    "usage_amount": 100.0,
    "usage_unit": "core-hours",
    "tags": {"env": "prod"},
    "source_type": "synthetic",
}


# ---------------------------------------------------------------------------
# Happy-path tests (from ING-01)
# ---------------------------------------------------------------------------


def test_ingest_event_accepted() -> None:
    response = client.post("/api/v1/events", json=VALID_EVENT)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert uuid.UUID(body["event_id"])


def test_ingest_event_preserves_event_id() -> None:
    event_id = str(uuid.uuid4())
    response = client.post("/api/v1/events", json={**VALID_EVENT, "event_id": event_id})
    assert response.status_code == 202
    assert response.json()["event_id"] == event_id


# ---------------------------------------------------------------------------
# Structural validation (missing / wrong-type fields)
# ---------------------------------------------------------------------------


def test_ingest_event_missing_required_field() -> None:
    payload = {k: v for k, v in VALID_EVENT.items() if k != "account_id"}
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 422


def test_ingest_event_negative_cost_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "cost_amount": -1.0})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Provider constraint
# ---------------------------------------------------------------------------


def test_unknown_provider_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "provider": "oracle"})
    assert response.status_code == 422


def test_all_known_providers_accepted() -> None:
    for provider in ("gcp", "aws", "azure"):
        response = client.post("/api/v1/events", json={**VALID_EVENT, "provider": provider})
        assert response.status_code == 202, f"provider={provider} unexpectedly rejected"


# ---------------------------------------------------------------------------
# Non-empty string fields
# ---------------------------------------------------------------------------


def test_blank_account_id_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "account_id": "   "})
    assert response.status_code == 422


def test_blank_service_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "service": ""})
    assert response.status_code == 422


def test_blank_region_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "region": ""})
    assert response.status_code == 422


def test_blank_usage_unit_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "usage_unit": "  "})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Timestamp constraint
# ---------------------------------------------------------------------------


def test_far_future_timestamp_rejected() -> None:
    far_future = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()
    response = client.post("/api/v1/events", json={**VALID_EVENT, "timestamp": far_future})
    assert response.status_code == 422


def test_near_future_timestamp_accepted() -> None:
    """Timestamps within the 5-minute clock-skew window should pass."""
    near_future = (datetime.now(tz=timezone.utc) + timedelta(seconds=60)).isoformat()
    response = client.post("/api/v1/events", json={**VALID_EVENT, "timestamp": near_future})
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Error response shape (ING-02: normalized error contract)
# ---------------------------------------------------------------------------


def test_validation_error_response_shape() -> None:
    payload = {k: v for k, v in VALID_EVENT.items() if k != "service"}
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert "errors" in body
    assert isinstance(body["errors"], list)
    first = body["errors"][0]
    assert "field" in first
    assert "message" in first


def test_validation_error_field_name_present() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "provider": "bad"})
    assert response.status_code == 422
    errors = response.json()["errors"]
    fields = [e["field"] for e in errors]
    assert any("provider" in f for f in fields)


# ---------------------------------------------------------------------------
# Idempotency (ING-03)
# ---------------------------------------------------------------------------


def test_first_submission_is_202() -> None:
    event_id = str(uuid.uuid4())
    response = client.post("/api/v1/events", json={**VALID_EVENT, "event_id": event_id})
    assert response.status_code == 202
    assert response.json()["duplicate"] is False


def test_duplicate_submission_is_200() -> None:
    event_id = str(uuid.uuid4())
    payload = {**VALID_EVENT, "event_id": event_id}
    client.post("/api/v1/events", json=payload)
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 200


def test_duplicate_receipt_has_duplicate_flag() -> None:
    event_id = str(uuid.uuid4())
    payload = {**VALID_EVENT, "event_id": event_id}
    client.post("/api/v1/events", json=payload)
    body = client.post("/api/v1/events", json=payload).json()
    assert body["duplicate"] is True
    assert body["event_id"] == event_id
    assert body["status"] == "accepted"


def test_duplicate_preserves_event_id() -> None:
    event_id = str(uuid.uuid4())
    payload = {**VALID_EVENT, "event_id": event_id}
    client.post("/api/v1/events", json=payload)
    response = client.post("/api/v1/events", json=payload)
    assert response.json()["event_id"] == event_id


def test_different_event_ids_are_independent() -> None:
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    r1 = client.post("/api/v1/events", json={**VALID_EVENT, "event_id": id_a})
    r2 = client.post("/api/v1/events", json={**VALID_EVENT, "event_id": id_b})
    assert r1.status_code == 202
    assert r2.status_code == 202


def test_third_submission_still_200() -> None:
    """Idempotency holds across more than two calls."""
    event_id = str(uuid.uuid4())
    payload = {**VALID_EVENT, "event_id": event_id}
    client.post("/api/v1/events", json=payload)
    client.post("/api/v1/events", json=payload)
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 200
    assert response.json()["duplicate"] is True
