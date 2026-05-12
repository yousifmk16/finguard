"""
ML-06: Admin endpoints for training and inspecting ML model artifacts.

GET  /api/v1/admin/train/status
    Return artifact metadata, data stats for the baseline and autoencoder models.

POST /api/v1/admin/train/baseline
    Train TimeSeriesBaselineModel from training data in the DB.

POST /api/v1/admin/train/autoencoder
    Train AutoencoderDetector from training data in the DB.

POST /api/v1/admin/train/data/upload
    Upload a CSV file of billing events as training data.

GET  /api/v1/admin/train/data/export
    Export all training data as a CSV download.

Training endpoints aggregate billing_events_raw (source_type IN
'training_generated', 'training_uploaded') into hourly buckets, apply the
appropriate feature pipeline, fit the model, and save artifacts to the
ml/artifacts directory.  They are admin-only.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.rbac import require_admin
from app.db.models.billing_event import BillingEventRow
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/train", tags=["training"])

# Resolve artifact directory relative to this file:
# backend/app/api/training.py  →  ../../../ml/artifacts
_ARTIFACT_DIR = (Path(__file__).resolve().parents[3] / "ml" / "artifacts").as_posix()
_PROFILES_DIR = Path(_ARTIFACT_DIR) / "profiles"

_TRAINING_SOURCES = ("training_generated", "training_uploaded")

_SOURCE_FILTERS = {
    "all":       "source_type IN ('training_generated', 'training_uploaded')",
    "generated": "source_type = 'training_generated'",
    "uploaded":  "source_type = 'training_uploaded'",
}

# Required CSV columns for upload
_UPLOAD_REQUIRED = {"timestamp", "account_id", "service", "region", "cost_amount", "usage_amount"}

# GCP billing export → FinGuard column mapping (auto-detected on CSV upload)
_GCP_COL_MAP: dict[str, str] = {
    "usage_start_time": "timestamp",
    "project.id": "account_id",
    "project_id": "account_id",
    "service.description": "service",
    "service_description": "service",
    "location.region": "region",
    "location_region": "region",
    "cost": "cost_amount",
    "usage.amount": "usage_amount",
    "usage.unit": "usage_unit",
}

# Columns that signal a GCP billing export (need at least 2 to auto-detect)
_GCP_DETECT_COLS = {"usage_start_time", "project.id", "service.description", "cost"}


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class TrainRequest(BaseModel):
    lookback_days: int = 30
    min_train_rows: int = 60
    data_source: str = "all"  # "all", "generated", "uploaded"
    profile_id: str | None = None  # if set, train into this profile; else use active profile


class ModelArtifactStatus(BaseModel):
    trained: bool
    last_trained_at: str | None = None
    version: str | None = None
    train_rows: int = 0
    artifact_dir: str = _ARTIFACT_DIR
    extra: dict[str, Any] = {}


class DataStats(BaseModel):
    generated: int = 0
    uploaded: int = 0
    total: int = 0


class TrainingStatusResponse(BaseModel):
    baseline: ModelArtifactStatus
    autoencoder: ModelArtifactStatus
    data: DataStats


class TrainResult(BaseModel):
    model: str
    train_rows: int
    elapsed_seconds: float
    artifact_dir: str
    version: str | None = None


class UploadResult(BaseModel):
    accepted: int
    failed: int
    total: int
    errors: list[str] = []


class TrainingRow(BaseModel):
    timestamp: str
    provider: str
    account_id: str
    service: str
    region: str
    cost_amount: float
    usage_amount: float
    usage_unit: str
    source: str  # "generated" | "uploaded"


class TrainingDataPage(BaseModel):
    rows: list[TrainingRow]
    total: int
    page: int
    page_size: int
    pages: int


class ProfileEntry(BaseModel):
    id: str
    name: str
    created_at: str
    active: bool = False
    baseline: ModelArtifactStatus
    autoencoder: ModelArtifactStatus


class ProfilesResponse(BaseModel):
    profiles: list[ProfileEntry]
    active_id: str | None = None


class CreateProfileRequest(BaseModel):
    name: str


class RenameProfileRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Profile management helpers
# ---------------------------------------------------------------------------


def _read_index() -> dict:
    idx_path = _PROFILES_DIR / "index.json"
    if not idx_path.exists():
        return {"active": None, "profiles": []}
    with idx_path.open() as f:
        return json.load(f)


def _write_index(index: dict) -> None:
    _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    (_PROFILES_DIR / "index.json").write_text(json.dumps(index, indent=2))


def _profile_artifact_dir(profile_id: str) -> str:
    return (_PROFILES_DIR / profile_id).as_posix()


def _active_artifact_dir() -> str:
    index = _read_index()
    active = index.get("active")
    if active:
        return _profile_artifact_dir(active)
    return _ARTIFACT_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _baseline_status(artifact_dir: str | None = None) -> ModelArtifactStatus:
    """Read baseline model metadata from manifest.json or profile file."""
    if artifact_dir is None:
        artifact_dir = _active_artifact_dir()
    root = Path(artifact_dir)
    manifest_path = root / "manifest.json"
    profile_path = root / "baseline_seasonal_profile.json"

    # Prefer manifest (versioning) if it exists
    if manifest_path.exists():
        try:
            with manifest_path.open() as f:
                manifest = json.load(f)
            versions = manifest.get("versions", [])
            if versions:
                latest = versions[-1]
                return ModelArtifactStatus(
                    trained=True,
                    last_trained_at=latest.get("trained_at"),
                    version=latest.get("version"),
                    train_rows=latest.get("train_rows", 0),
                    artifact_dir=artifact_dir,
                )
        except Exception:
            pass

    # Fallback: check for bare profile file
    if profile_path.exists():
        import os
        mtime = os.path.getmtime(profile_path)
        trained_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        return ModelArtifactStatus(
            trained=True,
            last_trained_at=trained_at,
            artifact_dir=artifact_dir,
        )

    return ModelArtifactStatus(trained=False, artifact_dir=artifact_dir)


def _autoencoder_status(artifact_dir: str | None = None) -> ModelArtifactStatus:
    """Read autoencoder model metadata from ae_meta.json."""
    if artifact_dir is None:
        artifact_dir = _active_artifact_dir()
    root = Path(artifact_dir)
    model_path = root / "ae_model.pkl"
    meta_path = root / "ae_meta.json"

    if not model_path.exists():
        return ModelArtifactStatus(trained=False, artifact_dir=artifact_dir)

    extra: dict[str, Any] = {}
    if meta_path.exists():
        try:
            with meta_path.open() as f:
                meta = json.load(f)
            extra["feature_count"] = len(meta.get("feature_cols", []))
            extra["feature_cols"] = meta.get("feature_cols", [])
            extra["error_lo"] = round(meta.get("error_lo", 0.0), 6)
            extra["error_hi"] = round(meta.get("error_hi", 1.0), 6)
        except Exception:
            pass

    import os
    mtime = os.path.getmtime(model_path)
    trained_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()

    return ModelArtifactStatus(
        trained=True,
        last_trained_at=trained_at,
        artifact_dir=artifact_dir,
        extra=extra,
    )


def _data_stats(db: Session) -> DataStats:
    """Count training rows by source type."""
    rows = db.execute(
        text("""
            SELECT source_type, COUNT(*) AS cnt
            FROM billing_events_raw
            WHERE source_type IN ('training_generated', 'training_uploaded')
            GROUP BY source_type
        """)
    ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    gen = counts.get("training_generated", 0)
    upl = counts.get("training_uploaded", 0)
    return DataStats(generated=gen, uploaded=upl, total=gen + upl)


def _load_billing_df(db: Session, lookback_days: int, data_source: str = "all") -> "Any":
    """
    Aggregate training billing_events_raw into hourly buckets per group.

    Returns a pandas DataFrame with columns:
        bucket, account_id, service, region, total_cost, total_usage, event_count
    """
    import pandas as pd

    source_filter = _SOURCE_FILTERS.get(data_source, _SOURCE_FILTERS["all"])

    query = text(f"""
        SELECT
            date_trunc('hour', timestamp) AS bucket,
            account_id,
            service,
            region,
            SUM(cost_amount::float)   AS total_cost,
            SUM(usage_amount::float)  AS total_usage,
            COUNT(*)                  AS event_count
        FROM billing_events_raw
        WHERE {source_filter}
          AND timestamp >= NOW() - INTERVAL '{int(lookback_days)} days'
        GROUP BY 1, account_id, service, region
        ORDER BY account_id, service, region, bucket
    """)

    rows = db.execute(query).fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["bucket", "account_id", "service", "region",
                     "total_cost", "total_usage", "event_count"]
        )

    df = pd.DataFrame(rows, columns=["bucket", "account_id", "service", "region",
                                      "total_cost", "total_usage", "event_count"])
    df["bucket"] = pd.to_datetime(df["bucket"], utc=True)
    return df


# ---------------------------------------------------------------------------
# GCP billing seed data
# ---------------------------------------------------------------------------


_GCP_SEED_PROJECTS: dict[str, dict[str, float]] = {
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

_GCP_SEED_REGIONS = ["us-central1", "us-east1", "europe-west1"]
_GCP_SEED_REGION_WEIGHTS = {"us-central1": 0.50, "us-east1": 0.30, "europe-west1": 0.20}

_GCP_SEED_USAGE = {
    "Compute Engine":    ("vCPU-hour",       150.0),
    "Cloud Storage":     ("gibibyte month",  500.0),
    "BigQuery":          ("tebibyte",          0.8),
    "Cloud SQL":         ("vCPU-hour",        48.0),
    "Kubernetes Engine": ("vCPU-hour",       210.0),
    "Cloud Functions":   ("invocations",  120000.0),
}


def _train_default_profile(db: Session) -> None:
    """Train both baseline and autoencoder into the Default profile artifact dir.

    Called once after seeding GCP data so the Default profile ships pre-trained.
    Silently skips if ML packages are unavailable or data is insufficient.
    """
    artifact_dir = _profile_artifact_dir("default")
    Path(artifact_dir).mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.baseline import BaselineConfig, TimeSeriesBaselineModel
        from ml.src.models.autoencoder import AutoencoderConfig, AutoencoderDetector
    except ImportError as exc:
        logger.warning("Skipping default profile auto-train — ML packages unavailable: %s", exc)
        return

    df = _load_billing_df(db, lookback_days=30, data_source="all")
    if df.empty or len(df) < 60:
        logger.warning("Skipping default profile auto-train — only %d rows", len(df))
        return

    df_tc = TimeContextFeatures().transform(df)

    # --- baseline ---
    try:
        cfg_b = BaselineConfig(artifact_dir=artifact_dir, min_train_rows=60)
        baseline = TimeSeriesBaselineModel(cfg_b)
        t0 = time.monotonic()
        baseline.fit_group(df_tc)
        elapsed_b = round(time.monotonic() - t0, 3)

        version: str | None = None
        try:
            from ml.src.training.versioning import ModelVersionRegistry
            registry = ModelVersionRegistry(artifact_dir)
            entry = registry.register(baseline, train_rows=len(df_tc), lookback_days=30)
            version = entry.version
        except Exception:
            baseline.save(artifact_dir)

        logger.info("Default profile baseline trained: %d rows, %.2fs, v=%s", len(df_tc), elapsed_b, version)
    except Exception as exc:
        logger.error("Default profile baseline training failed: %s", exc, exc_info=True)

    # --- autoencoder ---
    # NOTE: Do NOT add rolling window features here. The OnlineScorer inference
    # pipeline does not produce them, so the AE must be trained only on features
    # available at scoring time (time-context + cost/usage columns).
    try:
        cfg_a = AutoencoderConfig(
            artifact_dir=artifact_dir,
            min_train_rows=60,
            random_state=42,
            hidden_dim=10,
            max_iter=1000,
            exclude_cols=["event_count"],
        )
        detector = AutoencoderDetector(cfg_a)
        t0 = time.monotonic()
        detector.fit(df_tc)
        elapsed_a = round(time.monotonic() - t0, 3)
        detector.save(artifact_dir)
        logger.info("Default profile autoencoder trained: %d rows, %.2fs", len(df_tc), elapsed_a)
    except Exception as exc:
        logger.error("Default profile autoencoder training failed: %s", exc, exc_info=True)


def _seed_gcp_training_data(db: Session) -> int:
    """Insert 14 days of realistic GCP Cloud Billing training data.

    Data is deterministic (seed=42) and mimics the hourly line-item output of
    Google Cloud Billing Export to BigQuery, pre-mapped to FinGuard columns.
    Patterns include:
      - daily seasonality  (peak 09-17)
      - weekly seasonality (weekends ~60 %)
      - slight upward trend
      - Gaussian noise (σ ≈ 8 %)
    """
    rng = random.Random(42)

    start = datetime.now(tz=UTC) - timedelta(days=14)
    start = start.replace(minute=0, second=0, microsecond=0)
    hours = 14 * 24  # 336 h

    count = 0
    for h in range(hours):
        ts = start + timedelta(hours=h)
        hod = ts.hour
        dow = ts.weekday()

        # daily: Gaussian bump centred at 13:00
        daily = 1.0 + 0.30 * math.exp(-0.5 * ((hod - 13) / 4) ** 2)
        # weekly: weekends are quieter
        weekly = 0.60 if dow >= 5 else 1.0
        # trend: +0.1 % per hour
        trend = 1.0 + 0.001 * h

        for project_id, services in _GCP_SEED_PROJECTS.items():
            for service, base_cost in services.items():
                for region in _GCP_SEED_REGIONS:
                    rw = _GCP_SEED_REGION_WEIGHTS[region]
                    unit, usage_base = _GCP_SEED_USAGE[service]

                    cost = base_cost * rw * daily * weekly * trend
                    cost *= 1.0 + rng.gauss(0, 0.08)
                    cost = max(0.01, round(cost, 6))

                    usage = usage_base * rw * daily * weekly
                    usage *= 1.0 + rng.gauss(0, 0.05)
                    usage = max(0.001, round(usage, 6))

                    db.add(BillingEventRow(
                        event_id=uuid.uuid4(),
                        timestamp=ts,
                        provider="gcp",
                        account_id=project_id,
                        service=service,
                        region=region,
                        cost_amount=cost,
                        usage_amount=usage,
                        usage_unit=unit,
                        tags={
                            "env": "prod" if "prod" in project_id else "staging",
                            "team": "finops",
                        },
                        source_type="training_generated",
                    ))
                    count += 1

                    if count % 2000 == 0:
                        db.flush()

    db.commit()
    logger.info("Seeded %d GCP Cloud Billing training rows (14 days)", count)
    return count



# ---------------------------------------------------------------------------
# Endpoints — Status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=TrainingStatusResponse,
    summary="Model artifact status and training data stats",
    dependencies=[Depends(require_admin)],
)
def training_status(
    db: Session | None = Depends(get_db),
) -> TrainingStatusResponse:
    """Return artifact metadata for both trained models plus data stats."""
    data = DataStats() if db is None else _data_stats(db)
    artifact_dir = _active_artifact_dir()
    return TrainingStatusResponse(
        baseline=_baseline_status(artifact_dir),
        autoencoder=_autoencoder_status(artifact_dir),
        data=data,
    )


# ---------------------------------------------------------------------------
# Endpoints — Data management
# ---------------------------------------------------------------------------


@router.post(
    "/data/upload",
    response_model=UploadResult,
    summary="Upload CSV training data",
    dependencies=[Depends(require_admin)],
)
async def upload_training_data(
    file: UploadFile = File(...),
    db: Session | None = Depends(get_db),
) -> UploadResult:
    """
    Parse an uploaded CSV and insert rows into billing_events_raw
    with source_type='training_uploaded'.

    Required columns: timestamp, account_id, service, region,
                      cost_amount, usage_amount.
    Optional columns: provider (default 'custom'),
                      usage_unit (default 'units').
    """
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")

    content = await file.read()
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded CSV")

    reader = csv.DictReader(io.StringIO(text_content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV file is empty or has no header row")

    cols = {c.strip().lower() for c in reader.fieldnames}

    # Auto-detect GCP Cloud Billing export format and build a column remap
    is_gcp = len(cols & _GCP_DETECT_COLS) >= 2
    col_remap: dict[str, str] = {}
    if is_gcp:
        for raw_name in reader.fieldnames:
            key = raw_name.strip().lower()
            col_remap[raw_name] = _GCP_COL_MAP.get(key, key)
        logger.info("Detected GCP Cloud Billing export format — auto-mapping columns")

    # After potential remap, check required columns
    effective_cols = {col_remap.get(c, c.strip().lower()) for c in reader.fieldnames}
    missing = _UPLOAD_REQUIRED - effective_cols
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(sorted(missing))}",
        )

    accepted = failed = 0
    errors: list[str] = []
    for i, raw_row in enumerate(reader, start=2):  # row 1 = header
        # Remap GCP column names to FinGuard names
        row = {col_remap.get(k, k): v for k, v in raw_row.items()} if is_gcp else raw_row

        # Skip tax / adjustment rows in GCP exports
        cost_type = (row.get("cost_type") or "").strip().lower()
        if is_gcp and cost_type and cost_type != "regular":
            continue

        try:
            ts = datetime.fromisoformat(
                row["timestamp"].strip().replace("Z", "+00:00")
            )
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            db.add(BillingEventRow(
                event_id=uuid.uuid4(),
                timestamp=ts,
                provider=row.get("provider", "gcp" if is_gcp else "custom").strip() or "custom",
                account_id=row["account_id"].strip(),
                service=row["service"].strip(),
                region=row["region"].strip(),
                cost_amount=round(float(row["cost_amount"]), 6),
                usage_amount=round(float(row["usage_amount"]), 6),
                usage_unit=row.get("usage_unit", "units").strip() or "units",
                tags={},
                source_type="training_uploaded",
            ))
            accepted += 1
        except Exception as exc:
            failed += 1
            if len(errors) < 10:
                errors.append(f"Row {i}: {exc}")

    if accepted:
        db.commit()

    logger.info("CSV upload: %d accepted, %d failed out of %d rows", accepted, failed, accepted + failed)
    return UploadResult(
        accepted=accepted,
        failed=failed,
        total=accepted + failed,
        errors=errors,
    )


@router.get(
    "/data",
    response_model=TrainingDataPage,
    summary="Paginated preview of training data",
    dependencies=[Depends(require_admin)],
)
def list_training_data(
    page: int = 1,
    page_size: int = 50,
    source: str = "all",
    db: Session | None = Depends(get_db),
) -> TrainingDataPage:
    """
    Return a paginated view of billing_events_raw rows marked as training data.
    ``source`` can be "all", "generated", or "uploaded".
    """
    if db is None:
        return TrainingDataPage(rows=[], total=0, page=page, page_size=page_size, pages=0)

    source_filter = _SOURCE_FILTERS.get(source, _SOURCE_FILTERS["all"])
    offset = (max(page, 1) - 1) * page_size

    total_row = db.execute(
        text(f"SELECT COUNT(*) FROM billing_events_raw WHERE {source_filter}")
    ).scalar_one()

    rows = db.execute(
        text(f"""
            SELECT timestamp, provider, account_id, service, region,
                   cost_amount::float, usage_amount::float, usage_unit, source_type
            FROM billing_events_raw
            WHERE {source_filter}
            ORDER BY timestamp DESC
            LIMIT {int(page_size)} OFFSET {int(offset)}
        """)
    ).fetchall()

    return TrainingDataPage(
        rows=[
            TrainingRow(
                timestamp=r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                provider=r[1],
                account_id=r[2],
                service=r[3],
                region=r[4],
                cost_amount=round(r[5], 4),
                usage_amount=round(r[6], 4),
                usage_unit=r[7],
                source="generated" if r[8] == "training_generated" else "uploaded",
            )
            for r in rows
        ],
        total=total_row,
        page=page,
        page_size=page_size,
        pages=max(1, -(-total_row // page_size)),  # ceil division
    )


@router.get(
    "/data/export",
    summary="Export training data as CSV",
    dependencies=[Depends(require_admin)],
)
def export_training_data(
    db: Session | None = Depends(get_db),
) -> StreamingResponse:
    """
    Stream all training data (generated + uploaded) as a CSV file.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")

    rows = db.execute(
        text("""
            SELECT timestamp, provider, account_id, service, region,
                   cost_amount, usage_amount, usage_unit, source_type
            FROM billing_events_raw
            WHERE source_type IN ('training_generated', 'training_uploaded')
            ORDER BY timestamp
        """)
    ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "provider", "account_id", "service",
                     "region", "cost_amount", "usage_amount", "usage_unit", "source"])
    for r in rows:
        writer.writerow([
            r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
            r[1], r[2], r[3], r[4],
            float(r[5]), float(r[6]), r[7],
            "generated" if r[8] == "training_generated" else "uploaded",
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=training_data.csv"},
    )


# ---------------------------------------------------------------------------
# Endpoints — Model training
# ---------------------------------------------------------------------------


@router.post(
    "/baseline",
    response_model=TrainResult,
    summary="Train time-series baseline model",
    dependencies=[Depends(require_admin)],
)
def train_baseline(
    body: TrainRequest = TrainRequest(),
    db: Session | None = Depends(get_db),
) -> TrainResult:
    """
    Fit TimeSeriesBaselineModel on training billing events and save to artifacts.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")

    try:
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.baseline import BaselineConfig, TimeSeriesBaselineModel
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"ML package not available: {exc}")

    df = _load_billing_df(db, body.lookback_days, body.data_source)
    if df.empty or len(df) < body.min_train_rows:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Not enough data: {len(df)} rows available, "
                f"need >= {body.min_train_rows}. Generate or upload data first."
            ),
        )

    df = TimeContextFeatures().transform(df)

    if body.profile_id:
        index = _read_index()
        if not any(p["id"] == body.profile_id for p in index.get("profiles", [])):
            raise HTTPException(status_code=404, detail=f"Profile '{body.profile_id}' not found")
        artifact_dir = _profile_artifact_dir(body.profile_id)
    else:
        artifact_dir = _active_artifact_dir()

    resolved_id = body.profile_id or _read_index().get("active")
    if resolved_id == "default":
        raise HTTPException(status_code=403, detail="The Default profile is read-only and cannot be retrained.")

    Path(artifact_dir).mkdir(parents=True, exist_ok=True)

    cfg = BaselineConfig(artifact_dir=artifact_dir, min_train_rows=body.min_train_rows)
    model = TimeSeriesBaselineModel(cfg)

    t0 = time.monotonic()
    model.fit_group(df)
    elapsed = round(time.monotonic() - t0, 3)

    # Try versioned save; fall back to plain save
    version: str | None = None
    try:
        from ml.src.training.versioning import ModelVersionRegistry
        registry = ModelVersionRegistry(artifact_dir)
        entry = registry.register(model, train_rows=len(df), lookback_days=body.lookback_days)
        version = entry.version
    except Exception:
        model.save(artifact_dir)

    logger.info("Baseline retrain: %d rows, %.2fs, artifact=%s", len(df), elapsed, artifact_dir)
    return TrainResult(
        model="baseline",
        train_rows=len(df),
        elapsed_seconds=elapsed,
        artifact_dir=artifact_dir,
        version=version,
    )


@router.post(
    "/autoencoder",
    response_model=TrainResult,
    summary="Train autoencoder anomaly detection model",
    dependencies=[Depends(require_admin)],
)
def train_autoencoder(
    body: TrainRequest = TrainRequest(),
    db: Session | None = Depends(get_db),
) -> TrainResult:
    """
    Fit AutoencoderDetector on training billing events and save to artifacts.

    Aggregates training data → hourly buckets → time context features
    → rolling window features → trains a shallow MLP autoencoder whose
    reconstruction error serves as the anomaly signal in the ENS-01 ensemble.
    """
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")

    try:
        from ml.src.features.extractor import RollingWindowExtractor, WindowConfig
        from ml.src.features.time_context import TimeContextFeatures
        from ml.src.models.autoencoder import AutoencoderConfig, AutoencoderDetector
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"ML package not available: {exc}")

    df = _load_billing_df(db, body.lookback_days, body.data_source)
    if df.empty or len(df) < body.min_train_rows:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Not enough data: {len(df)} rows available, "
                f"need >= {body.min_train_rows}. Generate or upload data first."
            ),
        )

    df = TimeContextFeatures().transform(df)

    if body.profile_id:
        index = _read_index()
        if not any(p["id"] == body.profile_id for p in index.get("profiles", [])):
            raise HTTPException(status_code=404, detail=f"Profile '{body.profile_id}' not found")
        artifact_dir = _profile_artifact_dir(body.profile_id)
    else:
        artifact_dir = _active_artifact_dir()

    resolved_id = body.profile_id or _read_index().get("active")
    if resolved_id == "default":
        raise HTTPException(status_code=403, detail="The Default profile is read-only and cannot be retrained.")

    Path(artifact_dir).mkdir(parents=True, exist_ok=True)

    # NOTE: Rolling window features are NOT added here. The OnlineScorer
    # inference pipeline does not produce them, so training with them would
    # cause a feature mismatch (missing features imputed as 0 → if_score=1.0).
    cfg = AutoencoderConfig(
        artifact_dir=artifact_dir,
        min_train_rows=body.min_train_rows,
        random_state=42,
        hidden_dim=10,
        max_iter=1000,
        exclude_cols=["event_count"],
    )
    detector = AutoencoderDetector(cfg)

    t0 = time.monotonic()
    detector.fit(df)
    elapsed = round(time.monotonic() - t0, 3)
    detector.save(artifact_dir)

    logger.info(
        "Autoencoder retrain: %d rows, %d features, %.2fs, artifact=%s",
        len(df),
        len(detector.feature_cols),
        elapsed,
        artifact_dir,
    )
    return TrainResult(
        model="autoencoder",
        train_rows=len(df),
        elapsed_seconds=elapsed,
        artifact_dir=artifact_dir,
    )


# ---------------------------------------------------------------------------
# Endpoints — Profile management
# ---------------------------------------------------------------------------


@router.get(
    "/profiles",
    response_model=ProfilesResponse,
    summary="List all FinGuard profiles",
    dependencies=[Depends(require_admin)],
)
def list_profiles(db: Session | None = Depends(get_db)) -> ProfilesResponse:
    """Return all saved FinGuard model profiles with their artifact status."""
    index = _read_index()
    profiles = index.get("profiles", [])

    # Auto-create a Default profile and seed GCP training data on first run
    if not profiles:
        profile_id = "default"
        now = datetime.now(tz=UTC).isoformat()
        index = {
            "active": profile_id,
            "profiles": [{"id": profile_id, "name": "Default", "created_at": now}],
        }
        _write_index(index)
        (_PROFILES_DIR / profile_id).mkdir(parents=True, exist_ok=True)
        profiles = index["profiles"]

        # Seed realistic GCP Cloud Billing data and train the Default profile.
        if db is not None:
            stats = _data_stats(db)
            if stats.total == 0:
                try:
                    _seed_gcp_training_data(db)
                except Exception as exc:
                    logger.error("Auto-seed failed: %s", exc, exc_info=True)

            # Train both models so the Default profile ships pre-trained
            default_dir = _profile_artifact_dir("default")
            baseline_trained = (Path(default_dir) / "baseline_seasonal_profile.json").exists() or \
                               (Path(default_dir) / "manifest.json").exists()
            ae_trained = (Path(default_dir) / "ae_model.pkl").exists()
            if not (baseline_trained and ae_trained):
                try:
                    _train_default_profile(db)
                except Exception as exc:
                    logger.error("Auto-train default failed: %s", exc, exc_info=True)

    active_id = index.get("active")
    result = []
    for p in profiles:
        pid = p["id"]
        adir = _profile_artifact_dir(pid)
        result.append(ProfileEntry(
            id=pid,
            name=p["name"],
            created_at=p["created_at"],
            active=(pid == active_id),
            baseline=_baseline_status(adir),
            autoencoder=_autoencoder_status(adir),
        ))
    return ProfilesResponse(profiles=result, active_id=active_id)


@router.post(
    "/profiles",
    response_model=ProfileEntry,
    summary="Create a new FinGuard profile",
    dependencies=[Depends(require_admin)],
)
def create_profile(body: CreateProfileRequest) -> ProfileEntry:
    """Create a new empty FinGuard profile."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name cannot be empty")

    index = _read_index()
    profiles = index.get("profiles", [])

    if any(p["name"].lower() == name.lower() for p in profiles):
        raise HTTPException(status_code=409, detail=f"A profile named '{name}' already exists")

    profile_id = uuid.uuid4().hex[:8]
    now = datetime.now(tz=UTC).isoformat()
    new_entry = {"id": profile_id, "name": name, "created_at": now}
    profiles.append(new_entry)
    index["profiles"] = profiles

    # First profile becomes active automatically
    if len(profiles) == 1:
        index["active"] = profile_id

    _write_index(index)
    (_PROFILES_DIR / profile_id).mkdir(parents=True, exist_ok=True)

    adir = _profile_artifact_dir(profile_id)
    return ProfileEntry(
        id=profile_id,
        name=name,
        created_at=now,
        active=index.get("active") == profile_id,
        baseline=_baseline_status(adir),
        autoencoder=_autoencoder_status(adir),
    )


