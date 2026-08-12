"""Immutable synchronous repositories for frozen M1A-003B metadata."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from typing import Protocol, TypedDict, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Connection, Engine, Table
from sqlalchemy.exc import IntegrityError

from medevidence.domain import (
    CoverageStatus,
    DailyMedCandidateLabel,
    DailyMedLabelVersion,
    DailyMedMarketingState,
    ExecutionBounds,
    ExecutionStatus,
    LabelSection,
    LabelSelectionDecision,
    Provenance,
    PublicationRecord,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
)

from . import models
from .config import PersistenceSettings
from .session import _create_engine

logger = logging.getLogger(__name__)

PUBLICATION_BYTE_CAPACITY = 31_457_280
_SPECIALIZED_DAILYMED_TABLES = frozenset(
    {
        "m1b_dailymed_selection_decisions",
        "m1b_dailymed_label_versions",
        "m1b_dailymed_sections",
        "m1b_dailymed_label_supersession",
    }
)


class ArtifactRow(TypedDict):
    artifact_id: str
    artifact_kind: str
    source_partition: str
    content_hash: str
    byte_size: int
    media_type: str
    relative_storage_path: str
    artifact_schema_version: str


class SourceSnapshotRow(TypedDict):
    snapshot_id: str
    source: str
    acquisition_intent_id: str
    request_identity: str
    execution_status: str
    coverage_status: str
    result_status: str
    record_count: int
    attempts_used: int
    pages_completed: int
    truncated: bool
    manifest_artifact_id: str
    manifest_artifact_kind: str
    manifest_source_partition: str
    manifest_content_hash: str
    started_at_utc: datetime
    completed_at_utc: datetime
    connector_name: str
    connector_version: str
    manifest_schema_version: str
    source_record_schema_version: str
    code_revision: str
    retention_policy_id: str


class SnapshotFileRow(TypedDict):
    link_id: str
    acquisition_intent_id: str
    ordinal: int
    raw_artifact_id: str
    raw_artifact_kind: str
    raw_source_partition: str
    raw_content_hash: str
    relative_storage_path: str
    byte_size: int
    media_type: str
    content_encoding: str | None
    http_status: int
    body_complete: bool
    termination_reason: str
    observed_at_utc: datetime
    schema_version: str


class SourceSnapshotFileRow(TypedDict):
    snapshot_id: str
    acquisition_intent_id: str
    ordinal: int
    link_id: str


class SnapshotWarningRow(TypedDict):
    snapshot_id: str
    warning_ordinal: int
    warning_code: str


class PublicationVersionRow(TypedDict):
    publication_version_id: str
    source: str
    pmid: str
    content_hash: str
    publication_status_identity: str
    publication_status: str
    status_retrieved_at_utc: datetime
    version_payload: dict[str, object]
    publication_artifact_id: str
    publication_artifact_kind: str
    publication_source_partition: str
    publication_artifact_hash: str
    schema_version: str


class SourceSnapshotPublicationRow(TypedDict):
    snapshot_id: str
    publication_ordinal: int
    pmid: str
    publication_version_id: str
    source: str
    publication_content_hash: str


class ArtifactLineageRow(TypedDict):
    parent_artifact_id: str
    parent_artifact_kind: str
    parent_source_partition: str
    parent_content_hash: str
    child_artifact_id: str
    child_artifact_kind: str
    child_source_partition: str
    child_content_hash: str
    lineage_type: str
    lineage_ordinal: int
    schema_version: str


class ResearchRunRow(TypedDict):
    run_id: str
    run_intent_id: str
    request_id: str
    created_at_utc: datetime
    code_revision: str
    scope_id: str
    execution_profile_id: str
    catalog_version: str
    catalog_content_hash: str
    source: str
    drug_concept_ids: Sequence[str]
    adverse_event_concept_ids: Sequence[str]
    start_date: date | None
    end_date: date | None
    pubmed_query: str
    started_at_utc: datetime
    completed_at_utc: datetime
    run_status: str
    coverage_status: str
    result_status: str
    registration_envelope_id: str
    envelope_artifact_id: str
    envelope_artifact_kind: str
    envelope_source_partition: str
    envelope_content_hash: str
    report_id: str
    warning_codes: Sequence[str]


class ResearchRunAttemptRow(TypedDict):
    attempt_id: str
    run_id: str
    acquisition_ordinal: int
    acquisition_intent_id: str
    registration_envelope_id: str
    source: str
    operation: str
    intent_created_at_utc: datetime
    request_identity: str
    execution_profile_id: str
    started_at_utc: datetime
    completed_at_utc: datetime
    execution_status: str
    coverage_status: str
    result_status: str
    valid_result_count: int
    pages_completed: int
    attempts_used: int
    truncated: bool
    warning_codes: Sequence[str]
    failure_code: str | None
    redacted_detail: str | None
    registration_state: str
    manifest_id: str
    envelope_artifact_id: str
    envelope_artifact_kind: str
    envelope_source_partition: str
    envelope_content_hash: str
    intent_schema_version: str
    envelope_schema_version: str


class ResearchReportRow(TypedDict):
    report_id: str
    run_id: str
    report_status: str
    report_artifact_id: str
    report_artifact_kind: str
    report_source_partition: str
    report_content_hash: str
    report_byte_size: int
    report_media_type: str
    created_at_utc: datetime
    schema_version: str
    coverage_status: str
    result_status: str


class ArtifactIntegrityEventInput(TypedDict):
    event_kind: str
    subject_artifact_id: str
    subject_artifact_kind: str
    subject_source_partition: str
    subject_content_hash: str
    expected_content_hash: str
    observed_content_hash: str
    expected_byte_size: int
    observed_byte_size: int
    redacted_detail: str
    observed_at_utc: datetime


class ArtifactIntegrityEventRow(ArtifactIntegrityEventInput):
    integrity_event_id: int


class RegistrationObservationInput(TypedDict):
    observation_kind: str
    source_partition: str | None
    run_id: str | None
    attempt_id: str | None
    observed_relative_path: str | None
    observed_relative_path_hash: str | None
    expected_artifact_id: str | None
    expected_artifact_kind: str | None
    expected_source_partition: str | None
    expected_content_hash: str | None
    expected_envelope_id: str | None
    observed_artifact_id: str | None
    observed_envelope_id: str | None
    observed_content_hash: str | None
    expected_byte_size: int | None
    observed_byte_size: int | None
    redacted_detail: str
    observed_at_utc: datetime


class RegistrationObservationRow(RegistrationObservationInput):
    observation_id: int


@dataclass(frozen=True, slots=True)
class ValidatedManifestFile:
    """One canonical manifest file entry validated before persistence."""

    ordinal: int
    link_id: str
    artifact_id: str
    relative_path: str
    byte_size: int
    media_type: str
    content_encoding: str | None
    http_status: int
    body_complete: bool
    termination_reason: str


@dataclass(frozen=True, slots=True)
class ValidatedArtifactLink:
    """One canonical artifact-link journal record owned by the consumer port."""

    link_id: str
    acquisition_intent_id: str
    ordinal: int
    artifact_id: str
    artifact_kind: str
    media_type: str
    content_encoding: str | None
    http_status: int
    byte_size: int
    body_complete: bool
    termination_reason: str
    observed_at_utc: datetime
    schema_version: str


@dataclass(frozen=True, slots=True)
class ValidatedManifest:
    """Canonical manifest projections independently validated by the consumer."""

    manifest_id: str
    manifest_schema_version: str
    retention_policy_id: str
    source_type: str
    acquisition_intent_id: str
    request_identity: str
    started_at_utc: datetime
    completed_at_utc: datetime
    record_count: int
    execution_status: str
    coverage_status: str
    result_status: str
    attempts_used: int
    pages_completed: int
    truncated: bool
    warning_codes: tuple[str, ...]
    files: tuple[ValidatedManifestFile, ...]
    connector_name: str
    connector_version: str
    source_record_schema_version: str
    code_revision: str


@dataclass(frozen=True, slots=True)
class ValidatedAcquisitionEnvelope:
    """Validated acquisition-envelope projections compared before any SQL."""

    attempt: ResearchRunAttemptRow
    publications: tuple[PublicationVersionRow, ...]
    publication_memberships: tuple[SourceSnapshotPublicationRow, ...]
    lineage: tuple[ArtifactLineageRow, ...]


@dataclass(frozen=True, slots=True)
class ValidatedReplay:
    """Port result after canonical manifest and exact raw-byte verification."""

    manifest: ValidatedManifest
    artifact_links: tuple[ValidatedArtifactLink, ...]
    publications: tuple[PublicationVersionRow, ...]
    publication_memberships: tuple[SourceSnapshotPublicationRow, ...]
    lineage: tuple[ArtifactLineageRow, ...]
    attempt: ResearchRunAttemptRow


class SnapshotReplayPort(Protocol):
    """Consumer-owned port that verifies canonical and raw bytes before returning."""

    def load_verified_snapshot(
        self,
        *,
        manifest_relative_path: str,
        expected_manifest_id: str,
    ) -> ValidatedReplay:
        """Return DTOs only after exact manifest/raw byte and hash verification."""


@dataclass(frozen=True, slots=True)
class AcquisitionRegistration:
    """Complete database metadata for one acquisition transaction."""

    artifacts: tuple[ArtifactRow, ...]
    snapshot: SourceSnapshotRow
    files: tuple[SnapshotFileRow, ...]
    memberships: tuple[SourceSnapshotFileRow, ...]
    warnings: tuple[SnapshotWarningRow, ...]
    publications: tuple[PublicationVersionRow, ...]
    publication_memberships: tuple[SourceSnapshotPublicationRow, ...]
    lineage: tuple[ArtifactLineageRow, ...]
    attempt: ResearchRunAttemptRow
    manifest: ValidatedManifest
    artifact_links: tuple[ValidatedArtifactLink, ...]
    envelope: ValidatedAcquisitionEnvelope
    observations: tuple[RegistrationObservationInput, ...] = ()


@dataclass(frozen=True, slots=True)
class RunReportRegistration:
    """Complete database metadata for the separate final transaction."""

    artifacts: tuple[ArtifactRow, ...]
    run: ResearchRunRow
    report: ResearchReportRow
    lineage: tuple[ArtifactLineageRow, ...]
    acquisition_references: tuple[tuple[int, str], ...]
    observations: tuple[RegistrationObservationInput, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    """Complete immutable snapshot metadata and ordered children."""

    snapshot: SourceSnapshotRow
    files: tuple[SnapshotFileRow, ...]
    memberships: tuple[SourceSnapshotFileRow, ...]
    warnings: tuple[SnapshotWarningRow, ...]
    publications: tuple[PublicationVersionRow, ...]
    publication_memberships: tuple[SourceSnapshotPublicationRow, ...]
    lineage: tuple[ArtifactLineageRow, ...]
    attempt: ResearchRunAttemptRow | None


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Complete immutable run metadata."""

    run: ResearchRunRow
    attempts: tuple[ResearchRunAttemptRow, ...]
    report: ResearchReportRow | None


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """Verified replay result with no database- or storage-native objects."""

    metadata: SnapshotMetadata
    replay: ValidatedReplay


