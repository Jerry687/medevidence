"""Draft-only, non-exportable M1A research report contract."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, Self, cast

from pydantic import ConfigDict, Field, model_validator

from .claims import Citation, DailyMedLocatorV1, EvidenceClaim, FaersLocatorV1
from .identifiers import (
    AcquisitionId,
    AcquisitionIntentId,
    AcquisitionRegistrationEnvelopeId,
    ArtifactId,
    ArtifactLinkId,
    AttemptId,
    ClaimId,
    DecisionId,
    DurableModel,
    LongText,
    Pmid,
    PublicationStatusIdentity,
    PublicationVersionId,
    QueryId,
    ReportId,
    RequestId,
    RunId,
    RunIntentId,
    SchemaVersion,
    Sha256Digest,
    SnapshotId,
    SourceOutcomeId,
    UtcDateTime,
    WarningCode,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from .publications import PublicationRecord, PublicationStatusValue
from .scope import (
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    ExecutionBounds,
    FaersAggregateRequestV1,
    M1BResearchRequestV1,
    ResearchScope,
    SourceType,
)
from .sources import (
    CoverageStatus,
    DailyMedCandidateLabel,
    DailyMedLabelVersion,
    DomainWarning,
    ExecutionStatus,
    FaersAggregateQueryV1,
    FaersAggregateResult,
    LabelSection,
    LabelSelectionDecision,
    LabelSelectionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ResultStatus,
    RetainedSplResponse,
    SourceOutcome,
    SourcePlanEntry,
)

RESEARCH_ONLY_NOTICE: Final = (
    "Research assistance only. This draft summarizes public-source evidence and "
    "does not provide diagnosis, treatment, dosage, individualized medical advice, "
    "or a product-safety ranking."
)

PARTIAL_MATCHES_LIMITATION: Final = "Coverage is partial; retained matches are not exhaustive."
PARTIAL_INDETERMINATE_LIMITATION: Final = (
    "Coverage is partial; zero retained matches are indeterminate and do not establish "
    "that no evidence exists."
)
UNAVAILABLE_LIMITATION: Final = (
    "The source was unavailable; coverage is indeterminate and does not establish "
    "that no evidence exists."
)
LIMITATION_STATEMENTS: Final = {
    (CoverageStatus.PARTIAL, ResultStatus.MATCHES): PARTIAL_MATCHES_LIMITATION,
    (CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE): (PARTIAL_INDETERMINATE_LIMITATION),
    (CoverageStatus.UNAVAILABLE, ResultStatus.INDETERMINATE): UNAVAILABLE_LIMITATION,
}


class ReportWarning(DurableModel):
    """Evidence-derived publication-status warning bound to an exact source chain."""

    schema_version: SchemaVersion = "1.0"
    source: SourceType
    code: WarningCode
    message: LongText
    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_status: PublicationStatusValue
    publication_status_identity: PublicationStatusIdentity
    claim_id: ClaimId | None = None

    @classmethod
    def from_publication(
        cls,
        publication: PublicationRecord,
        *,
        code: WarningCode,
        claim: EvidenceClaim | None = None,
    ) -> Self:
        """Create an exact warning row from one publication or claim chain."""

        if code not in publication.publication_status.warning_codes:
            raise ValueError("warning code is not required by the publication status")
        if claim is not None and (
            claim.source_type is not publication.source_type
            or claim.pmid != publication.pmid
            or claim.publication_version_id != publication.publication_version_id
            or claim.publication_status is not publication.publication_status.status
            or claim.publication_status_identity
            != publication.publication_status.publication_status_identity
            or code not in claim.publication_warning_references
        ):
            raise ValueError("claim warning does not resolve to the publication")
        return cls(
            source=publication.source_type,
            code=code,
            message=publication.publication_status.disclosure_text,
            pmid=publication.pmid,
            publication_version_id=publication.publication_version_id,
            publication_status=publication.publication_status.status,
            publication_status_identity=(
                publication.publication_status.publication_status_identity
            ),
            claim_id=claim.claim_id if claim is not None else None,
        )


class CoverageLimitation(DurableModel):
    """Visible report limitation for incomplete source coverage."""

    schema_version: SchemaVersion = "1.0"
    source: SourceType
    query_id: QueryId
    coverage_status: Literal[CoverageStatus.PARTIAL, CoverageStatus.UNAVAILABLE]
    result_status: Literal[ResultStatus.MATCHES, ResultStatus.INDETERMINATE]
    warning_codes: tuple[WarningCode, ...]
    statement: LongText

    @classmethod
    def from_outcome(cls, outcome: SourceOutcome) -> Self:
        """Derive the exact visible limitation required by an incomplete outcome."""

        key = (outcome.coverage_status, outcome.result_status)
        statement = LIMITATION_STATEMENTS.get(key)
        if statement is None:
            raise ValueError("source outcome does not require a coverage limitation")
        return cls(
            source=outcome.source,
            query_id=outcome.query_id,
            coverage_status=cast(
                Literal[CoverageStatus.PARTIAL, CoverageStatus.UNAVAILABLE],
                outcome.coverage_status,
            ),
            result_status=cast(
                Literal[ResultStatus.MATCHES, ResultStatus.INDETERMINATE],
                outcome.result_status,
            ),
            warning_codes=outcome.warning_codes,
            statement=statement,
        )

    @model_validator(mode="after")
    def validate_warnings(self) -> Self:
        if not self.warning_codes:
            raise ValueError("coverage limitation requires warning codes")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("coverage limitation warnings must be unique and sorted")
        expected_statement = LIMITATION_STATEMENTS.get((self.coverage_status, self.result_status))
        if expected_statement is None or self.statement != expected_statement:
            raise ValueError("coverage limitation is not the approved deterministic statement")
        return self


class ResearchReport(DurableModel):
    """Structured research-assistance draft without review or export state."""

    schema_version: SchemaVersion = "1.0"
    report_id: ReportId
    run_id: RunId
    catalog_version: Literal["m1a-concepts-v1"] = "m1a-concepts-v1"
    catalog_content_hash: Sha256Digest
    run_intent_id: RunIntentId
    acquisition_snapshot_ids: tuple[Sha256Digest, ...]
    acquisition_manifest_ids: tuple[Sha256Digest, ...]
    acquisition_registration_envelope_ids: tuple[AcquisitionRegistrationEnvelopeId, ...]
    report_artifact_id: Sha256Digest
    status: Literal["draft"] = "draft"
    exportable: Literal[False] = False
    scope: ResearchScope
    source_plan: tuple[SourcePlanEntry, ...]
    source_outcomes: tuple[SourceOutcome, ...]
    publications: tuple[PublicationRecord, ...]
    claims: tuple[EvidenceClaim, ...]
    citations: tuple[Citation, ...]
    source_status_warnings: tuple[ReportWarning, ...]
    claim_status_warnings: tuple[ReportWarning, ...]
    coverage_limitations: tuple[CoverageLimitation, ...]
    retrieval_as_of: UtcDateTime
    research_only_notice: Literal[
        "Research assistance only. This draft summarizes public-source evidence and "
        "does not provide diagnosis, treatment, dosage, individualized medical advice, "
        "or a product-safety ranking."
    ] = RESEARCH_ONLY_NOTICE

    @classmethod
    def create(
        cls,
        *,
        run_id: RunId,
        catalog_content_hash: Sha256Digest,
        run_intent_id: RunIntentId,
        acquisition_snapshot_ids: tuple[Sha256Digest, ...],
        acquisition_manifest_ids: tuple[Sha256Digest, ...],
        acquisition_registration_envelope_ids: tuple[AcquisitionRegistrationEnvelopeId, ...],
        scope: ResearchScope,
        source_plan: tuple[SourcePlanEntry, ...],
        source_outcomes: tuple[SourceOutcome, ...],
        publications: tuple[PublicationRecord, ...],
        claims: tuple[EvidenceClaim, ...],
        citations: tuple[Citation, ...],
        source_status_warnings: tuple[ReportWarning, ...],
        claim_status_warnings: tuple[ReportWarning, ...],
        coverage_limitations: tuple[CoverageLimitation, ...],
        retrieval_as_of: UtcDateTime,
    ) -> Self:
        """Construct a draft report with a deterministic content identity."""

        canonical_plan = tuple(sorted(source_plan, key=lambda item: item.source.value))
        canonical_outcomes = tuple(sorted(source_outcomes, key=lambda item: item.source.value))
        canonical_publications = tuple(
            sorted(publications, key=lambda item: item.publication_version_id)
        )
        canonical_claims = tuple(sorted(claims, key=lambda item: item.claim_id))
        canonical_citations = tuple(sorted(citations, key=lambda item: item.citation_id))
        canonical_source_warnings = tuple(
            sorted(
                source_status_warnings,
                key=lambda item: (
                    item.source.value,
                    item.publication_version_id,
                    item.code,
                ),
            )
        )
        canonical_claim_warnings = tuple(
            sorted(
                claim_status_warnings,
                key=lambda item: (
                    item.source.value,
                    item.publication_version_id,
                    item.claim_id or "",
                    item.code,
                ),
            )
        )
        canonical_limitations = tuple(
            sorted(
                coverage_limitations,
                key=lambda item: (
                    item.source.value,
                    item.query_id,
                    item.coverage_status.value,
                    item.result_status.value,
                ),
            )
        )
        payload = {
            "schema_version": "1.0",
            "run_id": run_id,
            "catalog_version": "m1a-concepts-v1",
            "catalog_content_hash": catalog_content_hash,
            "run_intent_id": run_intent_id,
            "acquisition_snapshot_ids": acquisition_snapshot_ids,
            "acquisition_manifest_ids": acquisition_manifest_ids,
            "acquisition_registration_envelope_ids": (acquisition_registration_envelope_ids),
            "status": "draft",
            "exportable": False,
            "scope": scope,
            "source_plan": canonical_plan,
            "source_outcomes": canonical_outcomes,
            "publications": canonical_publications,
            "claims": canonical_claims,
            "citations": canonical_citations,
            "source_status_warnings": canonical_source_warnings,
            "claim_status_warnings": canonical_claim_warnings,
            "coverage_limitations": canonical_limitations,
            "retrieval_as_of": retrieval_as_of,
            "research_only_notice": RESEARCH_ONLY_NOTICE,
        }
        report_id = derive_identity("report", payload)
        artifact_payload = {"report_id": report_id, **payload}
        return cls(
            report_id=report_id,
            run_id=run_id,
            catalog_content_hash=catalog_content_hash,
            run_intent_id=run_intent_id,
            acquisition_snapshot_ids=acquisition_snapshot_ids,
            acquisition_manifest_ids=acquisition_manifest_ids,
            acquisition_registration_envelope_ids=(acquisition_registration_envelope_ids),
            report_artifact_id=sha256_digest(canonical_json(artifact_payload)),
            scope=scope,
            source_plan=canonical_plan,
            source_outcomes=canonical_outcomes,
            publications=canonical_publications,
            claims=canonical_claims,
            citations=canonical_citations,
            source_status_warnings=canonical_source_warnings,
            claim_status_warnings=canonical_claim_warnings,
            coverage_limitations=canonical_limitations,
            retrieval_as_of=retrieval_as_of,
        )

    def artifact_bytes(self) -> bytes:
        """Return exact canonical report bytes with the artifact self-field omitted."""

        return canonical_json(
            self.model_dump(mode="python", exclude={"report_artifact_id"})
        ).encode("utf-8")

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        acquisition_count = len(self.acquisition_snapshot_ids)
        if not 1 <= acquisition_count <= 101:
            raise ValueError("report requires between one and 101 acquisition bindings")
        if not (
            len(self.acquisition_manifest_ids)
            == len(self.acquisition_registration_envelope_ids)
            == acquisition_count
        ):
            raise ValueError("ordered acquisition identity bindings must have equal lengths")
        if self.acquisition_snapshot_ids != self.acquisition_manifest_ids:
            raise ValueError("M1A snapshot identities must equal their manifest identities")
        for identities in (
            self.acquisition_snapshot_ids,
            self.acquisition_manifest_ids,
            self.acquisition_registration_envelope_ids,
        ):
            if len(set(identities)) != len(identities):
                raise ValueError("ordered acquisition identities must be unique")
        expected_bounds = ExecutionBounds.from_scope(self.scope)
        plan_by_source = {entry.source: entry for entry in self.source_plan}
        if len(plan_by_source) != len(self.source_plan):
            raise ValueError("source plan entries must be unique by source")
        if set(plan_by_source) != set(self.scope.selected_sources):
            raise ValueError(
                "every in-scope source requires exactly one plan entry and "
                "out-of-scope plan entries are forbidden"
            )
        if any(
            entry.planning_status
            not in {
                PlanningStatus.SELECTED,
                PlanningStatus.SKIPPED_BY_POLICY,
            }
            for entry in self.source_plan
        ):
            raise ValueError("in-scope plan entries must be selected or skipped_by_policy")

        outcomes_by_source = {outcome.source: outcome for outcome in self.source_outcomes}
        if len(outcomes_by_source) != len(self.source_outcomes):
            raise ValueError("source outcomes must be unique by source")
        for source in outcomes_by_source:
            plan_entry = plan_by_source.get(source)
            if plan_entry is None or plan_entry.planning_status is not PlanningStatus.SELECTED:
                raise ValueError("outcomes may belong only to selected plan entries")
        for outcome in self.source_outcomes:
            if outcome.configured_bounds != expected_bounds:
                raise ValueError("source outcome bounds must exactly match report scope")
        if self.source_plan != tuple(sorted(self.source_plan, key=lambda item: item.source.value)):
            raise ValueError("source plan must be canonically sorted")
        if self.source_outcomes != tuple(
            sorted(self.source_outcomes, key=lambda item: item.source.value)
        ):
            raise ValueError("source outcomes must be canonically sorted")

        publications_by_version = {
            publication.publication_version_id: publication for publication in self.publications
        }
        if len(publications_by_version) != len(self.publications):
            raise ValueError("publication versions must be unique")
        if self.publications != tuple(
            sorted(self.publications, key=lambda item: item.publication_version_id)
        ):
            raise ValueError("publications must be canonically sorted")
        citations_by_id = {citation.citation_id: citation for citation in self.citations}
        if len(citations_by_id) != len(self.citations):
            raise ValueError("citation identities must be unique")
        if self.citations != tuple(sorted(self.citations, key=lambda item: item.citation_id)):
            raise ValueError("citations must be canonically sorted")
        claims_by_id = {claim.claim_id: claim for claim in self.claims}
        if len(claims_by_id) != len(self.claims):
            raise ValueError("claim identities must be unique")
        if self.claims != tuple(sorted(self.claims, key=lambda item: item.claim_id)):
            raise ValueError("claims must be canonically sorted")

        for publication in self.publications:
            report_outcome = outcomes_by_source.get(publication.source_type)
            provenance = publication.provenance
            if (
                provenance.snapshot_id not in self.acquisition_snapshot_ids
                or publication.content_hash not in provenance.artifact_ids
                or provenance.snapshot_id not in provenance.artifact_ids
                or provenance.transformation_lineage
                != (publication.content_hash, provenance.snapshot_id)
            ):
                raise ValueError(
                    "report publication requires persisted current-run artifact lineage"
                )
            if (
                publication.source_type not in plan_by_source
                or report_outcome is None
                or provenance.source is not publication.source_type
                or provenance.query_id != report_outcome.query_id
                or provenance.configured_bounds != expected_bounds
                or provenance.source_outcome != report_outcome
            ):
                raise ValueError("publication provenance outcome must match the report outcome")
        for citation in self.citations:
            citation_publication = publications_by_version.get(citation.publication_version_id)
            if citation_publication is None:
                raise ValueError("citation publication version is absent from report")
            if citation_publication.source_type not in plan_by_source:
                raise ValueError("citation publication source is not selected")
            citation.validate_against(citation_publication)
        for claim in self.claims:
            if claim.scope_id != self.scope.scope_id:
                raise ValueError("claim scope_id must exactly match report scope")
            claim_publication = publications_by_version.get(claim.publication_version_id)
            if claim_publication is None:
                raise ValueError("claim publication version is absent from report")
            if (
                claim.source_type is not claim_publication.source_type
                or claim.source_type not in plan_by_source
            ):
                raise ValueError("claim source is not selected or publication-aligned")
            claim_citation = citations_by_id.get(claim.supporting_citation_ids[0])
            if claim_citation is None:
                raise ValueError("claim citation is absent from report")
            claim.validate_against(claim_citation, claim_publication)

        def warning_key(warning: ReportWarning) -> tuple[object, ...]:
            return (
                warning.source,
                warning.code,
                warning.message,
                warning.pmid,
                warning.publication_version_id,
                warning.publication_status,
                warning.publication_status_identity,
                warning.claim_id,
            )

        if self.source_status_warnings != tuple(
            sorted(
                self.source_status_warnings,
                key=lambda item: (
                    item.source.value,
                    item.publication_version_id,
                    item.code,
                ),
            )
        ):
            raise ValueError("source-status warnings must be canonically sorted")
        actual_source_warning_keys = [
            warning_key(warning) for warning in self.source_status_warnings
        ]
        expected_source_warning_keys = {
            warning_key(ReportWarning.from_publication(publication, code=code))
            for publication in self.publications
            for code in publication.publication_status.warning_codes
        }
        if (
            len(actual_source_warning_keys) != len(set(actual_source_warning_keys))
            or set(actual_source_warning_keys) != expected_source_warning_keys
        ):
            raise ValueError(
                "source-status warnings must exactly match evidence-derived publications"
            )

        if self.claim_status_warnings != tuple(
            sorted(
                self.claim_status_warnings,
                key=lambda item: (
                    item.source.value,
                    item.publication_version_id,
                    item.claim_id or "",
                    item.code,
                ),
            )
        ):
            raise ValueError("claim-status warnings must be canonically sorted")
        actual_claim_warning_keys = [warning_key(warning) for warning in self.claim_status_warnings]
        expected_claim_warning_keys = {
            warning_key(
                ReportWarning.from_publication(
                    publications_by_version[claim.publication_version_id],
                    code=code,
                    claim=claim,
                )
            )
            for claim in self.claims
            for code in claim.publication_warning_references
        }
        if (
            len(actual_claim_warning_keys) != len(set(actual_claim_warning_keys))
            or set(actual_claim_warning_keys) != expected_claim_warning_keys
        ):
            raise ValueError("claim-status warnings must exactly match source warning chains")

        def limitation_key(limitation: CoverageLimitation) -> tuple[object, ...]:
            return (
                limitation.source,
                limitation.query_id,
                limitation.coverage_status,
                limitation.result_status,
                limitation.warning_codes,
                limitation.statement,
            )

        if self.coverage_limitations != tuple(
            sorted(
                self.coverage_limitations,
                key=lambda item: (
                    item.source.value,
                    item.query_id,
                    item.coverage_status.value,
                    item.result_status.value,
                ),
            )
        ):
            raise ValueError("coverage limitations must be canonically sorted")
        actual_limitation_keys = [
            limitation_key(limitation) for limitation in self.coverage_limitations
        ]
        expected_limitation_keys = {
            limitation_key(CoverageLimitation.from_outcome(outcome))
            for outcome in self.source_outcomes
            if outcome.coverage_status
            in {
                CoverageStatus.PARTIAL,
                CoverageStatus.UNAVAILABLE,
            }
        }
        if (
            len(actual_limitation_keys) != len(set(actual_limitation_keys))
            or set(actual_limitation_keys) != expected_limitation_keys
        ):
            raise ValueError("coverage limitations must exactly match evidence-derived outcomes")

        expected = derive_identity(
            "report",
            self.model_dump(
                mode="python",
                exclude={"report_id", "report_artifact_id"},
            ),
        )
        if self.report_id != expected:
            raise ValueError("report_id does not match canonical report content")
        if self.report_artifact_id != sha256_digest(self.artifact_bytes()):
            raise ValueError("report_artifact_id does not match canonical report artifact bytes")
        return self


class AcquisitionOutcomeRef(DurableModel):
    """Closed inline reference to one executed source acquisition outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    run_id: RunId
    source: SourceType
    acquisition_id: AcquisitionId
    acquisition_intent_id: AcquisitionIntentId
    acquisition_ordinal: int = Field(ge=0, le=7)
    operation: Literal["search", "fetch"]
    query_id: QueryId
    source_outcome_id: SourceOutcomeId
    snapshot_id: SnapshotId


