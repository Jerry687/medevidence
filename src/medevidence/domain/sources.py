"""Source planning, terminal outcomes, warnings, failures, and provenance."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Final, Literal, Self

from pydantic import ConfigDict, Field, ValidationInfo, model_validator

from .identifiers import (
    AcquisitionId,
    AcquisitionIntentId,
    ArtifactId,
    ArtifactLinkId,
    AttemptId,
    CandidateId,
    CandidateSetId,
    CanonicalSetId,
    CanonicalSplVersion,
    ConnectorVersion,
    DecisionId,
    DurableModel,
    FailureId,
    LabelSelectionWarningId,
    LabelVersionId,
    LongText,
    NonBlankText,
    QueryId,
    RetainedSplResponseId,
    RunId,
    SchemaVersion,
    SectionId,
    Sha256Digest,
    ShortText,
    SnapshotId,
    SourceLookupKey,
    SourceOutcomeId,
    SourceRecordId,
    UtcDateTime,
    WarningCode,
    canonical_json,
    derive_identity,
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


class M1BSourcePlanEntryV1(DurableModel):
    """Additive M1B planning row that leaves the M1A contract byte-stable."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.source-plan.v1"] = "m1b.source-plan.v1"
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


class DailyMedMarketingState(StrEnum):
    """Closed active/archive state retained for one DailyMed candidate or version."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"


class DailyMedMeaningfulDimension(StrEnum):
    """Owner-frozen dimensions that may make DailyMed candidates non-equivalent."""

    NDC = "ndc"
    PRODUCT_NAME = "product_name"
    INGREDIENT_SET = "ingredient_set"
    DOSAGE_FORM = "dosage_form"
    ROUTE = "route"
    STRENGTH = "strength"
    LABELER_NAME = "labeler_name"


class LabelSelectionWarningCode(StrEnum):
    """Closed warning vocabulary for the M1B DailyMed selection contract."""

    NO_CANDIDATE = "no_candidate"
    MULTIPLE_CLINICALLY_DISTINCT_CANDIDATES = "multiple_clinically_distinct_candidates"
    MISSING_REQUIRED_IDENTITY = "missing_required_identity"
    REQUESTED_VERSION_UNAVAILABLE = "requested_version_unavailable"
    ARCHIVED_CANDIDATE_SELECTED = "archived_candidate_selected"
    SELECTION_REQUIRES_REVIEW = "selection_requires_review"
    UNVERIFIED_SECTION_CODE = "unverified_section_code"
    SECTION_ABSENT = "section_absent"
    RESPONSE_TRUNCATED = "response_truncated"
    MALFORMED_SPL = "malformed_spl"


class LabelSelectionStatus(StrEnum):
    """Exhaustive persisted status for an executed DailyMed discovery decision."""

    SELECTED = "selected"
    REVIEW_REQUIRED = "review_required"
    NO_CANDIDATE = "no_candidate"


class DailyMedResolution(StrEnum):
    """Deterministic resolution result used by the exhaustive discovery matrix."""

    RESOLVED_EQUIVALENT = "resolved_equivalent"
    UNRESOLVED_NON_EQUIVALENT = "unresolved_non_equivalent"


def classify_dailymed_selection(
    *,
    outcome: SourceOutcome,
    candidate_count: int,
    resolution: DailyMedResolution | None,
    pinned_identity: bool = False,
) -> LabelSelectionStatus | None:
    """Apply the Owner-frozen exhaustive DailyMed discovery decision matrix.

    ``pinned_identity`` is intentionally non-authorizing: it is accepted only so
    callers can prove that the result is identical to the unpinned matrix.
    """

    del pinned_identity
    outcome = SourceOutcome.model_validate(outcome.model_dump(mode="python"))
    if outcome.source is not SourceType.DAILYMED:
        raise ValueError("DailyMed selection requires a DailyMed SourceOutcome")
    if not 0 <= candidate_count <= 100:
        raise ValueError("candidate_count must be between zero and 100")
    if candidate_count != outcome.valid_result_count:
        raise ValueError("candidate_count must equal the authoritative outcome count")

    triple = (
        outcome.execution_status,
        outcome.coverage_status,
        outcome.result_status,
    )
    complete_matches = (
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.COMPLETE,
        ResultStatus.MATCHES,
    )
    partial_matches = {
        (
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.PARTIAL,
            ResultStatus.MATCHES,
        ),
        (
            ExecutionStatus.FAILED,
            CoverageStatus.PARTIAL,
            ResultStatus.MATCHES,
        ),
    }
    complete_no_match = (
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.COMPLETE,
        ResultStatus.NO_MATCH,
    )
    indeterminate_zero_result = {
        (
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.PARTIAL,
            ResultStatus.INDETERMINATE,
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

    if triple == complete_matches:
        if candidate_count < 1 or resolution is None:
            raise ValueError("complete matches requires candidates and a resolution")
        if resolution is DailyMedResolution.RESOLVED_EQUIVALENT:
            return LabelSelectionStatus.SELECTED
        if candidate_count < 2:
            raise ValueError("one complete candidate cannot be unresolved non-equivalent")
        return LabelSelectionStatus.REVIEW_REQUIRED
    if triple in partial_matches:
        if candidate_count < 1 or resolution is None:
            raise ValueError("partial matches requires candidates and a resolution")
        return LabelSelectionStatus.REVIEW_REQUIRED
    if triple == complete_no_match:
        if candidate_count != 0 or resolution is not None:
            raise ValueError("complete no-match requires zero candidates and no resolution")
        return LabelSelectionStatus.NO_CANDIDATE
    if triple in indeterminate_zero_result:
        if candidate_count != 0 or resolution is not None:
            raise ValueError("indeterminate discovery requires zero candidates and no resolution")
        return None
    raise ValueError("outcome triple is not admitted by the DailyMed decision matrix")


class DailyMedCandidateBinding(DurableModel):
    """Closed nested candidate-to-retained-member binding; never a separate table."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    acquisition_intent_id: AcquisitionIntentId
    query_id: QueryId
    discovery_manifest_id: ArtifactId
    member_ordinal: int = Field(ge=0, le=99)
    link_id: ArtifactLinkId
    raw_artifact_id: ArtifactId
    raw_content_hash: Sha256Digest
    body_complete: Literal[True] = True
    termination_reason: Literal["complete_response"] = "complete_response"
    candidate_ordinal: int = Field(ge=0, le=99)
    candidate_id: CandidateId
    candidate_content_identity: CandidateId


