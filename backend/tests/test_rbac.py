"""SEC-02: tests for the RBAC dependencies in app.api.rbac."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from app.api.auth import router as auth_router
from app.api.rbac import (
    require_admin,
    require_analyst_or_admin,
    require_any_role,
    require_role,
)
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.schemas.auth import CurrentUser
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

_USER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")


@dataclass
class _FakeUser:
    user_id: uuid.UUID
    email: str
    hashed_password: str
    role: str
    is_active: bool = True


def _seed_user(role: str) -> _FakeUser:
    return _FakeUser(
        user_id=_USER_ID,
        email="user@example.com",
        hashed_password=hash_password("pw"),
        role=role,
    )


def _db_with(scalar_value: object) -> MagicMock:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = scalar_value
    return db


def _build_app() -> tuple[FastAPI, TestClient]:
    """Mount auth + four probe routes guarded by different RBAC deps."""
    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/admin-only")
    def admin_only(user: CurrentUser = Depends(require_admin)):  # noqa: B008
        return {"role": user.role}

    @app.get("/either")
    def either(
        user: CurrentUser = Depends(require_analyst_or_admin),  # noqa: B008
    ):
        return {"role": user.role}

    @app.get("/single-analyst")
    def single_analyst(
        user: CurrentUser = Depends(require_role("analyst")),  # noqa: B008
    ):
        return {"role": user.role}

    return app, TestClient(app)


def _auth(role: str) -> dict[str, str]:
    token = create_access_token(user_id=_USER_ID, role=role)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# factory contract
# ---------------------------------------------------------------------------


class TestFactoryContract:
    def test_require_any_role_rejects_empty(self):
        with pytest.raises(ValueError):
            require_any_role()

    def test_require_role_is_thin_wrapper(self):
        dep = require_role("admin")
        assert callable(dep)


# ---------------------------------------------------------------------------
# allow paths
# ---------------------------------------------------------------------------


class TestAllowed:
    def setup_method(self):
        self.app, self.client = _build_app()

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_admin_passes_admin_only(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("admin")
        )
        r = self.client.get("/admin-only", headers=_auth("admin"))
        assert r.status_code == 200
        assert r.json() == {"role": "admin"}

    def test_admin_passes_either(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("admin")
        )
        r = self.client.get("/either", headers=_auth("admin"))
        assert r.status_code == 200

    def test_analyst_passes_either(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("analyst")
        )
        r = self.client.get("/either", headers=_auth("analyst"))
        assert r.status_code == 200
        assert r.json() == {"role": "analyst"}

    def test_analyst_passes_single_analyst(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("analyst")
        )
        r = self.client.get("/single-analyst", headers=_auth("analyst"))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# deny paths (403)
# ---------------------------------------------------------------------------


class TestForbidden:
    def setup_method(self):
        self.app, self.client = _build_app()

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_analyst_blocked_from_admin_only(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("analyst")
        )
        r = self.client.get("/admin-only", headers=_auth("analyst"))
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden: requires role admin"

    def test_admin_blocked_from_single_analyst(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("admin")
        )
        r = self.client.get("/single-analyst", headers=_auth("admin"))
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden: requires role analyst"

    def test_multi_role_error_message_lists_all_sorted(self):
        # The CurrentUser schema rejects unknown roles at the auth boundary,
        # so an out-of-set role can't reach the checker via HTTP. Exercise
        # the closure directly with a model_construct'd user to verify the
        # multi-role message format and alphabetical ordering.
        dep = require_any_role("analyst", "admin")
        rogue = CurrentUser.model_construct(
            user_id=_USER_ID, email="x@example.com", role="auditor"
        )
        with pytest.raises(HTTPException) as exc_info:
            dep(user=rogue)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "forbidden: requires role admin or analyst"


# ---------------------------------------------------------------------------
# 401 fallthrough — RBAC must defer auth failures to get_current_user
# ---------------------------------------------------------------------------


class TestAuthFallthrough:
    def setup_method(self):
        self.app, self.client = _build_app()

    def teardown_method(self):
        self.app.dependency_overrides.clear()

    def test_missing_token_returns_401_not_403(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("admin")
        )
        r = self.client.get("/admin-only")
        assert r.status_code == 401

    def test_expired_token_returns_401(self):
        self.app.dependency_overrides[get_db] = lambda: _db_with(
            _seed_user("admin")
        )
        token = create_access_token(
            user_id=_USER_ID, role="admin", expires_minutes=-1
        )
        r = self.client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 401

    def test_inactive_user_returns_401(self):
        user = _seed_user("admin")
        user.is_active = False
        self.app.dependency_overrides[get_db] = lambda: _db_with(user)
        r = self.client.get("/admin-only", headers=_auth("admin"))
        assert r.status_code == 401
