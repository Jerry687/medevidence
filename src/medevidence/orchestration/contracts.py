"""Framework-neutral contracts for the bounded V1 orchestration workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    FAERS_MANDATORY_LIMITATIONS,
    AcquisitionOutcomeRef,
    CitationId,
    ClaimId,
    CoverageStatus,
    ExecutionStatus,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ReportId,
    ResearchScope,
    ResultStatus,
    RunId,
    Sha256Digest,
    SourceOutcome,
    SourceType,
    UtcDateTime,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.identifiers import (
    AcquisitionIntentId,
    DurableModel,
    LongText,
    derive_identity,
)

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
MAX_SOURCE_TASK_OPERATIONS = 101
MAX_OPERATION_OBSERVATIONS = 100


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

    schema_version: Literal["m3.source-outcome-ref.v2"] = "m3.source-outcome-ref.v2"
    terminal_outcome_id: StableWorkflowId
    operation_acquisition_ids: tuple[StableWorkflowId, ...] = Field(
        min_length=1, max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    acquisition: AcquisitionOutcomeRef
    outcome: SourceOutcome

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.acquisition.source is not self.outcome.source:
            raise ValueError("source outcome representative acquisition has the wrong source")
        if len(set(self.operation_acquisition_ids)) != len(self.operation_acquisition_ids):
            raise ValueError("terminal operation acquisition identities must be unique")
        expected = derive_identity("source-task-terminal-outcome", self.outcome)
        if self.terminal_outcome_id != expected:
            raise ValueError("terminal outcome identity does not match its exact content")
        return self


class EvidenceReference(DurableModel):
    """Immutable source evidence identity without copied source content."""

    schema_version: Literal["m3.evidence-ref.v1"] = "m3.evidence-ref.v1"
    evidence_id: StableWorkflowId
    source: SourceType
    snapshot_id: StableWorkflowId
    content_hash: Sha256Digest
    locator_ref: StableWorkflowId


class SourceOperationKind(StrEnum):
    """Closed source-neutral operation kinds required by M3-006."""

    PUBMED_SEARCH = "pubmed_search"
    PUBMED_FETCH = "pubmed_fetch"
    DAILYMED_DISCOVERY = "dailymed_discovery"
    DAILYMED_FETCH = "dailymed_fetch"
    FAERS_AGGREGATE = "faers_aggregate"
    CADEC_VERIFY = "cadec_verify"
    CADEC_SEARCH = "cadec_search"


class SourceOperationInputRole(StrEnum):
    """Closed semantic roles used to bind selected source work."""

    REQUEST = "request"
    PUBMED_PMID = "pubmed_pmid"
    DAILYMED_DECISION = "dailymed_decision"
    CANDIDATE = "candidate"
    SETID = "setid"
    SPL_VERSION = "spl_version"
    ASSET = "asset"
    MEMBERSHIP = "membership"
    QUERY_PLAN = "query_plan"


class SourceOperationInputRef(DurableModel):
    """One typed primitive identity selected for a required operation."""

    schema_version: Literal["m3.source-operation-input-ref.v1"] = "m3.source-operation-input-ref.v1"
    role: SourceOperationInputRole
    value: StableWorkflowId


class RequiredSourceOperation(DurableModel):
    """One operation frozen before a source task executes."""

    schema_version: Literal["m3.required-source-operation.v3"] = "m3.required-source-operation.v3"
    operation_id: StableWorkflowId
    run_id: RunId
    task_id: StableWorkflowId
    scope_id: StableWorkflowId
    source: SourceType
    ordinal: int = Field(ge=0, lt=MAX_SOURCE_TASK_OPERATIONS)
    kind: SourceOperationKind
    query_id: StableWorkflowId
    input_refs: tuple[SourceOperationInputRef, ...] = Field(min_length=1, max_length=16)
    input_identity: StableWorkflowId

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.task_id != source_task_id(self.run_id, self.source):
            raise ValueError("required operation task identity must bind run and source")
        roles = tuple(item.role for item in self.input_refs)
        if len(set(roles)) != len(roles):
            raise ValueError("source operation input roles must be unique")
        expected_input = derive_identity(
            "source-operation-input",
            {
                "kind": self.kind,
                "query_id": self.query_id,
                "input_refs": self.input_refs,
            },
        )
        if self.input_identity != expected_input:
            raise ValueError("source operation input identity does not match typed inputs")
        payload = self.model_dump(mode="python", exclude={"schema_version", "operation_id"})
        if self.operation_id != derive_identity("source-operation", payload):
            raise ValueError("required operation identity does not match its content")
        return self


class SourceOperationAcquisitionRef(DurableModel):
    """Reference binding one executed operation to its acquisition and snapshot."""

    schema_version: Literal["m3.source-operation-acquisition-ref.v2"] = (
        "m3.source-operation-acquisition-ref.v2"
    )
    acquisition_id: StableWorkflowId
    acquisition_intent_id: AcquisitionIntentId
    run_id: RunId
    task_id: StableWorkflowId
    attempt_id: StableWorkflowId
    source: SourceType
    ordinal: int = Field(ge=0, lt=MAX_SOURCE_TASK_OPERATIONS)
    operation_id: StableWorkflowId
    kind: SourceOperationKind
    query_id: StableWorkflowId
    source_outcome_id: StableWorkflowId
    snapshot_id: StableWorkflowId

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"schema_version", "acquisition_id"})
        if self.acquisition_id != derive_identity("source-operation-acquisition", payload):
            raise ValueError("operation acquisition identity does not match its content")
        return self


class SourceOperationObservationRef(DurableModel):
    """Content-free observation provenance for one operation acquisition."""

    schema_version: Literal["m3.source-operation-observation-ref.v1"] = (
        "m3.source-operation-observation-ref.v1"
    )
    observation_id: StableWorkflowId
    run_id: RunId
    task_id: StableWorkflowId
    attempt_id: StableWorkflowId
    source: SourceType
    ordinal: int = Field(ge=0, lt=MAX_SOURCE_TASK_OPERATIONS)
    operation_id: StableWorkflowId
    query_id: StableWorkflowId
    acquisition_id: StableWorkflowId
    snapshot_id: StableWorkflowId
    evidence_id: StableWorkflowId
    content_hash: Sha256Digest
    locator_ref: StableWorkflowId

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"schema_version", "observation_id"})
        if self.observation_id != derive_identity("source-observation", payload):
            raise ValueError("operation observation identity does not match its content")
        return self

    @property
    def evidence_reference(self) -> EvidenceReference:
        """Project the bounded observation into the existing evidence reference."""

        return EvidenceReference(
            evidence_id=self.evidence_id,
            source=self.source,
            snapshot_id=self.snapshot_id,
            content_hash=self.content_hash,
            locator_ref=self.locator_ref,
        )


class TerminalSourceOperationResult(DurableModel):
    """One reconstructed terminal result for one required operation."""

    schema_version: Literal["m3.terminal-source-operation-result.v1"] = (
        "m3.terminal-source-operation-result.v1"
    )
    operation: RequiredSourceOperation
    attempt: SourceTaskAttemptRef
    acquisition: SourceOperationAcquisitionRef
    outcome: SourceOutcome
    observations: tuple[SourceOperationObservationRef, ...] = Field(
        default=(), max_length=MAX_OPERATION_OBSERVATIONS
    )

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        operation = self.operation
        acquisition = self.acquisition
        if self.attempt.task_id != operation.task_id:
            raise ValueError("operation result attempt must bind the task")
        expected = (
            operation.run_id,
            operation.task_id,
            self.attempt.attempt_id,
            operation.source,
            operation.ordinal,
            operation.operation_id,
            operation.kind,
            operation.query_id,
        )
        actual = (
            acquisition.run_id,
            acquisition.task_id,
            acquisition.attempt_id,
            acquisition.source,
            acquisition.ordinal,
            acquisition.operation_id,
            acquisition.kind,
            acquisition.query_id,
        )
        if actual != expected:
            raise ValueError("operation acquisition must bind run/task/attempt/source/operation")
        if (
            self.outcome.source is not operation.source
            or self.outcome.query_id != operation.query_id
        ):
            raise ValueError("operation outcome must bind source and query")
        expected_outcome_id = derive_identity("source-operation-outcome", self.outcome)
        if acquisition.source_outcome_id != expected_outcome_id:
            raise ValueError("operation acquisition must bind the exact outcome content")
        observation_ids = tuple(item.observation_id for item in self.observations)
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("operation observations must be unique")
        evidence_ids = tuple(item.evidence_id for item in self.observations)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("operation observation evidence identities must be unique")
        for observation in self.observations:
            observed = (
                observation.run_id,
                observation.task_id,
                observation.attempt_id,
                observation.source,
                observation.ordinal,
                observation.operation_id,
                observation.query_id,
                observation.acquisition_id,
                observation.snapshot_id,
            )
            expected_observation = (
                operation.run_id,
                operation.task_id,
                self.attempt.attempt_id,
                operation.source,
                operation.ordinal,
                operation.operation_id,
                operation.query_id,
                acquisition.acquisition_id,
                acquisition.snapshot_id,
            )
            if observed != expected_observation:
                raise ValueError("operation observation must bind its exact acquisition")
        return self


class SourceTaskProgressResult(DurableModel):
    """Durable post-operation checkpoint before a dynamically expanded task finishes."""

    schema_version: Literal["m3.source-task-progress-result.v1"] = (
        "m3.source-task-progress-result.v1"
    )
    attempt: SourceTaskAttemptRef
    required_operations: tuple[RequiredSourceOperation, ...] = Field(
        min_length=1, max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    operation_results: tuple[TerminalSourceOperationResult, ...] = Field(
        min_length=1, max_length=MAX_SOURCE_TASK_OPERATIONS
    )

    @model_validator(mode="after")
    def validate_progress(self) -> Self:
        source = self.required_operations[0].source
        validate_required_operation_plan(source, self.required_operations)
        if (
            tuple(item.operation for item in self.operation_results)
            != self.required_operations[: len(self.operation_results)]
        ):
            raise ValueError("progress results must equal a nonempty exact plan prefix")
        if any(item.attempt != self.attempt for item in self.operation_results):
            raise ValueError("progress results must bind one exact attempt")
        if any(item.task_id != self.attempt.task_id for item in self.required_operations):
            raise ValueError("progress plan must bind the attempted task")
        if len({item.run_id for item in self.required_operations}) != 1:
            raise ValueError("progress plan must bind one exact run")
        return self


def validate_terminal_operation_binding(
    terminal: TerminalSourceOutcomeRef,
    results: tuple[TerminalSourceOperationResult, ...],
) -> None:
    """Bind the task outcome separately from its exact operation acquisitions."""

    acquisition_ids = tuple(item.acquisition.acquisition_id for item in results)
    if terminal.operation_acquisition_ids != acquisition_ids:
        raise ValueError("terminal operation acquisition identities must equal exact result order")
    representative = next(
        (
            item
            for item in results
            if item.acquisition.acquisition_id == terminal.acquisition.acquisition_id
        ),
        None,
    )
    if representative is None:
        raise ValueError("representative acquisition must be one terminal operation acquisition")
    acquisition = terminal.acquisition
    operation_acquisition = representative.acquisition
    legacy_operation = (
        "fetch"
        if representative.operation.kind
        in {SourceOperationKind.PUBMED_FETCH, SourceOperationKind.DAILYMED_FETCH}
        else "search"
    )
    if (
        acquisition.run_id != operation_acquisition.run_id
        or acquisition.source is not operation_acquisition.source
        or acquisition.acquisition_intent_id != operation_acquisition.acquisition_intent_id
        or acquisition.acquisition_ordinal != operation_acquisition.ordinal
        or acquisition.operation != legacy_operation
        or acquisition.query_id != operation_acquisition.query_id
        or acquisition.source_outcome_id != operation_acquisition.source_outcome_id
        or acquisition.snapshot_id != operation_acquisition.snapshot_id
    ):
        raise ValueError("representative acquisition must equal its exact operation binding")


def validate_source_limitations(
    source: SourceType,
    limitations: tuple[LongText, ...],
) -> None:
    """Enforce governed source limitations without inventing new source semantics."""

    if len(set(limitations)) != len(limitations):
        raise ValueError("source limitations must be unique and canonically ordered")
    if source is SourceType.CADEC and limitations != CADEC_MANDATORY_LIMITATIONS:
        raise ValueError("terminal CADEC task requires exact mandatory limitations")
    if source is SourceType.FAERS and limitations != FAERS_MANDATORY_LIMITATIONS:
        raise ValueError("terminal FAERS task requires exact mandatory limitations")


def validate_cadec_degraded_evidence(
    source: SourceType,
    outcome: SourceOutcome,
    evidence_refs: tuple[EvidenceReference, ...],
    results: tuple[TerminalSourceOperationResult, ...],
) -> None:
    """A degraded CADEC task exposes no partial observation or evidence reference."""

    degraded = (
        outcome.execution_status is ExecutionStatus.FAILED
        or outcome.coverage_status is CoverageStatus.UNAVAILABLE
        or outcome.result_status is ResultStatus.INDETERMINATE
    )
    if (
        source is SourceType.CADEC
        and degraded
        and (evidence_refs or any(item.observations for item in results))
    ):
        raise ValueError("degraded CADEC task cannot expose observations or evidence")


def validate_required_operation_plan(
    source: SourceType,
    operations: tuple[RequiredSourceOperation, ...],
) -> None:
    """Reject noncanonical, duplicated, or source-incompatible operation plans."""

    if not operations:
        raise ValueError("source task requires at least one required operation")
    if len(operations) > MAX_SOURCE_TASK_OPERATIONS:
        raise ValueError("source task operation count exceeds its bound")
    if tuple(item.ordinal for item in operations) != tuple(range(len(operations))):
        raise ValueError("required operations must use contiguous canonical ordinals")
    if len({item.operation_id for item in operations}) != len(operations):
        raise ValueError("required operation identities must be unique")
    if any(item.source is not source for item in operations):
        raise ValueError("required operations must belong to the task source")
    if len({item.scope_id for item in operations}) != 1:
        raise ValueError("required operations must bind one exact scope")
    required_roles = {
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
    }
    for item in operations:
        if tuple(ref.role for ref in item.input_refs) != required_roles[item.kind]:
            raise ValueError(f"{item.kind.value} requires its exact typed input roles")
    kinds = tuple(item.kind for item in operations)
    if source is SourceType.PUBMED:
        if any(item.query_id != operations[0].query_id for item in operations[1:]):
            raise ValueError("PubMed fetches must share the exact search query identity")
        if kinds[0] is not SourceOperationKind.PUBMED_SEARCH or any(
            kind is not SourceOperationKind.PUBMED_FETCH for kind in kinds[1:]
        ):
            raise ValueError("PubMed requires search followed by zero to 100 fetches")
        pmids = tuple(
            item.input_refs[0].value
            for item in operations
            if item.kind is SourceOperationKind.PUBMED_FETCH
        )
        if len(set(pmids)) != len(pmids):
            raise ValueError("PubMed fetch PMID inputs must be unique")
    elif source is SourceType.DAILYMED:
        if len(operations) > 8:
            raise ValueError("DailyMed operation count exceeds four discovery/fetch groups")
        first_fetch = next(
            (
                index
                for index, item in enumerate(operations)
                if item.kind is SourceOperationKind.DAILYMED_FETCH
            ),
            len(operations),
        )
        discoveries = operations[:first_fetch]
        fetches = operations[first_fetch:]
        if not discoveries or any(
            item.kind is not SourceOperationKind.DAILYMED_DISCOVERY for item in discoveries
        ):
            raise ValueError("DailyMed requires a nonempty discovery prefix")
        if any(item.kind is not SourceOperationKind.DAILYMED_FETCH for item in fetches):
            raise ValueError("DailyMed discovery cannot appear after the fetch suffix begins")
        discovery_query_ids = tuple(item.query_id for item in discoveries)
        if len(set(discovery_query_ids)) != len(discovery_query_ids):
            raise ValueError("DailyMed discovery query identities must be unique")
        if len(discoveries) > 4:
            raise ValueError("DailyMed requires one to four discovery groups")
        fetch_query_ids = tuple(item.query_id for item in fetches)
        if len(set(fetch_query_ids)) != len(fetch_query_ids):
            raise ValueError("DailyMed permits at most one fetch per discovery")
        discovery_order = {query_id: index for index, query_id in enumerate(discovery_query_ids)}
        if any(query_id not in discovery_order for query_id in fetch_query_ids):
            raise ValueError("DailyMed fetch must bind a prior discovery query")
        fetch_order = tuple(discovery_order[query_id] for query_id in fetch_query_ids)
        if fetch_order != tuple(sorted(fetch_order)):
            raise ValueError("DailyMed fetch suffix must preserve discovery order")
    elif source is SourceType.FAERS:
        if len({item.query_id for item in operations}) != len(operations):
            raise ValueError("FAERS operation query identities must be unique")
        if len(kinds) > 8 or any(kind is not SourceOperationKind.FAERS_AGGREGATE for kind in kinds):
            raise ValueError("FAERS requires one to eight aggregate operations")
    else:
        if len({item.query_id for item in operations}) != len(operations):
            raise ValueError("CADEC operation query identities must be unique")
        if kinds != (SourceOperationKind.CADEC_VERIFY, SourceOperationKind.CADEC_SEARCH):
            raise ValueError("CADEC requires verification followed by search")


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

    schema_version: Literal["m3.source-task.v3"] = "m3.source-task.v3"
    task_id: StableWorkflowId
    source: SourceType
    required_operations: tuple[RequiredSourceOperation, ...] = Field(
        default=(), max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    operation_results: tuple[TerminalSourceOperationResult, ...] = Field(
        default=(), max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    status: SourceTaskStatus = SourceTaskStatus.PENDING
    attempts: int = Field(default=0, ge=0, le=MAX_SOURCE_TASK_ATTEMPTS)
    active_attempt: SourceTaskAttemptRef | None = None
    failure_history: tuple[SourceTaskFailureRef, ...] = Field(
        default=(),
        max_length=MAX_SOURCE_TASK_ATTEMPTS,
    )
    terminal_outcome_ref: TerminalSourceOutcomeRef | None = None
    evidence_refs: tuple[EvidenceReference, ...] = Field(default=(), max_length=100)
    limitations: tuple[LongText, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_task_state(self) -> Self:
        if not self.required_operations:
            pristine_pending = (
                self.status is SourceTaskStatus.PENDING
                and self.attempts == 0
                and self.active_attempt is None
                and not self.failure_history
                and not self.operation_results
                and self.terminal_outcome_ref is None
                and not self.evidence_refs
                and not self.limitations
            )
            if not pristine_pending:
                raise ValueError("non-pristine source task requires a nonempty operation plan")
            return self
        validate_required_operation_plan(self.source, self.required_operations)
        plan_task_ids = {item.task_id for item in self.required_operations}
        plan_run_ids = {item.run_id for item in self.required_operations}
        if plan_task_ids != {self.task_id} or len(plan_run_ids) != 1:
            raise ValueError("required operations must bind the exact source task")
        result_operations = tuple(item.operation for item in self.operation_results)
        if result_operations != self.required_operations[: len(result_operations)]:
            raise ValueError("operation results must be the canonical required-plan prefix")
        result_attempts = {item.attempt.attempt_id for item in self.operation_results}
        if len(result_attempts) > 1:
            raise ValueError("operation results must belong to one task attempt")
        terminal = self.status is SourceTaskStatus.TERMINAL
        failed = self.status is SourceTaskStatus.FAILED
        if self.operation_results and not terminal:
            if self.status is not SourceTaskStatus.RUNNING:
                raise ValueError("only a running task may retain operation progress")
            if (
                self.active_attempt is None
                or self.attempts != self.active_attempt.attempt_number
                or any(item.attempt != self.active_attempt for item in self.operation_results)
            ):
                raise ValueError("running operation progress must bind the exact active attempt")
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
        if terminal and len(self.operation_results) != len(self.required_operations):
            raise ValueError("terminal source task requires every required operation terminal")
        if terminal and any(
            item.attempt.attempt_number != self.attempts for item in self.operation_results
        ):
            raise ValueError("terminal operation results must bind the task attempt count")
        if not terminal and self.evidence_refs:
            raise ValueError("unexecuted source task cannot expose evidence")
        if not terminal and self.limitations:
            raise ValueError("nonterminal source task cannot expose limitations")
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
            if self.terminal_outcome_ref.acquisition.run_id not in plan_run_ids:
                raise ValueError("source task terminal acquisition must bind the operation run")
        if any(item.source is not self.source for item in self.evidence_refs):
            raise ValueError("source task evidence must belong to the same source")
        if len({item.evidence_id for item in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError("source task evidence references must be unique")
        projected_evidence = tuple(
            observation.evidence_reference
            for result in self.operation_results
            for observation in result.observations
        )
        if terminal and self.evidence_refs != projected_evidence:
            raise ValueError("source task evidence must equal its operation observations")
        if terminal and self.terminal_outcome_ref is not None:
            validate_terminal_operation_binding(
                self.terminal_outcome_ref,
                self.operation_results,
            )
            validate_source_limitations(self.source, self.limitations)
            validate_cadec_degraded_evidence(
                self.source,
                self.terminal_outcome_ref.outcome,
                self.evidence_refs,
                self.operation_results,
            )
            from .source_task_projection import validate_canonical_terminal_source_outcome

            validate_canonical_terminal_source_outcome(
                self.terminal_outcome_ref.outcome,
                self.required_operations,
                self.operation_results,
            )
        return self


class CollectedEvidenceResult(DurableModel):
    """One bounded collection result with no source payload bytes."""

    schema_version: Literal["m3.collected-evidence.v2"] = "m3.collected-evidence.v2"
    attempt: SourceTaskAttemptRef
    required_operations: tuple[RequiredSourceOperation, ...] = Field(
        min_length=1, max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    operation_results: tuple[TerminalSourceOperationResult, ...] = Field(
        min_length=1, max_length=MAX_SOURCE_TASK_OPERATIONS
    )
    terminal_outcome_ref: TerminalSourceOutcomeRef
    evidence_refs: tuple[EvidenceReference, ...] = Field(default=(), max_length=100)
    limitations: tuple[LongText, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        source = self.terminal_outcome_ref.outcome.source
        validate_required_operation_plan(source, self.required_operations)
        if tuple(item.operation for item in self.operation_results) != self.required_operations:
            raise ValueError("collection requires every required operation exactly terminal")
        if any(item.attempt != self.attempt for item in self.operation_results):
            raise ValueError("collection operation results must bind the exact attempt")
        if any(item.operation.task_id != self.attempt.task_id for item in self.operation_results):
            raise ValueError("collection operation plan must bind the attempted task")
        operation_run_ids = {item.run_id for item in self.required_operations}
        if self.terminal_outcome_ref.acquisition.run_id not in operation_run_ids:
            raise ValueError("collection terminal acquisition must bind the operation run")
        if any(item.source is not source for item in self.evidence_refs):
            raise ValueError("collected evidence must match the terminal outcome source")
        projected_evidence = tuple(
            observation.evidence_reference
            for result in self.operation_results
            for observation in result.observations
        )
        if self.evidence_refs != projected_evidence:
            raise ValueError("collected evidence must equal its operation observations")
        validate_terminal_operation_binding(self.terminal_outcome_ref, self.operation_results)
        validate_source_limitations(source, self.limitations)
        validate_cadec_degraded_evidence(
            source,
            self.terminal_outcome_ref.outcome,
            self.evidence_refs,
            self.operation_results,
        )
        from .source_task_projection import validate_canonical_terminal_source_outcome

        validate_canonical_terminal_source_outcome(
            self.terminal_outcome_ref.outcome,
            self.required_operations,
            self.operation_results,
        )
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
