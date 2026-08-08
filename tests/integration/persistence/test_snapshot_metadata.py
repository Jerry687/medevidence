"""Repository replay, conflict, concurrency, and rollback integration tests."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import product
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError

from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    IndexingStatus,
    Provenance,
    PublicationRecord,
    PublicationStatus,
    PublicationStatusValue,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
)
from medevidence.persistence import (
    AcquisitionRegistration,
    ArtifactIntegrityEventInput,
    ArtifactLineageRow,
    ArtifactRow,
    PersistenceConflict,
    PersistenceIntegrityError,
    PersistenceRepository,
    PersistenceSettings,
    PublicationVersionRow,
    RegistrationObservationInput,
    ResearchReportRow,
    ResearchRunAttemptRow,
    ResearchRunRow,
    RunReportRegistration,
    SnapshotFileRow,
    SourceSnapshotRow,
    ValidatedAcquisitionEnvelope,
    ValidatedArtifactLink,
    ValidatedManifest,
    ValidatedManifestFile,
    ValidatedReplay,
    models,
)
from medevidence.persistence import repositories as repository_module
from medevidence.persistence.config import DATABASE_URL_ENV
from medevidence.persistence.repositories import PersistenceCapacityError


@pytest.fixture(scope="module")
def engine() -> Engine:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    instance = sa.create_engine(value, hide_parameters=True)
    yield instance
    instance.dispose()


@pytest.fixture(scope="module")
def repository(engine: Engine) -> PersistenceRepository:
    return PersistenceRepository._from_engine_for_testing(engine)


def _artifact(label: str, *, kind: str = "snapshot_manifest") -> ArtifactRow:
    digest = f"sha256:{sha256(label.encode()).hexdigest()}"
    partition = "global" if kind in {"run_registration_envelope", "research_report"} else "pubmed"
    size = 0 if kind == "pubmed_http_response" else len(label.encode())
    return ArtifactRow(
        artifact_id=digest,
        artifact_kind=kind,
        source_partition=partition,
        content_hash=digest,
        byte_size=size,
        media_type="application/octet-stream"
        if kind == "pubmed_http_response"
        else "application/json",
        relative_storage_path=f"test/{digest.removeprefix('sha256:')}",
        artifact_schema_version="1.0",
    )


def _observation(detail: str, *, identity: str = "journal") -> RegistrationObservationInput:
    path = f"pubmed/{identity}/registration-envelope.json"
    return RegistrationObservationInput(
        observation_kind="invalid_envelope",
        source_partition="pubmed",
        run_id=None,
        attempt_id=None,
        observed_relative_path=path,
        observed_relative_path_hash=f"sha256:{sha256(path.encode()).hexdigest()}",
        expected_artifact_id=None,
        expected_artifact_kind=None,
        expected_source_partition=None,
        expected_content_hash=None,
        expected_envelope_id=None,
        observed_artifact_id=None,
        observed_envelope_id=None,
        observed_content_hash=None,
        expected_byte_size=None,
        observed_byte_size=None,
        redacted_detail=detail,
        observed_at_utc=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    )


def test_identical_artifact_replay_and_conflicting_replay(
    repository: PersistenceRepository,
) -> None:
    artifact = _artifact("artifact-replay")

    assert repository.insert_or_verify_artifact(artifact) == artifact
    assert repository.insert_or_verify_artifact(artifact) == artifact
    conflict = ArtifactRow(**{**artifact, "relative_storage_path": "test/other-valid-path"})
    with pytest.raises(PersistenceConflict):
        repository.insert_or_verify_artifact(conflict)


def test_concurrent_identical_observations_converge(
    repository: PersistenceRepository,
) -> None:
    observation = _observation("same redacted detail")

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = tuple(
            pool.map(
                repository.insert_or_verify_registration_observation, (observation, observation)
            )
        )

    assert rows[0]["observation_id"] == rows[1]["observation_id"]


def test_concurrent_conflicting_observations_are_classified(
    repository: PersistenceRepository,
) -> None:
    first = _observation("first redacted detail", identity="conflict-concurrency")
    second = _observation("different redacted detail", identity="conflict-concurrency")

    def insert(value: RegistrationObservationInput) -> str:
        try:
            repository.insert_or_verify_registration_observation(value)
        except PersistenceConflict:
            return "conflict"
        return "inserted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(insert, (first, second)))

    assert sorted(outcomes) == ["conflict", "inserted"]


def test_acquisition_transaction_rolls_back_earlier_metadata(
    repository: PersistenceRepository,
) -> None:
    invalid_observation = _observation("rollback", identity="rollback-acquisition")
    invalid_observation["observed_relative_path_hash"] = _hash("different-path")
    registration = _complete_acquisition_registration(
        "rollback-acquisition", observations=(invalid_observation,)
    )

    with pytest.raises(ValueError, match="observed path hash"):
        repository.register_acquisition(registration)

    snapshot_id = registration.snapshot["snapshot_id"]
    assert repository.get_artifact(snapshot_id) is None
    assert repository.get_snapshot(snapshot_id) is None


def test_run_report_transaction_rolls_back_earlier_metadata(
    repository: PersistenceRepository,
) -> None:
    acquisition = _complete_acquisition_registration("rollback-report")
    repository.register_acquisition(acquisition)
    envelope, report_artifact, run, report = _run_report_values("rollback-report")
    lineage = ArtifactLineageRow(
        parent_artifact_id=envelope["artifact_id"],
        parent_artifact_kind=envelope["artifact_kind"],
        parent_source_partition=envelope["source_partition"],
        parent_content_hash=envelope["content_hash"],
        child_artifact_id=report_artifact["artifact_id"],
        child_artifact_kind=report_artifact["artifact_kind"],
        child_source_partition=report_artifact["source_partition"],
        child_content_hash=report_artifact["content_hash"],
        lineage_type="run_envelope_to_report",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    incomplete_observation = cast(
        RegistrationObservationInput,
        {"observed_relative_path": None, "observed_relative_path_hash": None},
    )
    registration = RunReportRegistration(
        artifacts=(envelope, report_artifact),
        run=cast(ResearchRunRow, run),
        report=cast(ResearchReportRow, report),
        lineage=(lineage,),
        acquisition_references=((0, acquisition.attempt["registration_envelope_id"]),),
        observations=(incomplete_observation,),
    )

    with pytest.raises(ValueError, match="every persisted column"):
        repository.register_run_and_report(registration)

    assert repository.get_artifact(envelope["artifact_id"]) is None
    assert repository.get_artifact(report_artifact["artifact_id"]) is None
    assert repository.get_run(cast(str, run["run_id"])) is None
    assert repository.get_report(cast(str, report["report_id"])) is None


NOW = datetime(2026, 8, 7, 14, 0, tzinfo=UTC)
VALID_OUTCOMES = {
    ("succeeded", "complete", "matches"),
    ("succeeded", "complete", "no_match"),
    ("succeeded", "partial", "matches"),
    ("succeeded", "partial", "indeterminate"),
    ("failed", "partial", "matches"),
    ("failed", "partial", "indeterminate"),
    ("failed", "unavailable", "indeterminate"),
}
ALL_OUTCOMES = tuple(
    product(
        ("succeeded", "failed"),
        ("complete", "partial", "unavailable"),
        ("matches", "no_match", "indeterminate"),
    )
)
ARTIFACT_SPECS = {
    "pubmed_http_response": ("pubmed", 0, 5_242_880, False),
    "snapshot_manifest": ("pubmed", 1, 1_048_576, True),
    "publication_record": ("pubmed", 1, 31_457_280, True),
    "acquisition_registration_envelope": ("pubmed", 1, 1_048_576, True),
    "run_registration_envelope": ("global", 1, 1_048_576, True),
    "research_report": ("global", 1, 4_294_967_296, True),
}


def _hash(label: str) -> str:
    return f"sha256:{sha256(label.encode()).hexdigest()}"


def _uuid4(label: str) -> str:
    tail = sha256(label.encode()).hexdigest()[:12]
    return f"00000000-0000-4000-8000-{tail}"


def _artifact_values(
    label: str,
    kind: str,
    *,
    partition: str | None = None,
    byte_size: int | None = None,
    media_type: str | None = None,
) -> ArtifactRow:
    expected_partition, lower, _, is_json = ARTIFACT_SPECS[kind]
    digest = _hash(label)
    return ArtifactRow(
        artifact_id=digest,
        artifact_kind=kind,
        source_partition=partition or expected_partition,
        content_hash=digest,
        byte_size=lower if byte_size is None else byte_size,
        media_type=media_type or ("application/json" if is_json else "application/xml"),
        relative_storage_path=f"matrix/{digest.removeprefix('sha256:')}",
        artifact_schema_version="1.0",
    )


def _snapshot_values(
    label: str,
    outcome: tuple[str, str, str],
    *,
    count: int | None = None,
    pages: int | None = None,
    truncated: bool = False,
) -> tuple[ArtifactRow, SourceSnapshotRow]:
    execution, coverage, result = outcome
    manifest = _artifact_values(f"{label}:manifest", "snapshot_manifest")
    record_count = (1 if result == "matches" else 0) if count is None else count
    page_count = (1 if coverage == "complete" else 0) if pages is None else pages
    intent = f"acquisition-intent:{_hash(f'{label}:intent')}"
    snapshot = SourceSnapshotRow(
        snapshot_id=manifest["artifact_id"],
        source="pubmed",
        acquisition_intent_id=intent,
        request_identity=f"bounded request {label}",
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        record_count=record_count,
        attempts_used=1,
        pages_completed=page_count,
        truncated=truncated,
        manifest_artifact_id=manifest["artifact_id"],
        manifest_artifact_kind="snapshot_manifest",
        manifest_source_partition="pubmed",
        manifest_content_hash=manifest["content_hash"],
        started_at_utc=NOW,
        completed_at_utc=NOW,
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        manifest_schema_version="1.0",
        source_record_schema_version="1.0",
        code_revision="a" * 40,
        retention_policy_id="M1A-LIVE-RETENTION-v1",
    )
    return manifest, snapshot


def _attempt_values(
    label: str,
    outcome: tuple[str, str, str],
    *,
    count: int | None = None,
    pages: int | None = None,
    truncated: bool = False,
) -> tuple[ArtifactRow, ArtifactRow, SourceSnapshotRow, ResearchRunAttemptRow]:
    execution, coverage, result = outcome
    manifest, snapshot = _snapshot_values(
        f"{label}:snapshot", ("succeeded", "complete", "no_match")
    )
    envelope = _artifact_values(f"{label}:envelope", "acquisition_registration_envelope")
    valid_count = (1 if result == "matches" else 0) if count is None else count
    page_count = (1 if coverage == "complete" else 0) if pages is None else pages
    failure_code = "source_failure" if execution == "failed" else None
    redacted_detail = "bounded failure" if execution == "failed" else None
    attempt = ResearchRunAttemptRow(
        attempt_id=f"attempt:{_uuid4(f'{label}:attempt')}",
        run_id=f"run:{_uuid4(f'{label}:run')}",
        acquisition_ordinal=0,
        acquisition_intent_id=snapshot["acquisition_intent_id"],
        registration_envelope_id=(
            f"registration-envelope:acquisition:{_hash(f'{label}:registration')}"
        ),
        source="pubmed",
        operation="search",
        intent_created_at_utc=NOW,
        request_identity=snapshot["request_identity"],
        execution_profile_id="M1A_CONSTRAINED_V1",
        started_at_utc=NOW,
        completed_at_utc=NOW,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        valid_result_count=valid_count,
        pages_completed=page_count,
        attempts_used=1,
        truncated=truncated,
        warning_codes=[],
        failure_code=failure_code,
        redacted_detail=redacted_detail,
        registration_state="ready_for_insert",
        manifest_id=snapshot["snapshot_id"],
        envelope_artifact_id=envelope["artifact_id"],
        envelope_artifact_kind="acquisition_registration_envelope",
        envelope_source_partition="pubmed",
        envelope_content_hash=envelope["content_hash"],
        intent_schema_version="1.0",
        envelope_schema_version="1.0",
    )
    return manifest, envelope, snapshot, attempt


def _complete_acquisition_registration(
    label: str,
    *,
    observations: tuple[RegistrationObservationInput, ...] = (),
) -> AcquisitionRegistration:
    manifest_artifact, envelope_artifact, snapshot, attempt = _attempt_values(
        label, ("succeeded", "complete", "no_match")
    )
    manifest_bytes = f"{label}:snapshot:manifest".encode()
    raw_bytes = f"{label}:raw".encode()
    manifest_artifact["byte_size"] = len(manifest_bytes)
    raw_artifact = _artifact_values(
        f"{label}:raw",
        "pubmed_http_response",
        byte_size=len(raw_bytes),
        media_type="application/xml",
    )
    digest = raw_artifact["artifact_id"].removeprefix("sha256:")
    relative_path = f"pubmed/sha256/{digest[:2]}/{digest}.bin"
    raw_artifact["relative_storage_path"] = relative_path
    link_id = f"artifact-link:{_hash(f'{label}:link')}"
    link = ValidatedArtifactLink(
        link_id=link_id,
        acquisition_intent_id=snapshot["acquisition_intent_id"],
        ordinal=0,
        artifact_id=raw_artifact["artifact_id"],
        artifact_kind="pubmed_http_response",
        media_type="application/xml",
        content_encoding=None,
        http_status=200,
        byte_size=len(raw_bytes),
        body_complete=True,
        termination_reason="complete_response",
        observed_at_utc=NOW,
        schema_version="1.0",
    )
    manifest_file = ValidatedManifestFile(
        ordinal=0,
        link_id=link_id,
        artifact_id=raw_artifact["artifact_id"],
        relative_path=relative_path,
        byte_size=len(raw_bytes),
        media_type="application/xml",
        content_encoding=None,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    manifest = ValidatedManifest(
        manifest_id=snapshot["snapshot_id"],
        manifest_schema_version="1.0",
        retention_policy_id="M1A-LIVE-RETENTION-v1",
        source_type="pubmed",
        acquisition_intent_id=snapshot["acquisition_intent_id"],
        request_identity=snapshot["request_identity"],
        started_at_utc=snapshot["started_at_utc"],
        completed_at_utc=snapshot["completed_at_utc"],
        record_count=0,
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        files=(manifest_file,),
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        source_record_schema_version="1.0",
        code_revision=snapshot["code_revision"],
    )
    file_row = SnapshotFileRow(
        link_id=link.link_id,
        acquisition_intent_id=link.acquisition_intent_id,
        ordinal=0,
        raw_artifact_id=link.artifact_id,
        raw_artifact_kind="pubmed_http_response",
        raw_source_partition="pubmed",
        raw_content_hash=link.artifact_id,
        relative_storage_path=relative_path,
        byte_size=len(raw_bytes),
        media_type=link.media_type,
        content_encoding=None,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
        observed_at_utc=NOW,
        schema_version="1.0",
    )
    membership = {
        "snapshot_id": snapshot["snapshot_id"],
        "acquisition_intent_id": snapshot["acquisition_intent_id"],
        "ordinal": 0,
        "link_id": link.link_id,
    }
    lineage = {
        "parent_artifact_id": manifest_artifact["artifact_id"],
        "parent_artifact_kind": manifest_artifact["artifact_kind"],
        "parent_source_partition": manifest_artifact["source_partition"],
        "parent_content_hash": manifest_artifact["content_hash"],
        "child_artifact_id": raw_artifact["artifact_id"],
        "child_artifact_kind": raw_artifact["artifact_kind"],
        "child_source_partition": raw_artifact["source_partition"],
        "child_content_hash": raw_artifact["content_hash"],
        "lineage_type": "manifest_to_raw_response",
        "lineage_ordinal": 0,
        "schema_version": "1.0",
    }
    return AcquisitionRegistration(
        artifacts=(manifest_artifact, raw_artifact, envelope_artifact),
        snapshot=snapshot,
        files=(file_row,),
        memberships=(cast(repository_module.SourceSnapshotFileRow, membership),),
        warnings=(),
        publications=(),
        publication_memberships=(),
        lineage=(cast(repository_module.ArtifactLineageRow, lineage),),
        attempt=attempt,
        manifest=manifest,
        artifact_links=(link,),
        envelope=ValidatedAcquisitionEnvelope(
            attempt=attempt,
            publications=(),
            publication_memberships=(),
            lineage=(cast(repository_module.ArtifactLineageRow, lineage),),
        ),
        observations=observations,
    )


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _execute_case(
    engine: Engine,
    setup: Callable[[Connection], None],
    table: sa.Table,
    values: dict[str, object],
    expected_constraint: str | None,
) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            setup(connection)
            if expected_constraint is None:
                connection.execute(table.insert().values(**values))
            else:
                with pytest.raises(IntegrityError) as captured:
                    connection.execute(table.insert().values(**values))
                assert _constraint_name(captured.value) == expected_constraint
        finally:
            transaction.rollback()


@pytest.mark.parametrize("table_name", ("snapshot", "attempt"))
@pytest.mark.parametrize(
    "outcome",
    ALL_OUTCOMES,
    ids=lambda value: "-".join(value) if isinstance(value, tuple) else str(value),
)
def test_exact_seven_outcome_matrix(
    engine: Engine,
    table_name: str,
    outcome: tuple[str, str, str],
) -> None:
    label = f"outcome:{table_name}:{':'.join(outcome)}"
    expected = (
        None
        if outcome in VALID_OUTCOMES
        else (
            f"ck_{'source_snapshot' if table_name == 'snapshot' else 'run_attempt'}_counts"
            if outcome[1:] == ("unavailable", "matches")
            else f"ck_{'source_snapshot' if table_name == 'snapshot' else 'run_attempt'}_outcome"
        )
    )
    if table_name == "snapshot":
        manifest, snapshot = _snapshot_values(label, outcome)

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))

        _execute_case(engine, setup, models.source_snapshot, dict(snapshot), expected)
    else:
        manifest, envelope, snapshot, attempt = _attempt_values(label, outcome)

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))
            connection.execute(models.source_snapshot.insert().values(**snapshot))
            connection.execute(models.artifact.insert().values(**envelope))

        _execute_case(engine, setup, models.research_run_attempt, dict(attempt), expected)


COUNT_CASES = (
    (("succeeded", "complete", "matches"), 1, True),
    (("succeeded", "complete", "matches"), 100, True),
    (("succeeded", "complete", "matches"), 0, False),
    (("succeeded", "complete", "no_match"), 0, True),
    (("succeeded", "complete", "no_match"), 1, False),
    (("succeeded", "partial", "indeterminate"), 0, True),
    (("succeeded", "partial", "indeterminate"), 1, False),
    (("failed", "partial", "indeterminate"), 0, True),
    (("failed", "partial", "indeterminate"), 1, False),
    (("failed", "unavailable", "indeterminate"), 0, True),
    (("failed", "unavailable", "indeterminate"), 1, False),
)


@pytest.mark.parametrize("table_name", ("snapshot", "attempt"))
@pytest.mark.parametrize("outcome,count,accepted", COUNT_CASES)
def test_result_count_matrix(
    engine: Engine,
    table_name: str,
    outcome: tuple[str, str, str],
    count: int,
    accepted: bool,
) -> None:
    label = f"count:{table_name}:{':'.join(outcome)}:{count}:{accepted}"
    expected = (
        None
        if accepted
        else f"ck_{'source_snapshot' if table_name == 'snapshot' else 'run_attempt'}_counts"
    )
    if table_name == "snapshot":
        manifest, snapshot = _snapshot_values(label, outcome, count=count)

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))

        _execute_case(engine, setup, models.source_snapshot, dict(snapshot), expected)
    else:
        manifest, envelope, snapshot, attempt = _attempt_values(label, outcome, count=count)

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))
            connection.execute(models.source_snapshot.insert().values(**snapshot))
            connection.execute(models.artifact.insert().values(**envelope))

        _execute_case(engine, setup, models.research_run_attempt, dict(attempt), expected)


@pytest.mark.parametrize("table_name", ("snapshot", "attempt"))
@pytest.mark.parametrize(
    "outcome,pages,truncated",
    (
        (("failed", "unavailable", "indeterminate"), 1, False),
        (("succeeded", "complete", "no_match"), 0, False),
        (("succeeded", "complete", "no_match"), 1, True),
    ),
)
def test_completion_count_rules(
    engine: Engine,
    table_name: str,
    outcome: tuple[str, str, str],
    pages: int,
    truncated: bool,
) -> None:
    label = f"completion:{table_name}:{pages}:{truncated}:{outcome[1]}"
    expected = f"ck_{'source_snapshot' if table_name == 'snapshot' else 'run_attempt'}_counts"
    if table_name == "snapshot":
        manifest, snapshot = _snapshot_values(label, outcome, pages=pages, truncated=truncated)

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))

        _execute_case(engine, setup, models.source_snapshot, dict(snapshot), expected)
    else:
        manifest, envelope, snapshot, attempt = _attempt_values(
            label, outcome, pages=pages, truncated=truncated
        )

        def setup(connection: Connection) -> None:
            connection.execute(models.artifact.insert().values(**manifest))
            connection.execute(models.source_snapshot.insert().values(**snapshot))
            connection.execute(models.artifact.insert().values(**envelope))

        _execute_case(engine, setup, models.research_run_attempt, dict(attempt), expected)


@pytest.mark.parametrize("kind", tuple(ARTIFACT_SPECS))
@pytest.mark.parametrize("boundary", ("lower", "upper"))
def test_artifact_exact_pairs_media_and_bounds(
    engine: Engine,
    kind: str,
    boundary: str,
) -> None:
    partition, lower, upper, is_json = ARTIFACT_SPECS[kind]
    size = lower if boundary == "lower" else upper
    media_type = (
        "application/json"
        if is_json
        else ("application/xml" if boundary == "lower" else "application/octet-stream")
    )
    artifact = _artifact_values(
        f"artifact-positive:{kind}:{boundary}",
        kind,
        partition=partition,
        byte_size=size,
        media_type=media_type,
    )
    _execute_case(engine, lambda _: None, models.artifact, dict(artifact), None)


@pytest.mark.parametrize("kind", tuple(ARTIFACT_SPECS))
def test_artifact_rejects_cross_partition(engine: Engine, kind: str) -> None:
    partition, _, _, _ = ARTIFACT_SPECS[kind]
    wrong_partition = "global" if partition == "pubmed" else "pubmed"
    artifact = _artifact_values(f"artifact-partition:{kind}", kind, partition=wrong_partition)
    _execute_case(
        engine,
        lambda _: None,
        models.artifact,
        dict(artifact),
        "ck_artifact_kind_partition",
    )


@pytest.mark.parametrize(
    "kind",
    tuple(kind for kind, spec in ARTIFACT_SPECS.items() if spec[3]),
)
def test_json_artifacts_reject_non_json_media(engine: Engine, kind: str) -> None:
    artifact = _artifact_values(
        f"artifact-media:{kind}", kind, media_type="application/octet-stream"
    )
    _execute_case(
        engine,
        lambda _: None,
        models.artifact,
        dict(artifact),
        "ck_artifact_media_schema",
    )


@pytest.mark.parametrize("kind", tuple(ARTIFACT_SPECS))
def test_artifact_rejects_upper_bound_plus_one(engine: Engine, kind: str) -> None:
    _, _, upper, _ = ARTIFACT_SPECS[kind]
    artifact = _artifact_values(f"artifact-upper:{kind}", kind, byte_size=upper + 1)
    _execute_case(engine, lambda _: None, models.artifact, dict(artifact), "ck_artifact_size")


@pytest.mark.parametrize(
    "kind",
    tuple(kind for kind, spec in ARTIFACT_SPECS.items() if spec[1] == 1),
)
def test_json_artifacts_reject_zero_bytes(engine: Engine, kind: str) -> None:
    artifact = _artifact_values(f"artifact-zero:{kind}", kind, byte_size=0)
    _execute_case(engine, lambda _: None, models.artifact, dict(artifact), "ck_artifact_size")


@pytest.mark.parametrize(
    "mutation,expected_constraint",
    (
        ({"snapshot_id": _hash("wrong-snapshot-id")}, "ck_source_snapshot_identity"),
        (
            {"manifest_artifact_id": _hash("wrong-manifest-id")},
            "ck_source_snapshot_identity",
        ),
        (
            {"manifest_content_hash": _hash("wrong-manifest-hash")},
            "ck_source_snapshot_identity",
        ),
        ({"manifest_artifact_kind": "publication_record"}, "ck_source_snapshot_static_values"),
        ({"manifest_source_partition": "global"}, "ck_source_snapshot_static_values"),
    ),
)
def test_snapshot_manifest_identity_matrix(
    engine: Engine,
    mutation: dict[str, object],
    expected_constraint: str,
) -> None:
    manifest, snapshot = _snapshot_values(
        f"snapshot-identity:{next(iter(mutation))}",
        ("succeeded", "complete", "no_match"),
    )
    snapshot.update(cast(SourceSnapshotRow, mutation))

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**manifest))

    _execute_case(engine, setup, models.source_snapshot, dict(snapshot), expected_constraint)


@pytest.mark.parametrize(
    "mutation",
    (
        {"subject_artifact_kind": "publication_record"},
        {"subject_source_partition": "global"},
        {
            "subject_artifact_id": _hash("missing-composite-artifact"),
            "subject_content_hash": _hash("missing-composite-artifact"),
        },
    ),
)
def test_artifact_composite_fk_mismatches(
    engine: Engine,
    mutation: dict[str, object],
) -> None:
    artifact = _artifact_values("composite-fk-subject", "snapshot_manifest")
    event: dict[str, object] = {
        "event_kind": "content_mismatch",
        "subject_artifact_id": artifact["artifact_id"],
        "subject_artifact_kind": artifact["artifact_kind"],
        "subject_source_partition": artifact["source_partition"],
        "subject_content_hash": artifact["content_hash"],
        "expected_content_hash": artifact["content_hash"],
        "observed_content_hash": _hash("observed-composite"),
        "expected_byte_size": artifact["byte_size"],
        "observed_byte_size": artifact["byte_size"],
        "redacted_detail": "bounded mismatch",
        "observed_at_utc": NOW,
    }
    event.update(mutation)

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**artifact))

    _execute_case(
        engine,
        setup,
        models.artifact_integrity_event,
        event,
        "fk_integrity_event_artifact",
    )


def _publication_values(
    label: str, *, pmid: str = "12345678"
) -> tuple[ArtifactRow, dict[str, object]]:
    bounds = ExecutionBounds(
        max_query_characters=512,
        max_pages=1,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id=f"query:{label}",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=bounds,
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
    )
    provenance = Provenance(
        source=SourceType.PUBMED,
        source_record_id=pmid,
        query_id=outcome.query_id,
        source_lookup_key=f"pubmed:{pmid}",
        retrieved_at=NOW,
        connector_version="fixture-1.0",
        content_hash=_hash(f"{label}:raw-publication"),
        source_outcome=outcome,
        configured_bounds=bounds,
    )
    publication_status = PublicationStatus.create(
        status=PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        status_source="PubMed relationship metadata",
        notice_type=None,
        relationship=None,
        retrieved_as_of=NOW,
    )
    record = PublicationRecord.create(
        pmid=pmid,
        doi=None,
        pmcid=None,
        title="Synthetic publication",
        abstract_sections=(),
        authors=(),
        journal="Synthetic Journal",
        publication_types=(),
        publication_date=None,
        publication_status=publication_status,
        indexing_status=IndexingStatus.INDEXED,
        provenance=provenance,
    )
    payload = cast(dict[str, object], json.loads(canonical_json(record.version_payload())))
    raw = canonical_json(payload).encode()
    artifact = _artifact_values(canonical_json(payload), "publication_record", byte_size=len(raw))
    assert artifact["content_hash"] == record.content_hash
    publication: dict[str, object] = {
        "publication_version_id": record.publication_version_id,
        "source": "pubmed",
        "pmid": pmid,
        "content_hash": record.content_hash,
        "publication_status_identity": publication_status.publication_status_identity,
        "publication_status": publication_status.status.value,
        "status_retrieved_at_utc": NOW,
        "version_payload": payload,
        "publication_artifact_id": artifact["artifact_id"],
        "publication_artifact_kind": "publication_record",
        "publication_source_partition": "pubmed",
        "publication_artifact_hash": artifact["content_hash"],
        "schema_version": "1.0",
    }
    return artifact, publication


def test_publication_positive_identity_and_payload(engine: Engine) -> None:
    artifact, publication = _publication_values("publication-positive")

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**artifact))

    _execute_case(engine, setup, models.publication_version, publication, None)


def _rebind_publication_payload(
    publication: dict[str, object],
    payload: dict[str, object],
) -> PublicationVersionRow:
    content_hash = _hash(canonical_json(payload))
    pmid = cast(str, publication["pmid"])
    return cast(
        PublicationVersionRow,
        {
            **publication,
            "version_payload": payload,
            "content_hash": content_hash,
            "publication_artifact_id": content_hash,
            "publication_artifact_hash": content_hash,
            "publication_version_id": (
                f"pubmed:{pmid}:sha256:{content_hash.removeprefix('sha256:')}"
            ),
        },
    )


def test_repository_accepts_complete_domain_valid_publication_payload() -> None:
    _, publication = _publication_values("repository-domain-valid")

    PersistenceRepository._validate_publication(cast(PublicationVersionRow, publication))


@pytest.mark.parametrize(
    "dimension",
    (
        "language",
        "evidence_scope",
        "publication_types",
        "canonical_abstract",
        "status_warning_contract",
    ),
)
def test_repository_rejects_domain_invalid_publication_payload(dimension: str) -> None:
    _, publication = _publication_values(f"repository-domain-invalid:{dimension}")
    payload = cast(dict[str, object], deepcopy(publication["version_payload"]))
    if dimension == "language":
        payload["language"] = "eng"
    elif dimension == "evidence_scope":
        payload["evidence_scope"] = "synthetic"
    elif dimension == "publication_types":
        payload["publication_types"] = ["Review", "Article"]
    elif dimension == "canonical_abstract":
        payload["canonical_abstract"] = "Contradictory abstract"
        payload["canonical_abstract_sha256"] = _hash("Contradictory abstract")
    else:
        status = cast(dict[str, object], payload["publication_status"])
        status["warning_codes"] = []
    rebound = _rebind_publication_payload(publication, payload)

    with pytest.raises(ValueError, match="frozen domain contract"):
        PersistenceRepository._validate_publication(rebound)


@pytest.mark.parametrize(
    "mutation",
    (
        {"publication_version_id": "pubmed:999:sha256:" + "a" * 64},
        {"pmid": "999"},
        {"content_hash": _hash("wrong-publication-content")},
        {"publication_artifact_id": _hash("wrong-publication-artifact")},
        {"publication_artifact_hash": _hash("wrong-publication-hash")},
        {"publication_artifact_kind": "snapshot_manifest"},
        {"publication_source_partition": "global"},
    ),
)
def test_publication_artifact_identity_matrix(
    engine: Engine,
    mutation: dict[str, object],
) -> None:
    artifact, publication = _publication_values(f"publication-identity:{next(iter(mutation))}")
    publication.update(mutation)

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**artifact))

    _execute_case(
        engine,
        setup,
        models.publication_version,
        publication,
        "ck_publication_version_identity",
    )


@pytest.mark.parametrize(
    "case,value",
    (
        ("invalid-calendar", "2026-02-30T14:00:00.000000Z"),
        ("arbitrary-text", "not-a-timestamp"),
        ("json-number", 20260807),
        ("json-null", None),
        ("offset", "2026-08-07T09:00:00.000000-05:00"),
        ("wrong-precision", "2026-08-07T14:00:00.000Z"),
        ("unequal-valid", "2026-08-07T14:00:01.000000Z"),
        ("missing", "unused"),
    ),
)
def test_safe_malformed_publication_timestamps_are_named_check_violations(
    engine: Engine,
    case: str,
    value: object,
) -> None:
    artifact, publication = _publication_values(f"publication-time:{case}")
    payload = cast(dict[str, object], deepcopy(publication["version_payload"]))
    status = cast(dict[str, object], payload["publication_status"])
    if case == "missing":
        del status["retrieved_as_of"]
    else:
        status["retrieved_as_of"] = value
    publication["version_payload"] = payload

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**artifact))

    _execute_case(
        engine,
        setup,
        models.publication_version,
        publication,
        "ck_publication_version_payload",
    )


EXPECTED_ARTIFACT_PAIRS = tuple((kind, spec[0]) for kind, spec in ARTIFACT_SPECS.items())


def _observation_values(
    label: str,
    kind: str,
    *,
    path: str | None = None,
    path_hash: str | None = None,
    expected_pair: tuple[str, str] = ("snapshot_manifest", "pubmed"),
) -> dict[str, object]:
    observed_path = f"observations/{label}.json" if path is None else path
    observed_path_hash = (
        _hash(observed_path) if path_hash is None and observed_path is not None else path_hash
    )
    expected_hash = _hash(f"{label}:expected")
    observed_hash = _hash(f"{label}:observed")
    values: dict[str, object] = {
        "observation_kind": kind,
        "source_partition": "pubmed",
        "run_id": None,
        "attempt_id": None,
        "observed_relative_path": observed_path,
        "observed_relative_path_hash": observed_path_hash,
        "expected_artifact_id": None,
        "expected_artifact_kind": None,
        "expected_source_partition": None,
        "expected_content_hash": None,
        "expected_envelope_id": None,
        "observed_artifact_id": None,
        "observed_envelope_id": None,
        "observed_content_hash": None,
        "expected_byte_size": None,
        "observed_byte_size": None,
        "redacted_detail": f"bounded {label}",
        "observed_at_utc": NOW,
    }
    if kind == "missing_expected_artifact":
        values.update(
            expected_artifact_id=expected_hash,
            expected_artifact_kind=expected_pair[0],
            expected_source_partition=expected_pair[1],
            expected_content_hash=expected_hash,
            expected_byte_size=1,
        )
    elif kind == "corrupt_content":
        values.update(
            expected_artifact_id=expected_hash,
            expected_artifact_kind=expected_pair[0],
            expected_source_partition=expected_pair[1],
            expected_content_hash=expected_hash,
            expected_byte_size=1,
            observed_artifact_id=observed_hash,
            observed_content_hash=observed_hash,
            observed_byte_size=2,
        )
    elif kind == "unregistered_orphan":
        values.update(observed_content_hash=observed_hash, observed_byte_size=1)
    return values


@pytest.mark.parametrize(
    "kind",
    (
        "missing_expected_artifact",
        "corrupt_content",
        "invalid_envelope",
        "unregistered_orphan",
    ),
)
def test_all_four_registration_shapes_accept_populated_path(
    engine: Engine,
    kind: str,
) -> None:
    values = _observation_values(f"shape-positive-{kind}", kind)
    _execute_case(engine, lambda _: None, models.registration_observation, values, None)


@pytest.mark.parametrize(
    "kind",
    (
        "missing_expected_artifact",
        "corrupt_content",
        "invalid_envelope",
        "unregistered_orphan",
    ),
)
def test_all_four_registration_shapes_reject_null_path_pair(
    engine: Engine,
    kind: str,
) -> None:
    values = _observation_values(f"shape-null-{kind}", kind)
    values["observed_relative_path"] = None
    values["observed_relative_path_hash"] = None
    _execute_case(
        engine,
        lambda _: None,
        models.registration_observation,
        values,
        "ck_registration_observation_shape",
    )


@pytest.mark.parametrize(
    "path",
    ("unicode/药物.json", "x" * 1024),
)
def test_registration_path_positive_boundaries(engine: Engine, path: str) -> None:
    values = _observation_values(
        f"path-positive-{len(path)}", "invalid_envelope", path=path, path_hash=_hash(path)
    )
    _execute_case(engine, lambda _: None, models.registration_observation, values, None)


@pytest.mark.parametrize(
    "path,path_hash",
    (
        ("present/path.json", None),
        (None, _hash("missing-path")),
        ("", _hash("")),
        ("/absolute.json", _hash("/absolute.json")),
        ("windows\\path.json", _hash("windows\\path.json")),
        (".", _hash(".")),
        ("..", _hash("..")),
        ("a/./b", _hash("a/./b")),
        ("a/../b", _hash("a/../b")),
        ("valid/path.json", "not-a-hash"),
    ),
)
def test_registration_path_hash_negative_matrix(
    engine: Engine,
    path: str | None,
    path_hash: str | None,
) -> None:
    values = _observation_values("path-negative", "invalid_envelope")
    values["observed_relative_path"] = path
    values["observed_relative_path_hash"] = path_hash
    _execute_case(
        engine,
        lambda _: None,
        models.registration_observation,
        values,
        "ck_registration_observation_path",
    )


def test_registration_rejects_path_beyond_storage_bound(engine: Engine) -> None:
    path = "x" * 1025
    values = _observation_values("path-storage-bound", "invalid_envelope")
    values["observed_relative_path"] = path
    values["observed_relative_path_hash"] = _hash(path)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            with pytest.raises(sa.exc.DataError):
                connection.execute(models.registration_observation.insert().values(**values))
        finally:
            transaction.rollback()


@pytest.mark.parametrize("expected_pair", EXPECTED_ARTIFACT_PAIRS)
def test_registration_accepts_all_six_expected_pairs(
    engine: Engine,
    expected_pair: tuple[str, str],
) -> None:
    values = _observation_values(
        f"expected-positive-{expected_pair[0]}",
        "missing_expected_artifact",
        expected_pair=expected_pair,
    )
    _execute_case(engine, lambda _: None, models.registration_observation, values, None)


@pytest.mark.parametrize("expected_pair", EXPECTED_ARTIFACT_PAIRS)
def test_registration_rejects_all_six_cross_partition_expected_pairs(
    engine: Engine,
    expected_pair: tuple[str, str],
) -> None:
    wrong = "global" if expected_pair[1] == "pubmed" else "pubmed"
    values = _observation_values(
        f"expected-negative-{expected_pair[0]}",
        "missing_expected_artifact",
        expected_pair=(expected_pair[0], wrong),
    )
    _execute_case(
        engine,
        lambda _: None,
        models.registration_observation,
        values,
        "ck_registration_observation_expected_binding",
    )


@pytest.mark.parametrize("mask", tuple(range(1, 15)))
def test_registration_rejects_fourteen_partial_expected_bindings(
    engine: Engine,
    mask: int,
) -> None:
    values = _observation_values("expected-partial", "missing_expected_artifact")
    columns = (
        "expected_artifact_id",
        "expected_content_hash",
        "expected_artifact_kind",
        "expected_source_partition",
    )
    for bit, column in enumerate(columns):
        if not mask & (1 << bit):
            values[column] = None
    _execute_case(
        engine,
        lambda _: None,
        models.registration_observation,
        values,
        "ck_registration_observation_expected_binding",
    )


def test_registration_rejects_expected_id_hash_mismatch(engine: Engine) -> None:
    values = _observation_values("expected-hash-mismatch", "missing_expected_artifact")
    values["expected_content_hash"] = _hash("different-expected-content")
    _execute_case(
        engine,
        lambda _: None,
        models.registration_observation,
        values,
        "ck_registration_observation_expected_binding",
    )


@pytest.mark.parametrize(
    "mutation,expected_constraint",
    (
        ({}, None),
        ({"pmid": "87654321"}, "ck_snapshot_publication_identity"),
        (
            {"publication_version_id": "pubmed:12345678:sha256:" + "0" * 64},
            "ck_snapshot_publication_identity",
        ),
        (
            {"publication_content_hash": _hash("wrong-association")},
            "ck_snapshot_publication_identity",
        ),
        ({"source": "global"}, "ck_snapshot_publication_identity"),
    ),
)
def test_snapshot_publication_association_identity(
    engine: Engine,
    mutation: dict[str, object],
    expected_constraint: str | None,
) -> None:
    manifest, snapshot = _snapshot_values(
        f"association:{next(iter(mutation), 'valid')}",
        ("succeeded", "complete", "no_match"),
    )
    publication_artifact, publication = _publication_values(
        f"association-publication:{next(iter(mutation), 'valid')}"
    )
    association: dict[str, object] = {
        "snapshot_id": snapshot["snapshot_id"],
        "publication_ordinal": 0,
        "pmid": publication["pmid"],
        "publication_version_id": publication["publication_version_id"],
        "source": publication["source"],
        "publication_content_hash": publication["content_hash"],
    }
    association.update(mutation)

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**manifest))
        connection.execute(models.source_snapshot.insert().values(**snapshot))
        connection.execute(models.artifact.insert().values(**publication_artifact))
        connection.execute(models.publication_version.insert().values(**publication))

    _execute_case(
        engine,
        setup,
        models.source_snapshot_publication,
        association,
        expected_constraint,
    )


def _run_report_values(
    label: str,
) -> tuple[ArtifactRow, ArtifactRow, dict[str, object], dict[str, object]]:
    envelope = _artifact_values(f"{label}:run-envelope", "run_registration_envelope")
    report_artifact = _artifact_values(f"{label}:report-artifact", "research_report")
    run_id = f"run:{_uuid4(f'{label}:run')}"
    report_id = f"report:{_hash(f'{label}:report')}"
    run: dict[str, object] = {
        "run_id": run_id,
        "run_intent_id": f"run-intent:{_hash(f'{label}:intent')}",
        "request_id": f"request:{_uuid4(f'{label}:request')}",
        "created_at_utc": NOW,
        "code_revision": "b" * 40,
        "scope_id": f"scope:{_hash(f'{label}:scope')}",
        "execution_profile_id": "M1A_CONSTRAINED_V1",
        "catalog_version": "m1a-concepts-v1",
        "catalog_content_hash": (
            "sha256:eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e"
        ),
        "source": "pubmed",
        "drug_concept_ids": ["drug:synthetic"],
        "adverse_event_concept_ids": ["event:synthetic"],
        "start_date": None,
        "end_date": None,
        "pubmed_query": "synthetic bounded query",
        "started_at_utc": NOW,
        "completed_at_utc": NOW,
        "run_status": "completed",
        "coverage_status": "complete",
        "result_status": "no_match",
        "registration_envelope_id": f"registration-envelope:run:{_hash(f'{label}:registration')}",
        "envelope_artifact_id": envelope["artifact_id"],
        "envelope_artifact_kind": "run_registration_envelope",
        "envelope_source_partition": "global",
        "envelope_content_hash": envelope["content_hash"],
        "report_id": report_id,
        "warning_codes": [],
    }
    report: dict[str, object] = {
        "report_id": report_id,
        "run_id": run_id,
        "report_status": "draft",
        "report_artifact_id": report_artifact["artifact_id"],
        "report_artifact_kind": "research_report",
        "report_source_partition": "global",
        "report_content_hash": report_artifact["content_hash"],
        "report_byte_size": report_artifact["byte_size"],
        "report_media_type": "application/json",
        "created_at_utc": NOW,
        "schema_version": "1.0",
        "coverage_status": "complete",
        "result_status": "no_match",
    }
    return envelope, report_artifact, run, report


def test_exact_catalog_binding_and_one_character_mutation(engine: Engine) -> None:
    envelope, report_artifact, run, _ = _run_report_values("catalog-mutation")
    run["catalog_content_hash"] = (
        "sha256:0affc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e"
    )

    def setup(connection: Connection) -> None:
        connection.execute(models.artifact.insert().values(**envelope))
        connection.execute(models.artifact.insert().values(**report_artifact))

    _execute_case(
        engine,
        setup,
        models.research_run,
        run,
        "ck_research_run_static",
    )


def test_deferred_run_report_closure_is_checked_at_commit(engine: Engine) -> None:
    envelope, report_artifact, run, report = _run_report_values("deferred-missing")
    with pytest.raises(IntegrityError) as captured, engine.begin() as connection:
        connection.execute(models.artifact.insert().values(**envelope))
        connection.execute(models.artifact.insert().values(**report_artifact))
        connection.execute(models.research_run.insert().values(**run))
    assert _constraint_name(captured.value) == "fk_research_run_report"

    envelope, report_artifact, run, report = _run_report_values("deferred-complete")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(models.artifact.insert().values(**envelope))
            connection.execute(models.artifact.insert().values(**report_artifact))
            connection.execute(models.research_run.insert().values(**run))
            connection.execute(models.research_report.insert().values(**report))
            connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
        finally:
            transaction.rollback()


def test_repository_logs_redact_paths_details_and_database_url(
    repository: PersistenceRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_path_fragment = "private-sensitive-path"
    secret_detail = "private sensitive diagnostic detail"
    observation = _observation(
        secret_detail,
        identity=secret_path_fragment,
    )
    persistence_logger = logging.getLogger("medevidence.persistence.repositories")
    persistence_logger.disabled = False
    caplog.set_level(logging.INFO, logger=persistence_logger.name)

    repository.insert_or_verify_registration_observation(observation)

    settings = PersistenceSettings.from_env()
    assert secret_path_fragment not in caplog.text
    assert secret_detail not in caplog.text
    assert settings.database_url not in caplog.text
    record = caplog.records[-1]
    assert cast(str, record.identity).startswith("sha256:")
    assert record.outcome == "inserted"


class _VerifiedReplayPort:
    def __init__(self, label: str, replay: ValidatedReplay) -> None:
        self._label = label
        self._replay = replay

    def load_verified_snapshot(
        self,
        *,
        manifest_relative_path: str,
        expected_manifest_id: str,
    ) -> ValidatedReplay:
        manifest_bytes = f"{self._label}:snapshot:manifest".encode()
        assert _hash(manifest_bytes.decode()) == expected_manifest_id
        assert manifest_relative_path == next(
            row["relative_storage_path"]
            for row in _complete_acquisition_registration(self._label).artifacts
            if row["artifact_kind"] == "snapshot_manifest"
        )
        for link, item in zip(
            self._replay.artifact_links, self._replay.manifest.files, strict=True
        ):
            raw = f"{self._label}:raw".encode()
            assert _hash(raw.decode()) == link.artifact_id == item.artifact_id
            assert len(raw) == link.byte_size == item.byte_size
        return self._replay


@pytest.mark.parametrize(
    "dimension",
    (
        "persisted_file",
        "artifact_link",
        "membership",
        "warning",
        "envelope_attempt",
        "publication",
        "lineage",
        "artifact_set",
    ),
)
def test_complete_acquisition_pre_sql_mutation_matrix(dimension: str) -> None:
    registration = _complete_acquisition_registration(f"pre-sql-{dimension}")
    if dimension == "persisted_file":
        registration = replace(
            registration,
            files=(
                SnapshotFileRow(
                    **{
                        **registration.files[0],
                        "http_status": 500,
                    }
                ),
            ),
        )
    elif dimension == "artifact_link":
        registration = replace(
            registration,
            artifact_links=(replace(registration.artifact_links[0], http_status=500),),
        )
    elif dimension == "membership":
        registration = replace(
            registration,
            memberships=(
                cast(
                    repository_module.SourceSnapshotFileRow,
                    {**registration.memberships[0], "ordinal": 1},
                ),
            ),
        )
    elif dimension == "warning":
        registration = replace(
            registration,
            warnings=(
                cast(
                    repository_module.SnapshotWarningRow,
                    {
                        "snapshot_id": registration.snapshot["snapshot_id"],
                        "warning_ordinal": 0,
                        "warning_code": "mutated",
                    },
                ),
            ),
        )
    elif dimension == "envelope_attempt":
        registration = replace(
            registration,
            envelope=replace(
                registration.envelope,
                attempt=ResearchRunAttemptRow(
                    **{
                        **registration.attempt,
                        "intent_created_at_utc": datetime(2026, 8, 7, 14, 59, tzinfo=UTC),
                    }
                ),
            ),
        )
    elif dimension == "publication":
        _, publication = _publication_values("pre-sql-publication-mutation")
        registration = replace(
            registration,
            envelope=replace(
                registration.envelope,
                publications=(cast(PublicationVersionRow, publication),),
            ),
        )
    elif dimension == "lineage":
        registration = replace(
            registration,
            envelope=replace(registration.envelope, lineage=()),
        )
    elif dimension == "artifact_set":
        registration = replace(
            registration,
            artifacts=(
                *registration.artifacts,
                _artifact_values("pre-sql-extra", "snapshot_manifest"),
            ),
        )

    with pytest.raises(ValueError):
        PersistenceRepository._validate_acquisition(registration)


def test_complete_no_match_rejects_mutually_coherent_publication_graph() -> None:
    registration = _complete_acquisition_registration("coherent-no-match-publication")
    publication_artifact, publication_values = _publication_values("coherent-no-match-publication")
    publication = cast(PublicationVersionRow, publication_values)
    membership = cast(
        repository_module.SourceSnapshotPublicationRow,
        {
            "snapshot_id": registration.snapshot["snapshot_id"],
            "publication_ordinal": 0,
            "pmid": publication["pmid"],
            "publication_version_id": publication["publication_version_id"],
            "source": publication["source"],
            "publication_content_hash": publication["content_hash"],
        },
    )
    registration = replace(
        registration,
        artifacts=(*registration.artifacts, publication_artifact),
        publications=(publication,),
        publication_memberships=(membership,),
        envelope=replace(
            registration.envelope,
            publications=(publication,),
            publication_memberships=(membership,),
        ),
    )

    with pytest.raises(ValueError, match="search acquisition"):
        PersistenceRepository._validate_acquisition(registration)


def test_complete_rejects_mutually_coherent_non_effective_terminal_response() -> None:
    registration = _complete_acquisition_registration("coherent-http-500")
    link = replace(
        registration.artifact_links[0],
        http_status=500,
        body_complete=False,
        termination_reason="stream_error",
    )
    manifest_file = replace(
        registration.manifest.files[0],
        http_status=500,
        body_complete=False,
        termination_reason="stream_error",
    )
    file_row = SnapshotFileRow(
        **{
            **registration.files[0],
            "http_status": 500,
            "body_complete": False,
            "termination_reason": "stream_error",
        }
    )
    registration = replace(
        registration,
        manifest=replace(registration.manifest, files=(manifest_file,)),
        artifact_links=(link,),
        files=(file_row,),
    )

    with pytest.raises(ValueError, match="terminal nonempty complete 2xx"):
        PersistenceRepository._validate_acquisition(registration)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("byte_size", 1),
        ("media_type", "text/plain"),
        ("relative_storage_path", "pubmed/other-valid.bin"),
    ),
)
def test_complete_rejects_raw_artifact_metadata_mismatch(column: str, value: object) -> None:
    registration = _complete_acquisition_registration(f"raw-metadata-{column}")
    raw = next(
        artifact
        for artifact in registration.artifacts
        if artifact["artifact_kind"] == "pubmed_http_response"
    )
    changed = ArtifactRow(**{**raw, column: value})
    registration = replace(
        registration,
        artifacts=tuple(changed if row is raw else row for row in registration.artifacts),
    )

    with pytest.raises(ValueError, match="artifact metadata"):
        PersistenceRepository._validate_acquisition(registration)


def test_run_report_rejects_missing_or_unowned_lineage() -> None:
    envelope, report_artifact, run, report = _run_report_values("run-lineage-negative")
    edge = ArtifactLineageRow(
        parent_artifact_id=envelope["artifact_id"],
        parent_artifact_kind=envelope["artifact_kind"],
        parent_source_partition=envelope["source_partition"],
        parent_content_hash=envelope["content_hash"],
        child_artifact_id=report_artifact["artifact_id"],
        child_artifact_kind=report_artifact["artifact_kind"],
        child_source_partition=report_artifact["source_partition"],
        child_content_hash=report_artifact["content_hash"],
        lineage_type="run_envelope_to_report",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    registration = RunReportRegistration(
        artifacts=(envelope, report_artifact),
        run=cast(ResearchRunRow, run),
        report=cast(ResearchReportRow, report),
        lineage=(edge,),
        acquisition_references=((0, f"registration-envelope:acquisition:{_hash('static')}"),),
    )
    PersistenceRepository._validate_run_and_report(registration)

    with pytest.raises(ValueError, match="lineage types"):
        PersistenceRepository._validate_run_and_report(replace(registration, lineage=()))
    with pytest.raises(ValueError, match="envelope/report lineage"):
        PersistenceRepository._validate_run_and_report(
            replace(
                registration,
                lineage=(
                    ArtifactLineageRow(**{**edge, "child_artifact_id": _hash("unowned-report")}),
                ),
            )
        )

    publication_artifact, _publication = _publication_values("run-lineage-positive")
    publication_edge = ArtifactLineageRow(
        parent_artifact_id=report_artifact["artifact_id"],
        parent_artifact_kind=report_artifact["artifact_kind"],
        parent_source_partition=report_artifact["source_partition"],
        parent_content_hash=report_artifact["content_hash"],
        child_artifact_id=publication_artifact["artifact_id"],
        child_artifact_kind=publication_artifact["artifact_kind"],
        child_source_partition=publication_artifact["source_partition"],
        child_content_hash=publication_artifact["content_hash"],
        lineage_type="report_to_publication",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    PersistenceRepository._validate_run_and_report(
        replace(
            registration,
            run=cast(ResearchRunRow, {**run, "result_status": "matches"}),
            report=cast(ResearchReportRow, {**report, "result_status": "matches"}),
            lineage=(edge, publication_edge),
        )
    )


class _RollbackEngine:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        connection = self._engine.connect()
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
            connection.close()


def _acquisition_for_run(
    label: str,
    run_id: str,
    *,
    ordinal: int = 0,
    publication: tuple[ArtifactRow, PublicationVersionRow] | None = None,
) -> AcquisitionRegistration:
    registration = _complete_acquisition_registration(label)
    effective_ordinal = 1 if publication is not None and ordinal == 0 else ordinal
    attempt = ResearchRunAttemptRow(
        **{
            **registration.attempt,
            "run_id": run_id,
            "acquisition_ordinal": effective_ordinal,
            "operation": "search" if effective_ordinal == 0 else "fetch",
        }
    )
    if publication is None:
        return replace(
            registration,
            attempt=attempt,
            envelope=replace(registration.envelope, attempt=attempt),
        )

    publication_artifact, publication_row = publication
    snapshot = SourceSnapshotRow(
        **{
            **registration.snapshot,
            "record_count": 1,
            "result_status": "matches",
        }
    )
    attempt = ResearchRunAttemptRow(
        **{
            **attempt,
            "valid_result_count": 1,
            "result_status": "matches",
        }
    )
    manifest = replace(registration.manifest, record_count=1, result_status="matches")
    membership = cast(
        repository_module.SourceSnapshotPublicationRow,
        {
            "snapshot_id": snapshot["snapshot_id"],
            "publication_ordinal": 0,
            "pmid": publication_row["pmid"],
            "publication_version_id": publication_row["publication_version_id"],
            "source": publication_row["source"],
            "publication_content_hash": publication_row["content_hash"],
        },
    )
    return replace(
        registration,
        artifacts=(*registration.artifacts, publication_artifact),
        snapshot=snapshot,
        publications=(publication_row,),
        publication_memberships=(membership,),
        attempt=attempt,
        manifest=manifest,
        envelope=replace(
            registration.envelope,
            attempt=attempt,
            publications=(publication_row,),
            publication_memberships=(membership,),
        ),
    )


def _with_acquisition_outcome(
    registration: AcquisitionRegistration,
    *,
    operation: str,
    execution_status: str,
    coverage_status: str,
    result_status: str,
    record_count: int,
    pages_completed: int,
) -> AcquisitionRegistration:
    snapshot = SourceSnapshotRow(
        **{
            **registration.snapshot,
            "execution_status": execution_status,
            "coverage_status": coverage_status,
            "result_status": result_status,
            "record_count": record_count,
            "pages_completed": pages_completed,
        }
    )
    attempt = ResearchRunAttemptRow(
        **{
            **registration.attempt,
            "operation": operation,
            "execution_status": execution_status,
            "coverage_status": coverage_status,
            "result_status": result_status,
            "valid_result_count": record_count,
            "pages_completed": pages_completed,
        }
    )
    manifest = replace(
        registration.manifest,
        execution_status=execution_status,
        coverage_status=coverage_status,
        result_status=result_status,
        record_count=record_count,
        pages_completed=pages_completed,
    )
    return replace(
        registration,
        snapshot=snapshot,
        attempt=attempt,
        manifest=manifest,
        envelope=replace(registration.envelope, attempt=attempt),
    )


@pytest.mark.parametrize(
    "coverage_status,record_count",
    (("complete", 2), ("partial", 2)),
)
def test_search_matches_accept_identifier_count_without_publications(
    repository: PersistenceRepository,
    coverage_status: str,
    record_count: int,
) -> None:
    label = f"operation-search-{coverage_status}-matches"
    registration = _with_acquisition_outcome(
        _complete_acquisition_registration(label),
        operation="search",
        execution_status="succeeded",
        coverage_status=coverage_status,
        result_status="matches",
        record_count=record_count,
        pages_completed=1,
    )

    assert repository.register_acquisition(registration) == registration.snapshot
    stored = repository.get_snapshot(registration.snapshot["snapshot_id"])
    assert stored is not None
    assert stored.snapshot["record_count"] == record_count
    assert stored.publications == stored.publication_memberships == ()


def test_search_complete_no_match_accepts_zero_publications(
    repository: PersistenceRepository,
) -> None:
    registration = _complete_acquisition_registration("operation-search-complete-no-match")

    assert repository.register_acquisition(registration) == registration.snapshot
    stored = repository.get_snapshot(registration.snapshot["snapshot_id"])
    assert stored is not None
    assert stored.snapshot["record_count"] == 0
    assert stored.publications == stored.publication_memberships == ()


def test_search_rejects_publication_row() -> None:
    label = "operation-search-publication-row"
    artifact, values = _publication_values(label)
    registration = _acquisition_for_run(
        label,
        f"run:{_uuid4(label)}",
        publication=(artifact, cast(PublicationVersionRow, values)),
    )
    attempt = ResearchRunAttemptRow(
        **{
            **registration.attempt,
            "acquisition_ordinal": 0,
            "operation": "search",
        }
    )
    registration = replace(
        registration,
        attempt=attempt,
        envelope=replace(registration.envelope, attempt=attempt),
    )

    with pytest.raises(ValueError, match="search acquisition"):
        PersistenceRepository._validate_acquisition(registration)


def test_search_rejects_publication_membership() -> None:
    label = "operation-search-publication-membership"
    _, values = _publication_values(label)
    registration = _with_acquisition_outcome(
        _complete_acquisition_registration(label),
        operation="search",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=1,
        pages_completed=1,
    )
    membership = cast(
        repository_module.SourceSnapshotPublicationRow,
        {
            "snapshot_id": registration.snapshot["snapshot_id"],
            "publication_ordinal": 0,
            "pmid": values["pmid"],
            "publication_version_id": values["publication_version_id"],
            "source": values["source"],
            "publication_content_hash": values["content_hash"],
        },
    )
    registration = replace(
        registration,
        publication_memberships=(membership,),
        envelope=replace(registration.envelope, publication_memberships=(membership,)),
    )

    with pytest.raises(ValueError):
        PersistenceRepository._validate_acquisition(registration)


def test_search_rejects_publication_lineage() -> None:
    label = "operation-search-publication-lineage"
    registration = _with_acquisition_outcome(
        _complete_acquisition_registration(label),
        operation="search",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=1,
        pages_completed=1,
    )
    edge = ArtifactLineageRow(
        parent_artifact_id=_hash(f"{label}:publication"),
        parent_artifact_kind="publication_record",
        parent_source_partition="pubmed",
        parent_content_hash=_hash(f"{label}:publication"),
        child_artifact_id=registration.snapshot["snapshot_id"],
        child_artifact_kind="snapshot_manifest",
        child_source_partition="pubmed",
        child_content_hash=registration.snapshot["snapshot_id"],
        lineage_type="publication_to_manifest",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    registration = replace(
        registration,
        lineage=(*registration.lineage, edge),
        envelope=replace(registration.envelope, lineage=(*registration.lineage, edge)),
    )

    with pytest.raises(ValueError, match="search acquisition"):
        PersistenceRepository._validate_acquisition(registration)


def test_search_rejects_manifest_snapshot_attempt_count_mismatch() -> None:
    registration = _with_acquisition_outcome(
        _complete_acquisition_registration("operation-search-count-mismatch"),
        operation="search",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=2,
        pages_completed=1,
    )
    attempt = ResearchRunAttemptRow(**{**registration.attempt, "valid_result_count": 1})
    registration = replace(
        registration,
        attempt=attempt,
        envelope=replace(registration.envelope, attempt=attempt),
    )

    with pytest.raises(ValueError, match="record count"):
        PersistenceRepository._validate_acquisition(registration)


def test_fetch_matches_accepts_one_publication_and_membership(
    repository: PersistenceRepository,
) -> None:
    label = "operation-fetch-one-publication"
    artifact, values = _publication_values(label)
    registration = _acquisition_for_run(
        label,
        f"run:{_uuid4(label)}",
        ordinal=1,
        publication=(artifact, cast(PublicationVersionRow, values)),
    )

    assert repository.register_acquisition(registration) == registration.snapshot
    stored = repository.get_snapshot(registration.snapshot["snapshot_id"])
    assert stored is not None
    assert len(stored.publications) == len(stored.publication_memberships) == 1


def test_fetch_matches_rejects_zero_publications() -> None:
    label = "operation-fetch-zero-publications"
    registration = _with_acquisition_outcome(
        _acquisition_for_run(label, f"run:{_uuid4(label)}", ordinal=1),
        operation="fetch",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=1,
        pages_completed=1,
    )

    with pytest.raises(ValueError, match="fetch publication cardinality"):
        PersistenceRepository._validate_acquisition(registration)


def test_fetch_matches_rejects_more_than_one_publication() -> None:
    label = "operation-fetch-two-publications"
    first_artifact, first_values = _publication_values(f"{label}:first", pmid="1")
    second_artifact, second_values = _publication_values(f"{label}:second", pmid="2")
    registration = _acquisition_for_run(
        label,
        f"run:{_uuid4(label)}",
        ordinal=1,
        publication=(first_artifact, cast(PublicationVersionRow, first_values)),
    )
    second = cast(PublicationVersionRow, second_values)
    second_membership = cast(
        repository_module.SourceSnapshotPublicationRow,
        {
            "snapshot_id": registration.snapshot["snapshot_id"],
            "publication_ordinal": 1,
            "pmid": second["pmid"],
            "publication_version_id": second["publication_version_id"],
            "source": second["source"],
            "publication_content_hash": second["content_hash"],
        },
    )
    registration = _with_acquisition_outcome(
        replace(
            registration,
            artifacts=(*registration.artifacts, second_artifact),
            publications=(*registration.publications, second),
            publication_memberships=(
                *registration.publication_memberships,
                second_membership,
            ),
            envelope=replace(
                registration.envelope,
                publications=(*registration.publications, second),
                publication_memberships=(
                    *registration.publication_memberships,
                    second_membership,
                ),
            ),
        ),
        operation="fetch",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=2,
        pages_completed=1,
    )

    with pytest.raises(ValueError, match="fetch publication cardinality"):
        PersistenceRepository._validate_acquisition(registration)


def test_fetch_rejects_publication_count_differing_from_manifest() -> None:
    label = "operation-fetch-publication-manifest-mismatch"
    artifact, values = _publication_values(label)
    registration = _with_acquisition_outcome(
        _acquisition_for_run(
            label,
            f"run:{_uuid4(label)}",
            ordinal=1,
            publication=(artifact, cast(PublicationVersionRow, values)),
        ),
        operation="fetch",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        record_count=0,
        pages_completed=1,
    )

    with pytest.raises(ValueError, match="fetch publication cardinality"):
        PersistenceRepository._validate_acquisition(registration)


@pytest.mark.parametrize(
    "coverage_status,result_status",
    (("complete", "no_match"), ("partial", "indeterminate")),
)
def test_fetch_nonmatch_accepts_zero_publications(
    repository: PersistenceRepository,
    coverage_status: str,
    result_status: str,
) -> None:
    label = f"operation-fetch-{coverage_status}-{result_status}"
    registration = _with_acquisition_outcome(
        _acquisition_for_run(label, f"run:{_uuid4(label)}", ordinal=1),
        operation="fetch",
        execution_status="succeeded",
        coverage_status=coverage_status,
        result_status=result_status,
        record_count=0,
        pages_completed=1,
    )

    assert repository.register_acquisition(registration) == registration.snapshot


def test_fetch_nonmatch_rejects_publication_row() -> None:
    label = "operation-fetch-nonmatch-publication"
    artifact, values = _publication_values(label)
    registration = _with_acquisition_outcome(
        _acquisition_for_run(
            label,
            f"run:{_uuid4(label)}",
            ordinal=1,
            publication=(artifact, cast(PublicationVersionRow, values)),
        ),
        operation="fetch",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        record_count=0,
        pages_completed=1,
    )

    with pytest.raises(ValueError, match="fetch publication cardinality"):
        PersistenceRepository._validate_acquisition(registration)


def test_matching_search_replay_accepts_positive_count_without_publications(
    repository: PersistenceRepository,
) -> None:
    label = "operation-search-positive-replay"
    registration = _with_acquisition_outcome(
        _complete_acquisition_registration(label),
        operation="search",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="matches",
        record_count=2,
        pages_completed=1,
    )
    repository.register_acquisition(registration)
    replay = ValidatedReplay(
        manifest=registration.manifest,
        artifact_links=registration.artifact_links,
        publications=(),
        publication_memberships=(),
        lineage=registration.lineage,
        attempt=registration.attempt,
    )

    loaded = repository.load_snapshot_for_replay(
        registration.snapshot["snapshot_id"],
        replay_port=_VerifiedReplayPort(label, replay),
    )
    assert loaded.replay.manifest.record_count == 2
    assert loaded.replay.publications == loaded.replay.publication_memberships == ()


def _final_registration(
    label: str,
    acquisitions: tuple[AcquisitionRegistration, ...],
    *,
    cited_artifacts: tuple[ArtifactRow, ...] = (),
) -> RunReportRegistration:
    envelope, report_artifact, run_values, report_values = _run_report_values(label)
    result_status = "matches" if cited_artifacts else "no_match"
    run = cast(ResearchRunRow, {**run_values, "result_status": result_status})
    report = cast(ResearchReportRow, {**report_values, "result_status": result_status})
    run_edge = ArtifactLineageRow(
        parent_artifact_id=envelope["artifact_id"],
        parent_artifact_kind=envelope["artifact_kind"],
        parent_source_partition=envelope["source_partition"],
        parent_content_hash=envelope["content_hash"],
        child_artifact_id=report_artifact["artifact_id"],
        child_artifact_kind=report_artifact["artifact_kind"],
        child_source_partition=report_artifact["source_partition"],
        child_content_hash=report_artifact["content_hash"],
        lineage_type="run_envelope_to_report",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    publication_edges = tuple(
        ArtifactLineageRow(
            parent_artifact_id=report_artifact["artifact_id"],
            parent_artifact_kind=report_artifact["artifact_kind"],
            parent_source_partition=report_artifact["source_partition"],
            parent_content_hash=report_artifact["content_hash"],
            child_artifact_id=artifact["artifact_id"],
            child_artifact_kind=artifact["artifact_kind"],
            child_source_partition=artifact["source_partition"],
            child_content_hash=artifact["content_hash"],
            lineage_type="report_to_publication",
            lineage_ordinal=ordinal,
            schema_version="1.0",
        )
        for ordinal, artifact in enumerate(cited_artifacts)
    )
    return RunReportRegistration(
        artifacts=(envelope, report_artifact),
        run=run,
        report=report,
        lineage=(run_edge, *publication_edges),
        acquisition_references=tuple(
            (
                acquisition.attempt["acquisition_ordinal"],
                acquisition.attempt["registration_envelope_id"],
            )
            for acquisition in acquisitions
        ),
    )


def _assert_final_metadata_absent(engine: Engine, registration: RunReportRegistration) -> None:
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(models.artifact)
                .where(
                    models.artifact.c.artifact_id.in_(
                        tuple(artifact["artifact_id"] for artifact in registration.artifacts)
                    )
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(models.research_run)
                .where(models.research_run.c.run_id == registration.run["run_id"])
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(models.research_report)
                .where(models.research_report.c.report_id == registration.report["report_id"])
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(models.artifact_lineage)
                .where(
                    models.artifact_lineage.c.parent_artifact_id
                    == registration.report["report_artifact_id"]
                )
            )
            == 0
        )


def _register_without_commit(
    engine: Engine,
    registration: RunReportRegistration,
) -> ResearchRunRow:
    rollback_engine = cast(Engine, _RollbackEngine(engine))
    rollback_repository = PersistenceRepository._from_engine_for_testing(rollback_engine)
    return rollback_repository.register_run_and_report(registration)


def test_run_finalization_rejects_when_no_durable_attempt_exists(
    repository: PersistenceRepository,
) -> None:
    registration = _final_registration("trace-no-attempt", ())
    registration = replace(
        registration,
        acquisition_references=((0, f"registration-envelope:acquisition:{_hash('missing')}"),),
    )

    with pytest.raises(PersistenceIntegrityError, match="no durable acquisition"):
        repository.register_run_and_report(registration)


def test_run_finalization_rejects_without_search_at_ordinal_zero(
    repository: PersistenceRepository,
) -> None:
    label = "trace-no-search-zero"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id, ordinal=1)
    repository.register_acquisition(acquisition)
    registration = replace(
        _final_registration(label, (acquisition,)),
        acquisition_references=((0, acquisition.attempt["registration_envelope_id"]),),
    )

    with pytest.raises(PersistenceIntegrityError, match="search attempt at ordinal zero"):
        repository.register_run_and_report(registration)


def test_run_finalization_rejects_reference_without_durable_attempt(
    repository: PersistenceRepository,
) -> None:
    label = "trace-reference-without-attempt"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id)
    repository.register_acquisition(acquisition)
    registration = replace(
        _final_registration(label, (acquisition,)),
        acquisition_references=(
            (0, acquisition.attempt["registration_envelope_id"]),
            (1, f"registration-envelope:acquisition:{_hash('not-durable')}"),
        ),
    )

    with pytest.raises(PersistenceIntegrityError, match="differ from durable"):
        repository.register_run_and_report(registration)


def test_run_finalization_rejects_omitted_durable_attempt(
    repository: PersistenceRepository,
) -> None:
    label = "trace-omitted-attempt"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, ordinal=1)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    registration = replace(
        _final_registration(label, (search, fetch)),
        acquisition_references=((0, search.attempt["registration_envelope_id"]),),
    )

    with pytest.raises(PersistenceIntegrityError, match="differ from durable"):
        repository.register_run_and_report(registration)


def test_run_finalization_rejects_attempt_ordinal_disagreement(
    repository: PersistenceRepository,
) -> None:
    label = "trace-attempt-ordinal-disagreement"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, ordinal=2)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    registration = replace(
        _final_registration(label, (search, fetch)),
        acquisition_references=(
            (0, search.attempt["registration_envelope_id"]),
            (1, fetch.attempt["registration_envelope_id"]),
        ),
    )

    with pytest.raises(PersistenceIntegrityError, match="not contiguous"):
        repository.register_run_and_report(registration)


def test_run_finalization_rejects_registration_envelope_disagreement(
    repository: PersistenceRepository,
) -> None:
    label = "trace-envelope-disagreement"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id)
    repository.register_acquisition(acquisition)
    registration = replace(
        _final_registration(label, (acquisition,)),
        acquisition_references=(
            (0, f"registration-envelope:acquisition:{_hash('different-envelope')}"),
        ),
    )

    with pytest.raises(PersistenceIntegrityError, match="differ from durable"):
        repository.register_run_and_report(registration)


def test_search_only_complete_no_match_run_is_accepted(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-search-only-no-match"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id)
    repository.register_acquisition(acquisition)
    registration = _final_registration(label, (acquisition,))

    assert _register_without_commit(engine, registration) == registration.run
    _assert_final_metadata_absent(engine, registration)


def test_exact_durable_attempt_set_and_owned_publication_are_accepted(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-normal-exact-attempts"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, publication=publication)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    registration = _final_registration(
        label,
        (search, fetch),
        cited_artifacts=(publication_artifact,),
    )

    assert _register_without_commit(engine, registration) == registration.run
    _assert_final_metadata_absent(engine, registration)


def test_cross_run_publication_citation_is_rejected(
    repository: PersistenceRepository,
) -> None:
    label = "trace-cross-run"
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    other = _acquisition_for_run(
        f"{label}:other",
        f"run:{_uuid4(f'{label}:other-run')}",
        publication=publication,
    )
    target_run_id = cast(str, _run_report_values(label)[2]["run_id"])
    target = _acquisition_for_run(f"{label}:target", target_run_id)
    repository.register_acquisition(other)
    repository.register_acquisition(target)
    registration = _final_registration(label, (target,), cited_artifacts=(publication_artifact,))

    with pytest.raises(PersistenceIntegrityError, match="not owned"):
        repository.register_run_and_report(registration)


def test_global_publication_without_target_snapshot_membership_is_rejected(
    repository: PersistenceRepository,
) -> None:
    label = "trace-global-without-membership"
    publication_artifact, publication_values = _publication_values(label)
    repository.insert_or_verify_artifact(publication_artifact)
    repository.insert_or_verify_publication_version(cast(PublicationVersionRow, publication_values))
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id)
    repository.register_acquisition(acquisition)
    registration = _final_registration(
        label,
        (acquisition,),
        cited_artifacts=(publication_artifact,),
    )

    with pytest.raises(PersistenceIntegrityError, match="not owned"):
        repository.register_run_and_report(registration)


def test_report_publication_artifact_binding_mismatch_is_rejected(
    repository: PersistenceRepository,
) -> None:
    label = "trace-artifact-binding-mismatch"
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, publication=publication)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    wrong_artifact = _artifact_values(f"{label}:wrong", "publication_record")
    repository.insert_or_verify_artifact(wrong_artifact)
    registration = _final_registration(
        label,
        (search, fetch),
        cited_artifacts=(wrong_artifact,),
    )

    with pytest.raises(PersistenceIntegrityError, match="not owned"):
        repository.register_run_and_report(registration)


def test_earlier_publication_version_with_current_run_membership_is_accepted(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-earlier-version-current-membership"
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    earlier = _acquisition_for_run(
        f"{label}:earlier",
        f"run:{_uuid4(f'{label}:earlier-run')}",
        publication=publication,
    )
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    search = _acquisition_for_run(f"{label}:search", run_id)
    current = _acquisition_for_run(f"{label}:current", run_id, publication=publication)
    repository.register_acquisition(earlier)
    repository.register_acquisition(search)
    repository.register_acquisition(current)
    registration = _final_registration(
        label,
        (search, current),
        cited_artifacts=(publication_artifact,),
    )

    assert _register_without_commit(engine, registration) == registration.run
    _assert_final_metadata_absent(engine, registration)


def test_publication_from_one_of_several_current_run_attempts_is_accepted(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-several-attempts"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, ordinal=1, publication=publication)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    registration = _final_registration(
        label,
        (search, fetch),
        cited_artifacts=(publication_artifact,),
    )

    assert _register_without_commit(engine, registration) == registration.run
    _assert_final_metadata_absent(engine, registration)


def test_uncited_current_run_publication_is_not_required_in_report_lineage(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-uncited-current-publication"
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    search = _acquisition_for_run(f"{label}:search", run_id)
    fetch = _acquisition_for_run(f"{label}:fetch", run_id, publication=publication)
    repository.register_acquisition(search)
    repository.register_acquisition(fetch)
    registration = _final_registration(label, (search, fetch))

    assert _register_without_commit(engine, registration) == registration.run
    _assert_final_metadata_absent(engine, registration)


def test_missing_attempt_failure_commits_no_final_metadata(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    registration = _final_registration("trace-missing-attempt-atomicity", ())
    registration = replace(
        registration,
        acquisition_references=((0, f"registration-envelope:acquisition:{_hash('absent')}"),),
    )

    with pytest.raises(PersistenceIntegrityError, match="no durable acquisition"):
        repository.register_run_and_report(registration)
    _assert_final_metadata_absent(engine, registration)


def test_cross_run_citation_failure_commits_no_final_metadata(
    engine: Engine,
    repository: PersistenceRepository,
) -> None:
    label = "trace-cross-run-atomicity"
    publication_artifact, publication_values = _publication_values(label)
    publication = (publication_artifact, cast(PublicationVersionRow, publication_values))
    other = _acquisition_for_run(
        f"{label}:other",
        f"run:{_uuid4(f'{label}:other-run')}",
        publication=publication,
    )
    target_run_id = cast(str, _run_report_values(label)[2]["run_id"])
    target = _acquisition_for_run(f"{label}:target", target_run_id)
    repository.register_acquisition(other)
    repository.register_acquisition(target)
    registration = _final_registration(label, (target,), cited_artifacts=(publication_artifact,))

    with pytest.raises(PersistenceIntegrityError, match="not owned"):
        repository.register_run_and_report(registration)
    _assert_final_metadata_absent(engine, registration)


def test_finalization_failure_preserves_earlier_acquisition_metadata(
    repository: PersistenceRepository,
) -> None:
    label = "trace-acquisition-preserved"
    publication_artifact, publication_values = _publication_values(label)
    repository.insert_or_verify_artifact(publication_artifact)
    repository.insert_or_verify_publication_version(cast(PublicationVersionRow, publication_values))
    run_id = cast(str, _run_report_values(label)[2]["run_id"])
    acquisition = _acquisition_for_run(label, run_id)
    repository.register_acquisition(acquisition)
    registration = _final_registration(
        label,
        (acquisition,),
        cited_artifacts=(publication_artifact,),
    )

    with pytest.raises(PersistenceIntegrityError, match="not owned"):
        repository.register_run_and_report(registration)
    stored = repository.get_snapshot(acquisition.snapshot["snapshot_id"])
    assert stored is not None
    assert stored.attempt == acquisition.attempt


def test_all_public_repository_operations_success_and_failure_paths(
    repository: PersistenceRepository,
) -> None:
    acquisition = _complete_acquisition_registration("all-public-operations")
    snapshot_id = acquisition.snapshot["snapshot_id"]
    assert repository.register_acquisition(acquisition) == acquisition.snapshot
    assert repository.register_acquisition(acquisition) == acquisition.snapshot
    assert repository.get_artifact(snapshot_id) == acquisition.artifacts[0]
    snapshot = repository.get_snapshot(snapshot_id)
    assert snapshot is not None
    assert snapshot.files == acquisition.files
    assert snapshot.memberships == acquisition.memberships

    publication_artifact, publication_values = _publication_values(
        "standalone-publication-operation"
    )
    publication = cast(PublicationVersionRow, publication_values)
    repository.insert_or_verify_artifact(publication_artifact)
    assert repository.insert_or_verify_publication_version(publication) == publication
    assert repository.insert_or_verify_publication_version(publication) == publication
    assert repository.get_publication_version(publication["publication_version_id"]) == publication
    invalid_publication = cast(
        PublicationVersionRow,
        {**publication, "publication_artifact_hash": _hash("invalid-publication-operation")},
    )
    with pytest.raises(ValueError, match="canonical bytes"):
        repository.insert_or_verify_publication_version(invalid_publication)

    subject = acquisition.artifacts[0]
    event = ArtifactIntegrityEventInput(
        event_kind="content_mismatch",
        subject_artifact_id=subject["artifact_id"],
        subject_artifact_kind=subject["artifact_kind"],
        subject_source_partition=subject["source_partition"],
        subject_content_hash=subject["content_hash"],
        expected_content_hash=subject["content_hash"],
        observed_content_hash=_hash("integrity-observed"),
        expected_byte_size=subject["byte_size"],
        observed_byte_size=subject["byte_size"],
        redacted_detail="bounded integrity detail",
        observed_at_utc=NOW,
    )
    inserted_event = repository.insert_or_verify_integrity_event(event)
    assert repository.insert_or_verify_integrity_event(event) == inserted_event
    with pytest.raises(PersistenceConflict):
        repository.insert_or_verify_integrity_event(
            ArtifactIntegrityEventInput(**{**event, "redacted_detail": "different detail"})
        )

    observation = _observation("all operations", identity="all-public-operations")
    inserted_observation = repository.insert_or_verify_registration_observation(observation)
    assert repository.insert_or_verify_registration_observation(observation) == inserted_observation
    with pytest.raises(PersistenceConflict):
        repository.insert_or_verify_registration_observation(
            RegistrationObservationInput(**{**observation, "redacted_detail": "different"})
        )

    replay = ValidatedReplay(
        manifest=acquisition.manifest,
        artifact_links=acquisition.artifact_links,
        publications=acquisition.publications,
        publication_memberships=acquisition.publication_memberships,
        lineage=acquisition.lineage,
        attempt=acquisition.attempt,
    )
    loaded = repository.load_snapshot_for_replay(
        snapshot_id,
        replay_port=_VerifiedReplayPort("all-public-operations", replay),
    )
    assert loaded.replay == replay
    with pytest.raises(PersistenceIntegrityError, match="validated attempt warnings"):
        repository.load_snapshot_for_replay(
            snapshot_id,
            replay_port=_VerifiedReplayPort(
                "all-public-operations",
                replace(
                    replay,
                    manifest=replace(replay.manifest, warning_codes=("mutated",)),
                ),
            ),
        )

    envelope, report_artifact, run, report = _run_report_values("all-public-operations")
    lineage = ArtifactLineageRow(
        parent_artifact_id=envelope["artifact_id"],
        parent_artifact_kind=envelope["artifact_kind"],
        parent_source_partition=envelope["source_partition"],
        parent_content_hash=envelope["content_hash"],
        child_artifact_id=report_artifact["artifact_id"],
        child_artifact_kind=report_artifact["artifact_kind"],
        child_source_partition=report_artifact["source_partition"],
        child_content_hash=report_artifact["content_hash"],
        lineage_type="run_envelope_to_report",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    run_registration = RunReportRegistration(
        artifacts=(envelope, report_artifact),
        run=cast(ResearchRunRow, run),
        report=cast(ResearchReportRow, report),
        lineage=(lineage,),
        acquisition_references=((0, acquisition.attempt["registration_envelope_id"]),),
    )
    assert repository.register_run_and_report(run_registration) == run
    assert repository.register_run_and_report(run_registration) == run
    assert repository.get_run(cast(str, run["run_id"])) is not None
    assert repository.get_report(cast(str, report["report_id"])) == report
    with pytest.raises(PersistenceConflict) as captured:
        repository.register_run_and_report(
            replace(
                run_registration,
                run=cast(ResearchRunRow, {**run, "pubmed_query": "different valid query"}),
            )
        )
    assert captured.value.table == "research_run"
    assert captured.value.constraint == "pk_research_run"

    new_envelope, new_report_artifact, new_run, new_report = _run_report_values(
        "repository-run-report-new-identity"
    )
    new_acquisition = _complete_acquisition_registration("repository-run-report-new-identity")
    repository.register_acquisition(new_acquisition)
    new_lineage = ArtifactLineageRow(
        parent_artifact_id=new_envelope["artifact_id"],
        parent_artifact_kind=new_envelope["artifact_kind"],
        parent_source_partition=new_envelope["source_partition"],
        parent_content_hash=new_envelope["content_hash"],
        child_artifact_id=new_report_artifact["artifact_id"],
        child_artifact_kind=new_report_artifact["artifact_kind"],
        child_source_partition=new_report_artifact["source_partition"],
        child_content_hash=new_report_artifact["content_hash"],
        lineage_type="run_envelope_to_report",
        lineage_ordinal=0,
        schema_version="1.0",
    )
    with pytest.raises(
        PersistenceCapacityError,
        match="frozen capacity reached for research_run: 1",
    ):
        repository.register_run_and_report(
            RunReportRegistration(
                artifacts=(new_envelope, new_report_artifact),
                run=cast(ResearchRunRow, new_run),
                report=cast(ResearchReportRow, new_report),
                lineage=(new_lineage,),
                acquisition_references=((0, new_acquisition.attempt["registration_envelope_id"]),),
            )
        )
    assert repository.get_artifact(new_envelope["artifact_id"]) is None

    assert repository.get_artifact(_hash("absent")) is None
    assert repository.get_publication_version("absent") is None
    assert repository.get_snapshot(_hash("absent-snapshot")) is None
    assert repository.get_run("run:00000000-0000-4000-8000-000000000000") is None
    assert repository.get_report(f"report:{_hash('absent-report')}") is None


def test_snapshot_lineage_ignores_unowned_parent_sharing_raw_child(
    repository: PersistenceRepository,
) -> None:
    acquisition = _complete_acquisition_registration("shared-content-lineage-owner")
    repository.register_acquisition(acquisition)
    unrelated_manifest = _artifact_values("shared-content-lineage-unrelated", "snapshot_manifest")
    repository.insert_or_verify_artifact(unrelated_manifest)
    raw = next(
        artifact
        for artifact in acquisition.artifacts
        if artifact["artifact_kind"] == "pubmed_http_response"
    )
    unrelated_edge = ArtifactLineageRow(
        parent_artifact_id=unrelated_manifest["artifact_id"],
        parent_artifact_kind=unrelated_manifest["artifact_kind"],
        parent_source_partition=unrelated_manifest["source_partition"],
        parent_content_hash=unrelated_manifest["content_hash"],
        child_artifact_id=raw["artifact_id"],
        child_artifact_kind=raw["artifact_kind"],
        child_source_partition=raw["source_partition"],
        child_content_hash=raw["content_hash"],
        lineage_type="manifest_to_raw_response",
        lineage_ordinal=1,
        schema_version="1.0",
    )
    with repository._engine.begin() as connection:
        connection.execute(models.artifact_lineage.insert().values(**unrelated_edge))

    snapshot = repository.get_snapshot(acquisition.snapshot["snapshot_id"])
    assert snapshot is not None
    assert snapshot.lineage == acquisition.lineage
    replay = ValidatedReplay(
        manifest=acquisition.manifest,
        artifact_links=acquisition.artifact_links,
        publications=acquisition.publications,
        publication_memberships=acquisition.publication_memberships,
        lineage=acquisition.lineage,
        attempt=acquisition.attempt,
    )
    loaded = repository.load_snapshot_for_replay(
        acquisition.snapshot["snapshot_id"],
        replay_port=_VerifiedReplayPort("shared-content-lineage-owner", replay),
    )
    assert loaded.replay.lineage == acquisition.lineage


CAPACITY_LIMITS = {
    "artifact": 708,
    "source_snapshot": 101,
    "snapshot_file": 404,
    "source_snapshot_file": 404,
    "snapshot_warning": 12_928,
    "publication_version": 100,
    "source_snapshot_publication": 100,
    "artifact_lineage": 1_210,
    "research_run": 1,
    "research_run_attempt": 101,
    "research_report": 1,
    "artifact_integrity_event": 13_056,
    "registration_observation": 13_056,
}

FROZEN_TABLE_ORDER = (
    models.artifact,
    models.source_snapshot,
    models.snapshot_file,
    models.source_snapshot_file,
    models.snapshot_warning,
    models.publication_version,
    models.source_snapshot_publication,
    models.artifact_lineage,
    models.research_run,
    models.research_run_attempt,
    models.research_report,
    models.artifact_integrity_event,
    models.registration_observation,
)


def _insert_many(connection: Connection, table: sa.Table, rows: list[dict[str, object]]) -> None:
    for offset in range(0, len(rows), 1_000):
        connection.execute(table.insert(), rows[offset : offset + 1_000])


def _capacity_snapshot_file_values(
    label: str, ordinal: int = 0
) -> tuple[ArtifactRow, dict[str, object]]:
    raw = _artifact_values(label, "pubmed_http_response")
    digest = raw["artifact_id"].removeprefix("sha256:")
    path = f"pubmed/sha256/{digest[:2]}/{digest}.bin"
    raw["relative_storage_path"] = path
    return raw, {
        "link_id": f"artifact-link:{_hash(f'{label}:link')}",
        "acquisition_intent_id": f"acquisition-intent:{_hash(f'{label}:intent')}",
        "ordinal": ordinal,
        "raw_artifact_id": raw["artifact_id"],
        "raw_artifact_kind": raw["artifact_kind"],
        "raw_source_partition": raw["source_partition"],
        "raw_content_hash": raw["content_hash"],
        "relative_storage_path": path,
        "byte_size": raw["byte_size"],
        "media_type": raw["media_type"],
        "content_encoding": None,
        "http_status": 500,
        "body_complete": False,
        "termination_reason": "stream_error",
        "observed_at_utc": NOW,
        "schema_version": "1.0",
    }


def _prepare_capacity_case(
    connection: Connection, table_name: str
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    capacity = CAPACITY_LIMITS[table_name]
    if table_name == "artifact":
        values = [
            dict(_artifact_values(f"capacity-artifact-{index}", "snapshot_manifest"))
            for index in range(capacity + 1)
        ]
        _insert_many(connection, models.artifact, values[: capacity - 1])
        candidate = values[capacity - 1]
        return candidate, {**candidate, "relative_storage_path": "capacity/conflict"}, values[-1]

    if table_name == "source_snapshot":
        pairs = [
            _snapshot_values(f"capacity-snapshot-{index}", ("succeeded", "complete", "no_match"))
            for index in range(capacity + 1)
        ]
        _insert_many(connection, models.artifact, [dict(pair[0]) for pair in pairs])
        _insert_many(connection, models.source_snapshot, [dict(pair[1]) for pair in pairs[:-2]])
        candidate = dict(pairs[-2][1])
        return (
            candidate,
            {**candidate, "request_identity": "different bounded request"},
            dict(pairs[-1][1]),
        )

    if table_name == "snapshot_file":
        pairs = [
            _capacity_snapshot_file_values(f"capacity-file-{index}")
            for index in range(capacity + 1)
        ]
        _insert_many(connection, models.artifact, [dict(pair[0]) for pair in pairs])
        _insert_many(connection, models.snapshot_file, [pair[1] for pair in pairs[:-2]])
        candidate = pairs[-2][1]
        return candidate, {**candidate, "observed_at_utc": NOW + timedelta(seconds=1)}, pairs[-1][1]

    if table_name == "source_snapshot_file":
        snapshots = [
            _snapshot_values(
                f"capacity-membership-snapshot-{index}",
                ("succeeded", "complete", "no_match"),
            )
            for index in range(101)
        ]
        raw_artifacts: list[dict[str, object]] = []
        files: list[dict[str, object]] = []
        memberships: list[dict[str, object]] = []
        for snapshot_index, (_manifest, snapshot) in enumerate(snapshots):
            for ordinal in range(4):
                raw, file_row = _capacity_snapshot_file_values(
                    f"capacity-membership-{snapshot_index}-{ordinal}", ordinal
                )
                file_row["acquisition_intent_id"] = snapshot["acquisition_intent_id"]
                raw_artifacts.append(dict(raw))
                files.append(file_row)
                memberships.append(
                    {
                        "snapshot_id": snapshot["snapshot_id"],
                        "acquisition_intent_id": snapshot["acquisition_intent_id"],
                        "ordinal": ordinal,
                        "link_id": file_row["link_id"],
                    }
                )
        _insert_many(
            connection,
            models.artifact,
            [dict(pair[0]) for pair in snapshots] + raw_artifacts,
        )
        _insert_many(connection, models.source_snapshot, [dict(pair[1]) for pair in snapshots])
        _insert_many(connection, models.snapshot_file, files)
        _insert_many(connection, models.source_snapshot_file, memberships[:-1])
        candidate = memberships[-1]
        conflict = {**candidate, "link_id": memberships[0]["link_id"]}
        return candidate, conflict, {**candidate, "snapshot_id": _hash("capacity-new-snapshot")}

    if table_name == "snapshot_warning":
        snapshots = [
            _snapshot_values(
                f"capacity-warning-snapshot-{index}",
                ("succeeded", "complete", "no_match"),
            )
            for index in range(101)
        ]
        warnings = [
            {
                "snapshot_id": snapshot["snapshot_id"],
                "warning_ordinal": ordinal,
                "warning_code": f"warning_{ordinal:03d}",
            }
            for _, snapshot in snapshots
            for ordinal in range(128)
        ]
        _insert_many(connection, models.artifact, [dict(pair[0]) for pair in snapshots])
        _insert_many(connection, models.source_snapshot, [dict(pair[1]) for pair in snapshots])
        _insert_many(connection, models.snapshot_warning, warnings[:-1])
        candidate = warnings[-1]
        conflict = {**candidate, "warning_code": "different_warning"}
        return candidate, conflict, {**candidate, "snapshot_id": _hash("capacity-new-warning")}

    if table_name in {"publication_version", "source_snapshot_publication"}:
        publications = [
            _publication_values(f"capacity-publication-{index}", pmid=str(20_000_000 + index))
            for index in range(101)
        ]
        if table_name == "publication_version":
            _insert_many(connection, models.artifact, [dict(pair[0]) for pair in publications])
            _insert_many(
                connection,
                models.publication_version,
                [pair[1] for pair in publications[:-2]],
            )
            candidate = publications[-2][1]
            conflict = {
                **candidate,
                "publication_status_identity": _hash("status-conflict").replace(
                    "sha256:", "publication-status:sha256:"
                ),
            }
            return candidate, conflict, publications[-1][1]
        manifest, snapshot = _snapshot_values(
            "capacity-publication-membership-snapshot",
            ("succeeded", "complete", "no_match"),
        )
        _insert_many(
            connection,
            models.artifact,
            [dict(manifest), *(dict(pair[0]) for pair in publications[:100])],
        )
        connection.execute(models.source_snapshot.insert().values(**snapshot))
        _insert_many(
            connection,
            models.publication_version,
            [pair[1] for pair in publications[:100]],
        )
        memberships = [
            {
                "snapshot_id": snapshot["snapshot_id"],
                "publication_ordinal": ordinal,
                "pmid": publication[1]["pmid"],
                "publication_version_id": publication[1]["publication_version_id"],
                "source": publication[1]["source"],
                "publication_content_hash": publication[1]["content_hash"],
            }
            for ordinal, publication in enumerate(publications[:100])
        ]
        _insert_many(connection, models.source_snapshot_publication, memberships[:-1])
        candidate = memberships[-1]
        conflict = {**candidate, "publication_content_hash": _hash("membership-conflict")}
        return candidate, conflict, {**candidate, "snapshot_id": _hash("capacity-new-membership")}

    if table_name == "artifact_lineage":
        parent = _artifact_values("capacity-lineage-parent", "snapshot_manifest")
        child = _artifact_values("capacity-lineage-child", "snapshot_manifest")
        connection.execute(models.artifact.insert(), [dict(parent), dict(child)])
        rows = []
        lineage_types = (
            "manifest_to_raw_response",
            "publication_to_manifest",
            "acquisition_envelope_to_manifest",
            "acquisition_envelope_to_raw_response",
            "acquisition_envelope_to_publication",
            "report_to_publication",
            "run_envelope_to_report",
        )
        for reverse in (False, True):
            left, right = (child, parent) if reverse else (parent, child)
            for lineage_type in lineage_types:
                for ordinal in range(101):
                    rows.append(
                        {
                            "parent_artifact_id": left["artifact_id"],
                            "parent_artifact_kind": left["artifact_kind"],
                            "parent_source_partition": left["source_partition"],
                            "parent_content_hash": left["content_hash"],
                            "child_artifact_id": right["artifact_id"],
                            "child_artifact_kind": right["artifact_kind"],
                            "child_source_partition": right["source_partition"],
                            "child_content_hash": right["content_hash"],
                            "lineage_type": lineage_type,
                            "lineage_ordinal": ordinal,
                            "schema_version": "1.0",
                        }
                    )
        _insert_many(connection, models.artifact_lineage, rows[: capacity - 1])
        candidate = rows[capacity - 1]
        return candidate, {**candidate, "schema_version": "2.0"}, rows[capacity]

    if table_name == "research_run":
        envelope, report_artifact, run, _ = _run_report_values("capacity-run")
        new_envelope, new_report_artifact, new_run, _ = _run_report_values("capacity-run-new")
        connection.execute(
            models.artifact.insert(),
            [dict(envelope), dict(report_artifact), dict(new_envelope), dict(new_report_artifact)],
        )
        candidate = run
        return candidate, {**candidate, "pubmed_query": "different bounded query"}, new_run

    if table_name == "research_run_attempt":
        rows = [
            _attempt_values(f"capacity-attempt-{index}", ("succeeded", "complete", "no_match"))
            for index in range(capacity + 1)
        ]
        _insert_many(
            connection,
            models.artifact,
            [dict(item) for row in rows for item in (row[0], row[1])],
        )
        _insert_many(connection, models.source_snapshot, [dict(row[2]) for row in rows])
        _insert_many(connection, models.research_run_attempt, [dict(row[3]) for row in rows[:-2]])
        candidate = dict(rows[-2][3])
        return (
            candidate,
            {**candidate, "request_identity": "different bounded request"},
            dict(rows[-1][3]),
        )

    if table_name == "research_report":
        envelope, report_artifact, run, report = _run_report_values("capacity-report")
        _, _, _, new_report = _run_report_values("capacity-report-new")
        connection.execute(models.artifact.insert(), [dict(envelope), dict(report_artifact)])
        connection.execute(models.research_run.insert().values(**run))
        candidate = report
        return candidate, {**candidate, "created_at_utc": NOW + timedelta(seconds=1)}, new_report

    if table_name == "artifact_integrity_event":
        subject = _artifact_values("capacity-integrity-subject", "snapshot_manifest")
        connection.execute(models.artifact.insert().values(**subject))
        rows = [
            {
                "event_kind": "content_mismatch",
                "subject_artifact_id": subject["artifact_id"],
                "subject_artifact_kind": subject["artifact_kind"],
                "subject_source_partition": subject["source_partition"],
                "subject_content_hash": subject["content_hash"],
                "expected_content_hash": subject["content_hash"],
                "observed_content_hash": _hash(f"capacity-integrity-{index}"),
                "expected_byte_size": subject["byte_size"],
                "observed_byte_size": index,
                "redacted_detail": "bounded synthetic mismatch",
                "observed_at_utc": NOW + timedelta(microseconds=index),
            }
            for index in range(capacity + 1)
        ]
        _insert_many(connection, models.artifact_integrity_event, rows[: capacity - 1])
        candidate = rows[capacity - 1]
        return candidate, {**candidate, "redacted_detail": "different bounded detail"}, rows[-1]

    if table_name == "registration_observation":
        rows = [
            dict(_observation("bounded synthetic observation", identity=f"capacity-{index}"))
            for index in range(capacity + 1)
        ]
        _insert_many(connection, models.registration_observation, rows[: capacity - 1])
        candidate = rows[capacity - 1]
        return candidate, {**candidate, "redacted_detail": "different bounded detail"}, rows[-1]

    raise AssertionError(f"unknown capacity table: {table_name}")


@pytest.mark.parametrize("table_name", tuple(CAPACITY_LIMITS))
def test_real_postgresql_all_table_capacity_and_identity_precedence(
    engine: Engine, table_name: str
) -> None:
    repository = PersistenceRepository._from_engine_for_testing(engine)
    spec = repository_module._SPECS[table_name]
    assert spec.capacity == CAPACITY_LIMITS[table_name]
    table_list = ", ".join(f'"{models.SCHEMA}"."{table.name}"' for table in FROZEN_TABLE_ORDER)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(sa.text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
            candidate, conflict, new_identity = _prepare_capacity_case(connection, table_name)
            assert connection.scalar(sa.select(sa.func.count()).select_from(spec.table)) == (
                spec.capacity - 1
            )
            inserted = repository._insert_or_verify(
                connection, spec, candidate, method="postgresql_capacity_matrix"
            )
            assert all(inserted[key] == value for key, value in candidate.items())
            assert connection.scalar(sa.select(sa.func.count()).select_from(spec.table)) == (
                spec.capacity
            )
            identical = repository._insert_or_verify(
                connection, spec, candidate, method="postgresql_capacity_matrix"
            )
            assert all(identical[key] == value for key, value in candidate.items())
            with pytest.raises(PersistenceConflict) as captured:
                repository._insert_or_verify(
                    connection, spec, conflict, method="postgresql_capacity_matrix"
                )
            assert captured.value.table == table_name
            assert captured.value.constraint == spec.identity_constraint_name
            with pytest.raises(PersistenceCapacityError):
                repository._insert_or_verify(
                    connection, spec, new_identity, method="postgresql_capacity_matrix"
                )
        finally:
            transaction.rollback()
