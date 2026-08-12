"""Deterministic claim policy and draft-only report aggregate tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    RESEARCH_ONLY_NOTICE,
    AbstractSection,
    AcquisitionOutcomeRef,
    AdverseEventConcept,
    Citation,
    CitationRelationship,
    ClaimUseContext,
    ComparisonIntent,
    CorrectionContentDisposition,
    CoverageLimitation,
    CoverageStatus,
    DailyMedCandidateBinding,
    DailyMedCandidateLabel,
    DailyMedLabelSectionV1,
    DailyMedLabelVersion,
    DailyMedLocatorV1,
    DailyMedMarketingState,
    DailyMedMeaningfulDimension,
    DailyMedResolution,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DomainWarning,
    DrugConcept,
    EvidenceClaim,
    ExecutionBounds,
    ExecutionStatus,
    IndexingStatus,
    LabelSection,
    LabelSelectionDecision,
    LabelSelectionStatus,
    LabelSelectionWarning,
    LabelSelectionWarningCode,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    M1BSourcePlanEntryV1,
    NoticeType,
    PlanningStatus,
    Provenance,
    PublicationRecord,
    PublicationRelationship,
    PublicationRelationshipType,
    PublicationStatus,
    PublicationStatusValue,
    QueryBounds,
    RelationshipResolution,
    ReportWarning,
    ResearchReport,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    RetainedSplResponse,
    SourceOutcome,
    SourcePlanEntry,
    SourcePlanReasonCode,
    SourceType,
    derive_identity,
    sha256_digest,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
RUN_ID = "run:00000000-0000-4000-8000-000000000002"
RUN_INTENT_ID = f"run-intent:sha256:{'1' * 64}"
CATALOG_HASH = f"sha256:{'2' * 64}"
SNAPSHOT_ID = f"sha256:{'3' * 64}"
ENVELOPE_ID = f"registration-envelope:acquisition:sha256:{'4' * 64}"


def report_bindings() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "catalog_content_hash": CATALOG_HASH,
        "run_intent_id": RUN_INTENT_ID,
        "acquisition_snapshot_ids": (SNAPSHOT_ID,),
        "acquisition_manifest_ids": (SNAPSHOT_ID,),
        "acquisition_registration_envelope_ids": (ENVELOPE_ID,),
    }


def scope(
    *,
    selected_sources: tuple[SourceType, ...] = (SourceType.PUBMED,),
) -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="drug:test", preferred_term="test drug"),),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="event:test",
                preferred_term="test event",
            ),
        ),
        date_range=None,
        selected_sources=selected_sources,
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=5,
            max_total_seconds=60,
        ),
        result_bounds=ResultBounds(
            max_records=100,
            max_payload_bytes=5_242_880,
        ),
    )


def bounds() -> ExecutionBounds:
    return ExecutionBounds.from_scope(scope())


def outcome(
    *,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
    source: SourceType = SourceType.PUBMED,
    query_id: str = "query:report",
    configured_bounds: ExecutionBounds | None = None,
) -> SourceOutcome:
    execution = (
        ExecutionStatus.FAILED
        if coverage is CoverageStatus.UNAVAILABLE
        else ExecutionStatus.SUCCEEDED
    )
    warning_codes = {
        CoverageStatus.COMPLETE: (),
        CoverageStatus.PARTIAL: ("source_coverage_incomplete",),
        CoverageStatus.UNAVAILABLE: ("source_unavailable",),
    }[coverage]
    return SourceOutcome(
        source=source,
        query_id=query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=configured_bounds or bounds(),
        valid_result_count=1 if result is ResultStatus.MATCHES else 0,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=warning_codes,
        failure_id="failure:unavailable" if execution is ExecutionStatus.FAILED else None,
    )


def status_for(value: PublicationStatusValue) -> PublicationStatus:
    if value is PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE:
        return PublicationStatus.create(
            status=value,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=None,
            retrieved_as_of=NOW,
        )
    if value is PublicationStatusValue.UNKNOWN_OR_UNVERIFIED:
        return PublicationStatus.create(
            status=value,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=PublicationRelationship(
                relationship_type=PublicationRelationshipType.OTHER,
                upstream_relationship_type="UnrecognizedUpstreamRelation",
                related_pmid="99999",
                resolution=RelationshipResolution.UNRESOLVED,
                content_disposition=CorrectionContentDisposition.NOT_ESTABLISHED,
            ),
            retrieved_as_of=NOW,
        )
    notice = {
        PublicationStatusValue.CORRECTED: NoticeType.CORRECTION,
        PublicationStatusValue.RETRACTED: NoticeType.RETRACTION,
        PublicationStatusValue.EXPRESSION_OF_CONCERN: (NoticeType.EXPRESSION_OF_CONCERN),
    }[value]
    relation_type = {
        PublicationStatusValue.CORRECTED: PublicationRelationshipType.CORRECTED_BY,
        PublicationStatusValue.RETRACTED: PublicationRelationshipType.RETRACTED_BY,
        PublicationStatusValue.EXPRESSION_OF_CONCERN: (
            PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN
        ),
    }[value]
    disposition = (
        CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
        if value is PublicationStatusValue.CORRECTED
        else CorrectionContentDisposition.STATUS_CONTEXT_ONLY
    )
    return PublicationStatus.create(
        status=value,
        status_source="PubMed relationship metadata",
        notice_type=notice,
        relationship=PublicationRelationship(
            relationship_type=relation_type,
            upstream_relationship_type=relation_type.value,
            related_pmid="99999",
            resolution=RelationshipResolution.RESOLVED,
            content_disposition=disposition,
        ),
        retrieved_as_of=NOW,
    )


def publication(
    status_value: PublicationStatusValue,
    *,
    source_outcome: SourceOutcome | None = None,
    publication_status: PublicationStatus | None = None,
) -> PublicationRecord:
    selected_outcome = source_outcome or outcome()
    provenance = Provenance(
        source=SourceType.PUBMED,
        source_record_id="12345",
        query_id=selected_outcome.query_id,
        source_lookup_key="pubmed:12345",
        retrieved_at=NOW,
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b"raw"),
        snapshot_id=SNAPSHOT_ID,
        warnings=tuple(
            DomainWarning(
                code=code,
                message="Source coverage is incomplete.",
            )
            for code in selected_outcome.warning_codes
        ),
        source_outcome=selected_outcome,
        configured_bounds=selected_outcome.configured_bounds,
    )
    record = PublicationRecord.create(
        pmid="12345",
        doi=None,
        pmcid=None,
        title="Report source",
        abstract_sections=(AbstractSection(text="The exact attributed abstract extract."),),
        authors=(),
        journal="Example Journal",
        publication_types=(),
        publication_date=None,
        publication_status=publication_status or status_for(status_value),
        indexing_status=IndexingStatus.INDEXED,
        provenance=provenance,
    )
    payload = record.model_dump(mode="python")
    payload["provenance"] = record.provenance.model_copy(
        update={
            "artifact_ids": tuple(sorted((record.content_hash, SNAPSHOT_ID))),
            "transformation_lineage": (record.content_hash, SNAPSHOT_ID),
        }
    )
    return PublicationRecord.model_validate(payload)


def citation_and_claim(
    status_value: PublicationStatusValue,
    use_context: ClaimUseContext,
    *,
    source_outcome: SourceOutcome | None = None,
) -> tuple[PublicationRecord, Citation, EvidenceClaim]:
    record = publication(status_value, source_outcome=source_outcome)
    relationship = (
        CitationRelationship.CONTEXT_ONLY
        if use_context is ClaimUseContext.SOURCE_STATUS_CONTEXT
        else CitationRelationship.SUPPORTS
    )
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=len(record.canonical_abstract or ""),
        relationship=relationship,
    )
    claim = EvidenceClaim.from_citation(
        scope_id=scope().scope_id,
        citation=citation,
        publication=record,
        use_context=use_context,
    )
    return record, citation, claim


def warning_rows(
    record: PublicationRecord,
    claim: EvidenceClaim,
) -> tuple[tuple[ReportWarning, ...], tuple[ReportWarning, ...]]:
    source_warnings = tuple(
        ReportWarning.from_publication(record, code=code)
        for code in record.publication_status.warning_codes
    )
    claim_warnings = tuple(
        ReportWarning.from_publication(record, code=code, claim=claim)
        for code in claim.publication_warning_references
    )
    return source_warnings, claim_warnings


def claim_with_changes(claim: EvidenceClaim, **changes: object) -> EvidenceClaim:
    """Rebuild a valid claim identity after changing one targeted contract field."""

    payload = claim.model_dump(mode="python", exclude={"claim_id"})
    payload.update(changes)
    payload["claim_id"] = derive_identity("claim", payload)
    return EvidenceClaim.model_validate(payload)


def publication_with_provenance_changes(
    record: PublicationRecord,
    **changes: object,
) -> PublicationRecord:
    payload = record.model_dump(mode="python")
    payload["provenance"] = record.provenance.model_copy(update=changes)
    return PublicationRecord.model_validate(payload)


def report_for(
    record: PublicationRecord,
    citation: Citation,
    claim: EvidenceClaim,
    *,
    source_outcome: SourceOutcome | None = None,
    limitations: tuple[CoverageLimitation, ...] = (),
    report_scope: ResearchScope | None = None,
    source_plan: tuple[SourcePlanEntry, ...] | None = None,
    source_warnings: tuple[ReportWarning, ...] | None = None,
    claim_warnings: tuple[ReportWarning, ...] | None = None,
) -> ResearchReport:
    selected_outcome = source_outcome or outcome()
    if source_warnings is None or claim_warnings is None:
        derived_source_warnings, derived_claim_warnings = warning_rows(record, claim)
    else:
        derived_source_warnings = source_warnings
        derived_claim_warnings = claim_warnings
    return ResearchReport.create(
        **report_bindings(),
        scope=report_scope or scope(),
        source_plan=(
            (
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            )
            if source_plan is None
            else source_plan
        ),
        source_outcomes=(selected_outcome,),
        publications=(record,),
        claims=(claim,),
        citations=(citation,),
        source_status_warnings=(
            derived_source_warnings if source_warnings is None else source_warnings
        ),
        claim_status_warnings=(
            derived_claim_warnings if claim_warnings is None else claim_warnings
        ),
        coverage_limitations=limitations,
        retrieval_as_of=NOW,
    )


def empty_report_for(
    selected_outcome: SourceOutcome,
    *,
    limitations: tuple[CoverageLimitation, ...],
) -> ResearchReport:
    return ResearchReport.create(
        **report_bindings(),
        scope=scope(),
        source_plan=(
            SourcePlanEntry(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(selected_outcome,),
        publications=(),
        claims=(),
        citations=(),
        source_status_warnings=(),
        claim_status_warnings=(),
        coverage_limitations=limitations,
        retrieval_as_of=NOW,
    )


def test_current_extract_is_exact_draft_only_and_non_exportable() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    report = report_for(record, citation, claim)

    assert claim.claim_text == citation.exact_quote
    assert claim.claim_kind == "attributed_abstract_extract"
    assert claim.limitations == ("abstract_only",)
    assert report.status == "draft"
    assert report.exportable is False
    assert report.research_only_notice == RESEARCH_ONLY_NOTICE
    forbidden = {
        "review",
        "approval",
        "rejection",
        "hitl",
        "export",
        "workflow_transition",
        "confidence_score",
        "diagnosis",
        "treatment",
        "dosage",
        "incidence",
        "causality",
        "relative_risk",
        "product_ranking",
    }
    assert forbidden.isdisjoint(type(report).model_fields)
    assert forbidden.isdisjoint(type(claim).model_fields)


@pytest.mark.parametrize(
    "provenance_changes",
    [
        {"snapshot_id": f"sha256:{'9' * 64}"},
        {"artifact_ids": (SNAPSHOT_ID, f"sha256:{'9' * 64}")},
        {"artifact_ids": (f"sha256:{'9' * 64}",)},
        {"transformation_lineage": (SNAPSHOT_ID, f"sha256:{'9' * 64}")},
        {"transformation_lineage": ()},
    ],
)
def test_report_requires_current_run_persisted_publication_lineage(
    provenance_changes: dict[str, object],
) -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    unbound = publication_with_provenance_changes(record, **provenance_changes)
    with pytest.raises(ValidationError, match="current-run artifact lineage"):
        report_for(unbound, citation, claim)


def test_ps03_retracted_record_cannot_support_affirmative_extract() -> None:
    record = publication(PublicationStatusValue.RETRACTED)
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=5,
        relationship=CitationRelationship.SUPPORTS,
    )
    with pytest.raises(ValueError, match="retracted"):
        EvidenceClaim.from_citation(
            scope_id=scope().scope_id,
            citation=citation,
            publication=record,
            use_context=ClaimUseContext.AFFIRMATIVE_SUPPORT,
        )


def test_ps04_retracted_record_is_allowed_only_for_source_status_context() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.RETRACTED,
        ClaimUseContext.SOURCE_STATUS_CONTEXT,
    )
    report = report_for(record, citation, claim)

    assert claim.use_context is ClaimUseContext.SOURCE_STATUS_CONTEXT
    assert citation.relationship is CitationRelationship.CONTEXT_ONLY
    assert "publication_status_retracted" in {
        warning.code for warning in report.claim_status_warnings
    }


def test_ps05_expression_of_concern_is_warning_bearing_and_support_limited() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.EXPRESSION_OF_CONCERN,
        ClaimUseContext.SUPPORT_LIMITED,
    )
    report = report_for(record, citation, claim)

    assert claim.use_context is ClaimUseContext.SUPPORT_LIMITED
    assert "publication_status_expression_of_concern" in {
        warning.code for warning in report.source_status_warnings
    }
    assert "publication_status_expression_of_concern" in {
        warning.code for warning in report.claim_status_warnings
    }


def test_corrected_affirmative_extract_requires_resolved_current_content() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CORRECTED,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    assert claim.claim_text == citation.exact_quote
    assert record.publication_status.relationship is not None
    assert (
        record.publication_status.relationship.content_disposition
        is CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
    )


@pytest.mark.parametrize(
    ("status_value", "use_context", "relationship"),
    [
        (
            PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            ClaimUseContext.AFFIRMATIVE_SUPPORT,
            CitationRelationship.CONTRADICTS,
        ),
        (
            PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            ClaimUseContext.AFFIRMATIVE_SUPPORT,
            CitationRelationship.CONTEXT_ONLY,
        ),
        (
            PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            ClaimUseContext.SOURCE_STATUS_CONTEXT,
            CitationRelationship.SUPPORTS,
        ),
        (
            PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            ClaimUseContext.SOURCE_STATUS_CONTEXT,
            CitationRelationship.CONTRADICTS,
        ),
        (
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            ClaimUseContext.SUPPORT_LIMITED,
            CitationRelationship.CONTEXT_ONLY,
        ),
        (
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            ClaimUseContext.SUPPORT_LIMITED,
            CitationRelationship.CONTRADICTS,
        ),
    ],
)
def test_claim_use_context_requires_exact_citation_relationship(
    status_value: PublicationStatusValue,
    use_context: ClaimUseContext,
    relationship: CitationRelationship,
) -> None:
    record = publication(status_value)
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=5,
        relationship=relationship,
    )
    with pytest.raises(ValueError, match=r"citation|claim use context"):
        EvidenceClaim.from_citation(
            scope_id=scope().scope_id,
            citation=citation,
            publication=record,
            use_context=use_context,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"pmid": "54321"},
        {"publication_version_id": f"pubmed:12345:sha256:{'0' * 64}"},
        {"publication_status": PublicationStatusValue.RETRACTED},
        {"publication_status_identity": f"publication-status:sha256:{'0' * 64}"},
        {"publication_warning_references": ()},
    ],
)
def test_claim_rejects_publication_citation_status_drift(
    changes: dict[str, object],
) -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    drifted = claim.model_copy(update=changes)

    with pytest.raises(ValueError, match=r"claim|warning"):
        drifted.validate_against(citation, record)


def test_report_rejects_claim_from_different_scope() -> None:
    record, citation, _claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    drifted = EvidenceClaim.from_citation(
        scope_id=f"scope:sha256:{'0' * 64}",
        citation=citation,
        publication=record,
        use_context=ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )

    with pytest.raises(ValidationError, match="scope_id"):
        report_for(record, citation, drifted)


def test_report_rejects_citation_whose_publication_is_absent() -> None:
    record, citation, _claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    source_warnings = tuple(
        ReportWarning.from_publication(record, code=code)
        for code in record.publication_status.warning_codes
    )

    with pytest.raises(ValidationError, match="citation publication version is absent"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(outcome(),),
            publications=(),
            claims=(),
            citations=(citation,),
            source_status_warnings=source_warnings,
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_claim_whose_publication_is_absent() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    missing_version = f"pubmed:54321:sha256:{'0' * 64}"
    drifted = claim_with_changes(
        claim,
        pmid="54321",
        publication_version_id=missing_version,
    )
    source_warnings, claim_warnings = warning_rows(record, claim)

    with pytest.raises(ValidationError, match="claim publication version is absent"):
        report_for(
            record,
            citation,
            drifted,
            source_warnings=source_warnings,
            claim_warnings=claim_warnings,
        )


def test_report_rejects_claim_whose_citation_is_absent() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    drifted = claim_with_changes(
        claim,
        supporting_citation_ids=(f"citation:sha256:{'0' * 64}",),
    )

    with pytest.raises(ValidationError, match="claim citation is absent"):
        report_for(record, citation, drifted)


def test_report_rejects_claim_text_that_differs_from_exact_quote() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    drifted = claim_with_changes(
        claim,
        claim_text="A different attributed extract.",
    )

    with pytest.raises(ValidationError, match="claim text must equal"):
        report_for(record, citation, drifted)


@pytest.mark.parametrize(
    "status_value",
    [
        PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
        PublicationStatusValue.EXPRESSION_OF_CONCERN,
    ],
)
def test_non_current_publication_rejects_affirmative_support(
    status_value: PublicationStatusValue,
) -> None:
    record = publication(status_value)
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=5,
        relationship=CitationRelationship.SUPPORTS,
    )

    with pytest.raises(ValueError, match="non-current publication"):
        EvidenceClaim.from_citation(
            scope_id=scope().scope_id,
            citation=citation,
            publication=record,
            use_context=ClaimUseContext.AFFIRMATIVE_SUPPORT,
        )


def test_corrected_affirmative_support_requires_resolved_current_content() -> None:
    corrected_for_context = PublicationStatus.create(
        status=PublicationStatusValue.CORRECTED,
        status_source="PubMed relationship metadata",
        notice_type=NoticeType.CORRECTION,
        relationship=PublicationRelationship(
            relationship_type=PublicationRelationshipType.CORRECTED_BY,
            upstream_relationship_type=PublicationRelationshipType.CORRECTED_BY.value,
            related_pmid="99999",
            resolution=RelationshipResolution.RESOLVED,
            content_disposition=CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
        retrieved_as_of=NOW,
    )
    record = publication(
        PublicationStatusValue.CORRECTED,
        publication_status=corrected_for_context,
    )
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=5,
        relationship=CitationRelationship.SUPPORTS,
    )

    with pytest.raises(ValueError, match="resolved current content"):
        EvidenceClaim.from_citation(
            scope_id=scope().scope_id,
            citation=citation,
            publication=record,
            use_context=ClaimUseContext.AFFIRMATIVE_SUPPORT,
        )


@pytest.mark.parametrize(
    "field",
    [
        "max_query_characters",
        "max_pages",
        "max_records",
        "max_payload_bytes",
        "max_total_seconds",
    ],
)
def test_report_rejects_every_cross_bounds_outcome(field: str) -> None:
    approved = bounds()
    drifted_bounds = approved.model_copy(update={field: getattr(approved, field) - 1})
    drifted_outcome = outcome(
        result=ResultStatus.NO_MATCH,
        configured_bounds=drifted_bounds,
    )

    with pytest.raises(ValidationError, match="bounds"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(drifted_outcome,),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_publication_provenance_query_and_bounds_drift() -> None:
    approved_outcome = outcome()
    for drifted_outcome in (
        outcome(query_id="query:other"),
        outcome(
            configured_bounds=bounds().model_copy(
                update={"max_payload_bytes": bounds().max_payload_bytes - 1}
            )
        ),
    ):
        record, citation, claim = citation_and_claim(
            PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            ClaimUseContext.AFFIRMATIVE_SUPPORT,
            source_outcome=drifted_outcome,
        )
        with pytest.raises(ValidationError, match="provenance outcome"):
            report_for(
                record,
                citation,
                claim,
                source_outcome=approved_outcome,
            )


def test_report_rejects_publication_or_claim_from_unselected_source() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    skipped_plan = (
        SourcePlanEntry(
            source=SourceType.PUBMED,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="Not selected.",
        ),
    )
    with pytest.raises(ValidationError, match="selected plan"):
        report_for(
            record,
            citation,
            claim,
            source_plan=skipped_plan,
        )


def test_partial_coverage_requires_visible_limitation_and_stays_partial() -> None:
    partial = outcome(
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.MATCHES,
    )
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
        source_outcome=partial,
    )
    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        report_for(record, citation, claim, source_outcome=partial)

    limitation = CoverageLimitation.from_outcome(partial)
    report = report_for(
        record,
        citation,
        claim,
        source_outcome=partial,
        limitations=(limitation,),
    )
    assert report.source_outcomes[0].coverage_status is CoverageStatus.PARTIAL


@pytest.mark.parametrize(
    "changes",
    [
        {"source": SourceType.CADEC},
        {"code": "publication_status_retracted"},
        {"message": "Invented disclosure."},
        {"pmid": "54321"},
        {"publication_version_id": f"pubmed:12345:sha256:{'0' * 64}"},
        {"publication_status": PublicationStatusValue.RETRACTED},
        {"publication_status_identity": f"publication-status:sha256:{'0' * 64}"},
    ],
)
def test_report_rejects_cross_source_stale_or_misleading_publication_warning(
    changes: dict[str, object],
) -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    source_warnings, _ = warning_rows(record, claim)
    drifted_warning = source_warnings[0].model_copy(update=changes)

    with pytest.raises(ValidationError, match="evidence-derived publications"):
        report_for(
            record,
            citation,
            claim,
            source_warnings=(drifted_warning,),
        )


def test_report_rejects_duplicate_or_invented_publication_warning() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    source_warnings, _ = warning_rows(record, claim)
    with pytest.raises(ValidationError, match="evidence-derived publications"):
        report_for(
            record,
            citation,
            claim,
            source_warnings=(source_warnings[0], source_warnings[0]),
        )
    invented = source_warnings[0].model_copy(update={"code": "invented_status_warning"})
    with pytest.raises(ValidationError, match="evidence-derived publications"):
        report_for(
            record,
            citation,
            claim,
            source_warnings=(source_warnings[0], invented),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"source": SourceType.CADEC},
        {"code": "publication_status_retracted"},
        {"message": "Invented disclosure."},
        {"pmid": "54321"},
        {"publication_version_id": f"pubmed:12345:sha256:{'0' * 64}"},
    ],
)
def test_claim_warning_must_resolve_to_exact_source_warning(
    changes: dict[str, object],
) -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    _, claim_warnings = warning_rows(record, claim)
    drifted_warning = claim_warnings[0].model_copy(update=changes)

    with pytest.raises(ValidationError, match="source warning chains"):
        report_for(
            record,
            citation,
            claim,
            claim_warnings=(drifted_warning,),
        )


def test_complete_outcome_rejects_invented_partial_limitation() -> None:
    complete = outcome(result=ResultStatus.NO_MATCH)
    partial = outcome(coverage=CoverageStatus.PARTIAL, result=ResultStatus.INDETERMINATE)

    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        empty_report_for(
            complete,
            limitations=(CoverageLimitation.from_outcome(partial),),
        )


def test_partial_outcome_rejects_unavailable_or_missing_limitation() -> None:
    partial = outcome(coverage=CoverageStatus.PARTIAL, result=ResultStatus.INDETERMINATE)
    unavailable = outcome(
        coverage=CoverageStatus.UNAVAILABLE,
        result=ResultStatus.INDETERMINATE,
    )

    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        empty_report_for(partial, limitations=())
    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        empty_report_for(
            partial,
            limitations=(CoverageLimitation.from_outcome(unavailable),),
        )


def test_unavailable_outcome_requires_exact_unavailable_limitation() -> None:
    unavailable = outcome(
        coverage=CoverageStatus.UNAVAILABLE,
        result=ResultStatus.INDETERMINATE,
    )
    limitation = CoverageLimitation.from_outcome(unavailable)
    report = empty_report_for(unavailable, limitations=(limitation,))

    assert report.coverage_limitations == (limitation,)
    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        empty_report_for(unavailable, limitations=())


@pytest.mark.parametrize(
    "changes",
    [
        {"source": SourceType.CADEC},
        {"query_id": "query:other"},
    ],
)
def test_limitation_source_and_query_must_match_outcome(
    changes: dict[str, object],
) -> None:
    partial = outcome(coverage=CoverageStatus.PARTIAL, result=ResultStatus.INDETERMINATE)
    limitation = CoverageLimitation.from_outcome(partial).model_copy(update=changes)

    with pytest.raises(ValidationError, match="evidence-derived outcomes"):
        empty_report_for(partial, limitations=(limitation,))


def test_no_match_and_indeterminate_remain_distinct() -> None:
    complete_no_match = outcome(result=ResultStatus.NO_MATCH)
    partial_indeterminate = outcome(
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
    )
    assert complete_no_match.result_status is ResultStatus.NO_MATCH
    assert partial_indeterminate.result_status is ResultStatus.INDETERMINATE


def test_missing_selected_outcome_remains_visible_and_is_not_fabricated() -> None:
    empty = ResearchReport.create(
        **report_bindings(),
        scope=scope(),
        source_plan=(
            SourcePlanEntry(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(),
        publications=(),
        claims=(),
        citations=(),
        source_status_warnings=(),
        claim_status_warnings=(),
        coverage_limitations=(),
        retrieval_as_of=NOW,
    )

    assert empty.source_plan[0].planning_status is PlanningStatus.SELECTED
    assert empty.source_outcomes == ()
    assert empty.status == "draft"


def test_ps10_domain_report_round_trip_preserves_status_identity_and_warnings() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.RETRACTED,
        ClaimUseContext.SOURCE_STATUS_CONTEXT,
    )
    report = report_for(record, citation, claim)
    round_trip = ResearchReport.model_validate_json(report.model_dump_json())

    assert round_trip == report
    restored = round_trip.publications[0].publication_status
    assert (
        restored.publication_status_identity
        == record.publication_status.publication_status_identity
    )
    assert restored.relationship == record.publication_status.relationship
    assert restored.disclosure_text == record.publication_status.disclosure_text
    assert round_trip.citations[0].status_warning_references == (
        record.publication_status.warning_codes
    )


def test_report_rejects_missing_status_warning() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    _, claim_warnings = warning_rows(record, claim)
    data = {
        **report_bindings(),
        "scope": scope(),
        "source_plan": (
            SourcePlanEntry(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        "source_outcomes": (outcome(),),
        "publications": (record,),
        "claims": (claim,),
        "citations": (citation,),
        "source_status_warnings": (),
        "claim_status_warnings": claim_warnings,
        "coverage_limitations": (),
        "retrieval_as_of": NOW,
    }
    with pytest.raises(ValidationError, match="evidence-derived publications"):
        ResearchReport.create(**data)


def test_report_accepts_mixed_selected_and_skipped_by_policy_sources() -> None:
    mixed_scope = scope(selected_sources=(SourceType.PUBMED, SourceType.CADEC))
    selected = outcome(result=ResultStatus.NO_MATCH)
    report = ResearchReport.create(
        **report_bindings(),
        scope=mixed_scope,
        source_plan=(
            SourcePlanEntry(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
            SourcePlanEntry(
                source=SourceType.CADEC,
                planning_status=PlanningStatus.SKIPPED_BY_POLICY,
                reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
                reason="CADEC execution is not authorized in M1A.",
            ),
        ),
        source_outcomes=(selected,),
        publications=(),
        claims=(),
        citations=(),
        source_status_warnings=(),
        claim_status_warnings=(),
        coverage_limitations=(),
        retrieval_as_of=NOW,
    )

    assert tuple(entry.source for entry in report.source_plan) == (
        SourceType.CADEC,
        SourceType.PUBMED,
    )
    assert report.source_plan[0].planning_status is PlanningStatus.SKIPPED_BY_POLICY
    assert report.source_plan[0].reason_code is SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED
    assert report.source_outcomes == (selected,)


def test_report_rejects_missing_in_scope_plan_entry() -> None:
    with pytest.raises(ValidationError, match="exactly one plan entry"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(selected_sources=(SourceType.PUBMED, SourceType.CADEC)),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_duplicate_in_scope_plan_entry() -> None:
    with pytest.raises(ValidationError, match="unique by source"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(selected_sources=(SourceType.PUBMED, SourceType.CADEC)),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.CADEC,
                    planning_status=PlanningStatus.SKIPPED_BY_POLICY,
                    reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
                    reason="CADEC execution is not authorized in M1A.",
                ),
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_fabricated_outcome_for_skipped_source() -> None:
    with pytest.raises(ValidationError, match="only to selected plan entries"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(selected_sources=(SourceType.PUBMED, SourceType.CADEC)),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.CADEC,
                    planning_status=PlanningStatus.SKIPPED_BY_POLICY,
                    reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
                    reason="CADEC execution is not authorized in M1A.",
                ),
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(
                outcome(source=SourceType.CADEC, result=ResultStatus.NO_MATCH),
                outcome(result=ResultStatus.NO_MATCH),
            ),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_in_scope_not_applicable_plan_entry() -> None:
    mixed_scope = scope(selected_sources=(SourceType.PUBMED, SourceType.CADEC))
    with pytest.raises(ValidationError, match="selected or skipped_by_policy"):
        ResearchReport.create(
            **report_bindings(),
            scope=mixed_scope,
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.CADEC,
                    planning_status=PlanningStatus.SKIPPED_NOT_APPLICABLE,
                    reason_code=SourcePlanReasonCode.NOT_APPLICABLE_TO_SCOPE,
                    reason="CADEC does not apply.",
                ),
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_report_rejects_out_of_scope_plan_entry() -> None:
    with pytest.raises(ValidationError, match="exactly one plan entry"):
        ResearchReport.create(
            **report_bindings(),
            scope=scope(),
            source_plan=(
                SourcePlanEntry(
                    source=SourceType.PUBMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
                SourcePlanEntry(
                    source=SourceType.CADEC,
                    planning_status=PlanningStatus.SKIPPED_BY_POLICY,
                    reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
                    reason="CADEC execution is not authorized in M1A.",
                ),
            ),
            source_outcomes=(),
            publications=(),
            claims=(),
            citations=(),
            source_status_warnings=(),
            claim_status_warnings=(),
            coverage_limitations=(),
            retrieval_as_of=NOW,
        )


def test_claim_and_report_forbid_extras_and_are_frozen() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    report = report_for(record, citation, claim)
    with pytest.raises(ValidationError):
        claim.claim_text = "mutated"
    with pytest.raises(ValidationError):
        ResearchReport(
            **{
                **report.model_dump(mode="python"),
                "approval_state": "approved",
            }
        )


def test_report_binds_exact_run_catalog_acquisition_and_artifact_identities() -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    report = report_for(record, citation, claim)

    assert report.run_id == RUN_ID
    assert report.catalog_version == "m1a-concepts-v1"
    assert report.catalog_content_hash == CATALOG_HASH
    assert report.run_intent_id == RUN_INTENT_ID
    assert report.acquisition_snapshot_ids == (SNAPSHOT_ID,)
    assert report.acquisition_manifest_ids == (SNAPSHOT_ID,)
    assert report.acquisition_registration_envelope_ids == (ENVELOPE_ID,)
    assert sha256_digest(report.artifact_bytes()) == report.report_artifact_id


@pytest.mark.parametrize(
    "changes",
    [
        {"acquisition_manifest_ids": (f"sha256:{'5' * 64}",)},
        {"acquisition_registration_envelope_ids": ()},
        {"report_artifact_id": f"sha256:{'6' * 64}"},
    ],
)
def test_report_rejects_new_identity_binding_drift(changes: dict[str, object]) -> None:
    record, citation, claim = citation_and_claim(
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
        ClaimUseContext.AFFIRMATIVE_SUPPORT,
    )
    report = report_for(record, citation, claim)
    with pytest.raises(ValidationError, match=r"identit|artifact|equal lengths"):
        ResearchReport.model_validate({**report.model_dump(mode="python"), **changes})


DM_REPORT_ID = f"report:sha256:{'a' * 64}"
DM_REQUEST_ID = "request:00000000-0000-4000-8000-000000000011"
DM_SETID = "11111111-1111-1111-1111-111111111111"
DM_DISCOVERY_QUERY = "query:dailymed-discovery"
DM_FETCH_QUERY = "query:dailymed-fetch"


def dailymed_bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=30,
    )


def dailymed_outcome(
    *,
    query_id: str,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
    count: int = 1,
) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.DAILYMED,
        query_id=query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=dailymed_bounds(),
        valid_result_count=count,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=(
            () if coverage is CoverageStatus.COMPLETE else ("source_coverage_incomplete",)
        ),
        failure_id="failure:dailymed" if execution is ExecutionStatus.FAILED else None,
    )


def dailymed_request() -> DailyMedSelectionRequestV1:
    return DailyMedSelectionRequestV1(
        drug_concept_id="drug:test",
        requested_section_codes=("34084-4",),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )


DM_SECTION_CODES = ("34084-4", "43685-7", "34066-1", "34067-9")


def dailymed_matrix_scope(
    drug_count: int,
    *,
    comparison_intent: ComparisonIntent = ComparisonIntent.SUMMARIZE,
) -> ResearchScope:
    return ResearchScope.create(
        drugs=tuple(
            DrugConcept(concept_id=f"drug:test-{ordinal}", preferred_term=f"test drug {ordinal}")
            for ordinal in range(drug_count)
        ),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="event:test",
                preferred_term="test event",
            ),
        ),
        date_range=None,
        selected_sources=(SourceType.DAILYMED,),
        comparison_intent=comparison_intent,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=5,
            max_total_seconds=60,
        ),
        result_bounds=ResultBounds(
            max_records=100,
            max_payload_bytes=5_242_880,
        ),
    )


def dailymed_matrix_request(ordinal: int) -> DailyMedSelectionRequestV1:
    return DailyMedSelectionRequestV1(
        drug_concept_id=f"drug:test-{ordinal}",
        requested_section_codes=(DM_SECTION_CODES[ordinal],),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )


def dailymed_report_for_acquisition_counts(
    acquisition_counts: tuple[int, ...],
    *,
    scope_drug_count: int | None = None,
) -> tuple[
    M1BResearchReportV1,
    M1BResearchRequestV1,
    tuple[tuple[DailyMedSelectionRequestV1, AcquisitionOutcomeRef, SourceOutcome], ...],
    tuple[
        tuple[
            DailyMedSelectionRequestV1,
            LabelSelectionDecision,
            tuple[DailyMedCandidateLabel, ...],
            str,
        ],
        ...,
    ],
]:
    drug_count = scope_drug_count or len(acquisition_counts)
    report_scope = dailymed_matrix_scope(drug_count)
    sections: list[DailyMedLabelSectionV1] = []
    outcomes: list[SourceOutcome] = []
    decisions: list[
        tuple[
            DailyMedSelectionRequestV1,
            LabelSelectionDecision,
            tuple[DailyMedCandidateLabel, ...],
            str,
        ]
    ] = []
    next_acquisition_ordinal = 0
    limitation = "Discovery was indeterminate; no authoritative label was selected."
    fetch_limitation = "The selected label fetch did not produce usable evidence."

    for request_ordinal, acquisition_count in enumerate(acquisition_counts):
        assert acquisition_count in {1, 2}
        request = dailymed_matrix_request(request_ordinal)
        discovery_query_id = f"query:dailymed-matrix-{request_ordinal}-search"
        discovery_ref = AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id=f"acquisition:dailymed-matrix-{request_ordinal}-search",
            acquisition_intent_id=(
                f"acquisition-intent:sha256:{str(next_acquisition_ordinal + 1) * 64}"
            ),
            acquisition_ordinal=next_acquisition_ordinal,
            operation="search",
            query_id=discovery_query_id,
            source_outcome_id=f"source-outcome:dailymed-matrix-{request_ordinal}-search",
            snapshot_id=f"snapshot:dailymed-matrix-{request_ordinal}-search",
        )
        next_acquisition_ordinal += 1

        if acquisition_count == 1:
            outcomes.append(
                dailymed_outcome(
                    query_id=discovery_query_id,
                    coverage=CoverageStatus.PARTIAL,
                    result=ResultStatus.INDETERMINATE,
                    count=0,
                )
            )
            sections.append(
                DailyMedLabelSectionV1(
                    report_id=DM_REPORT_ID,
                    run_id=RUN_ID,
                    ordinal=request_ordinal,
                    request=request,
                    acquisition_outcome_refs=(discovery_ref,),
                    limitations=(limitation,),
                )
            )
            continue

        fetch_query_id = f"query:dailymed-matrix-{request_ordinal}-fetch"
        fetch_ref = AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id=f"acquisition:dailymed-matrix-{request_ordinal}-fetch",
            acquisition_intent_id=(
                f"acquisition-intent:sha256:{str(next_acquisition_ordinal + 1) * 64}"
            ),
            acquisition_ordinal=next_acquisition_ordinal,
            operation="fetch",
            query_id=fetch_query_id,
            source_outcome_id=f"source-outcome:dailymed-matrix-{request_ordinal}-fetch",
            snapshot_id=f"snapshot:dailymed-matrix-{request_ordinal}-fetch",
        )
        next_acquisition_ordinal += 1
        discovery_outcome = dailymed_outcome(query_id=discovery_query_id)
        fetch_outcome = dailymed_outcome(
            query_id=fetch_query_id,
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.PARTIAL,
            result=ResultStatus.INDETERMINATE,
            count=0,
        )
        outcomes.extend((discovery_outcome, fetch_outcome))
        candidate = dailymed_candidate(discovery_ref=discovery_ref)
        decision = LabelSelectionDecision.selected_from_discovery(
            candidates=(candidate,),
            outcome=discovery_outcome,
            resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
            source_outcome_id=discovery_ref.source_outcome_id,
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            decided_at_utc=NOW,
        )
        decisions.append((request, decision, (candidate,), f"sha256:{'f' * 64}"))
        sections.append(
            DailyMedLabelSectionV1(
                report_id=DM_REPORT_ID,
                run_id=RUN_ID,
                ordinal=request_ordinal,
                request=request,
                selection_decision_id=decision.decision_id,
                selection_status=LabelSelectionStatus.SELECTED,
                acquisition_outcome_refs=(discovery_ref, fetch_ref),
                limitations=(fetch_limitation,),
            )
        )

    report = M1BResearchReportV1.create(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        request_id=DM_REQUEST_ID,
        scope=report_scope,
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.DAILYMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=tuple(outcomes),
        source_sections=tuple(sections),
        retrieved_as_of=NOW,
    )
    request = M1BResearchRequestV1(
        request_id=DM_REQUEST_ID,
        scope=report_scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=tuple(section.request for section in sections),
    )
    outcomes_by_query = {outcome.query_id: outcome for outcome in report.source_outcomes}
    trusted_pairs = tuple(
        (section.request, ref, outcomes_by_query[ref.query_id])
        for section in report.source_sections
        for ref in section.acquisition_outcome_refs
    )
    return report, request, trusted_pairs, tuple(decisions)


@pytest.mark.parametrize("acquisition_total", range(1, 9))
def test_actual_dailymed_report_accepts_each_acquisition_total_through_eight(
    acquisition_total: int,
) -> None:
    acquisition_counts = (2,) * (acquisition_total // 2) + ((1,) if acquisition_total % 2 else ())
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts(
        acquisition_counts
    )
    refs = tuple(
        ref for section in report.source_sections for ref in section.acquisition_outcome_refs
    )

    report.validate_against(
        request,
        trusted_acquisition_outcomes=trusted_pairs,
        trusted_selection_decisions=trusted_decisions,
    )
    assert len(refs) == acquisition_total
    assert all(
        1 <= len(section.acquisition_outcome_refs) <= 2 for section in report.source_sections
    )
    assert sum(ref.operation == "search" for ref in refs) <= 4
    assert sum(ref.operation == "fetch" for ref in refs) <= 4
    assert len({(ref.run_id, ref.source, ref.acquisition_ordinal) for ref in refs}) == len(refs)
    assert all(ref.run_id == RUN_ID and ref.source is SourceType.DAILYMED for ref in refs)
    if acquisition_total == 8:
        assert sum(ref.operation == "search" for ref in refs) == 4
        assert sum(ref.operation == "fetch" for ref in refs) == 4


@pytest.mark.parametrize("outcome_index", (0, 1))
@pytest.mark.parametrize("entrypoint", ("create", "mapping", "instance"))
def test_m1b_report_reconstructs_every_source_outcome_at_each_entrypoint(
    outcome_index: int,
    entrypoint: str,
) -> None:
    report, _request, _trusted_pairs, _trusted_decisions = dailymed_report_for_acquisition_counts(
        (2,)
    )
    outcomes = list(report.source_outcomes)
    outcomes[outcome_index] = outcomes[outcome_index].model_copy(update={"schema_version": "evil"})
    values = {name: getattr(report, name) for name in type(report).model_fields}
    values["source_outcomes"] = tuple(outcomes)

    with pytest.raises(ValidationError):
        if entrypoint == "create":
            M1BResearchReportV1.create(**values)
        elif entrypoint == "mapping":
            M1BResearchReportV1.model_validate(values)
        else:
            M1BResearchReportV1.model_validate(
                report.model_copy(update={"source_outcomes": tuple(outcomes)})
            )


def test_actual_dailymed_report_rejects_ninth_acquisition() -> None:
    report, _, _, _ = dailymed_report_for_acquisition_counts((2, 2, 2, 2))
    last_section = report.source_sections[-1]
    extra_ref = AcquisitionOutcomeRef(
        run_id=RUN_ID,
        source=SourceType.DAILYMED,
        acquisition_id="acquisition:dailymed-matrix-extra-fetch",
        acquisition_intent_id=f"acquisition-intent:sha256:{'9' * 64}",
        acquisition_ordinal=0,
        operation="fetch",
        query_id="query:dailymed-matrix-extra-fetch",
        source_outcome_id="source-outcome:dailymed-matrix-extra-fetch",
        snapshot_id="snapshot:dailymed-matrix-extra-fetch",
    )
    ninth_section = last_section.model_copy(
        update={"acquisition_outcome_refs": (*last_section.acquisition_outcome_refs, extra_ref)}
    )
    ninth_outcome = dailymed_outcome(
        query_id=extra_ref.query_id,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )

    with pytest.raises(ValidationError, match=r"bounded to eight|at most 2 items"):
        M1BResearchReportV1.create(
            report_id=report.report_id,
            run_id=report.run_id,
            request_id=report.request_id,
            scope=report.scope,
            source_plan=report.source_plan,
            source_outcomes=(*report.source_outcomes, ninth_outcome),
            source_sections=(*report.source_sections[:-1], ninth_section),
            retrieved_as_of=report.retrieved_as_of,
        )


def test_m1b_report_rejects_section_request_for_drug_outside_scope() -> None:
    report, _, _, _ = dailymed_report_for_acquisition_counts((1,))
    payload = report.model_dump(mode="python")
    payload["source_sections"][0]["request"]["drug_concept_id"] = "drug:foreign"

    with pytest.raises(ValidationError, match="request drug must belong to report scope"):
        M1BResearchReportV1.model_validate(payload)


def test_m1b_report_validates_against_exact_request_identity_scope_and_sources() -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts(
        (1, 2)
    )
    report.validate_against(
        request,
        trusted_acquisition_outcomes=trusted_pairs,
        trusted_selection_decisions=trusted_decisions,
    )

    with pytest.raises(ValueError, match="request_id"):
        report.validate_against(
            request.model_copy(
                update={"request_id": "request:00000000-0000-4000-8000-000000000099"}
            ),
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=trusted_decisions,
        )

    foreign_scope = dailymed_matrix_scope(2, comparison_intent=ComparisonIntent.COMPARE)
    with pytest.raises(ValueError, match="scope"):
        report.validate_against(
            request.model_copy(update={"scope": foreign_scope}),
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=trusted_decisions,
        )

    with pytest.raises(ValueError, match=r"source ownership|scope source set"):
        report.validate_against(
            request.model_copy(update={"requested_sources": (SourceType.PUBMED,)}),
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=trusted_decisions,
        )


def test_m1b_report_exact_request_comparison_rejects_missing_extra_or_drifted_echo() -> None:
    missing_report, missing_request, missing_pairs, missing_decisions = (
        dailymed_report_for_acquisition_counts(
            (1,),
            scope_drug_count=2,
        )
    )
    missing_request = M1BResearchRequestV1(
        request_id=missing_request.request_id,
        scope=missing_request.scope,
        requested_sources=missing_request.requested_sources,
        dailymed_selection_requests=(
            missing_request.dailymed_selection_requests[0],
            dailymed_matrix_request(1),
        ),
    )
    with pytest.raises(ValueError, match="exactly echo"):
        missing_report.validate_against(
            missing_request,
            trusted_acquisition_outcomes=missing_pairs,
            trusted_selection_decisions=missing_decisions,
        )

    extra_report, extra_request, extra_pairs, extra_decisions = (
        dailymed_report_for_acquisition_counts((1, 1))
    )
    extra_request = M1BResearchRequestV1(
        request_id=extra_request.request_id,
        scope=extra_request.scope,
        requested_sources=extra_request.requested_sources,
        dailymed_selection_requests=(extra_request.dailymed_selection_requests[0],),
    )
    with pytest.raises(ValueError, match="exactly echo"):
        extra_report.validate_against(
            extra_request,
            trusted_acquisition_outcomes=extra_pairs,
            trusted_selection_decisions=extra_decisions,
        )

    drifted_report, drifted_request, drifted_pairs, drifted_decisions = (
        dailymed_report_for_acquisition_counts((1,))
    )
    drifted_element = DailyMedSelectionRequestV1(
        drug_concept_id=drifted_request.dailymed_selection_requests[0].drug_concept_id,
        requested_section_codes=("43685-7",),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )
    drifted_request = M1BResearchRequestV1(
        request_id=drifted_request.request_id,
        scope=drifted_request.scope,
        requested_sources=drifted_request.requested_sources,
        dailymed_selection_requests=(drifted_element,),
    )
    with pytest.raises(ValueError, match="exactly echo"):
        drifted_report.validate_against(
            drifted_request,
            trusted_acquisition_outcomes=drifted_pairs,
            trusted_selection_decisions=drifted_decisions,
        )


@pytest.mark.parametrize(
    ("field", "drift"),
    (
        ("run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("source", SourceType.PUBMED),
        ("acquisition_id", "acquisition:foreign"),
        ("acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("acquisition_ordinal", 7),
        ("operation", "fetch"),
        ("query_id", "query:foreign"),
        ("source_outcome_id", "source-outcome:foreign"),
        ("snapshot_id", "snapshot:foreign"),
    ),
)
def test_m1b_report_rejects_each_foreign_trusted_acquisition_identity(
    field: str,
    drift: object,
) -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts(
        (1, 2)
    )
    owned_request, ref, outcome = trusted_pairs[0]
    altered_pairs = (
        (owned_request, ref.model_copy(update={field: drift}), outcome),
        *trusted_pairs[1:],
    )

    with pytest.raises(ValueError, match="trusted acquisition"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=altered_pairs,
            trusted_selection_decisions=trusted_decisions,
        )


def test_m1b_report_rejects_missing_extra_ambiguous_or_drifted_trusted_outcomes() -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts(
        (1, 2)
    )
    owned_request, ref, outcome = trusted_pairs[0]

    invalid_collections = (
        trusted_pairs[1:],
        (*trusted_pairs, trusted_pairs[-1]),
        (trusted_pairs[0], trusted_pairs[0], *trusted_pairs[1:]),
        tuple(reversed(trusted_pairs)),
        (
            (owned_request, ref, outcome.model_copy(update={"valid_result_count": 99})),
            *trusted_pairs[1:],
        ),
    )
    for invalid in invalid_collections:
        with pytest.raises(ValueError, match=r"trusted|report outcomes|validation error"):
            report.validate_against(
                request,
                trusted_acquisition_outcomes=invalid,
                trusted_selection_decisions=trusted_decisions,
            )

    foreign_outcome = outcome.model_copy(update={"query_id": "query:foreign"})
    with pytest.raises(ValueError, match="ownership or query identity"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=(
                (owned_request, ref, foreign_outcome),
                *trusted_pairs[1:],
            ),
            trusted_selection_decisions=trusted_decisions,
        )


def test_m1b_report_rejects_cross_request_acquisition_or_decision_swaps() -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts(
        (2, 2)
    )
    first_request, first_ref, first_outcome = trusted_pairs[0]
    second_request, second_ref, second_outcome = trusted_pairs[2]
    swapped_pairs = (
        (second_request, first_ref, first_outcome),
        trusted_pairs[1],
        (first_request, second_ref, second_outcome),
        trusted_pairs[3],
    )
    with pytest.raises(ValueError, match="canonical request-owned union"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=swapped_pairs,
            trusted_selection_decisions=trusted_decisions,
        )

    first_decision_request, first_decision, first_candidates, first_manifest_hash = (
        trusted_decisions[0]
    )
    second_decision_request, second_decision, second_candidates, second_manifest_hash = (
        trusted_decisions[1]
    )
    with pytest.raises(ValueError, match="canonical request-owned union"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (
                    second_decision_request,
                    first_decision,
                    first_candidates,
                    first_manifest_hash,
                ),
                (
                    first_decision_request,
                    second_decision,
                    second_candidates,
                    second_manifest_hash,
                ),
            ),
        )


@pytest.mark.parametrize(
    ("field", "drift"),
    (
        ("decision_id", "decision:foreign"),
        ("run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("source", SourceType.PUBMED),
        ("acquisition_id", "acquisition:foreign"),
        ("acquisition_intent_id", f"acquisition-intent:sha256:{'8' * 64}"),
        ("acquisition_ordinal", 7),
        ("operation", "fetch"),
        ("query_id", "query:foreign"),
        ("source_outcome_query_id", "query:foreign"),
        ("source_outcome_id", "source-outcome:foreign"),
        ("candidate_set_snapshot_id", "snapshot:foreign"),
        ("status", LabelSelectionStatus.REVIEW_REQUIRED),
    ),
)
def test_m1b_report_rejects_each_foreign_trusted_selection_identity(
    field: str,
    drift: object,
) -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts((2,))
    owned_request, trusted_decision, candidates, manifest_hash = trusted_decisions[0]
    decision = trusted_decision.model_copy(update={field: drift})

    with pytest.raises(ValueError, match=r"trusted selection|validation error"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=((owned_request, decision, candidates, manifest_hash),),
        )


def test_m1b_report_rejects_missing_extra_or_ambiguous_trusted_decisions() -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts((2,))
    owned_request, decision, candidates, manifest_hash = trusted_decisions[0]
    for invalid in (
        (),
        (
            (owned_request, decision, candidates, manifest_hash),
            (owned_request, decision, candidates, manifest_hash),
        ),
        (
            (owned_request, decision, candidates, manifest_hash),
            (
                owned_request,
                decision.model_copy(update={"decision_id": "decision:foreign"}),
                candidates,
                manifest_hash,
            ),
        ),
    ):
        with pytest.raises(ValueError, match=r"trusted selection decisions|validation error"):
            report.validate_against(
                request,
                trusted_acquisition_outcomes=trusted_pairs,
                trusted_selection_decisions=invalid,
            )


def test_failed_fetch_report_revalidates_exact_authoritative_candidate_context() -> None:
    report, request, trusted_pairs, trusted_decisions = dailymed_report_for_acquisition_counts((2,))
    owned_request, decision, candidates, manifest_hash = trusted_decisions[0]
    drifted_candidate = candidates[0].model_copy(update={"acquisition_id": "acquisition:foreign"})

    with pytest.raises(
        ValidationError,
        match=r"candidate discovery identity|candidate_id does not match",
    ):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (owned_request, decision, (drifted_candidate,), manifest_hash),
            ),
        )


def dailymed_version_and_section() -> tuple[DailyMedLabelVersion, LabelSection]:
    version = DailyMedLabelVersion.create(
        setid=DM_SETID,
        spl_version="3",
        marketing_state=DailyMedMarketingState.ACTIVE,
        effective_date=None,
        published_date=None,
        content_hash=f"sha256:{'b' * 64}",
        spl_artifact_id=f"sha256:{'c' * 64}",
    )
    section = LabelSection.create(
        setid=DM_SETID,
        label_version_id=version.label_version_id,
        spl_version="3",
        section_ordinal=0,
        section_code="34084-4",
        title="FDA package insert Adverse reactions section",
        parent_section_id=None,
        xml_path="/document/component/section[1]",
        text_start=0,
        text_end=12,
        text_hash=f"sha256:{'d' * 64}",
        spl_artifact_id=version.spl_artifact_id,
    )
    return version, section


def test_dailymed_stable_version_and_section_are_fetch_independent() -> None:
    version, section = dailymed_version_and_section()
    assert "acquisition_id" not in type(version).model_fields
    assert "fetch_acquisition_id" not in type(section).model_fields
    assert section.label_version_id == version.label_version_id
    assert DailyMedLabelVersion.model_validate_json(version.model_dump_json()) == version

    with pytest.raises(ValidationError):
        LabelSection(
            **{
                **section.model_dump(mode="python"),
                "title": "Adverse reactions",
            }
        )

    for model, field, drift in (
        (version, "label_version_id", "label-version:foreign"),
        (section, "section_id", "section:foreign"),
        (section, "title", "Wrong title"),
    ):
        with pytest.raises(ValidationError):
            type(model).model_validate(model.model_copy(update={field: drift}))


def test_all_closed_dm001_models_always_revalidate_instances() -> None:
    for model_type in (
        M1BSourcePlanEntryV1,
        DailyMedCandidateBinding,
        DailyMedCandidateLabel,
        LabelSelectionDecision,
        DailyMedLabelVersion,
        RetainedSplResponse,
        LabelSelectionWarning,
        LabelSection,
        DailyMedSelectionRequestV1,
        M1BResearchRequestV1,
        DailyMedLocatorV1,
        AcquisitionOutcomeRef,
        DailyMedLabelSectionV1,
        M1BResearchReportV1,
    ):
        assert model_type.model_config["extra"] == "forbid"
        assert model_type.model_config["frozen"] is True
        assert model_type.model_config["revalidate_instances"] == "always"


def test_no_candidate_decision_exists_only_for_complete_no_match() -> None:
    no_match = dailymed_outcome(
        query_id=DM_DISCOVERY_QUERY,
        result=ResultStatus.NO_MATCH,
        count=0,
    )
    decision = LabelSelectionDecision.no_candidate_from_discovery(
        run_id=RUN_ID,
        attempt_id="attempt:00000000-0000-4000-8000-000000000012",
        acquisition_id="acquisition:dailymed-discovery",
        acquisition_ordinal=0,
        acquisition_intent_id=f"acquisition-intent:sha256:{'e' * 64}",
        candidate_set_snapshot_id="snapshot:dailymed-discovery",
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        source_outcome_id="source-outcome:dailymed-discovery",
        outcome=no_match,
        decided_at_utc=NOW,
    )
    assert decision.status is LabelSelectionStatus.NO_CANDIDATE
    assert decision.candidate_count == 0
    assert decision.selected_candidate_id is None
    assert "decided_at" not in type(decision).model_fields
    assert "decided_at_utc" in type(decision).model_fields
    with pytest.raises(ValidationError, match="authoritative discovery context"):
        LabelSelectionDecision.model_validate(
            decision.model_dump(mode="python"),
            context={
                "outcome": no_match,
                "candidates": (),
                "source_outcome_id": "source-outcome:dailymed-discovery",
                "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
            },
        )

    indeterminate = dailymed_outcome(
        query_id=DM_DISCOVERY_QUERY,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )
    with pytest.raises(ValueError):
        LabelSelectionDecision.no_candidate_from_discovery(
            run_id=RUN_ID,
            attempt_id="attempt:00000000-0000-4000-8000-000000000012",
            acquisition_id="acquisition:dailymed-discovery",
            acquisition_ordinal=0,
            acquisition_intent_id=f"acquisition-intent:sha256:{'e' * 64}",
            candidate_set_snapshot_id="snapshot:dailymed-discovery",
            discovery_manifest_id="artifact:dailymed-discovery-manifest",
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            source_outcome_id="source-outcome:dailymed-discovery",
            outcome=indeterminate,
            decided_at_utc=NOW,
        )


def dailymed_refs() -> tuple[AcquisitionOutcomeRef, AcquisitionOutcomeRef]:
    return (
        AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:dailymed-discovery",
            acquisition_intent_id=f"acquisition-intent:sha256:{'1' * 64}",
            acquisition_ordinal=0,
            operation="search",
            query_id=DM_DISCOVERY_QUERY,
            source_outcome_id="source-outcome:dailymed-discovery",
            snapshot_id="snapshot:dailymed-discovery",
        ),
        AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:dailymed-fetch",
            acquisition_intent_id=f"acquisition-intent:sha256:{'2' * 64}",
            acquisition_ordinal=1,
            operation="fetch",
            query_id=DM_FETCH_QUERY,
            source_outcome_id="source-outcome:dailymed-fetch",
            snapshot_id="snapshot:dailymed-fetch",
        ),
    )


def dailymed_fetch_attempt_section(
    refs: tuple[AcquisitionOutcomeRef, AcquisitionOutcomeRef],
) -> DailyMedLabelSectionV1:
    return DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        selection_decision_id="decision:dailymed-fetch-attempt",
        selection_status=LabelSelectionStatus.SELECTED,
        acquisition_outcome_refs=refs,
        limitations=("The selected label fetch did not produce usable evidence.",),
    )


@pytest.mark.parametrize(
    ("ref_index", "changes", "message"),
    [
        (0, {"operation": "fetch"}, "begins with exactly one discovery"),
        (1, {"operation": "search"}, "optional second DailyMed reference must be a fetch"),
        (
            1,
            {"acquisition_id": "acquisition:dailymed-discovery"},
            "acquisition IDs must be distinct",
        ),
        (
            1,
            {"snapshot_id": "snapshot:dailymed-discovery"},
            "snapshot IDs must be distinct",
        ),
        (1, {"acquisition_ordinal": 0}, "strictly greater than discovery"),
        (0, {"acquisition_ordinal": 2}, "strictly greater than discovery"),
    ],
)
def test_dailymed_fetch_requires_distinct_ordered_acquisition_identity(
    ref_index: int,
    changes: dict[str, object],
    message: str,
) -> None:
    refs = list(dailymed_refs())
    refs[ref_index] = refs[ref_index].model_copy(update=changes)

    with pytest.raises(ValidationError, match=message):
        dailymed_fetch_attempt_section((refs[0], refs[1]))


def test_dailymed_fetch_ordinal_may_be_greater_without_being_next() -> None:
    discovery_ref, fetch_ref = dailymed_refs()
    fetch_ref = fetch_ref.model_copy(
        update={
            "acquisition_ordinal": 2,
            "acquisition_intent_id": discovery_ref.acquisition_intent_id,
        }
    )
    section = dailymed_fetch_attempt_section((discovery_ref, fetch_ref))
    discovery = dailymed_outcome(query_id=DM_DISCOVERY_QUERY)
    failed_fetch = dailymed_outcome(
        query_id=DM_FETCH_QUERY,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )

    report = M1BResearchReportV1.create(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        request_id=DM_REQUEST_ID,
        scope=scope(selected_sources=(SourceType.DAILYMED,)),
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.DAILYMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(failed_fetch, discovery),
        source_sections=(section,),
        retrieved_as_of=NOW,
    )

    assert tuple(
        ref.acquisition_ordinal for ref in report.source_sections[0].acquisition_outcome_refs
    ) == (0, 2)
    assert (
        report.source_sections[0].acquisition_outcome_refs[0].acquisition_intent_id
        == report.source_sections[0].acquisition_outcome_refs[1].acquisition_intent_id
    )


def test_dailymed_acquisition_ordinals_are_unique_across_report_requests() -> None:
    first_ref, _ = dailymed_refs()
    second_query_id = "query:dailymed-discovery-2"
    second_ref = AcquisitionOutcomeRef(
        run_id=RUN_ID,
        source=SourceType.DAILYMED,
        acquisition_id="acquisition:dailymed-discovery-2",
        acquisition_intent_id=f"acquisition-intent:sha256:{'3' * 64}",
        acquisition_ordinal=first_ref.acquisition_ordinal,
        operation="search",
        query_id=second_query_id,
        source_outcome_id="source-outcome:dailymed-discovery-2",
        snapshot_id="snapshot:dailymed-discovery-2",
    )
    limitation = "Discovery was indeterminate; no authoritative label was selected."
    first_section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        acquisition_outcome_refs=(first_ref,),
        limitations=(limitation,),
    )
    second_section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=1,
        request=DailyMedSelectionRequestV1(
            drug_concept_id="drug:test",
            requested_section_codes=("43685-7",),
            selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
        ),
        acquisition_outcome_refs=(second_ref,),
        limitations=(limitation,),
    )
    first_outcome = dailymed_outcome(
        query_id=first_ref.query_id,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )
    second_outcome = dailymed_outcome(
        query_id=second_ref.query_id,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )

    with pytest.raises(ValidationError, match="ordinals must be unique"):
        M1BResearchReportV1.create(
            report_id=DM_REPORT_ID,
            run_id=RUN_ID,
            request_id=DM_REQUEST_ID,
            scope=scope(selected_sources=(SourceType.DAILYMED,)),
            source_plan=(
                M1BSourcePlanEntryV1(
                    source=SourceType.DAILYMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(first_outcome, second_outcome),
            source_sections=(first_section, second_section),
            retrieved_as_of=NOW,
        )


@pytest.mark.parametrize(
    "field",
    ("acquisition_id", "snapshot_id", "source_outcome_id"),
)
def test_dailymed_reference_primary_id_is_globally_unique_across_requests(field: str) -> None:
    report, _, _, _ = dailymed_report_for_acquisition_counts((1, 1))
    first_section, second_section = report.source_sections
    first_ref = first_section.acquisition_outcome_refs[0]
    second_ref = second_section.acquisition_outcome_refs[0]
    reused_ref = second_ref.model_copy(update={field: getattr(first_ref, field)})
    reused_section = second_section.model_copy(update={"acquisition_outcome_refs": (reused_ref,)})

    with pytest.raises(ValidationError, match=rf"{field} values must be globally unique"):
        M1BResearchReportV1.model_validate(
            {
                **report.model_dump(mode="python"),
                "source_sections": (first_section, reused_section),
            }
        )


def test_dailymed_reference_intent_may_be_reused_across_distinct_acquisitions() -> None:
    report, _, _, _ = dailymed_report_for_acquisition_counts((1, 1))
    first_section, second_section = report.source_sections
    first_ref = first_section.acquisition_outcome_refs[0]
    second_ref = second_section.acquisition_outcome_refs[0]
    reused_intent_ref = second_ref.model_copy(
        update={"acquisition_intent_id": first_ref.acquisition_intent_id}
    )
    reused_intent_section = second_section.model_copy(
        update={"acquisition_outcome_refs": (reused_intent_ref,)}
    )

    accepted = M1BResearchReportV1.model_validate(
        {
            **report.model_dump(mode="python"),
            "source_sections": (first_section, reused_intent_section),
        }
    )
    assert (
        accepted.source_sections[0].acquisition_outcome_refs[0].acquisition_intent_id
        == accepted.source_sections[1].acquisition_outcome_refs[0].acquisition_intent_id
    )


def dailymed_candidate(
    *,
    setid: str = DM_SETID,
    ordinal: int = 0,
    labeler: str = "Example labeler",
    spl_versions: tuple[str, ...] = ("3",),
    discovery_ref: AcquisitionOutcomeRef | None = None,
) -> DailyMedCandidateLabel:
    if discovery_ref is None:
        discovery_ref, _ = dailymed_refs()
    digit = str(ordinal + 6)
    return DailyMedCandidateLabel.create(
        run_id=RUN_ID,
        attempt_id="attempt:00000000-0000-4000-8000-000000000013",
        acquisition_id=discovery_ref.acquisition_id,
        acquisition_ordinal=discovery_ref.acquisition_ordinal,
        acquisition_intent_id=discovery_ref.acquisition_intent_id,
        setid=setid,
        spl_versions=spl_versions,
        ingredients=("ingredient",),
        brand_name="Brand",
        generic_name="Generic",
        application_number="APP-1",
        product_id="PRODUCT-1",
        labeler=labeler,
        dosage_forms=("tablet",),
        routes=("oral",),
        strengths=("10 mg",),
        ndcs=("00000-0000",),
        marketing_state=DailyMedMarketingState.ACTIVE,
        effective_date=None,
        published_date=None,
        available_section_codes=("34084-4",),
        discovery_query_id=discovery_ref.query_id,
        candidate_set_snapshot_id=discovery_ref.snapshot_id,
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        member_ordinal=ordinal,
        link_id=f"artifact-link:sha256:{digit * 64}",
        raw_artifact_id=f"artifact:dailymed-candidate-{ordinal}",
        raw_content_hash=f"sha256:{digit * 64}",
        candidate_ordinal=ordinal,
    )


def test_dailymed_candidate_order_resolution_and_decision_identity_are_closed() -> None:
    first = dailymed_candidate(
        setid="11111111-1111-1111-1111-111111111111",
        ordinal=0,
        labeler="A labeler",
        spl_versions=("10", "2"),
    )
    second = dailymed_candidate(
        setid="22222222-2222-2222-2222-222222222222",
        ordinal=1,
        labeler="B labeler",
        spl_versions=("2", "10"),
    )
    assert first.spl_versions == second.spl_versions == ("2", "10")
    outcome = dailymed_outcome(query_id=DM_DISCOVERY_QUERY, count=2)
    provisional_warning = LabelSelectionWarning.create(
        decision_id="decision:pending",
        code=LabelSelectionWarningCode.SELECTION_REQUIRES_REVIEW,
        message="The exact candidates differ by labeler.",
        candidate_ids=(first.candidate_id, second.candidate_id),
        differing_dimensions=(DailyMedMeaningfulDimension.LABELER_NAME,),
    )
    decision = LabelSelectionDecision.review_required_from_discovery(
        candidates=(second, first),
        outcome=outcome,
        resolution=DailyMedResolution.UNRESOLVED_NON_EQUIVALENT,
        source_outcome_id="source-outcome:dailymed-discovery",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
        warning_ids=(provisional_warning.warning_id,),
    )
    assert decision.candidate_ids == (first.candidate_id, second.candidate_id)
    assert decision.meaningful_dimensions == (DailyMedMeaningfulDimension.LABELER_NAME,)
    assert decision.status is LabelSelectionStatus.REVIEW_REQUIRED
    warning = LabelSelectionWarning.create(
        decision_id=decision.decision_id,
        code=LabelSelectionWarningCode.SELECTION_REQUIRES_REVIEW,
        message=provisional_warning.message,
        candidate_ids=provisional_warning.candidate_ids,
        differing_dimensions=provisional_warning.differing_dimensions,
    )
    assert warning.warning_id == provisional_warning.warning_id
    decision_context = {
        "discovery_outcome": outcome,
        "decision_candidates": (first, second),
        "decision_source_outcome_id": "source-outcome:dailymed-discovery",
        "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
    }
    warning.validate_against(decision, **decision_context)
    assert LabelSelectionWarning.model_validate_json(warning.model_dump_json()) == warning

    with pytest.raises(ValidationError):
        LabelSelectionWarning.model_validate(
            warning.model_copy(update={"message": "different warning"})
        )
    with pytest.raises(ValueError, match="exact decision"):
        warning.model_copy(update={"decision_id": "decision:foreign"}).validate_against(
            decision, **decision_context
        )
    for field, drift in (("message", "forged warning"), ("schema_version", "evil")):
        with pytest.raises(ValidationError):
            warning.model_copy(update={field: drift}).validate_against(decision, **decision_context)

    with pytest.raises(ValueError, match="resolution"):
        LabelSelectionDecision.from_discovery(
            candidates=(first, second),
            outcome=outcome,
            resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
            source_outcome_id="source-outcome:dailymed-discovery",
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            decided_at_utc=NOW,
        )
    with pytest.raises(ValidationError, match="authoritative discovery context"):
        LabelSelectionDecision.model_validate(decision.model_dump(mode="python"))
    with pytest.raises(ValidationError, match="decision_id"):
        LabelSelectionDecision.model_validate(
            {
                **decision.model_dump(mode="python"),
                "candidate_set_id": "candidate-set:drift",
            },
            context={
                "outcome": outcome,
                "candidates": (first, second),
                "source_outcome_id": "source-outcome:dailymed-discovery",
                "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
            },
        )


def test_partial_single_candidate_factory_always_reviews_without_pinned_exception() -> None:
    candidate = dailymed_candidate()
    outcome = dailymed_outcome(
        query_id=DM_DISCOVERY_QUERY,
        coverage=CoverageStatus.PARTIAL,
        count=1,
    )
    decision = LabelSelectionDecision.review_required_from_discovery(
        candidates=(candidate,),
        outcome=outcome,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id="source-outcome:dailymed-discovery",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
        pinned_identity=True,
    )
    assert decision.status is LabelSelectionStatus.REVIEW_REQUIRED
    assert decision.meaningful_dimensions == ()


def test_pinned_partial_review_and_pinned_complete_no_candidate_remain_admitted() -> None:
    discovery_ref, _ = dailymed_refs()
    candidate = dailymed_candidate()
    pinned_request = DailyMedSelectionRequestV1(
        drug_concept_id="drug:test",
        pinned_setid=candidate.setid,
        pinned_spl_version=max(candidate.spl_versions, key=int),
        requested_section_codes=("34084-4",),
        selection_mode=DailyMedSelectionMode.PINNED_VERSION,
    )
    report_scope = scope(selected_sources=(SourceType.DAILYMED,))

    partial = dailymed_outcome(
        query_id=discovery_ref.query_id,
        coverage=CoverageStatus.PARTIAL,
        count=1,
    )
    review_decision = LabelSelectionDecision.review_required_from_discovery(
        candidates=(candidate,),
        outcome=partial,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id=discovery_ref.source_outcome_id,
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
        pinned_identity=True,
    )
    review_section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=pinned_request,
        selection_decision_id=review_decision.decision_id,
        selection_status=LabelSelectionStatus.REVIEW_REQUIRED,
        acquisition_outcome_refs=(discovery_ref,),
        limitations=("Partial discovery requires review.",),
    )

    no_match = dailymed_outcome(
        query_id=discovery_ref.query_id,
        result=ResultStatus.NO_MATCH,
        count=0,
    )
    no_candidate_decision = LabelSelectionDecision.no_candidate_from_discovery(
        run_id=RUN_ID,
        attempt_id="attempt:00000000-0000-4000-8000-000000000013",
        acquisition_id=discovery_ref.acquisition_id,
        acquisition_ordinal=discovery_ref.acquisition_ordinal,
        acquisition_intent_id=discovery_ref.acquisition_intent_id,
        candidate_set_snapshot_id=discovery_ref.snapshot_id,
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        source_outcome_id=discovery_ref.source_outcome_id,
        outcome=no_match,
        decided_at_utc=NOW,
    )
    no_candidate_section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=pinned_request,
        selection_decision_id=no_candidate_decision.decision_id,
        selection_status=LabelSelectionStatus.NO_CANDIDATE,
        acquisition_outcome_refs=(discovery_ref,),
        limitations=("No matching label exists in complete bounded discovery.",),
    )

    for outcome, decision, decision_candidates, section in (
        (partial, review_decision, (candidate,), review_section),
        (no_match, no_candidate_decision, (), no_candidate_section),
    ):
        report = M1BResearchReportV1.create(
            report_id=DM_REPORT_ID,
            run_id=RUN_ID,
            request_id=DM_REQUEST_ID,
            scope=report_scope,
            source_plan=(
                M1BSourcePlanEntryV1(
                    source=SourceType.DAILYMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(outcome,),
            source_sections=(section,),
            retrieved_as_of=NOW,
        )
        request = M1BResearchRequestV1(
            request_id=DM_REQUEST_ID,
            scope=report_scope,
            requested_sources=(SourceType.DAILYMED,),
            dailymed_selection_requests=(pinned_request,),
        )
        report.validate_against(
            request,
            trusted_acquisition_outcomes=((pinned_request, discovery_ref, outcome),),
            trusted_selection_decisions=(
                (
                    pinned_request,
                    decision,
                    decision_candidates,
                    f"sha256:{'f' * 64}",
                ),
            ),
        )
        with pytest.raises(ValidationError, match="trusted outcome or manifest"):
            report.validate_against(
                request,
                trusted_acquisition_outcomes=((pinned_request, discovery_ref, outcome),),
                trusted_selection_decisions=(
                    (pinned_request, decision, decision_candidates, f"sha256:{'0' * 64}"),
                ),
            )


def test_label_version_identity_excludes_marketing_dates_and_artifact_fields() -> None:
    base, _ = dailymed_version_and_section()
    replay = DailyMedLabelVersion.create(
        setid=base.setid,
        spl_version=base.spl_version,
        marketing_state=DailyMedMarketingState.UNKNOWN,
        effective_date=NOW.date(),
        published_date=NOW.date(),
        content_hash=base.content_hash,
        spl_artifact_id="artifact:alternate-row-binding",
    )
    assert replay.label_version_id == base.label_version_id
    assert replay.marketing_state is DailyMedMarketingState.UNKNOWN


def test_successful_dailymed_report_requires_exact_fetch_and_locator_binding() -> None:
    version, section = dailymed_version_and_section()
    discovery = dailymed_outcome(query_id=DM_DISCOVERY_QUERY)
    fetch = dailymed_outcome(query_id=DM_FETCH_QUERY)
    discovery_ref, fetch_ref = dailymed_refs()
    candidate = dailymed_candidate()
    decision = LabelSelectionDecision.selected_from_discovery(
        candidates=(candidate,),
        outcome=discovery,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id=discovery_ref.source_outcome_id,
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
    )
    locator = DailyMedLocatorV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        acquisition_id=fetch_ref.acquisition_id,
        snapshot_id=fetch_ref.snapshot_id,
        outcome_query_id=fetch_ref.query_id,
        selection_decision_id=decision.decision_id,
        selected_candidate_id=candidate.candidate_id,
        discovery_attempt_id="attempt:00000000-0000-4000-8000-000000000013",
        discovery_acquisition_intent_id=discovery_ref.acquisition_intent_id,
        discovery_acquisition_ordinal=0,
        discovery_query_id=DM_DISCOVERY_QUERY,
        discovery_snapshot_id=discovery_ref.snapshot_id,
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        discovery_source_outcome_id=discovery_ref.source_outcome_id,
        fetch_attempt_id="attempt:00000000-0000-4000-8000-000000000014",
        setid=version.setid,
        label_version_id=version.label_version_id,
        spl_version=version.spl_version,
        fetch_acquisition_id=fetch_ref.acquisition_id,
        fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
        fetch_acquisition_ordinal=1,
        fetch_query_id=fetch_ref.query_id,
        fetch_snapshot_id=fetch_ref.snapshot_id,
        fetch_manifest_id="artifact:dailymed-fetch-manifest",
        fetch_source_outcome_id=fetch_ref.source_outcome_id,
        fetch_member_ordinal=0,
        fetch_link_id=f"artifact-link:sha256:{'5' * 64}",
        fetch_raw_artifact_id=version.spl_artifact_id,
        fetch_raw_content_hash=version.content_hash,
        stable_content_hash=version.content_hash,
        section_code=section.section_code,
        section_ordinal=section.section_ordinal,
        xml_path=section.xml_path,
        start_char=section.text_start,
        end_char=section.text_end,
        section_hash=section.text_hash,
        spl_artifact_id=version.spl_artifact_id,
    )
    retained_response = RetainedSplResponse.create(
        run_id=RUN_ID,
        acquisition_id=fetch_ref.acquisition_id,
        candidate_set_snapshot_id=discovery_ref.snapshot_id,
        selection_decision_id=locator.selection_decision_id,
        source_outcome_query_id=fetch_ref.query_id,
        setid=version.setid,
        spl_version=version.spl_version,
        media_type="application/xml",
        byte_size=12,
        content_hash=version.content_hash,
        artifact_id=version.spl_artifact_id,
        manifest_id=locator.fetch_manifest_id,
        retrieved_at=NOW,
        section_ids=(section.section_id,),
        fetch_attempt_id=locator.fetch_attempt_id,
        fetch_acquisition_id=fetch_ref.acquisition_id,
        fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
        fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
        fetch_query_id=fetch_ref.query_id,
        fetch_snapshot_id=fetch_ref.snapshot_id,
        fetch_manifest_id=locator.fetch_manifest_id,
        fetch_source_outcome_id=fetch_ref.source_outcome_id,
        fetch_member_ordinal=locator.fetch_member_ordinal,
        fetch_link_id=locator.fetch_link_id,
        fetch_raw_artifact_id=version.spl_artifact_id,
        fetch_raw_content_hash=version.content_hash,
        selected_candidate_id=locator.selected_candidate_id,
        label_version_id=version.label_version_id,
    )
    for field, drift in (
        ("schema_version", "evil"),
        ("response_id", "retained-spl-response:foreign"),
        ("media_type", "text/xml"),
        ("byte_size", 13),
        ("retrieved_at", "evil"),
    ):
        with pytest.raises(ValidationError):
            RetainedSplResponse.model_validate(retained_response.model_copy(update={field: drift}))
    for field, drift in (
        ("fetch_operation", "search"),
        ("snapshot_id", "snapshot:foreign"),
    ):
        with pytest.raises(ValidationError):
            DailyMedLocatorV1.model_validate(locator.model_copy(update={field: drift}))
    for field, drift in (
        ("operation", "evil"),
        ("snapshot_id", None),
    ):
        with pytest.raises(ValidationError):
            AcquisitionOutcomeRef.model_validate(discovery_ref.model_copy(update={field: drift}))
    assert (
        RetainedSplResponse.model_validate_json(retained_response.model_dump_json())
        == retained_response
    )
    decision_context = {
        "discovery_outcome": discovery,
        "decision_candidates": (candidate,),
        "decision_source_outcome_id": discovery_ref.source_outcome_id,
        "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
    }
    trusted_fetch_context = {
        "trusted_fetch_run_id": fetch_ref.run_id,
        "trusted_fetch_source": fetch_ref.source,
        "trusted_fetch_acquisition_id": fetch_ref.acquisition_id,
        "trusted_fetch_acquisition_intent_id": fetch_ref.acquisition_intent_id,
        "trusted_fetch_acquisition_ordinal": fetch_ref.acquisition_ordinal,
        "trusted_fetch_operation": fetch_ref.operation,
        "trusted_fetch_query_id": fetch_ref.query_id,
        "trusted_fetch_snapshot_id": fetch_ref.snapshot_id,
        "trusted_fetch_source_outcome_id": fetch_ref.source_outcome_id,
        "trusted_fetch_attempt_id": "attempt:00000000-0000-4000-8000-000000000014",
        "trusted_fetch_manifest_id": "artifact:dailymed-fetch-manifest",
        "trusted_fetch_member_ordinal": 0,
        "trusted_fetch_link_id": f"artifact-link:sha256:{'5' * 64}",
        "trusted_fetch_raw_artifact_id": version.spl_artifact_id,
        "trusted_fetch_raw_content_hash": version.content_hash,
    }
    retained_response.validate_against(
        decision=decision,
        **decision_context,
        **trusted_fetch_context,
        fetch_outcome=fetch,
        label_version=version,
        sections=(section,),
    )
    complete_retained_context = {
        "decision": decision,
        **decision_context,
        **trusted_fetch_context,
        "fetch_outcome": fetch,
        "label_version": version,
        "sections": (section,),
    }
    for required_field in trusted_fetch_context:
        incomplete = dict(complete_retained_context)
        incomplete.pop(required_field)
        with pytest.raises(TypeError, match=required_field):
            retained_response.validate_against(**incomplete)

    for field, drift in (
        ("trusted_fetch_run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("trusted_fetch_source", SourceType.PUBMED),
        ("trusted_fetch_acquisition_id", "acquisition:foreign"),
        ("trusted_fetch_acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("trusted_fetch_acquisition_ordinal", 7),
        ("trusted_fetch_operation", "search"),
        ("trusted_fetch_query_id", "query:foreign"),
        ("trusted_fetch_snapshot_id", "snapshot:foreign"),
        ("trusted_fetch_source_outcome_id", "source-outcome:foreign"),
        ("trusted_fetch_attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("trusted_fetch_manifest_id", "artifact:foreign-manifest"),
        ("trusted_fetch_member_ordinal", 7),
        ("trusted_fetch_link_id", f"artifact-link:sha256:{'7' * 64}"),
        ("trusted_fetch_raw_artifact_id", "artifact:foreign-raw"),
        ("trusted_fetch_raw_content_hash", f"sha256:{'7' * 64}"),
    ):
        altered = {**complete_retained_context, field: drift}
        with pytest.raises(ValueError, match="trusted fetch acquisition"):
            retained_response.validate_against(**altered)
    for relation_drift in (
        {"trusted_fetch_acquisition_id": decision.acquisition_id},
        {"trusted_fetch_snapshot_id": decision.candidate_set_snapshot_id},
        {"trusted_fetch_acquisition_ordinal": decision.acquisition_ordinal},
        {"trusted_fetch_acquisition_ordinal": 0},
        {
            "trusted_fetch_acquisition_id": decision.acquisition_id,
            "trusted_fetch_snapshot_id": decision.candidate_set_snapshot_id,
            "trusted_fetch_acquisition_ordinal": decision.acquisition_ordinal,
        },
    ):
        forged = retained_response.model_copy(
            update={
                "acquisition_id": relation_drift.get(
                    "trusted_fetch_acquisition_id", retained_response.acquisition_id
                ),
                "fetch_acquisition_id": relation_drift.get(
                    "trusted_fetch_acquisition_id", retained_response.fetch_acquisition_id
                ),
                "fetch_snapshot_id": relation_drift.get(
                    "trusted_fetch_snapshot_id", retained_response.fetch_snapshot_id
                ),
                "fetch_acquisition_ordinal": relation_drift.get(
                    "trusted_fetch_acquisition_ordinal",
                    retained_response.fetch_acquisition_ordinal,
                ),
            }
        )
        forged_payload = forged.model_dump(mode="python", exclude={"response_id", "retrieved_at"})
        forged = forged.model_copy(
            update={
                "response_id": derive_identity("dailymed-retained-spl-response", forged_payload)
            }
        )
        forged_context = {**complete_retained_context, **relation_drift}
        with pytest.raises(
            ValueError,
            match=r"selection discovery|discovery and fetch snapshots|fetch acquisition",
        ):
            forged.validate_against(**forged_context)
    for bad_decision in (
        decision.model_copy(update={"schema_version": "evil"}),
        decision.model_copy(update={"selected_member_ordinal": 99}),
    ):
        with pytest.raises(ValidationError):
            retained_response.validate_against(
                decision=bad_decision,
                **decision_context,
                **trusted_fetch_context,
                fetch_outcome=fetch,
                label_version=version,
                sections=(section,),
            )
    with pytest.raises(ValidationError):
        retained_response.validate_against(
            decision=decision,
            **decision_context,
            **trusted_fetch_context,
            fetch_outcome=fetch.model_copy(update={"schema_version": "evil"}),
            label_version=version,
            sections=(section,),
        )
    report_section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        selection_decision_id=locator.selection_decision_id,
        selection_status=LabelSelectionStatus.SELECTED,
        acquisition_outcome_refs=(discovery_ref, fetch_ref),
        label_version=version,
        retained_response=retained_response,
        label_sections=(section,),
        locators=(locator,),
    )
    report = M1BResearchReportV1.create(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        request_id=DM_REQUEST_ID,
        scope=scope(selected_sources=(SourceType.DAILYMED,)),
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.DAILYMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(fetch, discovery),
        source_sections=(report_section,),
        retrieved_as_of=NOW,
    )
    assert report.source_outcomes == (discovery, fetch)
    assert report.status == "draft"
    assert report.exportable is False
    assert report.safety_notice == RESEARCH_ONLY_NOTICE
    assert M1BResearchReportV1.model_validate_json(report.model_dump_json()) == report
    trusted_pairs = (
        (report_section.request, discovery_ref, discovery),
        (report_section.request, fetch_ref, fetch),
    )
    report_request = M1BResearchRequestV1(
        request_id=DM_REQUEST_ID,
        scope=report.scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(report_section.request,),
    )

    def trusted_fetch_rows(
        owner: DailyMedSelectionRequestV1,
    ) -> tuple[tuple[object, ...], ...]:
        return (
            (
                owner,
                fetch_ref,
                "attempt:00000000-0000-4000-8000-000000000014",
                "artifact:dailymed-fetch-manifest",
                0,
                f"artifact-link:sha256:{'5' * 64}",
                version.spl_artifact_id,
                version.content_hash,
            ),
        )

    report.validate_against(
        report_request,
        trusted_acquisition_outcomes=trusted_pairs,
        trusted_selection_decisions=(
            (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
        ),
        trusted_fetch_evidence=trusted_fetch_rows(report_section.request),
    )
    with pytest.raises(ValueError, match="trusted fetch evidence"):
        report.validate_against(
            report_request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
            ),
        )
    exact_fetch_row = trusted_fetch_rows(report_section.request)[0]
    for index, drift in (
        (2, "attempt:00000000-0000-4000-8000-000000000099"),
        (3, "artifact:foreign-manifest"),
        (4, 7),
        (5, f"artifact-link:sha256:{'7' * 64}"),
        (6, "artifact:foreign-raw"),
        (7, f"sha256:{'7' * 64}"),
    ):
        drifted_row = (*exact_fetch_row[:index], drift, *exact_fetch_row[index + 1 :])
        with pytest.raises(ValueError, match="trusted fetch acquisition"):
            report.validate_against(
                report_request,
                trusted_acquisition_outcomes=trusted_pairs,
                trusted_selection_decisions=(
                    (
                        report_section.request,
                        decision,
                        (candidate,),
                        f"sha256:{'f' * 64}",
                    ),
                ),
                trusted_fetch_evidence=(drifted_row,),
            )
    foreign_owner_row = (
        dailymed_matrix_request(0),
        *exact_fetch_row[1:],
    )
    with pytest.raises(ValueError, match="request-owned union"):
        report.validate_against(
            report_request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
            ),
            trusted_fetch_evidence=(foreign_owner_row,),
        )
    invalid_nested_section = section.model_copy(update={"title": "Wrong title"})
    invalid_report_section = report_section.model_copy(
        update={"label_sections": (invalid_nested_section,)}
    )
    with pytest.raises(ValidationError):
        M1BResearchReportV1.model_validate(
            report.model_copy(update={"source_sections": (invalid_report_section,)})
        )
    authoritative_locator_context = {
        "discovery_outcome": discovery,
        "decision_candidates": (candidate,),
        "decision_source_outcome_id": discovery_ref.source_outcome_id,
        "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
        "fetch_outcome": fetch,
        "label_version": version,
        "section": section,
        "decision": decision,
        **trusted_fetch_context,
        "retained_response": retained_response,
    }
    locator.validate_against(**authoritative_locator_context)
    for required_field in (
        "decision",
        "decision_candidates",
        "decision_source_outcome_id",
        "discovery_manifest_content_hash",
        *trusted_fetch_context,
    ):
        incomplete = dict(authoritative_locator_context)
        incomplete.pop(required_field)
        with pytest.raises(TypeError, match=required_field):
            locator.validate_against(**incomplete)

    for field, drift in (
        ("trusted_fetch_run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("trusted_fetch_source", SourceType.PUBMED),
        ("trusted_fetch_acquisition_id", "acquisition:foreign"),
        ("trusted_fetch_acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("trusted_fetch_acquisition_ordinal", 7),
        ("trusted_fetch_operation", "search"),
        ("trusted_fetch_query_id", "query:foreign"),
        ("trusted_fetch_snapshot_id", "snapshot:foreign"),
        ("trusted_fetch_source_outcome_id", "source-outcome:foreign"),
        ("trusted_fetch_attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("trusted_fetch_manifest_id", "artifact:foreign-manifest"),
        ("trusted_fetch_member_ordinal", 7),
        ("trusted_fetch_link_id", f"artifact-link:sha256:{'7' * 64}"),
        ("trusted_fetch_raw_artifact_id", "artifact:foreign-raw"),
        ("trusted_fetch_raw_content_hash", f"sha256:{'7' * 64}"),
    ):
        altered = {**authoritative_locator_context, field: drift}
        with pytest.raises(ValueError, match="trusted fetch acquisition"):
            locator.validate_against(**altered)
    for relation_drift in (
        {"trusted_fetch_acquisition_id": decision.acquisition_id},
        {"trusted_fetch_snapshot_id": decision.candidate_set_snapshot_id},
        {"trusted_fetch_acquisition_ordinal": decision.acquisition_ordinal},
        {"trusted_fetch_acquisition_ordinal": 0},
        {
            "trusted_fetch_acquisition_id": decision.acquisition_id,
            "trusted_fetch_snapshot_id": decision.candidate_set_snapshot_id,
            "trusted_fetch_acquisition_ordinal": decision.acquisition_ordinal,
        },
    ):
        forged = locator.model_copy(
            update={
                "acquisition_id": relation_drift.get(
                    "trusted_fetch_acquisition_id", locator.acquisition_id
                ),
                "fetch_acquisition_id": relation_drift.get(
                    "trusted_fetch_acquisition_id", locator.fetch_acquisition_id
                ),
                "snapshot_id": relation_drift.get("trusted_fetch_snapshot_id", locator.snapshot_id),
                "fetch_snapshot_id": relation_drift.get(
                    "trusted_fetch_snapshot_id", locator.fetch_snapshot_id
                ),
                "fetch_acquisition_ordinal": relation_drift.get(
                    "trusted_fetch_acquisition_ordinal", locator.fetch_acquisition_ordinal
                ),
            }
        )
        forged_context = {**authoritative_locator_context, **relation_drift}
        with pytest.raises(
            ValueError,
            match=r"selection discovery|discovery and fetch snapshots|fetch acquisition",
        ):
            forged.validate_against(**forged_context)

    for field, drift in (
        ("selection_decision_id", "decision:foreign"),
        ("selected_candidate_id", "candidate:foreign"),
        ("discovery_attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("discovery_manifest_id", "artifact:foreign-manifest"),
        ("discovery_source_outcome_id", "source-outcome:foreign"),
    ):
        with pytest.raises(ValueError, match="selection decision"):
            locator.model_copy(update={field: drift}).validate_against(
                **authoritative_locator_context
            )
    for kwargs in (
        {"decision": decision.model_copy(update={"schema_version": "evil"})},
        {"decision": decision.model_copy(update={"selected_member_ordinal": 99})},
        {"discovery_outcome": discovery.model_copy(update={"schema_version": "evil"})},
        {"fetch_outcome": fetch.model_copy(update={"schema_version": "evil"})},
    ):
        exact = {
            "discovery_outcome": discovery,
            "fetch_outcome": fetch,
            "label_version": version,
            "section": section,
            "decision": decision,
            "decision_candidates": (candidate,),
            "decision_source_outcome_id": discovery_ref.source_outcome_id,
            "discovery_manifest_content_hash": f"sha256:{'f' * 64}",
            **trusted_fetch_context,
            "retained_response": retained_response,
            **kwargs,
        }
        with pytest.raises(ValidationError):
            locator.validate_against(**exact)

    for field, drift in (
        ("run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("source", SourceType.PUBMED),
        ("status", LabelSelectionStatus.REVIEW_REQUIRED),
        ("selected_candidate_id", "candidate:foreign"),
        ("selected_setid", "33333333-3333-3333-3333-333333333333"),
        ("selected_spl_version", "9"),
        ("attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("acquisition_ordinal", 7),
        ("query_id", "query:foreign"),
        ("candidate_set_snapshot_id", "snapshot:foreign"),
        ("discovery_manifest_id", "artifact:foreign-manifest"),
        ("source_outcome_id", "source-outcome:foreign"),
    ):
        with pytest.raises(ValueError, match=r"selection decision|validation error"):
            locator.validate_against(
                discovery_outcome=discovery,
                fetch_outcome=fetch,
                label_version=version,
                section=section,
                decision=decision.model_copy(update={field: drift}),
                decision_candidates=(candidate,),
                decision_source_outcome_id=discovery_ref.source_outcome_id,
                discovery_manifest_content_hash=f"sha256:{'f' * 64}",
                **trusted_fetch_context,
            )

    for field, drift in (
        ("run_id", "run:00000000-0000-4000-8000-000000000099"),
        ("source", SourceType.PUBMED),
        ("acquisition_id", "acquisition:foreign"),
        ("candidate_set_snapshot_id", "snapshot:foreign-discovery"),
        ("selection_decision_id", "decision:foreign"),
        ("source_outcome_query_id", "query:foreign"),
        ("setid", "33333333-3333-3333-3333-333333333333"),
        ("spl_version", "9"),
        ("label_version_id", "label-version:foreign"),
        ("manifest_id", "artifact:foreign-manifest"),
        ("body_complete", False),
        ("termination_reason", "foreign"),
        ("selected_candidate_id", "candidate:foreign"),
        ("fetch_attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("fetch_acquisition_id", "acquisition:foreign"),
        ("fetch_acquisition_intent_id", f"acquisition-intent:sha256:{'8' * 64}"),
        ("fetch_acquisition_ordinal", 7),
        ("fetch_query_id", "query:foreign"),
        ("fetch_snapshot_id", "snapshot:foreign-fetch"),
        ("fetch_manifest_id", "artifact:foreign-fetch-manifest"),
        ("fetch_source_outcome_id", "source-outcome:foreign"),
        ("fetch_member_ordinal", 7),
        ("fetch_link_id", f"artifact-link:sha256:{'7' * 64}"),
        ("fetch_raw_artifact_id", "artifact:foreign"),
        ("fetch_raw_content_hash", f"sha256:{'7' * 64}"),
        ("content_hash", f"sha256:{'7' * 64}"),
        ("artifact_id", "artifact:foreign"),
    ):
        with pytest.raises(
            ValueError,
            match=r"retained response|response_id does not match|literal_error",
        ):
            locator.validate_against(
                discovery_outcome=discovery,
                fetch_outcome=fetch,
                label_version=version,
                section=section,
                decision=decision,
                decision_candidates=(candidate,),
                decision_source_outcome_id=discovery_ref.source_outcome_id,
                discovery_manifest_content_hash=f"sha256:{'f' * 64}",
                **trusted_fetch_context,
                retained_response=retained_response.model_copy(update={field: drift}),
            )

    foreign_candidate = "candidate:foreign"
    forged_retained = retained_response.model_copy(
        update={"selected_candidate_id": foreign_candidate}
    )
    forged_payload = forged_retained.model_dump(
        mode="python", exclude={"response_id", "retrieved_at"}
    )
    forged_retained = forged_retained.model_copy(
        update={"response_id": derive_identity("dailymed-retained-spl-response", forged_payload)}
    )
    with pytest.raises(
        ValueError,
        match="selection decision",
    ):
        locator.model_copy(update={"selected_candidate_id": foreign_candidate}).validate_against(
            **{
                **authoritative_locator_context,
                "retained_response": forged_retained,
            }
        )

    forged_fetch_acquisition_id = "acquisition:coherent-foreign-fetch"
    forged_fetch_retained = retained_response.model_copy(
        update={
            "acquisition_id": forged_fetch_acquisition_id,
            "fetch_acquisition_id": forged_fetch_acquisition_id,
        }
    )
    forged_fetch_payload = forged_fetch_retained.model_dump(
        mode="python", exclude={"response_id", "retrieved_at"}
    )
    forged_fetch_retained = forged_fetch_retained.model_copy(
        update={
            "response_id": derive_identity("dailymed-retained-spl-response", forged_fetch_payload)
        }
    )
    forged_fetch_locator = locator.model_copy(
        update={
            "acquisition_id": forged_fetch_acquisition_id,
            "fetch_acquisition_id": forged_fetch_acquisition_id,
        }
    )
    with pytest.raises(ValueError, match="trusted fetch acquisition"):
        forged_fetch_retained.validate_against(**complete_retained_context)
    with pytest.raises(ValueError, match="trusted fetch acquisition"):
        forged_fetch_locator.validate_against(
            **{
                **authoritative_locator_context,
                "retained_response": forged_fetch_retained,
            }
        )

    for field, drift, dependent_updates in (
        (
            "fetch_attempt_id",
            "attempt:00000000-0000-4000-8000-000000000099",
            {},
        ),
        (
            "fetch_manifest_id",
            "artifact:foreign-manifest",
            {"manifest_id": "artifact:foreign-manifest"},
        ),
        ("fetch_member_ordinal", 7, {}),
        ("fetch_link_id", f"artifact-link:sha256:{'7' * 64}", {}),
        (
            "fetch_raw_artifact_id",
            "artifact:foreign-raw",
            {"artifact_id": "artifact:foreign-raw"},
        ),
        (
            "fetch_raw_content_hash",
            f"sha256:{'7' * 64}",
            {"content_hash": f"sha256:{'7' * 64}"},
        ),
    ):
        forged_retained_row = retained_response.model_copy(
            update={field: drift, **dependent_updates}
        )
        forged_row_payload = forged_retained_row.model_dump(
            mode="python", exclude={"response_id", "retrieved_at"}
        )
        forged_retained_row = forged_retained_row.model_copy(
            update={
                "response_id": derive_identity("dailymed-retained-spl-response", forged_row_payload)
            }
        )
        forged_locator_row = locator.model_copy(update={field: drift})
        with pytest.raises(ValueError, match="trusted fetch acquisition"):
            forged_retained_row.validate_against(**complete_retained_context)
        with pytest.raises(ValueError, match="trusted fetch acquisition"):
            forged_locator_row.validate_against(
                **{
                    **authoritative_locator_context,
                    "retained_response": forged_retained_row,
                }
            )

    request = M1BResearchRequestV1(
        request_id=DM_REQUEST_ID,
        scope=report.scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(report_section.request,),
    )
    drifted_response = retained_response.model_copy(
        update={"candidate_set_snapshot_id": "snapshot:foreign-discovery"}
    )
    drifted_response_section = report_section.model_copy(
        update={"retained_response": drifted_response}
    )
    with pytest.raises(
        ValueError,
        match=r"selected discovery|discovery snapshot|response_id does not match",
    ):
        report.model_copy(update={"source_sections": (drifted_response_section,)}).validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
            ),
            trusted_fetch_evidence=trusted_fetch_rows(report_section.request),
        )

    for field, drift in (
        ("fetch_acquisition_id", "acquisition:foreign"),
        ("fetch_acquisition_intent_id", f"acquisition-intent:sha256:{'7' * 64}"),
        ("fetch_acquisition_ordinal", 7),
        ("fetch_query_id", "query:foreign"),
        ("fetch_snapshot_id", "snapshot:foreign-fetch"),
        ("fetch_source_outcome_id", "source-outcome:foreign"),
    ):
        drifted_fetch_response = retained_response.model_copy(update={field: drift})
        drifted_fetch_section = report_section.model_copy(
            update={"retained_response": drifted_fetch_response}
        )
        with pytest.raises(
            ValueError,
            match=(
                r"trusted fetch acquisition|response_id does not match|"
                r"retained response common fields"
            ),
        ):
            report.model_copy(
                update={"source_sections": (drifted_fetch_section,)}
            ).validate_against(
                request,
                trusted_acquisition_outcomes=trusted_pairs,
                trusted_selection_decisions=(
                    (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
                ),
                trusted_fetch_evidence=trusted_fetch_rows(report_section.request),
            )

    other_candidate = dailymed_candidate(labeler="Another labeler")
    assert other_candidate.setid == candidate.setid
    assert other_candidate.spl_versions == candidate.spl_versions
    assert other_candidate.candidate_id != candidate.candidate_id
    drifted_locator = locator.model_copy(
        update={"selected_candidate_id": other_candidate.candidate_id}
    )
    drifted_locator_section = report_section.model_copy(update={"locators": (drifted_locator,)})
    with pytest.raises(
        ValueError,
        match=r"selected discovery|retained response|selection decision",
    ):
        report.model_copy(update={"source_sections": (drifted_locator_section,)}).validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (report_section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
            ),
            trusted_fetch_evidence=trusted_fetch_rows(report_section.request),
        )

    drifted_decision = decision.model_copy(
        update={"selected_candidate_id": other_candidate.candidate_id}
    )
    with pytest.raises(ValueError, match=r"selected discovery|candidate binding member"):
        report.validate_against(
            request,
            trusted_acquisition_outcomes=trusted_pairs,
            trusted_selection_decisions=(
                (
                    report_section.request,
                    drifted_decision,
                    (candidate,),
                    f"sha256:{'f' * 64}",
                ),
            ),
            trusted_fetch_evidence=trusted_fetch_rows(report_section.request),
        )

    assert decision.selected_setid is not None
    assert decision.selected_spl_version is not None

    def pinned_report_context(
        *, pinned_setid: str, pinned_spl_version: str
    ) -> tuple[
        M1BResearchReportV1,
        M1BResearchRequestV1,
        DailyMedSelectionRequestV1,
    ]:
        pinned_request = DailyMedSelectionRequestV1(
            drug_concept_id=report_section.request.drug_concept_id,
            pinned_setid=pinned_setid,
            pinned_spl_version=pinned_spl_version,
            requested_section_codes=report_section.request.requested_section_codes,
            selection_mode=DailyMedSelectionMode.PINNED_VERSION,
        )
        pinned_section = report_section.model_copy(update={"request": pinned_request})
        pinned_report = M1BResearchReportV1.create(
            report_id=report.report_id,
            run_id=report.run_id,
            request_id=report.request_id,
            scope=report.scope,
            source_plan=report.source_plan,
            source_outcomes=report.source_outcomes,
            source_sections=(pinned_section,),
            retrieved_as_of=report.retrieved_as_of,
        )
        pinned_envelope = M1BResearchRequestV1(
            request_id=report.request_id,
            scope=report.scope,
            requested_sources=(SourceType.DAILYMED,),
            dailymed_selection_requests=(pinned_request,),
        )
        return pinned_report, pinned_envelope, pinned_request

    pinned_report, pinned_envelope, pinned_request = pinned_report_context(
        pinned_setid=decision.selected_setid,
        pinned_spl_version=decision.selected_spl_version,
    )
    pinned_report.validate_against(
        pinned_envelope,
        trusted_acquisition_outcomes=(
            (pinned_request, discovery_ref, discovery),
            (pinned_request, fetch_ref, fetch),
        ),
        trusted_selection_decisions=(
            (pinned_request, decision, (candidate,), f"sha256:{'f' * 64}"),
        ),
        trusted_fetch_evidence=trusted_fetch_rows(pinned_request),
    )

    for pinned_setid, pinned_spl_version in (
        ("33333333-3333-3333-3333-333333333333", decision.selected_spl_version),
        (decision.selected_setid, "9"),
    ):
        mismatched_report, mismatched_envelope, mismatched_request = pinned_report_context(
            pinned_setid=pinned_setid,
            pinned_spl_version=pinned_spl_version,
        )
        with pytest.raises(ValueError, match="exact request pin"):
            mismatched_report.validate_against(
                mismatched_envelope,
                trusted_acquisition_outcomes=(
                    (mismatched_request, discovery_ref, discovery),
                    (mismatched_request, fetch_ref, fetch),
                ),
                trusted_selection_decisions=(
                    (mismatched_request, decision, (candidate,), f"sha256:{'f' * 64}"),
                ),
                trusted_fetch_evidence=trusted_fetch_rows(mismatched_request),
            )

    for field, drift in (
        ("selection_decision_id", "decision:foreign"),
        ("discovery_acquisition_intent_id", f"acquisition-intent:sha256:{'9' * 64}"),
        ("discovery_snapshot_id", "snapshot:foreign"),
        ("discovery_source_outcome_id", "source-outcome:foreign"),
        ("fetch_acquisition_intent_id", f"acquisition-intent:sha256:{'8' * 64}"),
        ("fetch_snapshot_id", "snapshot:foreign"),
        ("fetch_source_outcome_id", "source-outcome:foreign"),
        ("fetch_manifest_id", "artifact:foreign-manifest"),
        ("fetch_raw_artifact_id", "artifact:foreign"),
        ("fetch_raw_content_hash", f"sha256:{'0' * 64}"),
    ):
        payload = deepcopy(report.model_dump(mode="python"))
        payload["source_sections"][0]["locators"][0][field] = drift
        with pytest.raises(ValidationError):
            M1BResearchReportV1.model_validate(payload)

    for field, drift in (
        ("discovery_attempt_id", "attempt:00000000-0000-4000-8000-000000000099"),
        ("discovery_manifest_id", "artifact:foreign-manifest"),
    ):
        drifted_locator = locator.model_copy(update={field: drift})
        with pytest.raises(ValueError, match="locator discovery evidence"):
            drifted_locator.validate_against(
                discovery_outcome=discovery,
                fetch_outcome=fetch,
                label_version=version,
                section=section,
                decision=decision,
                decision_candidates=(candidate,),
                decision_source_outcome_id=discovery_ref.source_outcome_id,
                discovery_manifest_content_hash=f"sha256:{'f' * 64}",
                **trusted_fetch_context,
                retained_response=retained_response,
            )

    with pytest.raises(ValidationError):
        RetainedSplResponse.model_validate(
            {
                **retained_response.model_dump(mode="python"),
                "fetch_raw_content_hash": f"sha256:{'0' * 64}",
            }
        )


def test_usable_fetch_exposes_exact_requested_section_absence() -> None:
    version, section = dailymed_version_and_section()
    discovery_ref, fetch_ref = dailymed_refs()
    retained = RetainedSplResponse.create(
        run_id=RUN_ID,
        acquisition_id=fetch_ref.acquisition_id,
        candidate_set_snapshot_id=discovery_ref.snapshot_id,
        selection_decision_id="decision:dailymed",
        source_outcome_query_id=fetch_ref.query_id,
        setid=version.setid,
        spl_version=version.spl_version,
        media_type="application/xml",
        byte_size=12,
        content_hash=version.content_hash,
        artifact_id=version.spl_artifact_id,
        manifest_id="artifact:dailymed-fetch-manifest",
        retrieved_at=NOW,
        section_ids=(section.section_id,),
        fetch_attempt_id="attempt:00000000-0000-4000-8000-000000000014",
        fetch_acquisition_id=fetch_ref.acquisition_id,
        fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
        fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
        fetch_query_id=fetch_ref.query_id,
        fetch_snapshot_id=fetch_ref.snapshot_id,
        fetch_manifest_id="artifact:dailymed-fetch-manifest",
        fetch_source_outcome_id=fetch_ref.source_outcome_id,
        fetch_member_ordinal=0,
        fetch_link_id=f"artifact-link:sha256:{'5' * 64}",
        fetch_raw_artifact_id=version.spl_artifact_id,
        fetch_raw_content_hash=version.content_hash,
        selected_candidate_id="candidate:dailymed",
        label_version_id=version.label_version_id,
    )
    request = DailyMedSelectionRequestV1(
        drug_concept_id="drug:test",
        requested_section_codes=("34084-4", "43685-7"),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )
    common = {
        "report_id": DM_REPORT_ID,
        "run_id": RUN_ID,
        "ordinal": 0,
        "request": request,
        "selection_decision_id": "decision:dailymed",
        "selection_status": LabelSelectionStatus.SELECTED,
        "acquisition_outcome_refs": (discovery_ref, fetch_ref),
        "label_version": version,
        "retained_response": retained,
        "label_sections": (section,),
    }
    with pytest.raises(ValidationError, match="section absence"):
        DailyMedLabelSectionV1(**common)
    visible = DailyMedLabelSectionV1(
        **common,
        limitations=("section_absent:43685-7",),
    )
    assert visible.locators == ()


def test_degraded_dailymed_section_forbids_stable_result_and_locator() -> None:
    discovery = dailymed_outcome(
        query_id=DM_DISCOVERY_QUERY,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )
    discovery_ref, _ = dailymed_refs()
    limitation = "Discovery was indeterminate; no authoritative label was selected."
    section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        acquisition_outcome_refs=(discovery_ref,),
        limitations=(limitation,),
    )
    report = M1BResearchReportV1.create(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        request_id=DM_REQUEST_ID,
        scope=scope(selected_sources=(SourceType.DAILYMED,)),
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.DAILYMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(discovery,),
        source_sections=(section,),
        limitations=(limitation,),
        retrieved_as_of=NOW,
    )
    assert report.source_sections[0].selection_decision_id is None
    assert report.source_sections[0].locators == ()


def test_m1b_report_allows_only_one_section_per_exact_request() -> None:
    discovery = dailymed_outcome(
        query_id=DM_DISCOVERY_QUERY,
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )
    discovery_ref, _ = dailymed_refs()
    limitation = "Discovery was indeterminate; no authoritative label was selected."
    section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        acquisition_outcome_refs=(discovery_ref,),
        limitations=(limitation,),
    )
    with pytest.raises(ValidationError, match="exactly one source section"):
        M1BResearchReportV1.create(
            report_id=DM_REPORT_ID,
            run_id=RUN_ID,
            request_id=DM_REQUEST_ID,
            scope=scope(selected_sources=(SourceType.DAILYMED,)),
            source_plan=(
                M1BSourcePlanEntryV1(
                    source=SourceType.DAILYMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(discovery,),
            source_sections=(section, section.model_copy(update={"ordinal": 1})),
            retrieved_as_of=NOW,
        )


def test_complete_single_candidate_cannot_be_review_required() -> None:
    discovery = dailymed_outcome(query_id=DM_DISCOVERY_QUERY, count=1)
    discovery_ref, _ = dailymed_refs()
    section = DailyMedLabelSectionV1(
        report_id=DM_REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=dailymed_request(),
        selection_decision_id="decision:invalid-review",
        selection_status=LabelSelectionStatus.REVIEW_REQUIRED,
        acquisition_outcome_refs=(discovery_ref,),
        limitations=("Selection requires review.",),
    )
    with pytest.raises(ValidationError, match="multiple non-equivalent"):
        M1BResearchReportV1.create(
            report_id=DM_REPORT_ID,
            run_id=RUN_ID,
            request_id=DM_REQUEST_ID,
            scope=scope(selected_sources=(SourceType.DAILYMED,)),
            source_plan=(
                M1BSourcePlanEntryV1(
                    source=SourceType.DAILYMED,
                    planning_status=PlanningStatus.SELECTED,
                ),
            ),
            source_outcomes=(discovery,),
            source_sections=(section,),
            retrieved_as_of=NOW,
        )
