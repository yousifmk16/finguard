import uuid

import pytest
from app.api.auth import get_current_user
from app.core.idempotency import store as idempotency_store
from app.main import app
from app.schemas.auth import CurrentUser

_DEFAULT_TEST_ADMIN = CurrentUser(
    user_id=uuid.UUID("aaaaaaaa-0000-0000-0000-00000000ffff"),
    email="test-admin@example.com",
    role="admin",
)


@pytest.fixture(autouse=True)
def reset_idempotency_store() -> None:
    """Clear the in-memory idempotency store before each test."""
    idempotency_store._seen.clear()


@pytest.fixture(autouse=True)
def _default_admin_auth():
    """SEC-03: protected endpoints now require auth. To keep the existing
    test surface focused on business logic, default every test to a
    pre-resolved admin identity. Tests that exercise auth/RBAC behavior
    explicitly clear or replace this override.
    """
    app.dependency_overrides[get_current_user] = lambda: _DEFAULT_TEST_ADMIN
    yield
    app.dependency_overrides.pop(get_current_user, None)
