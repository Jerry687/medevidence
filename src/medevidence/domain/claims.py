"""Exact abstract citations and deterministic attributed extract claims."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from .identifiers import (
    AcquisitionId,
    AcquisitionIntentId,
    ArtifactId,
    ArtifactLinkId,
    AttemptId,
    CandidateId,
    CanonicalSetId,
    CanonicalSplVersion,
    CitationId,
    ClaimId,
    DecisionId,
    DurableModel,
    ExactText,
    LabelVersionId,
    Pmid,
    PublicationStatusIdentity,
    PublicationVersionId,
    QueryId,
    ReportId,
    RunId,
    SchemaVersion,
    ScopeId,
    Sha256Digest,
    SnapshotId,
    SourceOutcomeId,
    WarningCode,
    derive_identity,
)
from .publications import (
    CorrectionContentDisposition,
    PublicationRecord,
    PublicationStatusValue,
    RelationshipResolution,
)
from .scope import SourceType
from .sources import (
    CoverageStatus,
    DailyMedCandidateLabel,
    DailyMedLabelVersion,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    LabelSection,
    LabelSelectionDecision,
    LabelSelectionStatus,
    ResultStatus,
    RetainedSplResponse,
    SourceOutcome,
)


class CitationRelationship(StrEnum):
    """How an exact cited span relates to an attributed extract."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT_ONLY = "context_only"


