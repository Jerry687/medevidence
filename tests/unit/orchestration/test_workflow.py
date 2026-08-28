"""Executable transition tests for the bounded controlled workflow."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

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
    CitationReference,
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
    ValidationReceiptRef,
    WorkflowDisposition,
    WorkflowExecutionError,
    WorkflowNode,
    WorkflowTransitionError,
    source_task_attempt,
)
from medevidence.tools.report_validation import (
    AcquisitionInput,
    CanonicalReportRequest,
    CitationInput,
    CitationReferenceInput,
    CitationRelationship,
    ClaimClass,
    ClaimInclusion,
    ClaimInput,
    ClaimReferenceInput,
    EvaluatorIdentityInput,
    EvidenceInput,
    EvidenceReferenceInput,
    ExecutionBoundsInput,
    InferenceUse,
    QualitativeCode,
    ScopeInput,
    SemanticEvaluationInput,
    SemanticExpectationInput,
    SemanticResultInput,
    SemanticSupport,
    SourceOutcomeInput,
    SynthesisInput,
    TerminalTaskInput,
    ValidationRegistryInput,
    canonical_citation_id,
    canonical_claim_id,
    canonical_evidence_id,
    canonical_report_content_hash,
    canonical_semantic_input_digest,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
REPORT_ID = "report:sha256:" + "a" * 64
HASH_ONE = "sha256:" + "1" * 64
HASH_TWO = "sha256:" + "2" * 64
IDENTITY = EvaluatorIdentityInput("deterministic_workflow_test", "v1")


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


def _validation_evidence(source: SourceType) -> EvidenceInput:
    permissions = {
        SourceType.PUBMED: (
            frozenset({ClaimClass.DESCRIPTIVE, ClaimClass.ASSOCIATIONAL}),
            frozenset({InferenceUse.DESCRIPTIVE, InferenceUse.ASSOCIATIONAL}),
        ),
        SourceType.DAILYMED: (
            frozenset({ClaimClass.DESCRIPTIVE}),
            frozenset({InferenceUse.DESCRIPTIVE}),
        ),
        SourceType.FAERS: (
            frozenset({ClaimClass.DESCRIPTIVE}),
            frozenset({InferenceUse.DESCRIPTIVE}),
        ),
        SourceType.CADEC: (
            frozenset({ClaimClass.METHODOLOGICAL_OR_LIMITATION}),
            frozenset({InferenceUse.AUXILIARY_NLP_RETRIEVAL}),
        ),
    }[source]
    evidence = EvidenceInput(
        "evidence:sha256:" + "0" * 64,
        RUN_ID,
        source,
        f"record:{source.value}",
        "version:test",
        f"snapshot:{source.value}",
        "sha256:" + "e" * 64,
        (f"locator:{source.value}",),
        permissions[0],
        permissions[1],
        "",
        (),
    )
    return replace(evidence, evidence_id=canonical_evidence_id(evidence))


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
        registered = _validation_evidence(source)
        evidence = (
            EvidenceReference(
                evidence_id=registered.evidence_id,
                source=source,
                snapshot_id=registered.snapshot_id,
                content_hash=registered.content_hash,
                locator_ref=registered.locators[0],
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


def _expected_result(
    source: SourceType,
    outcomes: dict[SourceType, CollectedEvidenceResult] | None,
) -> CollectedEvidenceResult:
    return (outcomes or {}).get(source, _collected_result(source))


def _validation_registry(
    scope: ResearchScope,
    outcomes: dict[SourceType, CollectedEvidenceResult] | None,
    *,
    support: SemanticSupport,
    claim_variant: int,
) -> ValidationRegistryInput:
    evidence = tuple(
        _validation_evidence(source)
        for source in scope.selected_sources
        if _expected_result(source, outcomes).terminal_outcome_ref.outcome.result_status
        is ResultStatus.MATCHES
    )
    publication = next((item for item in evidence if item.source is SourceType.PUBMED), None)
    if publication is None:
        return ValidationRegistryInput(
            RUN_ID,
            scope.scope_id,
            (),
            (),
            evidence,
            (),
            IDENTITY,
        )
    code = (
        QualitativeCode.PUBMED_DESCRIPTIVE
        if claim_variant == 0
        else QualitativeCode.PUBMED_ASSOCIATIONAL
    )
    claim_class = ClaimClass.DESCRIPTIVE if claim_variant == 0 else ClaimClass.ASSOCIATIONAL
    inference_use = InferenceUse.DESCRIPTIVE if claim_variant == 0 else InferenceUse.ASSOCIATIONAL
    statement = (
        "The bounded publication supplies descriptive evidence."
        if claim_variant == 0
        else "The bounded publication supplies associational evidence."
    )
    claim = ClaimInput(
        "claim:sha256:" + "0" * 64,
        SourceType.PUBMED,
        code,
        statement,
        claim_class,
        inference_use,
        (),
        (),
        ClaimInclusion.FORMAL,
        None,
    )
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    outcome = _expected_result(SourceType.PUBMED, outcomes).terminal_outcome_ref.outcome
    citation = CitationInput(
        "citation:sha256:" + "0" * 64,
        claim.claim_id,
        publication.evidence_id,
        CitationRelationship.SUPPORTS,
        publication.source_record_id,
        publication.source_version,
        publication.snapshot_id,
        publication.content_hash,
        publication.locators[0],
        outcome.execution_status,
        outcome.coverage_status,
        outcome.result_status,
    )
    citation = replace(citation, citation_id=canonical_citation_id(citation))
    claim = replace(claim, citation_ids=(citation.citation_id,))
    expectation = SemanticExpectationInput(
        citation.citation_id,
        canonical_semantic_input_digest(RUN_ID, claim, citation, publication),
        IDENTITY.method,
        IDENTITY.version,
        support,
    )
    return ValidationRegistryInput(
        RUN_ID,
        scope.scope_id,
        (claim,),
        (citation,),
        evidence,
        (expectation,),
        IDENTITY,
    )


def _required_warnings(source_tasks: tuple[SourceTaskState, ...]) -> tuple[str, ...]:
    warnings = {
        warning
        for task in source_tasks
        if task.terminal_outcome_ref is not None
        for warning in task.terminal_outcome_ref.outcome.warning_codes
    }
    for task in source_tasks:
        if task.source is SourceType.FAERS:
            warnings.add("faers_mandatory_limitations")
        if task.source is SourceType.CADEC:
            warnings.add("cadec_mandatory_limitations")
    return tuple(sorted(warnings))


def _canonical_request(
    *,
    run_id: str,
    report_id: str,
    scope: ResearchScope,
    source_tasks: tuple[SourceTaskState, ...],
    synthesis: SynthesisState,
    registry: ValidationRegistryInput,
) -> CanonicalReportRequest:
    scope_input = ScopeInput(
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
    tasks = []
    for task in source_tasks:
        assert task.terminal_outcome_ref is not None
        terminal = task.terminal_outcome_ref
        acquisition = terminal.acquisition
        outcome = terminal.outcome
        bounds = outcome.configured_bounds
        tasks.append(
            TerminalTaskInput(
                task.task_id,
                task.source,
                task.status is SourceTaskStatus.TERMINAL,
                AcquisitionInput(
                    acquisition.run_id,
                    acquisition.source,
                    acquisition.acquisition_id,
                    acquisition.acquisition_intent_id,
                    acquisition.acquisition_ordinal,
                    acquisition.operation,
                    acquisition.query_id,
                    acquisition.source_outcome_id,
                    acquisition.snapshot_id,
                ),
                SourceOutcomeInput(
                    outcome.source,
                    outcome.query_id,
                    outcome.execution_status,
                    outcome.coverage_status,
                    outcome.result_status,
                    ExecutionBoundsInput(
                        bounds.max_query_characters,
                        bounds.max_pages,
                        bounds.max_records,
                        bounds.max_payload_bytes,
                        bounds.max_total_seconds,
                    ),
                    outcome.valid_result_count,
                    outcome.pages_completed,
                    outcome.truncated,
                    outcome.warning_codes,
                    outcome.failure_id,
                ),
                tuple(
                    EvidenceReferenceInput(
                        item.evidence_id,
                        item.source,
                        item.snapshot_id,
                        item.content_hash,
                        item.locator_ref,
                    )
                    for item in task.evidence_refs
                ),
            )
        )
    return CanonicalReportRequest(
        run_id,
        report_id,
        scope_input,
        tuple(tasks),
        SynthesisInput(
            synthesis.report_content_hash,
            tuple(ClaimReferenceInput(item.claim_id) for item in synthesis.claims),
            tuple(
                CitationReferenceInput(item.citation_id, item.claim_id, item.evidence_id)
                for item in synthesis.citations
            ),
            (),
            (),
            synthesis.warning_codes,
        ),
        registry,
    )


class FakeScopeSafety:
    def __init__(self, events: list[str], *, blocked: bool = False) -> None:
        self.events = events
        self.blocked = blocked
        self.interpreted_scope_override: ResearchScope | None = None

    def evaluate(self, scope: ResearchScope) -> ScopeSafetyEvaluation:
        self.events.append("scope_and_safety")
        return ScopeSafetyEvaluation(
            interpreted_scope=self.interpreted_scope_override or scope,
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
        self.raw_override: object | None = None

    def collect(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> object:
        del scope
        self.events.append(f"collect_evidence:{task.source.value}")
        self.calls.append(task.source)
        self.attempts_seen.append((task.source, task.attempts))
        assert task.status is SourceTaskStatus.RUNNING
        assert task.active_attempt == attempt
        if task.source in self.generic_fail_once:
            self.generic_fail_once.remove(task.source)
            raise RuntimeError("deterministic collection failure")
        if self.raw_override is not None:
            return self.raw_override
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
    def __init__(
        self,
        events: list[str],
        registry: ValidationRegistryInput,
    ) -> None:
        self.events = events
        self.registry = registry
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
        self.events.append("synthesize_claims")
        self.prior_hashes.append(prior_report_content_hash)
        assert all(task.status is SourceTaskStatus.TERMINAL for task in source_tasks)
        claims = tuple(
            ClaimReference(claim_id=item.claim_id)
            for item in self.registry.claims
            if item.inclusion is ClaimInclusion.FORMAL
        )
        formal_claim_ids = {item.claim_id for item in claims}
        citations = tuple(
            CitationReference(
                citation_id=item.citation_id,
                claim_id=item.claim_id,
                evidence_id=item.evidence_id,
            )
            for item in self.registry.citations
            if item.claim_id in formal_claim_ids
        )
        provisional = SynthesisState(
            report_content_hash="sha256:" + "0" * 64,
            claims=claims,
            citations=citations,
            comparability_refs=(),
            conflict_refs=(),
            warning_codes=_required_warnings(source_tasks),
        )
        request = _canonical_request(
            run_id=run_id,
            report_id=report_id,
            scope=scope,
            source_tasks=source_tasks,
            synthesis=provisional,
            registry=self.registry,
        )
        return provisional.model_copy(
            update={"report_content_hash": canonical_report_content_hash(request)}
        )


class FakeSemanticProvider:
    def __init__(self, events: list[str], result: SemanticSupport) -> None:
        self.events = events
        self.result = result
        self.calls: list[SemanticEvaluationInput] = []

    def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput:
        self.events.append("validate_report")
        self.calls.append(value)
        return SemanticResultInput(self.result, IDENTITY.method, IDENTITY.version)


class FakeValidationReceiptStore:
    """Deterministic immutable payload store with explicit effect accounting."""

    def __init__(self, events: list[str], *, fail_save: bool = False) -> None:
        self.events = events
        self.fail_save = fail_save
        self.save_calls = 0
        self.load_calls = 0
        self.saved: dict[str, dict[str, object]] = {}
        self.loaded_ids: list[str] = []
        self.missing_ids: set[str] = set()
        self.load_override: dict[str, object] | None = None
        self.post_save_load_missing = False
        self.load_exception: Exception | None = None
        self._next_load_missing = False

    def save_receipt(
        self,
        receipt_payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.events.append("validation_receipt:save")
        self.save_calls += 1
        if self.fail_save:
            raise RuntimeError("deterministic validation receipt persistence failure")
        receipt = validation_receipt_from_payload(receipt_payload)
        canonical_payload = canonical_validation_receipt_payload(receipt)
        assert dict(receipt_payload) == canonical_payload
        existing = self.saved.get(receipt.receipt_id)
        if existing is not None and existing != canonical_payload:
            raise RuntimeError("immutable validation receipt identity collision")
        self.saved.setdefault(receipt.receipt_id, canonical_payload)
        self._next_load_missing = self.post_save_load_missing
        return dict(self.saved[receipt.receipt_id])

    def load_receipt(self, receipt_id: str) -> Mapping[str, object] | None:
        self.events.append("validation_receipt:load")
        self.load_calls += 1
        self.loaded_ids.append(receipt_id)
        if self.load_exception is not None:
            raise self.load_exception
        if self._next_load_missing:
            self._next_load_missing = False
            return None
        if receipt_id in self.missing_ids:
            return None
        if self.load_override is not None:
            return dict(self.load_override)
        payload = self.saved.get(receipt_id)
        return None if payload is None else dict(payload)


class FakePersistence:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0
        self.load_calls = 0
        self.loaded_ids: list[str] = []
        self.saved: dict[str, PendingDraftRef] = {}
        self.report_id_override: str | None = None
        self.load_override: object | None = None
        self.missing_ids: set[str] = set()

    def save_pending(
        self,
        *,
        pending_draft_persistence_id: str,
        report_id: str,
        report_content_hash: str,
    ) -> PendingDraftRef:
        self.events.append("save_pending_draft")
        self.calls += 1
        return self.saved.setdefault(
            pending_draft_persistence_id,
            PendingDraftRef(
                persistence_id=pending_draft_persistence_id,
                report_id=self.report_id_override or report_id,
                report_content_hash=report_content_hash,
            ),
        )

    def load_pending(self, persistence_id: str) -> PendingDraftRef | None:
        self.events.append("pending_draft:load")
        self.load_calls += 1
        self.loaded_ids.append(persistence_id)
        if persistence_id in self.missing_ids:
            return None
        if self.load_override is not None:
            return cast(PendingDraftRef, self.load_override)
        return self.saved.get(persistence_id)


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
        self.report_id_override: str | None = None
        self.pending_draft_persistence_id_override: str | None = None

    def request_approval(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        pending_draft_persistence_id: str,
        destination: ExportDestinationRef,
        source_tasks: tuple[SourceTaskState, ...],
        warning_codes: tuple[str, ...],
    ) -> ReviewRecord:
        self.events.append("request_export_approval")
        self.calls += 1
        self.last_source_tasks = source_tasks
        return ReviewRecord(
            review_id=f"review:{self.calls}",
            report_id=self.report_id_override or report_id,
            report_content_hash=report_content_hash,
            pending_draft_persistence_id=(
                self.pending_draft_persistence_id_override or pending_draft_persistence_id
            ),
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
        self.report_id_override: str | None = None

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
                report_id=self.report_id_override or report_id,
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
        validation_passed: bool = True,
        receipt_persistence_fails: bool = False,
        decisions: list[ReviewDecision] | None = None,
        scope: ResearchScope | None = None,
        claim_variant: int = 0,
    ) -> None:
        self.events: list[str] = []
        self.scope = scope or _scope()
        support = SemanticSupport.SUPPORTED if validation_passed else SemanticSupport.UNSUPPORTED
        self.registry = _validation_registry(
            self.scope,
            outcomes,
            support=support,
            claim_variant=claim_variant,
        )
        self.scope_safety = FakeScopeSafety(self.events, blocked=blocked)
        self.planner = FakePlanner(self.events)
        self.collector = FakeCollector(
            self.events,
            outcomes,
            generic_fail_once,
            typed_failures,
        )
        self.synthesis = FakeSynthesis(self.events, self.registry)
        self.semantic = FakeSemanticProvider(self.events, support)
        self.receipts = FakeValidationReceiptStore(
            self.events,
            fail_save=receipt_persistence_fails,
        )
        self.persistence = FakePersistence(self.events)
        self.approval = FakeApproval(self.events, decisions)
        self.export = FakeExport(self.events)
        self.workflow = ControlledOrchestrationWorkflow(
            scope_safety=self.scope_safety,
            source_planning=self.planner,
            evidence_collection=self.collector,
            synthesis=self.synthesis,
            validation_registry=self.registry,
            semantic_result_provider=self.semantic,
            validation_receipt_store=self.receipts,
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


def _run_until_node(
    workflow: ControlledOrchestrationWorkflow,
    state: OrchestrationState,
    node: WorkflowNode,
) -> OrchestrationState:
    for _ in range(20):
        if state.current_node is node:
            return state
        state = workflow.run_next(state)
    raise AssertionError(f"workflow did not reach {node.value}")


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
        "validation_receipt:save",
        "validation_receipt:load",
        "validation_receipt:load",
        "save_pending_draft",
        "pending_draft:load",
        "pending_draft:load",
        "validation_receipt:load",
        "request_export_approval",
        "pending_draft:load",
        "validation_receipt:load",
        "finalize_and_export",
    ]
    assert state.pending_draft is not None
    assert state.active_approval is not None
    assert state.active_approval.schema_version == "m3.review-record.v2"
    assert state.active_approval.pending_draft_persistence_id == state.pending_draft.persistence_id
    resumed = harness.workflow.run_next(state)
    assert resumed == state
    assert len(harness.semantic.calls) == 1
    assert harness.export.calls == 1
    direct_resumed = harness.workflow.finalize_and_export(state)
    assert direct_resumed == state
    assert len(harness.semantic.calls) == 1
    assert harness.export.calls == 1


def test_blocked_scope_stops_before_planning_and_has_no_user_wording() -> None:
    harness = Harness(blocked=True)
    state = harness.workflow.run_next(_initial())
    assert state.disposition is WorkflowDisposition.POLICY_BLOCKED
    assert state.current_node is None
    assert state.safety_decision is not None
    assert state.safety_decision.reason is SafetyReason.UNSAFE_SCOPE
    assert harness.events == ["scope_and_safety"]
    assert harness.workflow.run_next(state) == state


def test_scope_safety_cannot_expand_selected_sources() -> None:
    harness = Harness()
    harness.scope_safety.interpreted_scope_override = _scope(
        SourceType.PUBMED,
        SourceType.DAILYMED,
    )
    with pytest.raises(WorkflowTransitionError, match="cannot expand"):
        harness.workflow.scope_and_safety(_initial())
    assert harness.planner.events.count("plan_sources") == 0
    assert harness.collector.calls == []
    assert harness.persistence.calls == 0


def test_source_planning_rejects_nonpermitted_decision_before_capability() -> None:
    harness = Harness()
    state = harness.workflow.scope_and_safety(_initial())
    blocked = SafetyDecision(
        outcome=SafetyOutcome.BLOCKED,
        reason=SafetyReason.UNSAFE_SCOPE,
        policy_version="policy:test",
    )
    corrupt = state.model_copy(update={"safety_decision": blocked})
    with pytest.raises(WorkflowTransitionError, match="permitted safety decision"):
        harness.workflow.plan_sources(corrupt)
    assert harness.planner.events.count("plan_sources") == 0


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
    harness = Harness(scope=scope)
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
        },
        scope=scope,
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


@pytest.mark.parametrize("target", ["failure_attempt", "result_attempt", "source", "run"])
def test_collection_result_bindings_reject_before_checkpoint(target: str) -> None:
    harness = Harness()
    state = _run_until_node(harness.workflow, _initial(), WorkflowNode.COLLECT_EVIDENCE)
    running = harness.workflow.collect_evidence(state)
    task = running.source_tasks[0]
    attempt = task.active_attempt
    assert attempt is not None
    if target == "failure_attempt":
        harness.collector.raw_override = SourceTaskFailureRef(
            failure_id="collection-failure:foreign",
            attempt=source_task_attempt(task.task_id, 2),
            classification=CollectionFailureClassification.RETRYABLE,
            reason_code="foreign_attempt",
        )
        message = "failure belongs to another attempt"
    elif target == "result_attempt":
        harness.collector.raw_override = _collected_result(
            SourceType.PUBMED,
            attempt=source_task_attempt(task.task_id, 2),
        )
        message = "result belongs to another attempt"
    elif target == "source":
        harness.collector.raw_override = _collected_result(
            SourceType.DAILYMED,
            attempt=attempt,
        )
        message = "result belongs to another source"
    else:
        result = _collected_result(SourceType.PUBMED, attempt=attempt)
        terminal = result.terminal_outcome_ref
        acquisition = terminal.acquisition.model_copy(
            update={"run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
        )
        harness.collector.raw_override = result.model_copy(
            update={
                "terminal_outcome_ref": terminal.model_copy(update={"acquisition": acquisition})
            }
        )
        message = "result belongs to another run"
    checkpoint = running.checkpoint_id
    with pytest.raises(WorkflowTransitionError, match=message):
        harness.workflow.collect_evidence(running)
    assert running.checkpoint_id == checkpoint
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


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


def test_persisted_failed_task_is_completed_without_redispatch() -> None:
    harness = Harness(
        typed_failures={SourceType.PUBMED: [CollectionFailureClassification.PERMANENT]}
    )
    blocked = _run_until_terminal(harness.workflow, _initial())
    assert blocked.source_tasks[0].status is SourceTaskStatus.FAILED
    calls = tuple(harness.collector.calls)
    resumed = blocked.model_copy(
        update={
            "current_node": WorkflowNode.COLLECT_EVIDENCE,
            "disposition": WorkflowDisposition.ACTIVE,
        }
    )
    completed = harness.workflow.collect_evidence(resumed)
    assert completed.current_node is None
    assert completed.disposition is WorkflowDisposition.COLLECTION_BLOCKED
    assert tuple(harness.collector.calls) == calls


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
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    harness = Harness(outcomes=outcomes, scope=scope)
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


def test_forged_passing_checkpoint_without_authoritative_receipt_fails_closed() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    assert saving.validation.passed
    assert saving.validation_receipt_ref is not None
    harness.receipts.saved.clear()
    semantic_calls = len(harness.semantic.calls)
    load_calls = harness.receipts.load_calls

    with pytest.raises(
        WorkflowTransitionError,
        match=r"receipt (is unavailable|reference drift)",
    ):
        harness.workflow.save_pending_draft(saving)

    assert len(harness.semantic.calls) == semantic_calls
    assert harness.receipts.load_calls == load_calls + 1
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_unknown_validation_receipt_reference_fails_before_any_effect() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    unknown = ValidationReceiptRef(
        receipt_id="validation-receipt:sha256:" + "f" * 64,
        receipt_content_hash=HASH_TWO,
    )
    forged = saving.model_copy(update={"validation_receipt_ref": unknown})
    semantic_calls = len(harness.semantic.calls)

    with pytest.raises(
        WorkflowTransitionError,
        match=r"receipt (is unavailable|reference drift)",
    ):
        harness.workflow.save_pending_draft(forged)

    assert harness.receipts.loaded_ids[-1] == unknown.receipt_id
    assert len(harness.semantic.calls) == semantic_calls
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    "drift",
    ("foreign_run", "stale_report", "different_input", "evaluator", "policy"),
)
def test_persisted_receipt_binding_drift_fails_closed_before_effect(drift: str) -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    receipt_ref = saving.validation_receipt_ref
    assert receipt_ref is not None
    receipt_payload = harness.receipts.saved[receipt_ref.receipt_id]
    changes: dict[str, object] = {
        "foreign_run": {"run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        "stale_report": {"report_content_hash": HASH_TWO},
        "different_input": {"validation_input_hash": HASH_TWO},
        "evaluator": {"evaluator_version": "foreign-evaluator-v2"},
        "policy": {"policy_version": "M3_VALIDATION_POLICY_FOREIGN"},
    }[drift]
    harness.receipts.load_override = {**receipt_payload, **changes}
    semantic_calls = len(harness.semantic.calls)
    load_calls = harness.receipts.load_calls

    with pytest.raises(
        WorkflowTransitionError,
        match=r"receipt (reconstruction|binding) failed",
    ):
        harness.workflow.save_pending_draft(saving)

    assert harness.receipts.load_calls == load_calls + 1
    assert len(harness.semantic.calls) == semantic_calls
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_self_consistent_foreign_receipt_reaches_reference_binding_guard() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    receipt_ref = saving.validation_receipt_ref
    assert receipt_ref is not None

    foreign = Harness(claim_variant=1)
    foreign_state = _run_until_node(
        foreign.workflow,
        _initial(),
        WorkflowNode.SAVE_PENDING_DRAFT,
    )
    foreign_ref = foreign_state.validation_receipt_ref
    assert foreign_ref is not None
    foreign_payload = foreign.receipts.saved[foreign_ref.receipt_id]
    reconstructed = validation_receipt_from_payload(foreign_payload)
    assert canonical_validation_receipt_payload(reconstructed) == foreign_payload
    assert reconstructed.receipt_id != receipt_ref.receipt_id
    assert reconstructed.receipt_content_hash != receipt_ref.receipt_content_hash

    harness.receipts.load_override = foreign_payload
    semantic_calls = len(harness.semantic.calls)
    load_calls = harness.receipts.load_calls
    with pytest.raises(
        WorkflowTransitionError,
        match="canonical report receipt reference drift",
    ) as captured:
        harness.workflow.save_pending_draft(saving)

    assert captured.value.__cause__ is None
    assert len(harness.semantic.calls) == semantic_calls
    assert harness.receipts.load_calls == load_calls + 1
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_malformed_persisted_receipt_mapping_fails_closed_before_effect() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    receipt_ref = saving.validation_receipt_ref
    assert receipt_ref is not None
    harness.receipts.load_override = {
        "marker": "M3_VALIDATION_RECEIPT_V1",
        "receipt_id": receipt_ref.receipt_id,
    }
    semantic_calls = len(harness.semantic.calls)

    with pytest.raises(
        WorkflowTransitionError,
        match=r"receipt (reconstruction|mapping|binding) failed",
    ):
        harness.workflow.save_pending_draft(saving)

    assert len(harness.semantic.calls) == semantic_calls
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_assessment_persists_receipt_and_each_progression_is_pure_load_then_effect() -> None:
    harness = Harness()
    validating = _run_until_node(harness.workflow, _initial(), WorkflowNode.VALIDATE_REPORT)
    validated = harness.workflow.validate_report(validating)
    receipt_ref = validated.validation_receipt_ref
    assert receipt_ref is not None
    assert receipt_ref.receipt_id in harness.receipts.saved
    persisted_payload = harness.receipts.saved[receipt_ref.receipt_id]
    assert (
        canonical_validation_receipt_payload(validation_receipt_from_payload(persisted_payload))
        == persisted_payload
    )
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == 1
    assert len(harness.semantic.calls) == 1
    assert harness.events[-3:] == [
        "validate_report",
        "validation_receipt:save",
        "validation_receipt:load",
    ]

    semantic_calls = len(harness.semantic.calls)
    pending = harness.workflow.save_pending_draft(validated)
    assert harness.events[-3:] == [
        "validation_receipt:load",
        "save_pending_draft",
        "pending_draft:load",
    ]
    approved = harness.workflow.request_export_approval(pending)
    assert harness.events[-3:] == [
        "pending_draft:load",
        "validation_receipt:load",
        "request_export_approval",
    ]
    exported = harness.workflow.finalize_and_export(approved)
    assert harness.events[-3:] == [
        "pending_draft:load",
        "validation_receipt:load",
        "finalize_and_export",
    ]
    assert harness.workflow.run_next(exported) == exported
    assert harness.events[-2:] == ["pending_draft:load", "validation_receipt:load"]
    assert harness.workflow.finalize_and_export(exported) == exported
    assert harness.events[-2:] == ["pending_draft:load", "validation_receipt:load"]

    assert len(harness.semantic.calls) == semantic_calls
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == 6
    assert harness.persistence.calls == 1
    assert harness.persistence.load_calls == 5
    assert harness.approval.calls == 1
    assert harness.export.calls == 1


def test_receipt_persistence_failure_cannot_create_passing_durable_state() -> None:
    harness = Harness(receipt_persistence_fails=True)
    validating = _run_until_node(harness.workflow, _initial(), WorkflowNode.VALIDATE_REPORT)

    with pytest.raises(WorkflowTransitionError, match="receipt persistence failed"):
        harness.workflow.validate_report(validating)

    assert validating.current_node is WorkflowNode.VALIDATE_REPORT
    assert not validating.validation.passed
    assert validating.validation_receipt_ref is None
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == 0
    assert harness.receipts.saved == {}
    assert len(harness.semantic.calls) == 1
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_post_save_missing_receipt_fails_assessment_before_durable_progression() -> None:
    harness = Harness()
    validating = _run_until_node(harness.workflow, _initial(), WorkflowNode.VALIDATE_REPORT)
    validating_dump = validating.model_dump(mode="python")
    harness.receipts.post_save_load_missing = True

    with pytest.raises(
        WorkflowTransitionError,
        match="persisted validation receipt is unavailable",
    ):
        harness.workflow.validate_report(validating)

    assert validating.model_dump(mode="python") == validating_dump
    assert validating.current_node is WorkflowNode.VALIDATE_REPORT
    assert validating.validation_receipt_ref is None
    assert not validating.validation.passed
    assert len(harness.semantic.calls) == 1
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == 1
    assert len(harness.receipts.saved) == 1
    assert harness.events[-3:] == [
        "validate_report",
        "validation_receipt:save",
        "validation_receipt:load",
    ]
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    "route",
    ("save", "approval", "export", "idempotent_export", "terminal_resume"),
)
def test_receipt_load_exception_precedes_every_progression_or_trusted_return(
    route: str,
) -> None:
    harness = Harness()
    if route == "save":
        state = _run_until_node(
            harness.workflow,
            _initial(),
            WorkflowNode.SAVE_PENDING_DRAFT,
        )
        operation = harness.workflow.save_pending_draft
    elif route == "approval":
        state = _run_until_node(
            harness.workflow,
            _initial(),
            WorkflowNode.REQUEST_EXPORT_APPROVAL,
        )
        operation = harness.workflow.request_export_approval
    elif route == "export":
        state = _run_until_node(
            harness.workflow,
            _initial(),
            WorkflowNode.FINALIZE_AND_EXPORT,
        )
        operation = harness.workflow.finalize_and_export
    else:
        state = _run_until_terminal(harness.workflow, _initial())
        operation = (
            harness.workflow.finalize_and_export
            if route == "idempotent_export"
            else harness.workflow.run_next
        )
    semantic_calls = len(harness.semantic.calls)
    receipt_load_calls = harness.receipts.load_calls
    effects = (
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )
    harness.receipts.load_exception = RuntimeError("deterministic receipt load failure")

    with pytest.raises(
        WorkflowTransitionError, match="canonical report receipt load failed"
    ) as exc:
        operation(state)

    assert isinstance(exc.value.__cause__, RuntimeError)
    assert str(exc.value.__cause__) == "deterministic receipt load failure"
    assert len(harness.semantic.calls) == semantic_calls
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == receipt_load_calls + 1
    assert harness.events[-1] == "validation_receipt:load"
    assert effects == (
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )


def test_validation_blocked_terminal_resume_is_pure_and_idempotent() -> None:
    harness = Harness(validation_passed=False)
    blocked = _run_until_terminal(harness.workflow, _initial())
    assert blocked.current_node is None
    assert blocked.synthesis is not None
    assert blocked.disposition is WorkflowDisposition.VALIDATION_BLOCKED
    assert not blocked.validation.passed
    assert blocked.validation.structural_citation_gate is GateStatus.PASSED
    assert blocked.validation.semantic_support_gate is GateStatus.FAILED
    assert blocked.validation.safety_policy_gate is GateStatus.PASSED
    assert blocked.validation.reason_codes == ("material_claim_not_accepted",)
    assert blocked.validation_receipt_ref is not None
    assert harness.receipts.save_calls == 1
    assert harness.receipts.load_calls == 1
    before = (
        len(harness.semantic.calls),
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )
    resumed = harness.workflow.run_next(blocked)
    assert resumed == OrchestrationState.model_validate(blocked.model_dump(mode="python"))
    assert resumed.validation == blocked.validation
    assert before == (
        len(harness.semantic.calls),
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )
    assert harness.receipts.load_calls == 2
    assert harness.events[-1] == "validation_receipt:load"


@pytest.mark.parametrize(
    "target",
    ["gate", "reason", "hash", "registry", "rejected_registry", "exported_registry"],
)
def test_terminal_binding_drift_rejects_without_semantic_or_effects(target: str) -> None:
    if target == "rejected_registry":
        harness = Harness(decisions=[ReviewDecision.REJECT])
        terminal = _run_until_terminal(harness.workflow, _initial())
        object.__setattr__(harness.registry, "scope_id", "scope:foreign")
    elif target == "exported_registry":
        harness = Harness()
        terminal = _run_until_terminal(harness.workflow, _initial())
        object.__setattr__(harness.registry, "scope_id", "scope:foreign")
    else:
        harness = Harness(validation_passed=False)
        terminal = _run_until_terminal(harness.workflow, _initial())
        if target == "gate":
            validation = terminal.validation.model_copy(
                update={"structural_citation_gate": GateStatus.FAILED}
            )
            terminal = terminal.model_copy(update={"validation": validation})
        elif target == "reason":
            validation = terminal.validation.model_copy(update={"reason_codes": ("forged_reason",)})
            terminal = terminal.model_copy(update={"validation": validation})
        elif target == "hash":
            assert terminal.synthesis is not None
            synthesis = terminal.synthesis.model_copy(update={"report_content_hash": HASH_TWO})
            terminal = terminal.model_copy(update={"synthesis": synthesis})
        else:
            object.__setattr__(harness.registry, "scope_id", "scope:foreign")
    before = (
        len(harness.semantic.calls),
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )
    with pytest.raises(
        WorkflowTransitionError,
        match=r"receipt binding failed|binding verification failed",
    ):
        harness.workflow.run_next(terminal)
    assert before == (
        len(harness.semantic.calls),
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )


def test_rejection_performs_no_export() -> None:
    harness = Harness(decisions=[ReviewDecision.REJECT])
    state = _run_until_terminal(harness.workflow, _initial())
    assert state.report_status is ReportStatus.REJECTED
    assert state.disposition is WorkflowDisposition.REJECTED
    assert harness.export.calls == 0


def test_edit_changes_hash_invalidates_approval_and_preserves_collection() -> None:
    harness = Harness(decisions=[ReviewDecision.EDIT])
    state = _initial()
    old_receipt_ref: ValidationReceiptRef | None = None
    for _ in range(9):
        state = harness.workflow.run_next(state)
        if state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL:
            old_receipt_ref = state.validation_receipt_ref
    assert state.current_node is WorkflowNode.SYNTHESIZE_CLAIMS
    assert state.active_approval is None
    assert state.pending_draft is None
    assert state.synthesis is None
    assert state.validation_receipt_ref is None
    assert old_receipt_ref is not None
    prior_hash = state.edit_base_content_hash
    assert prior_hash is not None
    assert state.completed_nodes == (
        WorkflowNode.SCOPE_AND_SAFETY,
        WorkflowNode.PLAN_SOURCES,
        WorkflowNode.COLLECT_EVIDENCE,
    )
    forged = state.model_copy(update={"validation_receipt_ref": old_receipt_ref})
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        harness.workflow.synthesize_claims(forged)

    edited = Harness(decisions=[ReviewDecision.APPROVE], claim_variant=1)
    state = _run_until_terminal(edited.workflow, state)
    assert state.synthesis is not None
    assert state.synthesis.report_content_hash != prior_hash
    assert harness.synthesis.prior_hashes == [None]
    assert edited.synthesis.prior_hashes == [prior_hash]
    assert harness.collector.calls == [SourceType.PUBMED]
    assert edited.collector.calls == []
    assert len(state.review_history) == 2
    assert state.validation_receipt_ref is not None
    assert state.validation_receipt_ref.receipt_id != old_receipt_ref.receipt_id
    assert edited.receipts.save_calls == 1
    assert len(edited.semantic.calls) == 1
    assert edited.export.calls == 1


def test_edit_with_unchanged_hash_is_rejected_before_revalidation() -> None:
    harness = Harness(decisions=[ReviewDecision.EDIT])
    state = _initial()
    for _ in range(9):
        state = harness.workflow.run_next(state)
    with pytest.raises(WorkflowTransitionError, match="must change"):
        harness.workflow.run_next(state)
    assert len(harness.semantic.calls) == 1


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
    receipt_load_calls = harness.receipts.load_calls
    with pytest.raises(
        WorkflowTransitionError,
        match="expected current node",
    ):
        harness.workflow.finalize_and_export(_initial())
    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.export.calls == 0


def test_finalize_topology_with_draft_status_reaches_direct_approval_guard() -> None:
    builder = Harness()
    approved = _run_until_node(
        builder.workflow,
        _initial(),
        WorkflowNode.FINALIZE_AND_EXPORT,
    )
    assert approved.report_status is ReportStatus.APPROVED
    assert approved.active_approval is not None
    corrupt = approved.model_copy(
        update={
            "report_status": ReportStatus.DRAFT,
            "active_approval": None,
        }
    )

    harness = Harness()
    harness.receipts.saved = {
        receipt_id: dict(payload) for receipt_id, payload in builder.receipts.saved.items()
    }
    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ):
        harness.workflow.finalize_and_export(corrupt)

    assert harness.events == []
    assert harness.receipts.load_calls == 0
    assert harness.semantic.calls == []
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    ("source", "warning"),
    [
        (SourceType.FAERS, "faers_mandatory_limitations"),
        (SourceType.CADEC, "cadec_mandatory_limitations"),
    ],
)
def test_canonical_warning_preflight_rejects_before_receipt_load(
    source: SourceType,
    warning: str,
) -> None:
    scope = _scope(source)
    outcomes = {source: _collected_result(source, result=ResultStatus.NO_MATCH)}
    harness = Harness(scope=scope, outcomes=outcomes)
    saving = _run_until_node(
        harness.workflow,
        _initial(scope),
        WorkflowNode.SAVE_PENDING_DRAFT,
    )
    assert saving.synthesis is not None
    assert saving.synthesis.warning_codes == (warning,)
    corrupt = saving.model_copy(
        update={"synthesis": saving.synthesis.model_copy(update={"warning_codes": ()})}
    )
    receipt_load_calls = harness.receipts.load_calls

    with pytest.raises(
        WorkflowTransitionError,
        match="canonical report binding verification failed",
    ):
        harness.workflow.save_pending_draft(corrupt)

    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.persistence.calls == 0
    assert harness.persistence.load_calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_forged_predictable_pending_ref_without_save_cannot_reach_approval() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    assert saving.synthesis is not None
    persistence_id = ControlledOrchestrationWorkflow._pending_draft_persistence_id(
        saving.report_id,
        saving.synthesis.report_content_hash,
    )
    forged = saving.model_copy(
        update={
            "completed_nodes": (*saving.completed_nodes, WorkflowNode.SAVE_PENDING_DRAFT),
            "current_node": WorkflowNode.REQUEST_EXPORT_APPROVAL,
            "pending_draft": PendingDraftRef(
                persistence_id=persistence_id,
                report_id=saving.report_id,
                report_content_hash=saving.synthesis.report_content_hash,
            ),
            "report_status": ReportStatus.PENDING_REVIEW,
        }
    )
    receipt_load_calls = harness.receipts.load_calls

    for operation in (
        harness.workflow.request_export_approval,
        harness.workflow.run_next,
    ):
        with pytest.raises(WorkflowTransitionError, match="pending draft is unavailable"):
            operation(forged)

    assert harness.persistence.calls == 0
    assert harness.persistence.load_calls == 2
    assert harness.persistence.loaded_ids == [persistence_id, persistence_id]
    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_saved_pending_draft_must_be_durably_reloadable_before_checkpoint() -> None:
    harness = Harness()
    saving = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    assert saving.synthesis is not None
    persistence_id = ControlledOrchestrationWorkflow._pending_draft_persistence_id(
        saving.report_id,
        saving.synthesis.report_content_hash,
    )
    harness.persistence.missing_ids.add(persistence_id)

    with pytest.raises(WorkflowTransitionError, match="pending draft is unavailable"):
        harness.workflow.save_pending_draft(saving)

    assert harness.persistence.calls == 1
    assert harness.persistence.load_calls == 1
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    "route",
    ["approval", "export", "idempotent_export", "terminal_resume", "rejected_resume"],
)
@pytest.mark.parametrize("drift", ["missing", "substituted", "stale", "malformed"])
def test_loaded_pending_draft_drift_fails_before_receipt_or_later_effect(
    route: str,
    drift: str,
) -> None:
    decisions = [ReviewDecision.REJECT] if route == "rejected_resume" else None
    harness = Harness(decisions=decisions)
    if route == "approval":
        state = _run_until_node(
            harness.workflow,
            _initial(),
            WorkflowNode.REQUEST_EXPORT_APPROVAL,
        )
        operation = harness.workflow.request_export_approval
    elif route == "export":
        state = _run_until_node(
            harness.workflow,
            _initial(),
            WorkflowNode.FINALIZE_AND_EXPORT,
        )
        operation = harness.workflow.finalize_and_export
    else:
        state = _run_until_terminal(harness.workflow, _initial())
        operation = (
            harness.workflow.finalize_and_export
            if route == "idempotent_export"
            else harness.workflow.run_next
        )
    pending = state.pending_draft
    assert pending is not None
    if drift == "missing":
        harness.persistence.missing_ids.add(pending.persistence_id)
    elif drift == "substituted":
        harness.persistence.load_override = pending.model_copy(
            update={"persistence_id": "persistence:foreign"}
        )
    elif drift == "stale":
        harness.persistence.load_override = pending.model_copy(
            update={"report_content_hash": HASH_TWO}
        )
    else:
        harness.persistence.load_override = object()
    pending_load_calls = harness.persistence.load_calls
    receipt_load_calls = harness.receipts.load_calls
    effects = (harness.persistence.calls, harness.approval.calls, harness.export.calls)

    with pytest.raises(
        WorkflowTransitionError,
        match=r"pending draft (is unavailable|reconstruction failed|durable binding drift)",
    ):
        operation(state)

    assert harness.persistence.load_calls == pending_load_calls + 1
    assert harness.receipts.load_calls == receipt_load_calls
    assert effects == (harness.persistence.calls, harness.approval.calls, harness.export.calls)


def test_instance_shadowed_binding_helper_cannot_bypass_invalid_preflight() -> None:
    harness = Harness()
    saving = _run_until_node(
        harness.workflow,
        _initial(),
        WorkflowNode.SAVE_PENDING_DRAFT,
    )

    class ShadowingWorkflow(ControlledOrchestrationWorkflow):
        pass

    workflow = ShadowingWorkflow(
        scope_safety=harness.scope_safety,
        source_planning=harness.planner,
        evidence_collection=harness.collector,
        synthesis=harness.synthesis,
        validation_registry=harness.registry,
        semantic_result_provider=harness.semantic,
        validation_receipt_store=harness.receipts,
        draft_persistence=harness.persistence,
        export_approval=harness.approval,
        export=harness.export,
    )
    workflow.__dict__["_verify_binding"] = lambda *args, **kwargs: None
    unknown = ValidationReceiptRef(
        receipt_id="validation-receipt:sha256:" + "f" * 64,
        receipt_content_hash=HASH_TWO,
    )
    corrupt = saving.model_copy(update={"validation_receipt_ref": unknown})
    receipt_load_calls = harness.receipts.load_calls
    effects = (
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )

    with pytest.raises(
        WorkflowTransitionError,
        match="canonical report receipt is unavailable",
    ):
        workflow.save_pending_draft(corrupt)

    assert workflow.__dict__["_verify_binding"] is not None
    assert harness.receipts.load_calls == receipt_load_calls + 1
    assert effects == (
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )


def test_foreign_pending_persistence_id_fails_before_approval_or_receipt_load() -> None:
    harness = Harness()
    pending_state = _run_until_node(
        harness.workflow,
        _initial(),
        WorkflowNode.REQUEST_EXPORT_APPROVAL,
    )
    assert pending_state.pending_draft is not None
    corrupt = pending_state.model_copy(
        update={
            "pending_draft": pending_state.pending_draft.model_copy(
                update={"persistence_id": "persistence:foreign"}
            )
        }
    )
    receipt_load_calls = harness.receipts.load_calls

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ):
        harness.workflow.request_export_approval(corrupt)

    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_substituted_pending_persistence_id_fails_before_export_or_receipt_load() -> None:
    harness = Harness()
    approved = _run_until_node(
        harness.workflow,
        _initial(),
        WorkflowNode.FINALIZE_AND_EXPORT,
    )
    assert approved.pending_draft is not None
    corrupt = approved.model_copy(
        update={
            "pending_draft": approved.pending_draft.model_copy(
                update={"persistence_id": "persistence:substituted"}
            )
        }
    )
    receipt_load_calls = harness.receipts.load_calls

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ):
        harness.workflow.finalize_and_export(corrupt)

    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.export.calls == 0


def test_exported_pending_persistence_id_drift_fails_before_idempotent_return() -> None:
    harness = Harness()
    exported = _run_until_terminal(harness.workflow, _initial())
    assert exported.pending_draft is not None
    corrupt = exported.model_copy(
        update={
            "pending_draft": exported.pending_draft.model_copy(
                update={"persistence_id": "persistence:stale"}
            )
        }
    )
    receipt_load_calls = harness.receipts.load_calls
    export_calls = harness.export.calls

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ):
        harness.workflow.finalize_and_export(corrupt)

    assert harness.receipts.load_calls == receipt_load_calls
    assert harness.export.calls == export_calls


def test_public_node_guards_reject_terminal_and_wrong_current_node() -> None:
    terminal_harness = Harness(blocked=True)
    terminal = terminal_harness.workflow.run_next(_initial())
    with pytest.raises(WorkflowTransitionError, match="terminal workflow"):
        terminal_harness.workflow.scope_and_safety(terminal)

    active_harness = Harness()
    with pytest.raises(WorkflowTransitionError, match="expected current node"):
        active_harness.workflow.plan_sources(_initial())
    assert active_harness.planner.events.count("plan_sources") == 0


@pytest.mark.parametrize("target", ["permission", "missing_synthesis", "repeated"])
def test_durable_reconstruction_dominates_unreachable_node_guards(target: str) -> None:
    harness = Harness()
    if target == "permission":
        state = _initial()
        permissions = state.permissions.model_copy(update={"allowed_nodes": ()})
        corrupt = state.model_copy(update={"permissions": permissions})
        operation = harness.workflow.scope_and_safety
    elif target == "missing_synthesis":
        state = _run_until_node(harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
        corrupt = state.model_copy(update={"synthesis": None})
        operation = harness.workflow.save_pending_draft
    else:
        state = _initial()
        corrupt = state.model_copy(update={"completed_nodes": (WorkflowNode.SCOPE_AND_SAFETY,)})
        operation = harness.workflow.scope_and_safety
    before = (harness.persistence.calls, harness.approval.calls, harness.export.calls)
    expected = "valid durable checkpoint"
    with pytest.raises(WorkflowTransitionError, match=expected) as captured:
        operation(corrupt)
    if target != "missing_synthesis":
        assert isinstance(captured.value.__cause__, ValidationError)
    assert before == (harness.persistence.calls, harness.approval.calls, harness.export.calls)


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


@pytest.mark.parametrize("source", [SourceType.FAERS, SourceType.CADEC])
def test_zero_evidence_source_warnings_are_bound_without_fabrication(source: SourceType) -> None:
    scope = _scope(source)
    outcomes = {source: _collected_result(source, result=ResultStatus.NO_MATCH)}
    harness = Harness(scope=scope, outcomes=outcomes)
    exported = _run_until_terminal(harness.workflow, _initial(scope))
    expected = (
        ("faers_mandatory_limitations",)
        if source is SourceType.FAERS
        else ("cadec_mandatory_limitations",)
    )
    assert exported.synthesis is not None
    assert exported.synthesis.warning_codes == expected
    assert exported.synthesis.claims == ()
    assert exported.synthesis.citations == ()
    assert harness.registry.evidence == ()
    assert harness.semantic.calls == []


@pytest.mark.parametrize("route", ["collect", "save", "approval", "export"])
def test_invalid_state_preflight_precedes_every_direct_effect(route: str) -> None:
    harness = Harness()
    node = {
        "collect": WorkflowNode.COLLECT_EVIDENCE,
        "save": WorkflowNode.SAVE_PENDING_DRAFT,
        "approval": WorkflowNode.REQUEST_EXPORT_APPROVAL,
        "export": WorkflowNode.FINALIZE_AND_EXPORT,
    }[route]
    state = _run_until_node(harness.workflow, _initial(), node)
    if route == "collect":
        task = state.source_tasks[0].model_copy(update={"task_id": "source-task:foreign"})
        state = state.model_copy(update={"source_tasks": (task,)})
        operation = harness.workflow.collect_evidence
    elif route == "save":
        task = state.source_tasks[0]
        assert task.terminal_outcome_ref is not None
        terminal = task.terminal_outcome_ref
        acquisition = terminal.acquisition.model_copy(update={"run_id": "run:foreign"})
        terminal = terminal.model_copy(update={"acquisition": acquisition})
        task = task.model_copy(update={"terminal_outcome_ref": terminal})
        state = state.model_copy(update={"source_tasks": (task,)})
        operation = harness.workflow.save_pending_draft
    elif route == "approval":
        assert state.pending_draft is not None
        pending = state.pending_draft.model_copy(update={"report_content_hash": HASH_TWO})
        state = state.model_copy(update={"pending_draft": pending})
        operation = harness.workflow.request_export_approval
    else:
        assert state.active_approval is not None
        approval = state.active_approval.model_copy(
            update={"report_id": "report:sha256:" + "f" * 64}
        )
        state = state.model_copy(update={"active_approval": approval})
        operation = harness.workflow.finalize_and_export
    before = (
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        operation(state)
    assert before == (
        len(harness.collector.calls),
        harness.persistence.calls,
        harness.approval.calls,
        harness.export.calls,
    )


@pytest.mark.parametrize("wrapper", [False, True])
def test_collection_mapping_rejects_unknown_and_subclass_results(wrapper: bool) -> None:
    harness = Harness()
    running = _run_until_node(harness.workflow, _initial(), WorkflowNode.COLLECT_EVIDENCE)
    running = harness.workflow.collect_evidence(running)
    assert running.source_tasks[0].status is SourceTaskStatus.RUNNING
    if wrapper:

        class UntrustedCollectedResult(CollectedEvidenceResult):
            injected: str

        base = _collected_result(SourceType.PUBMED, attempt=running.source_tasks[0].active_attempt)
        harness.collector.raw_override = UntrustedCollectedResult(
            **base.model_dump(mode="python"),
            injected="untrusted",
        )
        expected_error = ValidationError
    else:
        harness.collector.raw_override = object()
        expected_error = WorkflowTransitionError
    with pytest.raises(expected_error):
        harness.workflow.collect_evidence(running)
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


def test_duplicate_evidence_id_across_valid_selected_tasks_hits_application_guard() -> None:
    scope = _scope(SourceType.DAILYMED, SourceType.PUBMED)
    builder = Harness(scope=scope)
    synthesized = _run_until_node(
        builder.workflow,
        _initial(scope),
        WorkflowNode.SYNTHESIZE_CLAIMS,
    )
    first, second = synthesized.source_tasks
    assert first.status is SourceTaskStatus.TERMINAL
    assert second.status is SourceTaskStatus.TERMINAL
    assert len(first.evidence_refs) == 1
    assert len(second.evidence_refs) == 1
    first_evidence = first.evidence_refs[0]
    second_evidence = second.evidence_refs[0]
    assert first_evidence.evidence_id != second_evidence.evidence_id
    assert (
        first_evidence.source,
        first_evidence.snapshot_id,
        first_evidence.content_hash,
        first_evidence.locator_ref,
    ) != (
        second_evidence.source,
        second_evidence.snapshot_id,
        second_evidence.content_hash,
        second_evidence.locator_ref,
    )
    duplicate_id_evidence = second_evidence.model_copy(
        update={"evidence_id": first_evidence.evidence_id}
    )
    corrupt_second = second.model_copy(update={"evidence_refs": (duplicate_id_evidence,)})
    corrupt = synthesized.model_copy(update={"source_tasks": (first, corrupt_second)})
    harness = Harness(scope=scope)

    with pytest.raises(
        WorkflowTransitionError,
        match="formal export requires a valid durable checkpoint",
    ) as captured:
        harness.workflow.synthesize_claims(corrupt)

    assert isinstance(captured.value.__cause__, WorkflowTransitionError)
    assert str(captured.value.__cause__) == "cross-task evidence authority is invalid"
    assert harness.collector.calls == []
    assert harness.synthesis.prior_hashes == []
    assert harness.semantic.calls == []
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0


@pytest.mark.parametrize(
    "target",
    ["pending", "approval", "export_hash", "run", "task", "source", "evidence"],
)
def test_corrupt_exported_resumes_fail_before_idempotent_return(target: str) -> None:
    harness = Harness()
    exported = _run_until_terminal(harness.workflow, _initial())
    if target == "pending":
        corrupt = exported.model_copy(update={"pending_draft": None})
    elif target == "approval":
        assert exported.active_approval is not None
        approval = exported.active_approval.model_copy(update={"report_content_hash": HASH_TWO})
        corrupt = exported.model_copy(update={"active_approval": approval})
    elif target == "export_hash":
        assert exported.export_record is not None
        record = exported.export_record.model_copy(update={"report_content_hash": HASH_TWO})
        corrupt = exported.model_copy(update={"export_record": record})
    elif target == "run":
        corrupt = exported.model_copy(update={"run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"})
    else:
        task = exported.source_tasks[0]
        if target == "task":
            task = task.model_copy(update={"task_id": "source-task:foreign"})
        elif target == "source":
            task = task.model_copy(update={"source": SourceType.DAILYMED})
        else:
            evidence = task.evidence_refs[0].model_copy(update={"source": SourceType.DAILYMED})
            task = task.model_copy(update={"evidence_refs": (evidence,)})
        corrupt = exported.model_copy(update={"source_tasks": (task,)})
    before = (harness.persistence.calls, harness.approval.calls, harness.export.calls)
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        harness.workflow.run_next(corrupt)
    assert before == (harness.persistence.calls, harness.approval.calls, harness.export.calls)
    assert len(harness.semantic.calls) == 1


def test_stage1_failure_and_pure_binding_failure_invoke_no_new_evaluator_or_effect() -> None:
    harness = Harness()
    validating = _run_until_node(harness.workflow, _initial(), WorkflowNode.VALIDATE_REPORT)
    object.__setattr__(harness.registry, "scope_id", "scope:foreign")
    blocked = harness.workflow.validate_report(validating)
    assert blocked.disposition is WorkflowDisposition.VALIDATION_BLOCKED
    assert harness.semantic.calls == []
    assert harness.persistence.calls == 0
    assert harness.approval.calls == 0
    assert harness.export.calls == 0

    bound = Harness()
    saving = _run_until_node(bound.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    assert len(bound.semantic.calls) == 1
    object.__setattr__(bound.registry, "scope_id", "scope:foreign")
    with pytest.raises(WorkflowTransitionError, match="binding verification failed"):
        bound.workflow.save_pending_draft(saving)
    assert len(bound.semantic.calls) == 1
    assert bound.persistence.calls == 0


def test_canonical_exception_and_nonterminal_stored_validation_fail_closed() -> None:
    malformed = Harness()
    validating = _run_until_node(malformed.workflow, _initial(), WorkflowNode.VALIDATE_REPORT)
    object.__setattr__(
        malformed.registry,
        "evaluator_identity",
        EvaluatorIdentityInput("", IDENTITY.version),
    )
    with pytest.raises(WorkflowTransitionError, match="canonical report validation failed"):
        malformed.workflow.validate_report(validating)
    assert malformed.semantic.calls == []
    assert malformed.persistence.calls == 0

    nonterminal = Harness()
    approved = _run_until_node(nonterminal.workflow, _initial(), WorkflowNode.FINALIZE_AND_EXPORT)
    reset = approved.model_copy(update={"validation": ReportValidationState()})
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        nonterminal.workflow.finalize_and_export(reset)
    assert nonterminal.export.calls == 0
    assert len(nonterminal.semantic.calls) == 1


@pytest.mark.parametrize("route", ["save", "approval", "export"])
def test_untrusted_effect_results_are_reconstructed_and_rejected(route: str) -> None:
    harness = Harness()
    node = {
        "save": WorkflowNode.SAVE_PENDING_DRAFT,
        "approval": WorkflowNode.REQUEST_EXPORT_APPROVAL,
        "export": WorkflowNode.FINALIZE_AND_EXPORT,
    }[route]
    state = _run_until_node(harness.workflow, _initial(), node)
    foreign_report = "report:sha256:" + "f" * 64
    if route == "save":
        harness.persistence.report_id_override = foreign_report
        operation = harness.workflow.save_pending_draft
    elif route == "approval":
        harness.approval.report_id_override = foreign_report
        operation = harness.workflow.request_export_approval
    else:
        harness.export.report_id_override = foreign_report
        operation = harness.workflow.finalize_and_export
    with pytest.raises(
        WorkflowTransitionError,
        match=r"identity drift|not bound|does not bind",
    ):
        operation(state)
    assert harness.persistence.calls == 1
    assert harness.approval.calls == (1 if route in {"approval", "export"} else 0)
    assert harness.export.calls == (1 if route == "export" else 0)


def test_direct_transition_guards_reject_wrong_status_and_failed_validation() -> None:
    save_harness = Harness()
    saving = _run_until_node(save_harness.workflow, _initial(), WorkflowNode.SAVE_PENDING_DRAFT)
    failed = ReportValidationState(
        structural_citation_gate=GateStatus.FAILED,
        semantic_support_gate=GateStatus.FAILED,
        safety_policy_gate=GateStatus.FAILED,
        reason_codes=("forged_failure",),
    )
    with pytest.raises(WorkflowTransitionError, match="failed validation"):
        save_harness.workflow.save_pending_draft(saving.model_copy(update={"validation": failed}))
    assert save_harness.persistence.calls == 0

    approval_harness = Harness()
    approval = _run_until_node(
        approval_harness.workflow, _initial(), WorkflowNode.REQUEST_EXPORT_APPROVAL
    )
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        approval_harness.workflow.request_export_approval(
            approval.model_copy(update={"report_status": ReportStatus.DRAFT})
        )
    assert approval_harness.approval.calls == 0

    export_harness = Harness()
    exporting = _run_until_node(
        export_harness.workflow, _initial(), WorkflowNode.FINALIZE_AND_EXPORT
    )
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        export_harness.workflow.finalize_and_export(
            exporting.model_copy(update={"active_approval": None})
        )
    assert export_harness.export.calls == 0


def test_terminal_disposition_fields_and_decisions_are_revalidated() -> None:
    blocked_harness = Harness(validation_passed=False)
    blocked = _run_until_terminal(blocked_harness.workflow, _initial())
    forged_validation = ReportValidationState(
        structural_citation_gate=GateStatus.PASSED,
        semantic_support_gate=GateStatus.PASSED,
        safety_policy_gate=GateStatus.PASSED,
    )
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        blocked_harness.workflow.run_next(
            blocked.model_copy(update={"validation": forged_validation})
        )
    assert blocked_harness.persistence.calls == 0

    rejected_harness = Harness(decisions=[ReviewDecision.REJECT])
    rejected = _run_until_terminal(rejected_harness.workflow, _initial())
    forged_review = rejected.review_history[-1].model_copy(
        update={"report_id": REPORT_ID[:-1] + "b"}
    )
    with pytest.raises(WorkflowTransitionError, match="valid durable checkpoint"):
        rejected_harness.workflow.run_next(
            rejected.model_copy(update={"review_history": (forged_review,)})
        )
    assert rejected_harness.export.calls == 0


def test_closed_application_composition_ast_and_runtime_inventory() -> None:
    harness = Harness()
    assert not hasattr(harness.workflow, "__dict__")
    assert not hasattr(harness.workflow, "_dispatch")
    parameters = inspect.signature(ControlledOrchestrationWorkflow).parameters
    assert "validation_registry" in parameters
    assert "semantic_result_provider" in parameters
    assert "validation_receipt_store" in parameters
    assert "report_validation" not in parameters

    path = Path(inspect.getsourcefile(ControlledOrchestrationWorkflow) or "")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {item.name: item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef)}

    def attribute_call_lines(method: str, attribute: str) -> list[int]:
        return [
            item.lineno
            for item in ast.walk(methods[method])
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == attribute
        ]

    def named_call_lines(method: str, name: str) -> list[int]:
        return [
            item.lineno
            for item in ast.walk(methods[method])
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == name
        ]

    calls = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "canonical_validate_report"
    ]
    assert len(calls) == 2
    modes = {
        keyword.value.attr
        for call in calls
        for keyword in call.keywords
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Attribute)
    }
    assert modes == {"ASSESS", "VERIFY_BINDING"}
    assert attribute_call_lines("validate_report", "_persist_validation_receipt")
    receipt_save_lines = attribute_call_lines("_persist_validation_receipt", "save_receipt")
    receipt_load_lines = attribute_call_lines("_persist_validation_receipt", "load_receipt")
    receipt_ref_lines = named_call_lines("_persist_validation_receipt", "ValidationReceiptRef")
    receipt_payload_lines = named_call_lines(
        "_persist_validation_receipt",
        "canonical_validation_receipt_payload",
    )
    persisted_reconstruction_lines = named_call_lines(
        "_persist_validation_receipt",
        "validation_receipt_from_payload",
    )
    assert len(receipt_save_lines) == len(receipt_load_lines) == len(receipt_ref_lines) == 1
    assert len(receipt_payload_lines) == 1
    assert len(persisted_reconstruction_lines) == 2
    assert (
        receipt_payload_lines[0]
        < receipt_save_lines[0]
        < persisted_reconstruction_lines[0]
        < receipt_load_lines[0]
        < persisted_reconstruction_lines[1]
        < receipt_ref_lines[0]
    )
    verify_load_lines = attribute_call_lines("_verify_binding", "load_receipt")
    verify_request_lines = attribute_call_lines("_verify_binding", "_build_validation_request")
    verify_canonical_lines = named_call_lines("_verify_binding", "canonical_validate_report")
    verify_pending_lines = attribute_call_lines("_verify_binding", "_verify_pending_draft")
    verify_reconstruction_lines = named_call_lines(
        "_verify_binding",
        "validation_receipt_from_payload",
    )
    verify_receipt_lines = named_call_lines("_verify_binding", "verify_validation_receipt")
    assert len(verify_load_lines) == len(verify_reconstruction_lines) == 1
    assert len(verify_request_lines) == 1
    assert len(verify_canonical_lines) == 1
    assert len(verify_pending_lines) == 1
    assert len(verify_receipt_lines) == 1
    assert (
        verify_request_lines[0]
        < verify_canonical_lines[0]
        < verify_pending_lines[0]
        < verify_load_lines[0]
        < verify_reconstruction_lines[0]
        < verify_receipt_lines[0]
    )

    for method, effect in (
        ("save_pending_draft", "save_pending"),
        ("request_export_approval", "request_approval"),
        ("finalize_and_export", "finalize"),
    ):
        verify_lines = attribute_call_lines(method, "_verify_binding")
        effect_lines = attribute_call_lines(method, effect)
        assert len(verify_lines) == 1
        assert len(effect_lines) == 1
        assert verify_lines[0] < effect_lines[0]
    builders = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "_build_validation_request"
    ]
    assert len(builders) == 1
    binding_calls = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and item.func.attr == "_verify_binding"
    ]
    assert len(binding_calls) == 4
    critical_methods = {
        "run_next",
        "validate_report",
        "save_pending_draft",
        "request_export_approval",
        "finalize_and_export",
        "_build_validation_request",
        "_persist_validation_receipt",
        "_verify_binding",
        "_verify_pending_draft",
        "_reconstruct_pending_draft",
        "_validate_durable_state",
    }
    instance_private_helper_calls = [
        item
        for method in critical_methods
        for item in ast.walk(methods[method])
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Attribute)
        and isinstance(item.func.value, ast.Name)
        and item.func.value.id == "self"
        and item.func.attr.startswith("_")
    ]
    assert instance_private_helper_calls == []
    require_pass_values = [
        keyword.value
        for call in binding_calls
        for keyword in call.keywords
        if keyword.arg == "require_pass"
    ]
    assert len(require_pass_values) == 4
    assert (
        sum(
            isinstance(value, ast.Constant) and value.value is True for value in require_pass_values
        )
        == 3
    )
    assert sum(isinstance(value, ast.Compare) for value in require_pass_values) == 1
    receipt_ref_writes = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "ValidationReceiptRef"
    ]
    assert len(receipt_ref_writes) == 1
    assert "validation_receipt" not in OrchestrationState.model_fields
    assert "validation_receipt_ref" in OrchestrationState.model_fields
    validation_writes = [
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.Call)
        and isinstance(item.func, ast.Name)
        and item.func.id == "ReportValidationState"
    ]
    assert len(validation_writes) == 3
    assert sum(bool(item.keywords) for item in validation_writes) == 1
    assert "ReportValidationPort" not in source
    assert "bind_report_validation_operation" not in source
    assert "OrchestrationReportValidation" not in source
    production_root = path.parents[1]
    production_sources = tuple(production_root.rglob("*.py"))
    assert production_sources
    forbidden_authorities = (
        "ReportValidationPort",
        "bind_report_validation_operation",
        "OrchestrationReportValidation",
    )
    for candidate in production_sources:
        candidate_source = candidate.read_text(encoding="utf-8")
        assert not any(name in candidate_source for name in forbidden_authorities)
    for relative in ("orchestration/ports.py", "orchestration/__init__.py"):
        candidate_source = (production_root / relative).read_text(encoding="utf-8")
        assert not any(name in candidate_source for name in forbidden_authorities)
