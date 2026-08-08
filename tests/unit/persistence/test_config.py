"""Unit tests for fail-closed persistence configuration and redaction."""

from __future__ import annotations

import pytest

from medevidence.persistence.config import (
    DATABASE_URL_ENV,
    PersistenceConfigurationError,
    PersistenceSettings,
    redact_database_url,
)


def test_settings_require_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    with pytest.raises(PersistenceConfigurationError, match="must be set explicitly"):
        PersistenceSettings.from_env()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:secret@localhost/db",
        "postgresql+asyncpg://user:secret@localhost/db",
        "sqlite:///tmp.db",
        "not a URL",
    ],
)
def test_settings_reject_non_psycopg_or_invalid_urls(database_url: str) -> None:
    with pytest.raises(PersistenceConfigurationError):
        PersistenceSettings(database_url)


def test_settings_and_url_redaction_never_expose_credentials() -> None:
    raw = (
        "postgresql+psycopg://research%40owner:s3cr%40t@127.0.0.1:5432/medevidence"
        "?sslmode=disable&token=query-secret"
    )
    settings = PersistenceSettings(raw)

    rendered = f"{settings!r} {settings} {settings.redacted_database_url}"

    assert "research" not in rendered
    assert "owner" not in rendered
    assert "s3cr" not in rendered
    assert "sslmode" not in rendered
    assert "query-secret" not in rendered
    assert "token" not in rendered
    assert "@" not in settings.redacted_database_url
    assert settings.redacted_database_url == ("postgresql+psycopg://127.0.0.1:5432/medevidence")
    assert redact_database_url("not a URL") == "<invalid-database-url>"


def test_configuration_errors_never_echo_url_credentials() -> None:
    raw = "sqlite://encoded%40user:encoded%40password@localhost/db?token=query-secret"

    with pytest.raises(PersistenceConfigurationError) as captured:
        PersistenceSettings(raw)

    rendered = str(captured.value)
    assert "encoded" not in rendered
    assert "query-secret" not in rendered
    assert raw not in rendered


def test_invalid_port_is_translated_and_redacted_at_both_boundaries() -> None:
    raw = (
        "postgresql+psycopg://encoded%40user:encoded%40password@"
        "localhost:notaport/medevidence?token=query-secret"
    )

    with pytest.raises(PersistenceConfigurationError, match="database URL is invalid") as captured:
        PersistenceSettings(raw)

    rendered = str(captured.value)
    assert "encoded" not in rendered
    assert "query-secret" not in rendered
    assert raw not in rendered
    assert redact_database_url(raw) == "<invalid-database-url>"


def test_from_env_preserves_exact_runtime_url(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "postgresql+psycopg://user:password@localhost:5432/medevidence"
    monkeypatch.setenv(DATABASE_URL_ENV, raw)

    settings = PersistenceSettings.from_env()

    assert settings.database_url == raw
