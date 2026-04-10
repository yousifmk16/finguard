from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL: str | None = os.getenv("DATABASE_URL")

if DATABASE_URL:
    _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    _SessionLocal: sessionmaker[Session] | None = sessionmaker(
        bind=_engine, autocommit=False, autoflush=False
    )
else:
    _engine = None
    _SessionLocal = None


def get_db() -> Generator[Session | None, None, None]:
    """FastAPI dependency that yields a DB session.

    Yields ``None`` when DATABASE_URL is not configured (e.g. unit-test
    environment without a live Postgres instance).  Callers must guard
    against ``None`` before performing DB operations.
    """
    if _SessionLocal is None:
        yield None
        return
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