class DailyMedLabelSectionV1(DurableModel):
    """Truthful source-indexed DailyMed section for one selection request."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.report-section.v1"] = "m1b.dailymed.report-section.v1"
    report_id: ReportId
    run_id: RunId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    ordinal: int = Field(ge=0, le=3)
    section_kind: Literal["dailymed_label"] = "dailymed_label"
    request: DailyMedSelectionRequestV1
    selection_decision_id: DecisionId | None = None
    selection_status: LabelSelectionStatus | None = None
    acquisition_outcome_refs: tuple[AcquisitionOutcomeRef, ...] = Field(
        min_length=1,
        max_length=2,
    )
    label_version: DailyMedLabelVersion | None = None
    retained_response: RetainedSplResponse | None = None
    label_sections: tuple[LabelSection, ...] = ()
    locators: tuple[DailyMedLocatorV1, ...] = ()
    limitations: tuple[LongText, ...] = ()

    @model_validator(mode="after")
    def validate_section_shape(self) -> Self:
        if (self.selection_decision_id is None) != (self.selection_status is None):
            raise ValueError("selection decision identity and status are nullable together")
        refs = self.acquisition_outcome_refs
        if refs[0].operation != "search":
            raise ValueError("DailyMed section begins with exactly one discovery reference")
        if len(refs) == 2:
            discovery_ref, fetch_ref = refs
            if fetch_ref.operation != "fetch":
                raise ValueError("the optional second DailyMed reference must be a fetch")
            if discovery_ref.acquisition_id == fetch_ref.acquisition_id:
                raise ValueError("DailyMed discovery and fetch acquisition IDs must be distinct")
            if discovery_ref.snapshot_id == fetch_ref.snapshot_id:
                raise ValueError("DailyMed discovery and fetch snapshot IDs must be distinct")
            if fetch_ref.acquisition_ordinal <= discovery_ref.acquisition_ordinal:
                raise ValueError(
                    "DailyMed fetch acquisition ordinal must be strictly greater than discovery"
                )
        if len({ref.query_id for ref in refs}) != len(refs):
            raise ValueError("DailyMed acquisition refs must be unique")
        if any(ref.run_id != self.run_id or ref.source is not SourceType.DAILYMED for ref in refs):
            raise ValueError("DailyMed acquisition refs must match section run and source")

        if self.selection_status in {
            LabelSelectionStatus.NO_CANDIDATE,
            LabelSelectionStatus.REVIEW_REQUIRED,
        }:
            if (
                len(refs) != 1
                or self.label_version is not None
                or self.retained_response is not None
                or self.label_sections
            ):
                raise ValueError("degraded DailyMed decisions are discovery-only with no result")
            if self.locators or not self.limitations:
                raise ValueError("degraded DailyMed decisions need a limitation and no locator")
        elif self.selection_status is LabelSelectionStatus.SELECTED:
            if self.label_version is not None and len(refs) != 2:
                raise ValueError("a stable label result requires a distinct fetch reference")
            if self.label_version is None and (
                self.retained_response is not None or self.label_sections or self.locators
            ):
                raise ValueError("sections and locators require a stable label result")
            if self.label_version is not None and self.retained_response is None:
                raise ValueError("stable label result requires its exact retained response")
            if len(refs) == 2 and self.label_version is None and not self.limitations:
                raise ValueError("a selected failed fetch requires a visible limitation")
        else:
            if (
                len(refs) != 1
                or self.label_version is not None
                or self.retained_response is not None
                or self.label_sections
            ):
                raise ValueError("decisionless indeterminate discovery has no stable result")
            if self.locators or not self.limitations:
                raise ValueError("decisionless indeterminate discovery requires a limitation")

        if self.label_version is not None:
            assert self.retained_response is not None
            if self.retained_response.candidate_set_snapshot_id != refs[0].snapshot_id:
                raise ValueError("retained response must equal the discovery snapshot")
            for section in self.label_sections:
                if (
                    section.setid != self.label_version.setid
                    or section.label_version_id != self.label_version.label_version_id
                    or section.spl_version != self.label_version.spl_version
                    or section.spl_artifact_id != self.label_version.spl_artifact_id
                ):
                    raise ValueError("reported section must belong to the exact stable label")
            section_ordinals = tuple(section.section_ordinal for section in self.label_sections)
            if section_ordinals != tuple(range(len(self.label_sections))):
                raise ValueError("label section ordinals must be unique, contiguous, and canonical")
            if self.retained_response.section_ids != tuple(
                section.section_id for section in self.label_sections
            ):
                raise ValueError("retained response must bind the exact ordered sections")
            if (
                self.retained_response.run_id != self.run_id
                or self.retained_response.selection_decision_id != self.selection_decision_id
                or self.retained_response.label_version_id != self.label_version.label_version_id
                or self.retained_response.setid != self.label_version.setid
                or self.retained_response.spl_version != self.label_version.spl_version
                or self.retained_response.content_hash != self.label_version.content_hash
                or self.retained_response.artifact_id != self.label_version.spl_artifact_id
            ):
                raise ValueError("retained response must equal the section stable label")
            reported_codes = {section.section_code for section in self.label_sections}
            missing_codes = set(self.request.requested_section_codes) - reported_codes
            expected_absence = {f"section_absent:{code}" for code in missing_codes}
            actual_absence = {
                limitation
                for limitation in self.limitations
                if limitation.startswith("section_absent:")
            }
            if actual_absence != expected_absence:
                raise ValueError("requested section absence requires exact visible limitations")
        if tuple(
            (locator.section_ordinal, locator.start_char, locator.end_char)
            for locator in self.locators
        ) != tuple(
            sorted(
                {
                    (locator.section_ordinal, locator.start_char, locator.end_char)
                    for locator in self.locators
                }
            )
        ):
            raise ValueError("DailyMed locators must be unique and canonically sorted")
        if any(
            locator.report_id != self.report_id
            or locator.run_id != self.run_id
            or locator.selection_decision_id != self.selection_decision_id
            for locator in self.locators
        ):
            raise ValueError("DailyMed locators must match section report/run/decision")
        if self.retained_response is not None and any(
            locator.selected_candidate_id != self.retained_response.selected_candidate_id
            or locator.fetch_attempt_id != self.retained_response.fetch_attempt_id
            or locator.fetch_acquisition_id != self.retained_response.fetch_acquisition_id
            or locator.fetch_acquisition_intent_id
            != self.retained_response.fetch_acquisition_intent_id
            or locator.fetch_acquisition_ordinal != self.retained_response.fetch_acquisition_ordinal
            or locator.fetch_query_id != self.retained_response.fetch_query_id
            or locator.fetch_snapshot_id != self.retained_response.fetch_snapshot_id
            or locator.fetch_manifest_id != self.retained_response.fetch_manifest_id
            or locator.fetch_source_outcome_id != self.retained_response.fetch_source_outcome_id
            or locator.fetch_member_ordinal != self.retained_response.fetch_member_ordinal
            or locator.fetch_link_id != self.retained_response.fetch_link_id
            or locator.fetch_raw_artifact_id != self.retained_response.fetch_raw_artifact_id
            or locator.fetch_raw_content_hash != self.retained_response.fetch_raw_content_hash
            or locator.stable_content_hash != self.retained_response.content_hash
            or locator.spl_artifact_id != self.retained_response.artifact_id
            for locator in self.locators
        ):
            raise ValueError("DailyMed locator fetch evidence must equal retained response")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("DailyMed limitations must be unique and canonically sorted")
        return self


class FaersAggregateSectionV1(DurableModel):
    """Truthful source-indexed section for one closed FAERS aggregate request."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.faers.report-section.v1"] = "m1b.faers.report-section.v1"
    report_id: ReportId
    run_id: RunId
    source: Literal[SourceType.FAERS] = SourceType.FAERS
    ordinal: int = Field(ge=0, le=7)
    section_kind: Literal["faers_aggregate"] = "faers_aggregate"
    request: FaersAggregateRequestV1
    acquisition_outcome_refs: tuple[AcquisitionOutcomeRef] = Field(min_length=1, max_length=1)
    result: FaersAggregateResult
    locators: tuple[FaersLocatorV1, ...] = Field(max_length=100)
    limitations: tuple[LongText, ...]

    @model_validator(mode="after")
    def validate_faers_section(self) -> Self:
        ref = self.acquisition_outcome_refs[0]
        if (
            ref.run_id != self.run_id
            or ref.source is not SourceType.FAERS
            or ref.operation != "search"
            or ref.query_id != self.result.query.query_id
            or ref.snapshot_id != self.result.snapshot_id
        ):
            raise ValueError("FAERS section acquisition identity drift")
        if FaersAggregateQueryV1.create(self.request) != self.result.query:
            raise ValueError("FAERS section query must equal its exact closed request preimage")
        if self.limitations != self.result.limitations:
            raise ValueError("FAERS section limitations must equal its result limitations")
        if len(self.locators) != len(self.result.buckets):
            raise ValueError("FAERS locators must cover the complete bucket collection")
        for locator, bucket in zip(self.locators, self.result.buckets, strict=True):
            if (
                locator.report_id != self.report_id
                or locator.run_id != self.run_id
                or locator.acquisition_id != ref.acquisition_id
                or locator.snapshot_id != ref.snapshot_id
                or locator.query_id != bucket.query_id
                or locator.outcome_query_id != bucket.query_id
                or locator.endpoint_mode != self.result.query.endpoint_mode
                or locator.identity_stratum != bucket.identity_stratum
                or locator.reaction_pt != bucket.reaction_pt
                or locator.bucket_ordinal != bucket.bucket_ordinal
                or locator.report_count != bucket.report_count
                or locator.role_policy != bucket.role_policy
            ):
                raise ValueError("FAERS locator must equal the exact bucket at its ordinal")
        return self


