"""Contract tests for the framework-neutral M3 orchestration state."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    AcquisitionOutcomeRef,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourcePlanReasonCode,
    SourceType,
)
from medevidence.orchestration import (
    WORKFLOW_TOPOLOGY,
    EvidenceReference,
    ExportDestinationRef,
    GateStatus,
    OrchestrationState,
    PendingDraftRef,
    ReportStatus,
    ReportValidationState,
    SafetyDecision,
    SafetyOutcome,
    SafetyReason,
    SourceTaskState,
    SourceTaskStatus,
    TerminalSourceOutcomeRef,
    WorkflowDisposition,
    WorkflowNode,
    WorkflowPermissions,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
REPORT_ID = "report:sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64


def _task_id(source: SourceType) -> str:
    return f"source-task:{RUN_ID.removeprefix('run:')}:{source.value}"


def _scope(*sources: SourceType) -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test reaction"),
        ),
        date_range=None,
        selected_sources=sources or (SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=128,
            max_pages=2,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=20, max_payload_bytes=100_000),
    )


def _destination() -> ExportDestinationRef:
    return ExportDestinationRef(destination_id="destination:test")


def _state(scope: ResearchScope | None = None) -> OrchestrationState:
    return OrchestrationState(
        workflow_id="workflow:test",
        checkpoint_id="checkpoint:initial",
        run_id=RUN_ID,
        report_id=REPORT_ID,
        original_scope=scope or _scope(),
        destination=_destination(),
    )


def _plan(source: SourceType, status: PlanningStatus) -> M1BSourcePlanEntryV1:
    if status is PlanningStatus.SELECTED:
        return M1BSourcePlanEntryV1(source=source, planning_status=status)
    reason_code = {
        PlanningStatus.SKIPPED_NOT_APPLICABLE: (SourcePlanReasonCode.NOT_APPLICABLE_TO_SCOPE),
        PlanningStatus.SKIPPED_BY_POLICY: (SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED),
    }[status]
    return M1BSourcePlanEntryV1(
        source=source,
        planning_status=status,
        reason_code=reason_code,
        reason="Deterministic test policy reason.",
    )


def _terminal_ref(
    source: SourceType,
    *,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    result: ResultStatus = ResultStatus.MATCHES,
) -> TerminalSourceOutcomeRef:
    warnings = () if coverage is CoverageStatus.COMPLETE else ("source_degraded",)
    failure_id = "failure:test" if execution is ExecutionStatus.FAILED else None
    outcome = SourceOutcome(
        source=source,
        query_id=f"query:{source.value}",
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=ExecutionBounds(
            max_query_characters=128,
            max_pages=2,
            max_records=20,
            max_payload_bytes=100_000,
            max_total_seconds=30,
        ),
        valid_result_count=1 if result is ResultStatus.MATCHES else 0,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=warnings,
        failure_id=failure_id,
    )
    acquisition = AcquisitionOutcomeRef(
        run_id=RUN_ID,
        source=source,
        acquisition_id=f"acquisition:{source.value}",
        acquisition_intent_id="acquisition-intent:sha256:" + "c" * 64,
        acquisition_ordinal=0,
        operation="search",
        query_id=outcome.query_id,
        source_outcome_id=f"source-outcome:{source.value}",
        snapshot_id=f"snapshot:{source.value}",
    )
    return TerminalSourceOutcomeRef(acquisition=acquisition, outcome=outcome)


def _evidence(source: SourceType) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"evidence:{source.value}",
        source=source,
        snapshot_id=f"snapshot:{source.value}",
        content_hash=DIGEST,
        locator_ref=f"locator:{source.value}",
    )


def test_topology_and_permissions_are_exact_and_closed() -> None:
    assert tuple(node.value for node in WORKFLOW_TOPOLOGY) == (
        "scope_and_safety",
        "plan_sources",
        "collect_evidence",
        "synthesize_claims",
        "validate_report",
        "save_pending_draft",
        "request_export_approval",
        "finalize_and_export",
    )
    permissions = WorkflowPermissions()
    assert permissions.export_requires_approval is True
    assert permissions.retrieved_content_can_change_permissions is False

    with pytest.raises(ValidationError):
        WorkflowPermissions(allowed_nodes=(WorkflowNode.SCOPE_AND_SAFETY,))
    with pytest.raises(ValidationError):
        WorkflowPermissions(retrieved_content_can_change_permissions=True)  # type: ignore[arg-type]


def test_initial_state_is_versioned_immutable_and_reference_only() -> None:
    state = _state()
    assert state.schema_version == "m3.orchestration-state.v1"
    assert state.current_node is WorkflowNode.SCOPE_AND_SAFETY
    assert state.report_status is ReportStatus.DRAFT
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="evidence:test",
            source=SourceType.PUBMED,
            snapshot_id="snapshot:test",
            content_hash=DIGEST,
            locator_ref="locator:test",
            raw_payload=b"forbidden",
        )


def test_safety_contract_has_internal_codes_without_message_text() -> None:
    permitted = SafetyDecision(
        outcome=SafetyOutcome.PERMITTED,
        reason=SafetyReason.PERMITTED_RESEARCH_SCOPE,
        policy_version="policy:test",
    )
    assert "message" not in permitted.model_fields_set
    with pytest.raises(ValidationError):
        SafetyDecision(
            outcome=SafetyOutcome.PERMITTED,
            reason=SafetyReason.UNSAFE_SCOPE,
            policy_version="policy:test",
        )


def test_skipped_source_has_no_task_or_fabricated_outcome() -> None:
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    base = _state(scope)
    pubmed_task = SourceTaskState(
        task_id=_task_id(SourceType.PUBMED),
        source=SourceType.PUBMED,
    )
    valid = OrchestrationState.model_validate(
        {
            **base.model_dump(mode="python"),
            "interpreted_scope": scope,
            "source_plan": (
                _plan(SourceType.DAILYMED, PlanningStatus.SKIPPED_BY_POLICY),
                _plan(SourceType.PUBMED, PlanningStatus.SELECTED),
            ),
            "source_tasks": (pubmed_task,),
        }
    )
    assert tuple(task.source for task in valid.source_tasks) == (SourceType.PUBMED,)

    with pytest.raises(ValidationError, match="only selected sources"):
        OrchestrationState.model_validate(
            {
                **valid.model_dump(mode="python"),
                "source_tasks": (
                    SourceTaskState(
                        task_id=_task_id(SourceType.DAILYMED),
                        source=SourceType.DAILYMED,
                        status=SourceTaskStatus.TERMINAL,
                        attempts=1,
                        terminal_outcome_ref=_terminal_ref(SourceType.DAILYMED),
                    ),
                    pubmed_task,
                ),
            }
        )


@pytest.mark.parametrize(
    ("execution", "coverage", "result"),
    (
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
        (ExecutionStatus.FAILED, CoverageStatus.UNAVAILABLE, ResultStatus.INDETERMINATE),
    ),
)
def test_partial_and_unavailable_source_outcomes_remain_visible(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> None:
    reference = _terminal_ref(
        SourceType.PUBMED,
        execution=execution,
        coverage=coverage,
        result=result,
    )
    task = SourceTaskState(
        task_id="task:pubmed",
        source=SourceType.PUBMED,
        status=SourceTaskStatus.TERMINAL,
        attempts=1,
        terminal_outcome_ref=reference,
        evidence_refs=(_evidence(SourceType.PUBMED),) if result is ResultStatus.MATCHES else (),
    )
    assert task.terminal_outcome_ref is not None
    assert task.terminal_outcome_ref.outcome.coverage_status is coverage
    assert task.terminal_outcome_ref.outcome.execution_status is execution


def test_failed_source_can_never_be_no_match() -> None:
    with pytest.raises(ValidationError, match="invalid execution/coverage/result"):
        _terminal_ref(
            SourceType.PUBMED,
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.PARTIAL,
            result=ResultStatus.NO_MATCH,
        )


def test_task_requires_terminal_reference_only_after_execution() -> None:
    with pytest.raises(ValidationError, match="must coexist"):
        SourceTaskState(
            task_id="task:pubmed",
            source=SourceType.PUBMED,
            status=SourceTaskStatus.TERMINAL,
            attempts=1,
        )
    with pytest.raises(ValidationError, match="unexecuted source task"):
        SourceTaskState(
            task_id="task:pubmed",
            source=SourceType.PUBMED,
            evidence_refs=(_evidence(SourceType.PUBMED),),
        )


def test_terminal_reference_rejects_cross_source_binding() -> None:
    reference = _terminal_ref(SourceType.PUBMED)
    with pytest.raises(ValidationError, match="terminal outcome source"):
        SourceTaskState(
            task_id="task:dailymed",
            source=SourceType.DAILYMED,
            status=SourceTaskStatus.TERMINAL,
            attempts=1,
            terminal_outcome_ref=reference,
        )


def test_validation_requires_all_gates_and_reasons_for_failure() -> None:
    passed = ReportValidationState(
        structural_citation_gate=GateStatus.PASSED,
        semantic_support_gate=GateStatus.PASSED,
        safety_policy_gate=GateStatus.PASSED,
    )
    assert passed.passed
    with pytest.raises(ValidationError, match="requires a reason"):
        ReportValidationState(
            structural_citation_gate=GateStatus.FAILED,
            semantic_support_gate=GateStatus.PASSED,
            safety_policy_gate=GateStatus.PASSED,
        )


def test_pending_review_requires_passing_validation_and_matching_hash() -> None:
    base = _state()
    pending = PendingDraftRef(
        persistence_id="persistence:test",
        report_id=REPORT_ID,
        report_content_hash=DIGEST,
    )
    with pytest.raises(ValidationError, match="validated synthesis"):
        OrchestrationState.model_validate(
            {
                **base.model_dump(mode="python"),
                "pending_draft": pending,
                "report_status": ReportStatus.PENDING_REVIEW,
            }
        )


def test_terminal_disposition_cannot_retain_a_current_node() -> None:
    base = _state()
    with pytest.raises(ValidationError, match="terminal workflow"):
        OrchestrationState.model_validate(
            {
                **base.model_dump(mode="python"),
                "disposition": WorkflowDisposition.POLICY_BLOCKED,
            }
        )


def test_utc_review_time_fixture_is_timezone_aware() -> None:
    assert datetime(2026, 1, 1, tzinfo=UTC).utcoffset() is not None
