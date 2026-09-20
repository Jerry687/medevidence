"""V3 task evidence must bind its actual immutable child acquisition."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.unit.orchestration.test_source_task_projection import _collected, _operations, _result
from tests.unit.tools.test_report_validation import REPORT_ID, SOURCE_PLAN_ID
from tests.unit.tools.test_report_validation_v3 import _LowV3Port

from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceType,
)
from medevidence.orchestration.contracts import (
    SourceOperationKind,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
    TerminalSourceOperationResult,
)
from medevidence.orchestration.source_task_projection import source_operation_observation
from medevidence.orchestration.validation_projection import build_validation_request_projection
from medevidence.tools import report_validation as rv
from medevidence.tools.report_validation_source_bindings_v3 import (
    EvidenceChildAcquisitionBindingV3,
    TerminalTaskInputV3,
    evidence_acquisition_matches,
)


def _task(source: SourceType) -> TerminalTaskInputV3:
    kinds = (
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH)
        if source is SourceType.PUBMED
        else (SourceOperationKind.FAERS_AGGREGATE, SourceOperationKind.FAERS_AGGREGATE)
    )
    operations = _operations(source, kinds)
    results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=1,
            pages=1,
            warnings=("faers_mandatory_limitations",) if source is SourceType.FAERS else (),
        )
        for operation in operations
    )
    representative = results[0].acquisition
    observed = results[1].acquisition
    observation = source_operation_observation(
        operation=operations[1],
        acquisition=observed,
        evidence_id=f"evidence:{source.value}:child",
        content_hash="sha256:" + "b" * 64,
        locator_ref=f"locator:{source.value}:child",
    )
    bounds = results[0].outcome.configured_bounds
    return TerminalTaskInputV3(
        task_id=operations[0].task_id,
        source=source,
        terminal=True,
        acquisition=rv.AcquisitionInput(
            run_id=representative.run_id,
            source=source,
            acquisition_id=representative.acquisition_id,
            acquisition_intent_id=representative.acquisition_intent_id,
            acquisition_ordinal=representative.ordinal,
            operation="search",
            query_id=representative.query_id,
            source_outcome_id=representative.source_outcome_id,
            snapshot_id=representative.snapshot_id,
        ),
        outcome=rv.SourceOutcomeInput(
            source=source,
            query_id=results[0].outcome.query_id,
            execution_status=ExecutionStatus.SUCCEEDED,
            coverage_status=CoverageStatus.COMPLETE,
            result_status=ResultStatus.MATCHES,
            configured_bounds=rv.ExecutionBoundsInput(
                bounds.max_query_characters,
                bounds.max_pages,
                bounds.max_records,
                bounds.max_payload_bytes,
                bounds.max_total_seconds,
            ),
            valid_result_count=1,
            pages_completed=1,
            truncated=False,
            warning_codes=("faers_mandatory_limitations",) if source is SourceType.FAERS else (),
            failure_id=None,
        ),
        evidence_refs=(
            rv.EvidenceReferenceInput(
                observation.evidence_id,
                source,
                observation.snapshot_id,
                observation.content_hash,
                observation.locator_ref,
            ),
        ),
        operation_acquisition_ids=tuple(item.acquisition.acquisition_id for item in results),
        evidence_child_bindings=(
            EvidenceChildAcquisitionBindingV3(
                run_id=observed.run_id,
                task_id=observed.task_id,
                attempt_id=observed.attempt_id,
                source=source,
                kind=observed.kind.value,
                ordinal=observed.ordinal,
                query_id=observed.query_id,
                operation_id=observed.operation_id,
                acquisition_id=observed.acquisition_id,
                acquisition_intent_id=observed.acquisition_intent_id,
                source_outcome_id=observed.source_outcome_id,
                snapshot_id=observed.snapshot_id,
                evidence_id=observation.evidence_id,
                content_hash=observation.content_hash,
                locator_ref=observation.locator_ref,
            ),
        ),
    )


@pytest.mark.parametrize("source", (SourceType.PUBMED, SourceType.FAERS))
def test_actual_child_snapshot_passes_and_legacy_representative_rejects(source: SourceType) -> None:
    task = _task(source)
    assert task.acquisition.snapshot_id != task.evidence_refs[0].snapshot_id
    assert rv._copy_task(task) == task
    assert evidence_acquisition_matches(task, task.evidence_refs[0])
    legacy = rv.TerminalTaskInput(
        task.task_id, task.source, task.terminal, task.acquisition, task.outcome, task.evidence_refs
    )
    assert rv._copy_task(legacy) == legacy
    assert not evidence_acquisition_matches(legacy, legacy.evidence_refs[0])


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "run:foreign"),
        ("task_id", "source-task:foreign"),
        ("attempt_id", "source-task-attempt:foreign"),
        ("ordinal", 0),
        ("kind", "pubmed_search"),
        ("query_id", "query:foreign"),
        ("operation_id", "source-operation:foreign"),
        ("acquisition_id", "source-operation-acquisition:sha256:" + "f" * 64),
        ("acquisition_intent_id", "acquisition-intent:sha256:" + "f" * 64),
        ("source_outcome_id", "source-operation-outcome:foreign"),
        ("snapshot_id", "snapshot:foreign"),
        ("content_hash", "sha256:" + "f" * 64),
        ("locator_ref", "locator:foreign"),
    ),
)
def test_foreign_child_dimension_fails_before_stage2(field: str, value: object) -> None:
    task = _task(SourceType.PUBMED)
    changed = replace(task.evidence_child_bindings[0], **{field: value})
    with pytest.raises(rv.CanonicalValidationError):
        rv._copy_task(replace(task, evidence_child_bindings=(changed,)))


def test_missing_swapped_duplicate_or_foreign_task_mode_fails() -> None:
    task = _task(SourceType.PUBMED)
    with pytest.raises(rv.CanonicalValidationError):
        replace(task, evidence_child_bindings=())
    for ids in (
        tuple(reversed(task.operation_acquisition_ids)),
        (task.operation_acquisition_ids[0],) * 2,
        (task.operation_acquisition_ids[1],),
    ):
        with pytest.raises(rv.CanonicalValidationError):
            rv._copy_task(replace(task, operation_acquisition_ids=ids))
    with pytest.raises(rv.CanonicalValidationError, match="forbidden_in_legacy"):
        from medevidence.tools.report_validation_source_bindings_v3 import (
            validate_task_configuration,
        )

        validate_task_configuration((task,), rv.M3_VALIDATION_CONFIGURATION_V2)


def test_faers_multiple_buckets_may_share_one_authenticated_child_acquisition() -> None:
    task = _task(SourceType.FAERS)
    second_ref = rv.EvidenceReferenceInput(
        "evidence:faers:second",
        SourceType.FAERS,
        task.evidence_refs[0].snapshot_id,
        "sha256:" + "c" * 64,
        "locator:faers:second",
    )
    second_binding = replace(
        task.evidence_child_bindings[0],
        evidence_id=second_ref.evidence_id,
        content_hash=second_ref.content_hash,
        locator_ref=second_ref.locator_ref,
    )
    expanded = replace(
        task,
        evidence_refs=(*task.evidence_refs, second_ref),
        evidence_child_bindings=(*task.evidence_child_bindings, second_binding),
    )
    assert rv._copy_task(expanded) == expanded
    assert {item.acquisition_id for item in expanded.evidence_child_bindings} == {
        task.operation_acquisition_ids[1]
    }


def _v3_report_with_child_evidence(
    source: SourceType = SourceType.PUBMED,
) -> rv.CanonicalReportRequest:
    task = _task(source)
    scope = ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test event"),
        ),
        date_range=None,
        selected_sources=(source,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    scope_input = rv.ScopeInput(
        scope.scope_id,
        tuple((item.concept_id, item.preferred_term) for item in scope.drugs),
        tuple((item.concept_id, item.preferred_term) for item in scope.adverse_reactions),
        None,
        scope.selected_sources,
        scope.comparison_intent,
        scope.query_bounds.max_query_characters,
        scope.query_bounds.max_pages,
        scope.query_bounds.max_total_seconds,
        scope.result_bounds.max_records,
        scope.result_bounds.max_payload_bytes,
    )
    evidence_ref = task.evidence_refs[0]
    evidence = rv.EvidenceInput(
        evidence_id="evidence:sha256:" + "0" * 64,
        authorized_run_id=task.acquisition.run_id,
        source=task.source,
        source_record_id=f"record:{source.value}:child",
        source_version="version:test",
        snapshot_id=evidence_ref.snapshot_id,
        content_hash=evidence_ref.content_hash,
        locators=(evidence_ref.locator_ref,),
        permitted_claim_classes=frozenset(),
        permitted_inference_uses=frozenset(),
        normalized_excerpt="Verified title; abstract unavailable.",
        numerical_facts=(),
    )
    evidence = replace(evidence, evidence_id=rv.canonical_evidence_id(evidence))
    task = replace(
        task,
        evidence_refs=(replace(evidence_ref, evidence_id=evidence.evidence_id),),
        evidence_child_bindings=(
            replace(task.evidence_child_bindings[0], evidence_id=evidence.evidence_id),
        ),
        outcome=replace(
            task.outcome,
            configured_bounds=rv.ExecutionBoundsInput(
                512, 1 if source is SourceType.PUBMED else 5, 100, 5_242_880, 30
            ),
        ),
    )
    registry = rv.ValidationRegistryInput(
        run_id=task.acquisition.run_id,
        scope_id=scope.scope_id,
        claims=(),
        citations=(),
        evidence=(evidence,),
        semantic_expectations=(),
        evaluator_identity=rv.EvaluatorIdentityInput(
            rv.M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
            rv.M3_SEMANTIC_EVALUATION_V2,
        ),
        configuration_version=rv.M3_VALIDATION_CONFIGURATION_V3,
    )
    synthesis = rv.SynthesisInput("sha256:" + "0" * 64, (), (), (), (), task.outcome.warning_codes)
    request = rv.CanonicalReportRequest(
        task.acquisition.run_id,
        REPORT_ID,
        scope_input,
        SOURCE_PLAN_ID,
        (source,),
        (task,),
        synthesis,
        registry,
    )
    return replace(
        request,
        synthesis=replace(synthesis, report_content_hash=rv.canonical_report_content_hash(request)),
    )


@pytest.mark.parametrize("source", (SourceType.PUBMED, SourceType.FAERS))
def test_v3_stage1_uses_child_not_representative(source: SourceType) -> None:
    request = _v3_report_with_child_evidence(source)
    provider = _LowV3Port()
    audit = rv.canonical_validate_report(
        request, mode=rv.ValidationMode.ASSESS, semantic_result_provider_v2=provider
    )
    assert provider.calls == 0
    assert "evidence_acquisition_snapshot_drift" not in audit.summary.reason_codes
    assert audit.stage1_receipt is not None
    assert audit.receipt is not None
    stored = rv.StoredValidationInput(
        audit.summary.structural_passed,
        audit.summary.semantic_passed,
        audit.summary.safety_passed,
        audit.summary.reason_codes,
    )
    replay_request = replace(request, stored_validation=stored)
    replay = rv.canonical_validate_report(replay_request, mode=rv.ValidationMode.VERIFY_BINDING)
    assert replay.summary == audit.summary
    assert rv.verify_validation_receipt(audit.receipt, request=replay_request, audit=replay)
    assert provider.calls == 0
    task = request.tasks[0]
    legacy = rv.TerminalTaskInput(
        task.task_id, task.source, task.terminal, task.acquisition, task.outcome, task.evidence_refs
    )
    legacy_request = replace(request, tasks=(legacy,))
    legacy_request = replace(
        legacy_request,
        synthesis=replace(
            legacy_request.synthesis,
            report_content_hash=rv.canonical_report_content_hash(legacy_request),
        ),
    )
    legacy_audit = rv.canonical_validate_report(
        legacy_request, mode=rv.ValidationMode.ASSESS, semantic_result_provider_v2=provider
    )
    assert provider.calls == 0
    assert "evidence_acquisition_snapshot_drift" in legacy_audit.summary.reason_codes


def test_v3_projection_uses_actual_terminal_operation_observation() -> None:
    admitted = _v3_report_with_child_evidence()
    evidence = admitted.registry.evidence[0]
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    search, fetch = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=1,
            pages=1,
        )
        for operation in operations
    )
    observation = source_operation_observation(
        operation=operations[1],
        acquisition=fetch.acquisition,
        evidence_id=evidence.evidence_id,
        content_hash=evidence.content_hash,
        locator_ref=evidence.locators[0],
    )
    fetch = TerminalSourceOperationResult(
        operation=fetch.operation,
        attempt=fetch.attempt,
        acquisition=fetch.acquisition,
        outcome=fetch.outcome,
        observations=(observation,),
    )
    collected = _collected(
        operations,
        (search, fetch),
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        valid_result_count=1,
        pages_completed=1,
    )
    task = SourceTaskState(
        task_id=operations[0].task_id,
        source=SourceType.PUBMED,
        required_operations=operations,
        operation_results=(search, fetch),
        status=SourceTaskStatus.TERMINAL,
        attempts=1,
        terminal_outcome_ref=collected.terminal_outcome_ref,
        evidence_refs=collected.evidence_refs,
    )
    scope = ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test event"),
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    synthesis = SynthesisState(
        report_content_hash=admitted.synthesis.report_content_hash,
        claims=(),
        citations=(),
        comparability_refs=(),
        conflict_refs=(),
        warning_codes=(),
    )
    projected = build_validation_request_projection(
        run_id=admitted.run_id,
        report_id=admitted.report_id,
        scope=scope,
        source_plan=(
            M1BSourcePlanEntryV1(source=SourceType.PUBMED, planning_status=PlanningStatus.SELECTED),
        ),
        source_tasks=(task,),
        synthesis=synthesis,
        registry=admitted.registry,
    )
    exact_task = projected.tasks[0]
    assert type(exact_task) is TerminalTaskInputV3
    assert (
        exact_task.operation_acquisition_ids
        == collected.terminal_outcome_ref.operation_acquisition_ids
    )
    assert exact_task.evidence_child_bindings[0].acquisition_id == fetch.acquisition.acquisition_id
    assert exact_task.evidence_child_bindings[0].snapshot_id == fetch.acquisition.snapshot_id
    assert exact_task.acquisition.snapshot_id == search.acquisition.snapshot_id
    assert rv._copy_task(exact_task) == exact_task
