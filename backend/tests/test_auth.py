"""SEC-01: tests for JWT login + get_current_user dependency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock

import jwt
import pytest
from app.api.auth import get_current_user
from app.api.auth import router as auth_router
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.main import app
from app.schemas.auth import CurrentUser
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

client = TestClient(app)

_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@dataclass
class _FakeUser:
    user_id: uuid.UUID
    email: str
    hashed_password: str
    role: str
    is_active: bool = True


def _seed_user(password: str = "correct-horse", role: str = "analyst") -> _FakeUser:
    return _FakeUser(
        user_id=_USER_ID,
        email="user@example.com",
        hashed_password=hash_password(password),
        role=role,
    )


def _db_with(scalar_value: object) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = scalar_value
    return db


# ---------------------------------------------------------------------------
# password helpers
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_then_verify_succeeds(self):
        h = hash_password("s3cret")
        assert verify_password("s3cret", h)

    def test_verify_rejects_wrong_password(self):
        h = hash_password("s3cret")
        assert not verify_password("wrong", h)

    def test_verify_handles_malformed_hash(self):
        assert not verify_password("anything", "not-a-bcrypt-hash")

    def test_hash_rejects_empty(self):
        with pytest.raises(ValueError):
            hash_password("")


# ---------------------------------------------------------------------------
# JWT encode/decode
# ---------------------------------------------------------------------------


class TestJwtRoundtrip:
    def test_encode_decode_preserves_claims(self):
        token = create_access_token(user_id=_USER_ID, role="admin")
        claims = decode_access_token(token)
        assert claims["sub"] == str(_USER_ID)
        assert claims["role"] == "admin"
        assert "exp" in claims and "iat" in claims

    def test_expired_token_rejected(self):
        token = create_access_token(
            user_id=_USER_ID, role="analyst", expires_minutes=-1
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_tampered_token_rejected(self):
        token = create_access_token(user_id=_USER_ID, role="analyst")
        tampered = token + "x"
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(tampered)


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestLoginEndpoint:
    def teardown_method(self):
        app.dependency_overrides.pop(get_db, None)

    def test_valid_credentials_returns_token(self):
        user = _seed_user(password="hunter2", role="admin")
        app.dependency_overrides[get_db] = lambda: _db_with(user)

        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "hunter2"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["role"] == "admin"
        assert body["expires_in"] > 0

        claims = decode_access_token(body["access_token"])
        assert claims["sub"] == str(_USER_ID)
        assert claims["role"] == "admin"

    def test_unknown_email_returns_401(self):
        app.dependency_overrides[get_db] = lambda: _db_with(None)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "x"},
        )
        assert r.status_code == 401

    def test_wrong_password_returns_401(self):
        user = _seed_user(password="right")
        app.dependency_overrides[get_db] = lambda: _db_with(user)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong"},
        )
        assert r.status_code == 401

    def test_inactive_user_returns_401(self):
        user = _seed_user(password="ok")
        user.is_active = False
        app.dependency_overrides[get_db] = lambda: _db_with(user)
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "ok"},
        )
        assert r.status_code == 401

    def test_no_db_returns_503(self):
        app.dependency_overrides[get_db] = lambda: None
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "x"},
        )
        assert r.status_code == 503

    def test_malformed_email_returns_422(self):
        app.dependency_overrides[get_db] = lambda: None
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "x"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# get_current_user dependency
# ---------------------------------------------------------------------------


def _build_protected_app() -> tuple[FastAPI, TestClient]:
    """Mount the auth router plus a probe endpoint guarded by get_current_user."""
    test_app = FastAPI()
    test_app.include_router(auth_router)

    @test_app.get("/whoami")
    def whoami(user: CurrentUser = Depends(get_current_user)):  # noqa: B008
        return {"user_id": str(user.user_id), "role": user.role, "email": user.email}

    return test_app, TestClient(test_app)


class TestGetCurrentUser:
    def setup_method(self):
        self.test_app, self.client = _build_protected_app()

    def teardown_method(self):
        self.test_app.dependency_overrides.clear()

    def test_missing_header_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user())
        r = self.client.get("/whoami")
        assert r.status_code == 401

    def test_wrong_scheme_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user())
        r = self.client.get("/whoami", headers={"Authorization": "Basic abc"})
        assert r.status_code == 401

    def test_invalid_token_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user())
        r = self.client.get(
            "/whoami", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert r.status_code == 401

    def test_expired_token_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user())
        token = create_access_token(
            user_id=_USER_ID, role="analyst", expires_minutes=-1
        )
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401

    def test_valid_token_resolves_user(self):
        user = _seed_user(role="admin")
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(user)
        token = create_access_token(user_id=_USER_ID, role="admin")
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == str(_USER_ID)
        assert body["role"] == "admin"
        assert body["email"] == "user@example.com"

    def test_token_for_unknown_user_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(None)
        token = create_access_token(user_id=_USER_ID, role="analyst")
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401

    def test_token_for_inactive_user_returns_401(self):
        user = _seed_user()
        user.is_active = False
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(user)
        token = create_access_token(user_id=_USER_ID, role="analyst")
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401

    def test_token_with_non_uuid_sub_returns_401(self):
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user())
        token = create_access_token(user_id="not-a-uuid", role="analyst")
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