class DailyMedCandidateLabel(DurableModel):
    """One exact, retained DailyMed discovery candidate with complete provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.candidate.v1"] = "m1b.dailymed.candidate.v1"
    candidate_id: CandidateId
    run_id: RunId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    attempt_id: AttemptId
    acquisition_id: AcquisitionId
    acquisition_ordinal: int = Field(ge=0, le=7)
    acquisition_intent_id: AcquisitionIntentId
    setid: CanonicalSetId
    spl_versions: tuple[CanonicalSplVersion, ...] = Field(min_length=1)
    ingredients: tuple[NonBlankText, ...] = Field(min_length=1)
    brand_name: NonBlankText | None = None
    generic_name: NonBlankText | None = None
    application_number: ShortText | None = None
    product_id: ShortText | None = None
    labeler: NonBlankText | None = None
    dosage_forms: tuple[NonBlankText, ...] = ()
    routes: tuple[NonBlankText, ...] = ()
    strengths: tuple[NonBlankText, ...] = ()
    ndcs: tuple[ShortText, ...] = ()
    marketing_state: DailyMedMarketingState
    effective_date: date | None = None
    published_date: date | None = None
    available_section_codes: tuple[Literal["34084-4", "43685-7", "34066-1", "34067-9"], ...]
    discovery_query_id: QueryId
    candidate_set_snapshot_id: SnapshotId
    discovery_manifest_id: ArtifactId
    member_ordinal: int = Field(ge=0, le=99)
    link_id: ArtifactLinkId
    raw_artifact_id: ArtifactId
    raw_content_hash: Sha256Digest
    body_complete: Literal[True] = True
    termination_reason: Literal["complete_response"] = "complete_response"
    candidate_ordinal: int = Field(ge=0, le=99)
    candidate_content_identity: CandidateId

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Canonicalize set-valued fields and derive both candidate identities."""

        data: dict[str, Any] = dict(values)
        for field_name in (
            "ingredients",
            "dosage_forms",
            "routes",
            "strengths",
            "ndcs",
            "available_section_codes",
        ):
            if field_name in data:
                data[field_name] = tuple(
                    sorted(set(data[field_name]), key=lambda value: value.encode("utf-8"))
                )
        if "spl_versions" in data:
            data["spl_versions"] = tuple(
                sorted(set(data["spl_versions"]), key=lambda value: int(value))
            )
        payload = {
            "schema_version": "m1b.dailymed.candidate.v1",
            "source": SourceType.DAILYMED,
            **data,
        }
        candidate_payload = {
            key: payload[key]
            for key in (
                "schema_version",
                "run_id",
                "source",
                "acquisition_id",
                "discovery_query_id",
                "candidate_set_snapshot_id",
                "discovery_manifest_id",
                "setid",
                "spl_versions",
                "ingredients",
                "brand_name",
                "generic_name",
                "application_number",
                "product_id",
                "labeler",
                "dosage_forms",
                "routes",
                "strengths",
                "ndcs",
                "marketing_state",
                "effective_date",
                "published_date",
                "available_section_codes",
            )
        }
        data["candidate_content_identity"] = derive_identity(
            "dailymed-candidate-content", candidate_payload
        )
        data["candidate_id"] = derive_identity("dailymed-candidate", candidate_payload)
        return cls.model_validate(data)

    def as_binding(self) -> DailyMedCandidateBinding:
        """Project the exact nested binding retained by a selection decision."""

        validated = type(self).model_validate(self.model_dump(mode="python"))
        return DailyMedCandidateBinding(
            acquisition_intent_id=validated.acquisition_intent_id,
            query_id=validated.discovery_query_id,
            discovery_manifest_id=validated.discovery_manifest_id,
            member_ordinal=validated.member_ordinal,
            link_id=validated.link_id,
            raw_artifact_id=validated.raw_artifact_id,
            raw_content_hash=validated.raw_content_hash,
            body_complete=validated.body_complete,
            termination_reason=validated.termination_reason,
            candidate_ordinal=validated.candidate_ordinal,
            candidate_id=validated.candidate_id,
            candidate_content_identity=validated.candidate_content_identity,
        )

    @model_validator(mode="after")
    def validate_candidate_identity(self) -> Self:
        ordered_unique_fields = (
            "ingredients",
            "dosage_forms",
            "routes",
            "strengths",
            "ndcs",
            "available_section_codes",
        )
        for field_name in ordered_unique_fields:
            values = getattr(self, field_name)
            if values != tuple(sorted(set(values), key=lambda value: value.encode("utf-8"))):
                raise ValueError(f"{field_name} must be unique and canonically sorted")
        if self.spl_versions != tuple(sorted(set(self.spl_versions), key=int)):
            raise ValueError("spl_versions must be unique and numerically sorted")
        payload = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "source": self.source,
            "acquisition_id": self.acquisition_id,
            "discovery_query_id": self.discovery_query_id,
            "candidate_set_snapshot_id": self.candidate_set_snapshot_id,
            "discovery_manifest_id": self.discovery_manifest_id,
            "setid": self.setid,
            "spl_versions": self.spl_versions,
            "ingredients": self.ingredients,
            "brand_name": self.brand_name,
            "generic_name": self.generic_name,
            "application_number": self.application_number,
            "product_id": self.product_id,
            "labeler": self.labeler,
            "dosage_forms": self.dosage_forms,
            "routes": self.routes,
            "strengths": self.strengths,
            "ndcs": self.ndcs,
            "marketing_state": self.marketing_state,
            "effective_date": self.effective_date,
            "published_date": self.published_date,
            "available_section_codes": self.available_section_codes,
        }
        if self.candidate_id != derive_identity("dailymed-candidate", payload):
            raise ValueError("candidate_id does not match canonical candidate content")
        if self.candidate_content_identity != derive_identity(
            "dailymed-candidate-content", payload
        ):
            raise ValueError("candidate_content_identity does not match candidate content")
        return self


def _candidate_sort_key(candidate: DailyMedCandidateLabel) -> tuple[object, ...]:
    """Return the frozen order independent of caller tuple/member ordinals."""

    return (
        candidate.setid.encode("utf-8"),
        tuple(int(version) for version in candidate.spl_versions),
        candidate.candidate_id.encode("utf-8"),
        canonical_json(
            candidate.model_dump(
                mode="python",
                exclude={"candidate_ordinal", "member_ordinal"},
            )
        ).encode("utf-8"),
    )


def _candidate_dimension_value(
    candidate: DailyMedCandidateLabel,
    dimension: DailyMedMeaningfulDimension,
) -> object:
    return {
        DailyMedMeaningfulDimension.NDC: candidate.ndcs,
        DailyMedMeaningfulDimension.PRODUCT_NAME: (
            candidate.brand_name,
            candidate.generic_name,
            candidate.application_number,
            candidate.product_id,
        ),
        DailyMedMeaningfulDimension.INGREDIENT_SET: candidate.ingredients,
        DailyMedMeaningfulDimension.DOSAGE_FORM: candidate.dosage_forms,
        DailyMedMeaningfulDimension.ROUTE: candidate.routes,
        DailyMedMeaningfulDimension.STRENGTH: candidate.strengths,
        DailyMedMeaningfulDimension.LABELER_NAME: candidate.labeler,
    }[dimension]


def _meaningful_differences(
    candidates: tuple[DailyMedCandidateLabel, ...],
) -> tuple[DailyMedMeaningfulDimension, ...]:
    if len(candidates) < 2:
        return ()
    differences = {
        dimension
        for dimension in DailyMedMeaningfulDimension
        if len({_candidate_dimension_value(candidate, dimension) for candidate in candidates}) > 1
    }
    return tuple(sorted(differences, key=lambda value: value.value.encode("utf-8")))


_LABEL_SELECTION_DECISION_CONTEXT_TOKEN = object()


