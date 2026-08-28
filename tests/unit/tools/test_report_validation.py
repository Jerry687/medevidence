"""Adversarial tests for the sole data-only report-validation authority."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from pathlib import Path

import pytest

import medevidence.tools.report_validation as module
from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    FAERS_MANDATORY_LIMITATIONS,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.identifiers import derive_identity
from medevidence.tools.report_validation import (
    COMPARABILITY_DIMENSIONS,
    AcquisitionInput,
    ArtifactReferenceInput,
    CanonicalReportRequest,
    CanonicalValidationError,
    CitationInput,
    CitationReferenceInput,
    CitationRelationship,
    ClaimClass,
    ClaimInclusion,
    ClaimInput,
    ClaimReferenceInput,
    ComparableFindingRelation,
    ComparisonInput,
    ConflictInput,
    ConflictOutcome,
    DimensionInput,
    EvaluatorIdentityInput,
    EvidenceInput,
    EvidenceReferenceInput,
    ExecutionBoundsInput,
    InferenceUse,
    NumericalContextInput,
    NumericalFactInput,
    QualitativeCode,
    ResolutionAction,
    ResolutionInput,
    ScopeInput,
    SemanticEvaluationInput,
    SemanticExpectationInput,
    SemanticResultInput,
    SemanticSupport,
    SourceOutcomeInput,
    StoredValidationInput,
    SynthesisInput,
    TerminalTaskInput,
    ValidationMode,
    ValidationReceipt,
    ValidationRegistryInput,
    canonical_citation_id,
    canonical_claim_id,
    canonical_evidence_id,
    canonical_numerical_text,
    canonical_report_content_hash,
    canonical_semantic_input_digest,
    canonical_validate_report,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
    verify_validation_receipt,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
FOREIGN_RUN = "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
REPORT_ID = "report:sha256:" + "b" * 64
CONTENT_HASH = "sha256:" + "c" * 64
IDENTITY = EvaluatorIdentityInput("deterministic_test", "v1")


class Provider:
    def __init__(self, result: SemanticSupport = SemanticSupport.SUPPORTED) -> None:
        self.result = result
        self.calls: list[SemanticEvaluationInput] = []

    def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput:
        self.calls.append(value)
        return SemanticResultInput(self.result, IDENTITY.method, IDENTITY.version)


class SequencedProvider:
    def __init__(self, results: tuple[SemanticSupport, ...]) -> None:
        self.results = results
        self.calls: list[SemanticEvaluationInput] = []

    def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput:
        result = self.results[len(self.calls)]
        self.calls.append(value)
        return SemanticResultInput(result, IDENTITY.method, IDENTITY.version)


def _scope(*sources: SourceType) -> ScopeInput:
    model = ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test event"),
        ),
        date_range=None,
        selected_sources=tuple(sources) or (SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=128,
            max_pages=2,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=100_000),
    )
    return ScopeInput(
        model.scope_id,
        tuple((item.concept_id, item.preferred_term) for item in model.drugs),
        tuple((item.concept_id, item.preferred_term) for item in model.adverse_reactions),
        None,
        model.selected_sources,
        model.comparison_intent,
        model.query_bounds.max_query_characters,
        model.query_bounds.max_pages,
        model.query_bounds.max_total_seconds,
        model.result_bounds.max_records,
        model.result_bounds.max_payload_bytes,
    )


def _outer_exact_max_request() -> CanonicalReportRequest:
    model = ResearchScope.create(
        drugs=tuple(
            DrugConcept(concept_id=f"rxnorm:{index}", preferred_term=f"Test drug {index}")
            for index in range(1, 5)
        ),
        adverse_reactions=tuple(
            AdverseEventConcept(
                concept_id=f"meddra:{index}",
                preferred_term=f"Test event {index}",
            )
            for index in range(1, 9)
        ),
        date_range=None,
        selected_sources=tuple(SourceType),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=128,
            max_pages=2,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=100_000),
    )
    scope = ScopeInput(
        model.scope_id,
        tuple((item.concept_id, item.preferred_term) for item in model.drugs),
        tuple((item.concept_id, item.preferred_term) for item in model.adverse_reactions),
        None,
        model.selected_sources,
        model.comparison_intent,
        model.query_bounds.max_query_characters,
        model.query_bounds.max_pages,
        model.query_bounds.max_total_seconds,
        model.result_bounds.max_records,
        model.result_bounds.max_payload_bytes,
    )
    tasks = tuple(_task(source, _outcome(source)) for source in scope.selected_sources)
    warnings = ("cadec_mandatory_limitations", "faers_mandatory_limitations")
    registry = ValidationRegistryInput(RUN_ID, scope.scope_id, (), (), (), (), IDENTITY)
    synthesis = SynthesisInput("sha256:" + "0" * 64, (), (), (), (), warnings)
    return _rebind(
        CanonicalReportRequest(
            RUN_ID,
            REPORT_ID,
            scope,
            tasks,
            synthesis,
            registry,
        )
    )


def _outcome(
    source: SourceType,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.NO_MATCH,
    *,
    warnings: tuple[str, ...] | None = None,
) -> SourceOutcomeInput:
    return SourceOutcomeInput(
        source,
        f"query:{source.value}",
        execution,
        coverage,
        result,
        ExecutionBoundsInput(128, 2, 100, 100_000, 30),
        1 if result is ResultStatus.MATCHES else 0,
        0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        coverage is CoverageStatus.PARTIAL,
        (
            warnings
            if warnings is not None
            else ()
            if coverage is CoverageStatus.COMPLETE
            else ("source_degraded",)
        ),
        "failure:test" if execution is ExecutionStatus.FAILED else None,
    )


def _evidence(
    source: SourceType,
    index: int = 0,
    *,
    facts: tuple[NumericalFactInput, ...] = (),
    excerpt: str = "",
) -> EvidenceInput:
    claim_class = (
        ClaimClass.METHODOLOGICAL_OR_LIMITATION
        if source is SourceType.CADEC
        else ClaimClass.DESCRIPTIVE
    )
    use = (
        InferenceUse.AUXILIARY_NLP_RETRIEVAL
        if source is SourceType.CADEC
        else InferenceUse.DESCRIPTIVE
    )
    value = EvidenceInput(
        "evidence:sha256:" + "0" * 64,
        RUN_ID,
        source,
        f"record:{source.value}:{index:03d}",
        "version:test",
        f"snapshot:{source.value}",
        CONTENT_HASH,
        (f"locator:{source.value}:{index:03d}",),
        frozenset({claim_class}),
        frozenset({use}),
        excerpt,
        facts,
    )
    return replace(value, evidence_id=canonical_evidence_id(value))


def _task(
    source: SourceType,
    outcome: SourceOutcomeInput,
    evidence: tuple[EvidenceInput, ...] = (),
    *,
    run_id: str = RUN_ID,
) -> TerminalTaskInput:
    return TerminalTaskInput(
        f"source-task:{RUN_ID.removeprefix('run:')}:{source.value}",
        source,
        True,
        AcquisitionInput(
            run_id,
            source,
            f"acquisition:{source.value}",
            "acquisition-intent:sha256:" + "a" * 64,
            0,
            "search",
            outcome.query_id,
            f"source-outcome:{source.value}",
            f"snapshot:{source.value}",
        ),
        outcome,
        tuple(
            EvidenceReferenceInput(
                item.evidence_id,
                item.source,
                item.snapshot_id,
                item.content_hash,
                item.locators[0],
            )
            for item in evidence
        ),
    )


def _empty_request(
    *sources: SourceType,
    outcomes: tuple[SourceOutcomeInput, ...] | None = None,
) -> CanonicalReportRequest:
    scope = _scope(*(sources or (SourceType.PUBMED,)))
    source_order = scope.selected_sources
    outcome_values = outcomes or tuple(_outcome(source) for source in source_order)
    tasks = tuple(
        _task(source, outcome) for source, outcome in zip(source_order, outcome_values, strict=True)
    )
    warnings = {warning for task in tasks for warning in task.outcome.warning_codes}
    for source in source_order:
        if source is SourceType.FAERS:
            warnings.add("faers_mandatory_limitations")
        if source is SourceType.CADEC:
            warnings.add("cadec_mandatory_limitations")
    registry = ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        (),
        (),
        (),
        (),
        IDENTITY,
    )
    synthesis = SynthesisInput(
        "sha256:" + "0" * 64,
        (),
        (),
        (),
        (),
        tuple(sorted(warnings)),
    )
    request = CanonicalReportRequest(
        RUN_ID,
        REPORT_ID,
        scope,
        tasks,
        synthesis,
        registry,
    )
    return replace(
        request,
        synthesis=replace(
            synthesis,
            report_content_hash=canonical_report_content_hash(request),
        ),
    )


def _qualitative_code(source: SourceType) -> QualitativeCode:
    return {
        SourceType.PUBMED: QualitativeCode.PUBMED_DESCRIPTIVE,
        SourceType.DAILYMED: QualitativeCode.DAILYMED_DESCRIPTIVE,
        SourceType.FAERS: QualitativeCode.FAERS_DESCRIPTIVE_CONTEXT,
        SourceType.CADEC: QualitativeCode.CADEC_AUXILIARY_CONTEXT,
    }[source]


def _qualitative_statement(source: SourceType) -> str:
    return {
        SourceType.PUBMED: "The bounded publication supplies descriptive evidence.",
        SourceType.DAILYMED: (
            "The identified label section supplies descriptive labeling evidence."
        ),
        SourceType.FAERS: (
            "The configured FAERS query supplies descriptive spontaneous-report context. "
            + FAERS_MANDATORY_LIMITATIONS[1]
        ),
        SourceType.CADEC: (
            "The approved CADEC corpus supplies auxiliary NLP and retrieval context only."
        ),
    }[source]


def _material_request(
    source: SourceType = SourceType.PUBMED,
    *,
    support: SemanticSupport = SemanticSupport.SUPPORTED,
    resolution: ResolutionAction | None = None,
    context: NumericalContextInput | None = None,
    facts: tuple[NumericalFactInput, ...] = (),
) -> CanonicalReportRequest:
    excerpt = " ".join(item.exact_text for item in facts)
    evidence = _evidence(source, facts=facts, excerpt=excerpt)
    outcome = _outcome(source, result=ResultStatus.MATCHES)
    claim_class = (
        ClaimClass.METHODOLOGICAL_OR_LIMITATION
        if source is SourceType.CADEC
        else ClaimClass.DESCRIPTIVE
    )
    use = (
        InferenceUse.AUXILIARY_NLP_RETRIEVAL
        if source is SourceType.CADEC
        else InferenceUse.DESCRIPTIVE
    )
    statement = _qualitative_statement(source)
    code: QualitativeCode | None = _qualitative_code(source)
    if context is not None:
        code = None
        statement = canonical_numerical_text(context)
        if source is SourceType.FAERS:
            statement = (
                f"FAERS bounded spontaneous-report count: {statement} "
                f"{FAERS_MANDATORY_LIMITATIONS[1]}"
            )
    limitations = (
        tuple(FAERS_MANDATORY_LIMITATIONS)
        if source is SourceType.FAERS
        else tuple(CADEC_MANDATORY_LIMITATIONS)
        if source is SourceType.CADEC
        else ()
    )
    claim = ClaimInput(
        "claim:sha256:" + "0" * 64,
        source,
        code,
        statement,
        claim_class,
        use,
        (),
        limitations,
        ClaimInclusion.FORMAL,
        context,
    )
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    citation = CitationInput(
        "citation:sha256:" + "0" * 64,
        claim.claim_id,
        evidence.evidence_id,
        CitationRelationship.SUPPORTS,
        evidence.source_record_id,
        evidence.source_version,
        evidence.snapshot_id,
        evidence.content_hash,
        evidence.locators[0],
        outcome.execution_status,
        outcome.coverage_status,
        outcome.result_status,
    )
    citation = replace(citation, citation_id=canonical_citation_id(citation))
    claim = replace(claim, citation_ids=(citation.citation_id,))
    expectation = SemanticExpectationInput(
        citation.citation_id,
        canonical_semantic_input_digest(RUN_ID, claim, citation, evidence),
        IDENTITY.method,
        IDENTITY.version,
        support,
    )
    resolutions = (
        ()
        if resolution is None
        else (
            ResolutionInput(
                claim.claim_id,
                resolution,
                "review:resolution",
                "human_review",
                "v1",
            ),
        )
    )
    scope = _scope(source)
    registry = ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        (claim,),
        (citation,),
        (evidence,),
        (expectation,),
        IDENTITY,
        resolutions=resolutions,
    )
    warnings = (
        ("faers_mandatory_limitations",)
        if source is SourceType.FAERS
        else ("cadec_mandatory_limitations",)
        if source is SourceType.CADEC
        else ()
    )
    synthesis = SynthesisInput(
        "sha256:" + "0" * 64,
        (ClaimReferenceInput(claim.claim_id),),
        (CitationReferenceInput(citation.citation_id, claim.claim_id, evidence.evidence_id),),
        (),
        (),
        warnings,
    )
    request = CanonicalReportRequest(
        RUN_ID,
        REPORT_ID,
        scope,
        (_task(source, outcome, (evidence,)),),
        synthesis,
        registry,
    )
    return replace(
        request,
        synthesis=replace(
            synthesis,
            report_content_hash=canonical_report_content_hash(request),
        ),
    )


def _relationship_request(
    relationships: tuple[CitationRelationship, ...],
    results: tuple[SemanticSupport, ...],
    *,
    adjudicate: bool = False,
    resolution_binding: tuple[str | None, str | None] = (None, None),
) -> CanonicalReportRequest:
    assert len(relationships) == len(results)
    evidence = tuple(_evidence(SourceType.PUBMED, index) for index in range(len(results)))
    outcome = _outcome(SourceType.PUBMED, result=ResultStatus.MATCHES)
    claim = ClaimInput(
        "claim:sha256:" + "0" * 64,
        SourceType.PUBMED,
        QualitativeCode.PUBMED_DESCRIPTIVE,
        _qualitative_statement(SourceType.PUBMED),
        ClaimClass.DESCRIPTIVE,
        InferenceUse.DESCRIPTIVE,
        (),
        (),
        ClaimInclusion.FORMAL,
        None,
    )
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    citations = tuple(
        replace(
            citation,
            citation_id=canonical_citation_id(citation),
        )
        for item, relationship in zip(evidence, relationships, strict=True)
        for citation in (
            CitationInput(
                "citation:sha256:" + "0" * 64,
                claim.claim_id,
                item.evidence_id,
                relationship,
                item.source_record_id,
                item.source_version,
                item.snapshot_id,
                item.content_hash,
                item.locators[0],
                outcome.execution_status,
                outcome.coverage_status,
                outcome.result_status,
            ),
        )
    )
    claim = replace(claim, citation_ids=tuple(item.citation_id for item in citations))
    expectations = tuple(
        SemanticExpectationInput(
            citation.citation_id,
            canonical_semantic_input_digest(RUN_ID, claim, citation, item),
            IDENTITY.method,
            IDENTITY.version,
            result,
        )
        for item, citation, result in zip(evidence, citations, results, strict=True)
    )
    resolutions = (
        (
            ResolutionInput(
                claim.claim_id,
                ResolutionAction.ADJUDICATED_TO_SUPPORTED,
                "review:relationship-adjudication",
                "human_review",
                "v1",
                resolution_binding[0],
                resolution_binding[1],
            ),
        )
        if adjudicate
        else ()
    )
    scope = _scope(SourceType.PUBMED)
    registry = ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        (claim,),
        citations,
        evidence,
        expectations,
        IDENTITY,
        resolutions=resolutions,
    )
    synthesis = SynthesisInput(
        "sha256:" + "0" * 64,
        (ClaimReferenceInput(claim.claim_id),),
        tuple(
            CitationReferenceInput(item.citation_id, item.claim_id, item.evidence_id)
            for item in citations
        ),
        (),
        (),
        (),
    )
    return _rebind(
        CanonicalReportRequest(
            RUN_ID,
            REPORT_ID,
            scope,
            (_task(SourceType.PUBMED, outcome, evidence),),
            synthesis,
            registry,
        )
    )


def _stored(audit: object) -> StoredValidationInput:
    summary = audit.summary
    return StoredValidationInput(
        summary.structural_passed,
        summary.semantic_passed,
        summary.safety_passed,
        summary.reason_codes,
    )


def _assess(
    request: CanonicalReportRequest,
    provider: Provider | None = None,
) -> tuple[object, Provider]:
    evaluator = provider or Provider()
    return (
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=evaluator,
        ),
        evaluator,
    )


def _rebind(request: CanonicalReportRequest) -> CanonicalReportRequest:
    return replace(
        request,
        synthesis=replace(
            request.synthesis,
            report_content_hash=canonical_report_content_hash(request),
        ),
    )


def _retie_single_material_graph(
    request: CanonicalReportRequest,
    *,
    claim: ClaimInput | None = None,
    evidence: EvidenceInput | None = None,
    outcome: SourceOutcomeInput | None = None,
) -> CanonicalReportRequest:
    """Rebuild the one-claim fixture after an authorized primitive mutation."""
    evidence = evidence or request.registry.evidence[0]
    evidence = replace(evidence, evidence_id=canonical_evidence_id(evidence))
    claim = claim or request.registry.claims[0]
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    outcome = outcome or request.tasks[0].outcome
    original_citation = request.registry.citations[0]
    citation = replace(
        original_citation,
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        source_record_id=evidence.source_record_id,
        source_version=evidence.source_version,
        snapshot_id=evidence.snapshot_id,
        content_hash=evidence.content_hash,
        locator_ref=evidence.locators[0],
        execution_status=outcome.execution_status,
        coverage_status=outcome.coverage_status,
        result_status=outcome.result_status,
    )
    citation = replace(citation, citation_id=canonical_citation_id(citation))
    claim = replace(claim, citation_ids=(citation.citation_id,))
    expectation = SemanticExpectationInput(
        citation.citation_id,
        canonical_semantic_input_digest(RUN_ID, claim, citation, evidence),
        IDENTITY.method,
        IDENTITY.version,
        request.registry.semantic_expectations[0].result,
    )
    registry = replace(
        request.registry,
        claims=(claim,),
        citations=(citation,),
        evidence=(evidence,),
        semantic_expectations=(expectation,),
    )
    synthesis = replace(
        request.synthesis,
        claims=(ClaimReferenceInput(claim.claim_id),),
        citations=(
            CitationReferenceInput(citation.citation_id, claim.claim_id, evidence.evidence_id),
        ),
    )
    rebuilt = replace(
        request,
        tasks=(_task(evidence.source, outcome, (evidence,)),),
        registry=registry,
        synthesis=synthesis,
    )
    return _rebind(rebuilt)


def _assert_rejected(request: CanonicalReportRequest) -> None:
    provider = Provider()
    try:
        audit = canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    except (CanonicalValidationError, ValueError, TypeError):
        assert provider.calls == []
        return
    assert not audit.summary.passed
    assert provider.calls == []


def test_empty_no_match_assess_and_pure_verify_pass() -> None:
    request = _empty_request()
    audit, provider = _assess(request)
    assert audit.summary.passed and audit.summary.reason_codes == ()
    verified = canonical_validate_report(
        replace(request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary
    assert provider.calls == []


@pytest.mark.parametrize(
    ("support", "resolution", "passed"),
    [
        (SemanticSupport.SUPPORTED, None, True),
        (
            SemanticSupport.UNCERTAIN,
            ResolutionAction.ADJUDICATED_TO_SUPPORTED,
            True,
        ),
        (SemanticSupport.UNSUPPORTED, None, False),
    ],
)
def test_closed_semantic_resolution(
    support: SemanticSupport,
    resolution: ResolutionAction | None,
    passed: bool,
) -> None:
    request = _material_request(support=support, resolution=resolution)
    audit, provider = _assess(request, Provider(support))
    assert audit.summary.passed is passed
    assert audit.claims[0].formal_claim_accepted is passed
    assert len(audit.claims[0].citation_traces) == 1
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("execution", "coverage", "result"),
    [
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
        (
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.PARTIAL,
            ResultStatus.INDETERMINATE,
        ),
        (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
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
    ],
)
def test_all_seven_terminal_outcome_triples(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> None:
    request = _empty_request(
        SourceType.PUBMED,
        outcomes=(_outcome(SourceType.PUBMED, execution, coverage, result),),
    )
    audit, provider = _assess(request)
    assert audit.summary.passed
    assert provider.calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"execution_status": ExecutionStatus.FAILED, "failure_id": "failure:test"},
        {"coverage_status": CoverageStatus.PARTIAL, "warning_codes": ()},
        {"result_status": ResultStatus.NO_MATCH, "valid_result_count": 1},
        {"result_status": ResultStatus.MATCHES, "valid_result_count": 0},
    ],
)
def test_invalid_outcome_and_no_match_semantics(mutation: dict[str, object]) -> None:
    request = _empty_request()
    task = request.tasks[0]
    object.__setattr__(task.outcome, next(iter(mutation)), next(iter(mutation.values())))
    for key, value in tuple(mutation.items())[1:]:
        object.__setattr__(task.outcome, key, value)
    with pytest.raises(CanonicalValidationError):
        canonical_validate_report(request, mode=ValidationMode.ASSESS)


def test_foreign_run_zero_evidence_no_match_fails() -> None:
    request = _empty_request()
    task = request.tasks[0]
    task = replace(task, acquisition=replace(task.acquisition, run_id=FOREIGN_RUN))
    request = replace(request, tasks=(task,))
    audit, provider = _assess(request)
    assert not audit.summary.passed
    assert "source_not_in_authorized_run" in audit.summary.reason_codes
    assert provider.calls == []


@pytest.mark.parametrize("attack", ["missing", "extra", "duplicate", "nonterminal"])
def test_selected_source_task_equality(attack: str) -> None:
    request = _empty_request(SourceType.PUBMED, SourceType.DAILYMED)
    tasks = request.tasks
    if attack == "missing":
        tasks = tasks[:1]
    elif attack == "extra":
        tasks = (*tasks, tasks[-1])
    elif attack == "duplicate":
        tasks = (tasks[0], tasks[0])
    else:
        tasks = (replace(tasks[0], terminal=False), tasks[1])
    _assert_rejected(replace(request, tasks=tasks))


@pytest.mark.parametrize(
    "target",
    ["source", "version", "snapshot", "hash", "locator", "record"],
)
def test_evidence_citation_lineage_drift(target: str) -> None:
    request = _material_request()
    citation = request.registry.citations[0]
    evidence = request.registry.evidence[0]
    if target == "source":
        evidence = replace(evidence, source=SourceType.DAILYMED)
    elif target == "version":
        citation = replace(citation, source_version="version:foreign")
    elif target == "snapshot":
        citation = replace(citation, snapshot_id="snapshot:foreign")
    elif target == "hash":
        citation = replace(citation, content_hash="sha256:" + "d" * 64)
    elif target == "locator":
        citation = replace(citation, locator_ref="locator:foreign")
    else:
        citation = replace(citation, source_record_id="record:foreign")
    registry = replace(request.registry, evidence=(evidence,), citations=(citation,))
    _assert_rejected(replace(request, registry=registry))


@pytest.mark.parametrize("source", [SourceType.FAERS, SourceType.CADEC])
def test_source_warning_is_required_even_without_evidence_or_claims(source: SourceType) -> None:
    request = _empty_request(source)
    audit, provider = _assess(request)
    assert audit.summary.passed and provider.calls == []
    request = replace(
        request,
        synthesis=replace(request.synthesis, warning_codes=()),
    )
    request = _rebind(request)
    failed, provider = _assess(request)
    assert not failed.summary.passed
    assert "mandatory_coverage_warning_missing" in failed.summary.reason_codes
    assert provider.calls == []


@pytest.mark.parametrize(
    "warning",
    ["", "Upper", "_bad", "bad-value", "a" * 129],
)
def test_warning_grammar_fails_before_stage1(warning: str) -> None:
    request = _empty_request()
    object.__setattr__(request.synthesis, "warning_codes", (warning,))
    with pytest.raises(CanonicalValidationError, match="synthesis_warning_invalid"):
        canonical_validate_report(request, mode=ValidationMode.ASSESS)


@pytest.mark.parametrize(
    "field", ["unit", "denominator", "comparator", "time_basis", "population_scope"]
)
def test_faers_numerical_reconstruction_is_exact(field: str) -> None:
    context = NumericalContextInput(
        "7",
        "provider_count_occurrence",
        "no exposure denominator",
        "no product comparator",
        "configured query window",
        "bounded FAERS spontaneous reports",
    )
    fact = NumericalFactInput(
        "locator:faers:000",
        "",
        *tuple(getattr(context, item.name) for item in fields(context)),
    )
    fact = replace(fact, exact_text=canonical_numerical_text(fact))
    request = _material_request(SourceType.FAERS, context=context, facts=(fact,))
    audit, _ = _assess(request)
    assert audit.summary.passed
    bad = replace(context, **{field: "forged"})
    claim = request.registry.claims[0]
    claim = replace(claim, numerical_context=bad)
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    _assert_rejected(replace(request, registry=replace(request.registry, claims=(claim,))))


def test_cadec_numerical_claim_and_fact_are_forbidden() -> None:
    context = NumericalContextInput("1", "count", "none", "none", "window", "corpus")
    with pytest.raises(CanonicalValidationError, match="cadec_numerical_claim_forbidden"):
        canonical_validate_report(
            _material_request(SourceType.CADEC, context=context),
            mode=ValidationMode.ASSESS,
        )
    fact = NumericalFactInput(
        "locator:cadec:000",
        "",
        "1",
        "count",
        "none",
        "none",
        "window",
        "corpus",
    )
    fact = replace(fact, exact_text=canonical_numerical_text(fact))
    with pytest.raises(CanonicalValidationError, match="cadec_numerical_fact_forbidden"):
        canonical_validate_report(
            _material_request(SourceType.CADEC, facts=(fact,)),
            mode=ValidationMode.ASSESS,
        )


def test_global_stage1_barrier_and_evaluator_identity() -> None:
    request = _material_request()
    expectation = replace(
        request.registry.semantic_expectations[0],
        input_digest="sha256:" + "d" * 64,
    )
    request = replace(
        request,
        registry=replace(request.registry, semantic_expectations=(expectation,)),
    )
    request = _rebind(request)
    provider = Provider()
    audit, provider = _assess(request, provider)
    assert not audit.summary.passed
    assert "semantic_expectation_binding_drift" in audit.summary.reason_codes
    assert provider.calls == []


def _comparison(
    outcome: ConflictOutcome,
    *,
    index: int = 0,
) -> tuple[ComparisonInput, ConflictInput]:
    unavailable = outcome is ConflictOutcome.SOURCE_UNAVAILABLE
    insufficient = outcome is ConflictOutcome.INSUFFICIENT_INFORMATION
    mismatch = outcome is ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH
    unresolved = outcome is ConflictOutcome.UNRESOLVED_CONFLICT_COMPARABLE_SCOPE
    dimensions = tuple(
        DimensionInput(
            dimension,
            not insufficient,
            None if insufficient else "left",
            None if insufficient else "right" if mismatch and position == 0 else "left",
        )
        for position, dimension in enumerate(COMPARABILITY_DIMENSIONS)
    )
    comparison = ComparisonInput(
        f"comparison:{index:03d}",
        "sha256:" + "0" * 64,
        dimensions,
        (
            ComparableFindingRelation.CONFLICTING
            if unresolved
            else ComparableFindingRelation.CONSISTENT
        ),
        unavailable,
    )
    comparison = replace(comparison, artifact_hash=module._comparison_hash(comparison))
    conflict = ConflictInput(
        f"conflict:{index:03d}",
        "sha256:" + "0" * 64,
        comparison.comparison_id,
        outcome,
    )
    return comparison, replace(conflict, artifact_hash=module._conflict_hash(conflict))


def _with_comparison_graph(
    request: CanonicalReportRequest,
    *outcomes: ConflictOutcome,
) -> tuple[
    CanonicalReportRequest,
    tuple[ComparisonInput, ...],
    tuple[ConflictInput, ...],
]:
    pairs = tuple(_comparison(outcome, index=index) for index, outcome in enumerate(outcomes))
    comparisons = tuple(item[0] for item in pairs)
    conflicts = tuple(item[1] for item in pairs)
    registry = replace(
        request.registry,
        comparisons=comparisons,
        conflicts=conflicts,
    )
    synthesis = replace(
        request.synthesis,
        comparison_refs=tuple(
            ArtifactReferenceInput(item.comparison_id, item.artifact_hash) for item in comparisons
        ),
        conflict_refs=tuple(
            ArtifactReferenceInput(item.conflict_id, item.artifact_hash) for item in conflicts
        ),
    )
    return _rebind(replace(request, registry=registry, synthesis=synthesis)), comparisons, conflicts


def _bind_relationship_resolution(
    request: CanonicalReportRequest,
    comparison_id: str | None,
    conflict_id: str | None,
) -> CanonicalReportRequest:
    assert len(request.registry.resolutions) == 1
    resolution = replace(
        request.registry.resolutions[0],
        comparison_id=comparison_id,
        conflict_id=conflict_id,
    )
    return _rebind(
        replace(
            request,
            registry=replace(request.registry, resolutions=(resolution,)),
        )
    )


@pytest.mark.parametrize("outcome", list(ConflictOutcome))
def test_all_dimensions_and_conflict_outcomes(outcome: ConflictOutcome) -> None:
    comparison, conflict = _comparison(outcome)
    request = _empty_request()
    registry = replace(
        request.registry,
        comparisons=(comparison,),
        conflicts=(conflict,),
    )
    synthesis = replace(
        request.synthesis,
        comparison_refs=(
            ArtifactReferenceInput(comparison.comparison_id, comparison.artifact_hash),
        ),
        conflict_refs=(ArtifactReferenceInput(conflict.conflict_id, conflict.artifact_hash),),
    )
    request = _rebind(replace(request, registry=registry, synthesis=synthesis))
    audit, provider = _assess(request)
    assert audit.summary.passed
    assert audit.conflict_outcomes == ((conflict.conflict_id, outcome),)
    assert provider.calls == []


@pytest.mark.parametrize("target", ["run", "scope", "report_hash", "report_id"])
def test_report_scope_and_hash_bindings(target: str) -> None:
    request = _empty_request()
    if target == "run":
        request = replace(request, run_id=FOREIGN_RUN)
    elif target == "scope":
        request = replace(
            request, scope=replace(request.scope, scope_id="scope:sha256:" + "d" * 64)
        )
    elif target == "report_hash":
        request = replace(
            request, synthesis=replace(request.synthesis, report_content_hash="sha256:" + "d" * 64)
        )
    else:
        request = replace(request, report_id="report:bad")
    _assert_rejected(request)


def test_mutation_and_exact_runtime_base_types_are_reconstructed() -> None:
    request = _empty_request()
    audit, _ = _assess(request)
    assert audit.summary.passed
    object.__setattr__(request.tasks[0].acquisition, "run_id", FOREIGN_RUN)
    failed, _ = _assess(request)
    assert not failed.summary.passed
    evil = type("EvilTask", (TerminalTaskInput,), {"__post_init__": lambda self: None})
    task = evil(
        **{item.name: getattr(request.tasks[0], item.name) for item in fields(TerminalTaskInput)}
    )
    with pytest.raises(CanonicalValidationError, match="task_wrong_type"):
        canonical_validate_report(replace(request, tasks=(task,)), mode=ValidationMode.ASSESS)


@pytest.mark.parametrize("target", ["claim", "evidence", "comparison"])
def test_nested_registry_subclasses_fail_after_cardinality_precheck(target: str) -> None:
    request = _material_request()
    if target == "claim":
        base = request.registry.claims[0]
    elif target == "evidence":
        base = request.registry.evidence[0]
    else:
        base = _comparison(ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE)[0]
    evil_type = type(
        f"Evil{type(base).__name__}",
        (type(base),),
        {"__post_init__": lambda self: None},
    )
    evil = evil_type(**{item.name: getattr(base, item.name) for item in fields(type(base))})
    if target == "claim":
        registry = replace(request.registry, claims=(evil,))
        code = "claim_wrong_type"
    elif target == "evidence":
        registry = replace(request.registry, evidence=(evil,))
        code = "evidence_wrong_type"
    else:
        registry = replace(request.registry, comparisons=(evil,))
        code = "comparison_wrong_type"
    _expect_code(
        replace(request, registry=registry),
        code,
    )


def test_pure_verify_reproduces_reasons_and_never_calls_provider() -> None:
    request = _material_request(support=SemanticSupport.UNSUPPORTED)
    audit, provider = _assess(request, Provider(SemanticSupport.UNSUPPORTED))
    assert not audit.summary.passed and len(provider.calls) == 1
    verified = canonical_validate_report(
        replace(request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary
    assert len(provider.calls) == 1
    with pytest.raises(CanonicalValidationError, match="semantic_provider_forbidden_in_verify"):
        canonical_validate_report(
            replace(request, stored_validation=_stored(audit)),
            mode=ValidationMode.VERIFY_BINDING,
            semantic_result_provider=Provider(),
        )


def _maximum_request() -> CanonicalReportRequest:
    scope = _scope(*tuple(SourceType))
    evidence_by_source = {
        source: tuple(_evidence(source, index) for index in range(100))
        for source in scope.selected_sources
    }
    tasks = tuple(
        _task(source, _outcome(source, result=ResultStatus.MATCHES), evidence_by_source[source])
        for source in scope.selected_sources
    )
    evidence = tuple(
        item for source in scope.selected_sources for item in evidence_by_source[source]
    )
    publication = evidence_by_source[SourceType.PUBMED][0]
    claims: list[ClaimInput] = []
    citations: list[CitationInput] = []
    expectations: list[SemanticExpectationInput] = []
    resolutions: list[ResolutionInput] = []
    for index in range(200):
        limitations = (f"Boundary limitation {index:03d}.",)
        claim = ClaimInput(
            "claim:sha256:" + "0" * 64,
            SourceType.PUBMED,
            QualitativeCode.PUBMED_DESCRIPTIVE,
            _qualitative_statement(SourceType.PUBMED),
            ClaimClass.DESCRIPTIVE,
            InferenceUse.DESCRIPTIVE,
            (),
            limitations,
            ClaimInclusion.FORMAL,
            None,
        )
        claim = replace(claim, claim_id=canonical_claim_id(claim))
        claim_citations = []
        for relationship in (
            CitationRelationship.SUPPORTS,
            CitationRelationship.CONTEXT_ONLY,
        ):
            citation = CitationInput(
                "citation:sha256:" + "0" * 64,
                claim.claim_id,
                publication.evidence_id,
                relationship,
                publication.source_record_id,
                publication.source_version,
                publication.snapshot_id,
                publication.content_hash,
                publication.locators[0],
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.MATCHES,
            )
            claim_citations.append(replace(citation, citation_id=canonical_citation_id(citation)))
        claim = replace(claim, citation_ids=tuple(item.citation_id for item in claim_citations))
        claims.append(claim)
        citations.extend(claim_citations)
        expectations.extend(
            SemanticExpectationInput(
                item.citation_id,
                canonical_semantic_input_digest(RUN_ID, claim, item, publication),
                IDENTITY.method,
                IDENTITY.version,
                SemanticSupport.UNCERTAIN,
            )
            for item in claim_citations
        )
        resolutions.append(
            ResolutionInput(
                claim.claim_id,
                ResolutionAction.ADJUDICATED_TO_SUPPORTED,
                f"review:{index:03d}",
                "human_review",
                "v1",
            )
        )
    pairs = tuple(
        _comparison(ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE, index=index)
        for index in range(100)
    )
    registry = ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        tuple(claims),
        tuple(citations),
        evidence,
        tuple(expectations),
        IDENTITY,
        tuple(item[0] for item in pairs),
        tuple(item[1] for item in pairs),
        tuple(resolutions),
    )
    synthesis = SynthesisInput(
        "sha256:" + "0" * 64,
        tuple(ClaimReferenceInput(item.claim_id) for item in claims),
        tuple(
            CitationReferenceInput(item.citation_id, item.claim_id, item.evidence_id)
            for item in citations
        ),
        tuple(
            ArtifactReferenceInput(item.comparison_id, item.artifact_hash)
            for item in registry.comparisons
        ),
        tuple(
            ArtifactReferenceInput(item.conflict_id, item.artifact_hash)
            for item in registry.conflicts
        ),
        ("cadec_mandatory_limitations", "faers_mandatory_limitations"),
    )
    request = CanonicalReportRequest(RUN_ID, REPORT_ID, scope, tasks, synthesis, registry)
    return _rebind(request)


@pytest.fixture(scope="module")
def maximum_request() -> CanonicalReportRequest:
    return _maximum_request()


def test_exact_maximum_graph_passes(maximum_request: CanonicalReportRequest) -> None:
    provider = Provider(SemanticSupport.UNCERTAIN)
    audit, provider = _assess(maximum_request, provider)
    assert audit.summary.passed and audit.summary.reason_codes == ()
    assert len(audit.claims) == 200 and all(item.formal_claim_accepted for item in audit.claims)
    assert len(provider.calls) == 400
    verified = canonical_validate_report(
        replace(maximum_request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary.passed


_BOUNDARIES = (
    ("task", "evidence_refs", "task_evidence_cardinality_exceeded"),
    ("synthesis", "claims", "synthesis_claim_cardinality_exceeded"),
    ("synthesis", "citations", "synthesis_citation_cardinality_exceeded"),
    ("synthesis", "comparison_refs", "synthesis_comparison_cardinality_exceeded"),
    ("synthesis", "conflict_refs", "synthesis_conflict_cardinality_exceeded"),
    ("registry", "claims", "registry_claim_cardinality_exceeded"),
    ("registry", "citations", "registry_citation_cardinality_exceeded"),
    ("registry", "evidence", "registry_evidence_cardinality_exceeded"),
    (
        "registry",
        "semantic_expectations",
        "registry_semantic_expectation_cardinality_exceeded",
    ),
    ("registry", "resolutions", "registry_resolution_cardinality_exceeded"),
    ("registry", "comparisons", "registry_comparison_cardinality_exceeded"),
    ("registry", "conflicts", "registry_conflict_cardinality_exceeded"),
)


@pytest.mark.parametrize(("owner", "field", "code"), _BOUNDARIES)
def test_max_plus_one_has_specific_cardinality_error(
    maximum_request: CanonicalReportRequest,
    owner: str,
    field: str,
    code: str,
) -> None:
    container = (
        maximum_request.tasks[0]
        if owner == "task"
        else maximum_request.synthesis
        if owner == "synthesis"
        else maximum_request.registry
    )
    values = getattr(container, field)
    attacked = replace(container)
    object.__setattr__(attacked, field, (*values, values[-1]))
    request = (
        replace(maximum_request, tasks=(attacked, *maximum_request.tasks[1:]))
        if owner == "task"
        else replace(maximum_request, synthesis=attacked)
        if owner == "synthesis"
        else replace(maximum_request, registry=attacked)
    )
    provider = Provider(SemanticSupport.UNCERTAIN)
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    assert captured.value.code == code
    assert provider.calls == []


def test_warning_100_passes_and_101_fails() -> None:
    warnings = tuple(f"warning_{index:03d}" for index in range(100))
    request = _empty_request(
        SourceType.PUBMED,
        outcomes=(_outcome(SourceType.PUBMED, warnings=warnings),),
    )
    audit, provider = _assess(request)
    assert audit.summary.passed and provider.calls == []
    attacked = replace(request.synthesis)
    object.__setattr__(attacked, "warning_codes", (*warnings, "warning_100"))
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(request, synthesis=attacked),
            mode=ValidationMode.ASSESS,
        )
    assert captured.value.code == "synthesis_warning_cardinality_exceeded"


def _expect_code(request: CanonicalReportRequest, code: str) -> None:
    provider = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    assert captured.value.code == code
    assert provider.calls == []


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("collections", "scope_collection_wrong_type"),
        ("concept", "scope_concept_wrong_type"),
        ("date_shape", "scope_date_invalid"),
        ("date_value", "scope_date_invalid"),
        ("sources", "scope_sources_wrong_type"),
        ("source_member", "scope_sources_wrong_type"),
    ],
)
def test_scope_reconstruction_defenses(target: str, code: str) -> None:
    request = _empty_request()
    scope = replace(request.scope)
    if target == "collections":
        object.__setattr__(scope, "drugs", [])
    elif target == "concept":
        object.__setattr__(scope, "drugs", (("only-one",),))
    elif target == "date_shape":
        object.__setattr__(scope, "date_range", ("2026-01-01",))
    elif target == "date_value":
        object.__setattr__(scope, "date_range", ("invalid", "2026-01-01"))
    elif target == "sources":
        object.__setattr__(scope, "selected_sources", [SourceType.PUBMED])
    else:
        object.__setattr__(
            scope,
            "selected_sources",
            (SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS, object()),
        )
    _expect_code(replace(request, scope=scope), code)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"valid_result_count": "1"}, "outcome_primitive_wrong_type"),
        ({"valid_result_count": 101}, "outcome_bounds_invalid"),
        ({"truncated": True}, "outcome_complete_truncated"),
        (
            {
                "execution_status": ExecutionStatus.FAILED,
                "coverage_status": CoverageStatus.UNAVAILABLE,
                "result_status": ResultStatus.INDETERMINATE,
                "pages_completed": 1,
                "warning_codes": ("source_degraded",),
                "failure_id": "failure:test",
            },
            "outcome_unavailable_has_results",
        ),
        (
            {
                "coverage_status": CoverageStatus.PARTIAL,
                "result_status": ResultStatus.INDETERMINATE,
                "warning_codes": (),
            },
            "outcome_degradation_warning_missing",
        ),
        ({"failure_id": "failure:unexpected"}, "outcome_failure_identity_invalid"),
    ],
)
def test_outcome_reconstruction_defenses(changes: dict[str, object], code: str) -> None:
    request = _empty_request()
    outcome = replace(request.tasks[0].outcome)
    for field, value in changes.items():
        object.__setattr__(outcome, field, value)
    task = replace(request.tasks[0], outcome=outcome)
    _expect_code(replace(request, tasks=(task,)), code)


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("ordinal", "acquisition_primitive_invalid"),
        ("intent", "acquisition_intent_invalid"),
        ("source", "task_source_binding_invalid"),
        ("fact_text", "numerical_fact_text_invalid"),
        ("locators", "evidence_collection_invalid"),
        ("locator_duplicate", "evidence_locator_cardinality_exceeded"),
        ("permissions", "evidence_permissions_invalid"),
        ("permission_member", "evidence_permissions_invalid"),
        ("fact_lineage", "numerical_fact_lineage_invalid"),
    ],
)
def test_task_evidence_reconstruction_defenses(target: str, code: str) -> None:
    context = NumericalContextInput("1", "count", "none", "none", "window", "population")
    fact = NumericalFactInput(
        "locator:pubmed:000", "", *tuple(getattr(context, item.name) for item in fields(context))
    )
    fact = replace(fact, exact_text=canonical_numerical_text(fact))
    request = _material_request(facts=(fact,))
    task = replace(request.tasks[0])
    registry = request.registry
    if target in {"ordinal", "intent", "source"}:
        acquisition = replace(task.acquisition)
        if target == "ordinal":
            object.__setattr__(acquisition, "acquisition_ordinal", 9)
        elif target == "intent":
            object.__setattr__(acquisition, "acquisition_intent_id", "bad")
        else:
            object.__setattr__(acquisition, "source", SourceType.DAILYMED)
        task = replace(task, acquisition=acquisition)
    else:
        evidence = replace(registry.evidence[0])
        if target == "fact_text":
            object.__setattr__(evidence.numerical_facts[0], "exact_text", "forged")
        elif target == "locators":
            object.__setattr__(evidence, "locators", ())
        elif target == "locator_duplicate":
            object.__setattr__(evidence, "locators", (evidence.locators[0],) * 2)
        elif target == "permissions":
            object.__setattr__(evidence, "permitted_claim_classes", {ClaimClass.DESCRIPTIVE})
        elif target == "permission_member":
            object.__setattr__(
                evidence,
                "permitted_claim_classes",
                frozenset({ClaimClass.DESCRIPTIVE, "wrong-type"}),
            )
        else:
            object.__setattr__(evidence.numerical_facts[0], "locator_ref", "locator:foreign")
            object.__setattr__(
                evidence.numerical_facts[0],
                "exact_text",
                canonical_numerical_text(evidence.numerical_facts[0]),
            )
            object.__setattr__(
                evidence,
                "evidence_id",
                canonical_evidence_id(evidence),
            )
        registry = replace(registry, evidence=(evidence,))
    _expect_code(replace(request, tasks=(task,), registry=registry), code)


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("claim_collection", "claim_collection_invalid"),
        ("claim_form", "claim_closed_form_invalid"),
        ("claim_identity", "claim_identity_drift"),
        ("qualitative", "qualitative_claim_noncanonical"),
        ("comparison_dimensions", "comparison_dimensions_wrong_type"),
        ("comparison_applicable", "comparison_applicability_wrong_type"),
        ("comparison_values", "comparison_values_invalid"),
        ("comparison_hash", "comparison_authority_invalid"),
        ("conflict_hash", "conflict_authority_invalid"),
    ],
)
def test_claim_comparison_reconstruction_defenses(target: str, code: str) -> None:
    request = _material_request()
    if target.startswith("claim") or target == "qualitative":
        claim = replace(request.registry.claims[0])
        if target == "claim_collection":
            object.__setattr__(claim, "citation_ids", [])
        elif target == "claim_form":
            object.__setattr__(claim, "qualitative_code", None)
        elif target == "claim_identity":
            object.__setattr__(claim, "claim_id", "claim:sha256:" + "d" * 64)
        else:
            object.__setattr__(claim, "statement", "Forged statement")
            object.__setattr__(claim, "claim_id", canonical_claim_id(claim))
        request = replace(request, registry=replace(request.registry, claims=(claim,)))
    else:
        comparison, conflict = _comparison(ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE)
        if target == "comparison_dimensions":
            object.__setattr__(comparison, "dimensions", [])
        elif target == "comparison_applicable":
            object.__setattr__(comparison.dimensions[0], "applicable", 1)
        elif target == "comparison_values":
            object.__setattr__(comparison.dimensions[0], "left_value", None)
        elif target == "comparison_hash":
            object.__setattr__(comparison, "artifact_hash", "sha256:" + "d" * 64)
        else:
            object.__setattr__(conflict, "artifact_hash", "sha256:" + "d" * 64)
        registry = replace(request.registry, comparisons=(comparison,), conflicts=(conflict,))
        request = replace(request, registry=registry)
    _expect_code(request, code)


def test_stored_validation_and_semantic_provider_failures() -> None:
    request = _material_request()
    audit, _ = _assess(request)
    stored = _stored(audit)
    bad_stored = replace(stored)
    object.__setattr__(bad_stored, "structural_passed", "yes")
    _expect_code(
        replace(request, stored_validation=bad_stored), "stored_validation_gate_wrong_type"
    )
    with pytest.raises(CanonicalValidationError, match="stored_validation_forbidden_in_assess"):
        canonical_validate_report(
            replace(request, stored_validation=stored),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=Provider(),
        )
    with pytest.raises(CanonicalValidationError, match="semantic_result_provider_missing"):
        canonical_validate_report(request, mode=ValidationMode.ASSESS)

    class RaisingProvider:
        def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput:
            raise RuntimeError("deterministic failure")

    with pytest.raises(CanonicalValidationError, match="semantic_result_acquisition_failed"):
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=RaisingProvider(),
        )
    wrong = Provider()
    wrong.result = SemanticSupport.UNCERTAIN
    with pytest.raises(CanonicalValidationError, match="semantic_result_expectation_mismatch"):
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=wrong,
        )
    stale = replace(stored, reason_codes=("forged_reason",))
    with pytest.raises(
        CanonicalValidationError,
        match="stored_validation_reason_cardinality_mismatch",
    ):
        canonical_validate_report(
            replace(request, stored_validation=stale),
            mode=ValidationMode.VERIFY_BINDING,
        )
    wrong_type = replace(stored)
    object.__setattr__(wrong_type, "reason_codes", [])
    with pytest.raises(CanonicalValidationError, match="stored_validation_reason_invalid"):
        canonical_validate_report(
            replace(request, stored_validation=wrong_type),
            mode=ValidationMode.VERIFY_BINDING,
        )
    wrong_gate = replace(stored, structural_passed=False)
    gate_drift = canonical_validate_report(
        replace(request, stored_validation=wrong_gate),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert not gate_drift.summary.passed
    assert "stored_validation_binding_mismatch" in gate_drift.summary.reason_codes


def test_audit_reason_families_are_fail_closed() -> None:
    request = _material_request()
    mutations: list[CanonicalReportRequest] = []
    mutations.append(replace(request, registry=replace(request.registry, scope_id="scope:foreign")))
    mutations.append(replace(request, synthesis=replace(request.synthesis, claims=())))
    mutations.append(replace(request, synthesis=replace(request.synthesis, citations=())))
    task = request.tasks[0]
    mutations.append(
        replace(
            request,
            tasks=(replace(task, evidence_refs=(*task.evidence_refs, task.evidence_refs[0])),),
        )
    )
    ref = replace(task.evidence_refs[0], locator_ref="locator:foreign")
    mutations.append(replace(request, tasks=(replace(task, evidence_refs=(ref,)),)))
    mutations.append(replace(request, registry=replace(request.registry, semantic_expectations=())))
    for mutated in mutations:
        mutated = _rebind(mutated)
        audit, provider = _assess(mutated)
        assert not audit.summary.passed
        assert provider.calls == []


@pytest.mark.parametrize(
    ("owner", "code"),
    [
        ("task", "task_evidence_cardinality_exceeded"),
        ("synthesis", "synthesis_claim_cardinality_exceeded"),
        ("registry", "registry_claim_cardinality_exceeded"),
    ],
)
def test_constructor_cardinality_guards_reject_non_tuples(owner: str, code: str) -> None:
    request = _material_request()
    with pytest.raises(CanonicalValidationError) as captured:
        if owner == "task":
            replace(request.tasks[0], evidence_refs=[])
        elif owner == "synthesis":
            replace(request.synthesis, claims=[])
        else:
            replace(request.registry, claims=[])
    assert captured.value.code == code


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("text", "drug_term_invalid"),
        ("digest", "report_hash_invalid"),
        ("reasons", "synthesis_warning_invalid"),
        ("bounds", "execution_bounds_invalid"),
        ("task_collection", "task_collection_wrong_type"),
    ],
)
def test_primitive_shape_and_grammar_rejections(target: str, code: str) -> None:
    request = _empty_request()
    if target == "text":
        scope = replace(request.scope)
        object.__setattr__(scope, "drugs", (("rxnorm:1", "two  spaces"),))
        request = replace(request, scope=scope)
    elif target == "digest":
        synthesis = replace(request.synthesis)
        object.__setattr__(synthesis, "report_content_hash", "not-a-digest")
        request = replace(request, synthesis=synthesis)
    elif target == "reasons":
        synthesis = replace(request.synthesis)
        object.__setattr__(synthesis, "warning_codes", ("warning_z", "warning_a"))
        request = replace(request, synthesis=synthesis)
    elif target == "bounds":
        bounds = replace(request.tasks[0].outcome.configured_bounds)
        object.__setattr__(bounds, "max_pages", 0)
        outcome = replace(request.tasks[0].outcome, configured_bounds=bounds)
        request = replace(request, tasks=(replace(request.tasks[0], outcome=outcome),))
    else:
        object.__setattr__(request, "tasks", list(request.tasks))
    _expect_code(request, code)


def test_identity_helpers_reject_nonprimitive_nested_values() -> None:
    claim = replace(_material_request().registry.claims[0])
    object.__setattr__(claim, "statement", 1.5)
    with pytest.raises(CanonicalValidationError, match="nonprimitive_value"):
        canonical_claim_id(claim)


def test_faers_fact_and_numerical_claim_text_are_reconstructed() -> None:
    faers_context = NumericalContextInput(
        "7",
        "provider_count_occurrence",
        "no exposure denominator",
        "no product comparator",
        "configured query window",
        "bounded FAERS spontaneous reports",
    )
    faers_fact = NumericalFactInput(
        "locator:faers:000",
        "",
        *tuple(getattr(faers_context, item.name) for item in fields(faers_context)),
    )
    faers_fact = replace(faers_fact, exact_text=canonical_numerical_text(faers_fact))
    faers = _material_request(SourceType.FAERS, context=faers_context, facts=(faers_fact,))
    forged_fact = replace(faers_fact, unit="count")
    forged_fact = replace(forged_fact, exact_text=canonical_numerical_text(forged_fact))
    evidence = replace(faers.registry.evidence[0], numerical_facts=(forged_fact,))
    evidence = replace(evidence, evidence_id=canonical_evidence_id(evidence))
    _expect_code(
        replace(faers, registry=replace(faers.registry, evidence=(evidence,))),
        "faers_numerical_fact_invalid",
    )

    context = NumericalContextInput("1", "count", "none", "none", "window", "population")
    fact = NumericalFactInput(
        "locator:pubmed:000",
        "",
        *tuple(getattr(context, item.name) for item in fields(context)),
    )
    fact = replace(fact, exact_text=canonical_numerical_text(fact))
    publication = _material_request(context=context, facts=(fact,))
    claim = replace(publication.registry.claims[0], statement="forged numerical text")
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    _expect_code(
        replace(publication, registry=replace(publication.registry, claims=(claim,))),
        "numerical_claim_text_invalid",
    )


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("foreign_evidence_run", "source_not_in_authorized_run"),
        ("acquisition_snapshot", "evidence_acquisition_snapshot_drift"),
        ("orphan_resolution", "resolution_claim_missing"),
        ("unresolved_removed_claim", "removed_candidate_requires_recorded_removal"),
        ("missing_registry_citation", "citation_or_evidence_not_registered"),
        ("citation_evidence_binding", "claim_citation_evidence_binding_mismatch"),
        ("coverage_qualifier", "coverage_qualifier_untruthful"),
        ("source_policy", "policy_source_semantics_not_permitted"),
        ("cadec_limitation", "policy_mandatory_limitation_missing"),
        ("numerical_authority", "numerical_claim_not_bound_to_authoritative_fact"),
    ],
)
def test_stage1_reason_branches_are_executable(target: str, reason: str) -> None:
    if target == "cadec_limitation":
        request = _material_request(SourceType.CADEC)
        claim = replace(request.registry.claims[0], presented_limitations=())
        request = _retie_single_material_graph(request, claim=claim)
    elif target == "numerical_authority":
        context = NumericalContextInput("1", "count", "none", "none", "window", "population")
        request = _material_request(context=context)
    else:
        request = _material_request()
        if target == "foreign_evidence_run":
            evidence = replace(request.registry.evidence[0], authorized_run_id=FOREIGN_RUN)
            request = _retie_single_material_graph(request, evidence=evidence)
        elif target == "acquisition_snapshot":
            task = request.tasks[0]
            acquisition = replace(task.acquisition, snapshot_id="snapshot:foreign")
            request = _rebind(replace(request, tasks=(replace(task, acquisition=acquisition),)))
        elif target == "orphan_resolution":
            resolution = ResolutionInput(
                "claim:missing",
                ResolutionAction.REMOVED,
                "review:orphan",
                "human_review",
                "v1",
            )
            request = _rebind(
                replace(request, registry=replace(request.registry, resolutions=(resolution,)))
            )
        elif target == "unresolved_removed_claim":
            claim = replace(request.registry.claims[0], inclusion=ClaimInclusion.REMOVED)
            request = _retie_single_material_graph(request, claim=claim)
        elif target == "missing_registry_citation":
            request = _rebind(replace(request, registry=replace(request.registry, citations=())))
        elif target == "citation_evidence_binding":
            original = request.registry.evidence[0]
            other = _evidence(SourceType.PUBMED, 1)
            task = _task(SourceType.PUBMED, request.tasks[0].outcome, (original, other))
            citation_ref = replace(request.synthesis.citations[0], evidence_id=other.evidence_id)
            request = _rebind(
                replace(
                    request,
                    tasks=(task,),
                    synthesis=replace(request.synthesis, citations=(citation_ref,)),
                    registry=replace(request.registry, evidence=(original, other)),
                )
            )
        elif target == "coverage_qualifier":
            outcome = _outcome(SourceType.PUBMED, result=ResultStatus.NO_MATCH)
            request = _retie_single_material_graph(request, outcome=outcome)
        elif target == "source_policy":
            evidence = replace(
                request.registry.evidence[0],
                permitted_claim_classes=frozenset({ClaimClass.ASSOCIATIONAL}),
                permitted_inference_uses=frozenset({InferenceUse.ASSOCIATIONAL}),
            )
            request = _retie_single_material_graph(request, evidence=evidence)
    audit, provider = _assess(request)
    assert not audit.summary.passed
    assert reason in audit.summary.reason_codes
    assert provider.calls == []


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("registry_reference_mismatch", "comparison_conflict_registry_mismatch"),
        ("comparison_hash", "comparison_hash_drift"),
        ("conflict_classification", "conflict_classification_or_hash_drift"),
    ],
)
def test_comparison_graph_reason_branches_are_executable(target: str, reason: str) -> None:
    request = _empty_request()
    comparison, conflict = _comparison(ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE)
    if target == "conflict_classification":
        conflict = replace(conflict, outcome=ConflictOutcome.SOURCE_UNAVAILABLE)
        conflict = replace(conflict, artifact_hash=module._conflict_hash(conflict))
    registry = replace(request.registry, comparisons=(comparison,), conflicts=(conflict,))
    comparison_hash = (
        "sha256:" + "d" * 64 if target == "comparison_hash" else comparison.artifact_hash
    )
    synthesis = replace(
        request.synthesis,
        comparison_refs=(ArtifactReferenceInput(comparison.comparison_id, comparison_hash),),
        conflict_refs=(
            ()
            if target == "registry_reference_mismatch"
            else (ArtifactReferenceInput(conflict.conflict_id, conflict.artifact_hash),)
        ),
    )
    request = _rebind(replace(request, registry=registry, synthesis=synthesis))
    audit, provider = _assess(request)
    assert not audit.summary.passed
    assert reason in audit.summary.reason_codes
    assert provider.calls == []


def test_outer_scope_and_task_exact_maxima_are_canonical_passes() -> None:
    request = _outer_exact_max_request()
    assert len(request.scope.drugs) == 4
    assert len(request.scope.adverse_reactions) == 8
    assert len(request.scope.selected_sources) == 4
    assert len(request.tasks) == 4
    audit, provider = _assess(request)
    assert audit.summary.passed and audit.summary.reason_codes == ()
    assert provider.calls == []
    verified = canonical_validate_report(
        replace(request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("drugs", "scope_drug_cardinality_exceeded"),
        ("adverse_reactions", "scope_adverse_reaction_cardinality_exceeded"),
        ("selected_sources", "scope_source_cardinality_exceeded"),
        ("tasks", "task_cardinality_exceeded"),
    ],
)
def test_outer_max_plus_one_precedes_wrong_type_member(target: str, code: str) -> None:
    request = _outer_exact_max_request()
    if target == "tasks":
        object.__setattr__(request, "tasks", (*request.tasks, object()))
    else:
        scope = replace(request.scope)
        values = getattr(scope, target)
        object.__setattr__(scope, target, (*values, object()))
        request = replace(request, scope=scope)
    provider = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    assert captured.value.code == code
    assert provider.calls == []


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("comparison", "comparison_dimension_cardinality_exceeded"),
        ("outcome_warnings", "outcome_warning_cardinality_exceeded"),
    ],
)
def test_comparison_and_outcome_exact_max_pass_then_max_plus_one_fails(
    target: str,
    code: str,
) -> None:
    if target == "comparison":
        comparison, conflict = _comparison(ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE)
        request = _empty_request()
        registry = replace(
            request.registry,
            comparisons=(comparison,),
            conflicts=(conflict,),
        )
        synthesis = replace(
            request.synthesis,
            comparison_refs=(
                ArtifactReferenceInput(comparison.comparison_id, comparison.artifact_hash),
            ),
            conflict_refs=(ArtifactReferenceInput(conflict.conflict_id, conflict.artifact_hash),),
        )
        exact = _rebind(replace(request, registry=registry, synthesis=synthesis))
        assert len(comparison.dimensions) == 11
        attacked = replace(comparison)
        object.__setattr__(attacked, "dimensions", (*comparison.dimensions, object()))
        attacked_request = replace(exact, registry=replace(registry, comparisons=(attacked,)))
    else:
        warnings = tuple(f"warning_{index:03d}" for index in range(100))
        exact = _empty_request(
            SourceType.PUBMED,
            outcomes=(_outcome(SourceType.PUBMED, warnings=warnings),),
        )
        assert len(exact.tasks[0].outcome.warning_codes) == 100
        outcome = replace(exact.tasks[0].outcome)
        object.__setattr__(outcome, "warning_codes", (*warnings, object()))
        attacked_request = replace(
            exact,
            tasks=(replace(exact.tasks[0], outcome=outcome),),
        )
    audit, provider = _assess(exact)
    assert audit.summary.passed and provider.calls == []
    evaluator = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            attacked_request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=evaluator,
        )
    assert captured.value.code == code
    assert evaluator.calls == []


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("permitted_claim_classes", "evidence_claim_class_cardinality_exceeded"),
        ("permitted_inference_uses", "evidence_inference_use_cardinality_exceeded"),
    ],
)
def test_permission_exact_enum_max_passes_and_extra_wrong_type_fails(
    target: str,
    code: str,
) -> None:
    request = _material_request()
    evidence = replace(
        request.registry.evidence[0],
        permitted_claim_classes=frozenset(ClaimClass),
        permitted_inference_uses=frozenset(InferenceUse),
    )
    exact = _retie_single_material_graph(request, evidence=evidence)
    assert len(getattr(exact.registry.evidence[0], target)) == len(
        ClaimClass if target == "permitted_claim_classes" else InferenceUse
    )
    audit, provider = _assess(exact)
    assert audit.summary.passed and len(provider.calls) == 1

    attacked = replace(exact.registry.evidence[0])
    values = getattr(attacked, target)
    object.__setattr__(attacked, target, frozenset((*values, object())))
    evaluator = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(exact, registry=replace(exact.registry, evidence=(attacked,))),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=evaluator,
        )
    assert captured.value.code == code
    assert evaluator.calls == []


def test_stored_reason_bound_is_exactly_request_relative_before_traversal() -> None:
    request = _material_request(support=SemanticSupport.UNSUPPORTED)
    audit, provider = _assess(request, Provider(SemanticSupport.UNSUPPORTED))
    assert not audit.summary.passed
    assert audit.summary.reason_codes == ("material_claim_not_accepted",)
    assert len(provider.calls) == 1
    stored = _stored(audit)
    verified = canonical_validate_report(
        replace(request, stored_validation=stored),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary

    attacked = replace(stored)
    object.__setattr__(attacked, "reason_codes", (*stored.reason_codes, object()))
    with pytest.raises(
        CanonicalValidationError,
        match="stored_validation_reason_cardinality_mismatch",
    ):
        canonical_validate_report(
            replace(request, stored_validation=attacked),
            mode=ValidationMode.VERIFY_BINDING,
        )


def test_duplicate_identity_short_circuits_hash_and_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _material_request(
        support=SemanticSupport.UNCERTAIN,
        resolution=ResolutionAction.ADJUDICATED_TO_SUPPORTED,
    )
    resolution = request.registry.resolutions[0]
    duplicate = _rebind(
        replace(
            request,
            registry=replace(request.registry, resolutions=(resolution, resolution)),
        )
    )
    hash_calls = 0

    def observed_hash(value: CanonicalReportRequest) -> str:
        nonlocal hash_calls
        del value
        hash_calls += 1
        raise AssertionError("duplicate identities must bypass report hashing")

    monkeypatch.setattr(module, "canonical_report_content_hash", observed_hash)
    provider = Provider(SemanticSupport.UNCERTAIN)
    audit, provider = _assess(duplicate, provider)
    assert not audit.summary.passed
    assert "registry_identity_duplicate" in audit.summary.reason_codes
    assert hash_calls == 0
    assert provider.calls == []


def test_passing_receipt_is_deterministic_bound_and_payload_roundtrips() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    audit, provider = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    assert audit.summary.passed
    assert len(provider.calls) == 1
    receipt = audit.receipt
    assert isinstance(receipt, ValidationReceipt)
    assert receipt.run_id == request.run_id
    assert receipt.report_id == request.report_id
    assert receipt.report_content_hash == request.synthesis.report_content_hash
    assert (
        receipt.structural_passed,
        receipt.semantic_passed,
        receipt.safety_passed,
        receipt.reason_codes,
    ) == (
        audit.summary.structural_passed,
        audit.summary.semantic_passed,
        audit.summary.safety_passed,
        audit.summary.reason_codes,
    )
    claim_receipt = receipt.claim_results[0]
    assert claim_receipt.aggregate_result is SemanticSupport.SUPPORTED
    assert claim_receipt.formal_claim_accepted
    assert tuple(item.relationship for item in claim_receipt.citation_results) == (
        CitationRelationship.SUPPORTS,
    )
    assert tuple(item.citation_id for item in claim_receipt.citation_results) == tuple(
        item.citation_id for item in audit.claims[0].citation_traces
    )
    payload = canonical_validation_receipt_payload(receipt)
    rebuilt = validation_receipt_from_payload(payload)
    assert rebuilt == receipt
    assert verify_validation_receipt(receipt, request=request, audit=audit) == receipt

    repeated, _ = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    assert repeated.receipt == receipt


def test_failed_stage1_and_stage2_emit_completed_assessment_receipts() -> None:
    stage1_request = _relationship_request(
        (CitationRelationship.CONTEXT_ONLY,),
        (SemanticSupport.SUPPORTED,),
    )
    stage1, provider = _assess(
        stage1_request,
        SequencedProvider((SemanticSupport.SUPPORTED,)),
    )
    assert not stage1.summary.passed
    assert "formal_claim_requires_supporting_citation" in stage1.summary.reason_codes
    assert provider.calls == []
    assert stage1.receipt is not None
    stage1_claim = stage1.receipt.claim_results[0]
    assert not stage1_claim.stage1_passed
    assert stage1_claim.citation_results == ()
    assert stage1_claim.aggregate_result is None

    stage2_request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.UNSUPPORTED,),
    )
    stage2, provider = _assess(
        stage2_request,
        SequencedProvider((SemanticSupport.UNSUPPORTED,)),
    )
    assert not stage2.summary.passed
    assert stage2.summary.reason_codes == ("material_claim_not_accepted",)
    assert len(provider.calls) == 1
    assert stage2.receipt is not None
    stage2_claim = stage2.receipt.claim_results[0]
    assert stage2_claim.stage1_passed
    assert stage2_claim.aggregate_result is SemanticSupport.UNSUPPORTED
    assert not stage2_claim.formal_claim_accepted


def test_evaluator_failure_returns_no_audit_or_receipt() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )

    class RaisingProvider:
        def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput:
            del value
            raise RuntimeError("deterministic evaluator failure")

    with pytest.raises(CanonicalValidationError, match="semantic_result_acquisition_failed"):
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider=RaisingProvider(),
        )


def test_verify_has_no_receipt_and_never_replays_evaluator() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    audit, provider = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    calls = tuple(provider.calls)
    verified = canonical_validate_report(
        replace(request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary
    assert verified.receipt is None
    assert tuple(provider.calls) == calls


@pytest.mark.parametrize(
    ("relationships", "results", "aggregate", "passed"),
    [
        (
            (CitationRelationship.SUPPORTS,),
            (SemanticSupport.SUPPORTED,),
            SemanticSupport.SUPPORTED,
            True,
        ),
        (
            (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
            (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
            SemanticSupport.UNCERTAIN,
            False,
        ),
        (
            (CitationRelationship.SUPPORTS,),
            (SemanticSupport.UNCERTAIN,),
            SemanticSupport.UNCERTAIN,
            False,
        ),
        (
            (
                CitationRelationship.SUPPORTS,
                CitationRelationship.SUPPORTS,
                CitationRelationship.CONTRADICTS,
            ),
            (
                SemanticSupport.SUPPORTED,
                SemanticSupport.SUPPORTED,
                SemanticSupport.SUPPORTED,
            ),
            SemanticSupport.UNCERTAIN,
            False,
        ),
    ],
)
def test_relationship_aggregation_is_closed_and_unweighted(
    relationships: tuple[CitationRelationship, ...],
    results: tuple[SemanticSupport, ...],
    aggregate: SemanticSupport,
    passed: bool,
) -> None:
    request = _relationship_request(relationships, results)
    audit, provider = _assess(request, SequencedProvider(results))
    assert audit.summary.passed is passed
    assert len(provider.calls) == len(results)
    claim = audit.claims[0]
    assert claim.aggregate_result is aggregate
    assert claim.formal_claim_accepted is passed
    assert tuple(item.relationship for item in claim.citation_traces) == relationships
    assert tuple(item.result for item in claim.citation_traces) == results
    assert audit.receipt is not None
    receipt_claim = audit.receipt.claim_results[0]
    assert receipt_claim.aggregate_result is aggregate
    assert tuple(item.relationship for item in receipt_claim.citation_results) == relationships
    assert receipt_claim.resolution_action is None


def test_ordinary_uncertain_support_retains_unbound_human_resolution() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.UNCERTAIN,),
        adjudicate=True,
    )
    audit, provider = _assess(request, SequencedProvider((SemanticSupport.UNCERTAIN,)))
    assert audit.summary.passed and audit.summary.reason_codes == ()
    assert len(provider.calls) == 1
    claim = audit.claims[0]
    assert claim.aggregate_result is SemanticSupport.UNCERTAIN
    assert claim.formal_claim_accepted
    assert audit.receipt is not None
    receipt_claim = audit.receipt.claim_results[0]
    assert receipt_claim.resolution_action is ResolutionAction.ADJUDICATED_TO_SUPPORTED
    assert receipt_claim.resolution_record_id == "review:relationship-adjudication"
    assert receipt_claim.resolution_method == "human_review"
    assert receipt_claim.resolution_version == "v1"
    assert receipt_claim.comparison_id is None
    assert receipt_claim.conflict_id is None


def test_ordinary_uncertain_support_rejects_extraneous_conflict_binding() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.UNCERTAIN,),
        adjudicate=True,
    )
    request, comparisons, conflicts = _with_comparison_graph(
        request,
        ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH,
    )
    request = _bind_relationship_resolution(
        request,
        comparisons[0].comparison_id,
        conflicts[0].conflict_id,
    )
    audit, provider = _assess(request, SequencedProvider((SemanticSupport.UNCERTAIN,)))
    assert not audit.summary.passed
    assert audit.summary.reason_codes == ("material_claim_not_accepted",)
    assert len(provider.calls) == 1
    assert audit.claims[0].aggregate_result is SemanticSupport.UNCERTAIN
    assert not audit.claims[0].formal_claim_accepted


@pytest.mark.parametrize(
    "case",
    [
        "no_binding",
        "missing_comparison",
        "foreign_comparison",
        "missing_conflict",
        "foreign_conflict",
        "consistent",
        "unresolved",
        "insufficient",
        "source_unavailable",
    ],
)
def test_confirmed_contradiction_requires_exact_scope_mismatch_binding(case: str) -> None:
    results = (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    request = _relationship_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
        results,
        adjudicate=True,
    )
    if case != "no_binding":
        outcome = {
            "consistent": ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE,
            "unresolved": ConflictOutcome.UNRESOLVED_CONFLICT_COMPARABLE_SCOPE,
            "insufficient": ConflictOutcome.INSUFFICIENT_INFORMATION,
            "source_unavailable": ConflictOutcome.SOURCE_UNAVAILABLE,
        }.get(case, ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH)
        graph_outcomes = (
            (outcome, ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH)
            if case in {"foreign_comparison", "foreign_conflict"}
            else (outcome,)
        )
        request, comparisons, conflicts = _with_comparison_graph(request, *graph_outcomes)
        comparison_id = comparisons[0].comparison_id
        conflict_id = conflicts[0].conflict_id
        if case == "missing_comparison":
            comparison_id = "comparison:missing"
        elif case == "foreign_comparison":
            comparison_id = comparisons[1].comparison_id
        elif case == "missing_conflict":
            conflict_id = "conflict:missing"
        elif case == "foreign_conflict":
            conflict_id = conflicts[1].conflict_id
        request = _bind_relationship_resolution(request, comparison_id, conflict_id)

    audit, provider = _assess(request, SequencedProvider(results))
    assert not audit.summary.passed
    assert audit.summary.reason_codes == ("material_claim_not_accepted",)
    assert len(provider.calls) == 2
    assert audit.claims[0].aggregate_result is SemanticSupport.UNCERTAIN
    assert not audit.claims[0].formal_claim_accepted


def test_scope_mismatch_resolution_binds_graph_and_receipt_for_confirmed_contradiction() -> None:
    results = (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    request = _relationship_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
        results,
        adjudicate=True,
    )
    request, comparisons, conflicts = _with_comparison_graph(
        request,
        ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH,
    )
    comparison = comparisons[0]
    conflict = conflicts[0]
    request = _bind_relationship_resolution(
        request,
        comparison.comparison_id,
        conflict.conflict_id,
    )
    assert request.synthesis.comparison_refs == (
        ArtifactReferenceInput(comparison.comparison_id, comparison.artifact_hash),
    )
    assert request.synthesis.conflict_refs == (
        ArtifactReferenceInput(conflict.conflict_id, conflict.artifact_hash),
    )
    assert request.synthesis.report_content_hash == canonical_report_content_hash(request)

    audit, provider = _assess(request, SequencedProvider(results))
    assert audit.summary.passed and audit.summary.reason_codes == ()
    assert len(provider.calls) == 2
    assert audit.conflict_outcomes == (
        (conflict.conflict_id, ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH),
    )
    claim = audit.claims[0]
    assert claim.aggregate_result is SemanticSupport.UNCERTAIN
    assert claim.formal_claim_accepted
    assert audit.receipt is not None
    receipt_claim = audit.receipt.claim_results[0]
    assert receipt_claim.resolution_action is ResolutionAction.ADJUDICATED_TO_SUPPORTED
    assert receipt_claim.resolution_record_id == "review:relationship-adjudication"
    assert receipt_claim.resolution_method == "human_review"
    assert receipt_claim.resolution_version == "v1"
    assert receipt_claim.comparison_id == comparison.comparison_id
    assert receipt_claim.conflict_id == conflict.conflict_id
    payload = canonical_validation_receipt_payload(audit.receipt)
    rebuilt = validation_receipt_from_payload(payload)
    assert rebuilt == audit.receipt
    assert verify_validation_receipt(rebuilt, request=request, audit=audit) == rebuilt


@pytest.mark.parametrize(
    "target",
    [
        "outer_type",
        "outer_keys",
        "summary_reasons",
        "claims",
        "claim_keys",
        "claim_reasons",
        "citations",
        "total_citations",
        "result_enum",
        "result_type",
        "relationship_enum",
        "relationship_type",
        "resolution_binding",
        "comparison_missing",
        "conflict_missing",
        "comparison_type",
        "conflict_type",
        "comparison_drift",
        "conflict_drift",
    ],
)
def test_validation_receipt_payload_is_strict_and_bounded(target: str) -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    if target.startswith(("comparison_", "conflict_")):
        request = _relationship_request(
            (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
            (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
            adjudicate=True,
        )
        request, comparisons, conflicts = _with_comparison_graph(
            request,
            ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH,
        )
        request = _bind_relationship_resolution(
            request,
            comparisons[0].comparison_id,
            conflicts[0].conflict_id,
        )
        provider_results = (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    else:
        provider_results = (SemanticSupport.SUPPORTED,)
    audit, _ = _assess(request, SequencedProvider(provider_results))
    assert audit.receipt is not None
    payload: object = canonical_validation_receipt_payload(audit.receipt)
    if target == "outer_type":
        payload = []
    else:
        assert isinstance(payload, dict)
        if target == "outer_keys":
            payload.pop("marker")
        elif target == "summary_reasons":
            payload["reason_codes"] = "not-a-list"
        elif target == "claims":
            payload["claim_results"] = [payload["claim_results"][0]] * 201
        else:
            claim = payload["claim_results"][0]
            if target == "claim_keys":
                claim.pop("claim_id")
            elif target == "claim_reasons":
                claim["stage1_reason_codes"] = "not-a-list"
            elif target == "citations":
                claim["citation_results"] = [claim["citation_results"][0]] * 301
            elif target == "total_citations":
                first = dict(claim)
                second = dict(claim)
                first["citation_results"] = [claim["citation_results"][0]] * 201
                second["citation_results"] = [claim["citation_results"][0]] * 200
                payload["claim_results"] = [first, second]
            elif target == "result_enum":
                claim["citation_results"][0]["result"] = "not-a-result"
            elif target == "result_type":
                claim["citation_results"][0]["result"] = None
            elif target == "relationship_enum":
                claim["citation_results"][0]["relationship"] = "not-a-relationship"
            elif target == "relationship_type":
                claim["citation_results"][0]["relationship"] = None
            elif target == "resolution_binding":
                claim["resolution_action"] = ResolutionAction.ADJUDICATED_TO_SUPPORTED.value
                claim["resolution_record_id"] = None
            elif target == "comparison_missing":
                claim["comparison_id"] = None
            elif target == "conflict_missing":
                claim["conflict_id"] = None
            elif target == "comparison_type":
                claim["comparison_id"] = 1
            elif target == "conflict_type":
                claim["conflict_id"] = 1
            elif target == "comparison_drift":
                claim["comparison_id"] = "comparison:foreign"
            else:
                claim["conflict_id"] = "conflict:foreign"
    with pytest.raises(CanonicalValidationError):
        validation_receipt_from_payload(payload)


@pytest.mark.parametrize(
    "target",
    [
        "run",
        "report_hash",
        "validation_input",
        "evaluator",
        "policy",
        "configuration",
        "content_hash",
        "receipt_id",
        "claim",
        "citation",
        "resolution",
    ],
)
def test_validation_receipt_rejects_every_binding_drift(target: str) -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    audit, _ = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    assert audit.receipt is not None
    receipt = audit.receipt
    expected_request = request
    expected_audit = audit
    if target == "run":
        expected_request = replace(request, run_id=FOREIGN_RUN)
    elif target == "report_hash":
        expected_request = replace(
            request,
            synthesis=replace(request.synthesis, report_content_hash="sha256:" + "d" * 64),
        )
    elif target == "validation_input":
        expected_request = replace(
            request,
            registry=replace(request.registry, run_id=FOREIGN_RUN),
        )
    elif target == "evaluator":
        expected_request = replace(
            request,
            registry=replace(
                request.registry,
                evaluator_identity=EvaluatorIdentityInput("other_evaluator", "v2"),
            ),
        )
    elif target == "configuration":
        expected_request = replace(
            request,
            registry=replace(request.registry, configuration_version="configuration:v2"),
        )
    elif target == "policy":
        receipt = replace(receipt, policy_version="policy:v2")
    elif target == "content_hash":
        receipt = replace(receipt, receipt_content_hash="sha256:" + "d" * 64)
    elif target == "receipt_id":
        receipt = replace(receipt, receipt_id="validation-receipt:foreign")
    else:
        if target == "claim":
            expected_request = _material_request(SourceType.DAILYMED)
            expected_audit, _ = _assess(expected_request)
        elif target == "citation":
            expected_request = _relationship_request(
                (CitationRelationship.CONTEXT_ONLY,),
                (SemanticSupport.SUPPORTED,),
            )
            expected_audit, _ = _assess(
                expected_request,
                SequencedProvider((SemanticSupport.SUPPORTED,)),
            )
        else:
            expected_request = _relationship_request(
                (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
                (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
                adjudicate=True,
            )
            expected_audit, _ = _assess(
                expected_request,
                SequencedProvider((SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)),
            )
    with pytest.raises(CanonicalValidationError):
        verify_validation_receipt(
            receipt,
            request=expected_request,
            audit=expected_audit,
        )


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("claims", "validation_receipt_claim_cardinality_mismatch"),
        ("claim_reasons", "validation_receipt_reason_cardinality_mismatch"),
        ("citation_identity", "validation_receipt_citation_identity_drift"),
        ("claim_identity", "validation_receipt_claim_identity_drift"),
    ],
)
def test_validation_receipt_nested_identity_and_cardinality_fail_closed(
    target: str,
    code: str,
) -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    audit, _ = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    assert audit.receipt is not None
    receipt = audit.receipt
    claim = receipt.claim_results[0]
    if target == "claims":
        attacked = replace(receipt, claim_results=())
    elif target == "claim_reasons":
        attacked_claim = replace(claim, stage1_reason_codes=("forged_reason",))
        attacked = replace(receipt, claim_results=(attacked_claim,))
    elif target == "citation_identity":
        citation = replace(
            claim.citation_results[0],
            citation_result_id="validation-citation-result:foreign",
        )
        attacked = replace(
            receipt,
            claim_results=(replace(claim, citation_results=(citation,)),),
        )
    else:
        attacked = replace(
            receipt,
            claim_results=(replace(claim, claim_result_id="validation-claim-result:foreign"),),
        )
    with pytest.raises(CanonicalValidationError) as captured:
        verify_validation_receipt(attacked, request=request, audit=audit)
    assert captured.value.code == code


def _retie_receipt_claim_binding(
    receipt: ValidationReceipt,
    *,
    comparison_id: str,
    conflict_id: str,
) -> ValidationReceipt:
    claim = replace(
        receipt.claim_results[0],
        comparison_id=comparison_id,
        conflict_id=conflict_id,
    )
    claim_content = {
        item.name: module._primitive(getattr(claim, item.name))
        for item in fields(claim)
        if item.name != "claim_result_id"
    }
    claim = replace(
        claim,
        claim_result_id=derive_identity("validation-claim-result", claim_content),
    )
    attacked = replace(receipt, claim_results=(claim,))
    receipt_content = {
        item.name: module._primitive(getattr(attacked, item.name))
        for item in fields(attacked)
        if item.name not in {"receipt_id", "receipt_content_hash"}
    }
    return replace(
        attacked,
        receipt_content_hash=sha256_digest(canonical_json(receipt_content)),
        receipt_id=derive_identity("validation-receipt", receipt_content),
    )


@pytest.mark.parametrize("target", ["comparison", "conflict"])
def test_self_consistent_receipt_governed_binding_drift_fails_closed(target: str) -> None:
    results = (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    request = _relationship_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTRADICTS),
        results,
        adjudicate=True,
    )
    request, comparisons, conflicts = _with_comparison_graph(
        request,
        ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH,
    )
    request = _bind_relationship_resolution(
        request,
        comparisons[0].comparison_id,
        conflicts[0].conflict_id,
    )
    audit, _ = _assess(request, SequencedProvider(results))
    assert audit.summary.passed and audit.receipt is not None
    attacked = _retie_receipt_claim_binding(
        audit.receipt,
        comparison_id=(
            "comparison:foreign" if target == "comparison" else comparisons[0].comparison_id
        ),
        conflict_id=("conflict:foreign" if target == "conflict" else conflicts[0].conflict_id),
    )
    payload = canonical_validation_receipt_payload(attacked)
    rebuilt = validation_receipt_from_payload(payload)
    assert rebuilt == attacked
    with pytest.raises(
        CanonicalValidationError,
        match="validation_receipt_binding_drift",
    ):
        verify_validation_receipt(rebuilt, request=request, audit=audit)


def _receipt_with_policy(receipt: ValidationReceipt, policy: str) -> ValidationReceipt:
    payload = canonical_validation_receipt_payload(receipt)
    payload["policy_version"] = policy
    content = {
        key: value
        for key, value in payload.items()
        if key not in {"receipt_id", "receipt_content_hash"}
    }
    return replace(
        receipt,
        policy_version=policy,
        receipt_content_hash=sha256_digest(canonical_json(content)),
        receipt_id=derive_identity("validation-receipt", content),
    )


def test_internally_consistent_foreign_policy_is_rejected_by_all_public_routes() -> None:
    request = _relationship_request(
        (CitationRelationship.SUPPORTS,),
        (SemanticSupport.SUPPORTED,),
    )
    audit, _ = _assess(request, SequencedProvider((SemanticSupport.SUPPORTED,)))
    assert audit.receipt is not None
    receipt = _receipt_with_policy(audit.receipt, "policy:v2")
    with pytest.raises(CanonicalValidationError, match="validation_receipt_policy_drift"):
        verify_validation_receipt(receipt, request=request, audit=audit)
    with pytest.raises(CanonicalValidationError, match="validation_receipt_policy_drift"):
        canonical_validation_receipt_payload(receipt)
    payload = canonical_validation_receipt_payload(audit.receipt)
    payload["policy_version"] = "policy:v2"
    content = {
        key: value
        for key, value in payload.items()
        if key not in {"receipt_id", "receipt_content_hash"}
    }
    payload["receipt_content_hash"] = sha256_digest(canonical_json(content))
    payload["receipt_id"] = derive_identity("validation-receipt", content)
    with pytest.raises(CanonicalValidationError, match="validation_receipt_policy_drift"):
        validation_receipt_from_payload(payload)


def test_public_invariants_dominate_three_defensive_repeat_guards() -> None:
    request = _material_request()
    attacked_task = replace(request.tasks[0])
    object.__setattr__(
        attacked_task,
        "evidence_refs",
        attacked_task.evidence_refs * 101,
    )
    provider = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(request, tasks=(attacked_task,)),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    assert captured.value.code == "task_evidence_cardinality_exceeded"
    assert provider.calls == []

    expectation = replace(
        request.registry.semantic_expectations[0],
        input_digest="sha256:" + "d" * 64,
    )
    stale = _rebind(
        replace(
            request,
            registry=replace(request.registry, semantic_expectations=(expectation,)),
        )
    )
    audit, provider = _assess(stale)
    assert not audit.summary.passed
    assert "semantic_expectation_binding_drift" in audit.summary.reason_codes
    assert "stage1_failed_before_semantic_evaluation" in audit.summary.reason_codes
    assert provider.calls == []

    expectation = request.registry.semantic_expectations[0]
    duplicate = _rebind(
        replace(
            request,
            registry=replace(
                request.registry,
                semantic_expectations=(expectation, expectation),
            ),
        )
    )
    audit, provider = _assess(duplicate)
    assert not audit.summary.passed
    assert "semantic_expectation_registry_mismatch" in audit.summary.reason_codes
    assert "registry_identity_duplicate" in audit.summary.reason_codes
    assert provider.calls == []


def test_duplicate_adjudicated_resolution_fails_assess_and_pure_verify() -> None:
    request = _material_request(
        support=SemanticSupport.UNCERTAIN,
        resolution=ResolutionAction.ADJUDICATED_TO_SUPPORTED,
    )
    resolution = request.registry.resolutions[0]
    duplicate = _rebind(
        replace(
            request,
            registry=replace(request.registry, resolutions=(resolution, resolution)),
        )
    )
    audit, provider = _assess(duplicate, Provider(SemanticSupport.UNCERTAIN))
    assert not audit.summary.passed
    assert "registry_identity_duplicate" in audit.summary.reason_codes
    assert "stage1_failed_before_semantic_evaluation" in audit.summary.reason_codes
    assert provider.calls == []

    verified = canonical_validate_report(
        replace(duplicate, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary
    assert not verified.summary.passed


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("limitations", "claim_limitation_cardinality_exceeded"),
        ("numerical_facts", "evidence_numerical_fact_cardinality_exceeded"),
    ],
)
def test_nested_exact_max_passes_and_max_plus_one_fails_before_members(
    target: str,
    code: str,
) -> None:
    request = _material_request()
    if target == "limitations":
        values: tuple[object, ...] = tuple(
            f"Bounded limitation {index:03d}." for index in range(100)
        )
        claim = replace(request.registry.claims[0], presented_limitations=values)
        exact = _retie_single_material_graph(request, claim=claim)
        container = exact.registry.claims[0]
        field = "presented_limitations"
    else:
        context = NumericalContextInput("1", "count", "none", "none", "window", "population")
        fact = NumericalFactInput(
            "locator:pubmed:000",
            "",
            *tuple(getattr(context, item.name) for item in fields(context)),
        )
        fact = replace(fact, exact_text=canonical_numerical_text(fact))
        values = (fact,) * 100
        evidence = replace(
            request.registry.evidence[0],
            normalized_excerpt=fact.exact_text,
            numerical_facts=values,
        )
        exact = _retie_single_material_graph(request, evidence=evidence)
        container = exact.registry.evidence[0]
        field = "numerical_facts"
    audit, provider = _assess(exact)
    assert audit.summary.passed
    assert len(provider.calls) == 1

    attacked = replace(container)
    object.__setattr__(attacked, field, (*values, object()))
    registry = (
        replace(exact.registry, claims=(attacked,))
        if target == "limitations"
        else replace(exact.registry, evidence=(attacked,))
    )
    evaluator = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(exact, registry=registry),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=evaluator,
        )
    assert captured.value.code == code
    assert evaluator.calls == []


def _claim_citation_exact_max_request() -> CanonicalReportRequest:
    scope = _scope(SourceType.PUBMED)
    evidence = tuple(_evidence(SourceType.PUBMED, index) for index in range(100))
    outcome = _outcome(SourceType.PUBMED, result=ResultStatus.MATCHES)
    claim = ClaimInput(
        "claim:sha256:" + "0" * 64,
        SourceType.PUBMED,
        QualitativeCode.PUBMED_DESCRIPTIVE,
        _qualitative_statement(SourceType.PUBMED),
        ClaimClass.DESCRIPTIVE,
        InferenceUse.DESCRIPTIVE,
        (),
        (),
        ClaimInclusion.FORMAL,
        None,
    )
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    citations = tuple(
        replace(
            citation,
            citation_id=canonical_citation_id(citation),
        )
        for item in evidence
        for relationship in CitationRelationship
        for citation in (
            CitationInput(
                "citation:sha256:" + "0" * 64,
                claim.claim_id,
                item.evidence_id,
                relationship,
                item.source_record_id,
                item.source_version,
                item.snapshot_id,
                item.content_hash,
                item.locators[0],
                outcome.execution_status,
                outcome.coverage_status,
                outcome.result_status,
            ),
        )
    )
    assert len(citations) == 300
    claim = replace(claim, citation_ids=tuple(item.citation_id for item in citations))
    expectations = tuple(
        SemanticExpectationInput(
            citation.citation_id,
            canonical_semantic_input_digest(RUN_ID, claim, citation, item),
            IDENTITY.method,
            IDENTITY.version,
            SemanticSupport.SUPPORTED,
        )
        for item in evidence
        for citation in citations
        if citation.evidence_id == item.evidence_id
    )
    comparison, conflict = _comparison(
        ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH,
    )
    registry = ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        (claim,),
        citations,
        evidence,
        expectations,
        IDENTITY,
        comparisons=(comparison,),
        conflicts=(conflict,),
        resolutions=(
            ResolutionInput(
                claim.claim_id,
                ResolutionAction.ADJUDICATED_TO_SUPPORTED,
                "review:exact-300",
                "human_review",
                "v1",
                comparison.comparison_id,
                conflict.conflict_id,
            ),
        ),
    )
    synthesis = SynthesisInput(
        "sha256:" + "0" * 64,
        (ClaimReferenceInput(claim.claim_id),),
        tuple(
            CitationReferenceInput(item.citation_id, item.claim_id, item.evidence_id)
            for item in citations
        ),
        (ArtifactReferenceInput(comparison.comparison_id, comparison.artifact_hash),),
        (ArtifactReferenceInput(conflict.conflict_id, conflict.artifact_hash),),
        (),
    )
    request = CanonicalReportRequest(
        RUN_ID,
        REPORT_ID,
        scope,
        (_task(SourceType.PUBMED, outcome, evidence),),
        synthesis,
        registry,
    )
    return _rebind(request)


def test_claim_citations_300_and_evidence_locator_one_are_graph_valid_maxima() -> None:
    request = _claim_citation_exact_max_request()
    assert len(request.registry.claims[0].citation_ids) == 300
    assert all(len(item.locators) == 1 for item in request.registry.evidence)
    provider = Provider()
    audit, provider = _assess(request, provider)
    assert audit.summary.passed and audit.summary.reason_codes == ()
    assert len(provider.calls) == 300
    verified = canonical_validate_report(
        replace(request, stored_validation=_stored(audit)),
        mode=ValidationMode.VERIFY_BINDING,
    )
    assert verified.summary == audit.summary


@pytest.mark.parametrize(
    ("target", "maximum", "code"),
    [
        ("citation_ids", 300, "claim_citation_cardinality_exceeded"),
        ("locators", 1, "evidence_locator_cardinality_exceeded"),
    ],
)
def test_nested_cardinality_max_plus_one_precedes_malformed_member(
    target: str,
    maximum: int,
    code: str,
) -> None:
    request = _material_request()
    if target == "citation_ids":
        container = replace(request.registry.claims[0])
        exact_values: tuple[object, ...] = (container.citation_ids[0],) * maximum
        object.__setattr__(container, target, (*exact_values, object()))
        registry = replace(request.registry, claims=(container,))
    else:
        container = replace(request.registry.evidence[0])
        exact_values = (container.locators[0],) * maximum
        object.__setattr__(container, target, (*exact_values, object()))
        registry = replace(request.registry, evidence=(container,))
    provider = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(request, registry=registry),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=provider,
        )
    assert captured.value.code == code
    assert provider.calls == []


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("limitation", "claim_limitation_invalid"),
        ("excerpt", "evidence_excerpt_invalid"),
    ],
)
def test_bounded_strings_accept_4096_and_reject_4097_before_evaluator(
    target: str,
    code: str,
) -> None:
    request = _material_request()
    if target == "limitation":
        exact = _retie_single_material_graph(
            request,
            claim=replace(request.registry.claims[0], presented_limitations=("x" * 4096,)),
        )
        attacked = replace(exact.registry.claims[0], presented_limitations=("x" * 4097,))
        attacked = replace(attacked, claim_id=canonical_claim_id(attacked))
        registry = replace(exact.registry, claims=(attacked,))
    else:
        exact = _retie_single_material_graph(
            request,
            evidence=replace(request.registry.evidence[0], normalized_excerpt="x" * 4096),
        )
        attacked = replace(exact.registry.evidence[0], normalized_excerpt="x" * 4097)
        attacked = replace(attacked, evidence_id=canonical_evidence_id(attacked))
        registry = replace(exact.registry, evidence=(attacked,))
    audit, provider = _assess(exact)
    assert audit.summary.passed
    assert len(provider.calls) == 1

    evaluator = Provider()
    with pytest.raises(CanonicalValidationError) as captured:
        canonical_validate_report(
            replace(exact, registry=registry),
            mode=ValidationMode.ASSESS,
            semantic_result_provider=evaluator,
        )
    assert captured.value.code == code
    assert evaluator.calls == []


def test_authority_ast_and_dependency_boundary() -> None:
    path = Path(module.__file__)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    authority = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "canonical_validate_report"
    ]
    assert len(authority) == 1
    assert sum(isinstance(item, ast.Return) for item in ast.walk(authority[0])) == 1
    assert (
        sum(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "ReportValidationAudit"
            for item in ast.walk(authority[0])
        )
        == 1
    )
    receipt_calls = [
        item
        for item in ast.walk(authority[0])
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "_build_validation_receipt"
    ]
    assert len(receipt_calls) == 1
    authority_text = ast.unparse(authority[0])
    assert (
        "_build_validation_receipt(value, summary, tuple(audits)) if mode is "
        "ValidationMode.ASSESS else None"
    ) in authority_text
    receipt_verifiers = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "verify_validation_receipt"
    ]
    assert len(receipt_verifiers) == 1
    assert not any(
        isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "evaluate"
        for item in ast.walk(receipt_verifiers[0])
    )
    assert (
        sum(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "evaluate"
            for item in ast.walk(authority[0])
        )
        == 1
    )
    forbidden = ("binder", "factory", "adapter", "seal", "token", "fingerprint")
    assert not any(item in source.lower() for item in forbidden)
    assert "receipt_origin" not in source.lower()
    imports = {
        item.module
        for item in ast.walk(tree)
        if isinstance(item, ast.ImportFrom) and item.module is not None
    }
    assert not any(item.startswith("medevidence.orchestration") for item in imports)
    production_root = path.parents[1]
    production_sources = tuple(production_root.rglob("*.py"))
    assert production_sources
    assert not any(
        "ReportValidationPort" in candidate.read_text(encoding="utf-8")
        for candidate in production_sources
    )
    for relative in ("orchestration/ports.py", "orchestration/__init__.py"):
        assert "ReportValidationPort" not in (production_root / relative).read_text(
            encoding="utf-8"
        )
    assert len(source.splitlines()) <= 1300
    baseline_lines = {
        "orchestration/workflow.py": 587,
        "orchestration/ports.py": 120,
        "orchestration/__init__.py": 97,
    }
    added_production_lines = len(source.splitlines())
    for relative, baseline in baseline_lines.items():
        current = len((production_root / relative).read_text(encoding="utf-8").splitlines())
        added_production_lines += max(0, current - baseline)
    # Owner-authorized receipt design: recompute exact additions without pinning wiring LOC.
    assert added_production_lines <= 1800, (
        f"added production lines {added_production_lines} exceed Owner ceiling 1800"
    )
