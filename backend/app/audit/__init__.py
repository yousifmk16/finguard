"""SEC-04: audit logging package.

Public surface:
    record_event           – low-level recorder, wraps the repository.
    record_login_success   – auth audit helper.
    record_login_failure   – auth audit helper (NULL user_id when unknown email).
    record_admin_action    – privileged-action audit helper.
    request_context        – extract (ip, user_agent) from a FastAPI Request.

    EVENT_AUTH_LOGIN, EVENT_INGEST_EVENT, EVENT_ANOMALY_STATUS_UPDATE,
    OUTCOME_SUCCESS, OUTCOME_FAILURE — string constants used in queries.
"""

from app.audit.recorder import (
    EVENT_ANOMALY_STATUS_UPDATE,
    EVENT_AUTH_LOGIN,
    EVENT_INGEST_EVENT,
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    record_admin_action,
    record_event,
    record_login_failure,
    record_login_success,
    request_context,
)

__all__ = [
    "EVENT_ANOMALY_STATUS_UPDATE",
    "EVENT_AUTH_LOGIN",
    "EVENT_INGEST_EVENT",
    "OUTCOME_FAILURE",
    "OUTCOME_SUCCESS",
    "record_admin_action",
    "record_event",
    "record_login_failure",
    "record_login_success",
    "request_context",
]