class FaersLocatorV1(DurableModel):
    """Closed narrative-free locator for one exact FAERS aggregate bucket."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.faers.locator.v1"] = "m1b.faers.locator.v1"
    locator_kind: Literal["faers_aggregate_bucket"] = "faers_aggregate_bucket"
    report_id: ReportId
    run_id: RunId
    source: Literal[SourceType.FAERS] = SourceType.FAERS
    acquisition_id: AcquisitionId
    snapshot_id: SnapshotId
    outcome_query_id: QueryId
    query_id: QueryId
    endpoint_mode: Literal["provider_count_occurrence"] = "provider_count_occurrence"
    identity_stratum: Literal["harmonized_substance", "native_medicinal_product"]
    reaction_pt: Literal["DIARRHOEA", "NAUSEA", "VOMITING"]
    bucket_ordinal: int = Field(ge=0, le=99)
    report_count: int = Field(ge=0)
    role_policy: Literal["unfiltered_provider_roles"] = "unfiltered_provider_roles"

    @model_validator(mode="after")
    def validate_query_alias(self) -> Self:
        if self.outcome_query_id != self.query_id:
            raise ValueError("FAERS locator outcome query must equal its aggregate query")
        return self

    def validate_against(
        self,
        query: FaersAggregateQueryV1,
        bucket: FaersAggregateBucketV1,
    ) -> None:
        """Bind this locator to one exact parent query and bucket row."""

        validated = type(self).model_validate(self.model_dump(mode="python"))
        validated_query = FaersAggregateQueryV1.model_validate(query.model_dump(mode="python"))
        validated_bucket = FaersAggregateBucketV1.model_validate(bucket.model_dump(mode="python"))
        if validated != self or validated_query != query or validated_bucket != bucket:
            raise ValueError("FAERS locator context differs from closed validation")
        bucket.validate_against(query)
        if (
            self.query_id != query.query_id
            or self.outcome_query_id != query.query_id
            or self.endpoint_mode != query.endpoint_mode
            or self.identity_stratum != query.identity_stratum
            or self.role_policy != query.role_policy
            or self.query_id != bucket.query_id
            or self.reaction_pt != bucket.reaction_pt
            or self.bucket_ordinal != bucket.bucket_ordinal
            or self.report_count != bucket.report_count
        ):
            raise ValueError("FAERS locator must equal the exact bucket and parent query")


class CitationValidationCode(StrEnum):
    """Deterministic success reasons retained on a valid citation."""

    PMID_MATCH = "pmid_match"
    PUBLICATION_VERSION_MATCH = "publication_version_match"
    ABSTRACT_HASH_MATCH = "abstract_hash_match"
    QUOTE_SPAN_MATCH = "quote_span_match"
    PUBLICATION_STATUS_MATCH = "publication_status_match"
    STATUS_WARNING_MATCH = "status_warning_match"


class CitationValidationErrorCode(StrEnum):
    """Typed structural drift failures for citation validation."""

    PMID_MISMATCH = "pmid_mismatch"
    PUBLICATION_VERSION_MISMATCH = "publication_version_mismatch"
    ABSTRACT_MISSING = "abstract_missing"
    ABSTRACT_HASH_MISMATCH = "abstract_hash_mismatch"
    INVALID_SPAN = "invalid_span"
    QUOTE_MISMATCH = "quote_mismatch"
    PUBLICATION_STATUS_MISMATCH = "publication_status_mismatch"
    PUBLICATION_STATUS_IDENTITY_MISMATCH = "publication_status_identity_mismatch"
    STATUS_WARNING_MISMATCH = "status_warning_mismatch"


class CitationValidationError(ValueError):
    """Typed failure raised when a citation drifts from its publication."""

    def __init__(self, code: CitationValidationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ClaimUseContext(StrEnum):
    """Deterministic publication-status use policy for M1A extracts."""

    AFFIRMATIVE_SUPPORT = "affirmative_support"
    SUPPORT_LIMITED = "support_limited"
    SOURCE_STATUS_CONTEXT = "source_status_context"


REQUIRED_CITATION_CODES = tuple(sorted(code for code in CitationValidationCode))


class Citation(DurableModel):
    """Exact Unicode code-point span bound to one publication version."""

    schema_version: SchemaVersion = "1.0"
    citation_id: CitationId
    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_status: PublicationStatusValue
    publication_status_identity: PublicationStatusIdentity
    status_warning_references: tuple[WarningCode, ...]
    canonical_abstract_sha256: Sha256Digest
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: ExactText
    relationship: CitationRelationship
    validation_state: Literal["passed"] = "passed"
    validation_codes: tuple[CitationValidationCode, ...] = REQUIRED_CITATION_CODES

    @classmethod
    def from_publication(
        cls,
        publication: PublicationRecord,
        *,
        start_offset: int,
        end_offset: int,
        relationship: CitationRelationship = CitationRelationship.SUPPORTS,
    ) -> Self:
        """Create and validate an exact citation from a stored canonical abstract."""

        if publication.canonical_abstract is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_MISSING)
        if publication.canonical_abstract_sha256 is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_HASH_MISMATCH)
        if start_offset < 0 or end_offset <= start_offset:
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        if end_offset > len(publication.canonical_abstract):
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        quote = publication.canonical_abstract[start_offset:end_offset]
        payload = {
            "schema_version": "1.0",
            "pmid": publication.pmid,
            "publication_version_id": publication.publication_version_id,
            "publication_status": publication.publication_status.status,
            "publication_status_identity": (
                publication.publication_status.publication_status_identity
            ),
            "status_warning_references": publication.publication_status.warning_codes,
            "canonical_abstract_sha256": publication.canonical_abstract_sha256,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "exact_quote": quote,
            "relationship": relationship,
            "validation_state": "passed",
            "validation_codes": REQUIRED_CITATION_CODES,
        }
        citation = cls(
            citation_id=derive_identity("citation", payload),
            pmid=publication.pmid,
            publication_version_id=publication.publication_version_id,
            publication_status=publication.publication_status.status,
            publication_status_identity=(
                publication.publication_status.publication_status_identity
            ),
            status_warning_references=publication.publication_status.warning_codes,
            canonical_abstract_sha256=publication.canonical_abstract_sha256,
            start_offset=start_offset,
            end_offset=end_offset,
            exact_quote=quote,
            relationship=relationship,
        )
        citation.validate_against(publication)
        return citation

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.end_offset <= self.start_offset:
            raise ValueError("citation span must be non-empty and half-open")
        if len(set(self.status_warning_references)) != len(self.status_warning_references):
            raise ValueError("status warning references must be unique")
        if self.status_warning_references != tuple(sorted(self.status_warning_references)):
            raise ValueError("status warning references must be canonically sorted")
        if self.validation_codes != REQUIRED_CITATION_CODES:
            raise ValueError("citation must retain the complete deterministic success codes")
        expected = derive_identity(
            "citation",
            self.model_dump(mode="python", exclude={"citation_id"}),
        )
        if self.citation_id != expected:
            raise ValueError("citation_id does not match canonical citation content")
        return self

    def validate_against(self, publication: PublicationRecord) -> None:
        """Fail closed on any approved publication, status, warning, or span drift."""

        if self.pmid != publication.pmid:
            raise CitationValidationError(CitationValidationErrorCode.PMID_MISMATCH)
        if self.publication_version_id != publication.publication_version_id:
            raise CitationValidationError(CitationValidationErrorCode.PUBLICATION_VERSION_MISMATCH)
        if self.publication_status is not publication.publication_status.status:
            raise CitationValidationError(CitationValidationErrorCode.PUBLICATION_STATUS_MISMATCH)
        if (
            self.publication_status_identity
            != publication.publication_status.publication_status_identity
        ):
            raise CitationValidationError(
                CitationValidationErrorCode.PUBLICATION_STATUS_IDENTITY_MISMATCH
            )
        if self.status_warning_references != publication.publication_status.warning_codes:
            raise CitationValidationError(CitationValidationErrorCode.STATUS_WARNING_MISMATCH)
        if publication.canonical_abstract is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_MISSING)
        if self.canonical_abstract_sha256 != publication.canonical_abstract_sha256:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_HASH_MISMATCH)
        if (
            self.start_offset < 0
            or self.end_offset <= self.start_offset
            or self.end_offset > len(publication.canonical_abstract)
        ):
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        if publication.canonical_abstract[self.start_offset : self.end_offset] != self.exact_quote:
            raise CitationValidationError(CitationValidationErrorCode.QUOTE_MISMATCH)


class EvidenceClaim(DurableModel):
    """One deterministic attributed abstract extract with no medical synthesis."""

    schema_version: SchemaVersion = "1.0"
    claim_id: ClaimId
    claim_kind: Literal["attributed_abstract_extract"] = "attributed_abstract_extract"
    claim_text: ExactText
    scope_id: ScopeId
    source_type: Literal[SourceType.PUBMED] = SourceType.PUBMED
    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_status: PublicationStatusValue
    publication_status_identity: PublicationStatusIdentity
    supporting_citation_ids: tuple[CitationId, ...] = Field(min_length=1, max_length=1)
    use_context: ClaimUseContext
    publication_warning_references: tuple[WarningCode, ...]
    limitations: tuple[WarningCode, ...]

    @classmethod
    def from_citation(
        cls,
        *,
        scope_id: ScopeId,
        citation: Citation,
        publication: PublicationRecord,
        use_context: ClaimUseContext,
        additional_limitations: tuple[WarningCode, ...] = (),
    ) -> Self:
        """Build an exact attributed extract after publication-status policy checks."""

        citation.validate_against(publication)
        limitations = tuple(sorted({"abstract_only", *additional_limitations}))
        payload = {
            "schema_version": "1.0",
            "claim_kind": "attributed_abstract_extract",
            "claim_text": citation.exact_quote,
            "scope_id": scope_id,
            "source_type": SourceType.PUBMED,
            "pmid": citation.pmid,
            "publication_version_id": citation.publication_version_id,
            "publication_status": citation.publication_status,
            "publication_status_identity": citation.publication_status_identity,
            "supporting_citation_ids": (citation.citation_id,),
            "use_context": use_context,
            "publication_warning_references": citation.status_warning_references,
            "limitations": limitations,
        }
        claim = cls(
            claim_id=derive_identity("claim", payload),
            claim_text=citation.exact_quote,
            scope_id=scope_id,
            pmid=citation.pmid,
            publication_version_id=citation.publication_version_id,
            publication_status=citation.publication_status,
            publication_status_identity=citation.publication_status_identity,
            supporting_citation_ids=(citation.citation_id,),
            use_context=use_context,
            publication_warning_references=citation.status_warning_references,
            limitations=limitations,
        )
        claim.validate_against(citation, publication)
        return claim

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.publication_warning_references != tuple(
            sorted(self.publication_warning_references)
        ):
            raise ValueError("publication warning references must be canonically sorted")
        if len(set(self.publication_warning_references)) != len(
            self.publication_warning_references
        ):
            raise ValueError("publication warning references must be unique")
        if "abstract_only" not in self.limitations:
            raise ValueError("abstract_only limitation is mandatory")
        if self.limitations != tuple(sorted(self.limitations)):
            raise ValueError("claim limitations must be canonically sorted")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("claim limitations must be unique")
        expected = derive_identity(
            "claim",
            self.model_dump(mode="python", exclude={"claim_id"}),
        )
        if self.claim_id != expected:
            raise ValueError("claim_id does not match canonical claim content")
        return self

    def validate_against(
        self,
        citation: Citation,
        publication: PublicationRecord,
    ) -> None:
        """Revalidate exact quote, identity, warnings, and ADR-009 status policy."""

        citation.validate_against(publication)
        if self.supporting_citation_ids != (citation.citation_id,):
            raise ValueError("claim must reference exactly its validated citation")
        if self.claim_text != citation.exact_quote:
            raise ValueError("claim text must equal the exact cited abstract span")
        if self.pmid != publication.pmid or self.publication_version_id != (
            publication.publication_version_id
        ):
            raise ValueError("claim publication identity does not match citation")
        if (
            self.pmid != citation.pmid
            or self.publication_version_id != citation.publication_version_id
            or self.publication_status is not citation.publication_status
            or self.publication_status_identity != citation.publication_status_identity
        ):
            raise ValueError("claim publication status identity does not match citation")
        if self.publication_warning_references != (publication.publication_status.warning_codes):
            raise ValueError("claim must preserve all publication-status warnings")

        expected_relationship = {
            ClaimUseContext.AFFIRMATIVE_SUPPORT: CitationRelationship.SUPPORTS,
            ClaimUseContext.SUPPORT_LIMITED: CitationRelationship.SUPPORTS,
            ClaimUseContext.SOURCE_STATUS_CONTEXT: CitationRelationship.CONTEXT_ONLY,
        }[self.use_context]
        if citation.relationship is CitationRelationship.CONTRADICTS:
            raise ValueError("contradicting citations require a future typed claim contract")
        if citation.relationship is not expected_relationship:
            raise ValueError("claim use context does not match citation relationship")

        status = publication.publication_status.status
        if status is PublicationStatusValue.RETRACTED:
            if self.use_context is not ClaimUseContext.SOURCE_STATUS_CONTEXT:
                raise ValueError("retracted publication is limited to source-status context")
        elif status in {
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
        }:
            if self.use_context not in {
                ClaimUseContext.SUPPORT_LIMITED,
                ClaimUseContext.SOURCE_STATUS_CONTEXT,
            }:
                raise ValueError("non-current publication cannot be affirmative support")
        elif self.use_context is ClaimUseContext.SUPPORT_LIMITED:
            raise ValueError("support_limited is reserved for concern or unknown status")
        elif (
            status is PublicationStatusValue.CORRECTED
            and self.use_context is ClaimUseContext.AFFIRMATIVE_SUPPORT
        ):
            relationship = publication.publication_status.relationship
            if (
                relationship is None
                or relationship.resolution is not RelationshipResolution.RESOLVED
                or relationship.content_disposition
                is not CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
            ):
                raise ValueError("corrected affirmative support requires resolved current content")


class DailyMedLocatorV1(DurableModel):
    """Closed exact locator for one selected, successfully fetched label section."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.locator.v1"] = "m1b.dailymed.locator.v1"
    locator_kind: Literal["dailymed_label_span"] = "dailymed_label_span"
    report_id: ReportId
    run_id: RunId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    acquisition_id: AcquisitionId
    snapshot_id: SnapshotId
    outcome_query_id: QueryId
    selection_decision_id: DecisionId
    selection_status: Literal[LabelSelectionStatus.SELECTED] = LabelSelectionStatus.SELECTED
    selected_candidate_id: CandidateId
    discovery_attempt_id: AttemptId
    discovery_acquisition_intent_id: AcquisitionIntentId
    discovery_acquisition_ordinal: int = Field(ge=0, le=7)
    discovery_query_id: QueryId
    discovery_snapshot_id: SnapshotId
    discovery_manifest_id: ArtifactId
    discovery_source_outcome_id: SourceOutcomeId
    fetch_attempt_id: AttemptId
    setid: CanonicalSetId
    label_version_id: LabelVersionId
    spl_version: CanonicalSplVersion
    fetch_acquisition_id: AcquisitionId
    fetch_acquisition_intent_id: AcquisitionIntentId
    fetch_acquisition_ordinal: int = Field(ge=0, le=7)
    fetch_operation: Literal["fetch"] = "fetch"
    fetch_query_id: QueryId
    fetch_snapshot_id: SnapshotId
    fetch_manifest_id: ArtifactId
    fetch_source_outcome_id: SourceOutcomeId
    fetch_member_ordinal: int = Field(ge=0, le=127)
    fetch_link_id: ArtifactLinkId
    fetch_raw_artifact_id: ArtifactId
    fetch_raw_content_hash: Sha256Digest
    fetch_body_complete: Literal[True] = True
    fetch_termination_reason: Literal["complete_response"] = "complete_response"
    stable_content_hash: Sha256Digest
    section_code: Literal["34084-4", "43685-7", "34066-1", "34067-9"]
    section_ordinal: int = Field(ge=0, le=127)
    xml_path: ExactText
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    section_hash: Sha256Digest
    spl_artifact_id: ArtifactId

    @model_validator(mode="after")
    def validate_closed_locator(self) -> Self:
        if (
            self.acquisition_id != self.fetch_acquisition_id
            or self.snapshot_id != self.fetch_snapshot_id
            or self.outcome_query_id != self.fetch_query_id
        ):
            raise ValueError("common locator identities must equal the fetch aliases")
        if self.end_char <= self.start_char:
            raise ValueError("DailyMed locator span must be non-empty and half-open")
        if self.fetch_acquisition_ordinal <= self.discovery_acquisition_ordinal:
            raise ValueError("fetch acquisition must follow the discovery acquisition")
        if self.fetch_snapshot_id == self.discovery_snapshot_id:
            raise ValueError("discovery and fetch snapshots must remain distinct")
        return self

    def validate_against(
        self,
        *,
        discovery_outcome: SourceOutcome,
        fetch_outcome: SourceOutcome,
        label_version: DailyMedLabelVersion,
        section: LabelSection,
        decision: LabelSelectionDecision,
        decision_candidates: tuple[DailyMedCandidateLabel, ...],
        decision_source_outcome_id: SourceOutcomeId,
        discovery_manifest_content_hash: Sha256Digest,
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
        retained_response: RetainedSplResponse | None = None,
    ) -> None:
        """Fail closed on outcome, stable-version, or exact section drift."""

        validated = type(self).model_validate(self.model_dump(mode="python"))
        validated_discovery = SourceOutcome.model_validate(
            discovery_outcome.model_dump(mode="python")
        )
        validated_fetch = SourceOutcome.model_validate(fetch_outcome.model_dump(mode="python"))
        validated_version = DailyMedLabelVersion.model_validate(
            label_version.model_dump(mode="python")
        )
        validated_section = LabelSection.model_validate(section.model_dump(mode="python"))
        decision.validate_against(
            outcome=validated_discovery,
            candidates=decision_candidates,
            source_outcome_id=decision_source_outcome_id,
            discovery_manifest_content_hash=discovery_manifest_content_hash,
        )
        validated_decision = decision
        validated_retained = (
            RetainedSplResponse.model_validate(retained_response.model_dump(mode="python"))
            if retained_response is not None
            else None
        )
        if validated != self:
            raise ValueError("locator differs from closed validation")
        if validated_version != label_version:
            raise ValueError("label version differs from closed validation")
        if validated_section != section:
            raise ValueError("label section differs from closed validation")
        if validated_retained != retained_response:
            raise ValueError("retained response differs from closed validation")

        if (
            trusted_fetch_operation != "fetch"
            or validated.run_id != trusted_fetch_run_id
            or validated.source is not trusted_fetch_source
            or validated.fetch_acquisition_id != trusted_fetch_acquisition_id
            or validated.fetch_acquisition_intent_id != trusted_fetch_acquisition_intent_id
            or validated.fetch_acquisition_ordinal != trusted_fetch_acquisition_ordinal
            or validated.fetch_query_id != trusted_fetch_query_id
            or validated.fetch_snapshot_id != trusted_fetch_snapshot_id
            or validated.fetch_source_outcome_id != trusted_fetch_source_outcome_id
            or validated.fetch_attempt_id != trusted_fetch_attempt_id
            or validated.fetch_manifest_id != trusted_fetch_manifest_id
            or validated.fetch_member_ordinal != trusted_fetch_member_ordinal
            or validated.fetch_link_id != trusted_fetch_link_id
            or validated.fetch_raw_artifact_id != trusted_fetch_raw_artifact_id
            or validated.fetch_raw_content_hash != trusted_fetch_raw_content_hash
        ):
            raise ValueError("locator does not equal trusted fetch acquisition")
        if (
            trusted_fetch_acquisition_id == validated_decision.acquisition_id
            or trusted_fetch_snapshot_id == validated_decision.candidate_set_snapshot_id
            or trusted_fetch_acquisition_ordinal <= validated_decision.acquisition_ordinal
        ):
            raise ValueError(
                "trusted fetch acquisition must be distinct from and follow selection discovery"
            )
        if (
            validated_discovery.source is not SourceType.DAILYMED
            or validated_discovery.query_id != validated.discovery_query_id
            or validated_discovery.execution_status is not ExecutionStatus.SUCCEEDED
            or validated_discovery.coverage_status is not CoverageStatus.COMPLETE
            or validated_discovery.result_status is not ResultStatus.MATCHES
        ):
            raise ValueError("locator requires exact successful complete selection discovery")
        if (
            validated_fetch.source is not SourceType.DAILYMED
            or validated_fetch.query_id != validated.fetch_query_id
            or validated_fetch.execution_status is not ExecutionStatus.SUCCEEDED
            or validated_fetch.coverage_status is not CoverageStatus.COMPLETE
            or validated_fetch.result_status is not ResultStatus.MATCHES
        ):
            raise ValueError("DailyMed locator requires a successful complete matching fetch")
        if (
            validated_version.setid != validated.setid
            or validated_version.label_version_id != validated.label_version_id
            or validated_version.spl_version != validated.spl_version
            or validated_version.content_hash != validated.stable_content_hash
            or validated_version.spl_artifact_id != validated.spl_artifact_id
        ):
            raise ValueError("locator stable label identity does not match the label version")
        if (
            validated_section.setid != validated.setid
            or validated_section.label_version_id != validated.label_version_id
            or validated_section.spl_version != validated.spl_version
            or validated_section.section_code != validated.section_code
            or validated_section.section_ordinal != validated.section_ordinal
            or validated_section.xml_path != validated.xml_path
            or validated_section.text_start != validated.start_char
            or validated_section.text_end != validated.end_char
            or validated_section.text_hash != validated.section_hash
            or validated_section.spl_artifact_id != validated.spl_artifact_id
        ):
            raise ValueError("locator section identity does not match the stable section")
        if (
            validated_decision.decision_id != validated.selection_decision_id
            or validated_decision.run_id != validated.run_id
            or validated_decision.source is not validated.source
            or validated_decision.status is not LabelSelectionStatus.SELECTED
            or validated_decision.status is not validated.selection_status
            or validated_decision.selected_candidate_id != validated.selected_candidate_id
            or validated_decision.selected_setid != validated.setid
            or validated_decision.selected_spl_version != validated.spl_version
            or validated_decision.attempt_id != validated.discovery_attempt_id
            or validated_decision.acquisition_intent_id != validated.discovery_acquisition_intent_id
            or validated_decision.acquisition_ordinal != validated.discovery_acquisition_ordinal
            or validated_decision.query_id != validated.discovery_query_id
            or validated_decision.candidate_set_snapshot_id != validated.discovery_snapshot_id
            or validated_decision.discovery_manifest_id != validated.discovery_manifest_id
            or validated_decision.source_outcome_id != validated.discovery_source_outcome_id
        ):
            raise ValueError("locator discovery evidence does not match selection decision")
        if validated_retained is not None and (
            validated_retained.run_id != validated.run_id
            or validated_retained.source is not validated.source
            or validated_retained.acquisition_id != validated.acquisition_id
            or validated_retained.candidate_set_snapshot_id != validated.discovery_snapshot_id
            or validated_retained.selection_decision_id != validated.selection_decision_id
            or validated_retained.source_outcome_query_id != validated.outcome_query_id
            or validated_retained.setid != validated.setid
            or validated_retained.spl_version != validated.spl_version
            or validated_retained.label_version_id != validated.label_version_id
            or validated_retained.manifest_id != validated.fetch_manifest_id
            or validated_retained.body_complete is not validated.fetch_body_complete
            or validated_retained.termination_reason != validated.fetch_termination_reason
            or validated_retained.selected_candidate_id != validated.selected_candidate_id
            or validated_retained.fetch_attempt_id != validated.fetch_attempt_id
            or validated_retained.fetch_acquisition_id != validated.fetch_acquisition_id
            or validated_retained.fetch_acquisition_intent_id
            != validated.fetch_acquisition_intent_id
            or validated_retained.fetch_acquisition_ordinal != validated.fetch_acquisition_ordinal
            or validated_retained.fetch_query_id != validated.fetch_query_id
            or validated_retained.fetch_snapshot_id != validated.fetch_snapshot_id
            or validated_retained.fetch_manifest_id != validated.fetch_manifest_id
            or validated_retained.fetch_source_outcome_id != validated.fetch_source_outcome_id
            or validated_retained.fetch_member_ordinal != validated.fetch_member_ordinal
            or validated_retained.fetch_link_id != validated.fetch_link_id
            or validated_retained.fetch_raw_artifact_id != validated.fetch_raw_artifact_id
            or validated_retained.fetch_raw_content_hash != validated.fetch_raw_content_hash
            or validated_retained.content_hash != validated.stable_content_hash
            or validated_retained.artifact_id != validated.spl_artifact_id
        ):
            raise ValueError("locator fetch evidence does not match retained response")
