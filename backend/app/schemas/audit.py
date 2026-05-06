"""SEC-04: Pydantic schemas for the audit log retrieval endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    """One audit log row, as returned by GET /api/v1/audit/logs."""

    audit_id: uuid.UUID
    event_type: str
    action: str
    outcome: str
    user_id: uuid.UUID | None = None
    actor_email: str | None = None
    actor_role: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    meta: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    """Paginated list of audit log entries."""

    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int
    pages: int
