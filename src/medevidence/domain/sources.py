"""Source planning, terminal outcomes, warnings, failures, and provenance."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from .identifiers import (
    ArtifactId,
    ConnectorVersion,
    DurableModel,
    FailureId,
    LongText,
    QueryId,
    SchemaVersion,
    Sha256Digest,
    SnapshotId,
    SourceLookupKey,
    SourceRecordId,
    UtcDateTime,
    WarningCode,
)
from .scope import ExecutionBounds, SourceType


class PlanningStatus(StrEnum):
    """Planning state for each considered source."""

    SELECTED = "selected"
    SKIPPED_NOT_APPLICABLE = "skipped_not_applicable"
    SKIPPED_BY_POLICY = "skipped_by_policy"


class SourcePlanReasonCode(StrEnum):
    """Deterministic reason for a skipped source."""

    NOT_APPLICABLE_TO_SCOPE = "not_applicable_to_scope"
    SOURCE_EXECUTION_NOT_AUTHORIZED = "source_execution_not_authorized"


class ExecutionStatus(StrEnum):
    """Whether an executed source operation completed."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CoverageStatus(StrEnum):
    """Coverage of the declared bounded source scope."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ResultStatus(StrEnum):
    """Evidence-result meaning for a terminal source operation."""

    MATCHES = "matches"
    NO_MATCH = "no_match"
    INDETERMINATE = "indeterminate"


class FailureCode(StrEnum):
    """Source-neutral failure classification."""

    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    INTEGRITY_FAILURE = "integrity_failure"
    UNKNOWN = "unknown"


class DomainWarning(DurableModel):
    """Typed machine-readable warning with deterministic disclosure text."""

    schema_version: SchemaVersion = "1.0"
    code: WarningCode
    message: LongText


class SourcePlanEntry(DurableModel):
    """Planning decision; deliberately contains no execution outcome."""

    schema_version: SchemaVersion = "1.0"
    source: SourceType
    planning_status: PlanningStatus
    reason_code: SourcePlanReasonCode | None = None
    reason: LongText | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        expected = {
            PlanningStatus.SELECTED: None,
            PlanningStatus.SKIPPED_NOT_APPLICABLE: (SourcePlanReasonCode.NOT_APPLICABLE_TO_SCOPE),
            PlanningStatus.SKIPPED_BY_POLICY: (
                SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED
            ),
        }[self.planning_status]
        if self.reason_code != expected:
            raise ValueError("reason_code does not match planning_status")
        if self.planning_status is PlanningStatus.SELECTED and self.reason is not None:
            raise ValueError("selected source must not contain a skip reason")
        if self.planning_status is not PlanningStatus.SELECTED and self.reason is None:
            raise ValueError("skipped source requires a human-readable reason")
        if self.planning_status is PlanningStatus.SELECTED and self.source is not SourceType.PUBMED:
            raise ValueError("only PubMed execution is authorized in M1A")
        return self


class SourceFailure(DurableModel):
    """Typed failure identity and retry classification."""

    failure_id: FailureId
    failure_code: FailureCode
    retryable: bool


class SourceOutcome(DurableModel):
    """Immutable three-dimensional terminal outcome for an executed source."""

    schema_version: SchemaVersion = "1.0"
    source: SourceType
    query_id: QueryId
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    configured_bounds: ExecutionBounds
    valid_result_count: int = Field(ge=0)
    pages_completed: int = Field(ge=0)
    truncated: bool
    warning_codes: tuple[WarningCode, ...] = ()
    failure_id: FailureId | None = None

    @model_validator(mode="after")
    def validate_terminal_contract(self) -> Self:
        valid_triples = {
            (
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.MATCHES,
            ),
            (
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.NO_MATCH,
            ),
            (
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.PARTIAL,
                ResultStatus.MATCHES,
            ),
            (
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.PARTIAL,
                ResultStatus.INDETERMINATE,
            ),
            (
                ExecutionStatus.FAILED,
                CoverageStatus.PARTIAL,
                ResultStatus.MATCHES,
            ),
            (
                ExecutionStatus.FAILED,
                CoverageStatus.PARTIAL,
                ResultStatus.INDETERMINATE,
            ),
            (
                ExecutionStatus.FAILED,
                CoverageStatus.UNAVAILABLE,
                ResultStatus.INDETERMINATE,
            ),
        }
        triple = (
            self.execution_status,
            self.coverage_status,
            self.result_status,
        )
        if triple not in valid_triples:
            raise ValueError("invalid execution/coverage/result combination")
        if self.result_status is ResultStatus.MATCHES and self.valid_result_count < 1:
            raise ValueError("matches requires at least one valid result")
        if (
            self.result_status in {ResultStatus.NO_MATCH, ResultStatus.INDETERMINATE}
            and self.valid_result_count != 0
        ):
            raise ValueError("zero-result outcome requires zero valid results")
        if self.coverage_status is CoverageStatus.COMPLETE and self.truncated:
            raise ValueError("complete coverage forbids truncation")
        if self.execution_status is ExecutionStatus.FAILED and self.failure_id is None:
            raise ValueError("failed execution requires failure_id")
        if self.execution_status is ExecutionStatus.SUCCEEDED and self.failure_id is not None:
            raise ValueError("succeeded execution forbids failure_id")
        if self.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.pages_completed != 0 or self.valid_result_count != 0
        ):
            raise ValueError("unavailable coverage requires zero pages and results")
        if self.coverage_status in {CoverageStatus.PARTIAL, CoverageStatus.UNAVAILABLE} and (
            not self.warning_codes
        ):
            raise ValueError("partial or unavailable coverage requires a warning")
        if len(set(self.warning_codes)) != len(self.warning_codes):
            raise ValueError("warning codes must be unique")
        if self.warning_codes != tuple(sorted(self.warning_codes)):
            raise ValueError("warning codes must be canonically sorted")
        if self.pages_completed > self.configured_bounds.max_pages:
            raise ValueError("pages_completed exceeds configured bound")
        if self.valid_result_count > self.configured_bounds.max_records:
            raise ValueError("valid_result_count exceeds configured bound")
        return self


class Provenance(DurableModel):
    """Traceable acquisition provenance without storage or provider-native types."""

    schema_version: SchemaVersion = "1.0"
    source: SourceType
    source_record_id: SourceRecordId | None
    query_id: QueryId
    source_lookup_key: SourceLookupKey
    retrieved_at: UtcDateTime
    connector_version: ConnectorVersion
    content_hash: Sha256Digest
    snapshot_id: SnapshotId | None = None
    artifact_ids: tuple[ArtifactId, ...] = ()
    transformation_lineage: tuple[ArtifactId, ...] = ()
    warnings: tuple[DomainWarning, ...] = ()
    failure: SourceFailure | None = None
    source_outcome: SourceOutcome
    configured_bounds: ExecutionBounds

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        if self.source != self.source_outcome.source:
            raise ValueError("provenance source must match source outcome")
        if self.query_id != self.source_outcome.query_id:
            raise ValueError("provenance query_id must match source outcome")
        if self.configured_bounds != self.source_outcome.configured_bounds:
            raise ValueError("provenance bounds must match source outcome")
        if self.source_outcome.execution_status is ExecutionStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed outcome requires typed failure provenance")
            if self.failure.failure_id != self.source_outcome.failure_id:
                raise ValueError("failure identity must match source outcome")
        elif self.failure is not None:
            raise ValueError("succeeded outcome forbids failure provenance")
        if self.source_outcome.coverage_status is CoverageStatus.UNAVAILABLE and (
            self.source_record_id is not None
        ):
            raise ValueError("unavailable acquisition cannot fabricate a source record")
        warning_codes = tuple(warning.code for warning in self.warnings)
        if len(set(warning_codes)) != len(warning_codes):
            raise ValueError("provenance warnings must be unique")
        if warning_codes != tuple(sorted(warning_codes)):
            raise ValueError("provenance warnings must be canonically sorted")
        if not set(self.source_outcome.warning_codes).issubset(warning_codes):
            raise ValueError("outcome warning codes must be preserved in provenance")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("artifact_ids must be unique")
        if len(set(self.transformation_lineage)) != len(self.transformation_lineage):
            raise ValueError("transformation_lineage must be unique")
        return self
