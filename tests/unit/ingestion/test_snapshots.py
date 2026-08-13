"""Unit tests for immutable content-addressed PubMed snapshots."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from medevidence.ingestion.snapshots import (
    COMMITTED_BYTE_CAPACITY,
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    RAW_RUN_BYTE_CAPACITY,
    ROOT_LOCK_FILENAME,
    TEMPORARY_FILE_PEAK_CAPACITY,
    SnapshotBusyError,
    SnapshotCapacityError,
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)


def store(root: Path, *, free: int = INITIAL_FREE_SPACE_FLOOR_BYTES) -> SnapshotStore:
    return SnapshotStore(root, free_bytes=lambda _: free)


def test_exact_raw_bytes_are_immutable_and_reused(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    with snapshots.writer():
        first = snapshots.store_raw_body(b"<xml/>")
        second = snapshots.store_raw_body(b"<xml/>")

    assert first.artifact_id == (
        "sha256:6eb820e0f9762c611c2a77189f686afeca64dfb212e023017e0346e7ab826c39"
    )
    assert first.path == (
        snapshots.root
        / "pubmed"
        / "sha256"
        / "6e"
        / "6eb820e0f9762c611c2a77189f686afeca64dfb212e023017e0346e7ab826c39.bin"
    )
    assert first.path.read_bytes() == b"<xml/>"
    assert not first.reused_existing
    assert second.reused_existing
    assert (snapshots.root / ROOT_LOCK_FILENAME).stat().st_size == 0


def test_existing_corruption_is_never_overwritten(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    with snapshots.writer():
        written = snapshots.store_raw_body(b"<xml/>")
    written.path.write_bytes(b"damage")

    with snapshots.writer(), pytest.raises(SnapshotIntegrityError):
        snapshots.store_raw_body(b"<xml/>")
    assert written.path.read_bytes() == b"damage"


def test_faers_exact_raw_bytes_are_immutable_and_counted(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    body = b'{"results":[]}'
    with snapshots.writer():
        first = snapshots.store_faers_response(body)
        second = snapshots.store_faers_response(body)
    assert first.path.relative_to(snapshots.root).as_posix().startswith("faers/raw/sha256/")
    assert first.path.read_bytes() == body
    assert not first.reused_existing
    assert second.reused_existing
    assert snapshots._ledger().raw_bytes == len(body)


def test_faers_verification_rejects_corruption(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    with snapshots.writer():
        published = snapshots.store_faers_response(b"synthetic")
    published.path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotIntegrityError):
        snapshots.verify_faers(published.artifact_id)


def test_capacity_checks_are_injected_and_exact(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    with pytest.raises(SnapshotCapacityError, match="13 GiB"):
        store(root, free=INITIAL_FREE_SPACE_FLOOR_BYTES - 1).initialize()

    snapshots = SnapshotStore(
        root,
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
        committed_bytes=lambda: COMMITTED_BYTE_CAPACITY,
    )
    with snapshots.writer(), pytest.raises(SnapshotCapacityError, match="ceiling"):
        snapshots.store_raw_body(b"x")

    file_limited = SnapshotStore(
        tmp_path / "file-limited",
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
        committed_files=lambda: 1_214,
    )
    with file_limited.writer(), pytest.raises(SnapshotCapacityError, match="file"):
        file_limited.store_raw_body(b"x")

    raw_limited = SnapshotStore(
        tmp_path / "raw-limited",
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
        raw_bytes=lambda: RAW_RUN_BYTE_CAPACITY - 1,
    )
    with raw_limited.writer(), pytest.raises(SnapshotCapacityError, match="run-raw"):
        raw_limited.store_raw_body(b"xx")


def test_per_response_cap_is_enforced_without_large_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.ingestion.snapshots as snapshots_module

    monkeypatch.setattr(snapshots_module, "RAW_RESPONSE_BYTE_CAPACITY", 1)
    snapshots = store(tmp_path / "snapshots")
    with snapshots.writer(), pytest.raises(SnapshotCapacityError, match="5,242,880"):
        snapshots.store_raw_body(b"xx")


def test_initial_floor_applies_only_to_first_root_admission(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    store(root).initialize()

    existing = store(root, free=1)
    existing.initialize()

    assert (root / ROOT_LOCK_FILENAME).is_file()
    with existing.writer(), pytest.raises(SnapshotCapacityError, match="1 GiB"):
        existing.store_raw_body(b"x")


def test_default_ledger_counts_prior_committed_raw_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.ingestion.snapshots as snapshots_module

    root = tmp_path / "snapshots"
    first = store(root)
    with first.writer():
        first.store_raw_body(b"first")

    monkeypatch.setattr(snapshots_module, "RAW_RUN_BYTE_CAPACITY", 5)
    second = store(root)
    with second.writer(), pytest.raises(SnapshotCapacityError, match="run-raw"):
        second.store_raw_body(b"x")


def test_all_publication_paths_require_writer_lock(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()

    with pytest.raises(SnapshotBusyError):
        snapshots.store_raw_body(b"x")
    with pytest.raises(SnapshotBusyError):
        snapshots.publish_bytes("journal/record.json", b"{}", artifact_class="journal")


def test_frozen_file_peak_boundary_allows_last_persistent_slot(tmp_path: Path) -> None:
    snapshots = SnapshotStore(
        tmp_path / "snapshots",
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
        committed_files=lambda: TEMPORARY_FILE_PEAK_CAPACITY - 3,
    )
    with snapshots.writer():
        snapshots.store_raw_body(b"x")


def test_lock_and_temporary_file_ceilings_are_independently_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.ingestion.snapshots as snapshots_module

    monkeypatch.setattr(snapshots_module, "PERSISTENT_WITH_LOCK_CAPACITY", 1)
    lock_limited = store(tmp_path / "lock-limited")
    with lock_limited.writer(), pytest.raises(SnapshotCapacityError, match="with-lock"):
        lock_limited.store_raw_body(b"x")

    monkeypatch.setattr(snapshots_module, "PERSISTENT_WITH_LOCK_CAPACITY", 100)
    monkeypatch.setattr(snapshots_module, "TEMPORARY_FILE_PEAK_CAPACITY", 2)
    temp_limited = store(tmp_path / "temp-limited")
    with temp_limited.writer(), pytest.raises(SnapshotCapacityError, match="temp"):
        temp_limited.store_raw_body(b"x")

    monkeypatch.setattr(snapshots_module, "TEMPORARY_FILE_PEAK_CAPACITY", 100)
    monkeypatch.setattr(snapshots_module, "TEMPORARY_PEAK_BYTE_CAPACITY", 1)
    byte_peak_limited = store(tmp_path / "byte-peak-limited")
    with byte_peak_limited.writer(), pytest.raises(SnapshotCapacityError, match="temporary-byte"):
        byte_peak_limited.store_raw_body(b"x")


def test_stale_incomplete_files_count_toward_temporary_peaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.ingestion.snapshots as snapshots_module

    file_root = tmp_path / "file-root"
    file_limited = store(file_root)
    file_limited.initialize()
    (file_root / ".m1a-incomplete-retained.tmp").write_bytes(b"x")
    monkeypatch.setattr(snapshots_module, "TEMPORARY_FILE_PEAK_CAPACITY", 3)
    with file_limited.writer(), pytest.raises(SnapshotCapacityError, match="file peak"):
        file_limited.store_raw_body(b"x")

    monkeypatch.setattr(snapshots_module, "TEMPORARY_FILE_PEAK_CAPACITY", 100)
    monkeypatch.setattr(snapshots_module, "TEMPORARY_PEAK_BYTE_CAPACITY", 3)
    byte_root = tmp_path / "byte-root"
    byte_limited = store(byte_root)
    byte_limited.initialize()
    (byte_root / ".m1a-incomplete-retained.tmp").write_bytes(b"xx")
    with byte_limited.writer(), pytest.raises(SnapshotCapacityError, match="temporary-byte"):
        byte_limited.store_raw_body(b"x")


def test_one_writer_per_root_is_nonblocking(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    first = store(root)
    second = store(root)
    with first.writer(), pytest.raises(SnapshotBusyError), second.writer():
        pass


def test_recovery_observes_only_exact_directory_and_retains_prefix(
    tmp_path: Path,
) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    exact = snapshots.root / "journal"
    exact.mkdir()
    incomplete = exact / ".m1a-incomplete-retained.tmp"
    incomplete.write_bytes(b"incomplete prefix")

    observation = snapshots.observe_recovery(exact)

    assert observation.incomplete_files == (incomplete,)
    assert incomplete.read_bytes() == b"incomplete prefix"
    with pytest.raises(SnapshotContainmentError):
        snapshots.observe_recovery(tmp_path)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_symlink_or_reparse_containment_fails_closed(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = snapshots.root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")

    with pytest.raises(SnapshotContainmentError):
        snapshots.observe_recovery(link)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_lock_leaf_symlink_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    root.mkdir()
    outside = tmp_path / "outside.lock"
    outside.write_bytes(b"")
    lock = root / ROOT_LOCK_FILENAME
    try:
        lock.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")

    with pytest.raises(SnapshotContainmentError):
        store(root).initialize()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_recovery_leaf_symlink_fails_closed(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    journal = snapshots.root / "journal"
    journal.mkdir()
    outside = tmp_path / "outside.tmp"
    outside.write_bytes(b"prefix")
    leaf = journal / ".m1a-incomplete-linked.tmp"
    try:
        leaf.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")

    with pytest.raises(SnapshotContainmentError):
        snapshots.observe_recovery(journal)
