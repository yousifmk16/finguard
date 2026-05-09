"""Admin-only user listing endpoint."""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.rbac import require_admin
from app.db.models.user import UserRow
from app.db.session import get_db
from app.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get(
    "/users",
    summary="List users (admin only)",
    dependencies=[Depends(require_admin)],
)
def list_users(
    db: Session | None = Depends(get_db),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    if db is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}

    total = db.execute(select(func.count()).select_from(UserRow)).scalar_one()
    rows = db.execute(
        select(UserRow).order_by(UserRow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return {
        "items": [
            {
                "user_id": str(r.user_id),
                "email": r.email,
                "role": r.role,
                "is_active": r.is_active,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total > 0 else 0,
    }
