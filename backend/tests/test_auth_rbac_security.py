"""
TST-06: Auth & RBAC security tests — fills the gaps left by
``test_auth.py``, ``test_rbac.py``, and ``test_rbac_endpoints.py``.

Focus areas:
1. Audit endpoint (SEC-04) wired into the RBAC matrix.
2. Bearer-token parsing edge cases (empty/whitespace/missing claims).
3. **Privilege-escalation pin**: a tampered JWT claiming ``admin`` must
   NOT grant admin access — ``get_current_user`` re-reads the role from
   the DB so this is the contract that protects against token forgery.
4. RFC 6750 ``WWW-Authenticate: Bearer`` header on 401.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import get_current_user, router as auth_router
from app.api.rbac import require_admin, require_analyst_or_admin
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.schemas.auth import CurrentUser

client = TestClient(app)

_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000caf3")


@dataclass
class _FakeUser:
    user_id: uuid.UUID
    email: str
    hashed_password: str
    role: str
    is_active: bool = True


def _db_with(user: _FakeUser | None) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = user
    return db


def _as(role: str) -> CurrentUser:
    return CurrentUser(
        user_id=_USER_ID,
        email=f"{role}@example.com",
        role=role,
    )


# ---------------------------------------------------------------------------
# 1. Audit endpoint RBAC (SEC-04 — admin only)
# ---------------------------------------------------------------------------


@pytest.fixture
def no_auth():
    app.dependency_overrides.pop(get_current_user, None)
    yield


@pytest.fixture
def as_analyst():
    app.dependency_overrides[get_current_user] = lambda: _as("analyst")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def as_admin():
    app.dependency_overrides[get_current_user] = lambda: _as("admin")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def empty_db():
    app.dependency_overrides[get_db] = lambda: None
    yield
    app.dependency_overrides.pop(get_db, None)


class TestAuditEndpointRbac:
    def test_unauthenticated_returns_401(self, no_auth, empty_db) -> None:
        assert client.get("/api/v1/audit/logs").status_code == 401

    def test_analyst_returns_403(self, as_analyst, empty_db) -> None:
        r = client.get("/api/v1/audit/logs")
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden: requires role admin"

    def test_admin_passes_rbac_gate(self, as_admin) -> None:
        # With a mock DB returning empty results the handler should reply 200.
        empty_result = MagicMock()
        empty_result.scalar_one.return_value = 0
        empty_result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute.return_value = empty_result
        app.dependency_overrides[get_db] = lambda: db
        try:
            r = client.get("/api/v1/audit/logs")
            assert r.status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# 2. Bearer-token parsing edge cases
# ---------------------------------------------------------------------------


def _build_protected_app() -> tuple[FastAPI, TestClient]:
    """Mount get_current_user behind a probe route so we can inspect 401 headers."""
    test_app = FastAPI()
    test_app.include_router(auth_router)

    @test_app.get("/whoami")
    def whoami(user: CurrentUser = Depends(get_current_user)):  # noqa: B008
        return {"user_id": str(user.user_id), "role": user.role}

    return test_app, TestClient(test_app)


class TestBearerTokenEdgeCases:
    def setup_method(self) -> None:
        self.test_app, self.client = _build_protected_app()
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user_obj())

    def teardown_method(self) -> None:
        self.test_app.dependency_overrides.clear()

    def test_empty_bearer_returns_401(self) -> None:
        r = self.client.get("/whoami", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_lowercase_bearer_scheme_accepted(self) -> None:
        # Per RFC 7235 the auth scheme is case-insensitive ("bearer" ≡ "Bearer").
        token = create_access_token(user_id=_USER_ID, role="analyst")
        r = self.client.get(
            "/whoami", headers={"Authorization": f"bearer {token}"}
        )
        assert r.status_code == 200

    def test_token_missing_sub_claim_returns_401(self) -> None:
        # Hand-craft a token without ``sub`` so we can exercise the
        # "non-string sub" branch of get_current_user. Use the same secret
        # and algorithm the production module would use to sign / verify.
        import jwt
        from app.core import security as core_security

        secret = core_security._secret()
        algorithm = core_security._ALGORITHM
        # Add a far-future exp so we don't accidentally trip the expiry path.
        bad = jwt.encode(
            {"role": "admin", "exp": 9_999_999_999},
            secret,
            algorithm=algorithm,
        )
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {bad}"}
        )
        assert r.status_code == 401


def _seed_user_obj(role: str = "analyst") -> _FakeUser:
    from app.core.security import hash_password
    return _FakeUser(
        user_id=_USER_ID,
        email="user@example.com",
        hashed_password=hash_password("pw"),
        role=role,
    )


# ---------------------------------------------------------------------------
# 3. Privilege-escalation pin: DB role wins over JWT role claim
# ---------------------------------------------------------------------------


class TestRoleClaimSpoofing:
    """If someone hand-crafts a JWT claiming ``role: admin`` but the DB
    record says ``analyst``, the analyst role must be the one enforced.
    Otherwise anyone who can mint a JWT can escalate to admin."""

    def setup_method(self) -> None:
        self.test_app = FastAPI()
        self.test_app.include_router(auth_router)

        @self.test_app.get("/admin-only")
        def admin_only(user: CurrentUser = Depends(require_admin)):  # noqa: B008
            return {"role": user.role}

        @self.test_app.get("/either")
        def either(user: CurrentUser = Depends(require_analyst_or_admin)):  # noqa: B008
            return {"role": user.role}

        self.client = TestClient(self.test_app)

    def teardown_method(self) -> None:
        self.test_app.dependency_overrides.clear()

    def test_jwt_claiming_admin_with_analyst_db_record_is_403(self) -> None:
        # DB record is an analyst...
        analyst_in_db = _seed_user_obj(role="analyst")
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(analyst_in_db)

        # ...but the token claims admin. The DB role wins → 403 on admin-only.
        forged = create_access_token(user_id=_USER_ID, role="admin")
        r = self.client.get(
            "/admin-only", headers={"Authorization": f"Bearer {forged}"}
        )
        assert r.status_code == 403, (
            "Token role claim escalated privilege — get_current_user must "
            "re-read role from the DB to prevent JWT forgery from granting access."
        )

    def test_db_role_used_for_response(self) -> None:
        # Same setup: token claims admin, DB says analyst.
        analyst = _seed_user_obj(role="analyst")
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(analyst)
        forged = create_access_token(user_id=_USER_ID, role="admin")

        r = self.client.get(
            "/either", headers={"Authorization": f"Bearer {forged}"}
        )
        assert r.status_code == 200
        # The CurrentUser passed to the handler reflects the DB role,
        # not the spoofed claim.
        assert r.json()["role"] == "analyst"


# ---------------------------------------------------------------------------
# 4. RFC 6750 — 401 must include WWW-Authenticate: Bearer
# ---------------------------------------------------------------------------


class TestWwwAuthenticateHeader:
    def setup_method(self) -> None:
        self.test_app, self.client = _build_protected_app()
        self.test_app.dependency_overrides[get_db] = lambda: _db_with(_seed_user_obj())

    def teardown_method(self) -> None:
        self.test_app.dependency_overrides.clear()

    def test_invalid_token_response_includes_bearer_challenge(self) -> None:
        # Per RFC 6750 §3, a 401 from a bearer-token resource must carry a
        # WWW-Authenticate header naming the Bearer scheme so the client knows
        # how to re-authenticate.
        r = self.client.get(
            "/whoami", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert r.status_code == 401
        assert r.headers.get("www-authenticate", "").lower().startswith("bearer")

    def test_expired_token_response_includes_bearer_challenge(self) -> None:
        token = create_access_token(
            user_id=_USER_ID, role="analyst", expires_minutes=-1
        )
        r = self.client.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401
        assert r.headers.get("www-authenticate", "").lower().startswith("bearer")
