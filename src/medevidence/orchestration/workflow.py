"""Thin deterministic transitions for the Owner-frozen eight-node workflow."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, final

from pydantic import ValidationError

from medevidence.domain import PlanningStatus, ResearchScope, canonical_json, sha256_digest
from medevidence.domain.identifiers import derive_identity
from medevidence.tools.report_validation import (
    M3_VALIDATION_CONFIGURATION_V3,
    CanonicalReportRequest,
    PlannedStage2SemanticInputV2,
    ReportValidationAudit,
    SemanticEvaluationPortV2,
    SemanticResultProvider,
    Stage1ReceiptV2,
    ValidationMode,
    ValidationReceiptV2,
    ValidationRegistryInput,
    _copy_registry,
    _is_v2_family_configuration,
    _primitive,
    _require_v3_semantic_port_identity,
    _require_v4_semantic_port_identity,
    canonical_stage1_receipt_payload_v2,
    canonical_validate_report,
    canonical_validation_receipt_payload,
    stage1_receipt_from_payload_v2,
    stage2_projections_from_receipt_v2,
    validation_receipt_from_payload,
    verify_validation_receipt,
)
from medevidence.tools.report_validation_v3 import M3_VALIDATION_CONFIGURATION_V4

from .contracts import (
    WORKFLOW_TOPOLOGY,
    CollectedEvidenceResult,
    ExportRecord,
    GateStatus,
    OrchestrationState,
    PendingDraftRef,
    ReportStatus,
    ReportValidationState,
    ReviewDecision,
    ReviewRecord,
    RuntimeContext,
    SafetyOutcome,
    ScopeSafetyEvaluation,
    SourceTaskFailureRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    Stage1ReceiptRef,
    SynthesisState,
    ValidationReceiptRef,
    ValidationRegistryRef,
    WorkflowDisposition,
    WorkflowNode,
    export_idempotency_key,
    pending_draft_identity,
    source_task_attempt,
    source_task_id,
    validate_terminal_operation_binding,
)
from .ports import (
    DraftPersistencePort,
    EvidenceCollectionPort,
    ExportApprovalPort,
    ExportPort,
    ScopeSafetyPort,
    Stage1ReceiptStorePort,
    SynthesisPort,
    ValidationReceiptStorePort,
    ValidationRegistryProviderPort,
)
from .source_capabilities import (
    CanonicalSourcePlanningAuthority,
    SourceCapabilityContractError,
    checkpoint_source_task,
    exact_source_planning_authority,
    planned_running_source_task,
    replay_source_plan,
    replay_terminal_tasks,
    source_task_after_failure,
    source_task_after_progress,
    terminal_source_task,
    verify_running_source_plan,
    with_source_task,
)
from .validation_projection import (
    ValidationProjectionError,
    build_validation_request_projection,
    project_stored_validation,
)

__class__: type[ControlledOrchestrationWorkflow]


class WorkflowTransitionError(ValueError):
    """Raised when a caller attempts to bypass a frozen workflow transition."""


class WorkflowExecutionError(RuntimeError):
    """Non-retryable unexpected capability failure at the workflow boundary."""

    retryable = False

    def __init__(self, *, task_id: str, attempt_id: str) -> None:
        self.task_id = task_id
        self.attempt_id = attempt_id
        super().__init__("unexpected collection-port error; automatic retry is prohibited")


@final
class ControlledOrchestrationWorkflow:
    """Coordinate injected capabilities without owning their business logic."""

    # fmt: off
    __slots__ = ("_draft_persistence", "_evidence_collection", "_export", "_export_approval", "_runtime_context", "_scope_safety", "_semantic_result_provider", "_semantic_result_provider_v2", "_source_planning", "_stage1_receipt_store", "_synthesis", "_validation_receipt_store", "_validation_registry", "_validation_registry_provider")  # noqa: E501
    def __init_subclass__(cls, **kwargs: Any) -> None: raise TypeError("controlled workflow is final")  # noqa: E501
    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name): raise AttributeError("controlled workflow authority is immutable after construction")  # noqa: E501, E701
        object.__setattr__(self, name, value)
    # fmt: on

    def __init__(
        self,
        *,
        scope_safety: ScopeSafetyPort,
        source_planning: CanonicalSourcePlanningAuthority,
        evidence_collection: EvidenceCollectionPort,
        synthesis: SynthesisPort,
        validation_registry: ValidationRegistryInput | None = None,
        semantic_result_provider: SemanticResultProvider,
        validation_receipt_store: ValidationReceiptStorePort,
        draft_persistence: DraftPersistencePort,
        export_approval: ExportApprovalPort,
        export: ExportPort,
        semantic_result_provider_v2: SemanticEvaluationPortV2 | None = None,
        stage1_receipt_store: Stage1ReceiptStorePort | None = None,
        runtime_context: RuntimeContext | None = None,
        validation_registry_provider: ValidationRegistryProviderPort | None = None,
    ) -> None:
        fixed = validation_registry is not None
        dynamic = runtime_context is not None or validation_registry_provider is not None
        if fixed == dynamic or (
            dynamic and (runtime_context is None or validation_registry_provider is None)
        ):
            raise WorkflowTransitionError(
                "exactly one fixed or dynamic registry authority is required"
            )
        if fixed and type(validation_registry) is not ValidationRegistryInput:
            raise WorkflowTransitionError("fixed validation registry must use its exact type")
        if runtime_context is not None:
            if type(runtime_context) is not RuntimeContext:
                raise WorkflowTransitionError("runtime context must use its exact type")
            runtime_context = RuntimeContext.model_validate(
                runtime_context.model_dump(mode="python"), strict=True
            )
        self._scope_safety = scope_safety
        self._source_planning = exact_source_planning_authority(source_planning)
        self._evidence_collection = evidence_collection
        self._synthesis = synthesis
        self._validation_registry = validation_registry
        self._runtime_context = runtime_context
        self._validation_registry_provider = validation_registry_provider
        self._semantic_result_provider = semantic_result_provider
        self._semantic_result_provider_v2 = semantic_result_provider_v2
        self._stage1_receipt_store = stage1_receipt_store
        self._validation_receipt_store = validation_receipt_store
        self._draft_persistence = draft_persistence
        self._export_approval = export_approval
        self._export = export

    def run_next(self, state: OrchestrationState) -> OrchestrationState:
        """Run exactly the current node, or return an already terminal checkpoint."""
        state = __class__._validate_durable_state(self, state)
        if state.current_node is None:
            __class__._replay_source_plan(self, state)
            __class__._replay_terminal_tasks(self, state)
            if state.synthesis is not None:
                __class__._verify_binding(
                    self,
                    state,
                    require_pass=(state.disposition is not WorkflowDisposition.VALIDATION_BLOCKED),
                )
            return state
        if state.current_node is WorkflowNode.SCOPE_AND_SAFETY:
            return __class__.scope_and_safety(self, state)
        if state.current_node is WorkflowNode.PLAN_SOURCES:
            return __class__.plan_sources(self, state)
        if state.current_node is WorkflowNode.COLLECT_EVIDENCE:
            return __class__.collect_evidence(self, state)
        if state.current_node is WorkflowNode.SYNTHESIZE_CLAIMS:
            return __class__.synthesize_claims(self, state)
        if state.current_node is WorkflowNode.VALIDATE_REPORT:
            return __class__.validate_report(self, state)
        if state.current_node is WorkflowNode.SAVE_PENDING_DRAFT:
            return __class__.save_pending_draft(self, state)
        if state.current_node is WorkflowNode.REQUEST_EXPORT_APPROVAL:
            return __class__.request_export_approval(self, state)
        if state.current_node is WorkflowNode.FINALIZE_AND_EXPORT:
            return __class__.finalize_and_export(self, state)
        raise WorkflowTransitionError("current node is outside the frozen topology")

    def validate_terminal_sources(self, state: OrchestrationState) -> OrchestrationState:
        """Replay terminal source authority without advancing or mutating the workflow."""
        rebuilt = __class__._validate_durable_state(self, state)
        __class__._replay_source_plan(self, rebuilt)
        if any(task.status is SourceTaskStatus.TERMINAL for task in rebuilt.source_tasks):
            __class__._replay_terminal_tasks(self, rebuilt)
        return rebuilt

    def scope_and_safety(self, state: OrchestrationState) -> OrchestrationState:
        """Interpret and classify the immutable original scope before any source work."""
        state = __class__._validate_durable_state(self, state)
        __class__._require_node(state, WorkflowNode.SCOPE_AND_SAFETY)
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
        state = __class__._validate_durable_state(self, state)
        __class__._require_node(state, WorkflowNode.PLAN_SOURCES)
        scope = __class__._require_interpreted_scope(state)
        decision = state.safety_decision
        if decision is None or decision.outcome is not SafetyOutcome.PERMITTED:
            raise WorkflowTransitionError("source planning requires a permitted safety decision")
        try:
            plan = CanonicalSourcePlanningAuthority.plan(self._source_planning, scope, decision)
        except SourceCapabilityContractError as error:
            raise WorkflowTransitionError(str(error)) from error
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
        state = __class__.validate_terminal_sources(self, state)
        __class__._require_node(state, WorkflowNode.COLLECT_EVIDENCE)
        scope = __class__._require_interpreted_scope(state)
        for index, task in enumerate(state.source_tasks):
            if task.status is SourceTaskStatus.TERMINAL:
                continue
            if task.status in {SourceTaskStatus.PENDING, SourceTaskStatus.RETRY_WAIT}:
                attempt = source_task_attempt(task.task_id, task.attempts + 1)
                try:
                    running = planned_running_source_task(
                        self._evidence_collection, task, scope, attempt, state.run_id
                    )
                except SourceCapabilityContractError as error:
                    raise WorkflowTransitionError(str(error)) from error
                except Exception as error:
                    raise WorkflowExecutionError(
                        task_id=task.task_id, attempt_id=attempt.attempt_id
                    ) from error
                return checkpoint_source_task(state, index, running)
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
                verify_running_source_plan(
                    self._evidence_collection, task, scope, running_attempt, state.run_id
                )
                raw = self._evidence_collection.collect(task, scope, running_attempt)
            except SourceCapabilityContractError as error:
                raise WorkflowTransitionError(str(error)) from error
            except Exception as error:
                raise WorkflowExecutionError(
                    task_id=task.task_id,
                    attempt_id=running_attempt.attempt_id,
                ) from error
            if isinstance(raw, SourceTaskProgressResult):
                try:
                    progress = source_task_after_progress(task, raw, state.run_id)
                except SourceCapabilityContractError as error:
                    raise WorkflowTransitionError(str(error)) from error
                return checkpoint_source_task(state, index, progress)
            if isinstance(raw, SourceTaskFailureRef):
                try:
                    failed = source_task_after_failure(task, raw)
                except SourceCapabilityContractError as error:
                    raise WorkflowTransitionError(str(error)) from error
                if failed.status is SourceTaskStatus.RETRY_WAIT:
                    return checkpoint_source_task(state, index, failed)
                failed_state = with_source_task(state, index, failed)
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
            try:
                terminal = terminal_source_task(task, raw, state.run_id)
            except SourceCapabilityContractError as error:
                raise WorkflowTransitionError(str(error)) from error
            return checkpoint_source_task(state, index, terminal)
        return self._complete(
            state,
            node=WorkflowNode.COLLECT_EVIDENCE,
            next_node=WorkflowNode.SYNTHESIZE_CLAIMS,
        )

    def synthesize_claims(self, state: OrchestrationState) -> OrchestrationState:
        """Invoke the injected synthesis capability only after all selected tasks terminate."""
        state = __class__.validate_terminal_sources(self, state)
        __class__._require_node(state, WorkflowNode.SYNTHESIZE_CLAIMS)
        scope = __class__._require_interpreted_scope(state)
        if any(task.status is not SourceTaskStatus.TERMINAL for task in state.source_tasks):
            raise WorkflowTransitionError("selected but unexecuted source blocks synthesis")
        raw = self._synthesis.synthesize(
            run_id=state.run_id,
            report_id=state.report_id,
            scope=scope,
            source_plan=state.source_plan,
            source_tasks=state.source_tasks,
            prior_report_content_hash=state.edit_base_content_hash,
        )
        synthesis = SynthesisState.model_validate(raw.model_dump(mode="python"))
        __class__._registry_for(self, state, synthesis)
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
            validation_receipt_ref=None,
            stage1_receipt_ref=None,
            report_status=ReportStatus.DRAFT,
            pending_draft=None,
            active_approval=None,
            export_record=None,
            edit_base_content_hash=None,
        )

    def validate_report(self, state: OrchestrationState) -> OrchestrationState:
        """Apply externally implemented citation and safety gates."""
        state = __class__.validate_terminal_sources(self, state)
        __class__._require_node(state, WorkflowNode.VALIDATE_REPORT)
        request = __class__._build_validation_request(self, state, include_stored=False)
        is_v2_planned = (
            _is_v2_family_configuration(request.registry.configuration_version)
            and bool(request.registry.semantic_expectations)
            and all(
                type(item) is PlannedStage2SemanticInputV2
                for item in request.registry.semantic_expectations
            )
        )
        if (
            _is_v2_family_configuration(request.registry.configuration_version)
            and request.synthesis.citations
            and not is_v2_planned
        ):
            raise WorkflowTransitionError("V2 assessment requires an unlabelled citation plan")
        stage1_ref: Stage1ReceiptRef | None = None
        try:
            if request.registry.configuration_version == M3_VALIDATION_CONFIGURATION_V3:
                _require_v3_semantic_port_identity(self._semantic_result_provider_v2)
            elif request.registry.configuration_version == M3_VALIDATION_CONFIGURATION_V4:
                _require_v4_semantic_port_identity(self._semantic_result_provider_v2)
            if is_v2_planned:
                preflight = canonical_validate_report(request, mode=ValidationMode.PREPARE_STAGE1)
                stage1_receipt = preflight.stage1_receipt
                if stage1_receipt is not None:
                    stage1_ref = __class__._persist_stage1_receipt(self, stage1_receipt)
                audit = canonical_validate_report(
                    request,
                    mode=ValidationMode.ASSESS,
                    semantic_result_provider_v2=self._semantic_result_provider_v2,
                    stage1_receipt=stage1_receipt,
                )
            else:
                audit = canonical_validate_report(
                    request,
                    mode=ValidationMode.ASSESS,
                    semantic_result_provider=self._semantic_result_provider,
                )
        except Exception as error:
            raise WorkflowTransitionError("canonical report validation failed") from error
        receipt_ref = __class__._persist_validation_receipt(
            self, audit.resolved_request or request, audit
        )
        summary = audit.summary
        validation = ReportValidationState(
            structural_citation_gate=(
                GateStatus.PASSED if summary.structural_passed else GateStatus.FAILED
            ),
            semantic_support_gate=(
                GateStatus.PASSED if summary.semantic_passed else GateStatus.FAILED
            ),
            safety_policy_gate=(GateStatus.PASSED if summary.safety_passed else GateStatus.FAILED),
            reason_codes=summary.reason_codes,
        )
        if (
            validation.passed is not summary.passed
            or validation.reason_codes != summary.reason_codes
        ):
            raise WorkflowTransitionError("canonical validation mapping drift")
        if not validation.passed:
            return __class__._complete(
                self,
                state,
                node=WorkflowNode.VALIDATE_REPORT,
                next_node=None,
                validation=validation,
                validation_receipt_ref=receipt_ref,
                stage1_receipt_ref=stage1_ref,
                disposition=WorkflowDisposition.VALIDATION_BLOCKED,
            )
        return __class__._complete(
            self,
            state,
            node=WorkflowNode.VALIDATE_REPORT,
            next_node=WorkflowNode.SAVE_PENDING_DRAFT,
            validation=validation,
            validation_receipt_ref=receipt_ref,
            stage1_receipt_ref=stage1_ref,
        )

    def save_pending_draft(self, state: OrchestrationState) -> OrchestrationState:
        """Persist the validated pending draft through an idempotent capability."""
        state = __class__.validate_terminal_sources(self, state)
        __class__._require_node(state, WorkflowNode.SAVE_PENDING_DRAFT)
        synthesis = __class__._require_synthesis(state)
        if not state.validation.passed:
            raise WorkflowTransitionError("failed validation cannot reach pending review")
        pending_draft_persistence_id = __class__._pending_draft_persistence_id(
            state.report_id,
            synthesis.report_content_hash,
        )
        __class__._verify_binding(self, state, require_pass=True)
        raw = self._draft_persistence.save_pending(
            pending_draft_persistence_id=pending_draft_persistence_id,
            report_id=state.report_id,
            report_content_hash=synthesis.report_content_hash,
        )
        pending = __class__._reconstruct_pending_draft(raw)
        if (
            pending.persistence_id != pending_draft_persistence_id
            or pending.report_id != state.report_id
            or pending.report_content_hash != synthesis.report_content_hash
        ):
            raise WorkflowTransitionError("persisted pending draft identity drift")
        __class__._verify_pending_draft(self, pending)
        return __class__._complete(
            self,
            state,
            node=WorkflowNode.SAVE_PENDING_DRAFT,
            next_node=WorkflowNode.REQUEST_EXPORT_APPROVAL,
            pending_draft=pending,
            report_status=ReportStatus.PENDING_REVIEW,
        )

    def request_export_approval(self, state: OrchestrationState) -> OrchestrationState:
        """Process the sole human interrupt: approve, reject, or edit."""
        state = __class__.validate_terminal_sources(self, state)
        __class__._require_node(state, WorkflowNode.REQUEST_EXPORT_APPROVAL)
        synthesis = __class__._require_synthesis(state)
        if state.report_status is not ReportStatus.PENDING_REVIEW:
            raise WorkflowTransitionError("approval requires a pending-review report")
        pending = state.pending_draft
        if pending is None:
            raise WorkflowTransitionError("approval requires the exact persisted pending draft")
        __class__._verify_binding(self, state, require_pass=True)
        raw = self._export_approval.request_approval(
            report_id=state.report_id,
            report_content_hash=synthesis.report_content_hash,
            pending_draft_persistence_id=pending.persistence_id,
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
            or review.pending_draft_persistence_id != pending.persistence_id
            or review.destination != state.destination
            or review.source_outcome_refs != expected_outcome_refs
            or review.warning_codes != synthesis.warning_codes
        ):
            raise WorkflowTransitionError("review decision is not bound to the pending draft")
        history = (*state.review_history, review)
        if review.decision is ReviewDecision.APPROVE:
            return __class__._complete(
                self,
                state,
                node=WorkflowNode.REQUEST_EXPORT_APPROVAL,
                next_node=WorkflowNode.FINALIZE_AND_EXPORT,
                review_history=history,
                active_approval=review,
                report_status=ReportStatus.APPROVED,
            )
        if review.decision is ReviewDecision.REJECT:
            return __class__._complete(
                self,
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
        return __class__._replace(
            state,
            checkpoint_id=__class__._next_checkpoint_id(
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
            validation_receipt_ref=None,
            report_status=ReportStatus.DRAFT,
            edit_base_content_hash=synthesis.report_content_hash,
        )

    def finalize_and_export(self, state: OrchestrationState) -> OrchestrationState:
        """Finalize exactly once after approval and reuse an existing export on resume."""
        state = __class__.validate_terminal_sources(self, state)
        if state.export_record is None:
            __class__._require_node(state, WorkflowNode.FINALIZE_AND_EXPORT)
        __class__._verify_binding(self, state, require_pass=True)
        if state.export_record is not None:
            return state
        synthesis = __class__._require_synthesis(state)
        approval = state.active_approval
        if (
            state.report_status is not ReportStatus.APPROVED
            or approval is None
            or approval.decision is not ReviewDecision.APPROVE
        ):
            raise WorkflowTransitionError("formal export requires an active approval")
        idempotency_key = export_idempotency_key(
            state.report_id, synthesis.report_content_hash, state.destination
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
        return __class__._complete(
            self,
            state,
            node=WorkflowNode.FINALIZE_AND_EXPORT,
            next_node=None,
            export_record=exported,
            report_status=ReportStatus.EXPORTED,
            disposition=WorkflowDisposition.EXPORTED,
        )

    def _registry_for(
        self, state: OrchestrationState, synthesis: SynthesisState
    ) -> ValidationRegistryInput:
        fixed = self._validation_registry
        if fixed is not None:
            if synthesis.validation_registry_ref is not None:
                raise WorkflowTransitionError("fixed registry cannot accept a dynamic reference")
            return fixed
        context = self._runtime_context
        provider = self._validation_registry_provider
        reference = synthesis.validation_registry_ref
        if context is None or provider is None or type(reference) is not ValidationRegistryRef:
            raise WorkflowTransitionError("dynamic validation registry reference is missing")
        if (
            (context.run_id, context.report_id, context.scope_id)
            != (state.run_id, state.report_id, state.original_scope.scope_id)
            or (
                state.interpreted_scope is not None
                and state.interpreted_scope.scope_id != context.scope_id
            )
            or (
                reference.run_id,
                reference.report_id,
                reference.scope_id,
                reference.report_content_hash,
            )
            != (
                context.run_id,
                context.report_id,
                context.scope_id,
                synthesis.report_content_hash,
            )
        ):
            raise WorkflowTransitionError("dynamic registry context differs from the job")
        try:
            copied_reference = ValidationRegistryRef.model_validate(
                reference.model_dump(mode="python"), strict=True
            )
            raw = provider.load_registry(copied_reference)
            if type(raw) is not ValidationRegistryInput:
                raise WorkflowTransitionError("dynamic registry provider returned a foreign type")
            copied = _copy_registry(raw)
        except WorkflowTransitionError:
            raise
        except Exception as error:
            raise WorkflowTransitionError("dynamic registry readback failed") from error
        if (
            copied != raw
            or copied.run_id != context.run_id
            or copied.scope_id != context.scope_id
            or not _is_v2_family_configuration(copied.configuration_version)
            or any(
                type(item) is not PlannedStage2SemanticInputV2
                for item in copied.semantic_expectations
            )
            or sha256_digest(canonical_json(_primitive(copied)))
            != copied_reference.registry_content_hash
        ):
            raise WorkflowTransitionError("dynamic registry payload differs from the job")
        return copied

    def _build_validation_request(
        self,
        state: OrchestrationState,
        *,
        include_stored: bool,
    ) -> CanonicalReportRequest:
        scope = __class__._require_interpreted_scope(state)
        synthesis = __class__._require_synthesis(state)
        try:
            stored = project_stored_validation(state.validation) if include_stored else None
            return build_validation_request_projection(
                run_id=state.run_id,
                report_id=state.report_id,
                scope=scope,
                source_plan=state.source_plan,
                source_tasks=state.source_tasks,
                synthesis=synthesis,
                registry=__class__._registry_for(self, state, synthesis),
                stored_validation=stored,
            )
        except ValidationProjectionError as error:
            raise WorkflowTransitionError(str(error)) from error

    def _persist_stage1_receipt(self, receipt: Stage1ReceiptV2) -> Stage1ReceiptRef:
        store = self._stage1_receipt_store
        if store is None:
            raise WorkflowTransitionError("V2 Stage-1 receipt store is unavailable")
        try:
            payload = canonical_stage1_receipt_payload_v2(receipt)
            saved = stage1_receipt_from_payload_v2(dict(store.save_stage1_receipt(payload)))
            loaded_payload = store.load_stage1_receipt(receipt.receipt_id)
            if loaded_payload is None:
                raise WorkflowTransitionError("V2 Stage-1 receipt readback is unavailable")
            loaded = stage1_receipt_from_payload_v2(dict(loaded_payload))
        except WorkflowTransitionError:
            raise
        except Exception as error:
            raise WorkflowTransitionError("V2 Stage-1 receipt persistence failed") from error
        if saved != receipt or loaded != receipt:
            raise WorkflowTransitionError("V2 Stage-1 receipt persistence returned drift")
        return Stage1ReceiptRef(
            receipt_id=receipt.receipt_id, receipt_content_hash=receipt.receipt_content_hash
        )

    def _persist_validation_receipt(
        self,
        request: CanonicalReportRequest,
        audit: ReportValidationAudit,
    ) -> ValidationReceiptRef:
        receipt = audit.receipt
        if receipt is None:
            raise WorkflowTransitionError("completed validation did not produce a receipt")
        try:
            payload = canonical_validation_receipt_payload(receipt)
            saved_payload = self._validation_receipt_store.save_receipt(payload)
            saved = validation_receipt_from_payload(saved_payload)
            saved = verify_validation_receipt(saved, request=request, audit=audit)
            loaded_payload = self._validation_receipt_store.load_receipt(saved.receipt_id)
            if loaded_payload is None:
                raise WorkflowTransitionError("persisted validation receipt is unavailable")
            loaded = validation_receipt_from_payload(loaded_payload)
            loaded = verify_validation_receipt(loaded, request=request, audit=audit)
        except WorkflowTransitionError:
            raise
        except Exception as error:
            raise WorkflowTransitionError("validation receipt persistence failed") from error
        if saved != receipt or loaded != receipt:
            raise WorkflowTransitionError("validation receipt persistence returned drift")
        return ValidationReceiptRef(
            receipt_id=loaded.receipt_id,
            receipt_content_hash=loaded.receipt_content_hash,
        )

    def _verify_binding(
        self,
        state: OrchestrationState,
        *,
        require_pass: bool,
    ) -> None:
        request = __class__._build_validation_request(self, state, include_stored=True)
        if _is_v2_family_configuration(request.registry.configuration_version):
            receipt_ref = state.validation_receipt_ref
            if receipt_ref is None:
                raise WorkflowTransitionError("V2 validation receipt reference is missing")
            try:
                raw_receipt = self._validation_receipt_store.load_receipt(receipt_ref.receipt_id)
                if raw_receipt is None:
                    raise WorkflowTransitionError("V2 validation receipt is unavailable")
                parsed_receipt = validation_receipt_from_payload(raw_receipt)
                if type(parsed_receipt) is not ValidationReceiptV2 or (
                    parsed_receipt.receipt_id,
                    parsed_receipt.receipt_content_hash,
                ) != (receipt_ref.receipt_id, receipt_ref.receipt_content_hash):
                    raise WorkflowTransitionError("V2 validation receipt reference drift")
                projections = stage2_projections_from_receipt_v2(parsed_receipt)
                if projections:
                    request = replace(
                        request,
                        registry=replace(request.registry, semantic_expectations=projections),
                    )
                if (
                    projections
                    and any(
                        type(item) is PlannedStage2SemanticInputV2
                        for item in __class__._registry_for(
                            self, state, __class__._require_synthesis(state)
                        ).semantic_expectations
                    )
                    and state.stage1_receipt_ref is None
                ):
                    raise WorkflowTransitionError("V2 Stage-1 receipt reference is missing")
                if state.stage1_receipt_ref is not None:
                    planned_request = __class__._build_validation_request(
                        self, state, include_stored=False
                    )
                    preflight = canonical_validate_report(
                        planned_request, mode=ValidationMode.PREPARE_STAGE1
                    )
                    expected_stage1 = preflight.stage1_receipt
                    stage1_store = self._stage1_receipt_store
                    if expected_stage1 is None or stage1_store is None:
                        raise WorkflowTransitionError("V2 Stage-1 receipt authority is unavailable")
                    raw_stage1 = stage1_store.load_stage1_receipt(
                        state.stage1_receipt_ref.receipt_id
                    )
                    if raw_stage1 is None:
                        raise WorkflowTransitionError("V2 Stage-1 receipt is unavailable")
                    stored_stage1 = stage1_receipt_from_payload_v2(dict(raw_stage1))
                    if stored_stage1 != expected_stage1 or (
                        stored_stage1.receipt_id,
                        stored_stage1.receipt_content_hash,
                    ) != (
                        state.stage1_receipt_ref.receipt_id,
                        state.stage1_receipt_ref.receipt_content_hash,
                    ):
                        raise WorkflowTransitionError("V2 Stage-1 receipt binding drift")
            except WorkflowTransitionError:
                raise
            except Exception as error:
                raise WorkflowTransitionError("V2 saved authority reconstruction failed") from error
        try:
            audit = canonical_validate_report(request, mode=ValidationMode.VERIFY_BINDING)
        except Exception as error:
            raise WorkflowTransitionError("canonical report binding verification failed") from error
        expected = (
            state.validation.structural_citation_gate is GateStatus.PASSED,
            state.validation.semantic_support_gate is GateStatus.PASSED,
            state.validation.safety_policy_gate is GateStatus.PASSED,
            state.validation.reason_codes,
        )
        actual = (
            audit.summary.structural_passed,
            audit.summary.semantic_passed,
            audit.summary.safety_passed,
            audit.summary.reason_codes,
        )
        if (
            audit.receipt is not None
            or actual != expected
            or (require_pass and not audit.summary.passed)
        ):
            raise WorkflowTransitionError("canonical report binding verification failed")
        if state.pending_draft is not None:
            __class__._verify_pending_draft(self, state.pending_draft)
        receipt_ref = state.validation_receipt_ref
        if receipt_ref is None:
            raise WorkflowTransitionError("canonical report binding requires a receipt")
        try:
            loaded_payload = self._validation_receipt_store.load_receipt(receipt_ref.receipt_id)
        except Exception as error:
            raise WorkflowTransitionError("canonical report receipt load failed") from error
        if loaded_payload is None:
            raise WorkflowTransitionError("canonical report receipt is unavailable")
        try:
            loaded = validation_receipt_from_payload(loaded_payload)
        except Exception as error:
            raise WorkflowTransitionError("report receipt reconstruction failed") from error
        if (
            loaded.receipt_id != receipt_ref.receipt_id
            or loaded.receipt_content_hash != receipt_ref.receipt_content_hash
        ):
            raise WorkflowTransitionError("canonical report receipt reference drift")
        try:
            receipt = verify_validation_receipt(loaded, request=request, audit=audit)
        except Exception as error:
            raise WorkflowTransitionError("canonical report receipt binding failed") from error
        if (
            receipt.structural_passed,
            receipt.semantic_passed,
            receipt.safety_passed,
            receipt.reason_codes,
        ) != actual:
            raise WorkflowTransitionError("canonical report binding verification failed")

    def _verify_pending_draft(self, expected: PendingDraftRef) -> None:
        try:
            raw = self._draft_persistence.load_pending(expected.persistence_id)
        except Exception as error:
            raise WorkflowTransitionError("pending draft load failed") from error
        if raw is None:
            raise WorkflowTransitionError("pending draft is unavailable")
        loaded = __class__._reconstruct_pending_draft(raw)
        if loaded != expected:
            raise WorkflowTransitionError("pending draft durable binding drift")

    @staticmethod
    def _reconstruct_pending_draft(raw: PendingDraftRef) -> PendingDraftRef:
        if type(raw) is not PendingDraftRef:
            raise WorkflowTransitionError("pending draft reconstruction failed")
        return PendingDraftRef.model_validate(PendingDraftRef.model_dump(raw, mode="python"))

    @staticmethod
    def _validate_application_state(state: OrchestrationState) -> None:
        status_checkpoint = {
            ReportStatus.PENDING_REVIEW: (
                WorkflowDisposition.ACTIVE,
                WorkflowNode.REQUEST_EXPORT_APPROVAL,
                WORKFLOW_TOPOLOGY[:6],
            ),
            ReportStatus.APPROVED: (
                WorkflowDisposition.ACTIVE,
                WorkflowNode.FINALIZE_AND_EXPORT,
                WORKFLOW_TOPOLOGY[:7],
            ),
            ReportStatus.REJECTED: (
                WorkflowDisposition.REJECTED,
                None,
                WORKFLOW_TOPOLOGY[:7],
            ),
            ReportStatus.EXPORTED: (
                WorkflowDisposition.EXPORTED,
                None,
                WORKFLOW_TOPOLOGY,
            ),
        }.get(state.report_status)
        if (
            status_checkpoint is not None
            and (
                state.disposition,
                state.current_node,
                state.completed_nodes,
            )
            != status_checkpoint
        ):
            raise WorkflowTransitionError("report status does not bind the exact topology")
        expected_effect_status = None
        if state.current_node is not None:
            expected_effect_status = {
                WorkflowNode.SAVE_PENDING_DRAFT: ReportStatus.DRAFT,
                WorkflowNode.REQUEST_EXPORT_APPROVAL: ReportStatus.PENDING_REVIEW,
                WorkflowNode.FINALIZE_AND_EXPORT: ReportStatus.APPROVED,
            }.get(state.current_node)
        if expected_effect_status is not None and state.report_status is not expected_effect_status:
            raise WorkflowTransitionError("effect node does not bind the exact report status")
        if state.source_plan:
            selected = tuple(
                item.source
                for item in state.source_plan
                if item.planning_status is PlanningStatus.SELECTED
            )
            task_sources = tuple(item.source for item in state.source_tasks)
            if selected != task_sources or len(set(task_sources)) != len(task_sources):
                raise WorkflowTransitionError("selected plan sources must equal source tasks")
        post_collection = WorkflowNode.COLLECT_EVIDENCE in state.completed_nodes or (
            state.current_node is not None
            and WORKFLOW_TOPOLOGY.index(state.current_node)
            > WORKFLOW_TOPOLOGY.index(WorkflowNode.COLLECT_EVIDENCE)
        )
        if post_collection and any(
            task.status is not SourceTaskStatus.TERMINAL or task.terminal_outcome_ref is None
            for task in state.source_tasks
        ):
            raise WorkflowTransitionError("post-collection tasks must all be terminal")
        evidence_ids: set[str] = set()
        evidence_authorities: set[tuple[object, ...]] = set()
        for task in state.source_tasks:
            if task.task_id != source_task_id(state.run_id, task.source):
                raise WorkflowTransitionError("source task does not bind run and source")
            terminal = task.terminal_outcome_ref
            if terminal is None:
                continue
            acquisition = terminal.acquisition
            outcome = terminal.outcome
            try:
                validate_terminal_operation_binding(terminal, task.operation_results)
            except ValueError as error:
                raise WorkflowTransitionError("terminal child acquisitions are invalid") from error
            if (
                acquisition.run_id != state.run_id
                or acquisition.source is not task.source
                or outcome.source is not task.source
            ):
                raise WorkflowTransitionError("terminal task lineage does not bind current run")
            for evidence in task.evidence_refs:
                authority = (
                    evidence.source,
                    evidence.snapshot_id,
                    evidence.content_hash,
                    evidence.locator_ref,
                )
                if (
                    evidence.evidence_id in evidence_ids
                    or authority in evidence_authorities
                    or evidence.source is not task.source
                    or sum(
                        observation.evidence_reference == evidence
                        for result in task.operation_results
                        for observation in result.observations
                    )
                    != 1
                ):
                    raise WorkflowTransitionError("cross-task evidence authority is invalid")
                evidence_ids.add(evidence.evidence_id)
                evidence_authorities.add(authority)
        if state.report_status in {
            ReportStatus.PENDING_REVIEW,
            ReportStatus.APPROVED,
            ReportStatus.REJECTED,
            ReportStatus.EXPORTED,
        } and (
            state.pending_draft is None
            or state.synthesis is None
            or state.pending_draft.persistence_id
            != __class__._pending_draft_persistence_id(
                state.report_id,
                state.synthesis.report_content_hash,
            )
            or state.pending_draft.report_id != state.report_id
            or state.pending_draft.report_content_hash != state.synthesis.report_content_hash
        ):
            raise WorkflowTransitionError("reviewed report requires its bound pending draft")
        if state.active_approval is not None:
            synthesis = state.synthesis
            expected_outcomes = tuple(task.terminal_outcome_ref for task in state.source_tasks)
            if (
                synthesis is None
                or state.active_approval.report_id != state.report_id
                or state.active_approval.report_content_hash != synthesis.report_content_hash
                or state.pending_draft is None
                or state.active_approval.pending_draft_persistence_id
                != state.pending_draft.persistence_id
                or state.active_approval.destination != state.destination
                or state.active_approval.source_outcome_refs != expected_outcomes
                or state.active_approval.warning_codes != synthesis.warning_codes
            ):
                raise WorkflowTransitionError("approval does not bind current report")
        if state.export_record is not None:
            synthesis = state.synthesis
            approval = state.active_approval
            expected_key = export_idempotency_key(
                state.report_id,
                "" if synthesis is None else synthesis.report_content_hash,
                state.destination,
            )
            if (
                synthesis is None
                or approval is None
                or state.export_record.report_id != state.report_id
                or state.export_record.report_content_hash != synthesis.report_content_hash
                or state.export_record.destination != state.destination
                or state.export_record.approval_review_id != approval.review_id
                or state.export_record.idempotency_key != expected_key
            ):
                raise WorkflowTransitionError("export does not bind current approval")
        if state.disposition is WorkflowDisposition.VALIDATION_BLOCKED and (
            state.synthesis is None
            or state.validation.passed
            or state.report_status is not ReportStatus.DRAFT
            or state.pending_draft is not None
            or state.review_history
            or state.active_approval is not None
            or state.export_record is not None
        ):
            raise WorkflowTransitionError("validation-blocked fields are inconsistent")
        if state.disposition is WorkflowDisposition.REJECTED and (
            state.synthesis is None
            or not state.validation.passed
            or state.pending_draft is None
            or not state.review_history
            or state.review_history[-1].decision is not ReviewDecision.REJECT
            or state.active_approval is not None
            or state.export_record is not None
        ):
            raise WorkflowTransitionError("rejected fields are inconsistent")
        if state.disposition is WorkflowDisposition.REJECTED:
            assert state.synthesis is not None
            review = state.review_history[-1]
            expected_outcomes = tuple(task.terminal_outcome_ref for task in state.source_tasks)
            if (
                review.report_id != state.report_id
                or review.report_content_hash != state.synthesis.report_content_hash
                or state.pending_draft is None
                or review.pending_draft_persistence_id != state.pending_draft.persistence_id
                or review.destination != state.destination
                or review.source_outcome_refs != expected_outcomes
                or review.warning_codes != state.synthesis.warning_codes
            ):
                raise WorkflowTransitionError("rejected decision does not bind current report")

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

    def _replay_terminal_tasks(self, state: OrchestrationState) -> None:
        try:
            replay_terminal_tasks(self._evidence_collection, state)
        except Exception as error:
            raise WorkflowTransitionError("source terminal replay failed") from error

    def _replay_source_plan(self, state: OrchestrationState) -> None:
        try:
            replay_source_plan(self._source_planning, state)
        except Exception as error:
            raise WorkflowTransitionError("source plan replay failed") from error

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

    @staticmethod
    def _pending_draft_persistence_id(report_id: str, report_content_hash: str) -> str:
        return pending_draft_identity(report_id, report_content_hash)

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
        return __class__._replace(
            state,
            checkpoint_id=__class__._next_checkpoint_id(state, node),
            completed_nodes=(*state.completed_nodes, node),
            current_node=next_node,
            **changes,
        )

    @staticmethod
    def _replace(state: OrchestrationState, **changes: Any) -> OrchestrationState:
        payload = state.model_dump(mode="python")
        payload.update(changes)
        return OrchestrationState.model_validate(payload)

    def _validate_durable_state(self, state: OrchestrationState) -> OrchestrationState:
        try:
            if type(state) is not OrchestrationState:
                raise WorkflowTransitionError("durable checkpoint must use the exact state type")
            rebuilt = OrchestrationState.model_validate(
                OrchestrationState.model_dump(state, mode="python")
            )
            context = self._runtime_context
            if context is not None and (
                (rebuilt.run_id, rebuilt.report_id, rebuilt.original_scope.scope_id)
                != (context.run_id, context.report_id, context.scope_id)
                or (
                    rebuilt.interpreted_scope is not None
                    and rebuilt.interpreted_scope.scope_id != context.scope_id
                )
            ):
                raise WorkflowTransitionError("runtime context differs from checkpoint")
            if rebuilt.synthesis is not None:
                __class__._registry_for(self, rebuilt, rebuilt.synthesis)
            __class__._validate_application_state(rebuilt)
            return rebuilt
        except (ValidationError, WorkflowTransitionError) as error:
            raise WorkflowTransitionError(
                "formal export requires a valid durable checkpoint"
            ) from error

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