type M1BSourceSection = Annotated[
    DailyMedLabelSectionV1 | FaersAggregateSectionV1,
    Field(discriminator="section_kind"),
]


class M1BResearchReportV1(DurableModel):
    """Parallel additive M1B draft report; M1A ResearchReport remains unchanged."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.report.v1"] = "m1b.report.v1"
    report_id: ReportId
    run_id: RunId
    request_id: RequestId
    scope: ResearchScope
    source_plan: tuple[M1BSourcePlanEntryV1, ...] = Field(min_length=1, max_length=4)
    source_outcomes: tuple[SourceOutcome, ...]
    source_sections: tuple[M1BSourceSection, ...]
    warnings: tuple[DomainWarning, ...] = ()
    limitations: tuple[LongText, ...] = ()
    retrieved_as_of: UtcDateTime
    status: Literal["draft"] = "draft"
    exportable: Literal[False] = False
    safety_notice: Literal[
        "Research assistance only. This draft summarizes public-source evidence and "
        "does not provide diagnosis, treatment, dosage, individualized medical advice, "
        "or a product-safety ranking."
    ] = RESEARCH_ONLY_NOTICE

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Canonicalize M1B collections around the caller-supplied report identity."""

        data: dict[str, Any] = dict(values)
        data["source_outcomes"] = tuple(
            SourceOutcome.model_validate(
                outcome.model_dump(mode="python") if isinstance(outcome, SourceOutcome) else outcome
            )
            for outcome in data.get("source_outcomes", ())
        )
        sections = tuple(
            sorted(
                data.get("source_sections", ()),
                key=lambda item: (item.source.value, item.ordinal),
            )
        )
        data["source_sections"] = sections
        data["source_plan"] = tuple(sorted(data["source_plan"], key=lambda item: item.source.value))
        ref_order = {
            (ref.source, ref.query_id): (ref.source.value, ref.acquisition_ordinal, ref.query_id)
            for section in sections
            for ref in section.acquisition_outcome_refs
        }
        data["source_outcomes"] = tuple(
            sorted(
                data.get("source_outcomes", ()),
                key=lambda item: ref_order[(item.source, item.query_id)],
            )
        )
        data["warnings"] = tuple(
            sorted(
                set(data.get("warnings", ())),
                key=lambda item: (item.code, item.message),
            )
        )
        data["limitations"] = tuple(sorted(set(data.get("limitations", ()))))
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_m1b_report(self) -> Self:
        validated_outcomes = tuple(
            SourceOutcome.model_validate(outcome.model_dump(mode="python"))
            for outcome in self.source_outcomes
        )
        if validated_outcomes != self.source_outcomes:
            raise ValueError("M1B source outcomes differ from closed validation")

        plan_by_source = {entry.source: entry for entry in self.source_plan}
        if len(plan_by_source) != len(self.source_plan):
            raise ValueError("M1B source plan entries must be unique")
        if set(plan_by_source) != set(self.scope.selected_sources):
            raise ValueError("M1B source plan must exactly equal the scope source set")
        if self.source_plan != tuple(sorted(self.source_plan, key=lambda item: item.source.value)):
            raise ValueError("M1B source plan must be canonically sorted")
        if any(
            entry.planning_status not in {PlanningStatus.SELECTED, PlanningStatus.SKIPPED_BY_POLICY}
            for entry in self.source_plan
        ):
            raise ValueError("in-scope M1B plan entries are selected or skipped_by_policy")

        if self.source_sections != tuple(
            sorted(self.source_sections, key=lambda item: (item.source.value, item.ordinal))
        ):
            raise ValueError("M1B source sections must be canonically sorted")
        if any(
            section.report_id != self.report_id or section.run_id != self.run_id
            for section in self.source_sections
        ):
            raise ValueError("every source section must match the report identity")
        for source in self.scope.selected_sources:
            source_ordinals = tuple(
                section.ordinal for section in self.source_sections if section.source is source
            )
            if source_ordinals != tuple(range(len(source_ordinals))):
                raise ValueError(
                    "M1B same-source section ordinals must be contiguous and canonical"
                )
        request_keys = [canonical_json(section.request) for section in self.source_sections]
        if len(request_keys) != len(set(request_keys)):
            raise ValueError("each source request may have exactly one source section")
        scope_drug_ids = {drug.concept_id for drug in self.scope.drugs}
        if any(
            section.request.drug_concept_id not in scope_drug_ids
            for section in self.source_sections
        ):
            raise ValueError("every source section request drug must belong to report scope")

        refs = tuple(
            ref for section in self.source_sections for ref in section.acquisition_outcome_refs
        )
        ref_keys = tuple((ref.source, ref.query_id) for ref in refs)
        if len(set(ref_keys)) != len(ref_keys):
            raise ValueError("source-section acquisition references must be disjoint")
        for field_name in ("acquisition_id", "snapshot_id", "source_outcome_id"):
            identities = tuple(getattr(ref, field_name) for ref in refs)
            if len(set(identities)) != len(identities):
                raise ValueError(f"source-section {field_name} values must be globally unique")
        dailymed_refs = tuple(ref for ref in refs if ref.source is SourceType.DAILYMED)
        if len(dailymed_refs) > 8:
            raise ValueError("executed DailyMed report acquisitions are bounded to eight")
        ordinal_keys = tuple((ref.run_id, ref.source, ref.acquisition_ordinal) for ref in refs)
        if len(set(ordinal_keys)) != len(ordinal_keys):
            raise ValueError("acquisition ordinals must be unique under run/source ownership")
        outcome_keys = tuple((outcome.source, outcome.query_id) for outcome in self.source_outcomes)
        if len(set(outcome_keys)) != len(outcome_keys) or set(outcome_keys) != set(ref_keys):
            raise ValueError("report outcomes must equal the exact section-reference union")
        ref_by_key = {(ref.source, ref.query_id): ref for ref in refs}
        expected_outcome_order = tuple(
            sorted(
                self.source_outcomes,
                key=lambda item: (
                    item.source.value,
                    ref_by_key[(item.source, item.query_id)].acquisition_ordinal,
                    item.query_id,
                ),
            )
        )
        if self.source_outcomes != expected_outcome_order:
            raise ValueError("M1B source outcomes must use source/ordinal/query order")

        outcomes_by_key = {
            (outcome.source, outcome.query_id): outcome for outcome in self.source_outcomes
        }
        for source, entry in plan_by_source.items():
            has_outcome = any(outcome.source is source for outcome in self.source_outcomes)
            has_section = any(section.source is source for section in self.source_sections)
            if entry.planning_status is PlanningStatus.SKIPPED_BY_POLICY and (
                has_outcome or has_section
            ):
                raise ValueError("skipped source cannot have a section or outcome")
            if (
                entry.planning_status is PlanningStatus.SELECTED
                and source in {SourceType.DAILYMED, SourceType.FAERS}
                and (not has_outcome or not has_section)
            ):
                raise ValueError("executed source needs outcomes and truthful sections")

        for section in self.source_sections:
            if isinstance(section, FaersAggregateSectionV1):
                outcome = outcomes_by_key[(SourceType.FAERS, section.result.query.query_id)]
                if outcome != section.result.source_outcome:
                    raise ValueError("FAERS section result must bind the trusted report outcome")
                continue
            discovery_ref = section.acquisition_outcome_refs[0]
            discovery = outcomes_by_key[(SourceType.DAILYMED, discovery_ref.query_id)]
            if section.selection_status is LabelSelectionStatus.NO_CANDIDATE:
                expected = (
                    ExecutionStatus.SUCCEEDED,
                    CoverageStatus.COMPLETE,
                    ResultStatus.NO_MATCH,
                )
            elif section.selection_status is LabelSelectionStatus.REVIEW_REQUIRED:
                expected = None
                if discovery.result_status is not ResultStatus.MATCHES or (
                    discovery.execution_status,
                    discovery.coverage_status,
                ) not in {
                    (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE),
                    (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL),
                    (ExecutionStatus.FAILED, CoverageStatus.PARTIAL),
                }:
                    raise ValueError("review_required must bind an admitted matches discovery")
                if (
                    discovery.coverage_status is CoverageStatus.COMPLETE
                    and discovery.valid_result_count < 2
                ):
                    raise ValueError("complete review requires multiple non-equivalent candidates")
            elif section.selection_status is LabelSelectionStatus.SELECTED:
                expected = (
                    ExecutionStatus.SUCCEEDED,
                    CoverageStatus.COMPLETE,
                    ResultStatus.MATCHES,
                )
            else:
                expected = None
                if (
                    discovery.result_status is not ResultStatus.INDETERMINATE
                    or discovery.valid_result_count != 0
                ):
                    raise ValueError("decisionless DailyMed discovery must be indeterminate")
            if (
                expected is not None
                and (
                    discovery.execution_status,
                    discovery.coverage_status,
                    discovery.result_status,
                )
                != expected
            ):
                raise ValueError("DailyMed section status contradicts its discovery outcome")

            fetch: SourceOutcome | None = None
            if len(section.acquisition_outcome_refs) == 2:
                fetch_ref = section.acquisition_outcome_refs[1]
                fetch = outcomes_by_key[(SourceType.DAILYMED, fetch_ref.query_id)]
                if section.retained_response is not None and (
                    section.retained_response.fetch_acquisition_id != fetch_ref.acquisition_id
                    or section.retained_response.fetch_acquisition_intent_id
                    != fetch_ref.acquisition_intent_id
                    or section.retained_response.fetch_acquisition_ordinal
                    != fetch_ref.acquisition_ordinal
                    or section.retained_response.fetch_query_id != fetch_ref.query_id
                    or section.retained_response.fetch_snapshot_id != fetch_ref.snapshot_id
                    or section.retained_response.fetch_source_outcome_id
                    != fetch_ref.source_outcome_id
                ):
                    raise ValueError("retained response/fetch reference binding drift")
            if section.label_version is not None:
                if fetch is None or (
                    fetch.execution_status,
                    fetch.coverage_status,
                    fetch.result_status,
                ) != (
                    ExecutionStatus.SUCCEEDED,
                    CoverageStatus.COMPLETE,
                    ResultStatus.MATCHES,
                ):
                    raise ValueError("stable DailyMed result requires a successful complete fetch")
                section_by_key = {
                    (item.section_code, item.section_ordinal): item
                    for item in section.label_sections
                }
                for locator in section.locators:
                    if (
                        locator.discovery_acquisition_intent_id
                        != discovery_ref.acquisition_intent_id
                        or locator.discovery_acquisition_ordinal
                        != discovery_ref.acquisition_ordinal
                        or locator.discovery_query_id != discovery_ref.query_id
                        or locator.discovery_snapshot_id != discovery_ref.snapshot_id
                        or locator.discovery_source_outcome_id != discovery_ref.source_outcome_id
                    ):
                        raise ValueError("DailyMed locator discovery evidence binding drift")
                    stable_section = section_by_key.get(
                        (locator.section_code, locator.section_ordinal)
                    )
                    if stable_section is None:
                        raise ValueError("DailyMed locator must resolve to a reported section")
                    if (
                        locator.setid != section.label_version.setid
                        or locator.label_version_id != section.label_version.label_version_id
                        or locator.spl_version != section.label_version.spl_version
                        or locator.stable_content_hash != section.label_version.content_hash
                        or locator.spl_artifact_id != section.label_version.spl_artifact_id
                        or locator.section_code != stable_section.section_code
                        or locator.section_ordinal != stable_section.section_ordinal
                        or locator.xml_path != stable_section.xml_path
                        or locator.start_char != stable_section.text_start
                        or locator.end_char != stable_section.text_end
                        or locator.section_hash != stable_section.text_hash
                    ):
                        raise ValueError("DailyMed locator intrinsic stable-section binding drift")
            elif fetch is not None and (
                fetch.execution_status,
                fetch.coverage_status,
                fetch.result_status,
            ) == (
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.MATCHES,
            ):
                raise ValueError("successful usable fetch cannot suppress its stable result")

        if self.warnings != tuple(
            sorted(set(self.warnings), key=lambda item: (item.code, item.message))
        ):
            raise ValueError("M1B report warnings must be unique and canonically sorted")
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("M1B report limitations must be unique and canonically sorted")
        return self

    def validate_against(
        self,
        request: M1BResearchRequestV1,
        *,
        trusted_acquisition_outcomes: tuple[
            tuple[
                DailyMedSelectionRequestV1 | FaersAggregateRequestV1,
                AcquisitionOutcomeRef,
                SourceOutcome,
            ],
            ...,
        ],
        trusted_selection_decisions: tuple[
            tuple[
                DailyMedSelectionRequestV1,
                LabelSelectionDecision,
                tuple[DailyMedCandidateLabel, ...],
                Sha256Digest,
            ],
            ...,
        ],
        trusted_fetch_evidence: tuple[
            tuple[
                DailyMedSelectionRequestV1,
                AcquisitionOutcomeRef,
                AttemptId,
                ArtifactId,
                int,
                ArtifactLinkId,
                ArtifactId,
                Sha256Digest,
            ],
            ...,
        ] = (),
    ) -> None:
        """Fail closed on request, acquisition, outcome, or selection identity drift."""

        if type(self).model_validate(self.model_dump(mode="python")) != self:
            raise ValueError("M1B report differs from closed validation")
        if M1BResearchRequestV1.model_validate(request.model_dump(mode="python")) != request:
            raise ValueError("M1B request differs from closed validation")
        for owned_request, ref, outcome in trusted_acquisition_outcomes:
            if isinstance(owned_request, DailyMedSelectionRequestV1):
                validated_owned_request: DailyMedSelectionRequestV1 | FaersAggregateRequestV1 = (
                    DailyMedSelectionRequestV1.model_validate(
                        owned_request.model_dump(mode="python")
                    )
                )
            else:
                validated_owned_request = FaersAggregateRequestV1.model_validate(
                    owned_request.model_dump(mode="python")
                )
            if (
                validated_owned_request != owned_request
                or AcquisitionOutcomeRef.model_validate(ref.model_dump(mode="python")) != ref
                or SourceOutcome.model_validate(outcome.model_dump(mode="python")) != outcome
            ):
                raise ValueError("trusted acquisition context differs from closed validation")
        for owned_request, _decision, candidates, _manifest_hash in trusted_selection_decisions:
            if (
                DailyMedSelectionRequestV1.model_validate(owned_request.model_dump(mode="python"))
                != owned_request
            ):
                raise ValueError("trusted selection request differs from closed validation")
            if (
                tuple(
                    DailyMedCandidateLabel.model_validate(item.model_dump(mode="python"))
                    for item in candidates
                )
                != candidates
            ):
                raise ValueError("trusted selection candidates differ from closed validation")

        if self.request_id != request.request_id:
            raise ValueError("M1B report request_id must equal its exact request")
        if self.scope != request.scope:
            raise ValueError("M1B report scope must equal its exact request scope")
        report_sources = tuple(entry.source for entry in self.source_plan)
        if report_sources != request.requested_sources:
            raise ValueError("M1B report source ownership must equal its exact request")
        echoed_requests = tuple(
            sorted(
                (
                    section.request
                    for section in self.source_sections
                    if isinstance(section, DailyMedLabelSectionV1)
                ),
                key=lambda item: item.drug_concept_id,
            )
        )
        if echoed_requests != request.dailymed_selection_requests:
            raise ValueError(
                "M1B report DailyMed section requests must exactly echo the canonical request"
            )
        echoed_faers_requests = tuple(
            section.request
            for section in self.source_sections
            if isinstance(section, FaersAggregateSectionV1)
        )
        if echoed_faers_requests != request.faers_query_requests:
            raise ValueError(
                "M1B report FAERS section requests must exactly echo the canonical request"
            )
        report_ref_owners = tuple(
            (section.request, ref)
            for section in self.source_sections
            for ref in section.acquisition_outcome_refs
        )
        trusted_ref_owners = tuple(
            (owned_request, ref) for owned_request, ref, _outcome in trusted_acquisition_outcomes
        )
        if len(set(trusted_ref_owners)) != len(trusted_ref_owners):
            raise ValueError("trusted acquisition outcomes must be unique and unambiguous")
        if trusted_ref_owners != report_ref_owners:
            raise ValueError(
                "trusted acquisition outcomes must equal the exact canonical request-owned union"
            )

        for owned_request, ref, outcome in trusted_acquisition_outcomes:
            if isinstance(owned_request, DailyMedSelectionRequestV1):
                permitted_requests: tuple[
                    DailyMedSelectionRequestV1 | FaersAggregateRequestV1, ...
                ] = request.dailymed_selection_requests
                expected_source = SourceType.DAILYMED
            else:
                permitted_requests = request.faers_query_requests
                expected_source = SourceType.FAERS
            if (
                owned_request not in permitted_requests
                or ref.run_id != self.run_id
                or ref.source is not expected_source
                or ref.source is not outcome.source
                or ref.query_id != outcome.query_id
            ):
                raise ValueError("trusted acquisition request ownership or query identity drift")
        canonical_trusted_outcomes = tuple(
            outcome
            for _owned_request, _ref, outcome in sorted(
                trusted_acquisition_outcomes,
                key=lambda item: (
                    item[1].source.value,
                    item[1].acquisition_ordinal,
                    item[1].query_id,
                ),
            )
        )
        if self.source_outcomes != canonical_trusted_outcomes:
            raise ValueError("report outcomes must exactly equal trusted acquisition outcomes")

        decision_sections = tuple(
            section
            for section in self.source_sections
            if isinstance(section, DailyMedLabelSectionV1)
            and section.selection_decision_id is not None
        )
        expected_decision_owners = tuple(
            (section.request, cast(DecisionId, section.selection_decision_id))
            for section in decision_sections
        )
        trusted_decision_owners = tuple(
            (owned_request, decision.decision_id)
            for owned_request, decision, _candidates, _manifest_hash in trusted_selection_decisions
        )
        if len(set(trusted_decision_owners)) != len(trusted_decision_owners):
            raise ValueError("trusted selection decisions must be unique and unambiguous")
        if trusted_decision_owners != expected_decision_owners:
            raise ValueError(
                "trusted selection decisions must equal the exact canonical request-owned union"
            )

        trusted_outcome_by_owner = {
            (owned_request, ref): outcome
            for owned_request, ref, outcome in trusted_acquisition_outcomes
        }
        trusted_decision_by_owner = {
            (owned_request, decision.decision_id): (decision, candidates, manifest_hash)
            for owned_request, decision, candidates, manifest_hash in trusted_selection_decisions
        }
        expected_fetch_owners = tuple(
            (section.request, section.acquisition_outcome_refs[1])
            for section in self.source_sections
            if isinstance(section, DailyMedLabelSectionV1) and section.retained_response is not None
        )
        trusted_fetch_owners = tuple(
            (owned_request, fetch_ref)
            for (
                owned_request,
                fetch_ref,
                _attempt_id,
                _manifest_id,
                _member_ordinal,
                _link_id,
                _raw_artifact_id,
                _raw_content_hash,
            ) in trusted_fetch_evidence
        )
        if len(set(trusted_fetch_owners)) != len(trusted_fetch_owners):
            raise ValueError("trusted fetch evidence must be unique and unambiguous")
        if trusted_fetch_owners != expected_fetch_owners:
            raise ValueError(
                "trusted fetch evidence must equal the exact canonical request-owned union"
            )
        for index, field_name in (
            (2, "attempt_id"),
            (3, "manifest_id"),
            (5, "link_id"),
        ):
            identities = tuple(row[index] for row in trusted_fetch_evidence)
            if len(set(identities)) != len(identities):
                raise ValueError(f"trusted fetch {field_name} values must be globally unique")
        trusted_fetch_by_owner = {
            (owned_request, fetch_ref): (
                attempt_id,
                manifest_id,
                member_ordinal,
                link_id,
                raw_artifact_id,
                raw_content_hash,
            )
            for (
                owned_request,
                fetch_ref,
                attempt_id,
                manifest_id,
                member_ordinal,
                link_id,
                raw_artifact_id,
                raw_content_hash,
            ) in trusted_fetch_evidence
        }
        for section in decision_sections:
            assert section.selection_decision_id is not None
            decision, decision_candidates, discovery_manifest_content_hash = (
                trusted_decision_by_owner[(section.request, section.selection_decision_id)]
            )
            discovery_ref = section.acquisition_outcome_refs[0]
            discovery_outcome = trusted_outcome_by_owner[(section.request, discovery_ref)]
            if (
                decision.decision_id != section.selection_decision_id
                or decision.status is not section.selection_status
                or decision.run_id != section.run_id
                or decision.source is not section.source
                or decision.acquisition_id != discovery_ref.acquisition_id
                or decision.acquisition_intent_id != discovery_ref.acquisition_intent_id
                or decision.acquisition_ordinal != discovery_ref.acquisition_ordinal
                or decision.operation != discovery_ref.operation
                or decision.query_id != discovery_ref.query_id
                or decision.source_outcome_query_id != discovery_ref.query_id
                or decision.source_outcome_id != discovery_ref.source_outcome_id
                or decision.candidate_set_snapshot_id != discovery_ref.snapshot_id
            ):
                raise ValueError("trusted selection decision discovery identity drift")
            decision.validate_against(
                outcome=discovery_outcome,
                candidates=decision_candidates,
                source_outcome_id=discovery_ref.source_outcome_id,
                discovery_manifest_content_hash=discovery_manifest_content_hash,
            )
            if (
                section.request.selection_mode is DailyMedSelectionMode.PINNED_VERSION
                and decision.status is LabelSelectionStatus.SELECTED
                and (
                    section.request.pinned_setid != decision.selected_setid
                    or section.request.pinned_spl_version != decision.selected_spl_version
                )
            ):
                raise ValueError("selected decision must equal the exact request pin")

            if section.label_version is None:
                continue
            assert section.retained_response is not None
            fetch_ref = section.acquisition_outcome_refs[1]
            fetch_outcome = trusted_outcome_by_owner[(section.request, fetch_ref)]
            (
                trusted_fetch_attempt_id,
                trusted_fetch_manifest_id,
                trusted_fetch_member_ordinal,
                trusted_fetch_link_id,
                trusted_fetch_raw_artifact_id,
                trusted_fetch_raw_content_hash,
            ) = trusted_fetch_by_owner[(section.request, fetch_ref)]
            if (
                section.retained_response.fetch_acquisition_id != fetch_ref.acquisition_id
                or section.retained_response.fetch_acquisition_intent_id
                != fetch_ref.acquisition_intent_id
                or section.retained_response.fetch_acquisition_ordinal
                != fetch_ref.acquisition_ordinal
                or section.retained_response.fetch_query_id != fetch_ref.query_id
                or section.retained_response.fetch_snapshot_id != fetch_ref.snapshot_id
                or section.retained_response.fetch_source_outcome_id != fetch_ref.source_outcome_id
            ):
                raise ValueError("retained response must equal the trusted fetch acquisition")
            section.retained_response.validate_against(
                decision=decision,
                discovery_outcome=discovery_outcome,
                decision_candidates=decision_candidates,
                decision_source_outcome_id=discovery_ref.source_outcome_id,
                discovery_manifest_content_hash=discovery_manifest_content_hash,
                fetch_outcome=fetch_outcome,
                trusted_fetch_run_id=fetch_ref.run_id,
                trusted_fetch_source=fetch_ref.source,
                trusted_fetch_acquisition_id=fetch_ref.acquisition_id,
                trusted_fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
                trusted_fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
                trusted_fetch_operation=fetch_ref.operation,
                trusted_fetch_query_id=fetch_ref.query_id,
                trusted_fetch_snapshot_id=fetch_ref.snapshot_id,
                trusted_fetch_source_outcome_id=fetch_ref.source_outcome_id,
                trusted_fetch_attempt_id=trusted_fetch_attempt_id,
                trusted_fetch_manifest_id=trusted_fetch_manifest_id,
                trusted_fetch_member_ordinal=trusted_fetch_member_ordinal,
                trusted_fetch_link_id=trusted_fetch_link_id,
                trusted_fetch_raw_artifact_id=trusted_fetch_raw_artifact_id,
                trusted_fetch_raw_content_hash=trusted_fetch_raw_content_hash,
                label_version=section.label_version,
                sections=section.label_sections,
            )
            sections_by_key = {
                (item.section_code, item.section_ordinal): item for item in section.label_sections
            }
            for locator in section.locators:
                stable_section = sections_by_key[(locator.section_code, locator.section_ordinal)]
                locator.validate_against(
                    discovery_outcome=discovery_outcome,
                    fetch_outcome=fetch_outcome,
                    label_version=section.label_version,
                    section=stable_section,
                    decision=decision,
                    decision_candidates=decision_candidates,
                    decision_source_outcome_id=discovery_ref.source_outcome_id,
                    discovery_manifest_content_hash=discovery_manifest_content_hash,
                    trusted_fetch_run_id=fetch_ref.run_id,
                    trusted_fetch_source=fetch_ref.source,
                    trusted_fetch_acquisition_id=fetch_ref.acquisition_id,
                    trusted_fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
                    trusted_fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
                    trusted_fetch_operation=fetch_ref.operation,
                    trusted_fetch_query_id=fetch_ref.query_id,
                    trusted_fetch_snapshot_id=fetch_ref.snapshot_id,
                    trusted_fetch_source_outcome_id=fetch_ref.source_outcome_id,
                    trusted_fetch_attempt_id=trusted_fetch_attempt_id,
                    trusted_fetch_manifest_id=trusted_fetch_manifest_id,
                    trusted_fetch_member_ordinal=trusted_fetch_member_ordinal,
                    trusted_fetch_link_id=trusted_fetch_link_id,
                    trusted_fetch_raw_artifact_id=trusted_fetch_raw_artifact_id,
                    trusted_fetch_raw_content_hash=trusted_fetch_raw_content_hash,
                    retained_response=section.retained_response,
                )
