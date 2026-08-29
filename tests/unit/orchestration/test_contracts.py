"""Contract tests for the framework-neutral M3 orchestration state."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    FAERS_MANDATORY_LIMITATIONS,
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
    derive_identity,
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
    ReviewDecision,
    ReviewRecord,
    SafetyDecision,
    SafetyOutcome,
    SafetyReason,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
    TerminalSourceOutcomeRef,
    ValidationReceiptRef,
    WorkflowDisposition,
    WorkflowNode,
    WorkflowPermissions,
    source_task_attempt,
)
from medevidence.orchestration.contracts import (
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    TerminalSourceOperationResult,
)
from medevidence.orchestration.source_task_projection import (
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
REPORT_ID = "report:sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
SCOPE_ID = "scope:sha256:" + "d" * 64


def _task_id(source: SourceType) -> str:
    return f"source-task:{RUN_ID.removeprefix('run:')}:{source.value}"


def _required_operations(source: SourceType):
    kinds = {
        SourceType.PUBMED: (SourceOperationKind.PUBMED_SEARCH,),
        SourceType.DAILYMED: (SourceOperationKind.DAILYMED_DISCOVERY,),
        SourceType.FAERS: (SourceOperationKind.FAERS_AGGREGATE,),
        SourceType.CADEC: (SourceOperationKind.CADEC_VERIFY, SourceOperationKind.CADEC_SEARCH),
    }[source]
    return tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=source,
            ordinal=index,
            kind=kind,
            query_id=f"query:{source.value}:{index}",
            input_refs=_input_refs(kind, index),
        )
        for index, kind in enumerate(kinds)
    )


def _input_refs(kind: SourceOperationKind, index: int):
    roles = {
        SourceOperationKind.PUBMED_SEARCH: (SourceOperationInputRole.QUERY_PLAN,),
        SourceOperationKind.PUBMED_FETCH: (SourceOperationInputRole.PUBMED_PMID,),
        SourceOperationKind.DAILYMED_DISCOVERY: (SourceOperationInputRole.REQUEST,),
        SourceOperationKind.DAILYMED_FETCH: (
            SourceOperationInputRole.DAILYMED_DECISION,
            SourceOperationInputRole.CANDIDATE,
            SourceOperationInputRole.SETID,
            SourceOperationInputRole.SPL_VERSION,
        ),
        SourceOperationKind.FAERS_AGGREGATE: (SourceOperationInputRole.REQUEST,),
        SourceOperationKind.CADEC_VERIFY: (
            SourceOperationInputRole.ASSET,
            SourceOperationInputRole.MEMBERSHIP,
        ),
        SourceOperationKind.CADEC_SEARCH: (SourceOperationInputRole.QUERY_PLAN,),
    }[kind]
    return tuple(
        SourceOperationInputRef(role=role, value=f"input:{kind.value}:{role.value}:{index}")
        for role in roles
    )


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
    return TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity("source-task-terminal-outcome", outcome),
        operation_acquisition_ids=(acquisition.acquisition_id,),
        acquisition=acquisition,
        outcome=outcome,
    )


def _terminal_task(
    source: SourceType,
    *,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    result: ResultStatus = ResultStatus.MATCHES,
) -> SourceTaskState:
    operations = _required_operations(source)
    if source is SourceType.PUBMED and result is ResultStatus.MATCHES:
        search = operations[0]
        operations = (
            search,
            required_source_operation(
                run_id=RUN_ID,
                scope_id=SCOPE_ID,
                source=SourceType.PUBMED,
                ordinal=1,
                kind=SourceOperationKind.PUBMED_FETCH,
                query_id=search.query_id,
                input_refs=_input_refs(SourceOperationKind.PUBMED_FETCH, 1),
            ),
        )
    attempt = source_task_attempt(_task_id(source), 1)
    operation_results = []
    for operation in operations:
        warnings = () if coverage is CoverageStatus.COMPLETE else ("source_degraded",)
        operation_outcome = SourceOutcome(
            source=source,
            query_id=operation.query_id,
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
            failure_id="failure:test" if execution is ExecutionStatus.FAILED else None,
        )
        acquisition = source_operation_acquisition(
            operation=operation,
            attempt_id=attempt.attempt_id,
            acquisition_intent_id=derive_identity("acquisition-intent", operation.operation_id),
            outcome=operation_outcome,
            snapshot_id=f"snapshot:{source.value}:{operation.ordinal}",
        )
        observations = ()
        if result is ResultStatus.MATCHES:
            observations = (
                source_operation_observation(
                    operation=operation,
                    acquisition=acquisition,
                    evidence_id=f"evidence:{source.value}:{operation.ordinal}",
                    content_hash=DIGEST,
                    locator_ref=f"locator:{source.value}:{operation.ordinal}",
                ),
            )
        operation_results.append(
            TerminalSourceOperationResult(
                operation=operation,
                attempt=attempt,
                acquisition=acquisition,
                outcome=operation_outcome,
                observations=observations,
            )
        )
    terminal_results = tuple(operation_results)
    aggregate_outcome = canonical_terminal_source_outcome(operations, terminal_results)
    representative = terminal_results[0].acquisition
    terminal_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity("source-task-terminal-outcome", aggregate_outcome),
        operation_acquisition_ids=tuple(
            item.acquisition.acquisition_id for item in terminal_results
        ),
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=source,
            acquisition_id=representative.acquisition_id,
            acquisition_intent_id=representative.acquisition_intent_id,
            acquisition_ordinal=representative.ordinal,
            operation="search",
            query_id=representative.query_id,
            source_outcome_id=representative.source_outcome_id,
            snapshot_id=representative.snapshot_id,
        ),
        outcome=aggregate_outcome,
    )
    evidence = tuple(
        observation.evidence_reference
        for operation_result in terminal_results
        for observation in operation_result.observations
    )
    return SourceTaskState(
        task_id=_task_id(source),
        source=source,
        required_operations=operations,
        operation_results=terminal_results,
        status=SourceTaskStatus.TERMINAL,
        attempts=1,
        terminal_outcome_ref=terminal_ref,
        evidence_refs=evidence,
        limitations=(
            CADEC_MANDATORY_LIMITATIONS
            if source is SourceType.CADEC
            else FAERS_MANDATORY_LIMITATIONS
            if source is SourceType.FAERS
            else ()
        ),
    )


def _evidence(source: SourceType) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"evidence:{source.value}",
        source=source,
        snapshot_id=f"snapshot:{source.value}",
        content_hash=DIGEST,
        locator_ref=f"locator:{source.value}",
    )


def _validated_state() -> OrchestrationState:
    scope = _scope()
    base = _state(scope)
    task = _terminal_task(SourceType.PUBMED)
    return OrchestrationState.model_validate(
        {
            **base.model_dump(mode="python"),
            "interpreted_scope": scope,
            "safety_decision": SafetyDecision(
                outcome=SafetyOutcome.PERMITTED,
                reason=SafetyReason.PERMITTED_RESEARCH_SCOPE,
                policy_version="policy:test",
            ),
            "source_plan": (_plan(SourceType.PUBMED, PlanningStatus.SELECTED),),
            "source_tasks": (task,),
            "synthesis": SynthesisState(
                report_content_hash=DIGEST,
                claims=(),
                citations=(),
                comparability_refs=(),
                conflict_refs=(),
                warning_codes=(),
            ),
            "validation": ReportValidationState(
                structural_citation_gate=GateStatus.PASSED,
                semantic_support_gate=GateStatus.PASSED,
                safety_policy_gate=GateStatus.PASSED,
            ),
            "validation_receipt_ref": ValidationReceiptRef(
                receipt_id="validation-receipt:sha256:" + "d" * 64,
                receipt_content_hash="sha256:" + "e" * 64,
            ),
            "completed_nodes": WORKFLOW_TOPOLOGY[:5],
            "current_node": WorkflowNode.SAVE_PENDING_DRAFT,
        }
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
    assert state.schema_version == "m3.orchestration-state.v2"
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

    with pytest.raises(ValidationError, match=r"m3\.orchestration-state\.v2"):
        OrchestrationState.model_validate(
            {**state.model_dump(mode="python"), "schema_version": "m3.orchestration-state.v1"}
        )


def test_validation_receipt_reference_is_exact_and_cannot_inline_authority() -> None:
    state = _validated_state()
    receipt_ref = state.validation_receipt_ref
    assert receipt_ref is not None
    assert receipt_ref.schema_version == "m3.validation-receipt-ref.v1"
    assert set(type(receipt_ref).model_fields) == {
        "schema_version",
        "receipt_id",
        "receipt_content_hash",
    }
    inline_looking_receipt = {
        "marker": "M3_VALIDATION_RECEIPT_V1",
        "receipt_id": receipt_ref.receipt_id,
        "receipt_content_hash": receipt_ref.receipt_content_hash,
        "run_id": RUN_ID,
        "report_id": REPORT_ID,
        "report_content_hash": DIGEST,
        "validation_input_hash": "sha256:" + "f" * 64,
        "structural_passed": True,
        "semantic_passed": True,
        "safety_passed": True,
    }

    with pytest.raises(ValidationError):
        ValidationReceiptRef(
            receipt_id="validation-receipt:sha256:" + "d" * 64,
            receipt_content_hash="sha256:" + "e" * 64,
            receipt=inline_looking_receipt,
        )
    with pytest.raises(ValidationError):
        ValidationReceiptRef(
            receipt_id="receipt:caller-asserted",
            receipt_content_hash="sha256:" + "e" * 64,
        )
    with pytest.raises(ValidationError):
        OrchestrationState.model_validate(
            {
                **state.model_dump(mode="python"),
                "validation_receipt": inline_looking_receipt,
            }
        )


def test_completed_assessment_and_receipt_reference_must_coexist_exactly() -> None:
    state = _validated_state()
    with pytest.raises(ValidationError, match="persisted receipt reference"):
        OrchestrationState.model_validate(
            {**state.model_dump(mode="python"), "validation_receipt_ref": None}
        )
    initial = _state()
    with pytest.raises(ValidationError, match="completed assessment"):
        OrchestrationState.model_validate(
            {
                **initial.model_dump(mode="python"),
                "validation_receipt_ref": state.validation_receipt_ref,
            }
        )


def test_review_record_v2_requires_exact_pending_draft_identity() -> None:
    review = ReviewRecord(
        review_id="review:test",
        report_id=REPORT_ID,
        report_content_hash=DIGEST,
        pending_draft_persistence_id="pending-draft:test",
        destination=_destination(),
        source_outcome_refs=(_terminal_ref(SourceType.PUBMED),),
        warning_codes=(),
        decision=ReviewDecision.APPROVE,
        reviewer_id="reviewer:test",
        decided_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert review.schema_version == "m3.review-record.v2"
    assert review.pending_draft_persistence_id == "pending-draft:test"
    with pytest.raises(ValidationError, match=r"m3\.review-record\.v2"):
        ReviewRecord.model_validate(
            {**review.model_dump(mode="python"), "schema_version": "m3.review-record.v1"}
        )
    payload = review.model_dump(mode="python")
    payload.pop("pending_draft_persistence_id")
    with pytest.raises(ValidationError):
        ReviewRecord.model_validate(payload)


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
        required_operations=_required_operations(SourceType.PUBMED),
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
                        required_operations=_required_operations(SourceType.DAILYMED),
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
    task = _terminal_task(
        SourceType.PUBMED,
        execution=execution,
        coverage=coverage,
        result=result,
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
            task_id=_task_id(SourceType.PUBMED),
            source=SourceType.PUBMED,
            required_operations=_required_operations(SourceType.PUBMED),
            status=SourceTaskStatus.TERMINAL,
            attempts=1,
        )
    with pytest.raises(ValidationError, match="unexecuted source task"):
        SourceTaskState(
            task_id=_task_id(SourceType.PUBMED),
            source=SourceType.PUBMED,
            required_operations=_required_operations(SourceType.PUBMED),
            evidence_refs=(_evidence(SourceType.PUBMED),),
        )


def test_pristine_pending_task_may_defer_operation_planning() -> None:
    task = SourceTaskState(
        task_id=_task_id(SourceType.PUBMED),
        source=SourceType.PUBMED,
    )
    assert task.status is SourceTaskStatus.PENDING
    assert task.required_operations == ()


def test_nonempty_pending_planned_task_is_valid() -> None:
    task = SourceTaskState(
        task_id=_task_id(SourceType.PUBMED),
        source=SourceType.PUBMED,
        required_operations=_required_operations(SourceType.PUBMED),
    )
    assert len(task.required_operations) == 1


def test_running_task_round_trips_durable_operation_progress_prefix() -> None:
    terminal = _terminal_task(SourceType.PUBMED)
    first_result = terminal.operation_results[0]
    running = SourceTaskState(
        task_id=terminal.task_id,
        source=terminal.source,
        required_operations=terminal.required_operations,
        operation_results=(first_result,),
        status=SourceTaskStatus.RUNNING,
        attempts=first_result.attempt.attempt_number,
        active_attempt=first_result.attempt,
    )

    assert SourceTaskState.model_validate(running.model_dump(mode="python")) == running


def test_running_progress_rejects_foreign_active_attempt() -> None:
    terminal = _terminal_task(SourceType.PUBMED)
    first_result = terminal.operation_results[0]
    foreign_attempt = source_task_attempt(terminal.task_id, 2)
    with pytest.raises(ValidationError, match="exact active attempt"):
        SourceTaskState(
            task_id=terminal.task_id,
            source=terminal.source,
            required_operations=terminal.required_operations,
            operation_results=(first_result,),
            status=SourceTaskStatus.RUNNING,
            attempts=foreign_attempt.attempt_number,
            active_attempt=foreign_attempt,
        )


@pytest.mark.parametrize(
    "status",
    (
        SourceTaskStatus.PENDING,
        SourceTaskStatus.RETRY_WAIT,
        SourceTaskStatus.FAILED,
    ),
)
def test_pending_retry_and_failed_tasks_cannot_retain_operation_progress(
    status: SourceTaskStatus,
) -> None:
    terminal = _terminal_task(SourceType.PUBMED)
    first_result = terminal.operation_results[0]
    with pytest.raises(ValidationError, match="only a running task"):
        SourceTaskState(
            task_id=terminal.task_id,
            source=terminal.source,
            required_operations=terminal.required_operations,
            operation_results=(first_result,),
            status=status,
            attempts=0 if status is SourceTaskStatus.PENDING else 1,
        )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "status": SourceTaskStatus.RUNNING,
            "attempts": 1,
            "active_attempt": source_task_attempt(_task_id(SourceType.PUBMED), 1),
        },
        {"status": SourceTaskStatus.RETRY_WAIT, "attempts": 1},
        {"status": SourceTaskStatus.FAILED, "attempts": 1},
        {"status": SourceTaskStatus.TERMINAL, "attempts": 1},
    ),
)
def test_nonpending_or_nonpristine_task_requires_operation_plan(payload) -> None:
    with pytest.raises(ValidationError, match="nonempty operation plan"):
        SourceTaskState(
            task_id=_task_id(SourceType.PUBMED),
            source=SourceType.PUBMED,
            **payload,
        )


def test_terminal_reference_rejects_cross_source_binding() -> None:
    reference = _terminal_ref(SourceType.PUBMED)
    daily_task = _terminal_task(SourceType.DAILYMED)
    with pytest.raises(ValidationError, match="terminal outcome source"):
        SourceTaskState.model_validate(
            {
                **daily_task.model_dump(mode="python"),
                "terminal_outcome_ref": reference,
            }
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
