"""Unit tests for immutable content-addressed PubMed snapshots."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from medevidence.composition import _AcquisitionAdapter
from medevidence.ingestion.snapshots import (
    COMMITTED_BYTE_CAPACITY,
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    PERSISTENT_FILE_CAPACITY,
    RAW_RUN_BYTE_CAPACITY,
    ROOT_LOCK_FILENAME,
    TEMPORARY_FILE_PEAK_CAPACITY,
    SnapshotBusyError,
    SnapshotCapacityError,
    SnapshotContainmentError,
    SnapshotIntegrityError,
    SnapshotStore,
)
from medevidence.tools.ports import PubMedSearchProgressRecord


def store(root: Path, *, free: int = INITIAL_FREE_SPACE_FLOOR_BYTES) -> SnapshotStore:
    return SnapshotStore(root, free_bytes=lambda _: free)


def _search_progress() -> PubMedSearchProgressRecord:
    return PubMedSearchProgressRecord.create(
        run_id="run:00000000-0000-4000-8000-000000000002",
        scope_id=f"scope:sha256:{'a' * 64}",
        query='("semaglutide"[Title/Abstract])',
        query_id="query:fixture",
        acquisition_intent_id=f"acquisition-intent:sha256:{'b' * 64}",
        snapshot_id=f"sha256:{'c' * 64}",
        manifest_id=f"sha256:{'c' * 64}",
        pmids=("10", "20"),
        search_source_outcome_id="source-operation-outcome:fixture",
        valid_result_count=2,
    )


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


def test_snapshot_store_authority_is_slotted_frozen_and_internally_operable(
    tmp_path: Path,
) -> None:
    snapshots = store(tmp_path / "snapshots")
    expected_root = (tmp_path / "snapshots").absolute()

    assert snapshots.root == expected_root
    assert not hasattr(snapshots, "__dict__")
    for name, value in (
        ("root", tmp_path / "foreign"),
        ("_root", tmp_path / "foreign"),
        ("read_source_replay", lambda *_args, **_kwargs: b"forged"),
        ("read_pubmed_search_progress", lambda *_args, **_kwargs: b"forged"),
        ("read_pubmed_terminal_progress", lambda *_args, **_kwargs: b"forged"),
    ):
        with pytest.raises(AttributeError, match="frozen"):
            setattr(snapshots, name, value)

    snapshots.initialize()
    assert snapshots._initialized
    with snapshots.writer():
        assert snapshots.has_writer_lock
        snapshots.store_raw_body(b"exact")
    assert not snapshots.has_writer_lock
    assert snapshots.root == expected_root


def test_pubmed_search_progress_read_is_exact_and_run_scoped(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"
    relative = "journal/00000000-0000-4000-8000-000000000002/acquisition-0000/"
    with snapshots.writer():
        snapshots.publish_bytes(
            relative + "search-progress.json",
            b'{"exact":true}',
            artifact_class="journal",
        )

    assert snapshots.read_pubmed_search_progress(run_id) == b'{"exact":true}'
    with pytest.raises(SnapshotContainmentError, match="run identity"):
        snapshots.read_pubmed_search_progress("../outside")
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        snapshots.read_pubmed_search_progress("run:ffffffff-ffff-4fff-8fff-ffffffffffff")


def test_concrete_acquisition_adapter_insert_or_verifies_exact_search_progress(
    tmp_path: Path,
) -> None:
    snapshots = store(tmp_path / "snapshots")
    adapter = _AcquisitionAdapter(
        store=snapshots,
        repository=object(),  # type: ignore[arg-type]
        code_revision="b" * 40,
    )
    record = _search_progress()
    with snapshots.writer():
        first = adapter.persist_search_progress(record)
        second = adapter.persist_search_progress(record)

    assert first == second == record
    assert (
        adapter.load_search_progress(
            run_id=record.run_id,
            acquisition_intent_id=record.acquisition_intent_id,
        )
        == record
    )
    conflicting = PubMedSearchProgressRecord.create(
        **{
            **record.payload(),
            "pmids": ("10", "30"),
        }
    )
    with snapshots.writer(), pytest.raises(SnapshotIntegrityError):
        adapter.persist_search_progress(conflicting)


def test_pubmed_search_progress_read_rejects_oversize(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"
    target = (
        snapshots.root
        / "journal"
        / "00000000-0000-4000-8000-000000000002"
        / "acquisition-0000"
        / "search-progress.json"
    )
    snapshots.initialize()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 16_385)
    with pytest.raises(SnapshotIntegrityError, match="invalid size"):
        snapshots.read_pubmed_search_progress(run_id)


def test_generation_receipt_is_run_scoped_bounded_and_requires_writer(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"
    receipt_id = "generation-receipt:sha256:" + "d" * 64
    raw = b'{"marker":"M3_GENERATION_RECEIPT_V1"}'

    with pytest.raises(SnapshotBusyError, match="writer lock"):
        snapshots.publish_generation_receipt(raw, run_id=run_id, receipt_id=receipt_id)
    with snapshots.writer():
        first = snapshots.publish_generation_receipt(raw, run_id=run_id, receipt_id=receipt_id)
        second = snapshots.publish_generation_receipt(raw, run_id=run_id, receipt_id=receipt_id)

    assert snapshots.read_generation_receipt(run_id=run_id, receipt_id=receipt_id) == raw
    assert not first.reused_existing
    assert second.reused_existing
    assert first.path == (
        snapshots.root
        / "journal"
        / "00000000-0000-4000-8000-000000000002"
        / "generation"
        / f"{'d' * 64}.json"
    )
    with snapshots.writer(), pytest.raises(SnapshotCapacityError, match="invalid size"):
        snapshots.publish_generation_receipt(b"x" * 65_537, run_id=run_id, receipt_id=receipt_id)


def test_generation_receipt_rejects_invalid_identity_collision_and_missing(
    tmp_path: Path,
) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"
    receipt_id = "generation-receipt:sha256:" + "e" * 64
    with snapshots.writer():
        snapshots.publish_generation_receipt(
            b'{"exact":true}', run_id=run_id, receipt_id=receipt_id
        )
        with pytest.raises(SnapshotIntegrityError, match="size or type"):
            snapshots.publish_generation_receipt(
                b'{"exact":false}', run_id=run_id, receipt_id=receipt_id
            )
    for bad_run, bad_receipt in (
        ("../foreign", receipt_id),
        (run_id, "../foreign"),
        (run_id, "generation-receipt:sha256:" + "g" * 64),
    ):
        with pytest.raises(SnapshotContainmentError, match="receipt identity"):
            snapshots.read_generation_receipt(run_id=bad_run, receipt_id=bad_receipt)
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        snapshots.read_generation_receipt(
            run_id=run_id,
            receipt_id="generation-receipt:sha256:" + "f" * 64,
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_generation_receipt_read_rejects_reparse_parent(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    run_root = snapshots.root / "journal" / "00000000-0000-4000-8000-000000000002"
    run_root.mkdir(parents=True)
    outside = tmp_path / "outside-generation"
    outside.mkdir()
    try:
        (run_root / "generation").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")

    with pytest.raises(SnapshotContainmentError, match=r"symlink|reparse"):
        snapshots.read_generation_receipt(
            run_id="run:00000000-0000-4000-8000-000000000002",
            receipt_id="generation-receipt:sha256:" + "a" * 64,
        )


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_pubmed_search_progress_read_rejects_reparse_leaf(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    target = (
        snapshots.root
        / "journal"
        / "00000000-0000-4000-8000-000000000002"
        / "acquisition-0000"
        / "search-progress.json"
    )
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside-progress.json"
    outside.write_bytes(b'{"foreign":true}')
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")

    with pytest.raises(SnapshotContainmentError):
        snapshots.read_pubmed_search_progress("run:00000000-0000-4000-8000-000000000002")


def test_pubmed_terminal_progress_read_is_exact_attempt_scoped_and_immutable(
    tmp_path: Path,
) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"
    attempt_id = f"source-task-attempt:sha256:{'a' * 64}"
    relative = (
        "journal/00000000-0000-4000-8000-000000000002/orchestration/pubmed/"
        f"{'a' * 64}/terminal-progress.json"
    )
    with snapshots.writer():
        first = snapshots.publish_bytes(
            relative,
            b'{"terminal":true}',
            artifact_class="journal",
        )
        second = snapshots.publish_bytes(
            relative,
            b'{"terminal":true}',
            artifact_class="journal",
        )
    assert not first.reused_existing and second.reused_existing
    assert snapshots.read_pubmed_terminal_progress(run_id, attempt_id) == b'{"terminal":true}'
    with snapshots.writer(), pytest.raises(SnapshotIntegrityError):
        snapshots.publish_bytes(relative, b'{"rewritten":true}', artifact_class="journal")
    with pytest.raises(SnapshotContainmentError, match="terminal-progress identity"):
        snapshots.read_pubmed_terminal_progress(run_id, "attempt:foreign")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_pubmed_terminal_progress_read_rejects_reparse_leaf(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    snapshots.initialize()
    attempt_digest = "a" * 64
    target = (
        snapshots.root
        / "journal"
        / "00000000-0000-4000-8000-000000000002"
        / "orchestration"
        / "pubmed"
        / attempt_digest
        / "terminal-progress.json"
    )
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside-terminal.json"
    outside.write_bytes(b'{"foreign":true}')
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable to this test process")
    with pytest.raises(SnapshotContainmentError):
        snapshots.read_pubmed_terminal_progress(
            "run:00000000-0000-4000-8000-000000000002",
            f"source-task-attempt:sha256:{attempt_digest}",
        )


def test_source_replay_narrow_read_and_exact_per_source_run_ceilings(tmp_path: Path) -> None:
    snapshots = store(tmp_path / "snapshots")
    run_id = "run:00000000-0000-4000-8000-000000000002"

    def keys(index: int) -> dict[str, str]:
        return {
            "run_id": run_id,
            "task_id": f"source-task:fixture:{index}",
            "attempt_id": f"source-task-attempt:fixture:{index}",
            "query_id": f"query:fixture:{index}",
            "acquisition_intent_id": f"acquisition-intent:fixture:{index}",
        }

    with snapshots.writer():
        for index in range(8):
            kind = "dailymed-discovery" if index % 2 == 0 else "dailymed-fetch"
            snapshots.publish_source_replay(kind, f'{{"index":{index}}}'.encode(), **keys(index))
        with pytest.raises(SnapshotCapacityError, match="dailymed replay records"):
            snapshots.publish_source_replay("dailymed-discovery", b'{"index":8}', **keys(8))
        for index in range(8):
            snapshots.publish_source_replay(
                "faers-aggregate", f'{{"index":{index}}}'.encode(), **keys(index + 20)
            )
        with pytest.raises(SnapshotCapacityError, match="faers replay records"):
            snapshots.publish_source_replay("faers-aggregate", b'{"index":8}', **keys(28))

    assert snapshots.read_source_replay("dailymed-discovery", **keys(0)) == b'{"index":0}'
    assert snapshots.read_source_replay("faers-aggregate", **keys(20)) == b'{"index":0}'
    replay_paths = tuple(snapshots.root.rglob("projection.json"))
    assert len(replay_paths) == 16
    assert all("source-task:fixture" not in path.as_posix() for path in replay_paths)
    assert all("query:fixture" not in path.as_posix() for path in replay_paths)
    with pytest.raises(SnapshotIntegrityError, match="missing"):
        snapshots.read_source_replay("dailymed-discovery", **keys(80))
    with pytest.raises(SnapshotContainmentError, match="key has invalid size"):
        snapshots.read_source_replay(
            "dailymed-discovery",
            **{**keys(0), "query_id": "x" * 257},
        )


def test_source_replay_record_size_is_bounded_without_large_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.ingestion.snapshots as snapshots_module

    monkeypatch.setattr(snapshots_module, "SOURCE_REPLAY_RECORD_BYTE_CAPACITY", 1)
    snapshots = store(tmp_path / "snapshots")
    with snapshots.writer(), pytest.raises(SnapshotCapacityError, match="invalid size"):
        snapshots.publish_source_replay(
            "faers-aggregate",
            b"{}",
            run_id="run:00000000-0000-4000-8000-000000000002",
            task_id="source-task:fixture",
            attempt_id="source-task-attempt:fixture",
            query_id="query:fixture",
            acquisition_intent_id="acquisition-intent:fixture",
        )


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
        committed_files=lambda: PERSISTENT_FILE_CAPACITY,
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
