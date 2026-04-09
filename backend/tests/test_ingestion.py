import uuid
from datetime import datetime, timezone

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


def test_ingest_event_missing_required_field() -> None:
    payload = {k: v for k, v in VALID_EVENT.items() if k != "account_id"}
    response = client.post("/api/v1/events", json=payload)
    assert response.status_code == 422


def test_ingest_event_negative_cost_rejected() -> None:
    response = client.post("/api/v1/events", json={**VALID_EVENT, "cost_amount": -1.0})
    assert response.status_code == 422
