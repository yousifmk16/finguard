"""Admin-only endpoints to generate and clear synthetic data.

POST /api/v1/admin/generate
    mode="demo"     — generates synthetic billing events with source_type='synthetic',
                      seeds AnomalyRow and AlertRow so data appears in dashboards.
    mode="training" — generates events with source_type='training_generated',
                      no anomaly/alert seeding; data is isolated for ML training only.

DELETE /api/v1/admin/data
    mode="demo"     — deletes source_type='synthetic' events + all anomalies + alerts.
    mode="training" — deletes training_generated and training_uploaded events only.
"""

from __future__ import annotations

import math
import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
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
    mode: str = "demo"          # "demo" | "training"
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
    anomalies_seeded: int = 0
    alerts_seeded: int = 0
    seed_used: int


class DeleteResponse(BaseModel):
    events_deleted: int
    anomalies_deleted: int = 0
    alerts_deleted: int = 0


def _freq_to_timedelta(freq: str) -> timedelta:
    m = re.match(r"^(\d+)\s*([hHmM])", freq.strip())
    if not m:
        return timedelta(hours=1)
    val = int(m.group(1))
    unit = m.group(2).lower()
    return timedelta(hours=val) if unit == "h" else timedelta(minutes=val)


# ---------------------------------------------------------------------------
# GCP Cloud Billing style demo data
# ---------------------------------------------------------------------------

_DEMO_GCP_PROJECTS: dict[str, dict[str, float]] = {
    "finops-prod-01": {
        "Compute Engine": 85.0,
        "Cloud Storage": 12.0,
        "BigQuery": 35.0,
        "Cloud SQL": 42.0,
        "Kubernetes Engine": 68.0,
        "Cloud Functions": 5.5,
    },
    "finops-staging-01": {
        "Compute Engine": 28.0,
        "Cloud Storage": 4.5,
        "BigQuery": 8.0,
        "Cloud SQL": 14.0,
        "Kubernetes Engine": 22.0,
        "Cloud Functions": 2.0,
    },
    "analytics-prod-01": {
        "Compute Engine": 45.0,
        "Cloud Storage": 18.0,
        "BigQuery": 62.0,
        "Cloud SQL": 25.0,
        "Kubernetes Engine": 38.0,
        "Cloud Functions": 9.0,
    },
}

_DEMO_GCP_REGIONS = ["us-central1", "us-east1", "europe-west1"]
_DEMO_GCP_REGION_WEIGHTS = {"us-central1": 0.50, "us-east1": 0.30, "europe-west1": 0.20}

_DEMO_GCP_USAGE: dict[str, tuple[str, float]] = {
    "Compute Engine":    ("vCPU-hour",       150.0),
    "Cloud Storage":     ("gibibyte month",  500.0),
    "BigQuery":          ("tebibyte",          0.8),
    "Cloud SQL":         ("vCPU-hour",        48.0),
    "Kubernetes Engine": ("vCPU-hour",       210.0),
    "Cloud Functions":   ("invocations",  120000.0),
}


