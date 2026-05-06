"""SEC-04: thin write-side helpers for the audit log.

Design notes
------------
* The recorder *stages* an audit row on the supplied session (no commit).
  Auth/admin endpoints already commit at the end of their happy path; the
  audit row rides along on the same transaction so it can never be more
  durable than the action it describes.
* Failed-login callers must commit explicitly before raising 401, since
  raising HTTPException leaves the session uncommitted. Pass
  ``autocommit=True`` to do that in one call.
* All helpers swallow exceptions and log them. Audit logging must never
  break the underlying request — if the audit table is wedged we still
  want the user to be able to log in or triage anomalies.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLogRow
from app.db.repos.audit_log_repo import AuditLogRepository
from app.schemas.auth import CurrentUser

logger = logging.getLogger(__name__)

# Event types — kept here so callers and the read-side filter agree on spelling.
EVENT_AUTH_LOGIN = "auth.login"
EVENT_INGEST_EVENT = "ingest.event"
EVENT_ANOMALY_STATUS_UPDATE = "anomaly.status_update"

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"

# user-agent column is VARCHAR(512); truncate defensively for long UA strings.
_UA_MAX = 512

_repo = AuditLogRepository()


def request_context(request: Request | None) -> tuple[str | None, str | None]:
    """Return ``(ip_address, user_agent)`` extracted from ``request``.

    Honors ``X-Forwarded-For`` (first hop) when present so reverse-proxied
    deployments record the original client IP. Returns ``(None, None)``
    when called outside an HTTP context (e.g. background tasks).
    """
    if request is None:
        return None, None
    ip: str | None = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip() or ip
    ua = request.headers.get("user-agent")
    if ua and len(ua) > _UA_MAX:
        ua = ua[:_UA_MAX]
    return ip, ua


def record_event(
    session: Session | None,
    *,
    event_type: str,
    action: str,
    outcome: str,
    user_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
    autocommit: bool = False,
) -> AuditLogRow | None:
    """Stage an audit row. Best-effort — never raises.

    Returns the staged row on success, ``None`` if the session is missing
    or the underlying write failed (already logged).
    """
    if session is None:
        return None
    try:
        row = _repo.insert(
            session,
            event_type=event_type,
            action=action,
            outcome=outcome,
            user_id=user_id,
            actor_email=actor_email,
            actor_role=actor_role,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta=meta,
        )
        if autocommit:
            session.commit()
        return row
    except Exception:  # noqa: BLE001
        logger.exception(
            "audit recorder failed event_type=%s action=%s outcome=%s",
            event_type,
            action,
            outcome,
        )
        try:
            if autocommit:
                session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("audit recorder rollback also failed")
        return None


# ---------------------------------------------------------------------------
# Convenience wrappers — typed call sites for the three current callers.
# ---------------------------------------------------------------------------


def record_login_success(
    session: Session | None,
    *,
    user_id: uuid.UUID,
    email: str,
    role: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLogRow | None:
    return record_event(
        session,
        event_type=EVENT_AUTH_LOGIN,
        action="login",
        outcome=OUTCOME_SUCCESS,
        user_id=user_id,
        actor_email=email,
        actor_role=role,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def record_login_failure(
    session: Session | None,
    *,
    attempted_email: str,
    reason: str,
    user_id: uuid.UUID | None = None,
    role: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    autocommit: bool = True,
) -> AuditLogRow | None:
    """Record a failed login attempt.

    ``user_id`` is ``None`` when the email did not resolve to a real user
    (avoids fabricating identity). ``autocommit`` defaults to True because
    the auth handler raises 401 immediately after; without it the row
    would be discarded with the rolled-back transaction.
    """
    return record_event(
        session,
        event_type=EVENT_AUTH_LOGIN,
        action="login",
        outcome=OUTCOME_FAILURE,
        user_id=user_id,
        actor_email=attempted_email,
        actor_role=role,
        ip_address=ip_address,
        user_agent=user_agent,
        meta={"reason": reason},
        autocommit=autocommit,
    )


def record_admin_action(
    session: Session | None,
    *,
    event_type: str,
    action: str,
    actor: CurrentUser,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = OUTCOME_SUCCESS,
    ip_address: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLogRow | None:
    return record_event(
        session,
        event_type=event_type,
        action=action,
        outcome=outcome,
        user_id=actor.user_id,
        actor_email=actor.email,
        actor_role=actor.role,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip_address,
        user_agent=user_agent,
        meta=meta,
    )
