"""Synchronous SQLAlchemy engine ownership for persistence internals."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from .config import PersistenceSettings


def _create_engine(settings: PersistenceSettings) -> Engine:
    """Create the bounded synchronous engine without connecting eagerly."""

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
    )
