import pytest
from app.core.idempotency import store as idempotency_store


@pytest.fixture(autouse=True)
def reset_idempotency_store() -> None:
    """Clear the in-memory idempotency store before each test."""
    idempotency_store._seen.clear()