class LabelSelectionDecision(DurableModel):
    """Exact executed-discovery envelope; no indeterminate zero-result row exists."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.selection-decision.v1"] = (
        "m1b.dailymed.selection-decision.v1"
    )
    decision_id: DecisionId
    run_id: RunId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    attempt_id: AttemptId
    acquisition_id: AcquisitionId
    acquisition_ordinal: int = Field(ge=0, le=7)
    acquisition_intent_id: AcquisitionIntentId
    query_id: QueryId
    candidate_set_snapshot_id: SnapshotId
    status: LabelSelectionStatus
    selection_basis: Literal["executed_discovery"] = "executed_discovery"
    source_execution_started: Literal[True] = True
    policy_version: Literal["M1B_DAILYMED_SELECTION_V1"] = "M1B_DAILYMED_SELECTION_V1"
    candidate_ids: tuple[CandidateId, ...]
    meaningful_dimensions: tuple[DailyMedMeaningfulDimension, ...]
    selected_candidate_id: CandidateId | None = None
    selected_setid: CanonicalSetId | None = None
    selected_spl_version: CanonicalSplVersion | None = None
    warning_ids: tuple[LabelSelectionWarningId, ...] = ()
    warning_codes: tuple[LabelSelectionWarningCode, ...] = ()
    source_outcome_query_id: QueryId
    candidate_set_id: CandidateSetId
    candidate_count: int = Field(ge=0, le=100)
    discovery_manifest_id: ArtifactId
    operation: Literal["search"] = "search"
    source_outcome_id: SourceOutcomeId
    candidate_bindings: tuple[DailyMedCandidateBinding, ...]
    discovery_manifest_artifact_kind: Literal["dailymed_discovery_manifest"] = (
        "dailymed_discovery_manifest"
    )
    discovery_manifest_content_hash: Sha256Digest
    selected_member_ordinal: int | None = Field(default=None, ge=0, le=99)
    selected_link_id: ArtifactLinkId | None = None
    selected_raw_artifact_id: ArtifactId | None = None
    selected_raw_content_hash: Sha256Digest | None = None
    selected_body_complete: Literal[True] | None = None
    selected_termination_reason: Literal["complete_response"] | None = None
    selected_candidate_ordinal: int | None = Field(default=None, ge=0, le=99)
    decided_at_utc: UtcDateTime

    @classmethod
    def from_discovery(
        cls,
        *,
        candidates: tuple[DailyMedCandidateLabel, ...],
        outcome: SourceOutcome,
        resolution: DailyMedResolution | None,
        source_outcome_id: SourceOutcomeId,
        discovery_manifest_content_hash: Sha256Digest,
        decided_at_utc: UtcDateTime,
        meaningful_dimensions: tuple[DailyMedMeaningfulDimension, ...] | None = None,
        warning_ids: tuple[LabelSelectionWarningId, ...] = (),
        pinned_identity: bool = False,
    ) -> Self | None:
        """Build the only decision row admitted by one authoritative discovery."""

        outcome = SourceOutcome.model_validate(outcome.model_dump(mode="python"))
        candidates = tuple(
            DailyMedCandidateLabel.model_validate(candidate.model_dump(mode="python"))
            for candidate in candidates
        )
        if not candidates:
            if outcome.source is not SourceType.DAILYMED:
                raise ValueError("DailyMed decision requires a DailyMed outcome")
            status = classify_dailymed_selection(
                outcome=outcome,
                candidate_count=0,
                resolution=resolution,
                pinned_identity=pinned_identity,
            )
            if status is None:
                return None
            raise ValueError("no-candidate construction requires explicit discovery bindings")

        canonical_candidates = tuple(sorted(candidates, key=_candidate_sort_key))
        first = canonical_candidates[0]
        for expected_ordinal, candidate in enumerate(canonical_candidates):
            if candidate.candidate_ordinal != expected_ordinal:
                raise ValueError("candidate ordinals must be contiguous from zero")
            if (
                candidate.run_id != first.run_id
                or candidate.source is not SourceType.DAILYMED
                or candidate.attempt_id != first.attempt_id
                or candidate.acquisition_id != first.acquisition_id
                or candidate.acquisition_ordinal != first.acquisition_ordinal
                or candidate.acquisition_intent_id != first.acquisition_intent_id
                or candidate.discovery_query_id != first.discovery_query_id
                or candidate.candidate_set_snapshot_id != first.candidate_set_snapshot_id
                or candidate.discovery_manifest_id != first.discovery_manifest_id
            ):
                raise ValueError("all candidates must bind the same exact discovery")

        exact_differences = _meaningful_differences(canonical_candidates)
        if meaningful_dimensions is not None and meaningful_dimensions != exact_differences:
            raise ValueError("meaningful_dimensions must equal exact candidate differences")
        exact_resolution = (
            DailyMedResolution.RESOLVED_EQUIVALENT
            if not exact_differences
            else DailyMedResolution.UNRESOLVED_NON_EQUIVALENT
        )
        if resolution is not exact_resolution:
            raise ValueError("resolution must equal the deterministic candidate comparison")

        status = classify_dailymed_selection(
            outcome=outcome,
            candidate_count=len(canonical_candidates),
            resolution=exact_resolution,
            pinned_identity=pinned_identity,
        )
        if status is None or status is LabelSelectionStatus.NO_CANDIDATE:
            raise ValueError("positive candidates require selected or review_required")
        if outcome.query_id != first.discovery_query_id:
            raise ValueError("outcome query must equal the discovery query")

        bindings = tuple(candidate.as_binding() for candidate in canonical_candidates)
        candidate_ids = tuple(binding.candidate_id for binding in bindings)
        candidate_set_payload = {
            "schema_version": "m1b.dailymed.selection-decision.v1",
            "source": SourceType.DAILYMED,
            "acquisition_intent_id": first.acquisition_intent_id,
            "query_id": first.discovery_query_id,
            "candidate_set_snapshot_id": first.candidate_set_snapshot_id,
            "discovery_manifest_id": first.discovery_manifest_id,
            "candidate_count": len(bindings),
            "candidate_bindings": bindings,
        }
        candidate_set_id = derive_identity("dailymed-candidate-set", candidate_set_payload)
        selected = (
            max(
                canonical_candidates,
                key=lambda item: (
                    item.marketing_state is DailyMedMarketingState.ACTIVE,
                    item.effective_date or date.min,
                    item.published_date or date.min,
                    max(int(version) for version in item.spl_versions),
                    item.candidate_id,
                ),
            )
            if status is LabelSelectionStatus.SELECTED
            else None
        )
        selected_binding = selected.as_binding() if selected is not None else None
        selected_version = max(selected.spl_versions, key=int) if selected is not None else None
        warning_codes: tuple[LabelSelectionWarningCode, ...]
        if status is LabelSelectionStatus.REVIEW_REQUIRED:
            warning_codes = (LabelSelectionWarningCode.SELECTION_REQUIRES_REVIEW,)
        elif selected is not None and selected.marketing_state is DailyMedMarketingState.ARCHIVED:
            warning_codes = (LabelSelectionWarningCode.ARCHIVED_CANDIDATE_SELECTED,)
        else:
            warning_codes = ()
        values: dict[str, object] = {
            "run_id": first.run_id,
            "attempt_id": first.attempt_id,
            "acquisition_id": first.acquisition_id,
            "acquisition_ordinal": first.acquisition_ordinal,
            "acquisition_intent_id": first.acquisition_intent_id,
            "query_id": first.discovery_query_id,
            "candidate_set_snapshot_id": first.candidate_set_snapshot_id,
            "status": status,
            "candidate_ids": candidate_ids,
            "meaningful_dimensions": exact_differences,
            "selected_candidate_id": selected.candidate_id if selected else None,
            "selected_setid": selected.setid if selected else None,
            "selected_spl_version": selected_version,
            "warning_ids": tuple(sorted(set(warning_ids))),
            "warning_codes": warning_codes,
            "source_outcome_query_id": outcome.query_id,
            "candidate_set_id": candidate_set_id,
            "candidate_count": len(bindings),
            "discovery_manifest_id": first.discovery_manifest_id,
            "source_outcome_id": source_outcome_id,
            "candidate_bindings": bindings,
            "discovery_manifest_content_hash": discovery_manifest_content_hash,
            "selected_member_ordinal": (
                selected_binding.member_ordinal if selected_binding else None
            ),
            "selected_link_id": selected_binding.link_id if selected_binding else None,
            "selected_raw_artifact_id": (
                selected_binding.raw_artifact_id if selected_binding else None
            ),
            "selected_raw_content_hash": (
                selected_binding.raw_content_hash if selected_binding else None
            ),
            "selected_body_complete": selected_binding.body_complete if selected_binding else None,
            "selected_termination_reason": (
                selected_binding.termination_reason if selected_binding else None
            ),
            "selected_candidate_ordinal": (
                selected_binding.candidate_ordinal if selected_binding else None
            ),
            "decided_at_utc": decided_at_utc,
        }
        identity_payload = {
            "schema_version": "m1b.dailymed.selection-decision.v1",
            "source": SourceType.DAILYMED,
            "selection_basis": "executed_discovery",
            "source_execution_started": True,
            "policy_version": "M1B_DAILYMED_SELECTION_V1",
            "operation": "search",
            "discovery_manifest_artifact_kind": "dailymed_discovery_manifest",
            **{key: value for key, value in values.items() if key != "decided_at_utc"},
        }
        values["decision_id"] = derive_identity("dailymed-selection-decision", identity_payload)
        return cls.model_validate(
            values,
            context={
                "_validation_token": _LABEL_SELECTION_DECISION_CONTEXT_TOKEN,
                "outcome": outcome,
                "candidates": canonical_candidates,
                "source_outcome_id": source_outcome_id,
                "discovery_manifest_content_hash": discovery_manifest_content_hash,
            },
        )

    @classmethod
    def selected_from_discovery(cls, **values: Any) -> Self:
        """Create and assert the complete-only selected decision shape."""

        decision = cls.from_discovery(**values)
        if decision is None or decision.status is not LabelSelectionStatus.SELECTED:
            raise ValueError("discovery does not produce a selected decision")
        return decision

    @classmethod
    def review_required_from_discovery(cls, **values: Any) -> Self:
        """Create and assert the exact complete/partial review decision shape."""

        decision = cls.from_discovery(**values)
        if decision is None or decision.status is not LabelSelectionStatus.REVIEW_REQUIRED:
            raise ValueError("discovery does not produce a review_required decision")
        return decision

    @classmethod
    def no_candidate_from_discovery(
        cls,
        *,
        run_id: RunId,
        attempt_id: AttemptId,
        acquisition_id: AcquisitionId,
        acquisition_ordinal: int,
        acquisition_intent_id: AcquisitionIntentId,
        candidate_set_snapshot_id: SnapshotId,
        discovery_manifest_id: ArtifactId,
        discovery_manifest_content_hash: Sha256Digest,
        source_outcome_id: SourceOutcomeId,
        outcome: SourceOutcome,
        decided_at_utc: UtcDateTime,
    ) -> Self:
        """Build the sole authoritative zero-candidate decision shape."""

        outcome = SourceOutcome.model_validate(outcome.model_dump(mode="python"))
        status = classify_dailymed_selection(
            outcome=outcome,
            candidate_count=0,
            resolution=None,
        )
        if status is not LabelSelectionStatus.NO_CANDIDATE:
            raise ValueError("only succeeded/complete/no_match creates no_candidate")
        candidate_set_payload = {
            "schema_version": "m1b.dailymed.selection-decision.v1",
            "source": SourceType.DAILYMED,
            "acquisition_intent_id": acquisition_intent_id,
            "query_id": outcome.query_id,
            "candidate_set_snapshot_id": candidate_set_snapshot_id,
            "discovery_manifest_id": discovery_manifest_id,
            "candidate_count": 0,
            "candidate_bindings": (),
        }
        values: dict[str, object] = {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "acquisition_id": acquisition_id,
            "acquisition_ordinal": acquisition_ordinal,
            "acquisition_intent_id": acquisition_intent_id,
            "query_id": outcome.query_id,
            "candidate_set_snapshot_id": candidate_set_snapshot_id,
            "status": status,
            "candidate_ids": (),
            "meaningful_dimensions": (),
            "selected_candidate_id": None,
            "selected_setid": None,
            "selected_spl_version": None,
            "warning_ids": (),
            "warning_codes": (LabelSelectionWarningCode.NO_CANDIDATE,),
            "source_outcome_query_id": outcome.query_id,
            "candidate_set_id": derive_identity("dailymed-candidate-set", candidate_set_payload),
            "candidate_count": 0,
            "discovery_manifest_id": discovery_manifest_id,
            "source_outcome_id": source_outcome_id,
            "candidate_bindings": (),
            "discovery_manifest_content_hash": discovery_manifest_content_hash,
            "selected_member_ordinal": None,
            "selected_link_id": None,
            "selected_raw_artifact_id": None,
            "selected_raw_content_hash": None,
            "selected_body_complete": None,
            "selected_termination_reason": None,
            "selected_candidate_ordinal": None,
            "decided_at_utc": decided_at_utc,
        }
        identity_payload = {
            "schema_version": "m1b.dailymed.selection-decision.v1",
            "source": SourceType.DAILYMED,
            "selection_basis": "executed_discovery",
            "source_execution_started": True,
            "policy_version": "M1B_DAILYMED_SELECTION_V1",
            "operation": "search",
            "discovery_manifest_artifact_kind": "dailymed_discovery_manifest",
            **{key: value for key, value in values.items() if key != "decided_at_utc"},
        }
        values["decision_id"] = derive_identity("dailymed-selection-decision", identity_payload)
        return cls.model_validate(
            values,
            context={
                "_validation_token": _LABEL_SELECTION_DECISION_CONTEXT_TOKEN,
                "outcome": outcome,
                "candidates": (),
                "source_outcome_id": source_outcome_id,
                "discovery_manifest_content_hash": discovery_manifest_content_hash,
            },
        )

    @model_validator(mode="after")
    def validate_decision_shape(self, info: ValidationInfo) -> Self:
        if self.source_outcome_query_id != self.query_id:
            raise ValueError("source_outcome_query_id must equal discovery query_id")
        if self.candidate_count != len(self.candidate_ids) or self.candidate_count != len(
            self.candidate_bindings
        ):
            raise ValueError("candidate_count must equal both complete candidate arrays")
        if self.candidate_ids != tuple(binding.candidate_id for binding in self.candidate_bindings):
            raise ValueError("candidate_ids must equal the ordered binding projection")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate identities must be unique")
        for values, name in (
            (self.meaningful_dimensions, "meaningful_dimensions"),
            (self.warning_ids, "warning_ids"),
            (self.warning_codes, "warning_codes"),
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{name} must be unique and canonically sorted")

        selected_scalars = (
            self.selected_candidate_id,
            self.selected_setid,
            self.selected_spl_version,
            self.selected_member_ordinal,
            self.selected_link_id,
            self.selected_raw_artifact_id,
            self.selected_raw_content_hash,
            self.selected_body_complete,
            self.selected_termination_reason,
            self.selected_candidate_ordinal,
        )
        if self.status is LabelSelectionStatus.SELECTED:
            if self.candidate_count < 1 or any(value is None for value in selected_scalars):
                raise ValueError("selected requires a complete candidate/member identity")
            binding = next(
                (
                    item
                    for item in self.candidate_bindings
                    if item.candidate_id == self.selected_candidate_id
                ),
                None,
            )
            if binding is None or (
                binding.member_ordinal != self.selected_member_ordinal
                or binding.link_id != self.selected_link_id
                or binding.raw_artifact_id != self.selected_raw_artifact_id
                or binding.raw_content_hash != self.selected_raw_content_hash
                or binding.candidate_ordinal != self.selected_candidate_ordinal
            ):
                raise ValueError("selected member must be an exact candidate binding member")
        elif any(value is not None for value in selected_scalars):
            raise ValueError("non-selected decisions forbid every selected field")

        if self.status is LabelSelectionStatus.REVIEW_REQUIRED and (
            self.candidate_count < 1
            or LabelSelectionWarningCode.SELECTION_REQUIRES_REVIEW not in self.warning_codes
        ):
            raise ValueError("review_required needs candidates and its exact warning")
        if self.status is LabelSelectionStatus.NO_CANDIDATE and (
            self.candidate_count != 0
            or self.candidate_ids
            or self.candidate_bindings
            or self.meaningful_dimensions
            or self.warning_codes != (LabelSelectionWarningCode.NO_CANDIDATE,)
        ):
            raise ValueError("no_candidate has an exact zero-candidate shape")

        payload = self.model_dump(mode="python", exclude={"decision_id", "decided_at_utc"})
        if self.decision_id != derive_identity("dailymed-selection-decision", payload):
            raise ValueError("decision_id does not match non-observational decision content")

        context = info.context
        if (
            not isinstance(context, dict)
            or context.get("_validation_token") is not _LABEL_SELECTION_DECISION_CONTEXT_TOKEN
        ):
            raise ValueError("selection decisions require authoritative discovery context")
        outcome = context.get("outcome")
        candidates = context.get("candidates")
        source_outcome_id = context.get("source_outcome_id")
        discovery_manifest_content_hash = context.get("discovery_manifest_content_hash")
        if not isinstance(outcome, SourceOutcome) or not isinstance(candidates, tuple):
            raise ValueError("selection decision context is incomplete")
        outcome = SourceOutcome.model_validate(outcome.model_dump(mode="python"))
        if (
            source_outcome_id != self.source_outcome_id
            or discovery_manifest_content_hash != self.discovery_manifest_content_hash
        ):
            raise ValueError("selection decision trusted outcome or manifest identity drift")
        if (
            outcome.source is not SourceType.DAILYMED
            or outcome.query_id != self.query_id
            or outcome.valid_result_count != self.candidate_count
        ):
            raise ValueError("selection decision outcome binding is inconsistent")
        if candidates:
            if not all(isinstance(item, DailyMedCandidateLabel) for item in candidates):
                raise ValueError("selection decision candidate context is invalid")
            typed_candidates = tuple(
                DailyMedCandidateLabel.model_validate(item.model_dump(mode="python"))
                for item in candidates
            )
            if typed_candidates != tuple(sorted(typed_candidates, key=_candidate_sort_key)):
                raise ValueError("selection decision candidates must use canonical order")
            if tuple(item.as_binding() for item in typed_candidates) != self.candidate_bindings:
                raise ValueError("selection decision bindings must equal exact candidates")
            if any(
                item.run_id != self.run_id
                or item.source is not self.source
                or item.attempt_id != self.attempt_id
                or item.acquisition_id != self.acquisition_id
                or item.acquisition_ordinal != self.acquisition_ordinal
                or item.acquisition_intent_id != self.acquisition_intent_id
                or item.discovery_query_id != self.query_id
                or item.candidate_set_snapshot_id != self.candidate_set_snapshot_id
                or item.discovery_manifest_id != self.discovery_manifest_id
                for item in typed_candidates
            ):
                raise ValueError("selection decision candidate discovery identity drift")
            exact_differences = _meaningful_differences(typed_candidates)
            if self.meaningful_dimensions != exact_differences:
                raise ValueError("selection decision dimensions drift from candidates")
            exact_resolution = (
                DailyMedResolution.RESOLVED_EQUIVALENT
                if not exact_differences
                else DailyMedResolution.UNRESOLVED_NON_EQUIVALENT
            )
            if self.status is LabelSelectionStatus.SELECTED:
                resolved_candidate = max(
                    typed_candidates,
                    key=lambda item: (
                        item.marketing_state is DailyMedMarketingState.ACTIVE,
                        item.effective_date or date.min,
                        item.published_date or date.min,
                        max(int(version) for version in item.spl_versions),
                        item.candidate_id,
                    ),
                )
                resolved_version = max(resolved_candidate.spl_versions, key=int)
                if (
                    self.selected_candidate_id != resolved_candidate.candidate_id
                    or self.selected_setid != resolved_candidate.setid
                    or self.selected_spl_version != resolved_version
                ):
                    raise ValueError(
                        "selected identity must equal the authoritative resolved candidate"
                    )
        else:
            exact_resolution = None
        candidate_set_payload = {
            "schema_version": self.schema_version,
            "source": self.source,
            "acquisition_intent_id": self.acquisition_intent_id,
            "query_id": self.query_id,
            "candidate_set_snapshot_id": self.candidate_set_snapshot_id,
            "discovery_manifest_id": self.discovery_manifest_id,
            "candidate_count": self.candidate_count,
            "candidate_bindings": self.candidate_bindings,
        }
        if self.candidate_set_id != derive_identity(
            "dailymed-candidate-set", candidate_set_payload
        ):
            raise ValueError("candidate_set_id does not match exact authoritative candidates")
        expected_status = classify_dailymed_selection(
            outcome=outcome,
            candidate_count=self.candidate_count,
            resolution=exact_resolution,
        )
        if expected_status is None or self.status is not expected_status:
            raise ValueError("selection decision status contradicts authoritative discovery")
        if (
            self.status is LabelSelectionStatus.REVIEW_REQUIRED
            and outcome.coverage_status is CoverageStatus.COMPLETE
            and (self.candidate_count < 2 or not self.meaningful_dimensions)
        ):
            raise ValueError("complete review requires non-equivalent candidates")
        return self

    def validate_against(
        self,
        *,
        outcome: SourceOutcome,
        candidates: tuple[DailyMedCandidateLabel, ...],
        source_outcome_id: SourceOutcomeId,
        discovery_manifest_content_hash: Sha256Digest,
    ) -> None:
        """Revalidate a decision against its non-serialized authoritative context."""

        outcome = SourceOutcome.model_validate(outcome.model_dump(mode="python"))
        candidates = tuple(
            DailyMedCandidateLabel.model_validate(candidate.model_dump(mode="python"))
            for candidate in candidates
        )
        validated = type(self).model_validate(
            self.model_dump(mode="python"),
            context={
                "_validation_token": _LABEL_SELECTION_DECISION_CONTEXT_TOKEN,
                "outcome": outcome,
                "candidates": candidates,
                "source_outcome_id": source_outcome_id,
                "discovery_manifest_content_hash": discovery_manifest_content_hash,
            },
        )
        if validated != self:
            raise ValueError("selection decision differs from authoritative validation")


class DailyMedLabelVersion(DurableModel):
    """Fetch-independent stable DailyMed SPL-version identity."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.label-version.v1"] = "m1b.dailymed.label-version.v1"
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    setid: CanonicalSetId
    label_version_id: LabelVersionId
    spl_version: CanonicalSplVersion
    marketing_state: DailyMedMarketingState
    effective_date: date | None = None
    published_date: date | None = None
    content_hash: Sha256Digest
    spl_artifact_id: ArtifactId

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Derive stable identity without any fetch/acquisition tuple."""

        data = dict(values)
        payload = {
            "schema_version": "m1b.dailymed.label-version.v1",
            "source": SourceType.DAILYMED,
            "setid": data["setid"],
            "spl_version": data["spl_version"],
            "content_hash": data["content_hash"],
        }
        data["label_version_id"] = derive_identity("dailymed-label-version", payload)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_stable_identity(self) -> Self:
        expected = derive_identity(
            "dailymed-label-version",
            {
                "schema_version": self.schema_version,
                "source": self.source,
                "setid": self.setid,
                "spl_version": self.spl_version,
                "content_hash": self.content_hash,
            },
        )
        if self.label_version_id != expected:
            raise ValueError("label_version_id does not match stable label content")
        return self


class RetainedSplResponse(DurableModel):
    """Closed complete fetch observation bound to one stable SPL version."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.retained-spl-response.v1"] = (
        "m1b.dailymed.retained-spl-response.v1"
    )
    response_id: RetainedSplResponseId
    run_id: RunId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    acquisition_id: AcquisitionId
    candidate_set_snapshot_id: SnapshotId
    selection_decision_id: DecisionId
    source_outcome_query_id: QueryId
    setid: CanonicalSetId
    spl_version: CanonicalSplVersion
    media_type: ShortText
    byte_size: int = Field(gt=0, le=5_242_880)
    content_hash: Sha256Digest
    artifact_id: ArtifactId
    manifest_id: ArtifactId
    retrieved_at: UtcDateTime
    body_complete: Literal[True] = True
    termination_reason: Literal["complete_response"] = "complete_response"
    section_ids: tuple[SectionId, ...] = Field(max_length=128)
    fetch_attempt_id: AttemptId
    fetch_acquisition_id: AcquisitionId
    fetch_acquisition_ordinal: int = Field(ge=0, le=7)
    fetch_acquisition_intent_id: AcquisitionIntentId
    fetch_query_id: QueryId
    fetch_snapshot_id: SnapshotId
    fetch_manifest_id: ArtifactId
    fetch_source_outcome_id: SourceOutcomeId
    fetch_member_ordinal: int = Field(ge=0, le=127)
    fetch_link_id: ArtifactLinkId
    fetch_raw_artifact_id: ArtifactId
    fetch_raw_content_hash: Sha256Digest
    selected_candidate_id: CandidateId
    label_version_id: LabelVersionId

    @classmethod
    def create(cls, **values: Any) -> Self:
        data = dict(values)
        data["section_ids"] = tuple(
            sorted(set(data.get("section_ids", ())), key=lambda value: value.encode("utf-8"))
        )
        data.setdefault("body_complete", True)
        data.setdefault("termination_reason", "complete_response")
        payload = {
            "schema_version": "m1b.dailymed.retained-spl-response.v1",
            "source": SourceType.DAILYMED,
            **data,
        }
        payload.pop("retrieved_at")
        data["response_id"] = derive_identity("dailymed-retained-spl-response", payload)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_response_identity(self) -> Self:
        if (
            self.acquisition_id != self.fetch_acquisition_id
            or self.source_outcome_query_id != self.fetch_query_id
            or self.manifest_id != self.fetch_manifest_id
            or self.artifact_id != self.fetch_raw_artifact_id
            or self.content_hash != self.fetch_raw_content_hash
        ):
            raise ValueError("retained response common fields must equal exact fetch fields")
        if self.section_ids != tuple(
            sorted(set(self.section_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("retained response section_ids must be canonical and unique")
        payload = self.model_dump(
            mode="python",
            exclude={"response_id", "retrieved_at"},
        )
        if self.response_id != derive_identity("dailymed-retained-spl-response", payload):
            raise ValueError("response_id does not match exact retained fetch content")
        return self

    def validate_against(
        self,
        *,
        decision: LabelSelectionDecision,
        discovery_outcome: SourceOutcome,
        decision_candidates: tuple[DailyMedCandidateLabel, ...],
        decision_source_outcome_id: SourceOutcomeId,
        discovery_manifest_content_hash: Sha256Digest,
        fetch_outcome: SourceOutcome,
        trusted_fetch_run_id: RunId,
        trusted_fetch_source: SourceType,
        trusted_fetch_acquisition_id: AcquisitionId,
        trusted_fetch_acquisition_intent_id: AcquisitionIntentId,
        trusted_fetch_acquisition_ordinal: int,
        trusted_fetch_operation: Literal["search", "fetch"],
        trusted_fetch_query_id: QueryId,
        trusted_fetch_snapshot_id: SnapshotId,
        trusted_fetch_source_outcome_id: SourceOutcomeId,
        trusted_fetch_attempt_id: AttemptId,
        trusted_fetch_manifest_id: ArtifactId,
        trusted_fetch_member_ordinal: int,
        trusted_fetch_link_id: ArtifactLinkId,
        trusted_fetch_raw_artifact_id: ArtifactId,
        trusted_fetch_raw_content_hash: Sha256Digest,
        label_version: DailyMedLabelVersion,
        sections: tuple[LabelSection, ...],
    ) -> None:
        decision.validate_against(
            outcome=discovery_outcome,
            candidates=decision_candidates,
            source_outcome_id=decision_source_outcome_id,
            discovery_manifest_content_hash=discovery_manifest_content_hash,
        )
        validated_decision = decision
        validated_outcome = SourceOutcome.model_validate(fetch_outcome.model_dump(mode="python"))
        if type(self).model_validate(self.model_dump(mode="python")) != self:
            raise ValueError("retained response differs from closed validation")
        if (
            DailyMedLabelVersion.model_validate(label_version.model_dump(mode="python"))
            != label_version
        ):
            raise ValueError("label version differs from closed validation")
        if (
            tuple(
                LabelSection.model_validate(section.model_dump(mode="python"))
                for section in sections
            )
            != sections
        ):
            raise ValueError("label sections differ from closed validation")
        if (
            trusted_fetch_operation != "fetch"
            or self.run_id != trusted_fetch_run_id
            or self.source is not trusted_fetch_source
            or self.fetch_acquisition_id != trusted_fetch_acquisition_id
            or self.fetch_acquisition_intent_id != trusted_fetch_acquisition_intent_id
            or self.fetch_acquisition_ordinal != trusted_fetch_acquisition_ordinal
            or self.fetch_query_id != trusted_fetch_query_id
            or self.fetch_snapshot_id != trusted_fetch_snapshot_id
            or self.fetch_source_outcome_id != trusted_fetch_source_outcome_id
            or self.fetch_attempt_id != trusted_fetch_attempt_id
            or self.fetch_manifest_id != trusted_fetch_manifest_id
            or self.fetch_member_ordinal != trusted_fetch_member_ordinal
            or self.fetch_link_id != trusted_fetch_link_id
            or self.fetch_raw_artifact_id != trusted_fetch_raw_artifact_id
            or self.fetch_raw_content_hash != trusted_fetch_raw_content_hash
        ):
            raise ValueError("retained response does not equal trusted fetch acquisition")
        if (
            trusted_fetch_acquisition_id == validated_decision.acquisition_id
            or trusted_fetch_snapshot_id == validated_decision.candidate_set_snapshot_id
            or trusted_fetch_acquisition_ordinal <= validated_decision.acquisition_ordinal
        ):
            raise ValueError(
                "trusted fetch acquisition must be distinct from and follow selection discovery"
            )
        if (
            validated_decision.status is not LabelSelectionStatus.SELECTED
            or validated_decision.decision_id != self.selection_decision_id
            or validated_decision.run_id != self.run_id
            or validated_decision.candidate_set_snapshot_id != self.candidate_set_snapshot_id
            or validated_decision.selected_candidate_id != self.selected_candidate_id
            or validated_decision.selected_setid != self.setid
            or validated_decision.selected_spl_version != self.spl_version
        ):
            raise ValueError("retained response does not equal the selected discovery")
        if (
            validated_outcome.source is not SourceType.DAILYMED
            or validated_outcome.query_id != self.fetch_query_id
            or validated_outcome.execution_status is not ExecutionStatus.SUCCEEDED
            or validated_outcome.coverage_status is not CoverageStatus.COMPLETE
            or validated_outcome.result_status is not ResultStatus.MATCHES
        ):
            raise ValueError("retained response requires successful complete fetch outcome")
        if (
            label_version.setid != self.setid
            or label_version.spl_version != self.spl_version
            or label_version.label_version_id != self.label_version_id
            or label_version.content_hash != self.content_hash
            or label_version.spl_artifact_id != self.artifact_id
        ):
            raise ValueError("retained response stable label identity drift")
        if tuple(section.section_id for section in sections) != self.section_ids:
            raise ValueError("retained response section_ids must equal exact stable sections")
        if any(
            section.label_version_id != self.label_version_id
            or section.setid != self.setid
            or section.spl_version != self.spl_version
            or section.spl_artifact_id != self.artifact_id
            for section in sections
        ):
            raise ValueError("retained response section identity drift")


class LabelSelectionWarning(DurableModel):
    """Closed decision-bound DailyMed warning row."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.selection-warning.v1"] = (
        "m1b.dailymed.selection-warning.v1"
    )
    warning_id: LabelSelectionWarningId
    decision_id: DecisionId
    code: LabelSelectionWarningCode
    message: LongText
    candidate_ids: tuple[CandidateId, ...]
    differing_dimensions: tuple[DailyMedMeaningfulDimension, ...]

    @classmethod
    def create(cls, **values: Any) -> Self:
        data = dict(values)
        data["candidate_ids"] = tuple(
            sorted(set(data.get("candidate_ids", ())), key=lambda value: value.encode("utf-8"))
        )
        data["differing_dimensions"] = tuple(
            sorted(
                set(data.get("differing_dimensions", ())),
                key=lambda value: value.value.encode("utf-8"),
            )
        )
        payload = {
            "schema_version": "m1b.dailymed.selection-warning.v1",
            **{key: value for key, value in data.items() if key != "decision_id"},
        }
        data["warning_id"] = derive_identity("dailymed-selection-warning", payload)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_warning_identity(self) -> Self:
        if self.candidate_ids != tuple(
            sorted(set(self.candidate_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("warning candidate_ids must be canonical and unique")
        if self.differing_dimensions != tuple(
            sorted(
                set(self.differing_dimensions),
                key=lambda value: value.value.encode("utf-8"),
            )
        ):
            raise ValueError("warning dimensions must be canonical and unique")
        payload = self.model_dump(mode="python", exclude={"warning_id", "decision_id"})
        if self.warning_id != derive_identity("dailymed-selection-warning", payload):
            raise ValueError("warning_id does not match exact warning content")
        return self

    def validate_against(
        self,
        decision: LabelSelectionDecision,
        *,
        discovery_outcome: SourceOutcome,
        decision_candidates: tuple[DailyMedCandidateLabel, ...],
        decision_source_outcome_id: SourceOutcomeId,
        discovery_manifest_content_hash: Sha256Digest,
    ) -> None:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        decision.validate_against(
            outcome=discovery_outcome,
            candidates=decision_candidates,
            source_outcome_id=decision_source_outcome_id,
            discovery_manifest_content_hash=discovery_manifest_content_hash,
        )
        validated_decision = decision
        if (
            validated.decision_id != validated_decision.decision_id
            or validated.warning_id not in validated_decision.warning_ids
        ):
            raise ValueError("selection warning must bind its exact decision")
        if validated.code not in validated_decision.warning_codes:
            raise ValueError("selection warning code must be present on its decision")
        if (
            validated.candidate_ids
            != tuple(
                sorted(validated_decision.candidate_ids, key=lambda value: value.encode("utf-8"))
            )
            or validated.differing_dimensions != validated_decision.meaningful_dimensions
        ):
            raise ValueError("selection warning candidate/dimension binding drift")


_DAILYMED_LOINC_SECTION_ROW_SPECS: Final = (
    (
        "34084-4",
        "FDA package insert Adverse reactions section",
        "Active",
        "https://loinc.org/34084-4",
    ),
    (
        "43685-7",
        "FDA package insert Warnings and precautions section",
        "Active",
        "https://loinc.org/43685-7",
    ),
    (
        "34066-1",
        "FDA package insert Boxed warning section",
        "Active",
        "https://loinc.org/34066-1",
    ),
    (
        "34067-9",
        "FDA package insert Indications and usage section",
        "Active",
        "https://loinc.org/34067-9",
    ),
)


class LoincSectionDefinition(DurableModel):
    """One exact Owner-supplied LOINC 2.82 section-code oracle row."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    code: Literal["34084-4", "43685-7", "34066-1", "34067-9"]
    title: NonBlankText
    status: Literal["Active"] = "Active"
    evidence_url: NonBlankText

    @model_validator(mode="after")
    def validate_exact_row(self) -> Self:
        if (self.code, self.title, self.status, self.evidence_url) not in (
            _DAILYMED_LOINC_SECTION_ROW_SPECS
        ):
            raise ValueError("LOINC section definition must equal one exact frozen row")
        return self


_DAILYMED_LOINC_SECTION_ENTRIES: Final = (
    LoincSectionDefinition(
        code="34084-4",
        title="FDA package insert Adverse reactions section",
        evidence_url="https://loinc.org/34084-4",
    ),
    LoincSectionDefinition(
        code="43685-7",
        title="FDA package insert Warnings and precautions section",
        evidence_url="https://loinc.org/43685-7",
    ),
    LoincSectionDefinition(
        code="34066-1",
        title="FDA package insert Boxed warning section",
        evidence_url="https://loinc.org/34066-1",
    ),
    LoincSectionDefinition(
        code="34067-9",
        title="FDA package insert Indications and usage section",
        evidence_url="https://loinc.org/34067-9",
    ),
)


class DailyMedLoincSectionOracle(DurableModel):
    """Exact Owner-frozen LOINC 2.82 four-entry mapping oracle."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.loinc-section-allowlist.v1"] = (
        "m1b.dailymed.loinc-section-allowlist.v1"
    )
    authority: Literal["LOINC"] = "LOINC"
    steward: Literal["Regenstrief Institute, Inc."] = "Regenstrief Institute, Inc."
    code_system: Literal["http://loinc.org"] = "http://loinc.org"
    release: Literal["2.82"] = "2.82"
    mapping_mode: Literal["exact_code_title_pair_not_fuzzy_alias"] = (
        "exact_code_title_pair_not_fuzzy_alias"
    )
    entries: tuple[LoincSectionDefinition, ...] = Field(min_length=4, max_length=4)
    expansion_requires_new_owner_decision: Literal[True] = True

    @model_validator(mode="after")
    def validate_exact_entries(self) -> Self:
        if self.entries != _DAILYMED_LOINC_SECTION_ENTRIES:
            raise ValueError("LOINC entries must equal the frozen ordered four")
        return self


DAILYMED_LOINC_SECTION_ORACLE: Final = DailyMedLoincSectionOracle(
    entries=_DAILYMED_LOINC_SECTION_ENTRIES
)
DAILYMED_LOINC_SECTION_ALLOWLIST: Final = DAILYMED_LOINC_SECTION_ORACLE.entries
_LOINC_TITLE_BY_CODE: Final = {item.code: item.title for item in DAILYMED_LOINC_SECTION_ALLOWLIST}


class LabelSection(DurableModel):
    """Stable exact section span within one immutable DailyMed label version."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.label-section.v1"] = "m1b.dailymed.label-section.v1"
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    setid: CanonicalSetId
    label_version_id: LabelVersionId
    spl_version: CanonicalSplVersion
    section_ordinal: int = Field(ge=0, le=127)
    section_id: SectionId
    section_code: Literal["34084-4", "43685-7", "34066-1", "34067-9"]
    title: NonBlankText
    parent_section_id: SectionId | None = None
    xml_path: NonBlankText
    text_start: int = Field(ge=0)
    text_end: int = Field(gt=0)
    text_hash: Sha256Digest
    spl_artifact_id: ArtifactId

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Derive a stable section identity from exact version/path/span content."""

        data = dict(values)
        payload = {
            "schema_version": "m1b.dailymed.label-section.v1",
            "source": SourceType.DAILYMED,
            **data,
        }
        data["section_id"] = derive_identity("dailymed-label-section", payload)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_section_identity(self) -> Self:
        if self.text_end <= self.text_start:
            raise ValueError("label section span must be non-empty and half-open")
        if self.title != _LOINC_TITLE_BY_CODE[self.section_code]:
            raise ValueError("section code/title must equal the frozen LOINC 2.82 pair")
        expected = derive_identity(
            "dailymed-label-section",
            self.model_dump(mode="python", exclude={"section_id"}),
        )
        if self.section_id != expected:
            raise ValueError("section_id does not match stable section content")
        return self


_DAILYMED_TRUST_PATH_ROW_SPECS: Final = (
    (
        "/dailymed/services/v2/spls.json",
        "bounded_candidate_discovery",
        "closed_allowed_keys",
        (
            "application_number",
            "drug_name",
            "name_type",
            "labeler",
            "ndc",
            "setid",
            "rxcui",
            "unii_code",
            "published_date",
            "published_date_comparison",
            "pagesize",
            "page",
        ),
        (),
    ),
    (
        "/dailymed/services/v2/spls/{SETID}/history.json",
        "exact_setid_version_history",
        "closed_allowed_keys",
        ("pagesize", "page"),
        (),
    ),
    (
        "/dailymed/services/v2/spls/{SETID}/ndcs.json",
        "exact_candidate_product_identity",
        "closed_allowed_keys",
        ("pagesize", "page"),
        (),
    ),
    (
        "/dailymed/services/v2/spls/{SETID}/packaging.json",
        "exact_candidate_product_packaging_identity",
        "closed_allowed_keys",
        ("pagesize", "page"),
        (),
    ),
    (
        "/dailymed/services/v2/spls/{SETID}.xml",
        "current_exact_spl",
        "none",
        (),
        (),
    ),
    (
        "/dailymed/getFile.cfm",
        "selected_historical_spl",
        "exact_tuple",
        (),
        (("type", "zip"), ("setid", "{SETID}"), ("version", "{SPL_VERSION}")),
    ),
)


class DailyMedTrustPath(DurableModel):
    """One closed non-authorizing DailyMed connector path/query design row."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    path_template: NonBlankText
    purpose: ShortText
    query_mode: Literal["closed_allowed_keys", "none", "exact_tuple"]
    allowed_query_keys: tuple[ShortText, ...] = ()
    exact_query: tuple[tuple[ShortText, ShortText], ...] = ()

    @model_validator(mode="after")
    def validate_query_shape(self) -> Self:
        if self.query_mode == "closed_allowed_keys" and (
            not self.allowed_query_keys or self.exact_query
        ):
            raise ValueError("closed query path requires only its exact allowed keys")
        if self.query_mode == "none" and (self.allowed_query_keys or self.exact_query):
            raise ValueError("no-query path forbids query metadata")
        if self.query_mode == "exact_tuple" and (self.allowed_query_keys or not self.exact_query):
            raise ValueError("exact-query path requires only its exact tuple")
        row = (
            self.path_template,
            self.purpose,
            self.query_mode,
            self.allowed_query_keys,
            self.exact_query,
        )
        if row not in _DAILYMED_TRUST_PATH_ROW_SPECS:
            raise ValueError("DailyMed trust path must equal one exact frozen row")
        return self


DAILYMED_TRUST_PATHS: Final = (
    DailyMedTrustPath(
        path_template="/dailymed/services/v2/spls.json",
        purpose="bounded_candidate_discovery",
        query_mode="closed_allowed_keys",
        allowed_query_keys=(
            "application_number",
            "drug_name",
            "name_type",
            "labeler",
            "ndc",
            "setid",
            "rxcui",
            "unii_code",
            "published_date",
            "published_date_comparison",
            "pagesize",
            "page",
        ),
    ),
    DailyMedTrustPath(
        path_template="/dailymed/services/v2/spls/{SETID}/history.json",
        purpose="exact_setid_version_history",
        query_mode="closed_allowed_keys",
        allowed_query_keys=("pagesize", "page"),
    ),
    DailyMedTrustPath(
        path_template="/dailymed/services/v2/spls/{SETID}/ndcs.json",
        purpose="exact_candidate_product_identity",
        query_mode="closed_allowed_keys",
        allowed_query_keys=("pagesize", "page"),
    ),
    DailyMedTrustPath(
        path_template="/dailymed/services/v2/spls/{SETID}/packaging.json",
        purpose="exact_candidate_product_packaging_identity",
        query_mode="closed_allowed_keys",
        allowed_query_keys=("pagesize", "page"),
    ),
    DailyMedTrustPath(
        path_template="/dailymed/services/v2/spls/{SETID}.xml",
        purpose="current_exact_spl",
        query_mode="none",
    ),
    DailyMedTrustPath(
        path_template="/dailymed/getFile.cfm",
        purpose="selected_historical_spl",
        query_mode="exact_tuple",
        exact_query=(
            ("type", "zip"),
            ("setid", "{SETID}"),
            ("version", "{SPL_VERSION}"),
        ),
    ),
)


class DailyMedRedirectPolicy(DurableModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    maximum: Literal[1] = 1
    scheme: Literal["https"] = "https"
    host: Literal["dailymed.nlm.nih.gov"] = "dailymed.nlm.nih.gov"
    port: Literal[443] = 443
    cross_host_allowed: Literal[False] = False


class DailyMedTransportPolicy(DurableModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    connect_seconds: Literal[5] = 5
    read_seconds: Literal[10] = 10
    write_seconds: Literal[5] = 5
    pool_seconds: Literal[5] = 5
    total_seconds: Literal[30] = 30
    max_attempts: Literal[2] = 2
    backoff_base_ms: Literal[250] = 250
    backoff_cap_seconds: Literal[4] = 4
    jitter_max_ms: Literal[100] = 100
    retry_after_cap_seconds: Literal[10] = 10
    retryable: tuple[Literal["connect_timeout", "read_timeout", "408", "429", "5xx"], ...] = (
        "connect_timeout",
        "read_timeout",
        "408",
        "429",
        "5xx",
    )
    permanent: tuple[
        Literal["other_4xx", "parse_failure", "identity_drift", "integrity_failure"], ...
    ] = ("other_4xx", "parse_failure", "identity_drift", "integrity_failure")
    discovery_max_pages: Literal[5] = 5
    discovery_max_candidates: Literal[100] = 100
    cumulative_payload_bytes: Literal[5_242_880] = 5_242_880
    response_bytes: Literal[5_242_880] = 5_242_880
    fixed_version_cache: Literal["immutable"] = "immutable"
    latest_discovery_cache: Literal["none"] = "none"
    stale_fallback: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_transport_classes(self) -> Self:
        if self.retryable != (
            "connect_timeout",
            "read_timeout",
            "408",
            "429",
            "5xx",
        ):
            raise ValueError("retryable classes must equal the frozen ordered tuple")
        if self.permanent != (
            "other_4xx",
            "parse_failure",
            "identity_drift",
            "integrity_failure",
        ):
            raise ValueError("permanent classes must equal the frozen ordered tuple")
        return self


class DailyMedConnectorTrustAllowlist(DurableModel):
    """Frozen connector design metadata that explicitly grants no network authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.connector-trust-allowlist.v1"] = (
        "m1b.dailymed.connector-trust-allowlist.v1"
    )
    classification: Literal["frozen_non_authorizing_https_host_path_query_design_metadata"] = (
        "frozen_non_authorizing_https_host_path_query_design_metadata"
    )
    authorizes_network_io: Literal[False] = False
    ordinary_validation_hosts: tuple[()] = ()
    medical_source_network_execution_authorized: Literal[False] = False
    scheme: Literal["https"] = "https"
    host: Literal["dailymed.nlm.nih.gov"] = "dailymed.nlm.nih.gov"
    port: Literal[443] = 443
    methods: tuple[Literal["GET"], ...] = ("GET",)
    userinfo_allowed: Literal[False] = False
    fragments_allowed: Literal[False] = False
    redirect: DailyMedRedirectPolicy = DailyMedRedirectPolicy()
    paths: tuple[DailyMedTrustPath, ...] = Field(min_length=6, max_length=6)
    denied: tuple[ShortText, ...] = (
        "http",
        "alternate_hosts",
        "v1_services",
        "arbitrary_resource_paths",
        "media_endpoints",
        "pdf_endpoints",
        "bulk_downloads",
        "mapping_file_downloads",
        "caller_supplied_urls",
        "arbitrary_query_keys",
        "fragments",
        "userinfo",
        "cross_host_redirects",
    )
    transport: DailyMedTransportPolicy = DailyMedTransportPolicy()

    @model_validator(mode="after")
    def validate_exact_oracle(self) -> Self:
        if self.methods != ("GET",):
            raise ValueError("connector methods must equal the frozen GET-only tuple")
        if self.paths != DAILYMED_TRUST_PATHS:
            raise ValueError("connector trust paths must equal the frozen ordered six")
        if self.denied != (
            "http",
            "alternate_hosts",
            "v1_services",
            "arbitrary_resource_paths",
            "media_endpoints",
            "pdf_endpoints",
            "bulk_downloads",
            "mapping_file_downloads",
            "caller_supplied_urls",
            "arbitrary_query_keys",
            "fragments",
            "userinfo",
            "cross_host_redirects",
        ):
            raise ValueError("connector denied classes must equal the frozen ordered tuple")
        if self.redirect != DailyMedRedirectPolicy():
            raise ValueError("connector redirect policy must equal the frozen exact policy")
        if self.transport != DailyMedTransportPolicy():
            raise ValueError("connector transport policy must equal the frozen exact policy")
        return self


DAILYMED_CONNECTOR_TRUST_ALLOWLIST: Final = DailyMedConnectorTrustAllowlist(
    paths=DAILYMED_TRUST_PATHS
)


class DailyMedXmlSecurityPolicy(DurableModel):
    """Typed parser-security profile for future DM-002 implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.spl-xml-policy.v1"] = "m1b.dailymed.spl-xml-policy.v1"
    parser_policy: Literal["frozen_defusedxml_fail_closed"] = "frozen_defusedxml_fail_closed"
    candidate_root: Literal["{urn:hl7-org:v3}document"] = "{urn:hl7-org:v3}document"
    setid_element: Literal["direct {urn:hl7-org:v3}document/{urn:hl7-org:v3}setId"] = (
        "direct {urn:hl7-org:v3}document/{urn:hl7-org:v3}setId"
    )
    setid_element_count: Literal[1] = 1
    setid_identity_attribute: Literal["unqualified root"] = "unqualified root"
    setid_identity_attribute_count: Literal[1] = 1
    version_element: Literal["direct {urn:hl7-org:v3}document/{urn:hl7-org:v3}versionNumber"] = (
        "direct {urn:hl7-org:v3}document/{urn:hl7-org:v3}versionNumber"
    )
    version_element_count: Literal[1] = 1
    version_identity_attribute: Literal["unqualified value"] = "unqualified value"
    version_identity_attribute_count: Literal[1] = 1
    must_equal_selected_identity: Literal[True] = True
    additional_safe_attributes: Literal["permitted_semantically_inert"] = (
        "permitted_semantically_inert"
    )
    additional_safe_attributes_may_affect: tuple[()] = ()
    additional_safe_attributes_never_affect: tuple[
        Literal["identity", "selection", "provenance", "persistence"], ...
    ] = ("identity", "selection", "provenance", "persistence")
    namespaced_or_local_name_attribute_lookalikes_count: Literal[False] = False
    namespaced_or_local_name_element_lookalikes_count: Literal[False] = False
    nested_selector_elements_count: Literal[False] = False
    missing_duplicate_wrong_location_noncanonical_or_parity_mismatch: Literal["reject"] = "reject"
    parser_resource_io_prohibitions_apply: Literal[True] = True
    filename_or_member_name_is_identity_evidence: Literal[False] = False
    dtd_allowed: Literal[False] = False
    entity_declarations_allowed: Literal[False] = False
    external_resources_allowed: Literal[False] = False
    xinclude_allowed: Literal[False] = False
    schema_resolution_allowed: Literal[False] = False
    xslt_allowed: Literal[False] = False
    recovery_mode_allowed: Literal[False] = False
    response_bytes: Literal[5_242_880] = 5_242_880
    maximum_depth: Literal[64] = 64
    maximum_elements: Literal[50_000] = 50_000
    maximum_attributes_per_element: Literal[64] = 64
    maximum_decoded_characters: Literal[5_000_000] = 5_000_000
    maximum_text_node_characters: Literal[262_144] = 262_144
    maximum_label_sections: Literal[128] = 128
    external_io_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_xml_policy(self) -> Self:
        if self.additional_safe_attributes_never_affect != (
            "identity",
            "selection",
            "provenance",
            "persistence",
        ):
            raise ValueError("inert selector-attribute scope must equal the frozen ordered tuple")
        return self


class DailyMedHistoricalZipPolicy(DurableModel):
    """Typed fail-closed historical ZIP inventory/member contract metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.historical-zip.v1"] = "m1b.dailymed.historical-zip.v1"
    filesystem_extraction: Literal[False] = False
    max_http_or_compressed_bytes: Literal[5_242_880] = 5_242_880
    max_total_uncompressed_bytes: Literal[5_242_880] = 5_242_880
    max_member_uncompressed_bytes: Literal[5_242_880] = 5_242_880
    max_entries: Literal[128] = 128
    full_central_inventory_before_acceptance: Literal[True] = True
    bounds_enforced_before_and_during_reads: Literal[True] = True
    encrypted_entries_allowed: Literal[False] = False
    symlink_device_or_special_entries_allowed: Literal[False] = False
    directories: Literal["allowed_non_evidence"] = "allowed_non_evidence"
    unsafe_name_rejected_before_normalization: Literal[True] = True
    unsafe_name_never_normalized_into_acceptance: Literal[True] = True
    ascii_control_rejection_count: Literal[33] = 33
    rejected_ascii_codepoints: tuple[int, ...] = (*tuple(range(32)), 127)
    member_name_reject: tuple[ShortText, ...] = (
        "ascii_c0_u0000_through_u001f_before_normalization",
        "del_u007f_before_normalization",
        "absolute",
        "empty_segment",
        "dot_segment",
        "dot_dot_segment",
        "traversal",
        "backslash",
        "device",
        "drive",
        "unc",
        "duplicate_normalized_name",
    )
    rejected_path_classes: tuple[ShortText, ...] = (
        "absolute",
        "empty_segment",
        "dot_segment",
        "dot_dot_segment",
        "traversal",
        "backslash",
        "device",
        "drive",
        "unc",
        "duplicate_normalized_name",
    )
    normalized_name_rule: Literal[
        "only after all pre-normalization rejection checks, validated forward-slash POSIX "
        "segments are rejoined exactly; a directory's one terminal slash is removed only "
        "for duplicate comparison"
    ] = (
        "only after all pre-normalization rejection checks, validated forward-slash POSIX "
        "segments are rejoined exactly; a directory's one terminal slash is removed only "
        "for duplicate comparison"
    )
    xml_member_suffix_match: Literal["case_insensitive_.xml"] = "case_insensitive_.xml"
    xml_classification_parser: Literal["frozen_defusedxml_fail_closed"] = (
        "frozen_defusedxml_fail_closed"
    )
    candidate_root: Literal["{urn:hl7-org:v3}document"] = "{urn:hl7-org:v3}document"
    candidate_count: Literal[1] = 1
    exact_candidate_count: Literal[1] = 1
    multiple_candidates: Literal["reject_even_if_exactly_one_matches_selected_identity"] = (
        "reject_even_if_exactly_one_matches_selected_identity"
    )
    candidate_identity: Literal[
        "exactly one direct HL7 setId with one unqualified root and one direct HL7 "
        "versionNumber with one unqualified value; canonical values equal selected SETID/SPL "
        "version; additional safe attributes are inert and lookalikes do not count"
    ] = (
        "exactly one direct HL7 setId with one unqualified root and one direct HL7 "
        "versionNumber with one unqualified value; canonical values equal selected SETID/SPL "
        "version; additional safe attributes are inert and lookalikes do not count"
    )
    member_or_filename_identity_evidence: Literal[False] = False
    malformed_or_unclassifiable_xml: Literal["reject_archive"] = "reject_archive"
    safe_non_xml_attachments: Literal[
        "permitted_but_nonauthoritative_and_not_retained_as_label_evidence"
    ] = "permitted_but_nonauthoritative_and_not_retained_as_label_evidence"

    @model_validator(mode="after")
    def validate_exact_zip_rejection_oracle(self) -> Self:
        if self.rejected_ascii_codepoints != (*tuple(range(32)), 127):
            raise ValueError("ZIP rejected ASCII codepoints must equal all C0 controls and DEL")
        if self.member_name_reject != (
            "ascii_c0_u0000_through_u001f_before_normalization",
            "del_u007f_before_normalization",
            "absolute",
            "empty_segment",
            "dot_segment",
            "dot_dot_segment",
            "traversal",
            "backslash",
            "device",
            "drive",
            "unc",
            "duplicate_normalized_name",
        ):
            raise ValueError("ZIP member-name rejects must equal the frozen ordered tuple")
        if self.rejected_path_classes != (
            "absolute",
            "empty_segment",
            "dot_segment",
            "dot_dot_segment",
            "traversal",
            "backslash",
            "device",
            "drive",
            "unc",
            "duplicate_normalized_name",
        ):
            raise ValueError("ZIP path rejects must equal the frozen ordered tuple")
        return self


DAILYMED_XML_SECURITY_POLICY: Final = DailyMedXmlSecurityPolicy()
DAILYMED_HISTORICAL_ZIP_POLICY: Final = DailyMedHistoricalZipPolicy()
ORDINARY_VALIDATION_HOSTS: Final[tuple[()]] = ()
MEDICAL_SOURCE_NETWORK_EXECUTION_AUTHORIZED: Final = False
