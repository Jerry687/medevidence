"""Explicit, redacted configuration for the local single-user application."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from medevidence.persistence.config import PersistenceSettings


class LocalRuntimeConfigurationError(ValueError):
    """Configuration is absent or outside the local runtime boundary."""


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if not value or value != value.strip():
        raise LocalRuntimeConfigurationError(f"{name} must be explicitly configured")
    return value


def _absolute_path(value: str, name: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise LocalRuntimeConfigurationError(f"{name} must be an absolute bounded path")
    return path


@dataclass(frozen=True, slots=True)
class LocalRuntimeSettings:
    """No filesystem, database, model, or source execution during validation."""

    database: PersistenceSettings
    snapshot_root: Path
    code_revision: str
    qwen_endpoint: str
    qwen_api_key: str = field(repr=False)
    generation_api_key: str = field(repr=False)
    cadec_archive: Path | None = None
    cadec_manifest: Path | None = None

    def __post_init__(self) -> None:
        if type(self.database) is not PersistenceSettings:
            raise LocalRuntimeConfigurationError("database settings must be explicit")
        parsed = make_url(self.database.database_url)
        if parsed.host not in ("localhost", "127.0.0.1", "::1") or parsed.query:
            raise LocalRuntimeConfigurationError("local runtime requires loopback PostgreSQL")
        _absolute_path(str(self.snapshot_root), "MEDEV_SNAPSHOT_ROOT")
        if re.fullmatch(r"[0-9a-f]{40}", self.code_revision) is None:
            raise LocalRuntimeConfigurationError("MEDEV_CODE_REVISION must be an exact Git ID")
        try:
            url = urlsplit(self.qwen_endpoint)
            valid = (
                url.scheme == "https"
                and re.fullmatch(
                    r"[a-z0-9-]{5,64}\.cn-beijing\.maas\.aliyuncs\.com", url.hostname or ""
                )
                and url.path == "/compatible-mode/v1/chat/completions"
                and url.port is None
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            raise LocalRuntimeConfigurationError("Qwen endpoint must be the official workspace API")
        for key in (self.qwen_api_key, self.generation_api_key):
            if (
                type(key) is not str
                or not 1 <= len(key) <= 512
                or not key.isascii()
                or any(not 33 <= ord(c) <= 126 for c in key)
            ):
                raise LocalRuntimeConfigurationError("model credential is invalid")
        if (self.cadec_archive is None) != (self.cadec_manifest is None):
            raise LocalRuntimeConfigurationError(
                "CADEC archive and manifest must be configured together"
            )
        for path in (self.cadec_archive, self.cadec_manifest):
            if path is not None:
                _absolute_path(str(path), "CADEC asset")

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> LocalRuntimeSettings:
        """Read secrets from the server process only; never read a credential CSV."""
        source = os.environ if values is None else values
        archive = source.get("MEDEV_CADEC_ARCHIVE")
        manifest = source.get("MEDEV_CADEC_MANIFEST")
        return cls(
            database=PersistenceSettings(_required(source, "MEDEV_DATABASE_URL")),
            snapshot_root=_absolute_path(
                _required(source, "MEDEV_SNAPSHOT_ROOT"), "MEDEV_SNAPSHOT_ROOT"
            ),
            code_revision=_required(source, "MEDEV_CODE_REVISION"),
            qwen_endpoint=_required(source, "MEDEV_QWEN_ENDPOINT"),
            qwen_api_key=_required(source, "DASHSCOPE_API_KEY"),
            generation_api_key=_required(source, "DEEPSEEK_API_KEY"),
            cadec_archive=_absolute_path(archive, "MEDEV_CADEC_ARCHIVE") if archive else None,
            cadec_manifest=_absolute_path(manifest, "MEDEV_CADEC_MANIFEST") if manifest else None,
        )
