"""
Unit tests for DET-02: AnomalyEventEmitter.

All tests use an in-process stub broker — no Redis required.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

import pytest

from services.detection.anomaly_emitter import AnomalyEvent, AnomalyEventEmitter


# ---------------------------------------------------------------------------
# Stub broker
# ---------------------------------------------------------------------------


@dataclass
class _StubBroker:
    """Records every publish() call so tests can assert on it."""

    published: List[tuple[str, str]] = field(default_factory=list)
    _counter: int = 0

    def publish(self, stream_name: str, payload: str) -> str:
        self.published.append((stream_name, payload))
        self._counter += 1
        return f"1000-{self._counter}"

    # Unused by emitter, present for protocol completeness
    def consume(self, *args, **kwargs):  # type: ignore[override]
        return []

    def ack(self, *args, **kwargs) -> None:  # type: ignore[override]
        pass


# ---------------------------------------------------------------------------
# Minimal AnomalyRow stand-in
# ---------------------------------------------------------------------------


@dataclass
class _FakeAnomalyRow:
    anomaly_id: uuid.UUID
    account_id: str
    service: str
    region: str
    bucket: datetime
    anomaly_score: Decimal
    severity: str
    status: str
    detected_at: datetime
    score_breakdown: dict | None = None


_NOW = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


def _make_row(**overrides) -> _FakeAnomalyRow:
    defaults = dict(
        anomaly_id=uuid.UUID("11111111-0000-0000-0000-000000000001"),
        account_id="acct-001",
        service="BigQuery",
        region="us-central1",
        bucket=_NOW,
        anomaly_score=Decimal("0.750000"),
        severity="high",
        status="open",
        detected_at=_NOW,
        score_breakdown=None,
    )
    defaults.update(overrides)
    return _FakeAnomalyRow(**defaults)


# ---------------------------------------------------------------------------
# AnomalyEvent.from_row
# ---------------------------------------------------------------------------


class TestAnomalyEventFromRow:
    def test_fields_mapped_correctly(self) -> None:
        row = _make_row()
        event = AnomalyEvent.from_row(row)

        assert event.anomaly_id == "11111111-0000-0000-0000-000000000001"
        assert event.account_id == "acct-001"
        assert event.service == "BigQuery"
        assert event.region == "us-central1"
        assert event.anomaly_score == 0.75
        assert event.severity == "high"
        assert event.status == "open"

    def test_bucket_serialised_to_iso(self) -> None:
        row = _make_row(bucket=datetime(2026, 4, 16, 10, 30, tzinfo=timezone.utc))
        event = AnomalyEvent.from_row(row)
        assert event.bucket == "2026-04-16T10:30:00+00:00"

    def test_breakdown_excluded_by_default(self) -> None:
        row = _make_row(score_breakdown={"anomaly_score": 0.75})
        event = AnomalyEvent.from_row(row)
        assert event.score_breakdown is None

    def test_breakdown_included_when_flag_set(self) -> None:
        breakdown = {"anomaly_score": 0.75, "is_anomaly": True}
        row = _make_row(score_breakdown=breakdown)
        event = AnomalyEvent.from_row(row, include_breakdown=True)
        assert event.score_breakdown == breakdown

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2026, 4, 16, 8, 0, 0)  # no tzinfo
        row = _make_row(bucket=naive)
        event = AnomalyEvent.from_row(row)
        assert "+00:00" in event.bucket

    def test_none_detected_at_falls_back_gracefully(self) -> None:
        # None occurs when a row is emitted before db.refresh() populates the
        # server-default. The fallback emits current UTC time with a log warning.
        row = _make_row(detected_at=None)
        event = AnomalyEvent.from_row(row)
        assert isinstance(event.detected_at, str)
        assert len(event.detected_at) > 0


# ---------------------------------------------------------------------------
# AnomalyEvent serialisation
# ---------------------------------------------------------------------------


class TestAnomalyEventSerialisation:
    def test_to_json_is_valid_json(self) -> None:
        event = AnomalyEvent.from_row(_make_row())
        parsed = json.loads(event.to_json())
        assert isinstance(parsed, dict)

    def test_to_json_contains_required_keys(self) -> None:
        event = AnomalyEvent.from_row(_make_row())
        parsed = json.loads(event.to_json())
        required = {
            "anomaly_id", "account_id", "service", "region",
            "bucket", "anomaly_score", "severity", "status", "detected_at",
        }
        assert required.issubset(parsed.keys())

    def test_to_dict_roundtrips(self) -> None:
        event = AnomalyEvent.from_row(_make_row())
        d = event.to_dict()
        assert d["severity"] == "high"
        assert d["anomaly_score"] == 0.75


# ---------------------------------------------------------------------------
# AnomalyEventEmitter.emit
# ---------------------------------------------------------------------------


class TestAnomalyEventEmitterEmit:
    def _emitter(self) -> tuple[AnomalyEventEmitter, _StubBroker]:
        broker = _StubBroker()
        return AnomalyEventEmitter(broker, stream_name="anomaly-events"), broker

    def test_returns_message_id(self) -> None:
        emitter, _ = self._emitter()
        event = AnomalyEvent.from_row(_make_row())
        mid = emitter.emit(event)
        assert mid == "1000-1"

    def test_publishes_to_correct_stream(self) -> None:
        emitter, broker = self._emitter()
        emitter.emit(AnomalyEvent.from_row(_make_row()))
        stream, _ = broker.published[0]
        assert stream == "anomaly-events"

    def test_payload_is_valid_json(self) -> None:
        emitter, broker = self._emitter()
        emitter.emit(AnomalyEvent.from_row(_make_row()))
        _, payload = broker.published[0]
        parsed = json.loads(payload)
        assert parsed["account_id"] == "acct-001"

    def test_custom_stream_name(self) -> None:
        broker = _StubBroker()
        emitter = AnomalyEventEmitter(broker, stream_name="custom-stream")
        emitter.emit(AnomalyEvent.from_row(_make_row()))
        stream, _ = broker.published[0]
        assert stream == "custom-stream"


# ---------------------------------------------------------------------------
# AnomalyEventEmitter.emit_rows
# ---------------------------------------------------------------------------


class TestAnomalyEventEmitterEmitRows:
    def _emitter(self) -> tuple[AnomalyEventEmitter, _StubBroker]:
        broker = _StubBroker()
        return AnomalyEventEmitter(broker, stream_name="anomaly-events"), broker

    def test_empty_list_emits_nothing(self) -> None:
        emitter, broker = self._emitter()
        ids = emitter.emit_rows([])
        assert ids == []
        assert len(broker.published) == 0

    def test_emits_one_event_per_row(self) -> None:
        emitter, broker = self._emitter()
        rows = [
            _make_row(anomaly_id=uuid.UUID(f"11111111-0000-0000-0000-00000000000{i}"))
            for i in range(1, 4)
        ]
        ids = emitter.emit_rows(rows)
        assert len(ids) == 3
        assert len(broker.published) == 3

    def test_message_ids_are_unique(self) -> None:
        emitter, _ = self._emitter()
        rows = [_make_row() for _ in range(5)]
        ids = emitter.emit_rows(rows)
        assert len(set(ids)) == 5

    def test_each_payload_carries_correct_anomaly_id(self) -> None:
        emitter, broker = self._emitter()
        ids_in = [uuid.uuid4() for _ in range(3)]
        rows = [_make_row(anomaly_id=aid) for aid in ids_in]
        emitter.emit_rows(rows)
        emitted_ids = [
            json.loads(payload)["anomaly_id"]
            for _, payload in broker.published
        ]
        assert emitted_ids == [str(aid) for aid in ids_in]

    def test_breakdown_included_when_configured(self) -> None:
        broker = _StubBroker()
        emitter = AnomalyEventEmitter(
            broker, stream_name="anomaly-events", include_breakdown=True
        )
        breakdown = {"anomaly_score": 0.75, "is_anomaly": True}
        row = _make_row(score_breakdown=breakdown)
        emitter.emit_rows([row])
        _, payload = broker.published[0]
        parsed = json.loads(payload)
        assert parsed["score_breakdown"] == breakdown

    def test_breakdown_excluded_by_default(self) -> None:
        emitter, broker = self._emitter()
        row = _make_row(score_breakdown={"anomaly_score": 0.75})
        emitter.emit_rows([row])
        _, payload = broker.published[0]
        parsed = json.loads(payload)
        assert parsed["score_breakdown"] is None
