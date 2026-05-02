"""SEC-01: password hashing and JWT helpers.

This module is the single trust boundary for credential handling and
session tokens. It exposes:

* ``hash_password`` / ``verify_password`` — bcrypt-backed credential
  storage so plaintext passwords never reach the database.
* ``create_access_token`` / ``decode_access_token`` — symmetric HS256
  JWTs carrying the user id (``sub``), role, and expiry. SEC-02 will
  consume the decoded claims to enforce RBAC.

Configuration is read from environment variables:

* ``JWT_SECRET``           – HMAC secret. Must be set in non-test envs.
* ``JWT_ALGORITHM``        – default ``HS256``.
* ``JWT_EXPIRE_MINUTES``   – default ``60``.

A fallback secret is used only when ``JWT_SECRET`` is unset so unit
tests can run without env wiring; production deploys must override it.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

_DEV_FALLBACK_SECRET = "finguard-dev-secret-change-me"  # noqa: S105
_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


def _secret() -> str:
    return os.getenv("JWT_SECRET") or _DEV_FALLBACK_SECRET


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash of ``plaintext``."""
    if not plaintext:
        raise ValueError("password must be non-empty")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff ``plaintext`` matches the stored bcrypt ``hashed``."""
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    *,
    user_id: uuid.UUID | str,
    role: str,
    expires_minutes: int | None = None,
) -> str:
    """Encode a signed JWT carrying ``sub`` (user id) and ``role``.

    Payload includes ``iat`` and ``exp`` (UTC). Pass ``expires_minutes``
    only to override the default lifetime (e.g. tests for expiry).
    """
    now = datetime.now(tz=UTC)
    minutes = expires_minutes if expires_minutes is not None else _EXPIRE_MINUTES
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT, returning its claims.

    Raises ``jwt.PyJWTError`` (or subclass) on malformed, invalid, or
    expired tokens. Callers should translate those into HTTP 401.
    """
    return jwt.decode(token, _secret(), algorithms=[_ALGORITHM])


def access_token_ttl_seconds() -> int:
    """Default token lifetime, exposed for ``TokenResponse.expires_in``."""
    return _EXPIRE_MINUTES * 60
