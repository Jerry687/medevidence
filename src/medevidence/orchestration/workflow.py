"""Thin deterministic transitions for the Owner-frozen eight-node workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from medevidence.domain import PlanningStatus, ResearchScope, canonical_json, sha256_digest
from medevidence.domain.identifiers import derive_identity

from .contracts import (
    MAX_SOURCE_TASK_ATTEMPTS,
    WORKFLOW_TOPOLOGY,
    CollectedEvidenceResult,
    CollectionFailureClassification,
    ExportRecord,
    OrchestrationState,
    PendingDraftRef,
    ReportStatus,
    ReportValidationState,
    ReviewDecision,
    ReviewRecord,
    SafetyOutcome,
    ScopeSafetyEvaluation,
    SourceTaskFailureRef,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
    WorkflowDisposition,
    WorkflowNode,
    source_task_attempt,
    source_task_id,
)
from .ports import (
    DraftPersistencePort,
    EvidenceCollectionPort,
    ExportApprovalPort,
    ExportPort,
    ReportValidationPort,
    ScopeSafetyPort,
    SourcePlanningPort,
    SynthesisPort,
)


class WorkflowTransitionError(ValueError):
    """Raised when a caller attempts to bypass a frozen workflow transition."""


class WorkflowExecutionError(RuntimeError):
    """Non-retryable unexpected capability failure at the workflow boundary."""

    retryable = False

    def __init__(self, *, task_id: str, attempt_id: str) -> None:
        self.task_id = task_id
        self.attempt_id = attempt_id
        super().__init__("unexpected collection-port error; automatic retry is prohibited")


class ControlledOrchestrationWorkflow:
    """Coordinate injected capabilities without owning their business logic."""

    def __init__(
        self,
        *,
        scope_safety: ScopeSafetyPort,
        source_planning: SourcePlanningPort,
        evidence_collection: EvidenceCollectionPort,
        synthesis: SynthesisPort,
        report_validation: ReportValidationPort,
        draft_persistence: DraftPersistencePort,
        export_approval: ExportApprovalPort,
        export: ExportPort,
    ) -> None:
        self._scope_safety = scope_safety
        self._source_planning = source_planning
        self._evidence_collection = evidence_collection
        self._synthesis = synthesis
        self._report_validation = report_validation
        self._draft_persistence = draft_persistence
        self._export_approval = export_approval
        self._export = export
        self._dispatch: dict[
            WorkflowNode,
            Callable[[OrchestrationState], OrchestrationState],
        ] = {
            WorkflowNode.SCOPE_AND_SAFETY: self.scope_and_safety,
            WorkflowNode.PLAN_SOURCES: self.plan_sources,
            WorkflowNode.COLLECT_EVIDENCE: self.collect_evidence,
            WorkflowNode.SYNTHESIZE_CLAIMS: self.synthesize_claims,
            WorkflowNode.VALIDATE_REPORT: self.validate_report,
            WorkflowNode.SAVE_PENDING_DRAFT: self.save_pending_draft,
            WorkflowNode.REQUEST_EXPORT_APPROVAL: self.request_export_approval,
            WorkflowNode.FINALIZE_AND_EXPORT: self.finalize_and_export,
        }

    def run_next(self, state: OrchestrationState) -> OrchestrationState:
        """Run exactly the current node, or return an already terminal checkpoint."""

        state = self._validate_durable_state(state)
        if state.current_node is None:
            return state
        return self._dispatch[state.current_node](state)

    def scope_and_safety(self, state: OrchestrationState) -> OrchestrationState:
        """Interpret and classify the immutable original scope before any source work."""

        self._require_node(state, WorkflowNode.SCOPE_AND_SAFETY)
        raw = self._scope_safety.evaluate(state.original_scope)
        result = ScopeSafetyEvaluation.model_validate(raw.model_dump(mode="python"))
        if result.interpreted_scope.selected_sources != state.original_scope.selected_sources:
            raise WorkflowTransitionError("scope interpretation cannot expand source permissions")
        if result.decision.outcome is SafetyOutcome.BLOCKED:
            return self._complete(
                state,
                node=WorkflowNode.SCOPE_AND_SAFETY,
                next_node=None,
                interpreted_scope=result.interpreted_scope,
                safety_decision=result.decision,
                disposition=WorkflowDisposition.POLICY_BLOCKED,
            )
        return self._complete(
            state,
            node=WorkflowNode.SCOPE_AND_SAFETY,
            next_node=WorkflowNode.PLAN_SOURCES,
            interpreted_scope=result.interpreted_scope,
            safety_decision=result.decision,
        )

    def plan_sources(self, state: OrchestrationState) -> OrchestrationState:
        """Create one task for each selected planning row and none for skipped rows."""

        self._require_node(state, WorkflowNode.PLAN_SOURCES)
        scope = self._require_interpreted_scope(state)
        decision = state.safety_decision
        if decision is None or decision.outcome is not SafetyOutcome.PERMITTED:
            raise WorkflowTransitionError("source planning requires a permitted safety decision")
        plan = tuple(self._source_planning.plan(scope, decision))
        tasks = tuple(
            SourceTaskState(
                task_id=source_task_id(state.run_id, row.source),
                source=row.source,
            )
            for row in plan
            if row.planning_status is PlanningStatus.SELECTED
        )
        return self._complete(
            state,
            node=WorkflowNode.PLAN_SOURCES,
            next_node=WorkflowNode.COLLECT_EVIDENCE,
            source_plan=plan,
            source_tasks=tasks,
        )

    def collect_evidence(self, state: OrchestrationState) -> OrchestrationState:
        """Checkpoint or dispatch at most one bounded logical source attempt."""

        self._require_node(state, WorkflowNode.COLLECT_EVIDENCE)
        scope = self._require_interpreted_scope(state)
        for index, task in enumerate(state.source_tasks):
            if task.status is SourceTaskStatus.TERMINAL:
                continue
            if task.status in {
                SourceTaskStatus.PENDING,
                SourceTaskStatus.RETRY_WAIT,
            }:
                attempt = source_task_attempt(task.task_id, task.attempts + 1)
                running = SourceTaskState(
                    task_id=task.task_id,
                    source=task.source,
                    status=SourceTaskStatus.RUNNING,
                    attempts=attempt.attempt_number,
                    active_attempt=attempt,
                    failure_history=task.failure_history,
                )
                return self._checkpoint_source_task(state, index, running)
            if task.status is SourceTaskStatus.FAILED:
                return self._replace(
                    state,
                    checkpoint_id=self._next_checkpoint_id(
                        state,
                        WorkflowNode.COLLECT_EVIDENCE,
                    ),
                    current_node=None,
                    disposition=WorkflowDisposition.COLLECTION_BLOCKED,
                )

            running_attempt = task.active_attempt
            if running_attempt is None:
                raise WorkflowTransitionError("running source task lacks its attempt")
            try:
                raw = self._evidence_collection.collect(task, scope, running_attempt)
            except Exception as error:
                raise WorkflowExecutionError(
                    task_id=task.task_id,
                    attempt_id=running_attempt.attempt_id,
                ) from error

            if isinstance(raw, SourceTaskFailureRef):
                failure = SourceTaskFailureRef.model_validate(raw.model_dump(mode="python"))
                if failure.attempt != running_attempt:
                    raise WorkflowTransitionError("collection failure belongs to another attempt")
                failures = (*task.failure_history, failure)
                if (
                    failure.classification is CollectionFailureClassification.RETRYABLE
                    and task.attempts < MAX_SOURCE_TASK_ATTEMPTS
                ):
                    retry_wait = SourceTaskState(
                        task_id=task.task_id,
                        source=task.source,
                        status=SourceTaskStatus.RETRY_WAIT,
                        attempts=task.attempts,
                        failure_history=failures,
                    )
                    return self._checkpoint_source_task(state, index, retry_wait)
                failed = SourceTaskState(
                    task_id=task.task_id,
                    source=task.source,
                    status=SourceTaskStatus.FAILED,
                    attempts=task.attempts,
                    failure_history=failures,
                )
                failed_state = self._with_source_task(state, index, failed)
                return self._replace(
                    failed_state,
                    checkpoint_id=self._next_checkpoint_id(
                        failed_state,
                        WorkflowNode.COLLECT_EVIDENCE,
                    ),
                    current_node=None,
                    disposition=WorkflowDisposition.COLLECTION_BLOCKED,
                )

            if not isinstance(raw, CollectedEvidenceResult):
                raise WorkflowTransitionError("collection port returned an unknown contract")
            result = CollectedEvidenceResult.model_validate(raw.model_dump(mode="python"))
            if result.attempt != running_attempt:
                raise WorkflowTransitionError("collection result belongs to another attempt")
            if result.terminal_outcome_ref.outcome.source is not task.source:
                raise WorkflowTransitionError("collection result belongs to another source")
            if result.terminal_outcome_ref.acquisition.run_id != state.run_id:
                raise WorkflowTransitionError("collection result belongs to another run")
            terminal = SourceTaskState(
                task_id=task.task_id,
                source=task.source,
                status=SourceTaskStatus.TERMINAL,
                attempts=task.attempts,
                failure_history=task.failure_history,
                terminal_outcome_ref=result.terminal_outcome_ref,
                evidence_refs=result.evidence_refs,
            )
            return self._checkpoint_source_task(state, index, terminal)
        return self._complete(
            state,
            node=WorkflowNode.COLLECT_EVIDENCE,
            next_node=WorkflowNode.SYNTHESIZE_CLAIMS,
        )

    def synthesize_claims(self, state: OrchestrationState) -> OrchestrationState:
        """Invoke the injected synthesis capability only after all selected tasks terminate."""

        self._require_node(state, WorkflowNode.SYNTHESIZE_CLAIMS)
        scope = self._require_interpreted_scope(state)
        if any(task.status is not SourceTaskStatus.TERMINAL for task in state.source_tasks):
            raise WorkflowTransitionError("selected but unexecuted source blocks synthesis")
        raw = self._synthesis.synthesize(
            run_id=state.run_id,
            report_id=state.report_id,
            scope=scope,
            source_tasks=state.source_tasks,
            prior_report_content_hash=state.edit_base_content_hash,
        )
        synthesis = SynthesisState.model_validate(raw.model_dump(mode="python"))
        if (
            state.edit_base_content_hash is not None
            and synthesis.report_content_hash == state.edit_base_content_hash
        ):
            raise WorkflowTransitionError("an edit must change the report content hash")
        return self._complete(
            state,
            node=WorkflowNode.SYNTHESIZE_CLAIMS,
            next_node=WorkflowNode.VALIDATE_REPORT,
            synthesis=synthesis,
            validation=ReportValidationState(),
            report_status=ReportStatus.DRAFT,
            pending_draft=None,
            active_approval=None,
            export_record=None,
            edit_base_content_hash=None,
        )

    def validate_report(self, state: OrchestrationState) -> OrchestrationState:
        """Apply externally implemented citation and safety gates."""

        self._require_node(state, WorkflowNode.VALIDATE_REPORT)
        scope = self._require_interpreted_scope(state)
        synthesis = self._require_synthesis(state)
        raw = self._report_validation.validate(
            run_id=state.run_id,
            report_id=state.report_id,
            scope=scope,
            source_tasks=state.source_tasks,
            synthesis=synthesis,
        )
        validation = ReportValidationState.model_validate(raw.model_dump(mode="python"))
        if not validation.passed:
            return self._complete(
                state,
                node=WorkflowNode.VALIDATE_REPORT,
                next_node=None,
                validation=validation,
                disposition=WorkflowDisposition.VALIDATION_BLOCKED,
            )
        return self._complete(
            state,
            node=WorkflowNode.VALIDATE_REPORT,
            next_node=WorkflowNode.SAVE_PENDING_DRAFT,
            validation=validation,
        )

    def save_pending_draft(self, state: OrchestrationState) -> OrchestrationState:
        """Persist the validated pending draft through an idempotent capability."""

        self._require_node(state, WorkflowNode.SAVE_PENDING_DRAFT)
        synthesis = self._require_synthesis(state)
        if not state.validation.passed:
            raise WorkflowTransitionError("failed validation cannot reach pending review")
        raw = self._draft_persistence.save_pending(
            report_id=state.report_id,
            report_content_hash=synthesis.report_content_hash,
        )
        pending = PendingDraftRef.model_validate(raw.model_dump(mode="python"))
        if (
            pending.report_id != state.report_id
            or pending.report_content_hash != synthesis.report_content_hash
        ):
            raise WorkflowTransitionError("persisted pending draft identity drift")
        return self._complete(
            state,
            node=WorkflowNode.SAVE_PENDING_DRAFT,
            next_node=WorkflowNode.REQUEST_EXPORT_APPROVAL,
            pending_draft=pending,
            report_status=ReportStatus.PENDING_REVIEW,
        )

    def request_export_approval(self, state: OrchestrationState) -> OrchestrationState:
        """Process the sole human interrupt: approve, reject, or edit."""

        self._require_node(state, WorkflowNode.REQUEST_EXPORT_APPROVAL)
        synthesis = self._require_synthesis(state)
        if state.report_status is not ReportStatus.PENDING_REVIEW:
            raise WorkflowTransitionError("approval requires a pending-review report")
        raw = self._export_approval.request_approval(
            report_id=state.report_id,
            report_content_hash=synthesis.report_content_hash,
            destination=state.destination,
            source_tasks=state.source_tasks,
            warning_codes=synthesis.warning_codes,
        )
        review = ReviewRecord.model_validate(raw.model_dump(mode="python"))
        expected_outcome_refs = tuple(
            task.terminal_outcome_ref
            for task in state.source_tasks
            if task.terminal_outcome_ref is not None
        )
        if (
            review.report_id != state.report_id
            or review.report_content_hash != synthesis.report_content_hash
            or review.destination != state.destination
            or review.source_outcome_refs != expected_outcome_refs
            or review.warning_codes != synthesis.warning_codes
        ):
            raise WorkflowTransitionError("review decision is not bound to the pending draft")
        history = (*state.review_history, review)
        if review.decision is ReviewDecision.APPROVE:
            return self._complete(
                state,
                node=WorkflowNode.REQUEST_EXPORT_APPROVAL,
                next_node=WorkflowNode.FINALIZE_AND_EXPORT,
                review_history=history,
                active_approval=review,
                report_status=ReportStatus.APPROVED,
            )
        if review.decision is ReviewDecision.REJECT:
            return self._complete(
                state,
                node=WorkflowNode.REQUEST_EXPORT_APPROVAL,
                next_node=None,
                review_history=history,
                active_approval=None,
                report_status=ReportStatus.REJECTED,
                disposition=WorkflowDisposition.REJECTED,
            )

        retained_nodes = tuple(
            node
            for node in state.completed_nodes
            if WORKFLOW_TOPOLOGY.index(node)
            < WORKFLOW_TOPOLOGY.index(WorkflowNode.SYNTHESIZE_CLAIMS)
        )
        return self._replace(
            state,
            checkpoint_id=self._next_checkpoint_id(
                state,
                WorkflowNode.REQUEST_EXPORT_APPROVAL,
            ),
            completed_nodes=retained_nodes,
            current_node=WorkflowNode.SYNTHESIZE_CLAIMS,
            review_history=history,
            active_approval=None,
            pending_draft=None,
            synthesis=None,
            validation=ReportValidationState(),
            report_status=ReportStatus.DRAFT,
            edit_base_content_hash=synthesis.report_content_hash,
        )

    def finalize_and_export(self, state: OrchestrationState) -> OrchestrationState:
        """Finalize exactly once after approval and reuse an existing export on resume."""

        state = self._validate_durable_state(state)

        selected_sources = tuple(
            row.source
            for row in state.source_plan
            if row.planning_status is PlanningStatus.SELECTED
        )
        task_sources = tuple(task.source for task in state.source_tasks)
        terminal_sources = tuple(
            task.source
            for task in state.source_tasks
            if task.status is SourceTaskStatus.TERMINAL and task.terminal_outcome_ref is not None
        )
        if (
            len(set(selected_sources)) != len(selected_sources)
            or len(set(task_sources)) != len(task_sources)
            or len(set(terminal_sources)) != len(terminal_sources)
            or selected_sources != task_sources
            or task_sources != terminal_sources
        ):
            raise WorkflowTransitionError(
                "formal export requires a terminal SourceOutcome reference "
                "for every unique ordered selected source task"
            )
        if state.export_record is not None:
            return state
        self._require_node(state, WorkflowNode.FINALIZE_AND_EXPORT)
        synthesis = self._require_synthesis(state)
        approval = state.active_approval
        if (
            state.report_status is not ReportStatus.APPROVED
            or approval is None
            or approval.decision is not ReviewDecision.APPROVE
        ):
            raise WorkflowTransitionError("formal export requires an active approval")
        idempotency_key = sha256_digest(
            canonical_json(
                {
                    "report_id": state.report_id,
                    "report_content_hash": synthesis.report_content_hash,
                    "destination": state.destination,
                }
            )
        )
        raw = self._export.finalize(
            report_id=state.report_id,
            report_content_hash=synthesis.report_content_hash,
            destination=state.destination,
            idempotency_key=idempotency_key,
            approval=approval,
        )
        exported = ExportRecord.model_validate(raw.model_dump(mode="python"))
        if (
            exported.report_id != state.report_id
            or exported.report_content_hash != synthesis.report_content_hash
            or exported.destination != state.destination
            or exported.idempotency_key != idempotency_key
            or exported.approval_review_id != approval.review_id
        ):
            raise WorkflowTransitionError("export result does not bind the approved request")
        return self._complete(
            state,
            node=WorkflowNode.FINALIZE_AND_EXPORT,
            next_node=None,
            export_record=exported,
            report_status=ReportStatus.EXPORTED,
            disposition=WorkflowDisposition.EXPORTED,
        )

    @staticmethod
    def _require_node(state: OrchestrationState, expected: WorkflowNode) -> None:
        if state.disposition is not WorkflowDisposition.ACTIVE:
            raise WorkflowTransitionError("terminal workflow cannot execute another node")
        if state.current_node is not expected:
            raise WorkflowTransitionError(
                f"expected current node {expected.value}, got {state.current_node}"
            )
        if expected not in state.permissions.allowed_nodes:
            raise WorkflowTransitionError("workflow node is not permitted")

    @staticmethod
    def _require_interpreted_scope(state: OrchestrationState) -> ResearchScope:
        if state.interpreted_scope is None:
            raise WorkflowTransitionError("interpreted scope is not available")
        return state.interpreted_scope

    @staticmethod
    def _require_synthesis(state: OrchestrationState) -> SynthesisState:
        if state.synthesis is None:
            raise WorkflowTransitionError("synthesized report is not available")
        return state.synthesis

    def _complete(
        self,
        state: OrchestrationState,
        *,
        node: WorkflowNode,
        next_node: WorkflowNode | None,
        **changes: Any,
    ) -> OrchestrationState:
        if node in state.completed_nodes:
            raise WorkflowTransitionError("completed workflow node cannot be repeated")
        return self._replace(
            state,
            checkpoint_id=self._next_checkpoint_id(state, node),
            completed_nodes=(*state.completed_nodes, node),
            current_node=next_node,
            **changes,
        )

    @staticmethod
    def _replace(state: OrchestrationState, **changes: Any) -> OrchestrationState:
        payload = state.model_dump(mode="python")
        payload.update(changes)
        return OrchestrationState.model_validate(payload)

    @staticmethod
    def _validate_durable_state(state: OrchestrationState) -> OrchestrationState:
        try:
            return OrchestrationState.model_validate(state.model_dump(mode="python"))
        except ValidationError as error:
            raise WorkflowTransitionError(
                "formal export requires a valid durable checkpoint"
            ) from error

    def _checkpoint_source_task(
        self,
        state: OrchestrationState,
        index: int,
        task: SourceTaskState,
    ) -> OrchestrationState:
        updated = self._with_source_task(state, index, task)
        return self._replace(
            updated,
            checkpoint_id=self._next_checkpoint_id(
                updated,
                WorkflowNode.COLLECT_EVIDENCE,
            ),
        )

    @staticmethod
    def _with_source_task(
        state: OrchestrationState,
        index: int,
        task: SourceTaskState,
    ) -> OrchestrationState:
        tasks = list(state.source_tasks)
        tasks[index] = task
        return ControlledOrchestrationWorkflow._replace(
            state,
            source_tasks=tuple(tasks),
        )

    @staticmethod
    def _next_checkpoint_id(state: OrchestrationState, node: WorkflowNode) -> str:
        return derive_identity(
            "checkpoint",
            {
                "workflow_id": state.workflow_id,
                "previous_checkpoint_id": state.checkpoint_id,
                "node": node,
                "completed_count": len(state.completed_nodes) + 1,
            },
        )
