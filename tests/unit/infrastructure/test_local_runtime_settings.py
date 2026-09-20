"""Credential and local-boundary failures are safe before runtime construction."""

from pathlib import Path

import pytest

from medevidence.infrastructure.local_runtime_settings import (
    LocalRuntimeConfigurationError,
    LocalRuntimeSettings,
)


def environment(tmp_path: Path) -> dict[str, str]:
    return {
        "MEDEV_DATABASE_URL": "postgresql+psycopg://offline:db-secret@127.0.0.1/test",
        "MEDEV_SNAPSHOT_ROOT": str(tmp_path / "snapshots"),
        "MEDEV_CODE_REVISION": "a" * 40,
        "MEDEV_QWEN_ENDPOINT": "https://synthetic.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "DASHSCOPE_API_KEY": "synthetic-qwen-secret",
        "DEEPSEEK_API_KEY": "synthetic-generation-secret",
    }


def test_configuration_does_not_create_files_or_expose_credentials(tmp_path: Path) -> None:
    values = environment(tmp_path)
    settings = LocalRuntimeSettings.from_env(values)
    assert not settings.snapshot_root.exists()
    assert settings.cadec_archive is None
    for secret in ("db-secret", "synthetic-qwen-secret", "synthetic-generation-secret"):
        assert secret not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("MEDEV_DATABASE_URL", "postgresql+psycopg://offline:secret@remote.example/test"),
        ("MEDEV_QWEN_ENDPOINT", "https://attacker.example/compatible-mode/v1/chat/completions"),
        (
            "MEDEV_QWEN_ENDPOINT",
            "https://synthetic.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions?secret=yes",
        ),
        (
            "MEDEV_QWEN_ENDPOINT",
            "https://user:secret@synthetic.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        ),
        ("MEDEV_SNAPSHOT_ROOT", "relative"),
        ("MEDEV_CODE_REVISION", "main"),
        ("DASHSCOPE_API_KEY", "bad\nsecret"),
        ("DEEPSEEK_API_KEY", ""),
        ("MEDEV_CADEC_ARCHIVE", "relative.zip"),
    ),
)
def test_unsafe_configuration_fails_without_value_echo(
    tmp_path: Path, name: str, value: str
) -> None:
    values = environment(tmp_path)
    values[name] = value
    with pytest.raises(ValueError) as error:
        LocalRuntimeSettings.from_env(values)
    assert "secret" not in str(error.value)


def test_cadec_requires_both_assets(tmp_path: Path) -> None:
    values = environment(tmp_path)
    values["MEDEV_CADEC_ARCHIVE"] = str(tmp_path / "approved.zip")
    with pytest.raises(LocalRuntimeConfigurationError, match="together"):
        LocalRuntimeSettings.from_env(values)