@router.patch(
    "/profiles/{profile_id}",
    response_model=ProfileEntry,
    summary="Rename a FinGuard profile",
    dependencies=[Depends(require_admin)],
)
def rename_profile(profile_id: str, body: RenameProfileRequest) -> ProfileEntry:
    """Rename an existing FinGuard profile."""
    if profile_id == "default":
        raise HTTPException(status_code=403, detail="The Default profile cannot be renamed.")

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name cannot be empty")

    index = _read_index()
    profiles = index.get("profiles", [])
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    if any(p["name"].lower() == name.lower() and p["id"] != profile_id for p in profiles):
        raise HTTPException(status_code=409, detail=f"A profile named '{name}' already exists")

    target["name"] = name
    _write_index(index)

    adir = _profile_artifact_dir(profile_id)
    return ProfileEntry(
        id=profile_id,
        name=name,
        created_at=target["created_at"],
        active=index.get("active") == profile_id,
        baseline=_baseline_status(adir),
        autoencoder=_autoencoder_status(adir),
    )


@router.post(
    "/profiles/{profile_id}/activate",
    response_model=ProfilesResponse,
    summary="Activate a FinGuard profile",
    dependencies=[Depends(require_admin)],
)
def activate_profile(profile_id: str) -> ProfilesResponse:
    """Set a profile as the active model used for training and inference."""
    index = _read_index()
    profiles = index.get("profiles", [])

    if not any(p["id"] == profile_id for p in profiles):
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    index["active"] = profile_id
    _write_index(index)

    active_id = profile_id
    result = []
    for p in profiles:
        pid = p["id"]
        adir = _profile_artifact_dir(pid)
        result.append(ProfileEntry(
            id=pid,
            name=p["name"],
            created_at=p["created_at"],
            active=(pid == active_id),
            baseline=_baseline_status(adir),
            autoencoder=_autoencoder_status(adir),
        ))
    return ProfilesResponse(profiles=result, active_id=active_id)