class PersistenceConflict(RuntimeError):
    """An immutable identity already exists with different persisted content."""

    def __init__(self, table: str, constraint: str | None) -> None:
        self.table = table
        self.constraint = constraint
        suffix = f" ({constraint})" if constraint else ""
        super().__init__(f"immutable persistence conflict for {table}{suffix}")


class PersistenceCapacityError(RuntimeError):
    """A frozen table capacity would be exceeded."""


class PersistenceIntegrityError(RuntimeError):
    """Validated replay or acquisition provenance differs from persisted metadata."""


@dataclass(frozen=True, slots=True)
class _TableSpec:
    table: Table
    identity_columns: tuple[str, ...]
    comparison_columns: tuple[str, ...]
    capacity: int
    generated_id: str | None = None

    @property
    def unique_constraint_names(self) -> frozenset[str]:
        return frozenset(
            str(constraint.name)
            for constraint in self.table.constraints
            if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
            and constraint.name is not None
        )

    @property
    def identity_constraint_name(self) -> str | None:
        matches = tuple(
            str(constraint.name)
            for constraint in self.table.constraints
            if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
            and constraint.name is not None
            and tuple(column.name for column in constraint.columns) == self.identity_columns
        )
        return matches[0] if len(matches) == 1 else None


def _columns(table: Table, *, exclude: frozenset[str] = frozenset()) -> tuple[str, ...]:
    return tuple(column.name for column in table.columns if column.name not in exclude)


_SPECS = {
    "artifact": _TableSpec(models.artifact, ("artifact_id",), _columns(models.artifact), 708),
    "source_snapshot": _TableSpec(
        models.source_snapshot, ("snapshot_id",), _columns(models.source_snapshot), 101
    ),
    "snapshot_file": _TableSpec(
        models.snapshot_file, ("link_id",), _columns(models.snapshot_file), 404
    ),
    "source_snapshot_file": _TableSpec(
        models.source_snapshot_file,
        ("snapshot_id", "ordinal"),
        _columns(models.source_snapshot_file),
        404,
    ),
    "snapshot_warning": _TableSpec(
        models.snapshot_warning,
        ("snapshot_id", "warning_ordinal"),
        _columns(models.snapshot_warning),
        12_928,
    ),
    "publication_version": _TableSpec(
        models.publication_version,
        ("publication_version_id",),
        _columns(models.publication_version),
        100,
    ),
    "source_snapshot_publication": _TableSpec(
        models.source_snapshot_publication,
        ("snapshot_id", "publication_ordinal"),
        _columns(models.source_snapshot_publication),
        100,
    ),
    "artifact_lineage": _TableSpec(
        models.artifact_lineage,
        tuple(column.name for column in models.artifact_lineage.primary_key.columns),
        _columns(models.artifact_lineage),
        1_210,
    ),
    "research_run": _TableSpec(models.research_run, ("run_id",), _columns(models.research_run), 1),
    "research_run_attempt": _TableSpec(
        models.research_run_attempt,
        ("attempt_id",),
        _columns(models.research_run_attempt),
        101,
    ),
    "research_report": _TableSpec(
        models.research_report, ("report_id",), _columns(models.research_report), 1
    ),
    "artifact_integrity_event": _TableSpec(
        models.artifact_integrity_event,
        (
            "subject_artifact_id",
            "subject_artifact_kind",
            "subject_source_partition",
            "subject_content_hash",
            "event_kind",
            "observed_content_hash",
            "observed_byte_size",
            "observed_at_utc",
        ),
        _columns(models.artifact_integrity_event, exclude=frozenset({"integrity_event_id"})),
        13_056,
        "integrity_event_id",
    ),
    "registration_observation": _TableSpec(
        models.registration_observation,
        (
            "observation_kind",
            "source_partition",
            "run_id",
            "attempt_id",
            "observed_relative_path_hash",
            "expected_artifact_id",
            "expected_artifact_kind",
            "expected_source_partition",
            "expected_content_hash",
            "expected_envelope_id",
            "observed_artifact_id",
            "observed_envelope_id",
            "observed_content_hash",
            "expected_byte_size",
            "observed_byte_size",
            "observed_at_utc",
        ),
        _columns(models.registration_observation, exclude=frozenset({"observation_id"})),
        13_056,
        "observation_id",
    ),
}


def _values(row: Mapping[str, object]) -> dict[str, object]:
    return dict(row)


