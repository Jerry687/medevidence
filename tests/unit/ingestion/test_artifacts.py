"""Canonical manifest persistence and replay tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

from medevidence.connectors.dailymed.parsing import parse_spl_document
from medevidence.connectors.faers import (
    FaersConnector,
    FaersConnectorResult,
    FaersFailureKind,
)
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.domain.identifiers import m1a_canonical_json_bytes
from medevidence.ingestion import artifacts as artifacts_module
from medevidence.ingestion.artifacts import (
    DailyMedManifestMember,
    DailyMedSnapshotManifest,
    FaersManifestMember,
    FaersSnapshotManifest,
    ManifestFile,
    SnapshotManifest,
    capture_acquisition,
    capture_dailymed_snapshot,
    capture_faers_snapshot,
    manifest_file_from_link,
    replay_dailymed_snapshot,
    replay_faers_snapshot,
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


class ReadTimeoutStream(httpx.SyncByteStream):
    def __init__(self, prefix: bytes) -> None:
        self.prefix = prefix

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield self.prefix
        raise httpx.ReadTimeout("synthetic streamed read timeout")


def faers_query() -> FaersAggregateQueryV1:
    return FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:synthetic",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="SYNTHETIC",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            statistical_unit="provider_count_occurrence",
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
        )
    )


def faers_buckets() -> tuple[FaersAggregateBucketV1, ...]:
    query = faers_query()
    return tuple(
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=ordinal,
            reaction_pt=pt,
            report_count=count,
            identity_stratum=query.identity_stratum,
        )
        for ordinal, (pt, count) in enumerate((("NAUSEA", 8), ("VOMITING", 4)))
    )


def faers_outcome() -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.FAERS,
        query_id=faers_query().query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=2,
        pages_completed=1,
        truncated=False,
    )


def faers_observation(
    body: bytes,
    *,
    second: int,
    status: int = 200,
    complete: bool = True,
    termination_reason: artifacts_module.TerminationReason = "complete_response",
) -> artifacts_module.RawResponseObservation:
    return response_observation(
        body=body,
        observed_at_utc=datetime(2026, 8, 12, 0, 0, second, tzinfo=UTC),
        headers=(("content-type", "application/json"),),
        http_status=status,
        body_complete=complete,
        termination_reason=termination_reason,
    )


def faers_manifest_values(
    members: tuple[FaersManifestMember, ...],
    *,
    attempts_used: int,
) -> dict[str, object]:
    return {
        "run_id": "run:00000000-0000-4000-8000-000000000002",
        "acquisition_id": "acquisition:faers-attempt-lineage",
        "acquisition_intent_id": f"acquisition-intent:sha256:{'5' * 64}",
        "acquisition_ordinal": 0,
        "query": faers_query(),
        "snapshot_id": "snapshot:faers-attempt-lineage",
        "started_at_utc": datetime(2026, 8, 12, tzinfo=UTC),
        "completed_at_utc": datetime(2026, 8, 12, 0, 0, 3, tzinfo=UTC),
        "source_outcome": faers_outcome(),
        "retrieved_at_utc": datetime(2026, 8, 12, 0, 0, 3, tzinfo=UTC),
        "provider_as_of_utc": None,
        "attempts_used": attempts_used,
        "buckets": faers_buckets(),
        "members": members,
        "code_revision": "a" * 40,
    }


def connector_observations(
    result: FaersConnectorResult,
) -> tuple[artifacts_module.RawResponseObservation, ...]:
    return tuple(
        response_observation(
            body=raw.body,
            observed_at_utc=raw.observed_at_utc,
            headers=raw.headers,
            http_status=raw.status_code,
            body_complete=raw.body_complete,
            termination_reason=cast(
                artifacts_module.TerminationReason,
                raw.termination_reason,
            ),
        )
        for raw in result.raw_responses
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
    def validate_spl(body: bytes, setid: str, spl_version: str) -> None:
        parse_spl_document(
            body,
            expected_setid=setid,
            expected_spl_version=spl_version,
        )

    return SnapshotStore(
        root,
        free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES,
        dailymed_spl_validator=validate_spl,
    )


def _dailymed_member_for_size(
    *,
    ordinal: int,
    byte_size: int,
    stable_spl: bool = False,
    body_complete: bool = True,
) -> DailyMedManifestMember:
    digest = format(ordinal + 1, "x") * 64
    artifact_id = f"sha256:{digest}"
    return DailyMedManifestMember(
        ordinal=ordinal,
        link_id=f"artifact-link:sha256:{format(ordinal + 8, 'x') * 64}",
        artifact_id=artifact_id,
        content_hash=artifact_id,
        artifact_kind="dailymed_spl_xml" if stable_spl else "dailymed_http_response",
        relative_path=(
            f"dailymed/sha256/{digest}.xml"
            if stable_spl
            else f"dailymed/raw/sha256/{digest[:2]}/{digest}.bin"
        ),
        byte_size=byte_size,
        media_type="application/xml",
        http_status=200,
        body_complete=body_complete,
        termination_reason="complete_response" if body_complete else "stream_error",
    )


def _dailymed_manifest_for_sizes(
    response_sizes: tuple[int, ...],
    *,
    stable_spl_size: int | None = None,
    execution_status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    result_status: ResultStatus = ResultStatus.MATCHES,
    record_count: int = 1,
) -> DailyMedSnapshotManifest:
    response_members = tuple(
        _dailymed_member_for_size(ordinal=ordinal, byte_size=size)
        for ordinal, size in enumerate(response_sizes)
    )
    stable_members = (
        (
            _dailymed_member_for_size(
                ordinal=len(response_members),
                byte_size=stable_spl_size,
                stable_spl=True,
            ),
        )
        if stable_spl_size is not None
        else ()
    )
    return DailyMedSnapshotManifest(
        run_id="run:00000000-0000-4000-8000-000000000101",
        acquisition_id="acquisition:dailymed-bound",
        acquisition_intent_id=ACQUISITION_ID,
        acquisition_ordinal=1,
        query_id="query:dailymed-bound",
        snapshot_id="snapshot:dailymed-bound",
        operation="fetch" if stable_members else "search",
        request_identity="dailymed:synthetic-bound",
        selected_setid=("11111111-1111-1111-1111-111111111111" if stable_members else None),
        selected_spl_version="3" if stable_members else None,
        started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 12, 1, 0, 2, tzinfo=UTC),
        execution_status=execution_status,
        coverage_status=coverage_status,
        result_status=result_status,
        record_count=record_count,
        pages_completed=len(response_members) if coverage_status is CoverageStatus.COMPLETE else 0,
        attempts_used=1,
        truncated=coverage_status is CoverageStatus.PARTIAL,
        warning_codes=(
            ("source_unavailable",)
            if coverage_status is CoverageStatus.UNAVAILABLE
            else (("incomplete_coverage",) if coverage_status is CoverageStatus.PARTIAL else ())
        ),
        members=(*response_members, *stable_members),
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )


def _capture_dailymed_response_bodies(
    snapshots: SnapshotStore,
    *,
    bodies: tuple[bytes, ...],
    coverage_status: CoverageStatus,
    body_complete: bool,
) -> artifacts_module.CapturedDailyMedSnapshot:
    observations = tuple(
        response_observation(
            body=body,
            observed_at_utc=datetime(2026, 8, 12, 1, 0, ordinal, tzinfo=UTC),
            headers=(("content-type", "application/xml"),),
            http_status=200,
            body_complete=body_complete,
            termination_reason="complete_response" if body_complete else "stream_error",
        )
        for ordinal, body in enumerate(bodies, start=1)
    )
    return capture_dailymed_snapshot(
        snapshots,
        run_id="run:00000000-0000-4000-8000-000000000101",
        acquisition_id="acquisition:dailymed-response-bound",
        acquisition_intent_id=ACQUISITION_ID,
        acquisition_ordinal=1,
        query_id="query:dailymed-response-bound",
        snapshot_id="snapshot:dailymed-response-bound",
        operation="search",
        request_identity="dailymed:synthetic-response-bound",
        started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 12, 1, 0, 6, tzinfo=UTC),
        execution_status=(
            ExecutionStatus.SUCCEEDED
            if coverage_status is CoverageStatus.COMPLETE
            else ExecutionStatus.FAILED
        ),
        coverage_status=coverage_status,
        result_status=ResultStatus.MATCHES,
        record_count=1,
        pages_completed=len(bodies) if body_complete else 0,
        attempts_used=2 if len(bodies) > 1 else 1,
        truncated=coverage_status is CoverageStatus.PARTIAL,
        warning_codes=("incomplete_coverage",) if coverage_status is CoverageStatus.PARTIAL else (),
        observations=observations,
        stable_spl_bytes=None,
        selected_setid=None,
        selected_spl_version=None,
        code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
    )


def test_dailymed_manifest_enforces_cumulative_response_bound_without_double_counting_spl() -> None:
    first = RAW_RESPONSE_BYTE_CAPACITY // 2
    exact = _dailymed_manifest_for_sizes(
        (first, RAW_RESPONSE_BYTE_CAPACITY - first),
        stable_spl_size=RAW_RESPONSE_BYTE_CAPACITY,
    )

    response_total = sum(
        member.byte_size
        for member in exact.members
        if member.artifact_kind == "dailymed_http_response"
    )
    assert response_total == RAW_RESPONSE_BYTE_CAPACITY
    assert sum(member.byte_size for member in exact.members) > RAW_RESPONSE_BYTE_CAPACITY

    with pytest.raises(ValidationError, match="cumulative 5,242,880-byte bound"):
        _dailymed_manifest_for_sizes((first, RAW_RESPONSE_BYTE_CAPACITY - first + 1))


def test_dailymed_capture_accepts_exact_cumulative_response_bound(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "exact")
    first = RAW_RESPONSE_BYTE_CAPACITY // 2
    bodies = (b"a" * first, b"b" * (RAW_RESPONSE_BYTE_CAPACITY - first))

    with snapshots.writer():
        captured = _capture_dailymed_response_bodies(
            snapshots,
            bodies=bodies,
            coverage_status=CoverageStatus.COMPLETE,
            body_complete=True,
        )

    assert sum(member.byte_size for member in captured.manifest.members) == (
        RAW_RESPONSE_BYTE_CAPACITY
    )


@pytest.mark.parametrize(
    ("name", "sizes", "coverage_status", "body_complete"),
    [
        (
            "multi-page-plus-one",
            (2_000_000, 2_000_000, RAW_RESPONSE_BYTE_CAPACITY - 3_999_999),
            CoverageStatus.COMPLETE,
            True,
        ),
        (
            "partial-prefix-plus-one",
            (RAW_RESPONSE_BYTE_CAPACITY // 2, RAW_RESPONSE_BYTE_CAPACITY // 2 + 1),
            CoverageStatus.PARTIAL,
            False,
        ),
    ],
)
def test_dailymed_capture_cumulative_failure_writes_nothing(
    tmp_path: Path,
    name: str,
    sizes: tuple[int, ...],
    coverage_status: CoverageStatus,
    body_complete: bool,
) -> None:
    snapshots = snapshot_store(tmp_path / name)
    bodies = tuple(bytes([97 + ordinal]) * size for ordinal, size in enumerate(sizes))

    with (
        snapshots.writer(),
        pytest.raises(ValidationError, match="cumulative 5,242,880-byte bound"),
    ):
        _capture_dailymed_response_bodies(
            snapshots,
            bodies=bodies,
            coverage_status=coverage_status,
            body_complete=body_complete,
        )

    assert _committed_files(snapshots) == ()


def test_dailymed_replay_rejects_cumulative_plus_one_before_file_access(tmp_path: Path) -> None:
    first = RAW_RESPONSE_BYTE_CAPACITY // 2
    exact = _dailymed_manifest_for_sizes((first, RAW_RESPONSE_BYTE_CAPACITY - first))
    oversized_members = (
        exact.members[0],
        exact.members[1].model_copy(update={"byte_size": exact.members[1].byte_size + 1}),
    )
    oversized = DailyMedSnapshotManifest.model_construct(
        **exact.model_dump(mode="python", exclude={"members"}),
        members=oversized_members,
    )

    with pytest.raises(ValidationError, match="cumulative 5,242,880-byte bound"):
        replay_dailymed_snapshot(
            oversized.canonical_bytes(),
            snapshot_store(tmp_path / "uninitialized"),
            expected_manifest_id=oversized.manifest_id,
            expected_members=oversized_members,
        )


def test_dailymed_zero_response_file_unavailable_manifest_captures_and_replays(
    tmp_path: Path,
) -> None:
    snapshots = snapshot_store(tmp_path / "zero")
    with snapshots.writer():
        captured = capture_dailymed_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000101",
            acquisition_id="acquisition:dailymed-unavailable",
            acquisition_intent_id=ACQUISITION_ID,
            acquisition_ordinal=1,
            query_id="query:dailymed-unavailable",
            snapshot_id="snapshot:dailymed-unavailable",
            operation="search",
            request_identity="dailymed:synthetic-unavailable",
            started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 1, 0, 2, tzinfo=UTC),
            execution_status=ExecutionStatus.FAILED,
            coverage_status=CoverageStatus.UNAVAILABLE,
            result_status=ResultStatus.INDETERMINATE,
            record_count=0,
            pages_completed=0,
            attempts_used=2,
            truncated=False,
            warning_codes=("source_unavailable",),
            observations=(),
            stable_spl_bytes=None,
            selected_setid=None,
            selected_spl_version=None,
            code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
        )

    assert captured.member_paths == ()
    assert (
        replay_dailymed_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_members=(),
        )
        == captured.manifest
    )


def test_dailymed_snapshot_capture_and_replay_are_exact_and_immutable(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    observation = response_observation(
        body=spl,
        observed_at_utc=datetime(2026, 8, 12, 1, 0, 1, tzinfo=UTC),
        headers=(("content-type", "application/xml"),),
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    with snapshots.writer():
        captured = capture_dailymed_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000101",
            acquisition_id="acquisition:dailymed-fetch",
            acquisition_intent_id=ACQUISITION_ID,
            acquisition_ordinal=1,
            query_id="query:dailymed-fetch",
            snapshot_id="snapshot:dailymed-fetch",
            operation="fetch",
            request_identity="dailymed:11111111-1111-1111-1111-111111111111:3",
            started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 1, 0, 2, tzinfo=UTC),
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            record_count=1,
            pages_completed=1,
            attempts_used=1,
            truncated=False,
            warning_codes=(),
            observations=(observation,),
            stable_spl_bytes=spl,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
            code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
        )

    assert tuple(member.artifact_kind for member in captured.manifest.members) == (
        "dailymed_http_response",
        "dailymed_spl_xml",
    )
    stable = captured.manifest.members[-1]
    digest = stable.artifact_id.removeprefix("sha256:")
    assert stable.relative_path == f"dailymed/sha256/{digest}.xml"
    assert captured.manifest_path.read_bytes() == captured.manifest.canonical_bytes()
    assert (
        replay_dailymed_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_members=captured.manifest.members,
        )
        == captured.manifest
    )


def test_dailymed_replay_rejects_member_drift_and_corruption(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    with snapshots.writer():
        response = snapshots.store_dailymed_response(b"")
        stable = snapshots.store_dailymed_spl(
            spl,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
        )
    assert response.byte_size == 0
    stable.path.write_bytes(b"corrupt")
    with pytest.raises(SnapshotIntegrityError):
        snapshots.verify_dailymed(
            stable.artifact_id,
            stable_spl=True,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
        )


@pytest.mark.parametrize(
    ("stable_body", "selected_version", "coverage"),
    [
        (b"not xml", "3", CoverageStatus.COMPLETE),
        (
            Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes(),
            "4",
            CoverageStatus.COMPLETE,
        ),
        (
            Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes(),
            "3",
            CoverageStatus.PARTIAL,
        ),
    ],
)
def test_dailymed_capture_rejects_malformed_foreign_or_partial_stable_spl_before_write(
    tmp_path: Path,
    stable_body: bytes,
    selected_version: str,
    coverage: CoverageStatus,
) -> None:
    snapshots = snapshot_store(tmp_path / selected_version / coverage.value)
    observation = response_observation(
        body=stable_body,
        observed_at_utc=datetime(2026, 8, 12, 1, 0, 1, tzinfo=UTC),
        headers=(("content-type", "application/xml"),),
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    with snapshots.writer(), pytest.raises((ValueError, ValidationError, SnapshotIntegrityError)):
        capture_dailymed_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000101",
            acquisition_id="acquisition:dailymed-fetch",
            acquisition_intent_id=ACQUISITION_ID,
            acquisition_ordinal=1,
            query_id="query:dailymed-fetch",
            snapshot_id="snapshot:dailymed-fetch",
            operation="fetch",
            request_identity="dailymed:11111111-1111-1111-1111-111111111111:3",
            started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 1, 0, 2, tzinfo=UTC),
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=coverage,
            result_status=ResultStatus.MATCHES,
            record_count=1,
            pages_completed=1,
            attempts_used=1,
            truncated=coverage is CoverageStatus.PARTIAL,
            warning_codes=("incomplete_coverage",) if coverage is CoverageStatus.PARTIAL else (),
            observations=(observation,),
            stable_spl_bytes=stable_body,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version=selected_version,
            code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
        )

    assert _committed_files(snapshots) == ()


def test_dailymed_store_and_replay_reject_foreign_stable_spl_identity(tmp_path: Path) -> None:
    snapshots = snapshot_store(tmp_path / "snapshots")
    spl = Path("tests/fixtures/dailymed/spl-valid.xml").read_bytes()
    foreign_setid = "22222222-2222-2222-2222-222222222222"
    foreign_spl = spl.replace(
        b"11111111-1111-1111-1111-111111111111",
        foreign_setid.encode("ascii"),
    )
    with snapshots.writer(), pytest.raises((ValueError, SnapshotIntegrityError)):
        snapshots.store_dailymed_spl(
            foreign_spl,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
        )

    observation = response_observation(
        body=spl,
        observed_at_utc=datetime(2026, 8, 12, 1, 0, 1, tzinfo=UTC),
        headers=(("content-type", "application/xml"),),
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    with snapshots.writer():
        captured = capture_dailymed_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000101",
            acquisition_id="acquisition:dailymed-fetch",
            acquisition_intent_id=ACQUISITION_ID,
            acquisition_ordinal=1,
            query_id="query:dailymed-fetch",
            snapshot_id="snapshot:dailymed-fetch",
            operation="fetch",
            request_identity="dailymed:11111111-1111-1111-1111-111111111111:3",
            started_at_utc=datetime(2026, 8, 12, 1, 0, 0, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 1, 0, 2, tzinfo=UTC),
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            record_count=1,
            pages_completed=1,
            attempts_used=1,
            truncated=False,
            warning_codes=(),
            observations=(observation,),
            stable_spl_bytes=spl,
            selected_setid="11111111-1111-1111-1111-111111111111",
            selected_spl_version="3",
            code_revision="a3fd66477046c9e026d7b2222e882cd94a84d535",
        )
        foreign = snapshots.store_dailymed_spl(
            foreign_spl,
            selected_setid=foreign_setid,
            selected_spl_version="3",
        )

    stable = captured.manifest.members[-1]
    forged_stable = stable.model_copy(
        update={
            "artifact_id": foreign.artifact_id,
            "content_hash": foreign.artifact_id,
            "relative_path": foreign.path.relative_to(snapshots.root).as_posix(),
            "byte_size": foreign.byte_size,
        }
    )
    forged_manifest = captured.manifest.model_copy(
        update={"members": (*captured.manifest.members[:-1], forged_stable)}
    )
    with pytest.raises(SnapshotIntegrityError, match="exact selected label"):
        replay_dailymed_snapshot(
            forged_manifest.canonical_bytes(),
            snapshots,
            expected_manifest_id=forged_manifest.manifest_id,
            expected_members=forged_manifest.members,
        )


def test_dailymed_member_path_and_completion_are_fail_closed() -> None:
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="path must match"):
        DailyMedManifestMember(
            ordinal=0,
            link_id="artifact-link:sha256:" + "b" * 64,
            artifact_id=digest,
            content_hash=digest,
            artifact_kind="dailymed_spl_xml",
            relative_path="dailymed/run-scoped/label.xml",
            byte_size=1,
            media_type="application/xml",
            http_status=200,
            body_complete=True,
            termination_reason="complete_response",
        )
    with pytest.raises(ValidationError, match="nonempty and complete"):
        DailyMedManifestMember(
            ordinal=0,
            link_id="artifact-link:sha256:" + "b" * 64,
            artifact_id=digest,
            content_hash=digest,
            artifact_kind="dailymed_spl_xml",
            relative_path="dailymed/sha256/" + "a" * 64 + ".xml",
            byte_size=0,
            media_type="application/xml",
            http_status=200,
            body_complete=True,
            termination_reason="complete_response",
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


def test_faers_snapshot_capture_replay_and_exact_raw_bytes(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    body = b'{"results":[{"term":"NAUSEA","count":8}]}'
    observation = response_observation(
        body=body,
        observed_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
        headers=(("content-type", "application/json"),),
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    with snapshots.writer():
        captured = capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-synthetic",
            acquisition_intent_id=f"acquisition-intent:sha256:{'2' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-synthetic",
            started_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
            source_outcome=faers_outcome(),
            retrieved_at_utc=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
            provider_as_of_utc=None,
            attempts_used=1,
            buckets=faers_buckets(),
            observations=(observation,),
            code_revision="a" * 40,
        )
    assert captured.member_paths[0].read_bytes() == body
    assert captured.manifest_path.read_bytes() == captured.manifest.canonical_bytes()
    replayed = replay_faers_snapshot(
        captured.manifest_path.read_bytes(),
        snapshots,
        expected_manifest_id=captured.manifest.manifest_id,
        expected_query=faers_query(),
        expected_members=captured.manifest.members,
    )
    assert replayed == captured.manifest


def test_faers_replay_rejects_query_or_raw_byte_drift(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    observation = response_observation(
        body=b'{"results":[]}',
        observed_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
        headers=(("content-type", "application/json"),),
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    no_match = SourceOutcome(
        **{
            **faers_outcome().model_dump(mode="python"),
            "result_status": ResultStatus.NO_MATCH,
            "valid_result_count": 0,
        }
    )
    with snapshots.writer():
        captured = capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-empty",
            acquisition_intent_id=f"acquisition-intent:sha256:{'3' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-empty",
            started_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
            source_outcome=no_match,
            retrieved_at_utc=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
            provider_as_of_utc=None,
            attempts_used=1,
            buckets=(),
            observations=(observation,),
            code_revision="a" * 40,
        )
    foreign_query = FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:foreign",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="FOREIGN",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            statistical_unit="provider_count_occurrence",
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
        )
    )
    with pytest.raises(SnapshotIntegrityError, match="query differs"):
        replay_faers_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_query=foreign_query,
            expected_members=captured.manifest.members,
        )
    captured.member_paths[0].write_bytes(b"drift")
    with pytest.raises(SnapshotIntegrityError):
        replay_faers_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_query=faers_query(),
            expected_members=captured.manifest.members,
        )


def test_faers_manifest_rejects_missing_response_and_foreign_bucket() -> None:
    query = faers_query()
    values: dict[str, object] = {
        "run_id": "run:00000000-0000-4000-8000-000000000002",
        "acquisition_id": "acquisition:faers-synthetic",
        "acquisition_intent_id": f"acquisition-intent:sha256:{'2' * 64}",
        "acquisition_ordinal": 0,
        "query": query,
        "snapshot_id": "snapshot:faers-synthetic",
        "started_at_utc": datetime(2026, 8, 12, tzinfo=UTC),
        "completed_at_utc": datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
        "source_outcome": faers_outcome(),
        "retrieved_at_utc": datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
        "provider_as_of_utc": None,
        "attempts_used": 1,
        "buckets": faers_buckets(),
        "members": (),
        "code_revision": "a" * 40,
    }
    with pytest.raises(ValidationError, match="retained response"):
        FaersSnapshotManifest(**values)
    foreign = faers_buckets()[0].model_copy(update={"query_id": "query:foreign"})
    with pytest.raises(ValidationError):
        FaersSnapshotManifest(**{**values, "buckets": (foreign, faers_buckets()[1])})


def test_faers_capture_rejects_identical_retry_bodies_before_writes(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    observations = tuple(
        response_observation(
            body=b'{"results":[{"term":"NAUSEA","count":8}]}',
            observed_at_utc=datetime(2026, 8, 12, 0, 0, ordinal, tzinfo=UTC),
            headers=(("content-type", "application/json"),),
            http_status=503 if ordinal == 0 else 200,
            body_complete=ordinal == 1,
            termination_reason="stream_error" if ordinal == 0 else "complete_response",
        )
        for ordinal in range(2)
    )

    with (
        snapshots.writer(),
        pytest.raises(
            SnapshotIntegrityError,
            match=r"duplicate FAERS artifact_id .*ordinal=0 link_id=.*ordinal=1 link_id=",
        ),
    ):
        capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-duplicate-retry",
            acquisition_intent_id=f"acquisition-intent:sha256:{'4' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-duplicate-retry",
            started_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 0, 0, 2, tzinfo=UTC),
            source_outcome=faers_outcome(),
            retrieved_at_utc=datetime(2026, 8, 12, 0, 0, 2, tzinfo=UTC),
            provider_as_of_utc=None,
            attempts_used=2,
            buckets=faers_buckets(),
            observations=observations,
            code_revision="a" * 40,
        )

    assert _committed_files(snapshots) == ()


def test_faers_manifest_and_replay_reject_duplicate_artifact_members(tmp_path: Path) -> None:
    observations = tuple(
        response_observation(
            body=b'{"results":[]}',
            observed_at_utc=datetime(2026, 8, 12, 0, 0, ordinal, tzinfo=UTC),
            headers=(("content-type", "application/json"),),
            http_status=200,
            body_complete=True,
            termination_reason="complete_response",
        )
        for ordinal in range(2)
    )
    members = tuple(
        artifacts_module._faers_member(ordinal, observation)
        for ordinal, observation in enumerate(observations)
    )
    values = {
        "run_id": "run:00000000-0000-4000-8000-000000000002",
        "acquisition_id": "acquisition:faers-duplicate-members",
        "acquisition_intent_id": f"acquisition-intent:sha256:{'5' * 64}",
        "acquisition_ordinal": 0,
        "query": faers_query(),
        "snapshot_id": "snapshot:faers-duplicate-members",
        "started_at_utc": datetime(2026, 8, 12, tzinfo=UTC),
        "completed_at_utc": datetime(2026, 8, 12, 0, 0, 2, tzinfo=UTC),
        "source_outcome": faers_outcome(),
        "retrieved_at_utc": datetime(2026, 8, 12, 0, 0, 2, tzinfo=UTC),
        "provider_as_of_utc": None,
        "attempts_used": 2,
        "buckets": faers_buckets(),
        "members": members,
        "code_revision": "a" * 40,
    }
    with pytest.raises(ValidationError, match="duplicate FAERS artifact_id"):
        FaersSnapshotManifest(**values)

    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    valid_member = cast(FaersManifestMember, members[0].model_copy(update={"ordinal": 0}))
    valid_manifest = FaersSnapshotManifest(
        **{**values, "attempts_used": 1, "members": (valid_member,)}
    )
    duplicate_manifest_payload = valid_manifest.model_dump(mode="python", exclude_none=True)
    duplicate_manifest_payload["attempts_used"] = 2
    duplicate_manifest_payload["members"] = [
        member.model_dump(mode="python", exclude_none=True) for member in members
    ]
    with pytest.raises(ValidationError, match="duplicate FAERS artifact_id"):
        replay_faers_snapshot(
            m1a_canonical_json_bytes(duplicate_manifest_payload),
            snapshots,
            expected_manifest_id=valid_manifest.manifest_id,
            expected_query=faers_query(),
            expected_members=(valid_member,),
        )
    with pytest.raises(
        SnapshotIntegrityError,
        match=r"duplicate FAERS artifact_id .*ordinal=0 link_id=.*ordinal=1 link_id=",
    ):
        replay_faers_snapshot(
            valid_manifest.canonical_bytes(),
            snapshots,
            expected_manifest_id=valid_manifest.manifest_id,
            expected_query=faers_query(),
            expected_members=members,
        )


def test_faers_capture_rejects_three_responses_before_writes(tmp_path: Path) -> None:
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    observations = tuple(
        faers_observation(
            f'{{"attempt":{ordinal}}}'.encode(),
            second=ordinal,
            status=503 if ordinal < 2 else 200,
        )
        for ordinal in range(1, 4)
    )
    with snapshots.writer(), pytest.raises(ValueError, match="at most two"):
        capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-three-responses",
            acquisition_intent_id=f"acquisition-intent:sha256:{'6' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-three-responses",
            started_at_utc=datetime(2026, 8, 12, tzinfo=UTC),
            completed_at_utc=datetime(2026, 8, 12, 0, 0, 4, tzinfo=UTC),
            source_outcome=faers_outcome(),
            retrieved_at_utc=datetime(2026, 8, 12, 0, 0, 4, tzinfo=UTC),
            provider_as_of_utc=None,
            attempts_used=2,
            buckets=faers_buckets(),
            observations=observations,
            code_revision="a" * 40,
        )
    assert _committed_files(snapshots) == ()


def test_faers_manifest_attempt_response_lineage_matrix() -> None:
    success = artifacts_module._faers_member(0, faers_observation(b'{"ok":1}', second=1))
    retry = artifacts_module._faers_member(
        0,
        faers_observation(b'{"retry":1}', second=1, status=503),
    )
    retry_success = artifacts_module._faers_member(
        1,
        faers_observation(b'{"ok":2}', second=2),
    )

    one_for_one = FaersSnapshotManifest(**faers_manifest_values((success,), attempts_used=1))
    one_for_two = FaersSnapshotManifest(**faers_manifest_values((success,), attempts_used=2))
    two_for_two = FaersSnapshotManifest(
        **faers_manifest_values((retry, retry_success), attempts_used=2)
    )
    assert (len(one_for_one.members), one_for_one.attempts_used) == (1, 1)
    assert (len(one_for_two.members), one_for_two.attempts_used) == (1, 2)
    assert (len(two_for_two.members), two_for_two.attempts_used) == (2, 2)

    with pytest.raises(ValidationError, match="cannot exceed attempts_used"):
        FaersSnapshotManifest(**faers_manifest_values((retry, retry_success), attempts_used=1))
    terminal_first = artifacts_module._faers_member(
        0,
        faers_observation(b'{"ok":0}', second=1),
    )
    with pytest.raises(ValidationError, match="terminal response cannot precede"):
        FaersSnapshotManifest(
            **faers_manifest_values((terminal_first, retry_success), attempts_used=2)
        )


def test_faers_manifest_rejects_link_and_observation_order_drift() -> None:
    first = artifacts_module._faers_member(
        0,
        faers_observation(b'{"retry":1}', second=1, status=503),
    )
    second = artifacts_module._faers_member(1, faers_observation(b'{"ok":2}', second=2))
    with pytest.raises(ValidationError, match="link must bind"):
        FaersSnapshotManifest(
            **faers_manifest_values(
                (
                    first.model_copy(update={"link_id": f"artifact-link:sha256:{'f' * 64}"}),
                    second,
                ),
                attempts_used=2,
            )
        )
    late_first = artifacts_module._faers_member(
        0,
        faers_observation(b'{"retry":3}', second=2, status=503),
    )
    early_second = artifacts_module._faers_member(
        1,
        faers_observation(b'{"ok":4}', second=1),
    )
    with pytest.raises(ValidationError, match="follow response order"):
        FaersSnapshotManifest(**faers_manifest_values((late_first, early_second), attempts_used=2))


@pytest.mark.parametrize("status", (408, 429, 500, 501, 599))
def test_faers_manifest_admits_exact_complete_retryable_statuses(status: int) -> None:
    retry = artifacts_module._faers_member(
        0, faers_observation(b'{"retry":1}', second=1, status=status)
    )
    success = artifacts_module._faers_member(1, faers_observation(b'{"ok":2}', second=2))
    manifest = FaersSnapshotManifest(**faers_manifest_values((retry, success), attempts_used=2))
    assert manifest.members[0].http_status == status


def test_faers_manifest_rejects_nonretryable_incomplete_or_permanent_continuation() -> None:
    success = artifacts_module._faers_member(1, faers_observation(b'{"ok":2}', second=2))
    read_timeout = artifacts_module._faers_member(
        0,
        faers_observation(
            b'{"partial":',
            second=1,
            complete=False,
            termination_reason="read_timeout",
        ),
    )
    assert (
        FaersSnapshotManifest(**faers_manifest_values((read_timeout, success), attempts_used=2))
        .members[0]
        .termination_reason
        == "read_timeout"
    )

    invalid_first_members = (
        artifacts_module._faers_member(
            0,
            faers_observation(
                b'{"stream":',
                second=1,
                complete=False,
                termination_reason="stream_error",
            ),
        ),
        artifacts_module._faers_member(0, faers_observation(b'{"bad":1}', second=1, status=400)),
    )
    for first in invalid_first_members:
        with pytest.raises(ValidationError, match="terminal response cannot precede"):
            FaersSnapshotManifest(**faers_manifest_values((first, success), attempts_used=2))


def test_connector_stream_timeout_then_success_captures_and_replays(tmp_path: Path) -> None:
    requests = 0
    body = Path("tests/fixtures/faers/count-single-bucket.json").read_bytes()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, stream=ReadTimeoutStream(b'{"partial":'))
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=lambda: fixed,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.aggregate(faers_query())
    assert result.failure is None and result.value is not None
    assert tuple(raw.termination_reason for raw in result.raw_responses) == (
        "read_timeout",
        "complete_response",
    )
    buckets = tuple(
        FaersAggregateBucketV1(
            query_id=faers_query().query_id,
            bucket_ordinal=ordinal,
            reaction_pt=bucket.reaction_pt,
            report_count=bucket.report_count,
            identity_stratum=faers_query().identity_stratum,
        )
        for ordinal, bucket in enumerate(result.value.buckets)
    )
    outcome = SourceOutcome(
        **{
            **faers_outcome().model_dump(mode="python"),
            "valid_result_count": len(buckets),
        }
    )
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    with snapshots.writer():
        captured = capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-timeout-success",
            acquisition_intent_id=f"acquisition-intent:sha256:{'7' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-timeout-success",
            started_at_utc=fixed,
            completed_at_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            source_outcome=outcome,
            retrieved_at_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            provider_as_of_utc=result.value.provider_as_of_utc,
            attempts_used=result.request_count,
            buckets=buckets,
            observations=connector_observations(result),
            code_revision="a" * 40,
        )
    assert (
        replay_faers_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_query=faers_query(),
            expected_members=captured.manifest.members,
        )
        == captured.manifest
    )


def test_connector_stream_timeout_exhaustion_captures_and_replays(tmp_path: Path) -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            stream=ReadTimeoutStream(f'{{"partial":{requests}'.encode()),
        )

    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    with FaersConnector(
        httpx.MockTransport(handler),
        utc_now=lambda: fixed,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    ) as connector:
        result = connector.aggregate(faers_query())
    assert result.failure is not None
    assert result.failure.kind is FaersFailureKind.RETRY_EXHAUSTED
    assert tuple(raw.termination_reason for raw in result.raw_responses) == (
        "read_timeout",
        "read_timeout",
    )
    outcome = SourceOutcome(
        source=SourceType.FAERS,
        query_id=faers_query().query_id,
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=0,
        pages_completed=0,
        truncated=True,
        warning_codes=("incomplete_coverage",),
        failure_id="failure:synthetic-read-timeout",
    )
    snapshots = SnapshotStore(tmp_path, free_bytes=lambda _: INITIAL_FREE_SPACE_FLOOR_BYTES)
    with snapshots.writer():
        captured = capture_faers_snapshot(
            snapshots,
            run_id="run:00000000-0000-4000-8000-000000000002",
            acquisition_id="acquisition:faers-timeout-exhausted",
            acquisition_intent_id=f"acquisition-intent:sha256:{'8' * 64}",
            acquisition_ordinal=0,
            query=faers_query(),
            snapshot_id="snapshot:faers-timeout-exhausted",
            started_at_utc=fixed,
            completed_at_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            source_outcome=outcome,
            retrieved_at_utc=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
            provider_as_of_utc=None,
            attempts_used=result.request_count,
            buckets=(),
            observations=connector_observations(result),
            code_revision="a" * 40,
        )
    assert (
        replay_faers_snapshot(
            captured.manifest_path.read_bytes(),
            snapshots,
            expected_manifest_id=captured.manifest.manifest_id,
            expected_query=faers_query(),
            expected_members=captured.manifest.members,
        )
        == captured.manifest
    )
