"""Framework-neutral contracts for the bounded V1 orchestration workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    AcquisitionOutcomeRef,
    CitationId,
    ClaimId,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ReportId,
    ResearchScope,
    RunId,
    Sha256Digest,
    SourceOutcome,
    SourceType,
    UtcDateTime,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.identifiers import DurableModel, derive_identity

type StableWorkflowId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]
type PolicyReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,127}$"),
]
type ValidationReceiptId = Annotated[
    str,
    StringConstraints(pattern=r"^validation-receipt:sha256:[0-9a-f]{64}$"),
]


class WorkflowNode(StrEnum):
    """The eight Owner-frozen V1 workflow nodes."""

    SCOPE_AND_SAFETY = "scope_and_safety"
    PLAN_SOURCES = "plan_sources"
    COLLECT_EVIDENCE = "collect_evidence"
    SYNTHESIZE_CLAIMS = "synthesize_claims"
    VALIDATE_REPORT = "validate_report"
    SAVE_PENDING_DRAFT = "save_pending_draft"
    REQUEST_EXPORT_APPROVAL = "request_export_approval"
    FINALIZE_AND_EXPORT = "finalize_and_export"


WORKFLOW_TOPOLOGY: tuple[WorkflowNode, ...] = (
    WorkflowNode.SCOPE_AND_SAFETY,
    WorkflowNode.PLAN_SOURCES,
    WorkflowNode.COLLECT_EVIDENCE,
    WorkflowNode.SYNTHESIZE_CLAIMS,
    WorkflowNode.VALIDATE_REPORT,
    WorkflowNode.SAVE_PENDING_DRAFT,
    WorkflowNode.REQUEST_EXPORT_APPROVAL,
    WorkflowNode.FINALIZE_AND_EXPORT,
)
MAX_SOURCE_TASK_ATTEMPTS = 8


class SafetyOutcome(StrEnum):
    """Internal policy result; it deliberately contains no user-facing wording."""

    PERMITTED = "permitted"
    BLOCKED = "blocked"


class SafetyReason(StrEnum):
    """Closed M3-001 policy reasons pending later wording decisions."""

    PERMITTED_RESEARCH_SCOPE = "permitted_research_scope"
    UNSAFE_SCOPE = "unsafe_scope"
    SUSPECTED_PHI = "suspected_phi"
    UNRESOLVED_MEDICAL_BOUNDARY = "unresolved_medical_boundary"


class SafetyDecision(DurableModel):
    """Typed safety result produced before planning or evidence collection."""

    schema_version: Literal["m3.safety-decision.v1"] = "m3.safety-decision.v1"
    outcome: SafetyOutcome
    reason: SafetyReason
    policy_version: StableWorkflowId

    @model_validator(mode="after")
    def validate_outcome_reason(self) -> Self:
        if self.outcome is SafetyOutcome.PERMITTED:
            if self.reason is not SafetyReason.PERMITTED_RESEARCH_SCOPE:
                raise ValueError("permitted safety outcome requires its permitted reason")
        elif self.reason is SafetyReason.PERMITTED_RESEARCH_SCOPE:
            raise ValueError("blocked safety outcome requires a blocking reason")
        return self


class ScopeSafetyEvaluation(DurableModel):
    """Interpreted scope and internal policy decision from the first node."""

    schema_version: Literal["m3.scope-safety-evaluation.v1"] = "m3.scope-safety-evaluation.v1"
    interpreted_scope: ResearchScope
    decision: SafetyDecision


class WorkflowPermissions(DurableModel):
    """Static permissions that evidence and model output cannot expand."""

    schema_version: Literal["m3.workflow-permissions.v1"] = "m3.workflow-permissions.v1"
    allowed_nodes: tuple[WorkflowNode, ...] = WORKFLOW_TOPOLOGY
    export_requires_approval: Literal[True] = True
    retrieved_content_can_change_permissions: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_topology(self) -> Self:
        if self.allowed_nodes != WORKFLOW_TOPOLOGY:
            raise ValueError("workflow permissions must equal the frozen topology")
        return self


class SourceTaskStatus(StrEnum):
    """Internal execution state; terminal source semantics remain in SourceOutcome."""

    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    TERMINAL = "terminal"
    FAILED = "failed"


class SourceTaskAttemptRef(DurableModel):
    """Stable logical attempt and idempotency identity checkpointed before I/O."""

    schema_version: Literal["m3.source-task-attempt-ref.v1"] = "m3.source-task-attempt-ref.v1"
    attempt_id: StableWorkflowId
    task_id: StableWorkflowId
    attempt_number: int = Field(ge=1, le=MAX_SOURCE_TASK_ATTEMPTS)
    idempotency_key: Sha256Digest

    @model_validator(mode="after")
    def validate_attempt_identity(self) -> Self:
        identity_payload = {
            "task_id": self.task_id,
            "attempt_number": self.attempt_number,
        }
        if self.attempt_id != derive_identity("source-task-attempt", identity_payload):
            raise ValueError("source task attempt identity does not match its content")
        if self.idempotency_key != sha256_digest(canonical_json(identity_payload)):
            raise ValueError("source task attempt idempotency key does not match its content")
        return self


class CollectionFailureClassification(StrEnum):
    """Closed workflow-level classification supplied by the collection port."""

    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class SourceTaskFailureRef(DurableModel):
    """Typed collection failure with no fabricated source outcome or evidence."""

    schema_version: Literal["m3.source-task-failure-ref.v1"] = "m3.source-task-failure-ref.v1"
    failure_id: StableWorkflowId
    attempt: SourceTaskAttemptRef
    classification: CollectionFailureClassification
    reason_code: PolicyReasonCode


class TerminalSourceOutcomeRef(DurableModel):
    """Validated reference and small terminal outcome, never a source payload."""

    schema_version: Literal["m3.source-outcome-ref.v1"] = "m3.source-outcome-ref.v1"
    acquisition: AcquisitionOutcomeRef
    outcome: SourceOutcome

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.acquisition.source is not self.outcome.source
            or self.acquisition.query_id != self.outcome.query_id
        ):
            raise ValueError("source outcome reference does not bind its terminal outcome")
        return self


class EvidenceReference(DurableModel):
    """Immutable source evidence identity without copied source content."""

    schema_version: Literal["m3.evidence-ref.v1"] = "m3.evidence-ref.v1"
    evidence_id: StableWorkflowId
    source: SourceType
    snapshot_id: StableWorkflowId
    content_hash: Sha256Digest
    locator_ref: StableWorkflowId


class ClaimReference(DurableModel):
    """Reference to one material claim proposed for the current report."""

    schema_version: Literal["m3.claim-ref.v1"] = "m3.claim-ref.v1"
    claim_id: ClaimId


class CitationReference(DurableModel):
    """Reference to one citation proposed for the current report."""

    schema_version: Literal["m3.citation-ref.v1"] = "m3.citation-ref.v1"
    citation_id: CitationId
    claim_id: ClaimId
    evidence_id: StableWorkflowId


class ComparabilityReference(DurableModel):
    """Reference to an externally evaluated comparability record."""

    schema_version: Literal["m3.comparability-ref.v1"] = "m3.comparability-ref.v1"
    comparability_id: StableWorkflowId
    artifact_hash: Sha256Digest


class ConflictReference(DurableModel):
    """Reference to an externally evaluated conflict record."""

    schema_version: Literal["m3.conflict-ref.v1"] = "m3.conflict-ref.v1"
    conflict_id: StableWorkflowId
    artifact_hash: Sha256Digest


class SourceTaskState(DurableModel):
    """One selected source task and its terminal reference when executed."""

    schema_version: Literal["m3.source-task.v1"] = "m3.source-task.v1"
    task_id: StableWorkflowId
    source: SourceType
    status: SourceTaskStatus = SourceTaskStatus.PENDING
    attempts: int = Field(default=0, ge=0, le=MAX_SOURCE_TASK_ATTEMPTS)
    active_attempt: SourceTaskAttemptRef | None = None
    failure_history: tuple[SourceTaskFailureRef, ...] = Field(
        default=(),
        max_length=MAX_SOURCE_TASK_ATTEMPTS,
    )
    terminal_outcome_ref: TerminalSourceOutcomeRef | None = None
    evidence_refs: tuple[EvidenceReference, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_task_state(self) -> Self:
        terminal = self.status is SourceTaskStatus.TERMINAL
        failed = self.status is SourceTaskStatus.FAILED
        if terminal != (self.terminal_outcome_ref is not None):
            raise ValueError("terminal task status and outcome reference must coexist")
        if self.status is SourceTaskStatus.PENDING and self.attempts != 0:
            raise ValueError("pending source task must have zero attempts")
        if self.status is SourceTaskStatus.PENDING and (
            self.active_attempt is not None or self.failure_history
        ):
            raise ValueError("pending source task cannot contain attempt state")
        if self.status is SourceTaskStatus.RUNNING:
            if self.active_attempt is None:
                raise ValueError("running source task requires its active attempt")
            if (
                self.attempts != self.active_attempt.attempt_number
                or self.task_id != self.active_attempt.task_id
            ):
                raise ValueError("running source task must bind its numbered attempt")
        elif self.active_attempt is not None:
            raise ValueError("only a running source task may retain an active attempt")
        if self.status is SourceTaskStatus.RETRY_WAIT:
            if not self.failure_history or self.attempts < 1:
                raise ValueError("retry-wait task requires a checkpointed failure")
            if self.failure_history[-1].classification is not (
                CollectionFailureClassification.RETRYABLE
            ):
                raise ValueError("retry-wait task requires a retryable last failure")
            if self.attempts >= MAX_SOURCE_TASK_ATTEMPTS:
                raise ValueError("retry-wait task requires remaining attempt capacity")
        if failed and (not self.failure_history or self.attempts < 1):
            raise ValueError("failed source task requires a checkpointed failure")
        if terminal and self.attempts < 1:
            raise ValueError("terminal source task requires an attempt")
        if not terminal and self.evidence_refs:
            raise ValueError("unexecuted source task cannot expose evidence")
        failure_attempts = tuple(item.attempt.attempt_number for item in self.failure_history)
        if failure_attempts != tuple(sorted(set(failure_attempts))):
            raise ValueError("source task failures must have unique ordered attempts")
        if any(item.attempt.task_id != self.task_id for item in self.failure_history):
            raise ValueError("source task failures must bind the task identity")
        if failure_attempts and failure_attempts[-1] > self.attempts:
            raise ValueError("source task failure cannot exceed checkpointed attempts")
        if (self.status is SourceTaskStatus.RETRY_WAIT or failed) and (
            failure_attempts[-1] != self.attempts
        ):
            raise ValueError("failed attempt must equal the checkpointed attempt count")
        if self.status in {
            SourceTaskStatus.RUNNING,
            SourceTaskStatus.RETRY_WAIT,
            SourceTaskStatus.TERMINAL,
        } and any(
            item.classification is CollectionFailureClassification.PERMANENT
            for item in self.failure_history
        ):
            raise ValueError("permanent collection failure must terminate the source task")
        if (
            failed
            and self.failure_history[-1].classification is CollectionFailureClassification.RETRYABLE
            and self.attempts < MAX_SOURCE_TASK_ATTEMPTS
        ):
            raise ValueError("retryable collection failure requires attempt exhaustion")
        if self.terminal_outcome_ref is not None:
            if self.terminal_outcome_ref.outcome.source is not self.source:
                raise ValueError("source task and terminal outcome source must match")
            if self.terminal_outcome_ref.acquisition.source is not self.source:
                raise ValueError("source task and acquisition source must match")
        if any(item.source is not self.source for item in self.evidence_refs):
            raise ValueError("source task evidence must belong to the same source")
        if len({item.evidence_id for item in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError("source task evidence references must be unique")
        return self


class CollectedEvidenceResult(DurableModel):
    """One bounded collection result with no source payload bytes."""

    schema_version: Literal["m3.collected-evidence.v1"] = "m3.collected-evidence.v1"
    attempt: SourceTaskAttemptRef
    terminal_outcome_ref: TerminalSourceOutcomeRef
    evidence_refs: tuple[EvidenceReference, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        source = self.terminal_outcome_ref.outcome.source
        if any(item.source is not source for item in self.evidence_refs):
            raise ValueError("collected evidence must match the terminal outcome source")
        return self


class SynthesisState(DurableModel):
    """Small synthesis result containing identities rather than report content."""

    schema_version: Literal["m3.synthesis-state.v1"] = "m3.synthesis-state.v1"
    report_content_hash: Sha256Digest
    claims: tuple[ClaimReference, ...] = Field(max_length=200)
    citations: tuple[CitationReference, ...] = Field(max_length=400)
    comparability_refs: tuple[ComparabilityReference, ...] = Field(max_length=100)
    conflict_refs: tuple[ConflictReference, ...] = Field(max_length=100)
    warning_codes: tuple[PolicyReasonCode, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_reference_graph(self) -> Self:
        claim_ids = tuple(item.claim_id for item in self.claims)
        citation_ids = tuple(item.citation_id for item in self.citations)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim references must be unique")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("citation references must be unique")
        if any(item.claim_id not in set(claim_ids) for item in self.citations):
            raise ValueError("citation reference must bind a current claim")
        if len(set(self.warning_codes)) != len(self.warning_codes):
            raise ValueError("warning codes must be unique")
        if self.warning_codes != tuple(sorted(self.warning_codes)):
            raise ValueError("warning codes must be canonically sorted")
        return self


class GateStatus(StrEnum):
    """State of a deterministic or injected report gate."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


