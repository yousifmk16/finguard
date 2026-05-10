"""Admin-only endpoints to generate and clear synthetic data.

POST /api/v1/admin/generate
    Generates randomised billing events + anomalies and ingests them.

DELETE /api/v1/admin/data
    Truncates billing_events_raw, anomalies, and alerts tables and resets
    the in-process idempotency store.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import logging

from app.api.rbac import require_admin
from app.core.idempotency import store as idempotency_store
from app.db.models.billing_event import BillingEventRow
from app.db.models.anomaly import AnomalyRow
from app.db.models.alert import AlertRow
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_CONFIG_PATH = Path(__file__).resolve().parents[3] / "generators" / "config.json"


class InjectorConfig(BaseModel):
    enabled: bool = True
    count: int | None = None
    multiplier: float | None = None
    start_index: int | None = None
    slope: float | None = None
    shift: float | None = None
    budget_threshold: float | None = None
    breach_multiplier: float | None = None
    duration: int | None = None


class GenerateRequest(BaseModel):
    n: int | None = None
    seed: int | None = None
    provider: str | None = None
    start_time: str | None = None
    accounts: list[str] | None = None
    services: list[str] | None = None
    regions: list[str] | None = None
    baseline_default: float | None = None
    spike: InjectorConfig | None = None
    drift: InjectorConfig | None = None
    level_shift: InjectorConfig | None = None
    budget_breach: InjectorConfig | None = None


class GenerateResponse(BaseModel):
    accepted: int
    duplicate: int
    failed: int
    total: int
    anomalies_seeded: int
    alerts_seeded: int
    seed_used: int


class DeleteResponse(BaseModel):
    events_deleted: int
    anomalies_deleted: int
    alerts_deleted: int


def _freq_to_timedelta(freq: str) -> timedelta:
    """Parse a pandas-style frequency string like '3h' or '30min' into a timedelta."""
    m = re.match(r"^(\d+)\s*([hHmM])", freq.strip())
    if not m:
        return timedelta(hours=1)
    val = int(m.group(1))
    unit = m.group(2).lower()
    return timedelta(hours=val) if unit == "h" else timedelta(minutes=val)


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate and ingest synthetic billing events + anomalies",
    dependencies=[Depends(require_admin)],
)
def generate_data(
    body: GenerateRequest = GenerateRequest(),
    db: Session | None = Depends(get_db),
) -> GenerateResponse:
    try:
        from generators.core import generate_labeled_events_records
        from generators.config_loader import load_generator_config
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Generator package not available: {e}")

    if not _CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Config not found: {_CONFIG_PATH}")

    config = load_generator_config(_CONFIG_PATH)

    # Use a random seed unless caller specifies one
    seed = body.seed if body.seed is not None else random.randint(0, 999_999)
    config["seed"] = seed

    if body.n is not None:
        config["n"] = body.n
    if body.provider is not None:
        config["provider"] = body.provider
    if body.start_time is not None:
        config["start_time"] = body.start_time
    if body.accounts is not None:
        config["accounts"] = body.accounts
    if body.services is not None:
        config["services"] = body.services
    if body.regions is not None:
        config["regions"] = body.regions
    if body.baseline_default is not None:
        config.setdefault("baseline", {})["default"] = body.baseline_default

    for inj_name in ("spike", "drift", "level_shift", "budget_breach"):
        inj_body = getattr(body, inj_name)
        if inj_body is not None:
            patch = inj_body.model_dump(exclude_none=True)
            config.setdefault("anomaly_injectors", {}).setdefault(inj_name, {}).update(patch)

    # Compute dynamic start_time so the generated window ends ~1 h before now.
    # This ensures anomalies_last_24h and the trend chart always show live data.
    if body.start_time is None:
        n_events = int(config.get("n", 240))
        delta = _freq_to_timedelta(str(config.get("frequency", "1h")))
        end_time = datetime.now(tz=UTC) - timedelta(hours=1)
        config["start_time"] = (end_time - delta * (n_events - 1)).isoformat()

    # Always wipe existing data so re-generating gives a clean dataset
    if db is not None:
        db.execute(delete(AlertRow))
        db.execute(delete(AnomalyRow))
        db.execute(delete(BillingEventRow))
        db.commit()
        idempotency_store._seen.clear()  # type: ignore[attr-defined]

    sev_rng = random.Random(seed)

    def _next_severity() -> tuple[float, str]:
        r = sev_rng.random()
        if r < 0.18:
            return round(0.82 + sev_rng.random() * 0.16, 4), "high"
        if r < 0.55:
            return round(0.52 + sev_rng.random() * 0.26, 4), "medium"
        return round(0.22 + sev_rng.random() * 0.26, 4), "low"

    records = generate_labeled_events_records(config)

    accepted = duplicate = failed = anomalies_seeded = alerts_seeded = 0

    for ev in records:
        event_id = str(ev["event_id"])

        if idempotency_store.is_duplicate(event_id):
            duplicate += 1
            continue

        try:
            if db is not None:
                row = BillingEventRow(
                    event_id=event_id,
                    timestamp=ev["timestamp"],
                    provider=ev.get("provider", "gcp"),
                    account_id=ev["account_id"],
                    service=ev["service"],
                    region=ev["region"],
                    cost_amount=round(float(ev["cost_amount"]), 6),
                    usage_amount=round(float(ev["usage_amount"]), 6),
                    usage_unit=ev["usage_unit"],
                    tags=ev.get("tags", {}),
                    source_type=ev.get("source_type", "synthetic"),
                )
                db.add(row)
                db.flush()

                injector = ev.get("anomaly_type", "none")
                if ev.get("is_anomaly", 0) and injector not in ("none", "normal") and db is not None:
                    score, severity = _next_severity()
                    bucket = _parse_ts(ev["timestamp"])
                    anomaly_id = uuid.uuid4()
                    db.add(AnomalyRow(
                        anomaly_id=anomaly_id,
                        account_id=ev["account_id"],
                        service=ev["service"],
                        region=ev["region"],
                        bucket=bucket,
                        anomaly_score=Decimal(str(round(score, 6))),
                        severity=severity,
                        score_breakdown={
                            "ts_signal": round(score * 0.45, 4),
                            "if_score": round(score * 0.35, 4),
                            "rule_score": round(score * 0.20, 4),
                        },
                        status="open",
                        detected_at=bucket,
                    ))
                    db.flush()
                    anomalies_seeded += 1

                    if severity == "high":
                        db.add(AlertRow(
                            alert_id=uuid.uuid4(),
                            anomaly_id=anomaly_id,
                            account_id=ev["account_id"],
                            service=ev["service"],
                            region=ev["region"],
                            severity=severity,
                            channel="in_app",
                            status="sent",
                            dedup_key=f"datagen:{anomaly_id}:in_app",
                            sent_at=datetime.now(tz=UTC),
                        ))
                        alerts_seeded += 1

                db.commit()

            idempotency_store.register(event_id)
            accepted += 1
        except IntegrityError:
            if db is not None:
                db.rollback()
            duplicate += 1
        except Exception as exc:
            if db is not None:
                db.rollback()
            failed += 1
            logger.error("datagen row failed: %s", exc, exc_info=True)

    return GenerateResponse(
        accepted=accepted,
        duplicate=duplicate,
        failed=failed,
        total=len(records),
        anomalies_seeded=anomalies_seeded,
        alerts_seeded=alerts_seeded,
        seed_used=seed,
    )


@router.delete(
    "/data",
    response_model=DeleteResponse,
    summary="Delete all generated billing events, anomalies, and alerts",
    dependencies=[Depends(require_admin)],
)
def delete_all_data(db: Session | None = Depends(get_db)) -> DeleteResponse:
    if db is None:
        return DeleteResponse(events_deleted=0, anomalies_deleted=0, alerts_deleted=0)

    alerts_deleted = db.execute(delete(AlertRow)).rowcount
    anomalies_deleted = db.execute(delete(AnomalyRow)).rowcount
    events_deleted = db.execute(delete(BillingEventRow)).rowcount
    db.commit()

    # Clear in-process idempotency store so new generates aren't treated as duplicates
    idempotency_store._seen.clear()  # type: ignore[attr-defined]

    return DeleteResponse(
        events_deleted=events_deleted,
        anomalies_deleted=anomalies_deleted,
        alerts_deleted=alerts_deleted,
    )


def _parse_ts(ts: str | datetime) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _multiplier(injector: str) -> float:
    return {"spike": 2.8, "drift": 1.4, "level_shift": 1.3, "budget_breach": 1.1}.get(injector, 1.0)


