"""Startup identifies actual source bytes and forbids run identity substitution."""

from pathlib import Path

import pytest

from medevidence.infrastructure import local_runtime_identity as identity
from medevidence.ingestion.snapshots import SnapshotIntegrityError, SnapshotStore


def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout"
    (root / "src").mkdir(parents=True)
    (root / "alembic").mkdir()
    (root / "src" / "module.py").write_text("VALUE = 1\n")
    for name in ("pyproject.toml", "uv.lock", "alembic.ini"):
        (root / name).write_text("fixture\n")
    monkeypatch.setattr(identity, "_revision", lambda _: "a" * 40)
    return root


def test_wrong_head_and_uncommitted_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = checkout(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="actual checkout HEAD"):
        identity.capture_runtime_identity("b" * 40, root=root)
    first = identity.capture_runtime_identity("a" * 40, root=root)
    (root / "src" / "module.py").write_text("VALUE = 2\n")
    second = identity.capture_runtime_identity("a" * 40, root=root)
    assert first.revision == second.revision
    assert first.manifest_hash != second.manifest_hash


def test_existing_run_cannot_silently_switch_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = checkout(tmp_path, monkeypatch)
    store = SnapshotStore(tmp_path / "snapshots")
    first = identity.capture_runtime_identity("a" * 40, root=root)
    identity.bind_runtime_implementation(store, first, run_id="run:synthetic")
    identity.bind_runtime_implementation(store, first, run_id="run:synthetic")
    (root / "src" / "module.py").write_text("VALUE = 2\n")
    changed = identity.capture_runtime_identity("a" * 40, root=root)
    with pytest.raises(SnapshotIntegrityError):
        identity.bind_runtime_implementation(store, changed, run_id="run:synthetic")
