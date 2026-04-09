from __future__ import annotations

import uuid


class IdempotencyStore:
    """Track seen event IDs to prevent duplicate processing.

    Current implementation is in-process memory — intentionally simple until
    DB-01 lands.  Replace ``_seen`` with a Redis SET or a DB unique-index
    lookup at that point; the interface stays the same.
    """

    def __init__(self) -> None:
        self._seen: set[uuid.UUID] = set()

    def is_duplicate(self, event_id: uuid.UUID) -> bool:
        return event_id in self._seen

    def register(self, event_id: uuid.UUID) -> None:
        self._seen.add(event_id)


# Module-level singleton shared across requests within a single process.
store = IdempotencyStore()
