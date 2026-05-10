"""Admin-only user management endpoints."""

from __future__ import annotations

import uuid
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.rbac import require_admin
from app.core.security import hash_password
from app.db.models.user import UserRow
from app.db.repos.user_repo import UserRepository
from app.db.session import get_db
from app.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1", tags=["users"])

_repo = UserRepository()


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: Literal["admin", "analyst"] = "analyst"


@router.post(
    "/users",
    summary="Create a new user (admin only)",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_user(
    body: CreateUserRequest,
    db: Session | None = Depends(get_db),
) -> dict:
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")
    if _repo.get_by_email(db, body.email):
        raise HTTPException(status_code=409, detail="email already registered")

    user = _repo.create(db, email=body.email, hashed_password=hash_password(body.password), role=body.role)
    db.commit()
    db.refresh(user)
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


class UpdateRoleRequest(BaseModel):
    role: Literal["admin", "analyst"]


@router.patch(
    "/users/{user_id}/role",
    summary="Update a user's role (admin only)",
    dependencies=[Depends(require_admin)],
)
def update_role(
    user_id: uuid.UUID,
    body: UpdateRoleRequest,
    db: Session | None = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict:
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    if str(user_id) == str(current_user.user_id):
        raise HTTPException(status_code=400, detail="cannot change your own role")
    user = _repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.role == "admin" and body.role != "admin" and _repo.count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="cannot demote the last admin")
    user.role = body.role
    db.commit()
    db.refresh(user)
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


@router.delete(
    "/users/{user_id}",
    summary="Delete a user (admin only)",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_admin)],
)
def delete_user(
    user_id: uuid.UUID,
    db: Session | None = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> None:
    if db is None:
        raise HTTPException(status_code=503, detail="database not configured")
    if str(user_id) == str(current_user.user_id):
        raise HTTPException(status_code=400, detail="cannot delete your own account")

    target = _repo.get_by_id(db, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target.role == "admin" and _repo.count_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="cannot delete the last admin account")

    _repo.delete(db, user_id)
    db.commit()


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
