"""Canonical manifest persistence and replay tests."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from medevidence.domain import CoverageStatus, ExecutionStatus, ResultStatus
from medevidence.ingestion import artifacts as artifacts_module
from medevidence.ingestion.artifacts import (
    ManifestFile,
    SnapshotManifest,
    capture_acquisition,
    manifest_file_from_link,
    replay_manifest,
    response_observation,
    write_immutable_manifest,
    write_immutable_record,
)
from medevidence.ingestion.contracts import ArtifactLink, with_computed_identity
from medevidence.ingestion.snapshots import (
    INITIAL_FREE_SPACE_FLOOR_BYTES,
    RAW_RESPONSE_BYTE_CAPACITY,
    SnapshotBusyError,
    SnapshotIntegrityError,
    SnapshotStore,
)

FIXTURE = Path("tests/fixtures/snapshots/manifest-v1.json")
ACQUISITION_ID = (
    "acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d"
)
VALID_SEARCH_BODY = (
    b"<eSearchResult><Count>1</Count><RetMax>1</RetMax><RetStart>0</RetStart>"
    b"<IdList><Id>1</Id></IdList></eSearchResult>"
)


def artifact_link() -> ArtifactLink:
    return artifact_link_for(
        VALID_SEARCH_BODY,
        ordinal=0,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )


def artifact_link_for(
    body: bytes,
    *,
    ordinal: int,
    http_status: int,
    body_complete: bool,
    termination_reason: str,
) -> ArtifactLink:
    digest = sha256(body).hexdigest()
    return cast(
        ArtifactLink,
        with_computed_identity(
            ArtifactLink,
            {
                "schema_version": "1.0",
                "acquisition_intent_id": ACQUISITION_ID,
                "ordinal": ordinal,
                "artifact_id": f"sha256:{digest}",
                "artifact_kind": "pubmed_http_response",
                "media_type": "application/xml",
                "http_status": http_status,
                "byte_size": len(body),
                "body_complete": body_complete,
                "termination_reason": termination_reason,
                "observed_at_utc": "2026-08-06T12:00:02.000000Z",
            },
        ),
    )


def manifest(*, files: tuple[ManifestFile, ...]) -> SnapshotManifest:
    return SnapshotManifest(
        acquisition_intent_id=ACQUISITION_ID,
        request_identity="pubmed-search:synthetic",
        started_at_utc=datetime(2026, 8, 6, 12, 0, 1, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 6, 12, 0, 4, tzinfo=UTC),
        record_count=1,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        files=files,
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )


def file_entry() -> ManifestFile:
    return manifest_file_from_link(artifact_link())


def snapshot_store(root: Path) -> SnapshotStore:
    return SnapshotStore(
        root,
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
    )


def test_manifest_fixture_is_exact_canonical_utf8_lf() -> None:
    expected = manifest(files=(file_entry(),))
    raw = FIXTURE.read_bytes()

    assert raw == expected.canonical_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\r\n")
    assert SnapshotManifest.from_json_bytes(raw) == expected
    assert expected.manifest_id.startswith("sha256:")


def test_manifest_replay_binds_identity_links_count_and_raw_bytes(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    link = artifact_link()
    expected = manifest(files=(manifest_file_from_link(link),))
    with snapshots.writer():
        snapshots.store_raw_body(VALID_SEARCH_BODY)
        manifest_path = write_immutable_manifest(snapshots, expected)
        assert write_immutable_manifest(snapshots, expected) == manifest_path

    replayed = replay_manifest(
        manifest_path.read_bytes(),
        snapshots,
        expected_manifest_id=expected.manifest_id,
        expected_links=(link,),
        expected_validated_record_count=1,
    )

    assert replayed == expected
    assert manifest_path == (
        snapshots.root
        / "pubmed"
        / "manifests"
        / "sha256"
        / expected.manifest_id.removeprefix("sha256:")[:2]
        / f"{expected.manifest_id.removeprefix('sha256:')}.json"
    )


def test_journal_and_manifest_publication_require_store_writer(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    snapshots.initialize()
    link = artifact_link()
    expected = manifest(files=(manifest_file_from_link(link),))

    with pytest.raises(SnapshotBusyError):
        write_immutable_record(
            snapshots,
            "journal/acquisition-0000",
            link.filename,
            link,
        )
    with pytest.raises(SnapshotBusyError):
        write_immutable_manifest(snapshots, expected)


def test_corruption_noncanonical_or_wrong_binding_blocks_replay(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    link = artifact_link()
    expected = manifest(files=(manifest_file_from_link(link),))
    with snapshots.writer():
        written = snapshots.store_raw_body(VALID_SEARCH_BODY)
    written.path.write_bytes(b"broken")
    with pytest.raises(SnapshotIntegrityError):
        replay_manifest(
            expected.canonical_bytes(),
            snapshots,
            expected_manifest_id=expected.manifest_id,
            expected_links=(link,),
            expected_validated_record_count=1,
        )

    raw = FIXTURE.read_bytes()
    with pytest.raises(ValueError, match="canonical"):
        SnapshotManifest.from_json_bytes(raw.replace(b",", b", ", 1))
    with pytest.raises(SnapshotIntegrityError, match="identity"):
        replay_manifest(
            raw,
            snapshots,
            expected_manifest_id=f"sha256:{'0' * 64}",
            expected_links=(link,),
            expected_validated_record_count=1,
        )


def test_zero_file_unavailable_manifest_is_valid() -> None:
    unavailable = SnapshotManifest(
        acquisition_intent_id=ACQUISITION_ID,
        request_identity="pubmed-search:synthetic",
        started_at_utc=datetime(2026, 8, 6, 12, 0, 1, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 6, 12, 0, 5, tzinfo=UTC),
        record_count=0,
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
        attempts_used=2,
        pages_completed=0,
        truncated=False,
        warning_codes=("source_unavailable",),
        files=(),
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )
    assert unavailable.files == ()


def test_complete_manifest_requires_positive_complete_evidence() -> None:
    with pytest.raises(ValidationError, match="retained source evidence"):
        manifest(files=())
    no_match = manifest(files=(file_entry(),)).model_dump(mode="python")
    no_match.update(record_count=0, result_status=ResultStatus.NO_MATCH, files=())
    with pytest.raises(ValidationError, match="retained files"):
        SnapshotManifest(**no_match)
    with pytest.raises(ValidationError, match="terminal nonempty"):
        manifest(
            files=(
                file_entry().model_copy(
                    update={
                        "body_complete": False,
                        "termination_reason": "stream_error",
                    }
                ),
            )
        )
    with pytest.raises(ValidationError, match="terminal nonempty"):
        manifest(files=(file_entry().model_copy(update={"byte_size": 0}),))
    with pytest.raises(ValidationError, match="payload ceiling"):
        manifest(
            files=(
                file_entry().model_copy(update={"byte_size": RAW_RESPONSE_BYTE_CAPACITY}),
                file_entry().model_copy(
                    update={
                        "ordinal": 1,
                        "link_id": f"artifact-link:sha256:{'1' * 64}",
                        "byte_size": 1,
                    }
                ),
            )
        )


@pytest.mark.parametrize("status", [400, 503])
def test_complete_manifest_rejects_non_2xx_completion(status: int) -> None:
    with pytest.raises(ValidationError, match="complete 2xx"):
        manifest(files=(file_entry().model_copy(update={"http_status": status}),))


def test_complete_manifest_retains_failed_prefix_before_effective_2xx() -> None:
    prefix = artifact_link_for(
        b"retained prefix",
        ordinal=0,
        http_status=503,
        body_complete=False,
        termination_reason="stream_error",
    )
    effective = artifact_link_for(
        VALID_SEARCH_BODY,
        ordinal=1,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )

    retry_manifest = manifest(
        files=(manifest_file_from_link(prefix), manifest_file_from_link(effective))
    )

    assert len(retry_manifest.files) == 2
    assert not retry_manifest.files[0].body_complete
    assert retry_manifest.files[1].body_complete


def partial_match_manifest(
    execution: ExecutionStatus,
    files: tuple[ManifestFile, ...],
) -> SnapshotManifest:
    return SnapshotManifest(
        acquisition_intent_id=ACQUISITION_ID,
        request_identity="pubmed-search:synthetic",
        started_at_utc=datetime(2026, 8, 6, 12, 0, 1, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 6, 12, 0, 4, tzinfo=UTC),
        record_count=1,
        execution_status=execution,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES,
        attempts_used=2,
        pages_completed=0,
        truncated=False,
        warning_codes=("partial_failure",),
        files=files,
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )


@pytest.mark.parametrize(
    "execution",
    [ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED],
)
def test_partial_match_accepts_incomplete_nonempty_2xx_prefix(
    execution: ExecutionStatus,
) -> None:
    prefix = artifact_link_for(
        b"retained prefix",
        ordinal=0,
        http_status=200,
        body_complete=False,
        termination_reason="stream_error",
    )

    partial = partial_match_manifest(execution, (manifest_file_from_link(prefix),))

    assert partial.pages_completed == 0
    assert not partial.files[0].body_complete


@pytest.mark.parametrize(
    "execution",
    [ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED],
)
def test_partial_match_retains_usable_2xx_before_later_503_failure(
    execution: ExecutionStatus,
) -> None:
    usable = artifact_link_for(
        b"usable prefix",
        ordinal=0,
        http_status=200,
        body_complete=False,
        termination_reason="stream_error",
    )
    later_failure = artifact_link_for(
        b"later failure",
        ordinal=1,
        http_status=503,
        body_complete=False,
        termination_reason="stream_error",
    )

    partial = partial_match_manifest(
        execution,
        (manifest_file_from_link(usable), manifest_file_from_link(later_failure)),
    )

    assert tuple(item.http_status for item in partial.files) == (200, 503)


def unusable_partial_files(case: str) -> tuple[ManifestFile, ...]:
    if case == "zero-byte-only":
        return (
            file_entry().model_copy(
                update={
                    "byte_size": 0,
                    "body_complete": False,
                    "termination_reason": "stream_error",
                }
            ),
        )
    statuses = (503,) if case == "503-only" else (400,)
    if case == "error-history":
        statuses = (503, 400)
    return tuple(
        manifest_file_from_link(
            artifact_link_for(
                f"error-{ordinal}".encode(),
                ordinal=ordinal,
                http_status=status,
                body_complete=False,
                termination_reason="stream_error",
            )
        )
        for ordinal, status in enumerate(statuses)
    )


@pytest.mark.parametrize(
    ("execution", "case"),
    [
        (execution, case)
        for execution in (ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED)
        for case in ("503-only", "4xx-only", "zero-byte-only", "error-history")
    ],
)
def test_partial_match_rejects_histories_without_usable_2xx_body(
    execution: ExecutionStatus,
    case: str,
) -> None:
    with pytest.raises(ValidationError, match="nonempty retained HTTP 2xx"):
        partial_match_manifest(execution, unusable_partial_files(case))


@pytest.mark.parametrize(
    "execution",
    [ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED],
)
def test_partial_match_rejects_zero_retained_evidence(
    execution: ExecutionStatus,
) -> None:
    with pytest.raises(ValidationError, match="retained source evidence"):
        partial_match_manifest(execution, ())


def _observation(
    body: bytes = VALID_SEARCH_BODY,
    *,
    status: int = 200,
    complete: bool = True,
) -> artifacts_module.RawResponseObservation:
    return response_observation(
        body=body,
        observed_at_utc=datetime(2026, 8, 6, 12, 0, 2, tzinfo=UTC),
        headers=(("content-type", "application/xml"),),
        http_status=status,
        body_complete=complete,
        termination_reason="complete_response" if complete else "stream_error",
    )


def _capture(
    store: SnapshotStore,
    *,
    count: int,
    result: ResultStatus,
    observations: tuple[artifacts_module.RawResponseObservation, ...],
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
) -> artifacts_module.CapturedAcquisition:
    return capture_acquisition(
        store,
        journal_relative_directory="journal/acquisition-0000",
        acquisition_intent_id=ACQUISITION_ID,
        request_identity="pubmed-search:synthetic",
        started_at_utc=datetime(2026, 8, 6, 12, 0, 1, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 6, 12, 0, 4, tzinfo=UTC),
        validated_record_count=count,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        attempts_used=2 if len(observations) > 1 else 1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        observations=observations,
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )


def _committed_files(store: SnapshotStore) -> tuple[Path, ...]:
    return tuple(
        path
        for path in store.root.rglob("*")
        if path.is_file() and path.name != ".m1a-constrained-v1.lock"
    )


def test_capture_preflight_invalid_count_or_status_leaves_zero_files(tmp_path: Path) -> None:
    for name, count, result, execution, coverage in (
        (
            "count",
            101,
            ResultStatus.MATCHES,
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.COMPLETE,
        ),
        (
            "status",
            0,
            ResultStatus.INDETERMINATE,
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.COMPLETE,
        ),
        (
            "status-count",
            1,
            ResultStatus.NO_MATCH,
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.COMPLETE,
        ),
    ):
        snapshots = snapshot_store(tmp_path / name)
        with snapshots.writer(), pytest.raises(ValidationError):
            _capture(
                snapshots,
                count=count,
                result=result,
                observations=(_observation(),),
                execution=execution,
                coverage=coverage,
            )
        assert _committed_files(snapshots) == ()

    http_error = snapshot_store(tmp_path / "http-error")
    with http_error.writer(), pytest.raises(ValidationError, match="complete 2xx"):
        _capture(
            http_error,
            count=1,
            result=ResultStatus.MATCHES,
            observations=(_observation(status=503),),
        )
    assert _committed_files(http_error) == ()


def test_capture_preflight_cumulative_limit_leaves_zero_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(artifacts_module, "RAW_RESPONSE_BYTE_CAPACITY", 3)
    snapshots = snapshot_store(tmp_path / "snapshots")
    observations = (
        _observation(b"aa", status=503, complete=False),
        _observation(b"bb"),
    )

    with snapshots.writer(), pytest.raises(ValidationError, match="payload ceiling"):
        _capture(
            snapshots,
            count=1,
            result=ResultStatus.MATCHES,
            observations=observations,
        )

    assert _committed_files(snapshots) == ()


def test_capture_complete_retry_publishes_both_ordered_links(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    observations = (
        _observation(b"retained prefix", status=503, complete=False),
        _observation(VALID_SEARCH_BODY),
    )

    with snapshots.writer():
        captured = _capture(
            snapshots,
            count=1,
            result=ResultStatus.MATCHES,
            observations=observations,
        )

    assert len(captured.artifact_links) == 2
    assert len(captured.manifest.files) == 2
    assert not captured.artifact_links[0].body_complete
    assert captured.artifact_links[1].body_complete
    assert tuple(item.ordinal for item in captured.artifact_links) == (0, 1)


def test_manifest_rejects_unknown_fields_and_noncontiguous_files() -> None:
    raw = FIXTURE.read_bytes().replace(
        b'"manifest_schema_version":"1.0"',
        b'"manifest_schema_version":"1.0","unknown":"value"',
    )
    with pytest.raises(ValidationError):
        SnapshotManifest.from_json_bytes(raw)

    second = file_entry().model_copy(
        update={
            "ordinal": 2,
            "link_id": f"artifact-link:sha256:{'1' * 64}",
        }
    )
    with pytest.raises(ValidationError, match="contiguous"):
        manifest(files=(file_entry(), second))
