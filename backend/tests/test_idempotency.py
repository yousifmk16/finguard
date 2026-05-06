"""
TST-01: Unit tests for app.core.idempotency.

The in-memory idempotency store is the fast pre-check used by ING-03 to
avoid hitting the database for repeat ``event_id`` submissions. Tests
target the behavior callers depend on:
  * exact-match dedup (no false positives across distinct UUIDs)
  * registration is sticky across calls
  * eviction policy is FIFO and capped at the configured maximum
"""

from __future__ import annotations

import uuid

from app.core import idempotency
from app.core.idempotency import IdempotencyStore


class TestIdempotencyStore:
    def test_unseen_id_is_not_duplicate(self) -> None:
        store = IdempotencyStore()
        assert store.is_duplicate(uuid.uuid4()) is False

    def test_registered_id_is_duplicate(self) -> None:
        store = IdempotencyStore()
        eid = uuid.uuid4()
        store.register(eid)
        assert store.is_duplicate(eid) is True

    def test_distinct_ids_independent(self) -> None:
        store = IdempotencyStore()
        a, b = uuid.uuid4(), uuid.uuid4()
        store.register(a)
        assert store.is_duplicate(a) is True
        assert store.is_duplicate(b) is False

    def test_register_is_idempotent(self) -> None:
        # Calling register twice with the same ID must not break dedup.
        store = IdempotencyStore()
        eid = uuid.uuid4()
        store.register(eid)
        store.register(eid)
        assert store.is_duplicate(eid) is True

    def test_eviction_at_max_size(self) -> None:
        # Shrink the cap for the test so we can fill the store cheaply.
        original = idempotency._MAX_SIZE
        idempotency._MAX_SIZE = 3
        try:
            store = IdempotencyStore()
            ids = [uuid.uuid4() for _ in range(4)]
            for eid in ids:
                store.register(eid)
            # Oldest must have been evicted; newest three remain.
            assert store.is_duplicate(ids[0]) is False
            for eid in ids[1:]:
                assert store.is_duplicate(eid) is True
        finally:
            idempotency._MAX_SIZE = original

    def test_eviction_is_fifo(self) -> None:
        original = idempotency._MAX_SIZE
        idempotency._MAX_SIZE = 2
        try:
            store = IdempotencyStore()
            a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            store.register(a)
            store.register(b)
            store.register(c)  # evicts a
            assert store.is_duplicate(a) is False
            assert store.is_duplicate(b) is True
            assert store.is_duplicate(c) is True
        finally:
            idempotency._MAX_SIZE = original

    def test_module_singleton_exists(self) -> None:
        # The module exports a shared instance — used directly by ingestion.py.
        assert isinstance(idempotency.store, IdempotencyStore)
