"""
SEC-01: JWT authentication.

POST /api/v1/auth/login
    Verify email + password against the ``users`` table and return a
    signed bearer token.

get_current_user (FastAPI dependency)
    Resolve the bearer token on the ``Authorization`` header into a
    ``CurrentUser``. Used as a building block for SEC-02 RBAC and the
    role-protected endpoints in SEC-03 — this module does not enforce
    role checks itself.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import (
    access_token_ttl_seconds,
    create_access_token,
    decode_access_token,
    verify_password,
)
from app.db.repos.user_repo import UserRepository
from app.db.session import get_db
from app.schemas.auth import CurrentUser, LoginRequest, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_repo = UserRepository()
_bearer = HTTPBearer(auto_error=False)

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid email or password",
)
_INVALID_TOKEN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)
_DB_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="database not configured",
)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and issue a JWT",
    responses={
        401: {"description": "Invalid credentials"},
        503: {"description": "Database not configured"},
    },
)
def login(
    body: LoginRequest,
    db: Session | None = Depends(get_db),  # noqa: B008
) -> TokenResponse:
    if db is None:
        raise _DB_UNAVAILABLE

    user = _repo.get_by_email(db, body.email)
    if user is None or not user.is_active:
        raise _INVALID_CREDENTIALS
    if not verify_password(body.password, user.hashed_password):
        raise _INVALID_CREDENTIALS

    token = create_access_token(user_id=user.user_id, role=user.role)
    return TokenResponse(
        access_token=token,
        expires_in=access_token_ttl_seconds(),
        role=user.role,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
    db: Session | None = Depends(get_db),  # noqa: B008
) -> CurrentUser:
    """Resolve the bearer token into a ``CurrentUser``.

    Raises 401 if the header is missing/malformed, the token is invalid
    or expired, or the referenced user no longer exists / is inactive.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _INVALID_TOKEN

    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise _INVALID_TOKEN from exc

    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise _INVALID_TOKEN
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise _INVALID_TOKEN from exc

    if db is None:
        raise _DB_UNAVAILABLE

    user = _repo.get_by_id(db, user_id)
    if user is None or not user.is_active:
        raise _INVALID_TOKEN

    return CurrentUser(user_id=user.user_id, email=user.email, role=user.role)
