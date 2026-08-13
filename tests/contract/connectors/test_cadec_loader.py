"""Offline connector contract tests for the exact-path CADEC loader."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import medevidence.connectors.cadec.loader as loader_module
from medevidence.connectors.cadec import CadecLoadError, CadecLoadErrorCode, load_cadec_archive


def test_import_has_no_io_and_loader_requires_two_explicit_paths() -> None:
    signature = inspect.signature(load_cadec_archive)

    assert tuple(signature.parameters) == ("archive_path", "manifest_path")
    assert all(
        parameter.default is inspect.Parameter.empty for parameter in signature.parameters.values()
    )


def test_relative_paths_fail_before_any_asset_access() -> None:
    with pytest.raises(CadecLoadError) as raised:
        load_cadec_archive(Path("CADEC.v2.zip"), Path("manifest.json"))

    assert raised.value.code is CadecLoadErrorCode.INPUT_PATH


def test_loader_uses_only_standard_library_and_domain_contracts() -> None:
    source = inspect.getsource(loader_module)

    assert "httpx" not in source
    assert "requests" not in source
    assert "extractall" not in source
    assert "extract(" not in source
    assert "medevidence.ingestion" not in source
    assert "medevidence.persistence" not in source
    assert "ZipFile(archive_path" not in source
    assert "read_text(" not in source
    assert 'path.open("rb")' in source
    assert "os.fstat(stream.fileno())" in source
    assert "io.BytesIO(archive_bytes)" in source
