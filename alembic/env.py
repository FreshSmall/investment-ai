"""Alembic environment: URL built from Settings (.env), models imported for autogenerate."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.db.engine import build_database_url

# Import all models so target_metadata sees every table.
from app.db import models  # noqa: F401
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# NOTE: the URL is built in code, never written back to alembic.ini — configparser
# rejects '%' sequences that appear when the DB password contains URL-escaped chars.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=build_database_url(get_settings()).render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(build_database_url(get_settings()), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
