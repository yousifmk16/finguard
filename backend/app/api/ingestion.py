from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.rbac import require_admin
from app.audit import (
    EVENT_INGEST_EVENT,
    OUTCOME_SUCCESS,
    record_admin_action,
    request_context,
)
from app.core.idempotency import store as idempotency_store
from app.db.models.billing_event import BillingEventRow
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from app.schemas.event import BillingEvent, IngestionReceipt

router = APIRouter(prefix="/api/v1", tags=["ingestion"])


@router.post(
    "/events",
    response_model=IngestionReceipt,
    status_code=202,
    responses={
        200: {"description": "Event already accepted (duplicate event_id)"},
        401: {"description": "Missing or invalid bearer token"},
        403: {"description": "Authenticated user lacks the admin role"},
    },
    summary="Ingest a billing event",
)
def ingest_event(
    event: BillingEvent,
    response: Response,
    request: Request,
    actor: CurrentUser = Depends(require_admin),  # noqa: B008
    db: Session | None = Depends(get_db),  # noqa: B008
) -> IngestionReceipt:
    """Accept and validate a canonical billing event (ARC-04).

    Duplicate ``event_id`` values are handled idempotently: the original
    receipt is returned with ``duplicate=true`` and HTTP 200 instead of 202.

    When a live DB session is available the event is persisted to
    ``billing_events_raw`` (DB-01).  The in-memory store provides a fast
    pre-check so most duplicates never reach the database.

    SEC-04: every accepted ingest is recorded in ``audit_logs``. Duplicate
    submissions are deliberately *not* re-audited — the original ingest
    already produced a row.
    """
    if idempotency_store.is_duplicate(event.event_id):
        response.status_code = 200
        return IngestionReceipt(event_id=event.event_id, duplicate=True)

    if db is not None:
        row = BillingEventRow(
            event_id=event.event_id,
            timestamp=event.timestamp,
            provider=event.provider,
            account_id=event.account_id,
            service=event.service,
            region=event.region,
            cost_amount=event.cost_amount,
            usage_amount=event.usage_amount,
            usage_unit=event.usage_unit,
            tags=event.tags,
            source_type=event.source_type,
        )
        try:
            db.add(row)
            db.commit()
        except IntegrityError:
            db.rollback()
            # The in-memory store missed this (e.g. restart, multi-worker race);
            # backfill it so the next request is caught without hitting the DB.
            idempotency_store.register(event.event_id)
            response.status_code = 200
            return IngestionReceipt(event_id=event.event_id, duplicate=True)

    idempotency_store.register(event.event_id)

    if db is not None:
        ip, ua = request_context(request)
        record_admin_action(
            db,
            event_type=EVENT_INGEST_EVENT,
            action="ingest",
            actor=actor,
            target_type="billing_event",
            target_id=str(event.event_id),
            outcome=OUTCOME_SUCCESS,
            ip_address=ip,
            user_agent=ua,
            meta={
                "provider": event.provider,
                "account_id": event.account_id,
                "service": event.service,
                "region": event.region,
            },
        )
        db.commit()

    return IngestionReceipt(event_id=event.event_id)
