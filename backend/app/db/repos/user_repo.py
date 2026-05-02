"""SEC-01: read-side repository for the ``users`` table.

Login needs a single lookup-by-email; user creation is handled
out-of-band (seed script / admin tooling) so the surface stays narrow.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import UserRow


class UserRepository:
    def get_by_email(self, session: Session, email: str) -> UserRow | None:
        stmt = select(UserRow).where(UserRow.email == email.lower())
        return session.execute(stmt).scalar_one_or_none()

    def get_by_id(self, session: Session, user_id: uuid.UUID) -> UserRow | None:
        return session.execute(
            select(UserRow).where(UserRow.user_id == user_id)
        ).scalar_one_or_none()
