"""
SEC-01: JWT authentication.
SEC-04: login attempts (success + failure) recorded to ``audit_logs``.

POST /api/v1/auth/login
    Verify email + password against the ``users`` table and return a
    signed bearer token. Every attempt — success or failure — is written
    to the audit log with outcome and reason.

get_current_user (FastAPI dependency)
    Resolve the bearer token on the ``Authorization`` header into a
    ``CurrentUser``. Used as a building block for SEC-02 RBAC and the
    role-protected endpoints in SEC-03 — this module does not enforce
    role checks itself.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.audit import (
    record_login_failure,
    record_login_success,
    request_context,
)
from app.core.security import (
    access_token_ttl_seconds,
    create_access_token,
    decode_access_token,
    hash_password,
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
    request: Request,
    db: Session | None = Depends(get_db),  # noqa: B008
) -> TokenResponse:
    if db is None:
        raise _DB_UNAVAILABLE

    ip, ua = request_context(request)

    user = _repo.get_by_email(db, body.email)
    if user is None or not user.is_active:
        record_login_failure(
            db,
            attempted_email=body.email,
            reason="unknown_or_inactive_user",
            user_id=user.user_id if user is not None else None,
            role=user.role if user is not None else None,
            ip_address=ip,
            user_agent=ua,
        )
        raise _INVALID_CREDENTIALS
    if not verify_password(body.password, user.hashed_password):
        record_login_failure(
            db,
            attempted_email=user.email,
            reason="wrong_password",
            user_id=user.user_id,
            role=user.role,
            ip_address=ip,
            user_agent=ua,
        )
        raise _INVALID_CREDENTIALS

    token = create_access_token(user_id=user.user_id, role=user.role)
    record_login_success(
        db,
        user_id=user.user_id,
        email=user.email,
        role=user.role,
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=access_token_ttl_seconds(),
        role=user.role,
    )


class RegisterRequest(LoginRequest):
    pass  # same fields: email + password


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account and issue a JWT",
    responses={
        409: {"description": "Email already registered"},
        422: {"description": "Validation error"},
        503: {"description": "Database not configured"},
    },
)
def register(
    body: RegisterRequest,
    db: Session | None = Depends(get_db),
) -> TokenResponse:
    if db is None:
        raise _DB_UNAVAILABLE
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="password must be at least 8 characters",
        )
    if _repo.get_by_email(db, body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        )
    user = _repo.create(
        db,
        email=body.email,
        hashed_password=hash_password(body.password),
        role="admin",
    )
    db.commit()
    db.refresh(user)
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
