"""Deterministic claim policy and draft-only report aggregate tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    RESEARCH_ONLY_NOTICE,
    AbstractSection,
    AdverseEventConcept,
    Citation,
    CitationRelationship,
    ClaimUseContext,
    ComparisonIntent,
    CorrectionContentDisposition,
    CoverageLimitation,
    CoverageStatus,
    DomainWarning,
    DrugConcept,
    EvidenceClaim,
    ExecutionBounds,
    ExecutionStatus,
    IndexingStatus,
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
    SourceOutcome,
    SourcePlanEntry,
    SourcePlanReasonCode,
    SourceType,
    derive_identity,
    sha256_digest,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


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
    return PublicationRecord.create(
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
