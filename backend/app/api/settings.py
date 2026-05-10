"""Detection threshold settings.

GET  /api/v1/settings/thresholds  — read current thresholds (analyst+)
PUT  /api/v1/settings/thresholds  — update thresholds and re-classify
                                    all existing anomalies (admin only)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.api.rbac import require_admin, require_analyst_or_admin
from app.db.models.anomaly import AnomalyRow
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# In-memory store — survives the process lifetime, reset on restart
_store: dict[str, float] = {"high": 0.80, "medium": 0.50, "low": 0.20}


class Thresholds(BaseModel):
    high: float = Field(0.80, ge=0.0, le=1.0)
    medium: float = Field(0.50, ge=0.0, le=1.0)
    low: float = Field(0.20, ge=0.0, le=1.0)


@router.get(
    "/thresholds",
    response_model=Thresholds,
    summary="Get detection thresholds",
    dependencies=[Depends(require_analyst_or_admin)],
)
def get_thresholds() -> Thresholds:
    return Thresholds(**_store)


@router.put(
    "/thresholds",
    response_model=Thresholds,
    summary="Update detection thresholds and re-classify anomalies",
    dependencies=[Depends(require_admin)],
)
def put_thresholds(
    body: Thresholds,
    db: Session | None = Depends(get_db),
) -> Thresholds:
    _store.update(body.model_dump())

    if db is not None:
        db.execute(
            update(AnomalyRow).values(
                severity=case(
                    (AnomalyRow.anomaly_score >= body.high, "high"),
                    (AnomalyRow.anomaly_score >= body.medium, "medium"),
                    else_="low",
                )
            )
        )
        db.commit()

    return Thresholds(**_store)