def _generate_gcp_demo_records(seed: int, days: int = 365) -> list[dict]:
    """Generate GCP Cloud Billing style records with injected spike anomalies.

    Mirrors the pattern used in training._seed_gcp_training_data:
      - Daily seasonality (Gaussian peak at 13:00)
      - Weekly seasonality (weekends at 60 %)
      - Slight upward trend (+0.1 % / hr)
      - Gaussian noise (σ ≈ 8 % cost, 5 % usage)
    Anomalies: ~5 % of hours are randomly chosen as "spike hours"; within each
    spike hour ~25 % of service/region combos receive a 3–8× cost multiplier.
    """
    rng = random.Random(seed)

    now = datetime.now(tz=UTC)
    start = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    hours = days * 24

    spike_hours: set[int] = set(rng.sample(range(hours), min(int(hours * 0.05), hours)))

    records: list[dict] = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        hod = ts.hour
        dow = ts.weekday()

        daily = 1.0 + 0.30 * math.exp(-0.5 * ((hod - 13) / 4) ** 2)
        weekly = 0.60 if dow >= 5 else 1.0
        trend = 1.0 + 0.001 * h
        is_spike_hour = h in spike_hours

        for project_id, services in _DEMO_GCP_PROJECTS.items():
            for service, base_cost in services.items():
                for region in _DEMO_GCP_REGIONS:
                    rw = _DEMO_GCP_REGION_WEIGHTS[region]
                    unit, usage_base = _DEMO_GCP_USAGE[service]

                    cost = base_cost * rw * daily * weekly * trend
                    cost *= 1.0 + rng.gauss(0, 0.08)
                    cost = max(0.01, round(cost, 6))

                    usage = usage_base * rw * daily * weekly
                    usage *= 1.0 + rng.gauss(0, 0.05)
                    usage = max(0.001, round(usage, 6))

                    is_anomaly = 0
                    anomaly_type = "none"
                    if is_spike_hour and rng.random() < 0.25:
                        spike_mult = rng.uniform(3.0, 8.0)
                        cost = round(cost * spike_mult, 6)
                        usage = round(usage * spike_mult, 6)
                        is_anomaly = 1
                        anomaly_type = "spike"

                    records.append({
                        "event_id": uuid.uuid4(),
                        "timestamp": ts,
                        "provider": "gcp",
                        "account_id": project_id,
                        "service": service,
                        "region": region,
                        "cost_amount": cost,
                        "usage_amount": usage,
                        "usage_unit": unit,
                        "tags": {
                            "env": "prod" if "prod" in project_id else "staging",
                            "team": "finops",
                        },
                        "is_anomaly": is_anomaly,
                        "anomaly_type": anomaly_type,
                    })

    return records


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate synthetic billing events",
    dependencies=[Depends(require_admin)],
)
def generate_data(
    body: GenerateRequest = GenerateRequest(),
    db: Session | None = Depends(get_db),
) -> GenerateResponse:
    training_mode = body.mode == "training"
    source_type = "training_generated" if training_mode else "synthetic"

    seed = body.seed if body.seed is not None else random.randint(0, 999_999)

    if db is not None:
        if training_mode:
            # Wipe only existing generated training data
            db.execute(delete(BillingEventRow).where(BillingEventRow.source_type == "training_generated"))
        else:
            # Wipe all demo data (events + anomalies + alerts)
            db.execute(delete(AlertRow))
            db.execute(delete(AnomalyRow))
            db.execute(delete(BillingEventRow).where(BillingEventRow.source_type == "synthetic"))
        db.commit()
        idempotency_store._seen.clear()  # type: ignore[attr-defined]

    if not training_mode:
        # Demo mode: GCP Cloud Billing style data with injected anomalies
        records = _generate_gcp_demo_records(seed)
    else:
        # Training mode: use generators.core library with config file
        try:
            from generators.core import generate_labeled_events_records
            from generators.config_loader import load_generator_config
        except ImportError as e:
            raise HTTPException(status_code=500, detail=f"Generator package not available: {e}")

        if not _CONFIG_PATH.exists():
            raise HTTPException(status_code=500, detail=f"Config not found: {_CONFIG_PATH}")

        config = load_generator_config(_CONFIG_PATH)
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

        # Compute dynamic start_time so the window ends ~1 h before now
        if body.start_time is None:
            n_events = int(config.get("n", 240))
            delta = _freq_to_timedelta(str(config.get("frequency", "1h")))
            end_time = datetime.now(tz=UTC) - timedelta(hours=1)
            config["start_time"] = (end_time - delta * (n_events - 1)).isoformat()

        records = generate_labeled_events_records(config)

    sev_rng = random.Random(seed)

    def _next_severity() -> tuple[float, str]:
        r = sev_rng.random()
        if r < 0.18:
            return round(0.82 + sev_rng.random() * 0.16, 4), "high"
        if r < 0.55:
            return round(0.52 + sev_rng.random() * 0.26, 4), "medium"
        return round(0.22 + sev_rng.random() * 0.26, 4), "low"

    accepted = duplicate = failed = anomalies_seeded = alerts_seeded = 0
    _BATCH = 2000

    if not training_mode and db is not None:
        # Demo mode: bulk-insert in batches to handle large year-long datasets
        batch: list[BillingEventRow] = []
        anomaly_rows: list[AnomalyRow] = []
        alert_rows: list[AlertRow] = []

        for ev in records:
            batch.append(BillingEventRow(
                event_id=str(ev["event_id"]),
                timestamp=ev["timestamp"],
                provider=ev.get("provider", "gcp"),
                account_id=ev["account_id"],
                service=ev["service"],
                region=ev["region"],
                cost_amount=round(float(ev["cost_amount"]), 6),
                usage_amount=round(float(ev["usage_amount"]), 6),
                usage_unit=ev["usage_unit"],
                tags=ev.get("tags", {}),
                source_type=source_type,
            ))
            accepted += 1

            injector = ev.get("anomaly_type", "none")
            if ev.get("is_anomaly", 0) and injector not in ("none", "normal"):
                score, severity = _next_severity()
                bucket = _parse_ts(ev["timestamp"])
                anomaly_id = uuid.uuid4()
                anomaly_rows.append(AnomalyRow(
                    anomaly_id=anomaly_id,
                    account_id=ev["account_id"],
                    service=ev["service"],
                    region=ev["region"],
                    bucket=bucket,
                    anomaly_score=Decimal(str(round(score, 6))),
                    severity=severity,
                    score_breakdown={
                        "ts_signal": round(score * 0.45, 4),
                        "if_score":  round(score * 0.35, 4),
                        "rule_score": round(score * 0.20, 4),
                    },
                    status="open",
                    detected_at=bucket,
                ))
                anomalies_seeded += 1

                if severity == "high":
                    alert_rows.append(AlertRow(
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

            if len(batch) >= _BATCH:
                db.add_all(batch)
                db.flush()
                batch = []

        # flush remaining billing events
        if batch:
            db.add_all(batch)
            db.flush()

        # insert anomalies and alerts in batches
        for i in range(0, len(anomaly_rows), _BATCH):
            db.add_all(anomaly_rows[i:i + _BATCH])
            db.flush()
        for i in range(0, len(alert_rows), _BATCH):
            db.add_all(alert_rows[i:i + _BATCH])
            db.flush()

        db.commit()
        for ev in records:
            idempotency_store.register(str(ev["event_id"]))

    else:
        # Training mode: per-row commit (small dataset, keeps error isolation)
        for ev in records:
            event_id = str(ev["event_id"])
            if idempotency_store.is_duplicate(event_id):
                duplicate += 1
                continue
            try:
                if db is not None:
                    db.add(BillingEventRow(
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
                        source_type=source_type,
                    ))
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
    summary="Delete generated data",
    dependencies=[Depends(require_admin)],
)
def delete_all_data(
    mode: str = Query("demo"),
    db: Session | None = Depends(get_db),
) -> DeleteResponse:
    if db is None:
        return DeleteResponse(events_deleted=0)

    if mode == "training":
        events_deleted = db.execute(
            delete(BillingEventRow).where(
                BillingEventRow.source_type.in_(["training_generated", "training_uploaded"])
            )
        ).rowcount
        db.commit()
        idempotency_store._seen.clear()  # type: ignore[attr-defined]
        return DeleteResponse(events_deleted=events_deleted)
    else:
        # Demo mode: wipe synthetic events + anomalies + alerts
        alerts_deleted = db.execute(delete(AlertRow)).rowcount
        anomalies_deleted = db.execute(delete(AnomalyRow)).rowcount
        events_deleted = db.execute(
            delete(BillingEventRow).where(BillingEventRow.source_type == "synthetic")
        ).rowcount
        db.commit()
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
