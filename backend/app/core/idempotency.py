from __future__ import annotations

import uuid
from collections import OrderedDict

# Evict oldest entries beyond this cap to prevent unbounded memory growth.
_MAX_SIZE = 100_000


class IdempotencyStore:
    """Track seen event IDs to prevent duplicate processing.

    In-process only — valid for single-process deployments. In a multi-worker
    setup (Gunicorn, multiple uvicorn workers) each worker has its own store,
    so cross-worker duplicates are only caught by the DB unique constraint
    (the IntegrityError path in ingestion.py). Replace with a Redis SET for
    multi-worker correctness (ING-03).

    The store is capped at _MAX_SIZE entries; the oldest entry is evicted
    when the cap is reached.
    """

    def __init__(self) -> None:
        self._seen: OrderedDict[uuid.UUID, None] = OrderedDict()

    def is_duplicate(self, event_id: uuid.UUID) -> bool:
        return event_id in self._seen

    def register(self, event_id: uuid.UUID) -> None:
        if len(self._seen) >= _MAX_SIZE:
            self._seen.popitem(last=False)  # evict oldest
        self._seen[event_id] = None


# Module-level singleton shared across requests within a single process.
store = IdempotencyStore()
