"""Executable transition tests for the bounded controlled workflow."""

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
    SourceType,
)
from medevidence.orchestration import (
    MAX_SOURCE_TASK_ATTEMPTS,
    ClaimReference,
    CollectedEvidenceResult,
    CollectionFailureClassification,
    ControlledOrchestrationWorkflow,
    EvidenceReference,
    ExportDestinationRef,
    ExportRecord,
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
    ScopeSafetyEvaluation,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
    TerminalSourceOutcomeRef,
    WorkflowDisposition,
    WorkflowExecutionError,
    WorkflowNode,
    WorkflowTransitionError,
    source_task_attempt,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
REPORT_ID = "report:sha256:" + "a" * 64
HASH_ONE = "sha256:" + "1" * 64
HASH_TWO = "sha256:" + "2" * 64


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


def _initial(scope: ResearchScope | None = None) -> OrchestrationState:
    return OrchestrationState(
        workflow_id="workflow:test",
        checkpoint_id="checkpoint:initial",
        run_id=RUN_ID,
        report_id=REPORT_ID,
        original_scope=scope or _scope(),
        destination=ExportDestinationRef(destination_id="destination:test"),
    )


def _collected_result(
    source: SourceType,
    *,
    attempt: SourceTaskAttemptRef | None = None,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
) -> CollectedEvidenceResult:
    if attempt is None:
        task_id = f"source-task:{RUN_ID.removeprefix('run:')}:{source.value}"
        attempt = source_task_attempt(task_id, 1)
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
        warning_codes=() if coverage is CoverageStatus.COMPLETE else ("source_degraded",),
        failure_id="failure:test" if execution is ExecutionStatus.FAILED else None,
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
    evidence = ()
    if result is ResultStatus.MATCHES:
        evidence = (
            EvidenceReference(
                evidence_id=f"evidence:{source.value}",
                source=source,
                snapshot_id=f"snapshot:{source.value}",
                content_hash="sha256:" + "e" * 64,
                locator_ref=f"locator:{source.value}",
            ),
        )
    return CollectedEvidenceResult(
        attempt=attempt,
        terminal_outcome_ref=TerminalSourceOutcomeRef(
            acquisition=acquisition,
            outcome=outcome,
        ),
        evidence_refs=evidence,
    )


class FakeScopeSafety:
    def __init__(self, events: list[str], *, blocked: bool = False) -> None:
        self.events = events
        self.blocked = blocked

    def evaluate(self, scope: ResearchScope) -> ScopeSafetyEvaluation:
        self.events.append("scope_and_safety")
        return ScopeSafetyEvaluation(
            interpreted_scope=scope,
            decision=SafetyDecision(
                outcome=SafetyOutcome.BLOCKED if self.blocked else SafetyOutcome.PERMITTED,
                reason=(
                    SafetyReason.UNSAFE_SCOPE
                    if self.blocked
                    else SafetyReason.PERMITTED_RESEARCH_SCOPE
                ),
                policy_version="policy:test",
            ),
        )


class FakePlanner:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def plan(
        self,
        scope: ResearchScope,
        safety_decision: SafetyDecision,
    ) -> tuple[M1BSourcePlanEntryV1, ...]:
        self.events.append("plan_sources")
        assert safety_decision.outcome is SafetyOutcome.PERMITTED
        return tuple(
            M1BSourcePlanEntryV1(
                source=source,
                planning_status=PlanningStatus.SELECTED,
            )
            for source in scope.selected_sources
        )


class FakeCollector:
    def __init__(
        self,
        events: list[str],
        outcomes: dict[SourceType, CollectedEvidenceResult] | None = None,
        generic_fail_once: set[SourceType] | None = None,
        typed_failures: dict[
            SourceType,
            list[CollectionFailureClassification],
        ]
        | None = None,
    ) -> None:
        self.events = events
        self.outcomes = outcomes or {}
        self.generic_fail_once = set(generic_fail_once or set())
        self.typed_failures = {
            source: list(classifications)
            for source, classifications in (typed_failures or {}).items()
        }
        self.calls: list[SourceType] = []
        self.attempts_seen: list[tuple[SourceType, int]] = []

    def collect(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> CollectedEvidenceResult | SourceTaskFailureRef:
        del scope
        self.events.append(f"collect_evidence:{task.source.value}")
        self.calls.append(task.source)
        self.attempts_seen.append((task.source, task.attempts))
        assert task.status is SourceTaskStatus.RUNNING
        assert task.active_attempt == attempt
        if task.source in self.generic_fail_once:
            self.generic_fail_once.remove(task.source)
            raise RuntimeError("deterministic collection failure")
        failures = self.typed_failures.get(task.source, [])
        if failures:
            classification = failures.pop(0)
            return SourceTaskFailureRef(
                failure_id=f"collection-failure:{task.source.value}:{attempt.attempt_number}",
                attempt=attempt,
                classification=classification,
                reason_code="deterministic_test_failure",
            )
        result = self.outcomes.get(task.source, _collected_result(task.source))
        return CollectedEvidenceResult(
            attempt=attempt,
            terminal_outcome_ref=result.terminal_outcome_ref,
            evidence_refs=result.evidence_refs,
        )


class FakeSynthesis:
    def __init__(self, events: list[str], hashes: list[str] | None = None) -> None:
        self.events = events
        self.hashes = list(hashes or [HASH_ONE])
        self.prior_hashes: list[str | None] = []
        self.attempted_permission_override = True

    def synthesize(
        self,
        *,
        run_id: str,
        report_id: str,
        scope: ResearchScope,
        source_tasks: tuple[SourceTaskState, ...],
        prior_report_content_hash: str | None,
    ) -> SynthesisState:
        del run_id, report_id, scope
        self.events.append("synthesize_claims")
        self.prior_hashes.append(prior_report_content_hash)
        assert all(task.status is SourceTaskStatus.TERMINAL for task in source_tasks)
        content_hash = self.hashes.pop(0)
        return SynthesisState(
            report_content_hash=content_hash,
            claims=(ClaimReference(claim_id="claim:sha256:" + "3" * 64),),
            citations=(),
            comparability_refs=(),
            conflict_refs=(),
            warning_codes=(),
        )


class FakeValidation:
    def __init__(self, events: list[str], *, passed: bool = True) -> None:
        self.events = events
        self.passed = passed

    def validate(self, **kwargs: object) -> ReportValidationState:
        del kwargs
        self.events.append("validate_report")
        status = GateStatus.PASSED if self.passed else GateStatus.FAILED
        return ReportValidationState(
            structural_citation_gate=status,
            semantic_support_gate=status,
            safety_policy_gate=status,
            reason_codes=() if self.passed else ("citation_gate_failed",),
        )


class FakePersistence:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0
        self.saved: dict[tuple[str, str], PendingDraftRef] = {}

    def save_pending(
        self,
        *,
        report_id: str,
        report_content_hash: str,
    ) -> PendingDraftRef:
        self.events.append("save_pending_draft")
        self.calls += 1
        key = (report_id, report_content_hash)
        return self.saved.setdefault(
            key,
            PendingDraftRef(
                persistence_id=f"persistence:{report_content_hash[-8:]}",
                report_id=report_id,
                report_content_hash=report_content_hash,
            ),
        )


class FakeApproval:
    def __init__(
        self,
        events: list[str],
        decisions: list[ReviewDecision] | None = None,
    ) -> None:
        self.events = events
        self.decisions = list(decisions or [ReviewDecision.APPROVE])
        self.calls = 0
        self.last_source_tasks: tuple[SourceTaskState, ...] = ()

    def request_approval(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        destination: ExportDestinationRef,
        source_tasks: tuple[SourceTaskState, ...],
        warning_codes: tuple[str, ...],
    ) -> ReviewRecord:
        self.events.append("request_export_approval")
        self.calls += 1
        self.last_source_tasks = source_tasks
        return ReviewRecord(
            review_id=f"review:{self.calls}",
            report_id=report_id,
            report_content_hash=report_content_hash,
            destination=destination,
            source_outcome_refs=tuple(
                task.terminal_outcome_ref
                for task in source_tasks
                if task.terminal_outcome_ref is not None
            ),
            warning_codes=warning_codes,
            decision=self.decisions.pop(0),
            reviewer_id="reviewer:test",
            decided_at_utc=datetime(2026, 1, self.calls, tzinfo=UTC),
        )


class FakeExport:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0
        self.completed: dict[str, ExportRecord] = {}

    def finalize(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        destination: ExportDestinationRef,
        idempotency_key: str,
        approval: ReviewRecord,
    ) -> ExportRecord:
        assert approval.decision is ReviewDecision.APPROVE
        self.events.append("finalize_and_export")
        self.calls += 1
        return self.completed.setdefault(
            idempotency_key,
            ExportRecord(
                export_id="export:test",
                report_id=report_id,
                report_content_hash=report_content_hash,
                destination=destination,
                idempotency_key=idempotency_key,
                approval_review_id=approval.review_id,
                exported_at_utc=datetime(2026, 1, 10, tzinfo=UTC),
            ),
        )


class Harness:
    def __init__(
        self,
        *,
        blocked: bool = False,
        outcomes: dict[SourceType, CollectedEvidenceResult] | None = None,
        generic_fail_once: set[SourceType] | None = None,
        typed_failures: dict[
            SourceType,
            list[CollectionFailureClassification],
        ]
        | None = None,
        hashes: list[str] | None = None,
        validation_passed: bool = True,
        decisions: list[ReviewDecision] | None = None,
    ) -> None:
        self.events: list[str] = []
        self.scope_safety = FakeScopeSafety(self.events, blocked=blocked)
        self.planner = FakePlanner(self.events)
        self.collector = FakeCollector(
            self.events,
            outcomes,
            generic_fail_once,
            typed_failures,
        )
        self.synthesis = FakeSynthesis(self.events, hashes)
        self.validation = FakeValidation(self.events, passed=validation_passed)
        self.persistence = FakePersistence(self.events)
        self.approval = FakeApproval(self.events, decisions)
        self.export = FakeExport(self.events)
        self.workflow = ControlledOrchestrationWorkflow(
            scope_safety=self.scope_safety,
            source_planning=self.planner,
            evidence_collection=self.collector,
            synthesis=self.synthesis,
            report_validation=self.validation,
            draft_persistence=self.persistence,
            export_approval=self.approval,
            export=self.export,
        )


def _run_until_terminal(
    workflow: ControlledOrchestrationWorkflow,
    state: OrchestrationState,
) -> OrchestrationState:
    for _ in range(16):
        if state.current_node is None:
            return state
        state = workflow.run_next(state)
    raise AssertionError("bounded workflow did not terminate")


def test_happy_path_follows_exact_topology_and_exports_once() -> None:
    harness = Harness()
    state = _run_until_terminal(harness.workflow, _initial())

    assert state.report_status is ReportStatus.EXPORTED
    assert state.disposition is WorkflowDisposition.EXPORTED
    assert tuple(node.value for node in state.completed_nodes) == (
        "scope_and_safety",
        "plan_sources",
        "collect_evidence",
        "synthesize_claims",
        "validate_report",
        "save_pending_draft",
        "request_export_approval",
        "finalize_and_export",
    )
    assert harness.events == [
        "scope_and_safety",
        "plan_sources",
        "collect_evidence:pubmed",
        "synthesize_claims",
        "validate_report",
        "save_pending_draft",
        "request_export_approval",
        "finalize_and_export",
    ]
    resumed = harness.workflow.run_next(state)
    assert resumed == state
    assert harness.export.calls == 1
    direct_resumed = harness.workflow.finalize_and_export(state)
    assert direct_resumed == state
    assert harness.export.calls == 1


def test_blocked_scope_stops_before_planning_and_has_no_user_wording() -> None:
    harness = Harness(blocked=True)
    state = harness.workflow.run_next(_initial())
    assert state.disposition is WorkflowDisposition.POLICY_BLOCKED
    assert state.current_node is None
    assert state.safety_decision is not None
    assert state.safety_decision.reason is SafetyReason.UNSAFE_SCOPE
    assert harness.events == ["scope_and_safety"]


def test_persisted_post_collection_checkpoint_rejects_pending_selected_task() -> None:
    harness = Harness()
    state = _initial()
    state = harness.workflow.run_next(state)
    state = harness.workflow.run_next(state)
    with pytest.raises(ValidationError, match="completed collection requires"):
        OrchestrationState.model_validate(
            {
                **state.model_dump(mode="python"),
                "completed_nodes": (
                    WorkflowNode.SCOPE_AND_SAFETY,
                    WorkflowNode.PLAN_SOURCES,
                    WorkflowNode.COLLECT_EVIDENCE,
                ),
                "current_node": WorkflowNode.SYNTHESIZE_CLAIMS,
            }
        )


def test_persisted_post_synthesis_checkpoint_rejects_pending_selected_task() -> None:
    harness = Harness()
    state = _initial()
    while state.current_node is not WorkflowNode.VALIDATE_REPORT:
        state = harness.workflow.run_next(state)
    pending = SourceTaskState(
        task_id=state.source_tasks[0].task_id,
        source=state.source_tasks[0].source,
    )

    with pytest.raises(ValidationError, match="completed collection requires"):
        OrchestrationState.model_validate(
            {
                **state.model_dump(mode="python"),
                "source_tasks": (pending,),
            }
        )


def test_resume_does_not_repeat_already_terminal_source_task() -> None:
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    harness = Harness()
    state = harness.workflow.run_next(_initial(scope))
    state = harness.workflow.run_next(state)
    tasks = tuple(
        SourceTaskState(
            task_id=task.task_id,
            source=task.source,
            status=(
                SourceTaskStatus.TERMINAL
                if task.source is SourceType.DAILYMED
                else SourceTaskStatus.PENDING
            ),
            attempts=1 if task.source is SourceType.DAILYMED else 0,
            terminal_outcome_ref=(
                _collected_result(SourceType.DAILYMED).terminal_outcome_ref
                if task.source is SourceType.DAILYMED
                else None
            ),
            evidence_refs=(
                _collected_result(SourceType.DAILYMED).evidence_refs
                if task.source is SourceType.DAILYMED
                else ()
            ),
        )
        for task in state.source_tasks
    )
    resumed = OrchestrationState.model_validate(
        {**state.model_dump(mode="python"), "source_tasks": tasks}
    )
    running = harness.workflow.run_next(resumed)
    assert harness.collector.calls == []
    assert running.source_tasks[1].status is SourceTaskStatus.RUNNING
    assert running.source_tasks[1].attempts == 1
    collected = harness.workflow.run_next(running)
    assert harness.collector.calls == [SourceType.PUBMED]
    assert all(task.status is SourceTaskStatus.TERMINAL for task in collected.source_tasks)
    assert collected.current_node is WorkflowNode.COLLECT_EVIDENCE
    advanced = harness.workflow.run_next(collected)
    assert advanced.current_node is WorkflowNode.SYNTHESIZE_CLAIMS


def test_prior_source_remains_checkpointed_while_later_source_retries() -> None:
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    harness = Harness(
        typed_failures={
            SourceType.PUBMED: [CollectionFailureClassification.RETRYABLE],
        }
    )
    state = harness.workflow.run_next(_initial(scope))
    state = harness.workflow.run_next(state)

    daily_running = harness.workflow.run_next(state)
    assert harness.collector.calls == []
    daily_checkpoint = harness.workflow.run_next(daily_running)
    daily_task, pubmed_task = daily_checkpoint.source_tasks
    assert daily_task.source is SourceType.DAILYMED
    assert daily_task.status is SourceTaskStatus.TERMINAL
    assert daily_task.attempts == 1
    assert pubmed_task.source is SourceType.PUBMED
    assert pubmed_task.status is SourceTaskStatus.PENDING
    assert pubmed_task.attempts == 0
    assert daily_checkpoint.current_node is WorkflowNode.COLLECT_EVIDENCE

    pubmed_running_one = harness.workflow.run_next(daily_checkpoint)
    retry_wait = harness.workflow.run_next(pubmed_running_one)
    assert retry_wait.source_tasks[0] == daily_task
    assert retry_wait.source_tasks[1].status is SourceTaskStatus.RETRY_WAIT
    assert retry_wait.source_tasks[1].attempts == 1

    pubmed_running_two = harness.workflow.run_next(retry_wait)
    assert pubmed_running_two.source_tasks[1].status is SourceTaskStatus.RUNNING
    assert pubmed_running_two.source_tasks[1].attempts == 2
    retried = harness.workflow.run_next(pubmed_running_two)
    retried_daily, retried_pubmed = retried.source_tasks
    assert retried_daily == daily_task
    assert retried_pubmed.status is SourceTaskStatus.TERMINAL
    assert retried_pubmed.attempts == 2
    assert len(retried_pubmed.failure_history) == 1
    assert harness.collector.calls == [
        SourceType.DAILYMED,
        SourceType.PUBMED,
        SourceType.PUBMED,
    ]
    assert harness.collector.attempts_seen == [
        (SourceType.DAILYMED, 1),
        (SourceType.PUBMED, 1),
        (SourceType.PUBMED, 2),
    ]
    advanced = harness.workflow.run_next(retried)
    assert advanced.current_node is WorkflowNode.SYNTHESIZE_CLAIMS


def test_pending_to_running_checkpoints_attempt_before_any_io() -> None:
    harness = Harness()
    state = harness.workflow.run_next(_initial())
    state = harness.workflow.run_next(state)
    state = OrchestrationState.model_validate(state.model_dump(mode="python"))
    assert state.current_node is WorkflowNode.COLLECT_EVIDENCE
    assert state.source_tasks[0].status is SourceTaskStatus.PENDING
    running = harness.workflow.run_next(state)
    task = running.source_tasks[0]

    assert harness.collector.calls == []
    assert task.status is SourceTaskStatus.RUNNING
    assert task.attempts == 1
    assert task.active_attempt is not None
    assert task.active_attempt.attempt_number == 1
    assert task.active_attempt.task_id == task.task_id

    terminal = harness.workflow.run_next(running)
    assert harness.collector.calls == [SourceType.PUBMED]
    assert terminal.source_tasks[0].status is SourceTaskStatus.TERMINAL


def test_retryable_failures_are_bounded_at_eight_attempts() -> None:
    harness = Harness(
        typed_failures={
            SourceType.PUBMED: [CollectionFailureClassification.RETRYABLE]
            * MAX_SOURCE_TASK_ATTEMPTS,
        }
    )
    state = harness.workflow.run_next(_initial())
    state = harness.workflow.run_next(state)
    while state.current_node is not None:
        state = harness.workflow.run_next(state)

    task = state.source_tasks[0]
    assert state.disposition is WorkflowDisposition.COLLECTION_BLOCKED
    assert state.report_status is ReportStatus.DRAFT
    assert task.status is SourceTaskStatus.FAILED
    assert task.attempts == MAX_SOURCE_TASK_ATTEMPTS
    assert tuple(item.attempt.attempt_number for item in task.failure_history) == tuple(
        range(1, MAX_SOURCE_TASK_ATTEMPTS + 1)
    )
    assert harness.collector.attempts_seen == [
        (SourceType.PUBMED, number) for number in range(1, MAX_SOURCE_TASK_ATTEMPTS + 1)
    ]
    assert task.terminal_outcome_ref is None
    assert task.evidence_refs == ()
    assert harness.synthesis.events.count("synthesize_claims") == 0
    assert harness.export.calls == 0


def test_permanent_failure_dispatches_once_and_blocks_collection() -> None:
    harness = Harness(
        typed_failures={
            SourceType.PUBMED: [CollectionFailureClassification.PERMANENT],
        }
    )
    state = harness.workflow.run_next(_initial())
    state = harness.workflow.run_next(state)
    running = harness.workflow.run_next(state)
    blocked = harness.workflow.run_next(running)

    assert harness.collector.calls == [SourceType.PUBMED]
    assert blocked.disposition is WorkflowDisposition.COLLECTION_BLOCKED
    assert blocked.current_node is None
    assert blocked.source_tasks[0].status is SourceTaskStatus.FAILED
    assert blocked.source_tasks[0].attempts == 1
    assert blocked.source_tasks[0].terminal_outcome_ref is None
    assert harness.synthesis.events.count("synthesize_claims") == 0


def test_unexpected_port_error_is_nonretryable_and_preserves_running_checkpoint() -> None:
    harness = Harness(generic_fail_once={SourceType.PUBMED})
    state = harness.workflow.run_next(_initial())
    state = harness.workflow.run_next(state)
    running = harness.workflow.run_next(state)
    attempt = running.source_tasks[0].active_attempt
    assert attempt is not None

    with pytest.raises(WorkflowExecutionError) as captured:
        harness.workflow.run_next(running)
    assert captured.value.retryable is False
    assert captured.value.attempt_id == attempt.attempt_id
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert harness.collector.calls == [SourceType.PUBMED]
    assert running.source_tasks[0].status is SourceTaskStatus.RUNNING
    assert running.source_tasks[0].active_attempt == attempt
    assert running.source_tasks[0].attempts == 1


def test_retry_exhausted_terminal_failure_is_not_repeated_on_resume() -> None:
    harness = Harness()
    state = harness.workflow.run_next(_initial())
    state = harness.workflow.run_next(state)
    failed = _collected_result(
        SourceType.PUBMED,
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        result=ResultStatus.INDETERMINATE,
    )
    terminal_task = SourceTaskState(
        task_id=state.source_tasks[0].task_id,
        source=SourceType.PUBMED,
        status=SourceTaskStatus.TERMINAL,
        attempts=2,
        terminal_outcome_ref=failed.terminal_outcome_ref,
    )
    resumed = OrchestrationState.model_validate(
        {
            **state.model_dump(mode="python"),
            "source_tasks": (terminal_task,),
        }
    )
    collected = harness.workflow.run_next(resumed)
    assert harness.collector.calls == []
    assert collected.source_tasks == (terminal_task,)
    assert collected.current_node is WorkflowNode.SYNTHESIZE_CLAIMS


def test_partial_and_unavailable_sources_remain_visible_through_approval() -> None:
    outcomes = {
        SourceType.DAILYMED: _collected_result(
            SourceType.DAILYMED,
            coverage=CoverageStatus.PARTIAL,
        ),
        SourceType.PUBMED: _collected_result(
            SourceType.PUBMED,
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.UNAVAILABLE,
            result=ResultStatus.INDETERMINATE,
        ),
    }
    harness = Harness(outcomes=outcomes)
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    state = _initial(scope)
    for _ in range(11):
        state = harness.workflow.run_next(state)
    coverages = {
        task.source: task.terminal_outcome_ref.outcome.coverage_status
        for task in harness.approval.last_source_tasks
        if task.terminal_outcome_ref is not None
    }
    assert coverages == {
        SourceType.DAILYMED: CoverageStatus.PARTIAL,
        SourceType.PUBMED: CoverageStatus.UNAVAILABLE,
    }
    failed = next(
        task for task in harness.approval.last_source_tasks if task.source is SourceType.PUBMED
    )
    assert failed.terminal_outcome_ref is not None
    assert failed.terminal_outcome_ref.outcome.result_status is ResultStatus.INDETERMINATE
    assert state.active_approval is not None
    assert state.active_approval.source_outcome_refs == tuple(
        task.terminal_outcome_ref
        for task in state.source_tasks
        if task.terminal_outcome_ref is not None
    )


def test_failed_validation_blocks_pending_approval_and_export() -> None:
    harness = Harness(validation_passed=False)
    state = _run_until_terminal(harness.workflow, _initial())
    assert state.disposition is WorkflowDisposition.VALIDATION_BLOCKED
    assert state.report_status is ReportStatus.DRAFT
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_rejection_performs_no_export() -> None:
    harness = Harness(decisions=[ReviewDecision.REJECT])
    state = _run_until_terminal(harness.workflow, _initial())
    assert state.report_status is ReportStatus.REJECTED
    assert state.disposition is WorkflowDisposition.REJECTED
    assert harness.export.calls == 0


def test_edit_changes_hash_invalidates_approval_and_preserves_collection() -> None:
    harness = Harness(
        hashes=[HASH_ONE, HASH_TWO],
        decisions=[ReviewDecision.EDIT, ReviewDecision.APPROVE],
    )
    state = _initial()
    for _ in range(9):
        state = harness.workflow.run_next(state)
    assert state.current_node is WorkflowNode.SYNTHESIZE_CLAIMS
    assert state.active_approval is None
    assert state.pending_draft is None
    assert state.synthesis is None
    assert state.edit_base_content_hash == HASH_ONE
    assert state.completed_nodes == (
        WorkflowNode.SCOPE_AND_SAFETY,
        WorkflowNode.PLAN_SOURCES,
        WorkflowNode.COLLECT_EVIDENCE,
    )

    state = _run_until_terminal(harness.workflow, state)
    assert state.synthesis is not None
    assert state.synthesis.report_content_hash == HASH_TWO
    assert harness.synthesis.prior_hashes == [None, HASH_ONE]
    assert harness.collector.calls == [SourceType.PUBMED]
    assert len(state.review_history) == 2
    assert harness.export.calls == 1


def test_edit_with_unchanged_hash_is_rejected_before_revalidation() -> None:
    harness = Harness(
        hashes=[HASH_ONE, HASH_ONE],
        decisions=[ReviewDecision.EDIT],
    )
    state = _initial()
    for _ in range(9):
        state = harness.workflow.run_next(state)
    with pytest.raises(WorkflowTransitionError, match="must change"):
        harness.workflow.run_next(state)
    assert harness.validation.events.count("validate_report") == 1


def test_retrieved_content_cannot_change_static_permissions() -> None:
    harness = Harness()
    state = _initial()
    original_permissions = state.permissions
    for _ in range(6):
        state = harness.workflow.run_next(state)
    assert harness.synthesis.attempted_permission_override is True
    assert state.permissions == original_permissions
    assert state.permissions.retrieved_content_can_change_permissions is False


def test_export_node_cannot_be_called_before_approval() -> None:
    harness = Harness()
    with pytest.raises(WorkflowTransitionError, match="expected current node"):
        harness.workflow.finalize_and_export(_initial())
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    "corruption",
    ("duplicate_pending", "sole_pending", "missing_outcome", "duplicate_terminal"),
)
def test_finalize_reconstructs_and_rejects_corrupt_task_shapes(corruption: str) -> None:
    harness = Harness()
    state = _initial()
    while state.current_node is not WorkflowNode.FINALIZE_AND_EXPORT:
        state = harness.workflow.run_next(state)
    terminal = state.source_tasks[0]
    pending = SourceTaskState(
        task_id=terminal.task_id,
        source=terminal.source,
    )
    missing_outcome = terminal.model_copy(update={"terminal_outcome_ref": None})
    corrupt_tasks = {
        "duplicate_pending": (terminal, pending),
        "sole_pending": (pending,),
        "missing_outcome": (missing_outcome,),
        "duplicate_terminal": (terminal, terminal),
    }[corruption]
    corrupt = state.model_copy(update={"source_tasks": corrupt_tasks})
    harness.collector.calls.clear()

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ) as captured:
        harness.workflow.finalize_and_export(corrupt)
    assert isinstance(captured.value.__cause__, ValidationError)
    assert harness.collector.calls == []
    assert harness.export.calls == 0
    expected_outcome_refs = {
        "duplicate_pending": 1,
        "sole_pending": 0,
        "missing_outcome": 0,
        "duplicate_terminal": 2,
    }[corruption]
    assert (
        sum(task.terminal_outcome_ref is not None for task in corrupt.source_tasks)
        == expected_outcome_refs
    )
    assert corrupt.export_record is None
    assert corrupt.report_status is ReportStatus.APPROVED


