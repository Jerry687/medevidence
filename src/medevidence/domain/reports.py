"""Draft-only, non-exportable M1A research report contract."""

from __future__ import annotations

from typing import Final, Literal, Self, cast

from pydantic import model_validator

from .claims import Citation, EvidenceClaim
from .identifiers import (
    AcquisitionRegistrationEnvelopeId,
    ClaimId,
    DurableModel,
    LongText,
    Pmid,
    PublicationStatusIdentity,
    PublicationVersionId,
    QueryId,
    ReportId,
    RunId,
    RunIntentId,
    SchemaVersion,
    Sha256Digest,
    UtcDateTime,
    WarningCode,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from .publications import PublicationRecord, PublicationStatusValue
from .scope import ExecutionBounds, ResearchScope, SourceType
from .sources import (
    CoverageStatus,
    PlanningStatus,
    ResultStatus,
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
