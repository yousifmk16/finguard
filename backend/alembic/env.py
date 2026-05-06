from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
import app.db.models.billing_event  # noqa: F401 — registers model with Base.metadata
import app.db.models.anomaly  # noqa: F401 — registers model with Base.metadata
import app.db.models.alert  # noqa: F401 — registers model with Base.metadata
import app.db.models.audit_log  # noqa: F401 — registers model with Base.metadata

config = context.config
fileConfig(config.config_file_name)

# Pull DATABASE_URL from the environment — never hard-coded.
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Copy backend/.env.example to backend/.env and set it, "
        "or export it in your shell."
    )
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