def test_corrupt_exported_resume_fails_before_idempotent_return() -> None:
    harness = Harness()
    exported = _run_until_terminal(harness.workflow, _initial())
    assert exported.export_record is not None
    assert harness.export.calls == 1
    terminal = exported.source_tasks[0]
    pending = SourceTaskState(task_id=terminal.task_id, source=terminal.source)
    corrupt = exported.model_copy(update={"source_tasks": (*exported.source_tasks, pending)})
    harness.collector.calls.clear()

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ):
        harness.workflow.finalize_and_export(corrupt)
    assert harness.collector.calls == []
    assert harness.export.calls == 1


def test_run_next_rejects_corrupt_exported_terminal_checkpoint() -> None:
    harness = Harness()
    exported = _run_until_terminal(harness.workflow, _initial())
    assert exported.export_record is not None
    assert harness.export.calls == 1
    terminal = exported.source_tasks[0]
    pending = SourceTaskState(task_id=terminal.task_id, source=terminal.source)
    corrupt = exported.model_copy(update={"source_tasks": (*exported.source_tasks, pending)})
    harness.collector.calls.clear()

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ) as captured:
        harness.workflow.run_next(corrupt)
    assert isinstance(captured.value.__cause__, ValidationError)
    assert harness.collector.calls == []
    assert harness.export.calls == 1
    assert sum(task.terminal_outcome_ref is not None for task in corrupt.source_tasks) == 1
