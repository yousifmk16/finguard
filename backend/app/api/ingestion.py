from fastapi import APIRouter, Response

from app.core.idempotency import store as idempotency_store
from app.schemas.event import BillingEvent, IngestionReceipt

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


@router.post(
    "/events",
    response_model=IngestionReceipt,
    status_code=202,
    responses={200: {"description": "Event already accepted (duplicate event_id)"}},
    summary="Ingest a billing event",
)
def ingest_event(event: BillingEvent, response: Response) -> IngestionReceipt:
    """Accept and validate a canonical billing event (ARC-04).

    Duplicate ``event_id`` values are handled idempotently: the original
    receipt is returned with ``duplicate=true`` and HTTP 200 instead of 202.
    Persistence is wired up once DB-01 is complete.
    """
    if idempotency_store.is_duplicate(event.event_id):
        response.status_code = 200
        return IngestionReceipt(event_id=event.event_id, duplicate=True)

    idempotency_store.register(event.event_id)
    return IngestionReceipt(event_id=event.event_id)