def _normalize(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _is_unique_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == "23505"


def _identity_clause(spec: _TableSpec, values: Mapping[str, object]) -> sa.ColumnElement[bool]:
    clauses = [
        spec.table.c[name].is_not_distinct_from(values[name]) for name in spec.identity_columns
    ]
    return sa.and_(*clauses)


def _same_persisted_row(
    spec: _TableSpec,
    existing: Mapping[str, object],
    expected: Mapping[str, object],
) -> bool:
    return all(
        _normalize(existing[name]) == _normalize(expected[name]) for name in spec.comparison_columns
    )


def _safe_identity(spec: _TableSpec, values: Mapping[str, object]) -> str:
    identity = "|".join(str(values[name]) for name in spec.identity_columns)
    return f"sha256:{sha256(identity.encode('utf-8')).hexdigest()}"


class PersistenceRepository:
    """Own synchronous transactions and never expose SQLAlchemy objects."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._engine = _create_engine(settings)

    @classmethod
    def _from_engine_for_testing(cls, engine: Engine) -> PersistenceRepository:
        repository = cls.__new__(cls)
        repository._engine = engine
        return repository

    def close(self) -> None:
        """Dispose pooled connections without changing persisted data."""

        self._engine.dispose()

    def _lock_and_check_capacity(
        self,
        connection: Connection,
        spec: _TableSpec,
        values: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        connection.execute(
            sa.text(f'LOCK TABLE "{models.SCHEMA}"."{spec.table.name}" IN SHARE ROW EXCLUSIVE MODE')
        )
        count = connection.scalar(sa.select(sa.func.count()).select_from(spec.table))
        if count is None or count < spec.capacity:
            return None
        existing = (
            connection.execute(sa.select(spec.table).where(_identity_clause(spec, values)))
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            stored = dict(existing)
            if _same_persisted_row(spec, stored, values):
                return stored
            raise PersistenceConflict(spec.table.name, spec.identity_constraint_name)
        raise PersistenceCapacityError(
            f"frozen capacity reached for {spec.table.name}: {spec.capacity}"
        )

    def _insert_or_verify(
        self,
        connection: Connection,
        spec: _TableSpec,
        values: Mapping[str, object],
        *,
        method: str,
    ) -> dict[str, object]:
        if set(values) != set(spec.comparison_columns):
            raise ValueError(f"{spec.table.name} input must contain every persisted column")
        at_capacity = self._lock_and_check_capacity(connection, spec, values)
        if at_capacity is not None:
            result = dict(at_capacity)
            logger.info(
                "immutable persistence replay",
                extra={
                    "method": method,
                    "table": spec.table.name,
                    "identity": _safe_identity(spec, values),
                    "outcome": "identical_existing",
                },
            )
            return result

        statement = spec.table.insert().values(**values)
        if spec.generated_id is not None:
            statement = statement.returning(spec.table.c[spec.generated_id])
        try:
            with connection.begin_nested():
                returned = connection.execute(statement)
                generated = returned.scalar_one() if spec.generated_id is not None else None
        except IntegrityError as error:
            constraint = _constraint_name(error)
            if not _is_unique_violation(error) or constraint not in spec.unique_constraint_names:
                raise
            existing = (
                connection.execute(sa.select(spec.table).where(_identity_clause(spec, values)))
                .mappings()
                .one_or_none()
            )
            if existing is None or not _same_persisted_row(spec, dict(existing), values):
                raise PersistenceConflict(spec.table.name, constraint) from None
            result = dict(existing)
            logger.info(
                "immutable persistence replay",
                extra={
                    "method": method,
                    "table": spec.table.name,
                    "identity": _safe_identity(spec, values),
                    "outcome": "identical_existing",
                },
            )
            return result

        result = dict(values)
        if spec.generated_id is not None:
            result[spec.generated_id] = generated
        logger.info(
            "immutable persistence insert",
            extra={
                "method": method,
                "table": spec.table.name,
                "identity": _safe_identity(spec, values),
                "outcome": "inserted",
            },
        )
        return result

    def insert_or_verify_artifact(self, artifact: ArtifactRow) -> ArtifactRow:
        """Insert immutable artifact metadata or verify an identical replay."""

        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["artifact"],
                _values(artifact),
                method="insert_or_verify_artifact",
            )
        return cast(ArtifactRow, stored)

    def insert_or_verify_m1b(
        self,
        table_name: str,
        row: Mapping[str, object],
    ) -> dict[str, object]:
        """Insert one complete frozen M1B row or verify an exact immutable replay."""

        if table_name not in models.M1B_TABLE_ORDER:
            raise ValueError("table_name is outside the frozen DM002 persistence inventory")
        if table_name in _SPECIALIZED_DAILYMED_TABLES:
            raise ValueError(
                f"{table_name} requires its specialized authoritative repository method"
            )
        table = models.metadata.tables[f"{models.SCHEMA}.{table_name}"]
        expected_columns = tuple(column.name for column in table.columns)
        if set(row) != set(expected_columns):
            raise ValueError(f"{table_name} input must contain every persisted column exactly")
        values = dict(row)
        self._validate_m1b_row(table_name, values)
        with self._engine.begin() as connection:
            return self._insert_or_verify_m1b_connection(connection, table_name, table, values)

    @staticmethod
    def _insert_or_verify_m1b_connection(
        connection: Connection,
        table_name: str,
        table: Table,
        values: dict[str, object],
    ) -> dict[str, object]:
        expected_columns = tuple(column.name for column in table.columns)
        identity = tuple(column.name for column in table.primary_key.columns)
        predicate = sa.and_(
            *(table.c[name].is_not_distinct_from(values[name]) for name in identity)
        )
        existing = connection.execute(sa.select(table).where(predicate)).mappings().one_or_none()
        if existing is not None:
            stored = dict(existing)
            if all(
                _normalize(stored[name]) == _normalize(values[name]) for name in expected_columns
            ):
                return stored
            constraint_name = table.primary_key.name
            raise PersistenceConflict(
                table_name,
                constraint_name if isinstance(constraint_name, str) else None,
            )
        try:
            with connection.begin_nested():
                connection.execute(table.insert().values(**values))
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            existing = (
                connection.execute(sa.select(table).where(predicate)).mappings().one_or_none()
            )
            if existing is None:
                raise PersistenceConflict(table_name, _constraint_name(error)) from None
            stored = dict(existing)
            if not all(
                _normalize(stored[name]) == _normalize(values[name]) for name in expected_columns
            ):
                raise PersistenceConflict(table_name, _constraint_name(error)) from None
            return stored
        return values

    @staticmethod
    def _validate_m1b_row(
        table_name: str,
        values: Mapping[str, object],
        *,
        authoritative_decision_context: bool = False,
    ) -> None:
        if table_name == "m1b_artifacts":
            byte_size = values["byte_size"]
            if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0:
                raise ValueError("M1B artifact byte_size must be a nonnegative integer")
            zero_allowed = values["artifact_kind"] in {
                "pubmed_http_response",
                "dailymed_http_response",
                "faers_http_response",
            }
            if byte_size == 0 and not zero_allowed:
                raise ValueError("only exact retained source-response artifacts may be zero bytes")
            if values["artifact_kind"] == "dailymed_spl_xml":
                content_hash = values["content_hash"]
                if not isinstance(content_hash, str) or not content_hash.startswith("sha256:"):
                    raise ValueError("DailyMed SPL artifact content hash is invalid")
                digest = content_hash.removeprefix("sha256:")
                expected_path = f"dailymed/sha256/{digest}.xml"
                if (
                    values["source_partition"] != "dailymed"
                    or values["artifact_id"] != content_hash
                    or values["media_type"] != "application/xml"
                    or values["relative_storage_label"] != expected_path
                    or values["schema_version"] != "m1b.dailymed.spl-artifact.v1"
                    or values["corpus_id"] is not None
                    or values["corpus_version"] is not None
                    or values["split"] is not None
                ):
                    raise ValueError("DailyMed stable SPL artifact identity/path contract drift")
        if table_name == "m1b_dailymed_selection_decisions":
            if not authoritative_decision_context:
                raise ValueError(
                    "DailyMed decisions require the authoritative repository comparator"
                )
            for name in (
                "candidate_ids",
                "candidate_bindings",
                "meaningful_dimensions",
                "warning_ids",
                "warning_codes",
            ):
                value = values[name]
                if not isinstance(value, list):
                    raise ValueError(f"{name} must be a JSON array")
            for name in ("candidate_ids", "meaningful_dimensions", "warning_ids", "warning_codes"):
                value = values[name]
                if not isinstance(value, list) or value != sorted(
                    set(value), key=lambda item: str(item).encode("utf-8")
                ):
                    raise ValueError(f"{name} must be unique and bytewise sorted")
        if table_name == "m1b_dailymed_label_versions":
            PersistenceRepository._dailymed_label_version_from_row(values)
        if table_name == "m1b_dailymed_sections":
            PersistenceRepository._dailymed_section_from_row(values)
        if table_name == "m1b_dailymed_label_supersession" and (
            values["predecessor_label_version_id"] == values["successor_label_version_id"]
        ):
            raise ValueError("DailyMed supersession cannot be a self edge")

    def insert_or_verify_m1b_artifact(self, row: Mapping[str, object]) -> dict[str, object]:
        """Persist exact M1B artifact metadata without raw bytes."""

        return self.insert_or_verify_m1b("m1b_artifacts", row)

    @staticmethod
    def _require_exact_domain_row(
        row: Mapping[str, object],
        expected: Mapping[str, object],
        *,
        name: str,
    ) -> None:
        if set(row) != set(expected) or any(
            _normalize(row[key]) != _normalize(expected[key]) for key in expected
        ):
            raise ValueError(f"{name} row differs from its exact validated domain object")

    @staticmethod
    def _dailymed_label_version_from_row(
        row: Mapping[str, object],
    ) -> DailyMedLabelVersion:
        values = dict(row)
        values["source"] = SourceType.DAILYMED
        values["setid"] = str(values["setid"])
        values["spl_version"] = str(values["spl_version"])
        marketing_state = values["marketing_state"]
        if not isinstance(marketing_state, str):
            raise ValueError("DailyMed marketing_state must be a string")
        values["marketing_state"] = DailyMedMarketingState(marketing_state)
        return DailyMedLabelVersion.model_validate(values)

    @staticmethod
    def _dailymed_section_from_row(row: Mapping[str, object]) -> LabelSection:
        values = dict(row)
        values["source"] = SourceType.DAILYMED
        values["setid"] = str(values["setid"])
        values["spl_version"] = str(values["spl_version"])
        return LabelSection.model_validate(values)

    @staticmethod
    def _label_version_persisted_values(
        version: DailyMedLabelVersion,
    ) -> dict[str, object]:
        values = version.model_dump(mode="python")
        values["source"] = version.source.value
        values["spl_version"] = int(version.spl_version)
        values["marketing_state"] = version.marketing_state.value
        return values

    @staticmethod
    def _section_persisted_values(section: LabelSection) -> dict[str, object]:
        values = section.model_dump(mode="python")
        values["source"] = section.source.value
        values["spl_version"] = int(section.spl_version)
        return values

    def insert_or_verify_dailymed_selection_decision(
        self,
        row: Mapping[str, object],
        *,
        decision: LabelSelectionDecision,
        outcome: SourceOutcome,
        candidates: tuple[DailyMedCandidateLabel, ...],
        source_outcome_id: str,
        discovery_manifest_content_hash: str,
    ) -> dict[str, object]:
        """Persist one decision only after exact authoritative discovery validation."""

        decision.validate_against(
            outcome=outcome,
            candidates=candidates,
            source_outcome_id=source_outcome_id,
            discovery_manifest_content_hash=discovery_manifest_content_hash,
        )
        expected = decision.model_dump(mode="python")
        self._require_exact_domain_row(row, expected, name="DailyMed selection decision")
        table_name = "m1b_dailymed_selection_decisions"
        table = models.m1b_dailymed_selection_decisions
        values = dict(row)
        self._validate_m1b_row(
            table_name,
            values,
            authoritative_decision_context=True,
        )
        with self._engine.begin() as connection:
            return self._insert_or_verify_m1b_connection(connection, table_name, table, values)

    def insert_or_verify_dailymed_label_version(
        self, row: Mapping[str, object]
    ) -> dict[str, object]:
        """Persist one fetch-independent immutable DailyMed label version."""

        version = self._dailymed_label_version_from_row(row)
        self._require_exact_domain_row(
            row,
            self._label_version_persisted_values(version),
            name="DailyMed label version",
        )
        table_name = "m1b_dailymed_label_versions"
        table = models.m1b_dailymed_label_versions
        values = dict(row)
        self._validate_m1b_row(table_name, values)
        with self._engine.begin() as connection:
            artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == version.spl_artifact_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if artifact is None:
                raise ValueError("DailyMed label version requires its stable SPL artifact")
            artifact_values = dict(artifact)
            self._validate_m1b_row("m1b_artifacts", artifact_values)
            if (
                artifact["source_partition"] != "dailymed"
                or artifact["artifact_kind"] != "dailymed_spl_xml"
                or artifact["content_hash"] != version.content_hash
            ):
                raise ValueError("DailyMed label version stable artifact binding drift")
            return self._insert_or_verify_m1b_connection(connection, table_name, table, values)

    def insert_or_verify_dailymed_section(self, row: Mapping[str, object]) -> dict[str, object]:
        """Persist one stable canonical DailyMed section."""

        section = self._dailymed_section_from_row(row)
        self._require_exact_domain_row(
            row,
            self._section_persisted_values(section),
            name="DailyMed section",
        )
        table_name = "m1b_dailymed_sections"
        table = models.m1b_dailymed_sections
        values = dict(row)
        self._validate_m1b_row(table_name, values)
        with self._engine.begin() as connection:
            version = (
                connection.execute(
                    sa.select(models.m1b_dailymed_label_versions).where(
                        models.m1b_dailymed_label_versions.c.source == section.source.value,
                        models.m1b_dailymed_label_versions.c.setid == section.setid,
                        models.m1b_dailymed_label_versions.c.label_version_id
                        == section.label_version_id,
                        models.m1b_dailymed_label_versions.c.spl_version
                        == int(section.spl_version),
                        models.m1b_dailymed_label_versions.c.spl_artifact_id
                        == section.spl_artifact_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if version is None:
                raise ValueError("DailyMed section requires its exact stable label version")
            return self._insert_or_verify_m1b_connection(connection, table_name, table, values)

    def insert_or_verify_dailymed_supersession(
        self, row: Mapping[str, object]
    ) -> dict[str, object]:
        """Persist a DailyMed supersession edge after rejecting every cycle."""

        table_name = "m1b_dailymed_label_supersession"
        table = models.m1b_dailymed_label_supersession
        expected_columns = {column.name for column in table.columns}
        if set(row) != expected_columns:
            raise ValueError(f"{table_name} input must contain every persisted column exactly")
        values = dict(row)
        self._validate_m1b_row(table_name, values)
        source = values["source"]
        setid = values["setid"]
        predecessor = values["predecessor_label_version_id"]
        successor = values["successor_label_version_id"]
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(f'LOCK TABLE "{models.SCHEMA}"."{table.name}" IN SHARE ROW EXCLUSIVE MODE')
            )
            edges = connection.execute(
                sa.select(
                    table.c.predecessor_label_version_id,
                    table.c.successor_label_version_id,
                ).where(table.c.source == source, table.c.setid == setid)
            )
            adjacency: dict[object, set[object]] = {}
            for existing_predecessor, existing_successor in edges:
                adjacency.setdefault(existing_predecessor, set()).add(existing_successor)
            pending = [successor]
            seen: set[object] = set()
            while pending:
                current = pending.pop()
                if current == predecessor:
                    raise ValueError("DailyMed supersession would create a cycle")
                if current not in seen:
                    seen.add(current)
                    pending.extend(adjacency.get(current, ()))
            return self._insert_or_verify_m1b_connection(connection, table_name, table, values)

    def insert_or_verify_publication_version(
        self,
        publication: PublicationVersionRow,
    ) -> PublicationVersionRow:
        """Validate canonical publication bytes, then insert or verify."""

        self._validate_publication(publication)
        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["publication_version"],
                _values(publication),
                method="insert_or_verify_publication_version",
            )
        return cast(PublicationVersionRow, stored)

    @staticmethod
    def _validate_publication(publication: PublicationVersionRow) -> None:
        raw = canonical_json(publication["version_payload"]).encode("utf-8")
        if len(raw) > PUBLICATION_BYTE_CAPACITY:
            raise ValueError("publication canonical bytes exceed 31,457,280 bytes")
        content_hash = f"sha256:{sha256(raw).hexdigest()}"
        if not (
            content_hash
            == publication["content_hash"]
            == publication["publication_artifact_id"]
            == publication["publication_artifact_hash"]
        ):
            raise ValueError("publication canonical bytes do not match artifact identity")
        expected_id = f"pubmed:{publication['pmid']}:sha256:{content_hash.removeprefix('sha256:')}"
        if publication["publication_version_id"] != expected_id:
            raise ValueError("publication version identity does not match canonical bytes")
        expected_time = publication["status_retrieved_at_utc"].strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        status = publication["version_payload"].get("publication_status")
        if not isinstance(status, dict) or status.get("retrieved_as_of") != expected_time:
            raise ValueError("publication status timestamp projection does not match")
        bounds = ExecutionBounds(
            max_query_characters=512,
            max_pages=1,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=60,
        )
        outcome = SourceOutcome(
            source=SourceType.PUBMED,
            query_id="query:persistence-publication-validation",
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            configured_bounds=bounds,
            valid_result_count=1,
            pages_completed=1,
            truncated=False,
        )
        validation_provenance = Provenance(
            source=SourceType.PUBMED,
            source_record_id=publication["pmid"],
            query_id=outcome.query_id,
            source_lookup_key=f"pubmed:{publication['pmid']}",
            retrieved_at=publication["status_retrieved_at_utc"],
            connector_version="persistence-publication-validation",
            content_hash=publication["content_hash"],
            source_outcome=outcome,
            configured_bounds=bounds,
        )
        try:
            record = PublicationRecord.model_validate_json(
                canonical_json(
                    {
                        **publication["version_payload"],
                        "provenance": validation_provenance,
                        "content_hash": publication["content_hash"],
                        "publication_version_id": publication["publication_version_id"],
                    }
                )
            )
        except ValueError as error:
            raise ValueError("publication payload violates frozen domain contract") from error
        if canonical_json(record.version_payload()) != canonical_json(
            publication["version_payload"]
        ):
            raise ValueError("publication payload differs after domain validation")
        if (
            record.source_type.value,
            record.pmid,
            record.content_hash,
            record.publication_version_id,
            record.publication_status.publication_status_identity,
            record.publication_status.status.value,
            record.publication_status.retrieved_as_of,
        ) != (
            publication["source"],
            publication["pmid"],
            publication["content_hash"],
            publication["publication_version_id"],
            publication["publication_status_identity"],
            publication["publication_status"],
            publication["status_retrieved_at_utc"],
        ):
            raise ValueError("publication domain projections differ from persisted row")

    def insert_or_verify_integrity_event(
        self,
        event: ArtifactIntegrityEventInput,
    ) -> ArtifactIntegrityEventRow:
        """Insert a registered-artifact integrity event or verify replay."""

        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["artifact_integrity_event"],
                _values(event),
                method="insert_or_verify_integrity_event",
            )
        return cast(ArtifactIntegrityEventRow, stored)

    def insert_or_verify_registration_observation(
        self,
        observation: RegistrationObservationInput,
    ) -> RegistrationObservationRow:
        """Insert one null-safe observation or verify complete equality."""

        self._validate_observed_path_hash(observation)
        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["registration_observation"],
                _values(observation),
                method="insert_or_verify_registration_observation",
            )
        return cast(RegistrationObservationRow, stored)

    @staticmethod
    def _validate_observed_path_hash(observation: RegistrationObservationInput) -> None:
        path = observation["observed_relative_path"]
        path_hash = observation["observed_relative_path_hash"]
        if path is None and path_hash is None:
            return
        if path is None or path_hash is None:
            raise ValueError("observed path and path hash must be present together")
        expected = f"sha256:{sha256(path.encode('utf-8')).hexdigest()}"
        if path_hash != expected:
            raise ValueError("observed path hash does not match exact UTF-8 path")

    def register_acquisition(self, registration: AcquisitionRegistration) -> SourceSnapshotRow:
        """Atomically persist or verify one complete acquisition graph."""

        self._validate_acquisition(registration)
        with self._engine.begin() as connection:
            for artifact_row in registration.artifacts:
                self._insert_or_verify(
                    connection,
                    _SPECS["artifact"],
                    _values(artifact_row),
                    method="register_acquisition",
                )
            self._insert_or_verify(
                connection,
                _SPECS["source_snapshot"],
                _values(registration.snapshot),
                method="register_acquisition",
            )
            for table_name, rows in (
                ("snapshot_file", registration.files),
                ("source_snapshot_file", registration.memberships),
                ("snapshot_warning", registration.warnings),
                ("publication_version", registration.publications),
                ("source_snapshot_publication", registration.publication_memberships),
                ("artifact_lineage", registration.lineage),
            ):
                for child_row in rows:
                    self._insert_or_verify(
                        connection,
                        _SPECS[table_name],
                        _values(child_row),
                        method="register_acquisition",
                    )
            self._insert_or_verify(
                connection,
                _SPECS["research_run_attempt"],
                _values(registration.attempt),
                method="register_acquisition",
            )
            for observation in registration.observations:
                self._validate_observed_path_hash(observation)
                self._insert_or_verify(
                    connection,
                    _SPECS["registration_observation"],
                    _values(observation),
                    method="register_acquisition",
                )
        return registration.snapshot

    @staticmethod
    def _validate_acquisition(registration: AcquisitionRegistration) -> None:
        snapshot = registration.snapshot
        if not (
            snapshot["snapshot_id"]
            == snapshot["manifest_artifact_id"]
            == snapshot["manifest_content_hash"]
        ):
            raise ValueError("snapshot identity must equal exact manifest identity")
        manifest = registration.manifest
        PersistenceRepository._compare_manifest_snapshot(manifest, snapshot, error_type=ValueError)
        expected_files, expected_memberships = PersistenceRepository._expected_file_rows(
            manifest, registration.artifact_links, snapshot
        )
        PersistenceRepository._require_equal(
            registration.files, expected_files, "snapshot files differ from validated manifest"
        )
        PersistenceRepository._require_equal(
            registration.memberships,
            expected_memberships,
            "snapshot memberships differ from validated manifest",
        )
        expected_warnings = tuple(
            SnapshotWarningRow(
                snapshot_id=snapshot["snapshot_id"],
                warning_ordinal=ordinal,
                warning_code=code,
            )
            for ordinal, code in enumerate(manifest.warning_codes)
        )
        PersistenceRepository._require_equal(
            registration.warnings,
            expected_warnings,
            "snapshot warnings differ from validated manifest",
        )
        PersistenceRepository._compare_attempt_manifest(
            registration.attempt, manifest, snapshot, error_type=ValueError
        )
        PersistenceRepository._require_equal(
            registration.attempt,
            registration.envelope.attempt,
            "attempt differs from validated acquisition envelope",
        )
        expected_publication_memberships = tuple(
            SourceSnapshotPublicationRow(
                snapshot_id=snapshot["snapshot_id"],
                publication_ordinal=ordinal,
                pmid=publication["pmid"],
                publication_version_id=publication["publication_version_id"],
                source=publication["source"],
                publication_content_hash=publication["content_hash"],
            )
            for ordinal, publication in enumerate(registration.publications)
        )
        PersistenceRepository._require_equal(
            registration.publications,
            registration.envelope.publications,
            "publications differ from validated acquisition envelope",
        )
        PersistenceRepository._require_equal(
            registration.publication_memberships,
            expected_publication_memberships,
            "publication memberships differ from validated publications",
        )
        PersistenceRepository._require_equal(
            registration.publication_memberships,
            registration.envelope.publication_memberships,
            "publication memberships differ from validated acquisition envelope",
        )
        PersistenceRepository._require_equal(
            registration.lineage,
            registration.envelope.lineage,
            "lineage differs from validated acquisition envelope",
        )
        PersistenceRepository._validate_acquisition_outcome(registration)
        PersistenceRepository._validate_acquisition_artifacts(registration)
        for publication in registration.publications:
            PersistenceRepository._validate_publication(publication)

    @staticmethod
    def _require_equal(actual: object, expected: object, message: str) -> None:
        if _normalize(actual) != _normalize(expected):
            raise ValueError(message)

    @staticmethod
    def _compare_manifest_snapshot(
        manifest: ValidatedManifest,
        snapshot: SourceSnapshotRow,
        *,
        error_type: type[ValueError] | type[PersistenceIntegrityError],
    ) -> None:
        pairs = {
            "identity": (manifest.manifest_id, snapshot["snapshot_id"]),
            "source": (manifest.source_type, snapshot["source"]),
            "acquisition intent": (
                manifest.acquisition_intent_id,
                snapshot["acquisition_intent_id"],
            ),
            "request identity": (manifest.request_identity, snapshot["request_identity"]),
            "execution status": (manifest.execution_status, snapshot["execution_status"]),
            "coverage status": (manifest.coverage_status, snapshot["coverage_status"]),
            "result status": (manifest.result_status, snapshot["result_status"]),
            "record count": (manifest.record_count, snapshot["record_count"]),
            "attempts used": (manifest.attempts_used, snapshot["attempts_used"]),
            "pages completed": (manifest.pages_completed, snapshot["pages_completed"]),
            "truncated": (manifest.truncated, snapshot["truncated"]),
            "started time": (manifest.started_at_utc, snapshot["started_at_utc"]),
            "completed time": (manifest.completed_at_utc, snapshot["completed_at_utc"]),
            "connector name": (manifest.connector_name, snapshot["connector_name"]),
            "connector version": (manifest.connector_version, snapshot["connector_version"]),
            "manifest schema": (
                manifest.manifest_schema_version,
                snapshot["manifest_schema_version"],
            ),
            "source record schema": (
                manifest.source_record_schema_version,
                snapshot["source_record_schema_version"],
            ),
            "code revision": (manifest.code_revision, snapshot["code_revision"]),
            "retention policy": (manifest.retention_policy_id, snapshot["retention_policy_id"]),
        }
        for dimension, (actual, expected) in pairs.items():
            if _normalize(actual) != _normalize(expected):
                raise error_type(f"validated manifest {dimension} differs from snapshot")

    @staticmethod
    def _expected_file_rows(
        manifest: ValidatedManifest,
        links: tuple[ValidatedArtifactLink, ...],
        snapshot: SourceSnapshotRow,
    ) -> tuple[tuple[SnapshotFileRow, ...], tuple[SourceSnapshotFileRow, ...]]:
        if len(manifest.files) != len(links):
            raise ValueError("artifact link count differs from validated manifest")
        files: list[SnapshotFileRow] = []
        memberships: list[SourceSnapshotFileRow] = []
        for item, link in zip(manifest.files, links, strict=True):
            manifest_projection = (
                item.ordinal,
                item.link_id,
                item.artifact_id,
                item.byte_size,
                item.media_type,
                item.content_encoding,
                item.http_status,
                item.body_complete,
                item.termination_reason,
            )
            link_projection = (
                link.ordinal,
                link.link_id,
                link.artifact_id,
                link.byte_size,
                link.media_type,
                link.content_encoding,
                link.http_status,
                link.body_complete,
                link.termination_reason,
            )
            if manifest_projection != link_projection:
                raise ValueError("artifact link differs from validated manifest file")
            if (
                link.acquisition_intent_id != manifest.acquisition_intent_id
                or link.artifact_kind != "pubmed_http_response"
                or link.schema_version != "1.0"
            ):
                raise ValueError("artifact link provenance differs from validated manifest")
            files.append(
                SnapshotFileRow(
                    link_id=link.link_id,
                    acquisition_intent_id=link.acquisition_intent_id,
                    ordinal=link.ordinal,
                    raw_artifact_id=link.artifact_id,
                    raw_artifact_kind=link.artifact_kind,
                    raw_source_partition="pubmed",
                    raw_content_hash=link.artifact_id,
                    relative_storage_path=item.relative_path,
                    byte_size=link.byte_size,
                    media_type=link.media_type,
                    content_encoding=link.content_encoding,
                    http_status=link.http_status,
                    body_complete=link.body_complete,
                    termination_reason=link.termination_reason,
                    observed_at_utc=link.observed_at_utc,
                    schema_version=link.schema_version,
                )
            )
            memberships.append(
                SourceSnapshotFileRow(
                    snapshot_id=snapshot["snapshot_id"],
                    acquisition_intent_id=snapshot["acquisition_intent_id"],
                    ordinal=link.ordinal,
                    link_id=link.link_id,
                )
            )
        return tuple(files), tuple(memberships)

    @staticmethod
    def _compare_attempt_manifest(
        attempt: ResearchRunAttemptRow,
        manifest: ValidatedManifest,
        snapshot: SourceSnapshotRow,
        *,
        error_type: type[ValueError] | type[PersistenceIntegrityError],
    ) -> None:
        pairs = {
            "manifest identity": (attempt["manifest_id"], manifest.manifest_id),
            "acquisition intent": (
                attempt["acquisition_intent_id"],
                manifest.acquisition_intent_id,
            ),
            "source": (attempt["source"], manifest.source_type),
            "request identity": (attempt["request_identity"], manifest.request_identity),
            "started time": (attempt["started_at_utc"], manifest.started_at_utc),
            "completed time": (attempt["completed_at_utc"], manifest.completed_at_utc),
            "execution status": (attempt["execution_status"], manifest.execution_status),
            "coverage status": (attempt["coverage_status"], manifest.coverage_status),
            "result status": (attempt["result_status"], manifest.result_status),
            "record count": (attempt["valid_result_count"], manifest.record_count),
            "pages completed": (attempt["pages_completed"], manifest.pages_completed),
            "attempts used": (attempt["attempts_used"], manifest.attempts_used),
            "truncated": (attempt["truncated"], manifest.truncated),
            "warnings": (tuple(attempt["warning_codes"]), manifest.warning_codes),
            "snapshot identity": (attempt["manifest_id"], snapshot["snapshot_id"]),
        }
        for dimension, (actual, expected) in pairs.items():
            if _normalize(actual) != _normalize(expected):
                raise error_type(f"validated attempt {dimension} differs from manifest")

    @staticmethod
    def _validate_acquisition_outcome(registration: AcquisitionRegistration) -> None:
        manifest = registration.manifest
        PersistenceRepository._validate_operation_cardinality(
            operation=registration.attempt["operation"],
            manifest=manifest,
            publications=registration.publications,
            publication_memberships=registration.publication_memberships,
            lineage=registration.lineage,
            error_type=ValueError,
        )
        if manifest.coverage_status == "complete":
            if manifest.truncated or manifest.pages_completed != 1 or not manifest.files:
                raise ValueError("complete coverage requires retained terminal evidence")
            effective = manifest.files[-1]
            if (
                not effective.body_complete
                or effective.byte_size == 0
                or not 200 <= effective.http_status <= 299
            ):
                raise ValueError(
                    "complete coverage requires a terminal nonempty complete 2xx response"
                )
        if manifest.result_status == "matches" and not any(
            200 <= item.http_status <= 299 and item.byte_size > 0 for item in manifest.files
        ):
            raise ValueError("matches requires nonempty retained HTTP 2xx evidence")

    @staticmethod
    def _validate_operation_cardinality(
        *,
        operation: str,
        manifest: ValidatedManifest,
        publications: tuple[PublicationVersionRow, ...],
        publication_memberships: tuple[SourceSnapshotPublicationRow, ...],
        lineage: tuple[ArtifactLineageRow, ...],
        error_type: type[ValueError] | type[PersistenceIntegrityError],
    ) -> None:
        publication_lineage = tuple(
            row
            for row in lineage
            if row["lineage_type"]
            in {"publication_to_manifest", "acquisition_envelope_to_publication"}
            or row["parent_artifact_kind"] == "publication_record"
            or row["child_artifact_kind"] == "publication_record"
        )
        if operation == "search":
            if publications or publication_memberships or publication_lineage:
                raise error_type("search acquisition must not persist publication metadata")
            return
        if operation != "fetch":
            raise error_type("acquisition operation is not search or fetch")
        publication_count = len(publications)
        if (
            publication_count > 1
            or publication_count != manifest.record_count
            or len(publication_memberships) != publication_count
        ):
            raise error_type("fetch publication cardinality differs from validated manifest")

    @staticmethod
    def _validate_acquisition_artifacts(registration: AcquisitionRegistration) -> None:
        by_id = {row["artifact_id"]: row for row in registration.artifacts}
        snapshot = registration.snapshot
        required: list[tuple[str, str, str, str, int | None, str | None, str | None]] = [
            (
                snapshot["manifest_artifact_id"],
                snapshot["manifest_artifact_kind"],
                snapshot["manifest_source_partition"],
                snapshot["manifest_content_hash"],
                None,
                "application/json",
                None,
            ),
            (
                registration.attempt["envelope_artifact_id"],
                registration.attempt["envelope_artifact_kind"],
                registration.attempt["envelope_source_partition"],
                registration.attempt["envelope_content_hash"],
                None,
                "application/json",
                None,
            ),
        ]
        required.extend(
            (
                link.artifact_id,
                link.artifact_kind,
                "pubmed",
                link.artifact_id,
                link.byte_size,
                link.media_type,
                manifest_file.relative_path,
            )
            for link, manifest_file in zip(
                registration.artifact_links, registration.manifest.files, strict=True
            )
        )
        required.extend(
            (
                publication["publication_artifact_id"],
                publication["publication_artifact_kind"],
                publication["publication_source_partition"],
                publication["publication_artifact_hash"],
                len(canonical_json(publication["version_payload"]).encode("utf-8")),
                "application/json",
                None,
            )
            for publication in registration.publications
        )
        for artifact_id, kind, partition, content_hash, byte_size, media_type, path in required:
            artifact = by_id.get(artifact_id)
            if artifact is None or (
                artifact["artifact_kind"],
                artifact["source_partition"],
                artifact["content_hash"],
            ) != (kind, partition, content_hash):
                raise ValueError("registered artifact tuple differs from validated provenance")
            if (
                (byte_size is not None and artifact["byte_size"] != byte_size)
                or (media_type is not None and artifact["media_type"] != media_type)
                or (path is not None and artifact["relative_storage_path"] != path)
            ):
                raise ValueError("registered artifact metadata differs from validated provenance")
        if len(by_id) != len(registration.artifacts) or set(by_id) != {
            artifact_id for artifact_id, *_ in required
        }:
            raise ValueError("registered artifact set differs from validated provenance")

    def register_run_and_report(self, registration: RunReportRegistration) -> ResearchRunRow:
        """Atomically persist final run/report metadata in its own transaction."""

        self._validate_run_and_report(registration)
        with self._engine.begin() as connection:
            self._validate_durable_run_traceability(connection, registration)
            for artifact_row in registration.artifacts:
                self._insert_or_verify(
                    connection,
                    _SPECS["artifact"],
                    _values(artifact_row),
                    method="register_run_and_report",
                )
            self._insert_or_verify(
                connection,
                _SPECS["research_run"],
                _values(registration.run),
                method="register_run_and_report",
            )
            self._insert_or_verify(
                connection,
                _SPECS["research_report"],
                _values(registration.report),
                method="register_run_and_report",
            )
            for lineage_row in registration.lineage:
                self._insert_or_verify(
                    connection,
                    _SPECS["artifact_lineage"],
                    _values(lineage_row),
                    method="register_run_and_report",
                )
            for observation in registration.observations:
                self._validate_observed_path_hash(observation)
                self._insert_or_verify(
                    connection,
                    _SPECS["registration_observation"],
                    _values(observation),
                    method="register_run_and_report",
                )
        return registration.run

    @staticmethod
    def _validate_run_and_report(registration: RunReportRegistration) -> None:
        run = registration.run
        report = registration.report
        if run["report_id"] != report["report_id"]:
            raise ValueError("run and report identity binding differs")
        if run["run_id"] != report["run_id"]:
            raise ValueError("run and report run binding differs")
        if (run["coverage_status"], run["result_status"]) != (
            report["coverage_status"],
            report["result_status"],
        ):
            raise ValueError("run and report outcome binding differs")

        artifacts = {row["artifact_id"]: row for row in registration.artifacts}
        if len(artifacts) != 2 or set(artifacts) != {
            run["envelope_artifact_id"],
            report["report_artifact_id"],
        }:
            raise ValueError("run/report artifact set differs from frozen graph")
        envelope = artifacts[run["envelope_artifact_id"]]
        report_artifact = artifacts[report["report_artifact_id"]]
        if (
            envelope["artifact_kind"],
            envelope["source_partition"],
            envelope["content_hash"],
            envelope["media_type"],
        ) != (
            run["envelope_artifact_kind"],
            run["envelope_source_partition"],
            run["envelope_content_hash"],
            "application/json",
        ):
            raise ValueError("run envelope artifact differs from frozen graph")
        if (
            report_artifact["artifact_kind"],
            report_artifact["source_partition"],
            report_artifact["content_hash"],
            report_artifact["byte_size"],
            report_artifact["media_type"],
        ) != (
            report["report_artifact_kind"],
            report["report_source_partition"],
            report["report_content_hash"],
            report["report_byte_size"],
            report["report_media_type"],
        ):
            raise ValueError("report artifact differs from frozen graph")

        run_edges = tuple(
            row for row in registration.lineage if row["lineage_type"] == "run_envelope_to_report"
        )
        publication_edges = tuple(
            row for row in registration.lineage if row["lineage_type"] == "report_to_publication"
        )
        if len(run_edges) != 1 or len(run_edges) + len(publication_edges) != len(
            registration.lineage
        ):
            raise ValueError("run/report lineage types differ from frozen graph")
        expected_run_edge = ArtifactLineageRow(
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
        PersistenceRepository._require_equal(
            run_edges[0], expected_run_edge, "run envelope/report lineage differs"
        )
        if tuple(row["lineage_ordinal"] for row in publication_edges) != tuple(
            range(len(publication_edges))
        ):
            raise ValueError("report/publication lineage ordinals must be contiguous")
        if len(publication_edges) > 100:
            raise ValueError("report/publication lineage exceeds the frozen maximum")
        publication_ids: set[str] = set()
        for row in publication_edges:
            if (
                row["parent_artifact_id"],
                row["parent_artifact_kind"],
                row["parent_source_partition"],
                row["parent_content_hash"],
                row["child_artifact_kind"],
                row["child_source_partition"],
                row["child_artifact_id"],
                row["schema_version"],
            ) != (
                report_artifact["artifact_id"],
                report_artifact["artifact_kind"],
                report_artifact["source_partition"],
                report_artifact["content_hash"],
                "publication_record",
                "pubmed",
                row["child_content_hash"],
                "1.0",
            ):
                raise ValueError("report/publication lineage differs from frozen graph")
            if row["child_artifact_id"] in publication_ids:
                raise ValueError("report/publication lineage children must be unique")
            publication_ids.add(row["child_artifact_id"])
        if (run["result_status"] == "matches") != bool(publication_edges):
            raise ValueError("report/publication lineage cardinality differs from run result")

        references = registration.acquisition_references
        if not isinstance(references, tuple) or not 1 <= len(references) <= 101:
            raise ValueError("run acquisition references must contain between 1 and 101 entries")
        expected_prefix = "registration-envelope:acquisition:sha256:"
        for expected_ordinal, reference in enumerate(references):
            if (
                not isinstance(reference, tuple)
                or len(reference) != 2
                or not isinstance(reference[0], int)
                or isinstance(reference[0], bool)
                or reference[0] != expected_ordinal
                or not isinstance(reference[1], str)
                or not reference[1].startswith(expected_prefix)
                or len(reference[1]) != len(expected_prefix) + 64
                or any(character not in "0123456789abcdef" for character in reference[1][-64:])
            ):
                raise ValueError("run acquisition references must be ordered and valid")

    @staticmethod
    def _validate_durable_run_traceability(
        connection: Connection,
        registration: RunReportRegistration,
    ) -> None:
        run_id = registration.run["run_id"]
        attempts = (
            connection.execute(
                sa.select(
                    models.research_run_attempt.c.run_id,
                    models.research_run_attempt.c.acquisition_ordinal,
                    models.research_run_attempt.c.registration_envelope_id,
                    models.research_run_attempt.c.operation,
                )
                .where(models.research_run_attempt.c.run_id == run_id)
                .order_by(models.research_run_attempt.c.acquisition_ordinal)
                .limit(102)
            )
            .mappings()
            .all()
        )
        if not attempts:
            raise PersistenceIntegrityError("final run has no durable acquisition attempts")
        if len(attempts) > 101 or any(row["run_id"] != run_id for row in attempts):
            raise PersistenceIntegrityError("durable acquisition attempts exceed the run boundary")
        if not any(
            row["acquisition_ordinal"] == 0 and row["operation"] == "search" for row in attempts
        ):
            raise PersistenceIntegrityError(
                "final run has no durable search attempt at ordinal zero"
            )
        ordinals = tuple(row["acquisition_ordinal"] for row in attempts)
        if ordinals != tuple(range(len(attempts))):
            raise PersistenceIntegrityError(
                "durable acquisition attempt ordinals are not contiguous"
            )
        durable_references = tuple(
            (row["acquisition_ordinal"], row["registration_envelope_id"]) for row in attempts
        )
        if durable_references != registration.acquisition_references:
            raise PersistenceIntegrityError(
                "run acquisition references differ from durable acquisition attempts"
            )

        cited_bindings = tuple(
            (
                row["child_artifact_id"],
                row["child_artifact_kind"],
                row["child_source_partition"],
                row["child_content_hash"],
            )
            for row in registration.lineage
            if row["lineage_type"] == "report_to_publication"
        )
        if not cited_bindings:
            return
        publication_binding = sa.tuple_(
            models.publication_version.c.publication_artifact_id,
            models.publication_version.c.publication_artifact_kind,
            models.publication_version.c.publication_source_partition,
            models.publication_version.c.publication_artifact_hash,
        )
        reachable = set(
            connection.execute(
                sa.select(
                    models.publication_version.c.publication_artifact_id,
                    models.publication_version.c.publication_artifact_kind,
                    models.publication_version.c.publication_source_partition,
                    models.publication_version.c.publication_artifact_hash,
                )
                .select_from(models.research_run_attempt)
                .join(
                    models.source_snapshot,
                    sa.and_(
                        models.research_run_attempt.c.manifest_id
                        == models.source_snapshot.c.snapshot_id,
                        models.research_run_attempt.c.acquisition_intent_id
                        == models.source_snapshot.c.acquisition_intent_id,
                    ),
                )
                .join(
                    models.source_snapshot_publication,
                    models.source_snapshot.c.snapshot_id
                    == models.source_snapshot_publication.c.snapshot_id,
                )
                .join(
                    models.publication_version,
                    sa.and_(
                        models.source_snapshot_publication.c.publication_version_id
                        == models.publication_version.c.publication_version_id,
                        models.source_snapshot_publication.c.source
                        == models.publication_version.c.source,
                        models.source_snapshot_publication.c.pmid
                        == models.publication_version.c.pmid,
                        models.source_snapshot_publication.c.publication_content_hash
                        == models.publication_version.c.content_hash,
                    ),
                )
                .where(
                    models.research_run_attempt.c.run_id == run_id,
                    publication_binding.in_(cited_bindings),
                )
                .distinct()
                .limit(101)
            ).all()
        )
        if reachable != set(cited_bindings):
            raise PersistenceIntegrityError(
                "report publication lineage is not owned by a durable current-run acquisition"
            )

    def get_artifact(self, artifact_id: str) -> ArtifactRow | None:
        """Return complete immutable artifact metadata."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.artifact).where(models.artifact.c.artifact_id == artifact_id)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else cast(ArtifactRow, dict(row))

    def get_publication_version(
        self,
        publication_version_id: str,
    ) -> PublicationVersionRow | None:
        """Return complete projected publication metadata and JSON value."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.publication_version).where(
                        models.publication_version.c.publication_version_id
                        == publication_version_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else cast(PublicationVersionRow, dict(row))

    def get_snapshot(self, snapshot_id: str) -> SnapshotMetadata | None:
        """Return complete snapshot metadata and deterministically ordered children."""

        with self._engine.connect() as connection:
            snapshot = (
                connection.execute(
                    sa.select(models.source_snapshot).where(
                        models.source_snapshot.c.snapshot_id == snapshot_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if snapshot is None:
                return None
            files = (
                connection.execute(
                    sa.select(models.snapshot_file)
                    .join(
                        models.source_snapshot_file,
                        models.snapshot_file.c.link_id == models.source_snapshot_file.c.link_id,
                    )
                    .where(models.source_snapshot_file.c.snapshot_id == snapshot_id)
                    .order_by(models.source_snapshot_file.c.ordinal)
                )
                .mappings()
                .all()
            )
            memberships = (
                connection.execute(
                    sa.select(models.source_snapshot_file)
                    .where(models.source_snapshot_file.c.snapshot_id == snapshot_id)
                    .order_by(models.source_snapshot_file.c.ordinal)
                )
                .mappings()
                .all()
            )
            warnings = (
                connection.execute(
                    sa.select(models.snapshot_warning)
                    .where(models.snapshot_warning.c.snapshot_id == snapshot_id)
                    .order_by(models.snapshot_warning.c.warning_ordinal)
                )
                .mappings()
                .all()
            )
            publications = (
                connection.execute(
                    sa.select(models.publication_version)
                    .join(
                        models.source_snapshot_publication,
                        models.publication_version.c.publication_version_id
                        == models.source_snapshot_publication.c.publication_version_id,
                    )
                    .where(models.source_snapshot_publication.c.snapshot_id == snapshot_id)
                    .order_by(models.source_snapshot_publication.c.publication_ordinal)
                )
                .mappings()
                .all()
            )
            publication_memberships = (
                connection.execute(
                    sa.select(models.source_snapshot_publication)
                    .where(models.source_snapshot_publication.c.snapshot_id == snapshot_id)
                    .order_by(models.source_snapshot_publication.c.publication_ordinal)
                )
                .mappings()
                .all()
            )
            attempt = (
                connection.execute(
                    sa.select(models.research_run_attempt).where(
                        models.research_run_attempt.c.manifest_id == snapshot_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            raw_artifact_ids = tuple(row["raw_artifact_id"] for row in files)
            publication_artifact_ids = tuple(row["publication_artifact_id"] for row in publications)
            lineage_conditions: list[sa.ColumnElement[bool]] = []
            if raw_artifact_ids:
                lineage_conditions.append(
                    sa.and_(
                        models.artifact_lineage.c.lineage_type == "manifest_to_raw_response",
                        models.artifact_lineage.c.parent_artifact_id == snapshot_id,
                        models.artifact_lineage.c.child_artifact_id.in_(raw_artifact_ids),
                    )
                )
            if publication_artifact_ids:
                lineage_conditions.append(
                    sa.and_(
                        models.artifact_lineage.c.lineage_type == "publication_to_manifest",
                        models.artifact_lineage.c.parent_artifact_id.in_(publication_artifact_ids),
                        models.artifact_lineage.c.child_artifact_id == snapshot_id,
                    )
                )
            if attempt is not None:
                envelope_id = attempt["envelope_artifact_id"]
                lineage_conditions.append(
                    sa.and_(
                        models.artifact_lineage.c.lineage_type
                        == "acquisition_envelope_to_manifest",
                        models.artifact_lineage.c.parent_artifact_id == envelope_id,
                        models.artifact_lineage.c.child_artifact_id == snapshot_id,
                    )
                )
                if raw_artifact_ids:
                    lineage_conditions.append(
                        sa.and_(
                            models.artifact_lineage.c.lineage_type
                            == "acquisition_envelope_to_raw_response",
                            models.artifact_lineage.c.parent_artifact_id == envelope_id,
                            models.artifact_lineage.c.child_artifact_id.in_(raw_artifact_ids),
                        )
                    )
                if publication_artifact_ids:
                    lineage_conditions.append(
                        sa.and_(
                            models.artifact_lineage.c.lineage_type
                            == "acquisition_envelope_to_publication",
                            models.artifact_lineage.c.parent_artifact_id == envelope_id,
                            models.artifact_lineage.c.child_artifact_id.in_(
                                publication_artifact_ids
                            ),
                        )
                    )
            lineage = (
                []
                if not lineage_conditions
                else connection.execute(
                    sa.select(models.artifact_lineage)
                    .where(sa.or_(*lineage_conditions))
                    .order_by(
                        models.artifact_lineage.c.lineage_type,
                        models.artifact_lineage.c.lineage_ordinal,
                        models.artifact_lineage.c.parent_artifact_id,
                        models.artifact_lineage.c.child_artifact_id,
                    )
                )
                .mappings()
                .all()
            )
        return SnapshotMetadata(
            snapshot=cast(SourceSnapshotRow, dict(snapshot)),
            files=tuple(cast(SnapshotFileRow, dict(row)) for row in files),
            memberships=tuple(cast(SourceSnapshotFileRow, dict(row)) for row in memberships),
            warnings=tuple(cast(SnapshotWarningRow, dict(row)) for row in warnings),
            publications=tuple(cast(PublicationVersionRow, dict(row)) for row in publications),
            publication_memberships=tuple(
                cast(SourceSnapshotPublicationRow, dict(row)) for row in publication_memberships
            ),
            lineage=tuple(cast(ArtifactLineageRow, dict(row)) for row in lineage),
            attempt=None if attempt is None else cast(ResearchRunAttemptRow, dict(attempt)),
        )

    def get_run(self, run_id: str) -> RunMetadata | None:
        """Return complete immutable run metadata, attempts, and report."""

        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    sa.select(models.research_run).where(models.research_run.c.run_id == run_id)
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                return None
            attempts = (
                connection.execute(
                    sa.select(models.research_run_attempt)
                    .where(models.research_run_attempt.c.run_id == run_id)
                    .order_by(models.research_run_attempt.c.acquisition_ordinal)
                )
                .mappings()
                .all()
            )
            report = (
                connection.execute(
                    sa.select(models.research_report).where(
                        models.research_report.c.run_id == run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return RunMetadata(
            run=cast(ResearchRunRow, dict(run)),
            attempts=tuple(cast(ResearchRunAttemptRow, dict(row)) for row in attempts),
            report=None if report is None else cast(ResearchReportRow, dict(report)),
        )

    def get_report(self, report_id: str) -> ResearchReportRow | None:
        """Return complete immutable report metadata."""

        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.research_report).where(
                        models.research_report.c.report_id == report_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else cast(ResearchReportRow, dict(row))

    def load_snapshot_for_replay(
        self,
        snapshot_id: str,
        *,
        replay_port: SnapshotReplayPort,
    ) -> ReplaySnapshot:
        """Require exact port-verified bytes and complete persisted provenance equality."""

        metadata = self.get_snapshot(snapshot_id)
        if metadata is None:
            raise PersistenceIntegrityError("snapshot metadata does not exist")
        manifest_artifact = self.get_artifact(metadata.snapshot["manifest_artifact_id"])
        if manifest_artifact is None:
            raise PersistenceIntegrityError("manifest artifact metadata does not exist")
        replay = replay_port.load_verified_snapshot(
            manifest_relative_path=manifest_artifact["relative_storage_path"],
            expected_manifest_id=metadata.snapshot["snapshot_id"],
        )
        self._compare_manifest_snapshot(
            replay.manifest,
            metadata.snapshot,
            error_type=PersistenceIntegrityError,
        )
        if metadata.attempt is None:
            raise PersistenceIntegrityError("snapshot attempt metadata does not exist")
        self._compare_attempt_manifest(
            metadata.attempt,
            replay.manifest,
            metadata.snapshot,
            error_type=PersistenceIntegrityError,
        )
        try:
            expected_files, expected_memberships = self._expected_file_rows(
                replay.manifest, replay.artifact_links, metadata.snapshot
            )
        except ValueError as error:
            raise PersistenceIntegrityError(str(error)) from error
        self._validate_operation_cardinality(
            operation=metadata.attempt["operation"],
            manifest=replay.manifest,
            publications=replay.publications,
            publication_memberships=replay.publication_memberships,
            lineage=replay.lineage,
            error_type=PersistenceIntegrityError,
        )
        expected_warnings = tuple(
            SnapshotWarningRow(
                snapshot_id=snapshot_id,
                warning_ordinal=ordinal,
                warning_code=code,
            )
            for ordinal, code in enumerate(replay.manifest.warning_codes)
        )
        comparisons = (
            (metadata.files, expected_files, "stored files differ from verified replay"),
            (
                metadata.memberships,
                expected_memberships,
                "stored memberships differ from verified replay",
            ),
            (metadata.warnings, expected_warnings, "stored warnings differ from verified replay"),
            (
                metadata.publications,
                replay.publications,
                "stored publications differ from verified replay",
            ),
            (
                metadata.publication_memberships,
                replay.publication_memberships,
                "stored publication memberships differ from verified replay",
            ),
            (metadata.lineage, replay.lineage, "stored lineage differs from verified replay"),
            (metadata.attempt, replay.attempt, "stored attempt differs from verified replay"),
        )
        for actual, expected, message in comparisons:
            if _normalize(actual) != _normalize(expected):
                raise PersistenceIntegrityError(message)
        for publication in replay.publications:
            try:
                self._validate_publication(publication)
            except ValueError as error:
                raise PersistenceIntegrityError(
                    "verified publication payload differs from stored identity"
                ) from error
        return ReplaySnapshot(metadata=metadata, replay=replay)
