"""Structural tests for the exact frozen Core and private migration metadata."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from medevidence.persistence import models
from medevidence.persistence import repositories as repository_module
from medevidence.persistence.repositories import (
    PersistenceCapacityError,
    PersistenceConflict,
    PersistenceRepository,
    ResearchRunAttemptRow,
    SourceSnapshotRow,
    ValidatedArtifactLink,
    ValidatedManifest,
    ValidatedManifestFile,
)

EXPECTED_TABLES = (
    "artifact",
    "source_snapshot",
    "snapshot_file",
    "source_snapshot_file",
    "snapshot_warning",
    "publication_version",
    "source_snapshot_publication",
    "artifact_lineage",
    "research_run",
    "research_run_attempt",
    "research_report",
    "artifact_integrity_event",
    "registration_observation",
)

EXPECTED_IDENTITY_CONSTRAINTS = {
    "artifact": "pk_artifact",
    "source_snapshot": "pk_source_snapshot",
    "snapshot_file": "pk_snapshot_file",
    "source_snapshot_file": "pk_source_snapshot_file",
    "snapshot_warning": "pk_snapshot_warning",
    "publication_version": "pk_publication_version",
    "source_snapshot_publication": "pk_source_snapshot_publication",
    "artifact_lineage": "pk_artifact_lineage",
    "research_run": "pk_research_run",
    "research_run_attempt": "pk_research_run_attempt",
    "research_report": "pk_research_report",
    "artifact_integrity_event": "uq_integrity_event_natural",
    "registration_observation": "uq_registration_observation_natural",
}


def _constraints(kind: type[sa.Constraint]) -> set[str]:
    return {
        constraint.name
        for table in models.TABLE_ORDER
        for constraint in table.constraints
        if isinstance(constraint, kind) and constraint.name is not None
    }


def _migration_module() -> ModuleType:
    path = Path("alembic/versions/20260806_01_m1a_003b_snapshot_metadata.py")
    spec = importlib.util.spec_from_file_location("m1a003b_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_object_counts_and_names() -> None:
    assert tuple(table.name for table in models.TABLE_ORDER) == EXPECTED_TABLES
    assert len(models.metadata.tables) == 13
    assert len(_constraints(sa.CheckConstraint)) == 62
    assert len(_constraints(sa.ForeignKeyConstraint)) == 17
    assert len(_constraints(sa.PrimaryKeyConstraint)) == 13
    assert len(_constraints(sa.UniqueConstraint)) == 22
    assert sum(len(table.indexes) for table in models.TABLE_ORDER) == 12
    assert _constraints(sa.CheckConstraint) == set(models.EXPECTED_CHECK_NAMES)


def test_every_foreign_key_is_restrict_and_only_run_report_is_deferred() -> None:
    foreign_keys = [
        constraint for table in models.TABLE_ORDER for constraint in table.foreign_key_constraints
    ]

    assert all(item.onupdate == "RESTRICT" and item.ondelete == "RESTRICT" for item in foreign_keys)
    assert {item.name for item in foreign_keys if item.deferrable or item.initially} == {
        "fk_research_run_report"
    }
    deferred = next(item for item in foreign_keys if item.name == "fk_research_run_report")
    assert deferred.deferrable is True
    assert deferred.initially == "DEFERRED"


def test_migration_embeds_equivalent_private_metadata_without_application_import() -> None:
    module = _migration_module()
    private = module._metadata

    assert module.revision == "m1a003b0001"
    assert module.down_revision is None
    assert tuple(module._ORDER) == EXPECTED_TABLES
    assert set(private.tables) == set(models.metadata.tables)
    for key, table in models.metadata.tables.items():
        migrated = private.tables[key]
        assert tuple(column.name for column in migrated.columns) == tuple(
            column.name for column in table.columns
        )
        assert tuple(
            (str(column.type), column.nullable, str(column.server_default))
            for column in migrated.columns
        ) == tuple(
            (str(column.type), column.nullable, str(column.server_default))
            for column in table.columns
        )
        assert {constraint.name for constraint in migrated.constraints} == {
            constraint.name for constraint in table.constraints
        }
        assert {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                constraint.onupdate,
                constraint.ondelete,
                constraint.deferrable,
                constraint.initially,
            )
            for constraint in migrated.foreign_key_constraints
        } == {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
                constraint.onupdate,
                constraint.ondelete,
                constraint.deferrable,
                constraint.initially,
            )
            for constraint in table.foreign_key_constraints
        }
        assert {index.name for index in migrated.indexes} == {index.name for index in table.indexes}
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "medevidence.persistence" not in source


def test_raw_bytes_have_no_postgresql_column() -> None:
    assert all(
        not isinstance(column.type, (sa.LargeBinary,)) and "BYTEA" not in str(column.type).upper()
        for table in models.TABLE_ORDER
        for column in table.columns
    )


class _CapacityResult:
    def __init__(self, existing: dict[str, object] | None) -> None:
        self._existing = existing

    def mappings(self) -> _CapacityResult:
        return self

    def one_or_none(self) -> dict[str, object] | None:
        return self._existing


class _CapacityConnection:
    def __init__(self, count: int, existing: dict[str, object] | None) -> None:
        self._count = count
        self._existing = existing
        self.execute_calls = 0

    def execute(self, _statement: object) -> _CapacityResult:
        self.execute_calls += 1
        return _CapacityResult(self._existing)

    def scalar(self, _statement: object) -> int:
        return self._count


@pytest.mark.parametrize("table_name", EXPECTED_TABLES)
@pytest.mark.parametrize(
    "state",
    ("capacity_minus_one", "full_identical", "full_conflict", "full_new_identity"),
)
def test_capacity_guard_preserves_identity_precedence_for_every_table(
    table_name: str,
    state: str,
) -> None:
    spec = repository_module._SPECS[table_name]
    values: dict[str, object] = {
        column: f"synthetic:{table_name}:{column}" for column in spec.comparison_columns
    }
    existing: dict[str, object] | None = None
    if state in {"full_identical", "full_conflict"}:
        existing = dict(values)
    if state == "full_conflict":
        divergent_column = next(
            column for column in spec.comparison_columns if column not in spec.identity_columns
        )
        assert existing is not None
        existing[divergent_column] = f"different:{table_name}:{divergent_column}"
    count = spec.capacity - 1 if state == "capacity_minus_one" else spec.capacity
    fake = _CapacityConnection(count, existing)
    connection = cast(Connection, cast(object, fake))
    repository = cast(PersistenceRepository, object.__new__(PersistenceRepository))

    if state == "capacity_minus_one":
        assert repository._lock_and_check_capacity(connection, spec, values) is None
        assert fake.execute_calls == 1
    elif state == "full_identical":
        assert repository._lock_and_check_capacity(connection, spec, values) == values
        assert fake.execute_calls == 2
    elif state == "full_conflict":
        with pytest.raises(PersistenceConflict) as captured:
            repository._lock_and_check_capacity(connection, spec, values)
        assert captured.value.table == table_name
        assert captured.value.constraint == EXPECTED_IDENTITY_CONSTRAINTS[table_name]
        assert fake.execute_calls == 2
    else:
        with pytest.raises(
            PersistenceCapacityError,
            match=f"frozen capacity reached for {table_name}: {spec.capacity}",
        ):
            repository._lock_and_check_capacity(connection, spec, values)
        assert fake.execute_calls == 2


NOW = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
DIGEST = f"sha256:{'a' * 64}"
INTENT = f"acquisition-intent:sha256:{'b' * 64}"


def _manifest() -> ValidatedManifest:
    return ValidatedManifest(
        manifest_id=DIGEST,
        manifest_schema_version="1.0",
        retention_policy_id="M1A-LIVE-RETENTION-v1",
        source_type="pubmed",
        acquisition_intent_id=INTENT,
        request_identity="bounded request",
        started_at_utc=NOW,
        completed_at_utc=NOW,
        record_count=0,
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        warning_codes=(),
        files=(),
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        source_record_schema_version="1.0",
        code_revision="c" * 40,
    )


def _snapshot() -> SourceSnapshotRow:
    return SourceSnapshotRow(
        snapshot_id=DIGEST,
        source="pubmed",
        acquisition_intent_id=INTENT,
        request_identity="bounded request",
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        record_count=0,
        attempts_used=1,
        pages_completed=1,
        truncated=False,
        manifest_artifact_id=DIGEST,
        manifest_artifact_kind="snapshot_manifest",
        manifest_source_partition="pubmed",
        manifest_content_hash=DIGEST,
        started_at_utc=NOW,
        completed_at_utc=NOW,
        connector_name="medevidence.connectors.pubmed",
        connector_version="m1a-002",
        manifest_schema_version="1.0",
        source_record_schema_version="1.0",
        code_revision="c" * 40,
        retention_policy_id="M1A-LIVE-RETENTION-v1",
    )


MANIFEST_SNAPSHOT_MUTATIONS = (
    ("snapshot_id", f"sha256:{'d' * 64}"),
    ("source", "other"),
    ("acquisition_intent_id", f"acquisition-intent:sha256:{'d' * 64}"),
    ("request_identity", "different"),
    ("execution_status", "failed"),
    ("coverage_status", "partial"),
    ("result_status", "indeterminate"),
    ("record_count", 1),
    ("attempts_used", 2),
    ("pages_completed", 0),
    ("truncated", True),
    ("started_at_utc", datetime(2026, 8, 7, 14, 59, tzinfo=UTC)),
    ("completed_at_utc", datetime(2026, 8, 7, 15, 1, tzinfo=UTC)),
    ("connector_name", "different.connector"),
    ("connector_version", "different"),
    ("manifest_schema_version", "2.0"),
    ("source_record_schema_version", "2.0"),
    ("code_revision", "d" * 40),
    ("retention_policy_id", "different"),
)


@pytest.mark.parametrize("column,value", MANIFEST_SNAPSHOT_MUTATIONS)
def test_every_manifest_snapshot_projection_mismatch_is_rejected(
    column: str,
    value: object,
) -> None:
    snapshot = _snapshot()
    snapshot[column] = value  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="validated manifest"):
        PersistenceRepository._compare_manifest_snapshot(
            _manifest(), snapshot, error_type=ValueError
        )


def _attempt() -> ResearchRunAttemptRow:
    return ResearchRunAttemptRow(
        attempt_id="attempt:00000000-0000-4000-8000-000000000001",
        run_id="run:00000000-0000-4000-8000-000000000001",
        acquisition_ordinal=0,
        acquisition_intent_id=INTENT,
        registration_envelope_id=f"registration-envelope:acquisition:sha256:{'e' * 64}",
        source="pubmed",
        operation="search",
        intent_created_at_utc=NOW,
        request_identity="bounded request",
        execution_profile_id="M1A_CONSTRAINED_V1",
        started_at_utc=NOW,
        completed_at_utc=NOW,
        execution_status="succeeded",
        coverage_status="complete",
        result_status="no_match",
        valid_result_count=0,
        pages_completed=1,
        attempts_used=1,
        truncated=False,
        warning_codes=(),
        failure_code=None,
        redacted_detail=None,
        registration_state="ready_for_insert",
        manifest_id=DIGEST,
        envelope_artifact_id=f"sha256:{'e' * 64}",
        envelope_artifact_kind="acquisition_registration_envelope",
        envelope_source_partition="pubmed",
        envelope_content_hash=f"sha256:{'e' * 64}",
        intent_schema_version="1.0",
        envelope_schema_version="1.0",
    )


ATTEMPT_MANIFEST_MUTATIONS = (
    ("manifest_id", f"sha256:{'d' * 64}"),
    ("acquisition_intent_id", f"acquisition-intent:sha256:{'d' * 64}"),
    ("source", "other"),
    ("request_identity", "different"),
    ("started_at_utc", datetime(2026, 8, 7, 14, 59, tzinfo=UTC)),
    ("completed_at_utc", datetime(2026, 8, 7, 15, 1, tzinfo=UTC)),
    ("execution_status", "failed"),
    ("coverage_status", "partial"),
    ("result_status", "indeterminate"),
    ("valid_result_count", 1),
    ("pages_completed", 0),
    ("attempts_used", 2),
    ("truncated", True),
    ("warning_codes", ("different",)),
)


@pytest.mark.parametrize("column,value", ATTEMPT_MANIFEST_MUTATIONS)
def test_every_attempt_manifest_projection_mismatch_is_rejected(
    column: str,
    value: object,
) -> None:
    attempt = _attempt()
    attempt[column] = value  # type: ignore[literal-required]

    with pytest.raises(ValueError, match="validated attempt"):
        PersistenceRepository._compare_attempt_manifest(
            attempt, _manifest(), _snapshot(), error_type=ValueError
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("ordinal", 1),
        ("link_id", f"artifact-link:sha256:{'d' * 64}"),
        ("artifact_id", f"sha256:{'d' * 64}"),
        ("byte_size", 2),
        ("media_type", "application/octet-stream"),
        ("content_encoding", "gzip"),
        ("http_status", 500),
        ("body_complete", False),
        ("termination_reason", "stream_error"),
    ),
)
def test_every_manifest_file_link_projection_mismatch_is_rejected(
    field: str,
    value: object,
) -> None:
    file = ValidatedManifestFile(
        ordinal=0,
        link_id=f"artifact-link:sha256:{'f' * 64}",
        artifact_id=f"sha256:{'f' * 64}",
        relative_path=f"pubmed/sha256/ff/{'f' * 64}.bin",
        byte_size=1,
        media_type="application/xml",
        content_encoding=None,
        http_status=200,
        body_complete=True,
        termination_reason="complete_response",
    )
    link = ValidatedArtifactLink(
        link_id=file.link_id,
        acquisition_intent_id=INTENT,
        ordinal=0,
        artifact_id=file.artifact_id,
        artifact_kind="pubmed_http_response",
        media_type=file.media_type,
        content_encoding=None,
        http_status=200,
        byte_size=1,
        body_complete=True,
        termination_reason="complete_response",
        observed_at_utc=NOW,
        schema_version="1.0",
    )
    mutated = replace(file, **{field: value})

    with pytest.raises(ValueError, match="artifact link differs"):
        PersistenceRepository._expected_file_rows(
            replace(_manifest(), files=(mutated,)), (link,), _snapshot()
        )
