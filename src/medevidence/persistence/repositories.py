"""Immutable synchronous repositories for frozen M1A-003B metadata."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
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
    FaersAggregateQueryV1,
    FaersAggregateResult,
    LabelSection,
    LabelSelectionDecision,
    Provenance,
    PublicationRecord,
    ResultStatus,
    SourceOutcome,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.provenance import EvidenceProvenanceEnvelopeV1
from medevidence.tools.provider_attempt_framing import (
    PERSISTED_AUTHORITY_FIELDS,
    V2_ONLY_LEDGER_COLUMNS,
    ContentEncodingState,
    ContentLengthState,
    ContentTypeState,
    FramingObservation,
    HeaderOccurrence,
    HeaderSurfaceState,
    HttpVersionState,
    NormalizedHeaderFacts,
    Observation,
    RawEvidenceState,
    TransferEncodingState,
    UnavailableObservation,
    build_framing_observation,
    build_unavailable_observation,
    canonical_fact_free_v2_event_projection,
    canonical_observation_projection,
    fact_free_v2_event_matches,
    framing_contract_identity,
    legacy_v2_raw_projection,
    projection_matches,
    provider_raw_relative_path_is_canonical,
    reconstruct_normalized_headers,
    v2_event_metadata_matches,
)

from . import models
from .config import PersistenceSettings
from .session import _create_engine

logger = logging.getLogger(__name__)

PUBLICATION_BYTE_CAPACITY = 31_457_280
_VALIDATION_RECEIPT_MARKER = "M3_VALIDATION_RECEIPT_V1"
_VALIDATION_RECEIPT_ID = re.compile(r"validation-receipt:sha256:[0-9a-f]{64}")
_VALIDATION_RECEIPT_V2_ID = re.compile(r"validation-receipt-v2:sha256:[0-9a-f]{64}")
_VALIDATION_STAGE1_RECEIPT_ID = re.compile(r"validation-stage1-receipt-v2:sha256:[0-9a-f]{64}")
_VALIDATION_SCOPE_ID = re.compile(r"scope:sha256:[0-9a-f]{64}")
_VALIDATION_STAGE1_ID = re.compile(r"validation-stage1-result:sha256:[0-9a-f]{64}")
_VALIDATION_RUN_ID = re.compile(
    r"run:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_VALIDATION_REPORT_ID = re.compile(r"report:sha256:[0-9a-f]{64}")
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VALIDATION_RECEIPT_KEYS = frozenset(
    {
        "marker",
        "receipt_id",
        "receipt_content_hash",
        "run_id",
        "report_id",
        "report_content_hash",
        "validation_input_hash",
        "task_binding_hash",
        "stage1_result_id",
        "evaluator_method",
        "evaluator_version",
        "claim_results",
        "structural_passed",
        "semantic_passed",
        "safety_passed",
        "reason_codes",
        "policy_version",
        "configuration_version",
    }
)
_VALIDATION_RECEIPT_V2_KEYS = _VALIDATION_RECEIPT_KEYS | frozenset(
    {
        "semantic_contract",
        "semantic_contract_version",
        "semantic_contract_hash",
        "semantic_configuration_hash",
        "provider_configuration_version",
        "provider_configuration_hash",
        "routing_policy_version",
        "routing_policy_hash",
        "routing_matrix_hash",
    }
)
_VALIDATION_STAGE1_RECEIPT_KEYS = frozenset(
    {
        "marker",
        "stage1_passed",
        "receipt_id",
        "receipt_content_hash",
        "run_id",
        "scope_id",
        "report_id",
        "report_content_hash",
        "validation_input_hash",
        "registry_binding_hash",
        "task_binding_hash",
        "stage1_result_id",
        "claim_result_ids",
        "citation_ids",
        "policy_version",
        "configuration_version",
    }
)
_VALIDATION_RECEIPT_MAX_CANONICAL_BYTES = 4_194_304
_VALIDATION_RECEIPT_MAX_JSON_NODES = 100_000
_SPECIALIZED_M1B_TABLES = frozenset(
    {
        "m1b_dailymed_selection_decisions",
        "m1b_dailymed_label_versions",
        "m1b_dailymed_sections",
        "m1b_dailymed_label_supersession",
        "m1b_faers_queries",
        "m1b_faers_buckets",
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
class M1BRunLifecycle:
    """Exact monotonic M1B run row used before source execution."""

    run_id: str
    request_id: str
    scope_id: str
    status: str
    created_at_utc: datetime
    completed_at_utc: datetime | None
    schema_version: str = "m1b.run.v1"


@dataclass(frozen=True, slots=True)
class M1BAcquisitionLifecycle:
    """Exact M1B acquisition intent row with one nullable completion time."""

    acquisition_intent_id: str
    acquisition_ordinal: int
    attempt_id: str
    run_id: str
    acquisition_id: str
    source: str
    operation: str
    request_identity: str
    query_id: str
    execution_profile_id: str
    started_at_utc: datetime
    completed_at_utc: datetime | None
    schema_version: str


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
class M1BSourceParentBinding:
    artifact_id: str
    content_hash: str
    byte_size: int
    relative_path: str
    artifact_kind: str


@dataclass(frozen=True, slots=True)
class DailyMedEvidenceBinding:
    run_id: str
    acquisition_id: str
    acquisition_intent_id: str
    attempt_id: str
    query_id: str
    source_outcome_id: str
    snapshot_id: str
    retrieved_at_utc: datetime
    connector_version: str
    manifest: M1BSourceParentBinding
    raw: M1BSourceParentBinding
    stable_spl: M1BSourceParentBinding
    setid: str
    spl_version: int
    label_version_id: str
    section_id: str
    section_code: str
    xml_path: str
    text_start: int
    text_end: int
    text_hash: str


@dataclass(frozen=True, slots=True)
class FaersEvidenceBinding:
    run_id: str
    acquisition_id: str
    acquisition_intent_id: str
    attempt_id: str
    query_id: str
    source_outcome_id: str
    snapshot_id: str
    retrieved_at_utc: datetime
    connector_version: str
    manifest: M1BSourceParentBinding
    raw: M1BSourceParentBinding
    execution_profile_id: str
    ast_schema_version: str
    serializer_version: str
    bucket_ordinal: int
    reaction_pt: str
    report_count: int
    statistical_unit: str
    identity_stratum: str
    role_policy: str


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
    "m3_validation_receipts": _TableSpec(
        models.m3_validation_receipts,
        ("receipt_id",),
        _columns(
            models.m3_validation_receipts,
            exclude=frozenset({"persisted_at_utc"}),
        ),
        1_000,
    ),
    "m3_stage1_receipts": _TableSpec(
        models.m3_stage1_receipts,
        ("receipt_id",),
        _columns(models.m3_stage1_receipts, exclude=frozenset({"persisted_at_utc"})),
        1_000,
    ),
    "m3_report_documents": _TableSpec(
        models.m3_report_documents,
        ("document_id",),
        _columns(models.m3_report_documents, exclude=frozenset({"persisted_at_utc"})),
        1_000,
    ),
    "m3_pending_drafts": _TableSpec(
        models.m3_pending_drafts,
        ("persistence_id",),
        _columns(models.m3_pending_drafts, exclude=frozenset({"persisted_at_utc"})),
        1_000,
    ),
    "m3_review_records": _TableSpec(
        models.m3_review_records,
        ("review_id",),
        _columns(models.m3_review_records, exclude=frozenset({"persisted_at_utc"})),
        1_000,
    ),
    "m3_evidence_provenance": _TableSpec(
        models.m3_evidence_provenance,
        ("run_id", "evidence_id"),
        _columns(models.m3_evidence_provenance, exclude=frozenset({"persisted_at_utc"})),
        2_000,
    ),
}


def _values(row: Mapping[str, object]) -> dict[str, object]:
    return dict(row)


def _normalize(value: object) -> object:
    if isinstance(value, sa.sql.elements.Null):
        return None
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

    @staticmethod
    def _copy_validation_receipt_payload(
        receipt_payload: Mapping[str, object],
    ) -> dict[str, object]:
        source = dict(receipt_payload)
        is_v2 = source.get("marker") == "M3_VALIDATION_RECEIPT_V2"
        if set(source) != (_VALIDATION_RECEIPT_V2_KEYS if is_v2 else _VALIDATION_RECEIPT_KEYS):
            raise ValueError("validation receipt payload must contain the exact top-level keys")
        budget = [_VALIDATION_RECEIPT_MAX_JSON_NODES]

        def copy_json(value: object, depth: int = 0) -> object:
            budget[0] -= 1
            if budget[0] < 0 or depth > 8:
                raise ValueError("validation receipt payload exceeds the JSON structure bound")
            if value is None or type(value) in (bool, str):
                if type(value) is str and len(value) > 4096:
                    raise ValueError("validation receipt payload string exceeds 4096 characters")
                return value
            if type(value) is list:
                return [copy_json(item, depth + 1) for item in value]
            if type(value) is dict:
                copied: dict[str, object] = {}
                for key, item in value.items():
                    if type(key) is not str or len(key) > 512:
                        raise ValueError("validation receipt payload contains an invalid JSON key")
                    copied[key] = copy_json(item, depth + 1)
                return copied
            raise ValueError("validation receipt payload must contain only JSON data")

        copied = cast(dict[str, object], copy_json(source))

        def text(name: str, pattern: re.Pattern[str] | None = None) -> str:
            value = copied[name]
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise ValueError(f"validation receipt {name} is invalid")
            if pattern is not None and pattern.fullmatch(value) is None:
                raise ValueError(f"validation receipt {name} is invalid")
            return value

        if copied["marker"] not in (
            _VALIDATION_RECEIPT_MARKER,
            "M3_VALIDATION_RECEIPT_V2",
        ):
            raise ValueError("validation receipt marker is unsupported")
        text("receipt_id", _VALIDATION_RECEIPT_V2_ID if is_v2 else _VALIDATION_RECEIPT_ID)
        text("receipt_content_hash", _SHA256_DIGEST)
        text("run_id", _VALIDATION_RUN_ID)
        text("report_id", _VALIDATION_REPORT_ID)
        for name in (
            "report_content_hash",
            "validation_input_hash",
            "task_binding_hash",
        ):
            text(name, _SHA256_DIGEST)
        text("stage1_result_id", _VALIDATION_STAGE1_ID)
        for name in (
            "evaluator_method",
            "evaluator_version",
            "policy_version",
            "configuration_version",
        ):
            text(name)
        for name in ("structural_passed", "semantic_passed", "safety_passed"):
            if type(copied[name]) is not bool:
                raise ValueError(f"validation receipt {name} is invalid")
        reasons = copied["reason_codes"]
        claims = copied["claim_results"]
        if type(reasons) is not list or len(reasons) > 100:
            raise ValueError("validation receipt reason cardinality exceeds 100")
        if type(claims) is not list or len(claims) > 200:
            raise ValueError("validation receipt claim cardinality exceeds 200")
        if len(canonical_json(copied).encode("utf-8")) > _VALIDATION_RECEIPT_MAX_CANONICAL_BYTES:
            raise ValueError("validation receipt payload exceeds 4,194,304 canonical bytes")
        if is_v2:
            content = {
                name: value
                for name, value in copied.items()
                if name not in ("receipt_id", "receipt_content_hash")
            }
            if copied["receipt_content_hash"] != sha256_digest(canonical_json(content)):
                raise ValueError("validation receipt V2 content hash is invalid")
            if copied["receipt_id"] != derive_identity("validation-receipt-v2", content):
                raise ValueError("validation receipt V2 identity is invalid")
        return copied

    @staticmethod
    def _validation_receipt_values(
        receipt_payload: Mapping[str, object],
    ) -> dict[str, object]:
        payload = PersistenceRepository._copy_validation_receipt_payload(receipt_payload)
        return {
            "receipt_id": payload["receipt_id"],
            "schema_version": payload["marker"],
            "receipt_content_hash": payload["receipt_content_hash"],
            "run_id": payload["run_id"],
            "report_id": payload["report_id"],
            "report_content_hash": payload["report_content_hash"],
            "validation_input_hash": payload["validation_input_hash"],
            "task_binding_hash": payload["task_binding_hash"],
            "evaluator_method": payload["evaluator_method"],
            "evaluator_version": payload["evaluator_version"],
            "policy_version": payload["policy_version"],
            "configuration_version": payload["configuration_version"],
            "receipt_payload": payload,
        }

    @staticmethod
    def _receipt_payload_from_persisted_row(
        row: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            raw_payload = row["receipt_payload"]
            if type(raw_payload) is not dict:
                raise ValueError("persisted validation receipt payload is not a JSON object")
            payload = PersistenceRepository._copy_validation_receipt_payload(raw_payload)
            expected = PersistenceRepository._validation_receipt_values(payload)
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError(
                "persisted validation receipt payload violates the bounded storage contract"
            ) from error
        if not all(
            _normalize(row.get(name)) == _normalize(value) for name, value in expected.items()
        ):
            raise PersistenceIntegrityError(
                "persisted validation receipt projections differ from canonical payload"
            )
        return payload

    def save_receipt(self, receipt_payload: Mapping[str, object]) -> dict[str, object]:
        """Persist one bounded immutable receipt payload or verify exact replay."""

        values = self._validation_receipt_values(receipt_payload)
        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["m3_validation_receipts"],
                values,
                method="save_receipt",
            )
        return self._receipt_payload_from_persisted_row(stored)

    def load_receipt(self, receipt_id: str) -> dict[str, object] | None:
        """Load one bounded immutable M3 validation receipt payload."""

        if type(receipt_id) is not str or not (
            _VALIDATION_RECEIPT_ID.fullmatch(receipt_id)
            or _VALIDATION_RECEIPT_V2_ID.fullmatch(receipt_id)
        ):
            raise ValueError("receipt_id must be an exact validation-receipt identity")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_validation_receipts).where(
                        models.m3_validation_receipts.c.receipt_id == receipt_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return self._receipt_payload_from_persisted_row(dict(row))

    def insert_or_verify_evidence_provenance(
        self, envelope: EvidenceProvenanceEnvelopeV1
    ) -> dict[str, object]:
        """Anchor one exact published envelope without permitting identity replacement."""

        if type(envelope) is not EvidenceProvenanceEnvelopeV1:
            raise TypeError("evidence provenance requires an exact envelope")
        copied = EvidenceProvenanceEnvelopeV1.from_canonical_bytes(envelope.canonical_bytes())
        if copied != envelope:
            raise ValueError("evidence provenance envelope identity differs")
        digest = copied.envelope_hash.removeprefix("sha256:")
        values: dict[str, object] = {
            "run_id": copied.run_id,
            "evidence_id": copied.evidence_id,
            "source": copied.source.value,
            "snapshot_id": copied.snapshot_id,
            "envelope_id": copied.envelope_id,
            "envelope_hash": copied.envelope_hash,
            "relative_path": f"m3/evidence-provenance/{digest[:2]}/{digest}.json",
            "byte_size": len(copied.canonical_bytes()),
        }
        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["m3_evidence_provenance"],
                values,
                method="insert_or_verify_evidence_provenance",
            )
        return {name: stored[name] for name in values}

    def get_evidence_provenance_anchor(
        self, *, run_id: str, evidence_id: str
    ) -> dict[str, object] | None:
        """Read one bounded insert-only anchor by its exact run/evidence key."""

        if (
            re.fullmatch(
                r"run:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                run_id,
            )
            is None
            or re.fullmatch(r"evidence:sha256:[0-9a-f]{64}", evidence_id) is None
        ):
            raise ValueError("invalid evidence provenance lookup identity")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_evidence_provenance).where(
                        models.m3_evidence_provenance.c.run_id == run_id,
                        models.m3_evidence_provenance.c.evidence_id == evidence_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    @staticmethod
    def _m1b_parent_from_rows(
        artifact: Mapping[str, object], member: Mapping[str, object] | None = None
    ) -> M1BSourceParentBinding:
        try:
            if member is not None and (
                member["artifact_id"] != artifact["artifact_id"]
                or member["content_hash"] != artifact["content_hash"]
                or member["artifact_kind"] != artifact["artifact_kind"]
                or member["body_complete"] is not True
                or member["termination_reason"] != "complete_response"
            ):
                raise ValueError("source artifact membership drift")
            result = M1BSourceParentBinding(
                artifact_id=cast(str, artifact["content_hash"]),
                content_hash=cast(str, artifact["content_hash"]),
                byte_size=cast(int, artifact["byte_size"]),
                relative_path=cast(str, artifact["relative_storage_label"]),
                artifact_kind=cast(str, artifact["artifact_kind"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored source parent binding is invalid") from error
        if (
            _SHA256_DIGEST.fullmatch(result.content_hash) is None
            or not 1 <= result.byte_size <= 5_242_880
            or not result.relative_path
        ):
            raise PersistenceIntegrityError("stored source parent identity is invalid")
        return result

    def get_dailymed_evidence_binding(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        query_id: str,
        source_outcome_id: str,
        snapshot_id: str,
        label_version_id: str,
        section_id: str,
    ) -> DailyMedEvidenceBinding | None:
        """Read one exact DailyMed section and its immutable source parents."""

        for value in (
            run_id,
            acquisition_id,
            query_id,
            source_outcome_id,
            snapshot_id,
            label_version_id,
            section_id,
        ):
            if type(value) is not str or not 1 <= len(value) <= 160:
                raise ValueError("DailyMed evidence lookup identity is invalid")

        with self._engine.connect() as connection:
            acquisition = (
                connection.execute(
                    sa.select(models.m1b_acquisitions).where(
                        models.m1b_acquisitions.c.run_id == run_id,
                        models.m1b_acquisitions.c.source == "dailymed",
                        models.m1b_acquisitions.c.operation == "fetch",
                        models.m1b_acquisitions.c.acquisition_id == acquisition_id,
                        models.m1b_acquisitions.c.query_id == query_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = (
                connection.execute(
                    sa.select(models.m1b_snapshots).where(
                        models.m1b_snapshots.c.run_id == run_id,
                        models.m1b_snapshots.c.source == "dailymed",
                        models.m1b_snapshots.c.acquisition_id == acquisition_id,
                        models.m1b_snapshots.c.query_id == query_id,
                        models.m1b_snapshots.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if acquisition is None or snapshot is None:
                return None
            outcome = (
                connection.execute(
                    sa.select(models.m1b_source_outcomes).where(
                        models.m1b_source_outcomes.c.run_id == run_id,
                        models.m1b_source_outcomes.c.source == "dailymed",
                        models.m1b_source_outcomes.c.acquisition_id == acquisition_id,
                        models.m1b_source_outcomes.c.query_id == query_id,
                        models.m1b_source_outcomes.c.source_outcome_id == source_outcome_id,
                        models.m1b_source_outcomes.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if outcome is None:
                return None
            section = (
                connection.execute(
                    sa.select(models.m1b_dailymed_sections).where(
                        models.m1b_dailymed_sections.c.source == "dailymed",
                        models.m1b_dailymed_sections.c.label_version_id == label_version_id,
                        models.m1b_dailymed_sections.c.section_id == section_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if section is None:
                return None
            version = (
                connection.execute(
                    sa.select(models.m1b_dailymed_label_versions).where(
                        models.m1b_dailymed_label_versions.c.source == "dailymed",
                        models.m1b_dailymed_label_versions.c.setid == section["setid"],
                        models.m1b_dailymed_label_versions.c.label_version_id == label_version_id,
                        models.m1b_dailymed_label_versions.c.spl_version == section["spl_version"],
                        models.m1b_dailymed_label_versions.c.spl_artifact_id
                        == section["spl_artifact_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            members = (
                connection.execute(
                    sa.select(models.m1b_snapshot_artifacts).where(
                        models.m1b_snapshot_artifacts.c.run_id == run_id,
                        models.m1b_snapshot_artifacts.c.source == "dailymed",
                        models.m1b_snapshot_artifacts.c.acquisition_id == acquisition_id,
                        models.m1b_snapshot_artifacts.c.snapshot_id == snapshot_id,
                        models.m1b_snapshot_artifacts.c.artifact_kind == "dailymed_http_response",
                        models.m1b_snapshot_artifacts.c.body_complete.is_(True),
                        models.m1b_snapshot_artifacts.c.termination_reason == "complete_response",
                    )
                )
                .mappings()
                .all()
            )
            if version is None or len(members) != 1:
                raise PersistenceIntegrityError("DailyMed source parent graph is incomplete")
            raw_artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == members[0]["artifact_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            manifest_artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == snapshot["manifest_artifact_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            spl_artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == version["spl_artifact_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
        if raw_artifact is None or manifest_artifact is None or spl_artifact is None:
            raise PersistenceIntegrityError("DailyMed artifact graph is incomplete")
        manifest_parent = self._m1b_parent_from_rows(dict(manifest_artifact))
        raw_parent = self._m1b_parent_from_rows(dict(raw_artifact), dict(members[0]))
        stable_parent = self._m1b_parent_from_rows(dict(spl_artifact))
        if (
            "manifest" not in manifest_parent.artifact_kind
            or raw_parent.artifact_kind != "dailymed_http_response"
            or stable_parent.artifact_kind != "dailymed_spl_xml"
        ):
            raise PersistenceIntegrityError("DailyMed artifact kind graph is invalid")
        return DailyMedEvidenceBinding(
            run_id=run_id,
            acquisition_id=acquisition_id,
            acquisition_intent_id=cast(str, acquisition["acquisition_intent_id"]),
            attempt_id=cast(str, acquisition["attempt_id"]),
            query_id=query_id,
            source_outcome_id=source_outcome_id,
            snapshot_id=snapshot_id,
            retrieved_at_utc=cast(datetime, snapshot["retrieved_at_utc"]),
            connector_version=cast(str, snapshot["connector_version"]),
            manifest=manifest_parent,
            raw=raw_parent,
            stable_spl=stable_parent,
            setid=str(section["setid"]),
            spl_version=cast(int, section["spl_version"]),
            label_version_id=label_version_id,
            section_id=section_id,
            section_code=cast(str, section["section_code"]),
            xml_path=cast(str, section["xml_path"]),
            text_start=cast(int, section["text_start"]),
            text_end=cast(int, section["text_end"]),
            text_hash=cast(str, section["text_hash"]),
        )

    def get_faers_evidence_binding(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        query_id: str,
        source_outcome_id: str,
        snapshot_id: str,
        bucket_ordinal: int,
    ) -> FaersEvidenceBinding | None:
        """Read one exact FAERS bucket and its immutable source parents."""

        for value in (run_id, acquisition_id, query_id, source_outcome_id, snapshot_id):
            if type(value) is not str or not 1 <= len(value) <= 160:
                raise ValueError("FAERS evidence lookup identity is invalid")
        if type(bucket_ordinal) is not int or not 0 <= bucket_ordinal < 100:
            raise ValueError("FAERS evidence bucket ordinal is invalid")

        with self._engine.connect() as connection:
            acquisition = (
                connection.execute(
                    sa.select(models.m1b_acquisitions).where(
                        models.m1b_acquisitions.c.run_id == run_id,
                        models.m1b_acquisitions.c.source == "faers",
                        models.m1b_acquisitions.c.acquisition_id == acquisition_id,
                        models.m1b_acquisitions.c.query_id == query_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = (
                connection.execute(
                    sa.select(models.m1b_snapshots).where(
                        models.m1b_snapshots.c.run_id == run_id,
                        models.m1b_snapshots.c.source == "faers",
                        models.m1b_snapshots.c.acquisition_id == acquisition_id,
                        models.m1b_snapshots.c.query_id == query_id,
                        models.m1b_snapshots.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            query = (
                connection.execute(
                    sa.select(models.m1b_faers_queries).where(
                        models.m1b_faers_queries.c.run_id == run_id,
                        models.m1b_faers_queries.c.acquisition_id == acquisition_id,
                        models.m1b_faers_queries.c.query_id == query_id,
                        models.m1b_faers_queries.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            outcome = (
                connection.execute(
                    sa.select(models.m1b_source_outcomes).where(
                        models.m1b_source_outcomes.c.run_id == run_id,
                        models.m1b_source_outcomes.c.source == "faers",
                        models.m1b_source_outcomes.c.acquisition_id == acquisition_id,
                        models.m1b_source_outcomes.c.query_id == query_id,
                        models.m1b_source_outcomes.c.source_outcome_id == source_outcome_id,
                        models.m1b_source_outcomes.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            bucket = (
                connection.execute(
                    sa.select(models.m1b_faers_buckets).where(
                        models.m1b_faers_buckets.c.run_id == run_id,
                        models.m1b_faers_buckets.c.acquisition_id == acquisition_id,
                        models.m1b_faers_buckets.c.query_id == query_id,
                        models.m1b_faers_buckets.c.bucket_ordinal == bucket_ordinal,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                acquisition is None
                or snapshot is None
                or query is None
                or outcome is None
                or bucket is None
            ):
                return None
            members = (
                connection.execute(
                    sa.select(models.m1b_snapshot_artifacts).where(
                        models.m1b_snapshot_artifacts.c.run_id == run_id,
                        models.m1b_snapshot_artifacts.c.source == "faers",
                        models.m1b_snapshot_artifacts.c.acquisition_id == acquisition_id,
                        models.m1b_snapshot_artifacts.c.snapshot_id == snapshot_id,
                        models.m1b_snapshot_artifacts.c.artifact_kind == "faers_http_response",
                        models.m1b_snapshot_artifacts.c.body_complete.is_(True),
                    )
                )
                .mappings()
                .all()
            )
            if len(members) != 1:
                raise PersistenceIntegrityError("FAERS source parent graph is incomplete")
            raw_artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == members[0]["artifact_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            manifest_artifact = (
                connection.execute(
                    sa.select(models.m1b_artifacts).where(
                        models.m1b_artifacts.c.artifact_id == snapshot["manifest_artifact_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
        if raw_artifact is None or manifest_artifact is None:
            raise PersistenceIntegrityError("FAERS artifact graph is incomplete")
        manifest_parent = self._m1b_parent_from_rows(dict(manifest_artifact))
        raw_parent = self._m1b_parent_from_rows(dict(raw_artifact), dict(members[0]))
        if (
            "manifest" not in manifest_parent.artifact_kind
            or raw_parent.artifact_kind != "faers_http_response"
        ):
            raise PersistenceIntegrityError("FAERS artifact kind graph is invalid")
        return FaersEvidenceBinding(
            run_id=run_id,
            acquisition_id=acquisition_id,
            acquisition_intent_id=cast(str, acquisition["acquisition_intent_id"]),
            attempt_id=cast(str, acquisition["attempt_id"]),
            query_id=query_id,
            source_outcome_id=source_outcome_id,
            snapshot_id=snapshot_id,
            retrieved_at_utc=cast(datetime, query["retrieved_at_utc"]),
            connector_version=cast(str, snapshot["connector_version"]),
            manifest=manifest_parent,
            raw=raw_parent,
            execution_profile_id=cast(str, query["execution_profile_id"]),
            ast_schema_version=cast(str, query["ast_schema_version"]),
            serializer_version=cast(str, query["serializer_version"]),
            bucket_ordinal=bucket_ordinal,
            reaction_pt=cast(str, bucket["reaction_pt"]),
            report_count=cast(int, bucket["report_count"]),
            statistical_unit=cast(str, bucket["statistical_unit"]),
            identity_stratum=cast(str, bucket["identity_stratum"]),
            role_policy=cast(str, bucket["role_policy"]),
        )

    def load_m1b_faers_terminal_rows(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        query_id: str,
        snapshot_id: str,
        source_outcome_id: str,
    ) -> dict[str, object] | None:
        """Read bounded exact FAERS terminal rows, including zero-bucket outcomes."""

        for value in (run_id, acquisition_id, query_id, snapshot_id, source_outcome_id):
            if type(value) is not str or not 1 <= len(value) <= 160:
                raise ValueError("FAERS terminal lookup identity is invalid")
        with self._engine.connect() as connection:
            acquisition = (
                connection.execute(
                    sa.select(models.m1b_acquisitions).where(
                        models.m1b_acquisitions.c.run_id == run_id,
                        models.m1b_acquisitions.c.source == "faers",
                        models.m1b_acquisitions.c.acquisition_id == acquisition_id,
                        models.m1b_acquisitions.c.query_id == query_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            snapshot = (
                connection.execute(
                    sa.select(models.m1b_snapshots).where(
                        models.m1b_snapshots.c.run_id == run_id,
                        models.m1b_snapshots.c.source == "faers",
                        models.m1b_snapshots.c.acquisition_id == acquisition_id,
                        models.m1b_snapshots.c.query_id == query_id,
                        models.m1b_snapshots.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            outcome = (
                connection.execute(
                    sa.select(models.m1b_source_outcomes).where(
                        models.m1b_source_outcomes.c.run_id == run_id,
                        models.m1b_source_outcomes.c.source == "faers",
                        models.m1b_source_outcomes.c.acquisition_id == acquisition_id,
                        models.m1b_source_outcomes.c.query_id == query_id,
                        models.m1b_source_outcomes.c.snapshot_id == snapshot_id,
                        models.m1b_source_outcomes.c.source_outcome_id == source_outcome_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            query = (
                connection.execute(
                    sa.select(models.m1b_faers_queries).where(
                        models.m1b_faers_queries.c.run_id == run_id,
                        models.m1b_faers_queries.c.acquisition_id == acquisition_id,
                        models.m1b_faers_queries.c.query_id == query_id,
                        models.m1b_faers_queries.c.snapshot_id == snapshot_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            members = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(models.m1b_snapshot_artifacts)
                    .where(
                        models.m1b_snapshot_artifacts.c.run_id == run_id,
                        models.m1b_snapshot_artifacts.c.source == "faers",
                        models.m1b_snapshot_artifacts.c.acquisition_id == acquisition_id,
                        models.m1b_snapshot_artifacts.c.snapshot_id == snapshot_id,
                    )
                    .order_by(models.m1b_snapshot_artifacts.c.ordinal)
                    .limit(3)
                ).mappings()
            )
            buckets = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(models.m1b_faers_buckets)
                    .where(
                        models.m1b_faers_buckets.c.run_id == run_id,
                        models.m1b_faers_buckets.c.acquisition_id == acquisition_id,
                        models.m1b_faers_buckets.c.query_id == query_id,
                    )
                    .order_by(models.m1b_faers_buckets.c.bucket_ordinal)
                    .limit(101)
                ).mappings()
            )
        if acquisition is None or snapshot is None or outcome is None or query is None:
            return None
        if len(members) > 2 or len(buckets) > 100:
            raise PersistenceIntegrityError("FAERS terminal rows exceed the closed bounds")
        return {
            "acquisition": dict(acquisition),
            "snapshot": dict(snapshot),
            "outcome": dict(outcome),
            "query": dict(query),
            "members": members,
            "buckets": buckets,
        }

    @staticmethod
    def _stage1_receipt_values(receipt_payload: Mapping[str, object]) -> dict[str, object]:
        """Bound and project Stage-1 JSON; outer adapters own canonical parsing."""

        if (
            type(receipt_payload) is not dict
            or set(receipt_payload) != _VALIDATION_STAGE1_RECEIPT_KEYS
        ):
            raise ValueError("stage1 receipt payload must have exact keys")
        payload = dict(receipt_payload)
        for name in _VALIDATION_STAGE1_RECEIPT_KEYS - {
            "stage1_passed",
            "claim_result_ids",
            "citation_ids",
        }:
            value = payload[name]
            if type(value) is not str or not value.strip() or len(value) > 512:
                raise ValueError(f"stage1 receipt {name} is invalid")
        if payload["marker"] != "M3_STAGE1_VALIDATION_RECEIPT_V2":
            raise ValueError("stage1 receipt marker is invalid")
        if type(payload["stage1_passed"]) is not bool or payload["stage1_passed"] is not True:
            raise ValueError("stage1 receipt requires a passing Stage-1 result")
        claims, citations = payload["claim_result_ids"], payload["citation_ids"]
        if type(claims) not in (tuple, list) or len(claims) > 200:
            raise ValueError("stage1 receipt claims are invalid")
        if type(citations) not in (tuple, list) or len(citations) > 400:
            raise ValueError("stage1 receipt citations are invalid")
        for item in claims:
            if (
                type(item) not in (tuple, list)
                or len(item) != 2
                or any(type(part) is not str or not part or len(part) > 512 for part in item)
            ):
                raise ValueError("stage1 receipt claim binding is invalid")
        if any(type(item) is not str or not item or len(item) > 512 for item in citations):
            raise ValueError("stage1 receipt citation binding is invalid")
        payload = json.loads(canonical_json(payload))
        if len(canonical_json(payload).encode("utf-8")) > _VALIDATION_RECEIPT_MAX_CANONICAL_BYTES:
            raise ValueError("stage1 receipt payload exceeds 4,194,304 canonical bytes")
        if (
            _VALIDATION_STAGE1_RECEIPT_ID.fullmatch(payload["receipt_id"]) is None
            or _VALIDATION_RUN_ID.fullmatch(payload["run_id"]) is None
            or _VALIDATION_SCOPE_ID.fullmatch(payload["scope_id"]) is None
            or _VALIDATION_REPORT_ID.fullmatch(payload["report_id"]) is None
            or _VALIDATION_STAGE1_ID.fullmatch(payload["stage1_result_id"]) is None
        ):
            raise ValueError("stage1 receipt projected identity is invalid")
        for name in (
            "receipt_content_hash",
            "report_content_hash",
            "validation_input_hash",
            "registry_binding_hash",
            "task_binding_hash",
        ):
            if _SHA256_DIGEST.fullmatch(payload[name]) is None:
                raise ValueError(f"stage1 receipt {name} is invalid")
        content = {
            name: value
            for name, value in payload.items()
            if name not in ("receipt_id", "receipt_content_hash")
        }
        if payload["receipt_content_hash"] != sha256_digest(canonical_json(content)) or payload[
            "receipt_id"
        ] != derive_identity("validation-stage1-receipt-v2", content):
            raise ValueError("stage1 receipt content identity is invalid")
        return {
            "receipt_id": payload["receipt_id"],
            "schema_version": payload["marker"],
            "receipt_content_hash": payload["receipt_content_hash"],
            "run_id": payload["run_id"],
            "scope_id": payload["scope_id"],
            "report_id": payload["report_id"],
            "report_content_hash": payload["report_content_hash"],
            "validation_input_hash": payload["validation_input_hash"],
            "registry_binding_hash": payload["registry_binding_hash"],
            "task_binding_hash": payload["task_binding_hash"],
            "stage1_result_id": payload["stage1_result_id"],
            "policy_version": payload["policy_version"],
            "configuration_version": payload["configuration_version"],
            "receipt_payload": payload,
        }

    @staticmethod
    def _stage1_payload_from_persisted_row(row: Mapping[str, object]) -> dict[str, object]:
        try:
            raw = row["receipt_payload"]
            if type(raw) is not dict:
                raise ValueError("stored stage1 receipt payload is not a JSON object")
            expected = PersistenceRepository._stage1_receipt_values(raw)
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError(
                "stored stage1 receipt violates canonical contract"
            ) from error
        if not all(
            _normalize(row.get(name)) == _normalize(value) for name, value in expected.items()
        ):
            raise PersistenceIntegrityError("stored stage1 receipt projections differ from payload")
        return cast(dict[str, object], expected["receipt_payload"])

    def save_stage1_receipt(self, receipt_payload: Mapping[str, object]) -> dict[str, object]:
        """Insert a Stage-1 receipt or verify an exact immutable replay."""

        values = self._stage1_receipt_values(receipt_payload)
        with self._engine.begin() as connection:
            stored = self._insert_or_verify(
                connection,
                _SPECS["m3_stage1_receipts"],
                values,
                method="save_stage1_receipt",
            )
        return self._stage1_payload_from_persisted_row(stored)

    def load_stage1_receipt(self, receipt_id: str) -> dict[str, object] | None:
        """Reload and verify a durable Stage-1 receipt by exact identity."""

        if (
            type(receipt_id) is not str
            or _VALIDATION_STAGE1_RECEIPT_ID.fullmatch(receipt_id) is None
        ):
            raise ValueError("receipt_id must be an exact stage1-receipt identity")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_stage1_receipts).where(
                        models.m3_stage1_receipts.c.receipt_id == receipt_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return self._stage1_payload_from_persisted_row(dict(row))

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
        if table_name in _SPECIALIZED_M1B_TABLES:
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
    def _exact_lifecycle_time(value: datetime, name: str) -> None:
        if (
            type(value) is not datetime
            or value.tzinfo is None
            or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError(f"{name} must be an exact timezone-aware UTC datetime")

    @staticmethod
    def _run_lifecycle_values(value: M1BRunLifecycle) -> dict[str, object]:
        if type(value) is not M1BRunLifecycle:
            raise TypeError("M1B run lifecycle requires the exact DTO")
        if (
            not all(
                type(item) is str and 1 <= len(item) <= 512
                for item in (
                    value.run_id,
                    value.request_id,
                    value.scope_id,
                )
            )
            or value.schema_version != "m1b.run.v1"
            or value.status not in {"running", "completed", "degraded", "failed"}
            or (value.status == "running" and value.completed_at_utc is not None)
        ):
            raise ValueError("M1B run lifecycle fields are invalid")
        PersistenceRepository._exact_lifecycle_time(value.created_at_utc, "created_at_utc")
        if value.completed_at_utc is not None:
            PersistenceRepository._exact_lifecycle_time(value.completed_at_utc, "completed_at_utc")
            if value.completed_at_utc < value.created_at_utc:
                raise ValueError("M1B run completion precedes creation")
        return {
            "run_id": value.run_id,
            "request_id": value.request_id,
            "scope_id": value.scope_id,
            "status": value.status,
            "created_at_utc": value.created_at_utc,
            "completed_at_utc": value.completed_at_utc,
            "schema_version": value.schema_version,
        }

    @staticmethod
    def _run_lifecycle_from_row(row: Mapping[str, object]) -> M1BRunLifecycle:
        return M1BRunLifecycle(
            run_id=cast(str, row["run_id"]),
            request_id=cast(str, row["request_id"]),
            scope_id=cast(str, row["scope_id"]),
            status=cast(str, row["status"]),
            created_at_utc=cast(datetime, row["created_at_utc"]),
            completed_at_utc=cast(datetime | None, row["completed_at_utc"]),
            schema_version=cast(str, row["schema_version"]),
        )

    def begin_m1b_run(self, value: M1BRunLifecycle) -> tuple[M1BRunLifecycle, bool]:
        """Insert a running run or verify its immutable identity without reopening it."""

        values = self._run_lifecycle_values(value)
        if value.status != "running":
            raise ValueError("begin_m1b_run requires running status")
        table = models.m1b_runs
        with self._engine.begin() as connection:
            existing = (
                connection.execute(sa.select(table).where(table.c.run_id == value.run_id))
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(table.insert().values(**values))
                stored = values
                created = True
            else:
                stored = dict(existing)
                created = False
                if any(
                    _normalize(stored[name]) != _normalize(values[name])
                    for name in (
                        "run_id",
                        "request_id",
                        "scope_id",
                        "created_at_utc",
                        "schema_version",
                    )
                ):
                    raise PersistenceConflict("m1b_runs", "pk_m1b_runs")
        return self._run_lifecycle_from_row(stored), created

    def get_m1b_run_lifecycle(self, run_id: str) -> M1BRunLifecycle | None:
        """Load one exact run row without changing its lifecycle state."""

        if type(run_id) is not str or not 1 <= len(run_id) <= 512:
            raise ValueError("M1B run_id is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m1b_runs).where(models.m1b_runs.c.run_id == run_id)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        result = self._run_lifecycle_from_row(dict(row))
        self._run_lifecycle_values(result)
        return result

    def finalize_m1b_run(self, value: M1BRunLifecycle) -> M1BRunLifecycle:
        """CAS one running run to its exact terminal row; terminal rows are immutable."""

        values = self._run_lifecycle_values(value)
        if (
            value.status not in {"completed", "degraded", "failed"}
            or value.completed_at_utc is None
        ):
            raise ValueError("finalize_m1b_run requires an exact terminal row")
        table = models.m1b_runs
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(table).where(table.c.run_id == value.run_id).with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                raise PersistenceIntegrityError("M1B run start is missing")
            stored = dict(existing)
            if all(_normalize(stored[name]) == _normalize(values[name]) for name in values):
                return self._run_lifecycle_from_row(stored)
            if stored["status"] != "running" or any(
                _normalize(stored[name]) != _normalize(values[name])
                for name in ("run_id", "request_id", "scope_id", "created_at_utc", "schema_version")
            ):
                raise PersistenceConflict("m1b_runs", "pk_m1b_runs")
            connection.execute(
                table.update()
                .where(table.c.run_id == value.run_id)
                .values(
                    status=value.status,
                    completed_at_utc=value.completed_at_utc,
                )
            )
        return value

    @staticmethod
    def _acquisition_lifecycle_values(
        value: M1BAcquisitionLifecycle,
    ) -> dict[str, object]:
        if type(value) is not M1BAcquisitionLifecycle:
            raise TypeError("M1B acquisition lifecycle requires the exact DTO")
        texts = (
            value.acquisition_intent_id,
            value.attempt_id,
            value.run_id,
            value.acquisition_id,
            value.source,
            value.operation,
            value.request_identity,
            value.query_id,
            value.execution_profile_id,
            value.schema_version,
        )
        if (
            any(type(item) is not str or not 1 <= len(item) <= 1024 for item in texts)
            or type(value.acquisition_ordinal) is not int
            or not 0 <= value.acquisition_ordinal <= 100
            or value.source not in {"dailymed", "faers"}
            or value.operation not in {"search", "fetch", "packaging"}
            or (value.operation == "packaging" and value.source != "dailymed")
        ):
            raise ValueError("M1B acquisition lifecycle fields are invalid")
        PersistenceRepository._exact_lifecycle_time(value.started_at_utc, "started_at_utc")
        if value.completed_at_utc is not None:
            PersistenceRepository._exact_lifecycle_time(value.completed_at_utc, "completed_at_utc")
            if value.completed_at_utc < value.started_at_utc:
                raise ValueError("M1B acquisition completion precedes start")
        return {name: getattr(value, name) for name in value.__dataclass_fields__}

    @staticmethod
    def _acquisition_lifecycle_from_row(
        row: Mapping[str, object],
    ) -> M1BAcquisitionLifecycle:
        return M1BAcquisitionLifecycle(
            acquisition_intent_id=cast(str, row["acquisition_intent_id"]),
            acquisition_ordinal=cast(int, row["acquisition_ordinal"]),
            attempt_id=cast(str, row["attempt_id"]),
            run_id=cast(str, row["run_id"]),
            acquisition_id=cast(str, row["acquisition_id"]),
            source=cast(str, row["source"]),
            operation=cast(str, row["operation"]),
            request_identity=cast(str, row["request_identity"]),
            query_id=cast(str, row["query_id"]),
            execution_profile_id=cast(str, row["execution_profile_id"]),
            started_at_utc=cast(datetime, row["started_at_utc"]),
            completed_at_utc=cast(datetime | None, row["completed_at_utc"]),
            schema_version=cast(str, row["schema_version"]),
        )

    def begin_m1b_acquisition(
        self, value: M1BAcquisitionLifecycle
    ) -> tuple[M1BAcquisitionLifecycle, bool]:
        """Persist an exact source START row before the external operation."""

        values = self._acquisition_lifecycle_values(value)
        if value.completed_at_utc is not None:
            raise ValueError("begin_m1b_acquisition requires an incomplete row")
        table = models.m1b_acquisitions
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(table).where(table.c.acquisition_id == value.acquisition_id)
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(table.insert().values(**values))
                stored = values
                created = True
            else:
                stored = dict(existing)
                created = False
                if any(
                    _normalize(stored[name]) != _normalize(values[name])
                    for name in values
                    if name not in {"started_at_utc", "completed_at_utc"}
                ):
                    raise PersistenceConflict("m1b_acquisitions", "pk_m1b_acquisitions")
        return self._acquisition_lifecycle_from_row(stored), created

    def get_m1b_acquisition_lifecycle(self, acquisition_id: str) -> M1BAcquisitionLifecycle | None:
        """Load one exact acquisition lifecycle row for safe resume decisions."""

        if type(acquisition_id) is not str or not 1 <= len(acquisition_id) <= 512:
            raise ValueError("M1B acquisition_id is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m1b_acquisitions).where(
                        models.m1b_acquisitions.c.acquisition_id == acquisition_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        result = self._acquisition_lifecycle_from_row(dict(row))
        self._acquisition_lifecycle_values(result)
        return result

    def finalize_m1b_acquisition(self, value: M1BAcquisitionLifecycle) -> M1BAcquisitionLifecycle:
        """CAS one exact START row to its immutable completion timestamp."""

        values = self._acquisition_lifecycle_values(value)
        if value.completed_at_utc is None:
            raise ValueError("finalize_m1b_acquisition requires completed_at_utc")
        table = models.m1b_acquisitions
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(table)
                    .where(table.c.acquisition_id == value.acquisition_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                raise PersistenceIntegrityError("M1B acquisition START row is missing")
            stored = dict(existing)
            if all(_normalize(stored[name]) == _normalize(values[name]) for name in values):
                return self._acquisition_lifecycle_from_row(stored)
            if stored["completed_at_utc"] is not None or any(
                _normalize(stored[name]) != _normalize(values[name])
                for name in values
                if name != "completed_at_utc"
            ):
                raise PersistenceConflict("m1b_acquisitions", "pk_m1b_acquisitions")
            connection.execute(
                table.update()
                .where(table.c.acquisition_id == value.acquisition_id)
                .values(completed_at_utc=value.completed_at_utc)
            )
        return value

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
        if table_name == "m1b_snapshot_artifacts" and values["source"] == "faers":
            ordinal = values["ordinal"]
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal not in {0, 1}:
                raise ValueError("FAERS snapshot membership exceeds the two-attempt profile")
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
        """Persist immutable content metadata while retaining its first-seen time."""

        table_name = "m1b_artifacts"
        table = models.m1b_artifacts
        expected_columns = tuple(column.name for column in table.columns)
        if set(row) != set(expected_columns):
            raise ValueError("m1b_artifacts input must contain every persisted column exactly")
        values = dict(row)
        self._validate_m1b_row(table_name, values)
        created_at = values["created_at_utc"]
        if type(created_at) is not datetime:
            raise ValueError("M1B artifact created_at_utc must be an exact datetime")
        self._exact_lifecycle_time(created_at, "M1B artifact created_at_utc")

        def verify(existing: Mapping[str, object]) -> dict[str, object]:
            stored = dict(existing)
            if all(
                _normalize(stored[name]) == _normalize(values[name])
                for name in expected_columns
                if name != "created_at_utc"
            ):
                return stored
            raise PersistenceConflict(table_name, "pk_m1b_artifacts")

        predicate = table.c.artifact_id == values["artifact_id"]
        with self._engine.begin() as connection:
            existing = (
                connection.execute(sa.select(table).where(predicate)).mappings().one_or_none()
            )
            if existing is not None:
                return verify(dict(existing))
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
                return verify(dict(existing))
        return values

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

    def insert_or_verify_faers_result(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        result: FaersAggregateResult,
    ) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
        """Persist one exact FAERS query and its complete ordered bucket collection."""

        trusted = FaersAggregateResult.model_validate(result.model_dump(mode="python"))
        query = FaersAggregateQueryV1.model_validate(trusted.query.model_dump(mode="python"))
        if trusted != result or query != result.query:
            raise ValueError("FAERS result differs from closed validation")
        query_row = self._faers_query_row(
            run_id=run_id,
            acquisition_id=acquisition_id,
            result=trusted,
        )
        bucket_rows = tuple(
            {
                "acquisition_id": acquisition_id,
                "source": "faers",
                "run_id": run_id,
                "query_id": query.query_id,
                "bucket_ordinal": bucket.bucket_ordinal,
                "reaction_pt": bucket.reaction_pt,
                "report_count": bucket.report_count,
                "statistical_unit": bucket.statistical_unit,
                "identity_stratum": bucket.identity_stratum,
                "role_policy": bucket.role_policy,
            }
            for bucket in trusted.buckets
        )
        with self._engine.begin() as connection:
            self._validate_faers_parent_ownership(
                connection,
                run_id=run_id,
                acquisition_id=acquisition_id,
                result=trusted,
            )
            stored_query = self._insert_or_verify_m1b_connection(
                connection,
                "m1b_faers_queries",
                models.m1b_faers_queries,
                query_row,
            )
            stored_query["role_predicate_json"] = None
            existing = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(models.m1b_faers_buckets)
                    .where(
                        models.m1b_faers_buckets.c.run_id == run_id,
                        models.m1b_faers_buckets.c.source == "faers",
                        models.m1b_faers_buckets.c.acquisition_id == acquisition_id,
                        models.m1b_faers_buckets.c.query_id == query.query_id,
                    )
                    .order_by(models.m1b_faers_buckets.c.bucket_ordinal)
                )
                .mappings()
                .all()
            )
            if existing:
                if len(existing) != len(bucket_rows) or any(
                    any(_normalize(stored[name]) != _normalize(expected[name]) for name in expected)
                    for stored, expected in zip(existing, bucket_rows, strict=True)
                ):
                    raise PersistenceConflict("m1b_faers_buckets", "pk_m1b_faers_buckets")
                return stored_query, existing
            stored_buckets = tuple(
                self._insert_or_verify_m1b_connection(
                    connection,
                    "m1b_faers_buckets",
                    models.m1b_faers_buckets,
                    row,
                )
                for row in bucket_rows
            )
            return stored_query, stored_buckets

    @staticmethod
    def _faers_query_row(
        *,
        run_id: str,
        acquisition_id: str,
        result: FaersAggregateResult,
    ) -> dict[str, object]:
        query = result.query
        bounds = query.execution_bounds
        return {
            "generic_total_deadline_ceiling_ms": query.generic_total_deadline_ceiling_ms,
            "effective_total_deadline_ms": query.effective_total_deadline_ms,
            "execution_profile_id": query.execution_profile_id,
            "outcome_query_id": result.source_outcome.query_id,
            "acquisition_id": acquisition_id,
            "source": "faers",
            "run_id": run_id,
            "query_id": query.query_id,
            "snapshot_id": result.snapshot_id,
            "ast_schema_version": query.ast_schema_version,
            "serializer_version": query.serializer_version,
            "endpoint_mode": query.endpoint_mode,
            "provider_path": query.endpoint_path,
            "identity_stratum": query.identity_stratum,
            "identity_field": query.identity_field,
            "identity_value": query.identity_value,
            "pt_set_id": query.pt_set_id,
            "pt_authority_version": query.pt_authority_version,
            "pt_values": list(query.pt_values),
            "date_field": query.date_field,
            "start_date": query.inclusive_date_range.start_date,
            "end_date": query.inclusive_date_range.end_date,
            "role_policy": query.role_policy,
            "role_predicate_json": sa.null(),
            "provider_latest_policy": query.provider_latest_policy,
            "bounds_json": {
                "max_query_characters": bounds.max_query_characters,
                "max_pages": bounds.max_pages,
                "page_size": bounds.page_size,
                "max_returned_raw_records": bounds.max_returned_raw_records,
                "max_response_bytes": bounds.max_response_bytes,
                "max_cumulative_bytes": bounds.max_cumulative_bytes,
                "effective_total_deadline_ms": bounds.effective_total_deadline_ms,
                "generic_total_deadline_ceiling_ms": bounds.generic_total_deadline_ceiling_ms,
            },
            "retrieved_at_utc": result.retrieved_at_utc,
        }

    @staticmethod
    def _validate_faers_parent_ownership(
        connection: Connection,
        *,
        run_id: str,
        acquisition_id: str,
        result: FaersAggregateResult,
    ) -> None:
        snapshot = (
            connection.execute(
                sa.select(models.m1b_snapshots).where(
                    models.m1b_snapshots.c.run_id == run_id,
                    models.m1b_snapshots.c.source == "faers",
                    models.m1b_snapshots.c.acquisition_id == acquisition_id,
                    models.m1b_snapshots.c.query_id == result.query.query_id,
                    models.m1b_snapshots.c.snapshot_id == result.snapshot_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if snapshot is None or snapshot["manifest_artifact_id"] != result.manifest_id:
            raise ValueError("FAERS result requires its exact trusted snapshot and manifest")
        outcome = (
            connection.execute(
                sa.select(models.m1b_source_outcomes).where(
                    models.m1b_source_outcomes.c.run_id == run_id,
                    models.m1b_source_outcomes.c.source == "faers",
                    models.m1b_source_outcomes.c.acquisition_id == acquisition_id,
                    models.m1b_source_outcomes.c.query_id == result.query.query_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if outcome is None:
            raise ValueError("FAERS result requires its exact trusted SourceOutcome")
        expected_outcome = {
            "query_id": result.source_outcome.query_id,
            "source": "faers",
            "execution_status": result.source_outcome.execution_status.value,
            "coverage_status": result.source_outcome.coverage_status.value,
            "result_status": result.source_outcome.result_status.value,
            "max_query_characters": result.source_outcome.configured_bounds.max_query_characters,
            "max_pages": result.source_outcome.configured_bounds.max_pages,
            "max_records": result.source_outcome.configured_bounds.max_records,
            "max_payload_bytes": result.source_outcome.configured_bounds.max_payload_bytes,
            "max_total_seconds": result.source_outcome.configured_bounds.max_total_seconds,
            "valid_result_count": result.source_outcome.valid_result_count,
            "pages_completed": result.source_outcome.pages_completed,
            "truncated": result.source_outcome.truncated,
            "failure_id": result.source_outcome.failure_id,
            "warning_codes": list(result.source_outcome.warning_codes),
            "schema_version": result.source_outcome.schema_version,
            "snapshot_id": result.snapshot_id,
        }
        if any(
            _normalize(outcome[name]) != _normalize(value)
            for name, value in expected_outcome.items()
        ):
            raise ValueError("FAERS trusted SourceOutcome differs from the result")

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


class ProviderAttemptLedgerError(RuntimeError):
    """Stable failure for the authoritative insert-only provider-attempt ledger."""


class ProviderAttemptLedgerConflict(ProviderAttemptLedgerError):
    """A unique attempt/event slot already exists and must never be resent."""


@dataclass(slots=True)
class ProviderAttemptRunLease:
    connection: Connection
    provider_run_id: str


@dataclass(frozen=True, slots=True)
class ProviderAttemptEvent:
    event_id: str
    schema_version: str
    provider_run_id: str
    case_id: str
    case_ordinal: int
    attempt_ordinal: int
    event_kind: str
    event_slot: int
    start_event_id: str | None
    start_event_kind: str | None
    provider: str
    endpoint: str
    model: str
    configuration_hash: str
    request_hash: str
    started_at_utc: datetime
    completed_at_utc: datetime | None
    http_status: int | None
    disposition: str
    error_code: str | None
    credential_echo: bool
    body_complete: bool | None
    body_byte_count: int | None
    body_hash: str | None
    body_relative_path: str | None
    observed_body_bytes_lower_bound: int | None
    approved_header_names: tuple[str, ...]
    approved_header_names_identity: str | None = None
    normalized_header_names: tuple[str, ...] | None = None
    normalized_content_encoding_values: tuple[str, ...] | None = None
    normalized_content_length_values: tuple[str, ...] | None = None
    normalized_content_type_values: tuple[str, ...] | None = None
    normalized_transfer_encoding_values: tuple[str, ...] | None = None
    normalized_x_request_id_values: tuple[str, ...] | None = None
    normalized_header_facts_identity: str | None = None
    raw_header_field_count: int | None = None
    framing_contract_identity: str | None = None
    framing_input_identity: str | None = None
    http_version_state: str | None = None
    observed_http_version: str | None = None
    header_surface_state: str | None = None
    content_length_state: str | None = None
    content_length_value: int | None = None
    transfer_encoding_state: str | None = None
    content_encoding_state: str | None = None
    content_type_state: str | None = None
    actual_body_byte_count: int | None = None
    raw_evidence_state: str | None = None
    raw_body_hash: str | None = None
    raw_relative_path: str | None = None
    raw_artifact_identity: str | None = None
    framing_status: str | None = None
    accepted_framing_class: str | None = None
    framing_rejection_code: str | None = None


_PROVIDER_EVENT_FIELDS = tuple(ProviderAttemptEvent.__dataclass_fields__)
_PROVIDER_AUTHORITY_FIELDS = PERSISTED_AUTHORITY_FIELDS
_PROVIDER_AUTHORITY_FIELD_SET = frozenset(_PROVIDER_AUTHORITY_FIELDS)
_PROVIDER_RUN_ID = re.compile(r"provider-attempt-run:sha256:[0-9a-f]{64}")
_PROVIDER_CASE_ID = re.compile(r"M3-008B-CAL-[0-9]{3}")
_PROVIDER_EVENT_ID = re.compile(r"provider-attempt-event:sha256:[0-9a-f]{64}")
_PROVIDER_V1_TERMINAL_DISPOSITIONS = frozenset(models.PROVIDER_V1_TERMINAL_DISPOSITIONS)
_PROVIDER_V2_TERMINAL_DISPOSITIONS = frozenset(models.PROVIDER_V2_TERMINAL_DISPOSITIONS)
_PROVIDER_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "transfer-encoding",
        "content-encoding",
        "x-request-id",
    }
)


_PROVIDER_V2_FIELDS = frozenset(V2_ONLY_LEDGER_COLUMNS)

_PROVIDER_REQUIRED_STR_FIELDS = (
    "event_id",
    "schema_version",
    "provider_run_id",
    "case_id",
    "event_kind",
    "provider",
    "endpoint",
    "model",
    "configuration_hash",
    "request_hash",
    "disposition",
)
_PROVIDER_OPTIONAL_STR_FIELDS = (
    "start_event_id",
    "start_event_kind",
    "error_code",
    "body_hash",
    "body_relative_path",
    "approved_header_names_identity",
    "normalized_header_facts_identity",
    "framing_contract_identity",
    "framing_input_identity",
    "http_version_state",
    "observed_http_version",
    "header_surface_state",
    "content_length_state",
    "transfer_encoding_state",
    "content_encoding_state",
    "content_type_state",
    "raw_evidence_state",
    "raw_body_hash",
    "raw_relative_path",
    "raw_artifact_identity",
    "framing_status",
    "accepted_framing_class",
    "framing_rejection_code",
)
_PROVIDER_REQUIRED_INT_FIELDS = ("case_ordinal", "attempt_ordinal", "event_slot")
_PROVIDER_OPTIONAL_INT_FIELDS = (
    "http_status",
    "body_byte_count",
    "observed_body_bytes_lower_bound",
    "raw_header_field_count",
    "content_length_value",
    "actual_body_byte_count",
)
_PROVIDER_OPTIONAL_STR_TUPLE_FIELDS = (
    "normalized_header_names",
    "normalized_content_encoding_values",
    "normalized_content_length_values",
    "normalized_content_type_values",
    "normalized_transfer_encoding_values",
    "normalized_x_request_id_values",
)


def _provider_attempt_values_have_exact_primitive_types(
    *,
    required_strings: tuple[object, ...] = (),
    optional_strings: tuple[object, ...] = (),
    required_integers: tuple[object, ...] = (),
    optional_integers: tuple[object, ...] = (),
    required_booleans: tuple[object, ...] = (),
    optional_booleans: tuple[object, ...] = (),
    string_tuples: tuple[object, ...] = (),
    optional_string_tuples: tuple[object, ...] = (),
    required_datetimes: tuple[object, ...] = (),
    optional_datetimes: tuple[object, ...] = (),
) -> bool:
    """Return whether every supplied primitive has its exact built-in type."""

    return (
        all(type(value) is str for value in required_strings)
        and all(value is None or type(value) is str for value in optional_strings)
        and all(type(value) is int for value in required_integers)
        and all(value is None or type(value) is int for value in optional_integers)
        and all(type(value) is bool for value in required_booleans)
        and all(value is None or type(value) is bool for value in optional_booleans)
        and all(
            type(value) is tuple and all(type(item) is str for item in value)
            for value in string_tuples
        )
        and all(
            value is None or (type(value) is tuple and all(type(item) is str for item in value))
            for value in optional_string_tuples
        )
        and all(type(value) is datetime for value in required_datetimes)
        and all(value is None or type(value) is datetime for value in optional_datetimes)
    )


def _provider_attempt_event_primitives_are_exact(event: ProviderAttemptEvent) -> bool:
    return _provider_attempt_values_have_exact_primitive_types(
        required_strings=tuple(getattr(event, name) for name in _PROVIDER_REQUIRED_STR_FIELDS),
        optional_strings=tuple(getattr(event, name) for name in _PROVIDER_OPTIONAL_STR_FIELDS),
        required_integers=tuple(getattr(event, name) for name in _PROVIDER_REQUIRED_INT_FIELDS),
        optional_integers=tuple(getattr(event, name) for name in _PROVIDER_OPTIONAL_INT_FIELDS),
        required_booleans=(event.credential_echo,),
        optional_booleans=(event.body_complete,),
        string_tuples=(event.approved_header_names,),
        optional_string_tuples=tuple(
            getattr(event, name) for name in _PROVIDER_OPTIONAL_STR_TUPLE_FIELDS
        ),
        required_datetimes=(event.started_at_utc,),
        optional_datetimes=(event.completed_at_utc,),
    )


def _provider_attempt_observation_primitives_are_exact(value: object) -> bool:
    if type(value) is UnavailableObservation:
        unavailable = value
        return _provider_attempt_values_have_exact_primitive_types(
            required_strings=(unavailable.disposition, unavailable.input_identity),
            optional_integers=(unavailable.http_status,),
        )
    if type(value) is not FramingObservation:
        return False
    observation = value
    headers = observation.headers
    if (
        type(headers) is not NormalizedHeaderFacts
        or type(headers.occurrences) is not tuple
        or any(
            type(item) is not HeaderOccurrence
            or type(item.name) is not str
            or type(item.value) is not str
            for item in headers.occurrences
        )
        or type(headers.surface_state) is not HeaderSurfaceState
        or type(observation.http_version_state) is not HttpVersionState
        or type(observation.content_length_state) is not ContentLengthState
        or type(observation.transfer_encoding_state) is not TransferEncodingState
        or type(observation.content_encoding_state) is not ContentEncodingState
        or type(observation.content_type_state) is not ContentTypeState
        or type(observation.raw_evidence_state) is not RawEvidenceState
    ):
        return False
    return _provider_attempt_values_have_exact_primitive_types(
        required_strings=(
            observation.disposition,
            observation.input_identity,
            headers.approved_header_names_identity,
            headers.facts_identity,
        ),
        optional_strings=(
            observation.observed_http_version,
            observation.raw_body_hash,
            observation.raw_relative_path,
            observation.raw_artifact_identity,
        ),
        required_integers=(
            observation.http_status,
            observation.raw_header_field_count,
            observation.observed_body_bytes_lower_bound,
            headers.raw_header_field_count,
        ),
        optional_integers=(
            observation.content_length_value,
            observation.actual_body_byte_count,
        ),
        required_booleans=(observation.body_complete,),
        string_tuples=(headers.approved_header_names, headers.observed_names),
    )


def _validate_provider_attempt_event_primitives(event: ProviderAttemptEvent) -> None:
    """Reject coercible primitives before identity, reconstruction, or persistence."""

    if not _provider_attempt_event_primitives_are_exact(event):
        raise ValueError("provider attempt event primitive type is invalid")
    if event.started_at_utc.utcoffset() is None or (
        event.completed_at_utc is not None and event.completed_at_utc.utcoffset() is None
    ):
        raise ValueError("provider attempt event primitive type is invalid")


def _provider_attempt_disposition_matches_version(
    *, schema_version: str, event_kind: str, disposition: str
) -> bool:
    if event_kind == "START":
        return disposition == "started"
    if event_kind == "RECOVERY":
        return disposition == "interrupted_unknown_after_start"
    if event_kind != "TERMINAL":
        return False
    if schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        return disposition in _PROVIDER_V1_TERMINAL_DISPOSITIONS
    if schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2":
        return disposition in _PROVIDER_V2_TERMINAL_DISPOSITIONS
    return False


def _validate_make_provider_attempt_event_primitives(
    *,
    provider_run_id: object,
    case_id: object,
    case_ordinal: object,
    attempt_ordinal: object,
    event_kind: object,
    start_event: object,
    configuration_hash: object,
    request_hash: object,
    started_at_utc: object,
    completed_at_utc: object,
    http_status: object,
    disposition: object,
    error_code: object,
    credential_echo: object,
    body_complete: object,
    body_byte_count: object,
    body_hash: object,
    body_relative_path: object,
    observed_body_bytes_lower_bound: object,
    approved_header_names: object,
    schema_version: object,
    framing_observation: object,
) -> None:
    """Reject every non-exact caller primitive before any behavioral operation."""

    exact = _provider_attempt_values_have_exact_primitive_types(
        required_strings=(
            provider_run_id,
            case_id,
            event_kind,
            configuration_hash,
            request_hash,
            disposition,
            schema_version,
        ),
        optional_strings=(error_code, body_hash, body_relative_path),
        required_integers=(case_ordinal, attempt_ordinal),
        optional_integers=(http_status, body_byte_count, observed_body_bytes_lower_bound),
        required_booleans=(credential_echo,),
        optional_booleans=(body_complete,),
        string_tuples=(approved_header_names,),
        required_datetimes=(started_at_utc,),
        optional_datetimes=(completed_at_utc,),
    )
    if (
        not exact
        or (start_event is not None and type(start_event) is not ProviderAttemptEvent)
        or (
            type(start_event) is ProviderAttemptEvent
            and not _provider_attempt_event_primitives_are_exact(start_event)
        )
        or (
            framing_observation is not None
            and not _provider_attempt_observation_primitives_are_exact(framing_observation)
        )
    ):
        raise ValueError("provider attempt event primitive type is invalid")
    if cast(datetime, started_at_utc).utcoffset() is None or (
        cast(datetime | None, completed_at_utc) is not None
        and cast(datetime, completed_at_utc).utcoffset() is None
    ):
        raise ValueError("provider attempt event primitive type is invalid")
    if type(start_event) is ProviderAttemptEvent:
        _validate_provider_attempt_event_primitives(start_event)


def _provider_event_payload(event: ProviderAttemptEvent) -> dict[str, object]:
    excluded = {"event_id"}
    if event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        excluded.update(_PROVIDER_V2_FIELDS)
    authority = {name: getattr(event, name) for name in _PROVIDER_AUTHORITY_FIELDS}
    return {
        name: authority[name] if name in _PROVIDER_AUTHORITY_FIELD_SET else getattr(event, name)
        for name in _PROVIDER_EVENT_FIELDS
        if name not in excluded
    }


def _provider_storage_payload(event: ProviderAttemptEvent) -> dict[str, object]:
    authority = {name: getattr(event, name) for name in _PROVIDER_AUTHORITY_FIELDS}
    return {
        name: authority[name] if name in _PROVIDER_AUTHORITY_FIELD_SET else getattr(event, name)
        for name in _PROVIDER_EVENT_FIELDS
        if name != "event_id"
    }


def canonical_provider_attempt_event_id(payload: Mapping[str, object]) -> str:
    """Return the deterministic identity of one exact event projection."""

    return (
        "provider-attempt-event:sha256:"
        + sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()
    )


def _provider_v2_fields_are_null(event: ProviderAttemptEvent) -> bool:
    return all(getattr(event, name) is None for name in _PROVIDER_V2_FIELDS)


def _provider_fact_free_projection(event: ProviderAttemptEvent) -> dict[str, object]:
    return {
        "schema_version": event.schema_version,
        "event_kind": event.event_kind,
        **{name: getattr(event, name) for name in _PROVIDER_AUTHORITY_FIELDS},
    }


def _provider_v2_observation(event: ProviderAttemptEvent) -> Observation | None:
    """Rebuild the exact contract input; stored decisions never authorize themselves."""

    if event.schema_version != "M3_PROVIDER_ATTEMPT_EVENT_V2":
        return None
    if not v2_event_metadata_matches(
        {
            "event_kind": event.event_kind,
            "disposition": event.disposition,
            "credential_echo": event.credential_echo,
            "error_code": event.error_code,
        }
    ):
        raise ValueError("V2 event metadata differs from canonical topology")
    if fact_free_v2_event_matches(_provider_fact_free_projection(event)):
        return None
    if _provider_v2_fields_are_null(event):
        raise ValueError("V2 fact-free event differs from canonical topology")
    if event.framing_contract_identity != framing_contract_identity():
        raise ValueError("V2 framing contract identity drift")
    if event.disposition in {"credential_echo", "evidence_persistence_failure"}:
        if event.http_status is None:
            raise ValueError("V2 unavailable response terminal requires HTTP status")
        observation: Observation = build_unavailable_observation(
            disposition=event.disposition,
            http_status=event.http_status,
        )
    else:
        if (
            event.normalized_header_names is None
            or event.approved_header_names_identity is None
            or event.normalized_header_facts_identity is None
            or event.raw_header_field_count is None
            or event.header_surface_state is None
        ):
            raise ValueError("V2 normalized header provenance is incomplete")
        value_fields = (
            ("content-encoding", event.normalized_content_encoding_values),
            ("content-length", event.normalized_content_length_values),
            ("content-type", event.normalized_content_type_values),
            ("transfer-encoding", event.normalized_transfer_encoding_values),
            ("x-request-id", event.normalized_x_request_id_values),
        )
        if any(values is None for _, values in value_fields):
            raise ValueError("V2 normalized header value provenance is incomplete")
        occurrences = tuple(
            (name, value)
            for name, values in value_fields
            for value in cast(tuple[str, ...], values)
        )
        headers = reconstruct_normalized_headers(
            approved_header_names=event.approved_header_names,
            approved_header_names_identity=event.approved_header_names_identity,
            occurrences=occurrences,
            observed_names=event.normalized_header_names,
            raw_header_field_count=event.raw_header_field_count,
            surface_state=event.header_surface_state,
            facts_identity=event.normalized_header_facts_identity,
        )
        if event.http_status is None or event.body_complete is None:
            raise ValueError("V2 response observation is incomplete")
        observation = build_framing_observation(
            disposition=event.disposition,
            http_status=event.http_status,
            http_version=event.observed_http_version,
            headers=headers,
            raw_header_field_count=event.raw_header_field_count,
            body_complete=event.body_complete,
            actual_body_byte_count=event.actual_body_byte_count,
            raw_body_hash=event.raw_body_hash,
            raw_relative_path=event.raw_relative_path,
            observed_body_bytes_lower_bound=event.observed_body_bytes_lower_bound,
        )
    projection = canonical_observation_projection(observation)
    if event.approved_header_names != projection["approved_header_names"]:
        raise ValueError("V2 canonical framing projection drift: approved_header_names")
    for name in _PROVIDER_V2_FIELDS:
        if name in projection and getattr(event, name) != projection[name]:
            raise ValueError(f"V2 canonical framing projection drift: {name}")
    if type(observation) is UnavailableObservation and any(
        getattr(event, name) is not None
        for name in (
            "normalized_content_encoding_values",
            "normalized_content_length_values",
            "normalized_content_type_values",
            "normalized_transfer_encoding_values",
            "normalized_x_request_id_values",
        )
    ):
        raise ValueError("V2 unavailable terminal fabricated normalized header facts")
    if not projection_matches(
        observation,
        framing_status=cast(str, event.framing_status),
        accepted_framing_class=event.accepted_framing_class,
        framing_rejection_code=event.framing_rejection_code,
        framing_input_identity=cast(str, event.framing_input_identity),
    ):
        raise ValueError("V2 stored framing decision differs from recomputation")
    legacy_v2_raw_projection(
        observation,
        {
            "body_byte_count": event.body_byte_count,
            "body_hash": event.body_hash,
            "body_relative_path": event.body_relative_path,
            "observed_body_bytes_lower_bound": event.observed_body_bytes_lower_bound,
        },
    )
    if type(observation) is UnavailableObservation and event.body_complete is not None:
        raise ValueError("V2 unavailable terminal fabricated response facts")
    return observation


def validate_provider_attempt_event(event: ProviderAttemptEvent) -> ProviderAttemptEvent:
    if type(event) is not ProviderAttemptEvent:
        raise ValueError("provider attempt event type is invalid")
    _validate_provider_attempt_event_primitives(event)
    if event.body_relative_path is not None and not provider_raw_relative_path_is_canonical(
        event.body_relative_path
    ):
        raise ValueError("provider attempt body relative path is noncanonical")
    if not _provider_attempt_disposition_matches_version(
        schema_version=event.schema_version,
        event_kind=event.event_kind,
        disposition=event.disposition,
    ):
        raise ValueError("provider attempt disposition is invalid for schema version")
    if event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2" and (
        not v2_event_metadata_matches(
            {
                "event_kind": event.event_kind,
                "disposition": event.disposition,
                "credential_echo": event.credential_echo,
                "error_code": event.error_code,
            }
        )
    ):
        raise ValueError("V2 event metadata differs from canonical topology")
    payload = _provider_event_payload(event)
    v1_start_shape = (
        event.event_kind == "START"
        and event.start_event_id is None
        and event.start_event_kind is None
        and event.disposition == "started"
        and event.completed_at_utc is None
        and event.http_status is None
        and event.error_code is None
        and not event.credential_echo
        and event.body_complete is None
        and event.body_hash is None
        and event.body_relative_path is None
    )
    v1_recovery_shape = (
        event.event_kind == "RECOVERY"
        and event.start_event_id is not None
        and event.start_event_kind == "START"
        and event.disposition == "interrupted_unknown_after_start"
        and event.error_code == "interrupted_unknown_after_start"
        and event.completed_at_utc is not None
        and event.http_status is None
        and event.body_hash is None
        and event.body_relative_path is None
    )
    v1_terminal_shape = (
        event.event_kind == "TERMINAL"
        and event.start_event_id is not None
        and event.start_event_kind == "START"
        and event.completed_at_utc is not None
        and (
            (event.disposition == "success" and event.error_code is None)
            or (event.disposition != "success" and event.error_code == event.disposition)
        )
        and (
            event.disposition != "success"
            or (
                event.body_complete is True
                and event.body_hash is not None
                and event.body_relative_path is not None
                and event.body_byte_count is not None
            )
        )
        and (
            (
                event.credential_echo
                and event.disposition == "credential_echo"
                and event.body_hash is None
                and event.body_relative_path is None
            )
            or (
                not event.credential_echo
                and (
                    (
                        event.body_hash is not None
                        and event.body_relative_path is not None
                        and event.body_complete is True
                        and event.body_byte_count is not None
                        and event.observed_body_bytes_lower_bound == event.body_byte_count
                    )
                    or (event.body_hash is None and event.body_relative_path is None)
                )
            )
        )
    )
    v2_shape = (
        (
            event.event_kind == "START"
            and event.start_event_id is None
            and event.start_event_kind is None
            and event.completed_at_utc is None
        )
        or (
            event.event_kind == "RECOVERY"
            and event.start_event_id is not None
            and event.start_event_kind == "START"
            and event.completed_at_utc is not None
        )
        or (
            event.event_kind == "TERMINAL"
            and event.start_event_id is not None
            and event.start_event_kind == "START"
            and event.completed_at_utc is not None
        )
    )
    if (
        _PROVIDER_EVENT_ID.fullmatch(event.event_id) is None
        or event.event_id != canonical_provider_attempt_event_id(payload)
        or event.schema_version
        not in {"M3_PROVIDER_ATTEMPT_EVENT_V1", "M3_PROVIDER_ATTEMPT_EVENT_V2"}
        or _PROVIDER_RUN_ID.fullmatch(event.provider_run_id) is None
        or _PROVIDER_CASE_ID.fullmatch(event.case_id) is None
        or event.case_id != f"M3-008B-CAL-{event.case_ordinal:03d}"
        or not 1 <= event.case_ordinal <= 36
        or not 1 <= event.attempt_ordinal <= 3
        or (event.event_kind, event.event_slot)
        not in {("START", 0), ("TERMINAL", 1), ("RECOVERY", 1)}
        or event.provider != "DeepSeek API"
        or event.endpoint != "https://api.deepseek.com/responses"
        or event.model != "deepseek-v4-pro"
        or _SHA256_DIGEST.fullmatch(event.configuration_hash) is None
        or _SHA256_DIGEST.fullmatch(event.request_hash) is None
        or not (
            (
                event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1"
                and (v1_start_shape or v1_recovery_shape or v1_terminal_shape)
            )
            or (event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2" and v2_shape)
        )
        or tuple(sorted(set(event.approved_header_names))) != event.approved_header_names
        or any(name not in _PROVIDER_HEADERS for name in event.approved_header_names)
        or event.started_at_utc.tzinfo is None
        or (
            event.completed_at_utc is not None
            and (
                event.completed_at_utc.tzinfo is None
                or event.completed_at_utc < event.started_at_utc
            )
        )
    ):
        raise ValueError("provider attempt event violates the closed contract")
    if event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        if not _provider_v2_fields_are_null(event):
            raise ValueError("V1 provider attempt event cannot contain V2 framing facts")
    else:
        _provider_v2_observation(event)
    return event


class ProviderAttemptLedgerRepository:
    """Dedicated insert/list/recovery API; deliberately exposes no update or delete."""

    def __init__(self, settings: PersistenceSettings) -> None:
        self._engine = _create_engine(settings)

    @classmethod
    def _from_engine_for_testing(cls, engine: Engine) -> ProviderAttemptLedgerRepository:
        value = cls.__new__(cls)
        value._engine = engine
        return value

    def close(self) -> None:
        self._engine.dispose()

    def acquire_run_lease(self, provider_run_id: str) -> ProviderAttemptRunLease:
        if _PROVIDER_RUN_ID.fullmatch(provider_run_id) is None:
            raise ValueError("provider_run_id is invalid")
        connection = self._engine.connect()
        acquired = connection.scalar(
            sa.text("SELECT pg_try_advisory_lock(hashtextextended(:run_id, 0))"),
            {"run_id": provider_run_id},
        )
        if acquired is not True:
            connection.close()
            raise ProviderAttemptLedgerConflict("provider run lease is already held")
        return ProviderAttemptRunLease(connection, provider_run_id)

    def release_run_lease(self, lease: ProviderAttemptRunLease) -> None:
        if type(lease) is not ProviderAttemptRunLease:
            raise ValueError("provider run lease type is invalid")
        try:
            lease.connection.scalar(
                sa.text("SELECT pg_advisory_unlock(hashtextextended(:run_id, 0))"),
                {"run_id": lease.provider_run_id},
            )
        finally:
            lease.connection.close()

    def append(self, event: ProviderAttemptEvent) -> ProviderAttemptEvent:
        value = validate_provider_attempt_event(event)
        values = _provider_storage_payload(value)
        values["event_id"] = value.event_id
        try:
            with self._engine.begin() as connection:
                if value.event_kind != "START":
                    start_row = (
                        connection.execute(
                            sa.select(models.m3_provider_attempt_events).where(
                                models.m3_provider_attempt_events.c.event_id == value.start_event_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if start_row is None:
                        raise ProviderAttemptLedgerConflict(
                            "closure requires the exact persisted START"
                        )
                    start = _provider_event_from_row(dict(start_row))
                    if (
                        start.event_id != value.start_event_id
                        or start.event_kind != "START"
                        or start.schema_version != value.schema_version
                        or start.provider_run_id != value.provider_run_id
                        or start.case_id != value.case_id
                        or start.case_ordinal != value.case_ordinal
                        or start.attempt_ordinal != value.attempt_ordinal
                        or start.configuration_hash != value.configuration_hash
                        or start.request_hash != value.request_hash
                    ):
                        raise ProviderAttemptLedgerConflict(
                            "closure requires the exact persisted START"
                        )
                connection.execute(models.m3_provider_attempt_events.insert().values(**values))
        except ProviderAttemptLedgerConflict:
            raise
        except IntegrityError as error:
            if _is_unique_violation(error):
                raise ProviderAttemptLedgerConflict(
                    "provider attempt event slot already exists"
                ) from None
            raise ProviderAttemptLedgerError("provider attempt event insert failed") from error
        return value

    def list_events(self, provider_run_id: str) -> tuple[ProviderAttemptEvent, ...]:
        if _PROVIDER_RUN_ID.fullmatch(provider_run_id) is None:
            raise ValueError("provider_run_id is invalid")
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(models.m3_provider_attempt_events)
                    .where(models.m3_provider_attempt_events.c.provider_run_id == provider_run_id)
                    .order_by(
                        models.m3_provider_attempt_events.c.case_ordinal,
                        models.m3_provider_attempt_events.c.attempt_ordinal,
                        models.m3_provider_attempt_events.c.event_slot,
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_provider_event_from_row(dict(row)) for row in rows)

    def reconcile_orphan_starts(
        self, provider_run_id: str, *, recovered_at_utc: datetime
    ) -> tuple[ProviderAttemptEvent, ...]:
        if _PROVIDER_RUN_ID.fullmatch(provider_run_id) is None:
            raise ValueError("provider_run_id is invalid")
        if recovered_at_utc.tzinfo is None:
            raise ValueError("recovery timestamp must be timezone-aware")
        inserted: list[ProviderAttemptEvent] = []
        with self._engine.begin() as connection:
            connection.execute(
                sa.text(
                    'LOCK TABLE "medevidence"."m3_provider_attempt_events" '
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
            rows = (
                connection.execute(
                    sa.select(models.m3_provider_attempt_events)
                    .where(models.m3_provider_attempt_events.c.provider_run_id == provider_run_id)
                    .order_by(
                        models.m3_provider_attempt_events.c.case_ordinal,
                        models.m3_provider_attempt_events.c.attempt_ordinal,
                        models.m3_provider_attempt_events.c.event_slot,
                    )
                )
                .mappings()
                .all()
            )
            grouped: dict[tuple[int, int], list[dict[str, object]]] = {}
            for row in rows:
                item = dict(row)
                grouped.setdefault(
                    (cast(int, item["case_ordinal"]), cast(int, item["attempt_ordinal"])), []
                ).append(item)
            for events in grouped.values():
                kinds = {cast(str, item["event_kind"]) for item in events}
                if "START" not in kinds or kinds & {"TERMINAL", "RECOVERY"}:
                    continue
                start = _provider_event_from_row(events[0])
                recovery = make_provider_attempt_event(
                    provider_run_id=start.provider_run_id,
                    case_id=start.case_id,
                    case_ordinal=start.case_ordinal,
                    attempt_ordinal=start.attempt_ordinal,
                    event_kind="RECOVERY",
                    start_event=start,
                    configuration_hash=start.configuration_hash,
                    request_hash=start.request_hash,
                    started_at_utc=start.started_at_utc,
                    completed_at_utc=recovered_at_utc,
                    disposition="interrupted_unknown_after_start",
                    error_code="interrupted_unknown_after_start",
                    schema_version=start.schema_version,
                )
                values = _provider_storage_payload(recovery)
                values["event_id"] = recovery.event_id
                connection.execute(models.m3_provider_attempt_events.insert().values(**values))
                inserted.append(recovery)
        return tuple(inserted)


def make_provider_attempt_event(
    *,
    provider_run_id: str,
    case_id: str,
    case_ordinal: int,
    attempt_ordinal: int,
    event_kind: str,
    start_event: ProviderAttemptEvent | None = None,
    configuration_hash: str,
    request_hash: str,
    started_at_utc: datetime,
    completed_at_utc: datetime | None = None,
    http_status: int | None = None,
    disposition: str = "started",
    error_code: str | None = None,
    credential_echo: bool = False,
    body_complete: bool | None = None,
    body_byte_count: int | None = None,
    body_hash: str | None = None,
    body_relative_path: str | None = None,
    observed_body_bytes_lower_bound: int | None = None,
    approved_header_names: tuple[str, ...] = (),
    schema_version: str = "M3_PROVIDER_ATTEMPT_EVENT_V1",
    framing_observation: Observation | None = None,
) -> ProviderAttemptEvent:
    _validate_make_provider_attempt_event_primitives(
        provider_run_id=provider_run_id,
        case_id=case_id,
        case_ordinal=case_ordinal,
        attempt_ordinal=attempt_ordinal,
        event_kind=event_kind,
        start_event=start_event,
        configuration_hash=configuration_hash,
        request_hash=request_hash,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        http_status=http_status,
        disposition=disposition,
        error_code=error_code,
        credential_echo=credential_echo,
        body_complete=body_complete,
        body_byte_count=body_byte_count,
        body_hash=body_hash,
        body_relative_path=body_relative_path,
        observed_body_bytes_lower_bound=observed_body_bytes_lower_bound,
        approved_header_names=approved_header_names,
        schema_version=schema_version,
        framing_observation=framing_observation,
    )
    if not _provider_attempt_disposition_matches_version(
        schema_version=schema_version,
        event_kind=event_kind,
        disposition=disposition,
    ):
        raise ValueError("provider attempt disposition is invalid for schema version")
    if schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2" and (
        type(credential_echo) is not bool
        or not v2_event_metadata_matches(
            {
                "event_kind": event_kind,
                "disposition": disposition,
                "credential_echo": credential_echo,
                "error_code": error_code,
            }
        )
    ):
        raise ValueError("V2 event metadata differs from canonical topology")
    slot = {"START": 0, "TERMINAL": 1, "RECOVERY": 1}.get(event_kind)
    if slot is None:
        raise ValueError("provider attempt event kind is invalid")
    if (event_kind == "START") != (start_event is None):
        raise ValueError("closure must bind one exact START event")
    if start_event is not None and (
        start_event.event_kind != "START"
        or start_event.provider_run_id != provider_run_id
        or start_event.case_id != case_id
        or start_event.case_ordinal != case_ordinal
        or start_event.attempt_ordinal != attempt_ordinal
        or start_event.configuration_hash != configuration_hash
        or start_event.request_hash != request_hash
        or start_event.schema_version != schema_version
    ):
        raise ValueError("closure differs from exact START binding")
    framing: dict[str, object] = {name: None for name in _PROVIDER_V2_FIELDS}
    if schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1":
        if framing_observation is not None:
            raise ValueError("V1 provider attempt event cannot reinterpret V2 framing facts")
    elif schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V2":
        if framing_observation is not None:
            if event_kind != "TERMINAL":
                raise ValueError("only a terminal event may bind a framing observation")
            projection = canonical_observation_projection(framing_observation)
            if projection["disposition"] != disposition or projection["http_status"] != http_status:
                raise ValueError("framing observation differs from terminal event")
            if (
                any(
                    value is not None
                    for value in (
                        body_complete,
                        body_byte_count,
                        body_hash,
                        body_relative_path,
                    )
                )
                or approved_header_names
            ):
                raise ValueError("V2 raw/header facts must derive only from framing observation")
            framing.update({name: projection.get(name) for name in _PROVIDER_V2_FIELDS})
            legacy = legacy_v2_raw_projection(framing_observation)
            body_byte_count = cast(int | None, legacy["body_byte_count"])
            body_hash = cast(str | None, legacy["body_hash"])
            body_relative_path = cast(str | None, legacy["body_relative_path"])
            observed_body_bytes_lower_bound = cast(
                int | None,
                legacy["observed_body_bytes_lower_bound"],
            )
            if type(framing_observation) is FramingObservation:
                body_complete = framing_observation.body_complete
                framing["raw_body_hash"] = framing_observation.raw_body_hash
                framing["raw_relative_path"] = framing_observation.raw_relative_path
            else:
                credential_echo = disposition == "credential_echo"
            approved_header_names = cast(tuple[str, ...], projection["approved_header_names"])
        else:
            expected = canonical_fact_free_v2_event_projection(
                event_kind=event_kind,
                disposition=disposition,
            )
            supplied = {
                "schema_version": schema_version,
                "event_kind": event_kind,
                "disposition": disposition,
                "error_code": error_code,
                "http_status": http_status,
                "credential_echo": credential_echo,
                "body_complete": body_complete,
                "body_byte_count": body_byte_count,
                "body_hash": body_hash,
                "body_relative_path": body_relative_path,
                "observed_body_bytes_lower_bound": observed_body_bytes_lower_bound,
                "approved_header_names": approved_header_names,
                **framing,
            }
            if supplied != expected:
                raise ValueError("V2 fact-free event differs from canonical topology")
    else:
        raise ValueError("provider attempt schema version is invalid")
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "provider_run_id": provider_run_id,
        "case_id": case_id,
        "case_ordinal": case_ordinal,
        "attempt_ordinal": attempt_ordinal,
        "event_kind": event_kind,
        "event_slot": slot,
        "start_event_id": start_event.event_id if start_event is not None else None,
        "start_event_kind": "START" if start_event is not None else None,
        "provider": "DeepSeek API",
        "endpoint": "https://api.deepseek.com/responses",
        "model": "deepseek-v4-pro",
        "configuration_hash": configuration_hash,
        "request_hash": request_hash,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "http_status": http_status,
        "disposition": disposition,
        "error_code": error_code,
        "credential_echo": credential_echo,
        "body_complete": body_complete,
        "body_byte_count": body_byte_count,
        "body_hash": body_hash,
        "body_relative_path": body_relative_path,
        "observed_body_bytes_lower_bound": observed_body_bytes_lower_bound,
        "approved_header_names": approved_header_names,
    }
    identity_payload = payload if schema_version.endswith("_V1") else {**payload, **framing}
    event = ProviderAttemptEvent(
        event_id="provider-attempt-event:sha256:" + "0" * 64,
        **payload,  # type: ignore[arg-type]
        **framing,  # type: ignore[arg-type]
    )
    _validate_provider_attempt_event_primitives(event)
    event = replace(
        event,
        event_id=canonical_provider_attempt_event_id(identity_payload),
    )
    return validate_provider_attempt_event(event)


def _provider_event_from_row(row: Mapping[str, object]) -> ProviderAttemptEvent:
    values = {name: row[name] for name in _PROVIDER_EVENT_FIELDS}
    values["approved_header_names"] = tuple(cast(Sequence[str], values["approved_header_names"]))
    normalized_names = values["normalized_header_names"]
    if normalized_names is not None:
        values["normalized_header_names"] = tuple(cast(Sequence[str], normalized_names))
    for name in (
        "normalized_content_encoding_values",
        "normalized_content_length_values",
        "normalized_content_type_values",
        "normalized_transfer_encoding_values",
        "normalized_x_request_id_values",
    ):
        item = values[name]
        if item is not None:
            values[name] = tuple(cast(Sequence[str], item))
    try:
        return validate_provider_attempt_event(ProviderAttemptEvent(**values))  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError) as error:
        raise ProviderAttemptLedgerError("stored provider attempt event is invalid") from error


class ReviewExportRepository(PersistenceRepository):
    """Bounded PostgreSQL operations for document, review, and export records."""

    def _save_immutable(self, table_name: str, values: Mapping[str, object]) -> dict[str, object]:
        spec = _SPECS[table_name]
        with self._engine.begin() as connection:
            return self._insert_or_verify(connection, spec, values, method=f"save_{table_name}")

    def save_document(self, values: Mapping[str, object]) -> dict[str, object]:
        return self._save_immutable("m3_report_documents", values)

    def load_document(self, report_id: str, report_content_hash: str) -> dict[str, object] | None:
        if (
            type(report_id) is not str
            or _VALIDATION_REPORT_ID.fullmatch(report_id) is None
            or type(report_content_hash) is not str
            or _SHA256_DIGEST.fullmatch(report_content_hash) is None
        ):
            raise ValueError("document lookup requires exact report identity and hash")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_report_documents).where(
                        models.m3_report_documents.c.report_id == report_id,
                        models.m3_report_documents.c.report_content_hash == report_content_hash,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    def save_pending_draft(self, values: Mapping[str, object]) -> dict[str, object]:
        return self._save_immutable("m3_pending_drafts", values)

    def load_pending_draft(self, persistence_id: str) -> dict[str, object] | None:
        if type(persistence_id) is not str or not persistence_id.startswith(
            "pending-draft:sha256:"
        ):
            raise ValueError("pending draft identity is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_pending_drafts).where(
                        models.m3_pending_drafts.c.persistence_id == persistence_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    def save_review(self, values: Mapping[str, object]) -> dict[str, object]:
        return self._save_immutable("m3_review_records", values)

    def load_review(self, pending_id: str, destination_id: str) -> dict[str, object] | None:
        if type(pending_id) is not str or type(destination_id) is not str:
            raise ValueError("review lookup identity is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_review_records).where(
                        models.m3_review_records.c.pending_draft_persistence_id == pending_id,
                        models.m3_review_records.c.destination_id == destination_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    def prepare_export(self, values: Mapping[str, object]) -> dict[str, object]:
        """Reserve one logical export before filesystem work."""

        table = models.m3_exports
        immutable = frozenset(table.c.keys()) - {"status", "prepared_at_utc", "exported_at_utc"}
        if set(values) != immutable:
            raise ValueError("export preparation requires exact immutable fields")
        with self._engine.begin() as connection:
            connection.execute(
                sa.text('LOCK TABLE "medevidence"."m3_exports" IN SHARE ROW EXCLUSIVE MODE')
            )
            existing = (
                connection.execute(
                    sa.select(table).where(table.c.idempotency_key == values["idempotency_key"])
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                row = dict(existing)
                if any(
                    _normalize(row.get(name)) != _normalize(value) for name, value in values.items()
                ):
                    raise PersistenceConflict("m3_exports", "uq_m3_export_idempotency")
                return row
            count = connection.scalar(sa.select(sa.func.count()).select_from(table))
            if count is None or count >= 1_000:
                raise PersistenceCapacityError("frozen capacity reached for m3_exports: 1000")
            prepared = {
                **values,
                "status": "prepared",
                "prepared_at_utc": datetime.now(UTC),
                "exported_at_utc": None,
            }
            try:
                connection.execute(table.insert().values(**prepared))
            except IntegrityError as error:
                if _is_unique_violation(error):
                    raise PersistenceConflict("m3_exports", _constraint_name(error)) from None
                raise
            return prepared

    def load_export(self, idempotency_key: str) -> dict[str, object] | None:
        if type(idempotency_key) is not str or _SHA256_DIGEST.fullmatch(idempotency_key) is None:
            raise ValueError("export idempotency key is invalid")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(models.m3_exports).where(
                        models.m3_exports.c.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else dict(row)

    def commit_export(
        self, idempotency_key: str, values: Mapping[str, object]
    ) -> dict[str, object]:
        """Advance a verified prepared row to committed exactly once."""

        table = models.m3_exports
        immutable = frozenset(table.c.keys()) - {"status", "prepared_at_utc", "exported_at_utc"}
        if set(values) != immutable or values.get("idempotency_key") != idempotency_key:
            raise ValueError("export commit requires exact immutable fields")
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(table)
                    .where(table.c.idempotency_key == idempotency_key)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PersistenceIntegrityError("prepared export is missing")
            stored = dict(row)
            if any(
                _normalize(stored.get(name)) != _normalize(value) for name, value in values.items()
            ):
                raise PersistenceIntegrityError("prepared export binding drift")
            if stored["status"] == "committed":
                return stored
            if stored["status"] != "prepared" or stored["exported_at_utc"] is not None:
                raise PersistenceIntegrityError("prepared export status drift")
            exported_at = datetime.now(UTC)
            connection.execute(
                table.update()
                .where(table.c.idempotency_key == idempotency_key, table.c.status == "prepared")
                .values(status="committed", exported_at_utc=exported_at)
            )
            return {**stored, "status": "committed", "exported_at_utc": exported_at}
