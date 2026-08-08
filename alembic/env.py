"""Offline-safe Alembic environment for the frozen persistence schema."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from medevidence.persistence.config import PersistenceSettings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    return PersistenceSettings.from_env().database_url


def run_migrations_offline() -> None:
    """Render migrations without creating a database connection."""

    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=None,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the explicitly configured PostgreSQL database."""

    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, version_table_schema=None)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