@router.delete(
    "/profiles/{profile_id}",
    response_model=ProfilesResponse,
    summary="Delete a FinGuard profile",
    dependencies=[Depends(require_admin)],
)
def delete_profile(profile_id: str) -> ProfilesResponse:
    """Delete a FinGuard profile and its saved artifacts."""
    index = _read_index()
    profiles = index.get("profiles", [])

    if not any(p["id"] == profile_id for p in profiles):
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")

    # The Default profile is permanent — cannot be deleted by anyone
    if profile_id == "default":
        raise HTTPException(status_code=403, detail="The Default profile cannot be deleted.")

    if index.get("active") == profile_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the active profile. Activate a different profile first.",
        )

    index["profiles"] = [p for p in profiles if p["id"] != profile_id]
    _write_index(index)

    profile_dir = _PROFILES_DIR / profile_id
    if profile_dir.exists():
        shutil.rmtree(profile_dir)

    active_id = index.get("active")
    result = []
    for p in index["profiles"]:
        pid = p["id"]
        adir = _profile_artifact_dir(pid)
        result.append(ProfileEntry(
            id=pid,
            name=p["name"],
            created_at=p["created_at"],
            active=(pid == active_id),
            baseline=_baseline_status(adir),
            autoencoder=_autoencoder_status(adir),
        ))
    return ProfilesResponse(profiles=result, active_id=active_id)