class ReportValidationState(DurableModel):
    """Report validation outcome; M3-001 does not implement gate algorithms."""

    schema_version: Literal["m3.report-validation.v1"] = "m3.report-validation.v1"
    structural_citation_gate: GateStatus = GateStatus.NOT_RUN
    semantic_support_gate: GateStatus = GateStatus.NOT_RUN
    safety_policy_gate: GateStatus = GateStatus.NOT_RUN
    reason_codes: tuple[PolicyReasonCode, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether all three independently supplied gates passed."""

        return (
            self.structural_citation_gate is GateStatus.PASSED
            and self.semantic_support_gate is GateStatus.PASSED
            and self.safety_policy_gate is GateStatus.PASSED
        )

    @model_validator(mode="after")
    def validate_gate_summary(self) -> Self:
        statuses = (
            self.structural_citation_gate,
            self.semantic_support_gate,
            self.safety_policy_gate,
        )
        if GateStatus.FAILED in statuses and not self.reason_codes:
            raise ValueError("failed report validation requires a reason code")
        if self.passed and self.reason_codes:
            raise ValueError("passed report validation forbids failure reasons")
        if GateStatus.NOT_RUN in statuses and GateStatus.FAILED in statuses:
            raise ValueError("a terminal failed validation cannot retain not-run gates")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("validation reason codes must be unique")
        return self


class ValidationReceiptRef(DurableModel):
    """Checkpoint reference to independently persisted validation authority."""

    schema_version: Literal["m3.validation-receipt-ref.v1"] = "m3.validation-receipt-ref.v1"
    receipt_id: ValidationReceiptId
    receipt_content_hash: Sha256Digest


class ReportStatus(StrEnum):
    """The governed report review/export states."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class ReviewDecision(StrEnum):
    """The only three export-review decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ExportDestinationRef(DurableModel):
    """Abstract export target; no format, path, or provider is selected in M3-001."""

    schema_version: Literal["m3.export-destination-ref.v1"] = "m3.export-destination-ref.v1"
    destination_id: StableWorkflowId
    capability: Literal["abstract_export"] = "abstract_export"


class PendingDraftRef(DurableModel):
    """Idempotent persistence reference for one pending report hash."""

    schema_version: Literal["m3.pending-draft-ref.v1"] = "m3.pending-draft-ref.v1"
    persistence_id: StableWorkflowId
    report_id: ReportId
    report_content_hash: Sha256Digest


class ReviewRecord(DurableModel):
    """Auditable export decision bound to exact report bytes and destination."""

    schema_version: Literal["m3.review-record.v2"] = "m3.review-record.v2"
    review_id: StableWorkflowId
    report_id: ReportId
    report_content_hash: Sha256Digest
    pending_draft_persistence_id: StableWorkflowId
    destination: ExportDestinationRef
    source_outcome_refs: tuple[TerminalSourceOutcomeRef, ...] = Field(max_length=4)
    warning_codes: tuple[PolicyReasonCode, ...] = Field(max_length=100)
    decision: ReviewDecision
    reviewer_id: StableWorkflowId
    decided_at_utc: UtcDateTime

    @model_validator(mode="after")
    def validate_review_bindings(self) -> Self:
        sources = tuple(item.outcome.source for item in self.source_outcome_refs)
        if len(set(sources)) != len(sources):
            raise ValueError("review source outcome references must be unique by source")
        if len(set(self.warning_codes)) != len(self.warning_codes):
            raise ValueError("review warning codes must be unique")
        if self.warning_codes != tuple(sorted(self.warning_codes)):
            raise ValueError("review warning codes must be canonically sorted")
        return self


class ExportRecord(DurableModel):
    """Reference to an idempotently completed abstract export."""

    schema_version: Literal["m3.export-record.v1"] = "m3.export-record.v1"
    export_id: StableWorkflowId
    report_id: ReportId
    report_content_hash: Sha256Digest
    destination: ExportDestinationRef
    idempotency_key: Sha256Digest
    approval_review_id: StableWorkflowId
    exported_at_utc: UtcDateTime


class WorkflowDisposition(StrEnum):
    """Terminal or active workflow disposition, separate from report status."""

    ACTIVE = "active"
    POLICY_BLOCKED = "policy_blocked"
    COLLECTION_BLOCKED = "collection_blocked"
    VALIDATION_BLOCKED = "validation_blocked"
    REJECTED = "rejected"
    EXPORTED = "exported"


class OrchestrationState(DurableModel):
    """Versioned, framework-neutral checkpoint state for the bounded workflow."""

    schema_version: Literal["m3.orchestration-state.v2"] = "m3.orchestration-state.v2"
    workflow_id: StableWorkflowId
    checkpoint_id: StableWorkflowId
    run_id: RunId
    report_id: ReportId
    original_scope: ResearchScope
    interpreted_scope: ResearchScope | None = None
    safety_decision: SafetyDecision | None = None
    permissions: WorkflowPermissions = Field(default_factory=WorkflowPermissions)
    source_plan: tuple[M1BSourcePlanEntryV1, ...] = ()
    source_tasks: tuple[SourceTaskState, ...] = ()
    synthesis: SynthesisState | None = None
    validation: ReportValidationState = Field(default_factory=ReportValidationState)
    validation_receipt_ref: ValidationReceiptRef | None = None
    report_status: ReportStatus = ReportStatus.DRAFT
    destination: ExportDestinationRef
    pending_draft: PendingDraftRef | None = None
    review_history: tuple[ReviewRecord, ...] = ()
    active_approval: ReviewRecord | None = None
    export_record: ExportRecord | None = None
    edit_base_content_hash: Sha256Digest | None = None
    completed_nodes: tuple[WorkflowNode, ...] = ()
    current_node: WorkflowNode | None = WorkflowNode.SCOPE_AND_SAFETY
    disposition: WorkflowDisposition = WorkflowDisposition.ACTIVE

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if len(set(self.completed_nodes)) != len(self.completed_nodes):
            raise ValueError("completed workflow nodes must be unique")
        if any(node not in WORKFLOW_TOPOLOGY for node in self.completed_nodes):
            raise ValueError("completed workflow node is outside the frozen topology")
        if self.current_node in self.completed_nodes:
            raise ValueError("current workflow node cannot already be complete")
        if self.disposition is WorkflowDisposition.ACTIVE and self.current_node is None:
            raise ValueError("active workflow requires a current node")
        if self.current_node is not None:
            expected_completed = WORKFLOW_TOPOLOGY[: WORKFLOW_TOPOLOGY.index(self.current_node)]
            if self.completed_nodes != expected_completed:
                raise ValueError("completed nodes must be the exact topology prefix")
        else:
            expected_terminal = {
                WorkflowDisposition.POLICY_BLOCKED: WORKFLOW_TOPOLOGY[:1],
                WorkflowDisposition.COLLECTION_BLOCKED: WORKFLOW_TOPOLOGY[:2],
                WorkflowDisposition.VALIDATION_BLOCKED: WORKFLOW_TOPOLOGY[:5],
                WorkflowDisposition.REJECTED: WORKFLOW_TOPOLOGY[:7],
                WorkflowDisposition.EXPORTED: WORKFLOW_TOPOLOGY,
            }.get(self.disposition)
            if expected_terminal is not None and self.completed_nodes != expected_terminal:
                raise ValueError("terminal completed nodes do not match the disposition")
        if self.interpreted_scope is not None and (
            self.interpreted_scope.selected_sources != self.original_scope.selected_sources
        ):
            raise ValueError("interpreted scope cannot change source permissions")

        if self.source_plan:
            plan_sources = tuple(item.source for item in self.source_plan)
            if len(set(plan_sources)) != len(plan_sources):
                raise ValueError("source plan must contain one row per source")
            if plan_sources != tuple(sorted(plan_sources, key=lambda item: item.value)):
                raise ValueError("source plan must be canonically sorted")
            scope = self.interpreted_scope or self.original_scope
            if set(plan_sources) != set(scope.selected_sources):
                raise ValueError("source plan must exactly cover the interpreted scope")
            selected = {
                item.source
                for item in self.source_plan
                if item.planning_status is PlanningStatus.SELECTED
            }
            task_sources = tuple(item.source for item in self.source_tasks)
            if len(set(task_sources)) != len(task_sources):
                raise ValueError("selected source tasks must be unique")
            if task_sources != tuple(sorted(task_sources, key=lambda item: item.value)):
                raise ValueError("source tasks must be canonically sorted")
            if set(task_sources) != selected:
                raise ValueError("only selected sources may have execution tasks")
            for task in self.source_tasks:
                if task.task_id != source_task_id(self.run_id, task.source):
                    raise ValueError("source task identity must bind run and source")
                if (
                    task.terminal_outcome_ref is not None
                    and task.terminal_outcome_ref.acquisition.run_id != self.run_id
                ):
                    raise ValueError("source task outcome reference must bind the run")
        elif self.source_tasks:
            raise ValueError("source tasks require a source plan")
        elif WorkflowNode.PLAN_SOURCES in self.completed_nodes:
            raise ValueError("completed planning requires a bounded source plan")

        collection_completed = WorkflowNode.COLLECT_EVIDENCE in self.completed_nodes
        current_beyond_collection = self.current_node is not None and WORKFLOW_TOPOLOGY.index(
            self.current_node
        ) > WORKFLOW_TOPOLOGY.index(WorkflowNode.COLLECT_EVIDENCE)
        if (collection_completed or current_beyond_collection) and any(
            task.status is not SourceTaskStatus.TERMINAL or task.terminal_outcome_ref is None
            for task in self.source_tasks
        ):
            raise ValueError(
                "completed collection requires every selected source task "
                "to have a terminal SourceOutcome reference"
            )

        validation_completed = WorkflowNode.VALIDATE_REPORT in self.completed_nodes
        validation_gates = (
            self.validation.structural_citation_gate,
            self.validation.semantic_support_gate,
            self.validation.safety_policy_gate,
        )
        if validation_completed and (
            self.synthesis is None
            or self.validation_receipt_ref is None
            or GateStatus.NOT_RUN in validation_gates
        ):
            raise ValueError("completed validation requires its persisted receipt reference")
        if not validation_completed and (
            self.validation_receipt_ref is not None
            or any(item is not GateStatus.NOT_RUN for item in validation_gates)
        ):
            raise ValueError("validation result and receipt require a completed assessment")

        if self.pending_draft is not None:
            if self.synthesis is None or not self.validation.passed:
                raise ValueError("pending draft requires a validated synthesis")
            if (
                self.pending_draft.report_id != self.report_id
                or self.pending_draft.report_content_hash != self.synthesis.report_content_hash
            ):
                raise ValueError("pending draft must bind the current report hash")
        if self.report_status is ReportStatus.PENDING_REVIEW and (
            self.pending_draft is None or not self.validation.passed
        ):
            raise ValueError("pending review requires a validated persisted draft")

        if self.active_approval is not None:
            if self.active_approval.decision is not ReviewDecision.APPROVE:
                raise ValueError("active approval must be an approve decision")
            if self.synthesis is None:
                raise ValueError("approval requires a synthesized report")
            if (
                self.active_approval.report_id != self.report_id
                or self.active_approval.report_content_hash != self.synthesis.report_content_hash
                or self.pending_draft is None
                or self.active_approval.pending_draft_persistence_id
                != self.pending_draft.persistence_id
                or self.active_approval.destination != self.destination
            ):
                raise ValueError("approval must bind the current report and destination")
            if not self.validation.passed:
                raise ValueError("approval requires passing validation")
            if self.active_approval not in self.review_history:
                raise ValueError("active approval must be retained in review history")
            expected_outcomes = tuple(
                task.terminal_outcome_ref
                for task in self.source_tasks
                if task.terminal_outcome_ref is not None
            )
            if (
                self.active_approval.source_outcome_refs != expected_outcomes
                or self.active_approval.warning_codes != self.synthesis.warning_codes
            ):
                raise ValueError("approval must bind current coverage and warnings")
        if self.report_status is ReportStatus.APPROVED and self.active_approval is None:
            raise ValueError("approved report requires its active approval")
        if self.active_approval is not None and self.report_status not in {
            ReportStatus.APPROVED,
            ReportStatus.EXPORTED,
        }:
            raise ValueError("active approval requires approved or exported report status")

        if self.export_record is not None:
            if self.active_approval is None or self.synthesis is None:
                raise ValueError("export requires the active approved report")
            if (
                self.export_record.report_id != self.report_id
                or self.export_record.report_content_hash != self.synthesis.report_content_hash
                or self.export_record.destination != self.destination
                or self.export_record.approval_review_id != self.active_approval.review_id
            ):
                raise ValueError("export must bind the current approved report")
            if self.report_status is not ReportStatus.EXPORTED:
                raise ValueError("export record requires exported report status")
        if self.report_status is ReportStatus.EXPORTED and (
            self.export_record is None or self.disposition is not WorkflowDisposition.EXPORTED
        ):
            raise ValueError("exported report requires a terminal export record")
        if self.disposition is WorkflowDisposition.EXPORTED and self.current_node is not None:
            raise ValueError("exported workflow cannot retain a current node")
        if self.disposition is not WorkflowDisposition.ACTIVE and self.current_node is not None:
            raise ValueError("terminal workflow disposition cannot retain a current node")
        if (self.report_status is ReportStatus.REJECTED) != (
            self.disposition is WorkflowDisposition.REJECTED
        ):
            raise ValueError("rejected report and workflow disposition must coexist")
        if self.edit_base_content_hash is not None and (
            self.current_node is not WorkflowNode.SYNTHESIZE_CLAIMS
            or self.synthesis is not None
            or self.pending_draft is not None
            or self.active_approval is not None
            or self.validation_receipt_ref is not None
        ):
            raise ValueError("edit state must re-enter synthesis with approval invalidated")
        return self


def source_task_id(run_id: RunId, source: SourceType) -> str:
    """Derive a stable task identity without provider or framework details."""

    return f"source-task:{run_id.removeprefix('run:')}:{source.value}"


def source_task_attempt(task_id: StableWorkflowId, attempt_number: int) -> SourceTaskAttemptRef:
    """Derive the stable logical attempt used by an idempotent collection port."""

    identity_payload = {"task_id": task_id, "attempt_number": attempt_number}
    return SourceTaskAttemptRef(
        attempt_id=derive_identity("source-task-attempt", identity_payload),
        task_id=task_id,
        attempt_number=attempt_number,
        idempotency_key=sha256_digest(canonical_json(identity_payload)),
    )
