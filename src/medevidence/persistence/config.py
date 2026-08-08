"""Validated synchronous PostgreSQL configuration with safe redaction."""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

DATABASE_URL_ENV = "MEDEV_DATABASE_URL"
EXPECTED_DRIVER = "postgresql+psycopg"


class PersistenceConfigurationError(ValueError):
    """The database configuration is missing or outside the frozen boundary."""


def redact_database_url(value: str | URL) -> str:
    """Render a database URL without its password or query values."""

    try:
        url = make_url(value) if isinstance(value, str) else value
        parsed_port = url.port
    except (ArgumentError, ValueError):
        return "<invalid-database-url>"
    host = url.host or ""
    port = f":{parsed_port}" if parsed_port is not None else ""
    database = f"/{url.database}" if url.database else ""
    return f"{url.drivername}://{host}{port}{database}"


@dataclass(frozen=True, slots=True, repr=False)
class PersistenceSettings:
    """Explicit synchronous PostgreSQL settings loaded without side effects."""

    database_url: str

    def __post_init__(self) -> None:
        try:
            parsed = make_url(self.database_url)
            _parsed_port = parsed.port
        except (ArgumentError, ValueError) as error:
            raise PersistenceConfigurationError("database URL is invalid") from error
        if parsed.drivername != EXPECTED_DRIVER:
            raise PersistenceConfigurationError(f"database URL must use {EXPECTED_DRIVER}")
        if not parsed.host or not parsed.database or not parsed.username:
            raise PersistenceConfigurationError(
                "database URL requires host, database, and username"
            )

    @classmethod
    def from_env(cls) -> PersistenceSettings:
        """Load the one approved environment variable."""

        value = os.environ.get(DATABASE_URL_ENV)
        if value is None or not value.strip():
            raise PersistenceConfigurationError(f"{DATABASE_URL_ENV} must be set explicitly")
        return cls(database_url=value)

    @property
    def redacted_database_url(self) -> str:
        """Return a diagnostic-safe database location."""

        return redact_database_url(self.database_url)

    def __repr__(self) -> str:
        return f"PersistenceSettings(database_url={self.redacted_database_url!r})"

    def __str__(self) -> str:
        return self.__repr__()
