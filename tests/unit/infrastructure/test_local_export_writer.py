"""No-clobber, generated-name local export behavior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from medevidence.domain import sha256_digest
from medevidence.infrastructure.local_export_writer import (
    DEFAULT_EXPORT_ROOT,
    LocalExportIntegrityError,
    LocalExportWriter,
)

KEY = "sha256:" + "a" * 64
JSON = '{"report":"synthetic"}\n'
MARKDOWN = "# Synthetic report\n"


def _write(writer: LocalExportWriter) -> tuple[str, str]:
    return writer.write(
        KEY,
        JSON,
        MARKDOWN,
        sha256_digest(JSON.encode()),
        sha256_digest(MARKDOWN.encode()),
    )


def test_generated_names_exact_bytes_and_idempotent_readback(tmp_path: Path) -> None:
    writer = LocalExportWriter._for_testing(tmp_path)
    names = _write(writer)
    assert names == LocalExportWriter.filenames(KEY)
    assert _write(writer) == names
    assert (tmp_path / names[0]).read_bytes() == JSON.encode()
    assert (tmp_path / names[1]).read_bytes() == MARKDOWN.encode()
    assert tuple(path.name for path in tmp_path.iterdir()) == names


def test_default_root_stays_under_project_local_data() -> None:
    checkout_root = Path(__file__).resolve().parents[3]
    project_root = (
        checkout_root.parents[2]
        if checkout_root.parent.name == "worktrees" and checkout_root.parent.parent.name == ".local"
        else checkout_root
    )
    assert (
        project_root / ".local" / "data" / "v1-completion-20260914" / "exports"
    ) == DEFAULT_EXPORT_ROOT


def test_foreign_existing_file_is_never_replaced(tmp_path: Path) -> None:
    writer = LocalExportWriter._for_testing(tmp_path)
    name, _ = writer.filenames(KEY)
    (tmp_path / name).write_bytes(b"foreign")
    with pytest.raises(LocalExportIntegrityError, match="bytes differ"):
        _write(writer)
    assert (tmp_path / name).read_bytes() == b"foreign"


def test_committed_read_never_creates_or_repairs_files(tmp_path: Path) -> None:
    absent = tmp_path / "absent"
    writer = LocalExportWriter._for_testing(absent)
    with pytest.raises(LocalExportIntegrityError):
        writer.read_verified(KEY, "json", sha256_digest(JSON.encode()))
    assert not absent.exists()

    writer = LocalExportWriter._for_testing(tmp_path)
    names = _write(writer)
    assert writer.read_verified(KEY, "json", sha256_digest(JSON.encode())) == JSON.encode()
    (tmp_path / names[0]).write_bytes(b"foreign")
    with pytest.raises(LocalExportIntegrityError):
        writer.read_verified(KEY, "json", sha256_digest(JSON.encode()))
    assert (tmp_path / names[0]).read_bytes() == b"foreign"


def test_relative_root_and_symlinked_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        LocalExportWriter._for_testing(Path("relative"))
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        pytest.skip("local test user cannot create symlinks")
    writer = LocalExportWriter._for_testing(link)
    with pytest.raises(LocalExportIntegrityError, match="symlink"):
        _write(writer)
    assert list(target.iterdir()) == []
