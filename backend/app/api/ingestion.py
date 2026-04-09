from fastapi import APIRouter

from app.schemas.event import BillingEvent, IngestionReceipt

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


@router.post(
    "/events",
    response_model=IngestionReceipt,
    status_code=202,
    summary="Ingest a billing event",
)
def ingest_event(event: BillingEvent) -> IngestionReceipt:
    """Accept and validate a canonical billing event (ARC-04).

    Persistence is handled by a downstream worker once DB-01 is complete.
    """
    return IngestionReceipt(event_id=event.event_id)
