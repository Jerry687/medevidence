"""Closed dispatcher for the three externally injected M3 source capabilities."""

from __future__ import annotations

from typing import Protocol, final

from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    AcquisitionOutcomeRef,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    M1BSourcePlanEntryV1,
    ResearchScope,
    ResultStatus,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.tools.cadec_runtime import (
    CADEC_LIMITATION_WARNING,
    CadecLocalSearchPlan,
    CadecRuntimeError,
    CadecSearchResult,
    cadec_search_input_identity,
    cadec_verification_input_identity,
    plan_cadec_local_search,
    reconstruct_cadec_local_search_plan,
    reconstruct_cadec_search_result,
)
from medevidence.tools.contracts import ResearchPubMedRequest
from medevidence.tools.ports import (
    DailyMedExecutionPort,
    FaersExecutionPort,
    FaersPersistencePort,
)
from medevidence.tools.research import PubMedResearchService

from .contracts import (
    MAX_SOURCE_TASK_ATTEMPTS,
    CollectedEvidenceResult,
    CollectionFailureClassification,
    OrchestrationState,
    RequiredSourceOperation,
    SafetyDecision,
    SafetyOutcome,
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    WorkflowNode,
    source_task_id,
)
from .dailymed_faers_capability import (
    CanonicalDailyMedProjectionAuthority,
    CanonicalFaersProjectionAuthority,
    collect_dailymed_capability,
    collect_faers_capability,
    plan_dailymed_operations,
    plan_faers_operations,
)
from .ports import EvidenceCollectionPort
from .pubmed_capability import (
    collect_pubmed,
    plan_pubmed_operations,
    validate_pubmed_terminal_task,
)
from .source_task_projection import (
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)


class SourceCapabilityContractError(ValueError):
    """A pure source plan or terminal projection violated its closed contract."""


class CadecLocalSearchPort(Protocol):
    """Execute one exact source-neutral CADEC plan through replaceable infrastructure."""

    def search(
        self,
        *,
        plan: CadecLocalSearchPlan,
        scope: ResearchScope,
    ) -> CadecSearchResult: ...


def with_source_task(
    state: OrchestrationState,
    index: int,
    task: SourceTaskState,
) -> OrchestrationState:
    """Replace one source task through exact durable-state reconstruction."""

    tasks = list(state.source_tasks)
    tasks[index] = task
    payload = state.model_dump(mode="python")
    payload["source_tasks"] = tuple(tasks)
    return OrchestrationState.model_validate(payload)


def checkpoint_source_task(
    state: OrchestrationState,
    index: int,
    task: SourceTaskState,
) -> OrchestrationState:
    """Persist one collect-node task transition under a derived checkpoint identity."""

    updated = with_source_task(state, index, task)
    payload = updated.model_dump(mode="python")
    payload["checkpoint_id"] = derive_identity(
        "checkpoint",
        {
            "workflow_id": updated.workflow_id,
            "previous_checkpoint_id": updated.checkpoint_id,
            "node": WorkflowNode.COLLECT_EVIDENCE,
            "completed_count": len(updated.completed_nodes) + 1,
        },
    )
    return OrchestrationState.model_validate(payload)


def canonical_source_plan(
    raw: object,
    scope: ResearchScope,
) -> tuple[M1BSourcePlanEntryV1, ...]:
    """Reconstruct one canonically ordered row for every selected scope source."""

    if type(raw) is not tuple or any(type(row) is not M1BSourcePlanEntryV1 for row in raw):
        raise SourceCapabilityContractError("source planning returned a noncanonical plan contract")
    plan = tuple(
        M1BSourcePlanEntryV1.model_validate(row.model_dump(mode="python"), strict=True)
        for row in raw
    )
    sources = tuple(row.source for row in plan)
    if sources != scope.selected_sources or len(set(sources)) != len(sources):
        raise SourceCapabilityContractError(
            "every selected scope source requires exactly one canonical plan row"
        )
    return plan


@final
class CanonicalSourcePlanningAuthority:
    """Frozen exact authority for one scope's full visible source plan."""

    __slots__ = ("_plan", "_scope")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("canonical source planning authority is final")

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("canonical source planning authority is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        scope: ResearchScope,
        plan: tuple[M1BSourcePlanEntryV1, ...],
    ) -> None:
        if type(scope) is not ResearchScope:
            raise SourceCapabilityContractError("source planning authority requires exact scope")
        rebuilt = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        if rebuilt != scope:
            raise SourceCapabilityContractError("source planning authority scope drift")
        self._scope = rebuilt
        self._plan = canonical_source_plan(plan, rebuilt)

    def plan(
        self,
        scope: ResearchScope,
        safety_decision: SafetyDecision,
    ) -> tuple[M1BSourcePlanEntryV1, ...]:
        """Return the frozen plan only for its exact permitted scope decision."""

        if (
            type(self) is not CanonicalSourcePlanningAuthority
            or type(scope) is not ResearchScope
            or scope != self._scope
            or type(safety_decision) is not SafetyDecision
            or safety_decision.outcome is not SafetyOutcome.PERMITTED
        ):
            raise SourceCapabilityContractError(
                "source planning requires exact permitted authority"
            )
        return self._plan


def exact_source_planning_authority(value: object) -> CanonicalSourcePlanningAuthority:
    """Reject every replaceable caller planning port at workflow construction."""

    if type(value) is not CanonicalSourcePlanningAuthority:
        raise SourceCapabilityContractError("workflow requires canonical source planning authority")
    return value


def source_plan_identity(plan: tuple[M1BSourcePlanEntryV1, ...]) -> str:
    """Bind the exact full canonical plan, including visible skip reasons and order."""

    if type(plan) is not tuple or any(type(row) is not M1BSourcePlanEntryV1 for row in plan):
        raise SourceCapabilityContractError("source plan identity requires exact canonical rows")
    return derive_identity("source-plan", plan)


def replay_source_plan(
    authority: CanonicalSourcePlanningAuthority,
    state: OrchestrationState,
) -> None:
    """Re-execute and compare the exact durable full plan before post-plan authority."""

    if not state.source_plan:
        return
    scope = state.interpreted_scope
    decision = state.safety_decision
    if scope is None or decision is None or decision.outcome is not SafetyOutcome.PERMITTED:
        raise SourceCapabilityContractError("source plan replay requires a permitted decision")
    replayed = CanonicalSourcePlanningAuthority.plan(authority, scope, decision)
    if replayed != state.source_plan:
        raise SourceCapabilityContractError("durable source plan differs from exact replay")


def replay_terminal_tasks(port: EvidenceCollectionPort, state: OrchestrationState) -> None:
    """Replay every exact terminal task through its injected source authority."""

    scope = state.interpreted_scope or state.original_scope
    for task in state.source_tasks:
        if task.status is SourceTaskStatus.TERMINAL:
            port.validate_terminal_task(task, scope)


def planned_running_source_task(
    port: EvidenceCollectionPort,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: str,
) -> SourceTaskState:
    """Pure-plan and construct the exact RUNNING checkpoint for one attempt."""

    planning_task = task
    if task.status is SourceTaskStatus.RETRY_WAIT:
        planning_task = SourceTaskState(
            task_id=task.task_id,
            source=task.source,
            required_operations=task.required_operations,
            status=SourceTaskStatus.RUNNING,
            attempts=attempt.attempt_number,
            active_attempt=attempt,
            failure_history=task.failure_history,
        )
    operations = canonical_required_operations(port, planning_task, scope, attempt, run_id)
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=attempt.attempt_number,
        active_attempt=attempt,
        failure_history=task.failure_history,
    )


def verify_running_source_plan(
    port: EvidenceCollectionPort,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: str,
) -> None:
    """Re-plan a resumed task and reject any checkpoint drift before collection."""

    planned = canonical_required_operations(port, task, scope, attempt, run_id)
    expected = (
        task.required_operations[: len(planned)]
        if task.operation_results
        else task.required_operations
    )
    if planned != expected or (
        task.operation_results and task.source not in {SourceType.PUBMED, SourceType.DAILYMED}
    ):
        raise SourceCapabilityContractError("resumed source operation plan drifted")


def canonical_required_operations(
    port: EvidenceCollectionPort,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: str,
) -> tuple[RequiredSourceOperation, ...]:
    """Reconstruct and bind a pure source plan to the exact run/task/source."""

    raw = port.plan_operations(task, scope, attempt)
    if type(raw) is not tuple or any(type(item) is not RequiredSourceOperation for item in raw):
        raise SourceCapabilityContractError(
            "source operation planner returned a noncanonical contract"
        )
    operations = tuple(
        RequiredSourceOperation.model_validate(item.model_dump(mode="python"), strict=True)
        for item in raw
    )
    try:
        from .contracts import validate_required_operation_plan

        validate_required_operation_plan(task.source, operations)
    except ValueError as error:
        raise SourceCapabilityContractError("source operation plan is invalid") from error
    if any(
        item.run_id != run_id
        or item.task_id != task.task_id
        or item.scope_id != scope.scope_id
        or item.source is not task.source
        for item in operations
    ):
        raise SourceCapabilityContractError("source operation plan is foreign or stale")
    return operations


def source_task_after_failure(
    task: SourceTaskState,
    raw: SourceTaskFailureRef,
) -> SourceTaskState:
    """Reconstruct one typed failure and preserve its exact checkpointed plan."""

    failure = SourceTaskFailureRef.model_validate(raw.model_dump(mode="python"))
    if failure.attempt != task.active_attempt:
        raise SourceCapabilityContractError("collection failure belongs to another attempt")
    failures = (*task.failure_history, failure)
    retry = (
        failure.classification is CollectionFailureClassification.RETRYABLE
        and task.attempts < MAX_SOURCE_TASK_ATTEMPTS
    )
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=task.required_operations,
        status=SourceTaskStatus.RETRY_WAIT if retry else SourceTaskStatus.FAILED,
        attempts=task.attempts,
        failure_history=failures,
    )


def source_task_after_progress(
    task: SourceTaskState,
    raw: SourceTaskProgressResult,
    run_id: str,
) -> SourceTaskState:
    """Checkpoint one exact completed operation prefix without terminal authority."""

    if type(raw) is not SourceTaskProgressResult:
        raise SourceCapabilityContractError("source progress returned a noncanonical contract")
    progress = SourceTaskProgressResult.model_validate(raw.model_dump(mode="python"), strict=True)
    if progress.attempt != task.active_attempt:
        raise SourceCapabilityContractError("source progress belongs to another attempt")
    if task.source not in {SourceType.PUBMED, SourceType.DAILYMED}:
        raise SourceCapabilityContractError("source does not permit dynamic operation progress")
    operations = progress.required_operations
    if (
        not operations
        or operations[0].run_id != run_id
        or any(item.run_id != run_id or item.source is not task.source for item in operations)
    ):
        raise SourceCapabilityContractError("source progress belongs to another run or source")
    if len(operations) <= len(task.required_operations) or operations[
        : len(task.required_operations)
    ] != (task.required_operations):
        raise SourceCapabilityContractError("source progress changed its checkpointed plan prefix")
    results = progress.operation_results
    if len(results) >= len(operations):
        raise SourceCapabilityContractError("source progress cannot be terminal")
    if len(results) <= len(task.operation_results) or results[: len(task.operation_results)] != (
        task.operation_results
    ):
        raise SourceCapabilityContractError(
            "source progress changed its checkpointed result prefix"
        )
    if task.terminal_outcome_ref is not None or task.evidence_refs or task.limitations:
        raise SourceCapabilityContractError("source progress cannot carry terminal authority")
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=operations,
        operation_results=results,
        status=SourceTaskStatus.RUNNING,
        attempts=task.attempts,
        active_attempt=task.active_attempt,
        failure_history=task.failure_history,
    )


def terminal_source_task(
    task: SourceTaskState,
    raw: CollectedEvidenceResult,
    run_id: str,
) -> SourceTaskState:
    """Reconstruct and bind every terminal operation before checkpointing it."""

    result = CollectedEvidenceResult.model_validate(raw.model_dump(mode="python"))
    attempt = task.active_attempt
    if result.attempt != attempt:
        raise SourceCapabilityContractError("collection result belongs to another attempt")
    if result.terminal_outcome_ref.outcome.source is not task.source:
        raise SourceCapabilityContractError("collection result belongs to another source")
    if result.terminal_outcome_ref.acquisition.run_id != run_id:
        raise SourceCapabilityContractError("collection result belongs to another run")
    if task.source in {SourceType.FAERS, SourceType.CADEC}:
        if result.required_operations != task.required_operations:
            raise SourceCapabilityContractError(
                "collection result changed the exact operation plan"
            )
    elif result.required_operations[: len(task.required_operations)] != task.required_operations:
        raise SourceCapabilityContractError(
            "collection result does not extend the checkpointed operation-plan prefix"
        )
    if result.operation_results[: len(task.operation_results)] != task.operation_results:
        raise SourceCapabilityContractError(
            "collection result changed its checkpointed operation-result prefix"
        )
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=result.required_operations,
        operation_results=result.operation_results,
        status=SourceTaskStatus.TERMINAL,
        attempts=task.attempts,
        failure_history=task.failure_history,
        terminal_outcome_ref=result.terminal_outcome_ref,
        evidence_refs=result.evidence_refs,
        limitations=result.limitations,
    )


@final
class SourceCapabilities:
    """Statically dispatch exact source tasks to explicit injected capabilities."""

    __slots__ = (
        "_dailymed_execution",
        "_dailymed_projection",
        "_faers_execution",
        "_faers_persistence",
        "_faers_projection",
        "_is_frozen",
        "_pubmed_request",
        "_pubmed_service",
        "_sources",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_is_frozen", False):
            raise AttributeError("source capability composition fields are frozen")
        object.__setattr__(self, name, value)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("SourceCapabilities is a sealed application dispatcher")

    def __init__(
        self,
        *,
        pubmed_request: ResearchPubMedRequest | None = None,
        pubmed_service: PubMedResearchService | None = None,
        dailymed_projection: CanonicalDailyMedProjectionAuthority | None = None,
        dailymed_execution: DailyMedExecutionPort | None = None,
        faers_projection: CanonicalFaersProjectionAuthority | None = None,
        faers_execution: FaersExecutionPort | None = None,
        faers_persistence: FaersPersistencePort | None = None,
    ) -> None:
        pubmed_present = (pubmed_request is not None, pubmed_service is not None)
        dailymed_present = (dailymed_projection is not None, dailymed_execution is not None)
        faers_present = (
            faers_projection is not None,
            faers_execution is not None,
            faers_persistence is not None,
        )
        if len(set(pubmed_present)) != 1:
            raise TypeError("SourceCapabilities requires the complete PubMed dependency group")
        if len(set(dailymed_present)) != 1:
            raise TypeError("SourceCapabilities requires the complete DailyMed dependency group")
        if len(set(faers_present)) != 1:
            raise TypeError("SourceCapabilities requires the complete FAERS dependency group")
        if dailymed_projection is not None and (
            type(dailymed_projection) is not CanonicalDailyMedProjectionAuthority
        ):
            raise TypeError("SourceCapabilities requires canonical DailyMed authority")
        if faers_projection is not None and (
            type(faers_projection) is not CanonicalFaersProjectionAuthority
        ):
            raise TypeError("SourceCapabilities requires canonical FAERS authority")
        sources: set[SourceType] = set()
        if pubmed_request is not None and pubmed_service is not None:
            self._pubmed_request = ResearchPubMedRequest.model_validate(
                pubmed_request.model_dump(mode="python"), strict=True
            )
            self._pubmed_service = pubmed_service
            sources.add(SourceType.PUBMED)
        if dailymed_projection is not None and dailymed_execution is not None:
            self._dailymed_projection = dailymed_projection
            self._dailymed_execution = dailymed_execution
            sources.add(SourceType.DAILYMED)
        if (
            faers_projection is not None
            and faers_execution is not None
            and faers_persistence is not None
        ):
            self._faers_projection = faers_projection
            self._faers_execution = faers_execution
            self._faers_persistence = faers_persistence
            sources.add(SourceType.FAERS)
        self._sources = frozenset(sources)
        object.__setattr__(self, "_is_frozen", True)

    def plan_operations(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> tuple[RequiredSourceOperation, ...]:
        """Freeze one exact source-specific operation plan without source I/O."""

        if task.source is SourceType.PUBMED:
            if SourceType.PUBMED not in self._sources:
                raise SourceCapabilityContractError("PubMed capability group is absent")
            return plan_pubmed_operations(
                task=task,
                scope=scope,
                attempt=attempt,
                request=self._pubmed_request,
                service=self._pubmed_service,
            )
        if task.source is SourceType.DAILYMED:
            if SourceType.DAILYMED not in self._sources:
                raise SourceCapabilityContractError("DailyMed capability group is absent")
            return plan_dailymed_operations(
                task,
                scope,
                attempt,
                projection=self._dailymed_projection,
            )
        if task.source is SourceType.FAERS:
            if SourceType.FAERS not in self._sources:
                raise SourceCapabilityContractError("FAERS capability group is absent")
            return plan_faers_operations(
                task,
                scope,
                attempt,
                projection=self._faers_projection,
            )
        raise ValueError("source task is outside the closed three-source dispatcher")

    def collect(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> CollectedEvidenceResult | SourceTaskProgressResult:
        """Execute one exact source task through its statically selected capability."""

        if task.source is SourceType.PUBMED:
            if SourceType.PUBMED not in self._sources:
                raise SourceCapabilityContractError("PubMed capability group is absent")
            return collect_pubmed(
                task=task,
                scope=scope,
                attempt=attempt,
                request=self._pubmed_request,
                service=self._pubmed_service,
            )
        if task.source is SourceType.DAILYMED:
            if SourceType.DAILYMED not in self._sources:
                raise SourceCapabilityContractError("DailyMed capability group is absent")
            return collect_dailymed_capability(
                task,
                scope,
                attempt,
                projection=self._dailymed_projection,
                execution=self._dailymed_execution,
            )
        if task.source is SourceType.FAERS:
            if SourceType.FAERS not in self._sources:
                raise SourceCapabilityContractError("FAERS capability group is absent")
            return collect_faers_capability(
                task,
                scope,
                attempt,
                projection=self._faers_projection,
                execution=self._faers_execution,
                persistence=self._faers_persistence,
            )
        raise ValueError("source task is outside the closed three-source dispatcher")

    def validate_terminal_task(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
    ) -> None:
        """Reconstruct a terminal non-CADEC task at the sealed delegate boundary."""

        if type(task) is not SourceTaskState or type(scope) is not ResearchScope:
            raise SourceCapabilityContractError(
                "terminal validation requires exact task and scope contracts"
            )
        task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        if (
            task.source is SourceType.CADEC
            or task.status is not SourceTaskStatus.TERMINAL
            or task.source not in scope.selected_sources
            or not task.required_operations
            or any(item.scope_id != scope.scope_id for item in task.required_operations)
        ):
            raise SourceCapabilityContractError(
                "terminal task is outside the sealed three-source scope"
            )
        if task.source is SourceType.PUBMED:
            if SourceType.PUBMED not in self._sources:
                raise SourceCapabilityContractError("PubMed capability group is absent")
            if scope != self._pubmed_request.scope:
                raise SourceCapabilityContractError(
                    "terminal PubMed task belongs to another request"
                )
            validate_pubmed_terminal_task(
                task=task,
                scope=scope,
                request=self._pubmed_request,
                service=self._pubmed_service,
            )
            return
        if task.source is SourceType.DAILYMED:
            if SourceType.DAILYMED not in self._sources:
                raise SourceCapabilityContractError("DailyMed capability group is absent")
            CanonicalDailyMedProjectionAuthority.validate_terminal_task(
                self._dailymed_projection,
                task,
                scope,
            )
            return
        if task.source is SourceType.FAERS:
            if SourceType.FAERS not in self._sources:
                raise SourceCapabilityContractError("FAERS capability group is absent")
            CanonicalFaersProjectionAuthority.validate_terminal_task(
                self._faers_projection,
                task,
                scope,
            )
            return
        raise SourceCapabilityContractError("terminal task source is outside the sealed delegate")


def plan_cadec_operations(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
) -> tuple[RequiredSourceOperation, ...]:
    """Freeze exact CADEC verify/search operations without opening either asset."""

    task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
    scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
    attempt = SourceTaskAttemptRef.model_validate(attempt.model_dump(mode="python"), strict=True)
    _validate_cadec_context(task, scope, attempt)
    plan = CadecLocalSearchPlan.model_validate(
        plan_cadec_local_search(scope).model_dump(mode="python"), strict=True
    )
    operations = _cadec_operations(task, plan)
    if task.status is SourceTaskStatus.RUNNING and task.required_operations != operations:
        raise ValueError("running CADEC task differs from the exact pure operation plan")
    return operations


def collect_cadec_capability(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    search: CadecLocalSearchPort,
) -> CollectedEvidenceResult:
    """Execute exact local CADEC verification/search with no partial-evidence fallback."""

    task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
    scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
    attempt = SourceTaskAttemptRef.model_validate(attempt.model_dump(mode="python"), strict=True)
    operations = plan_cadec_operations(task=task, scope=scope, attempt=attempt)
    if task.status is not SourceTaskStatus.RUNNING:
        raise ValueError("CADEC collection requires an exact planned running task")
    plan = reconstruct_cadec_local_search_plan(plan_cadec_local_search(scope), scope)
    try:
        result = search.search(plan=plan, scope=scope)
        result = reconstruct_cadec_search_result(result, scope=scope, plan=plan)
    except CadecRuntimeError as error:
        return _failed_cadec_collection(task, scope, attempt, operations, plan, error)

    corpus_payload = result.verification.model_dump(mode="python")
    snapshot_id = derive_identity(
        "cadec-search-snapshot",
        {"plan": plan, "verification": corpus_payload},
    )
    verify_outcome = SourceOutcome(
        source=SourceType.CADEC,
        query_id=operations[0].query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=result.outcome.configured_bounds,
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
        warning_codes=(CADEC_LIMITATION_WARNING,),
    )
    verify_result = _cadec_operation_result(
        operation=operations[0],
        attempt=attempt,
        outcome=verify_outcome,
        snapshot_id=snapshot_id,
    )
    search_acquisition = source_operation_acquisition(
        operation=operations[1],
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=_cadec_acquisition_intent_id(operations[1], attempt),
        outcome=result.outcome,
        snapshot_id=snapshot_id,
    )
    observations = tuple(
        source_operation_observation(
            operation=operations[1],
            acquisition=search_acquisition,
            evidence_id=derive_identity("cadec-document-evidence", item),
            content_hash=item.content_sha256,
            locator_ref=item.locator_ref,
        )
        for item in result.evidence_refs
    )
    search_result = TerminalSourceOperationResult(
        operation=operations[1],
        attempt=attempt,
        acquisition=search_acquisition,
        outcome=result.outcome,
        observations=observations,
    )
    operation_results = (verify_result, search_result)
    return _cadec_collection_result(
        task=task,
        operations=operations,
        operation_results=operation_results,
    )


def _validate_cadec_context(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
) -> None:
    if (
        SourceType.CADEC not in scope.selected_sources
        or task.source is not SourceType.CADEC
        or task.task_id != source_task_id(_operation_run_id(task), SourceType.CADEC)
        or attempt.task_id != task.task_id
    ):
        raise ValueError("CADEC capability context is foreign or stale")
    if task.status is SourceTaskStatus.PENDING:
        if task.required_operations or task.attempts != 0 or attempt.attempt_number != 1:
            raise ValueError("pending CADEC planning requires its pristine first attempt")
    elif task.status is SourceTaskStatus.RUNNING:
        if task.active_attempt != attempt or task.attempts != attempt.attempt_number:
            raise ValueError("running CADEC planning requires its exact active attempt")
    else:
        raise ValueError("CADEC planning accepts only pending or running tasks")
    if task.operation_results or task.terminal_outcome_ref is not None or task.evidence_refs:
        raise ValueError("CADEC planning requires an unpopulated task")


def _operation_run_id(task: SourceTaskState) -> str:
    if task.required_operations:
        return task.required_operations[0].run_id
    prefix = "source-task:"
    suffix = f":{task.source.value}"
    if not task.task_id.startswith(prefix) or not task.task_id.endswith(suffix):
        raise ValueError("source task identity is not canonical")
    return "run:" + task.task_id[len(prefix) : -len(suffix)]


def _cadec_operations(
    task: SourceTaskState,
    plan: CadecLocalSearchPlan,
) -> tuple[RequiredSourceOperation, ...]:
    run_id = _operation_run_id(task)
    verify_query_id = derive_identity(
        "cadec-verify-query",
        {
            "archive_sha256": plan.archive_sha256,
            "manifest_sha256": plan.manifest_sha256,
        },
    )
    return (
        required_source_operation(
            run_id=run_id,
            scope_id=plan.scope_id,
            source=SourceType.CADEC,
            ordinal=0,
            kind=SourceOperationKind.CADEC_VERIFY,
            query_id=verify_query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.ASSET,
                    value=derive_identity(
                        "cadec-asset-input",
                        {
                            "archive_sha256": plan.archive_sha256,
                            "manifest_sha256": plan.manifest_sha256,
                        },
                    ),
                ),
                SourceOperationInputRef(
                    role=SourceOperationInputRole.MEMBERSHIP,
                    value=cadec_verification_input_identity(plan),
                ),
            ),
        ),
        required_source_operation(
            run_id=run_id,
            scope_id=plan.scope_id,
            source=SourceType.CADEC,
            ordinal=1,
            kind=SourceOperationKind.CADEC_SEARCH,
            query_id=plan.query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.QUERY_PLAN,
                    value=cadec_search_input_identity(plan),
                ),
            ),
        ),
    )


def _failed_cadec_collection(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    operations: tuple[RequiredSourceOperation, ...],
    plan: CadecLocalSearchPlan,
    error: CadecRuntimeError,
) -> CollectedEvidenceResult:
    bounds = ExecutionBounds.from_scope(scope)
    failure_id = derive_identity(
        "failure",
        {
            "source": SourceType.CADEC,
            "run_id": _operation_run_id(task),
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "archive_sha256": plan.archive_sha256,
            "manifest_sha256": plan.manifest_sha256,
            "error_code": error.code,
        },
    )
    snapshot_id = derive_identity(
        "cadec-failed-asset-attempt",
        {
            "archive_sha256": plan.archive_sha256,
            "manifest_sha256": plan.manifest_sha256,
            "failure_id": failure_id,
        },
    )
    operation_results = tuple(
        _cadec_operation_result(
            operation=operation,
            attempt=attempt,
            outcome=SourceOutcome(
                source=SourceType.CADEC,
                query_id=operation.query_id,
                execution_status=ExecutionStatus.FAILED,
                coverage_status=CoverageStatus.UNAVAILABLE,
                result_status=ResultStatus.INDETERMINATE,
                configured_bounds=bounds,
                valid_result_count=0,
                pages_completed=0,
                truncated=False,
                warning_codes=(CADEC_LIMITATION_WARNING,),
                failure_id=failure_id,
            ),
            snapshot_id=snapshot_id,
        )
        for operation in operations
    )
    return _cadec_collection_result(
        task=task,
        operations=operations,
        operation_results=operation_results,
    )


def _cadec_operation_result(
    *,
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
    outcome: SourceOutcome,
    snapshot_id: str,
) -> TerminalSourceOperationResult:
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=source_operation_acquisition(
            operation=operation,
            attempt_id=attempt.attempt_id,
            acquisition_intent_id=_cadec_acquisition_intent_id(operation, attempt),
            outcome=outcome,
            snapshot_id=snapshot_id,
        ),
        outcome=outcome,
    )


def _cadec_collection_result(
    *,
    task: SourceTaskState,
    operations: tuple[RequiredSourceOperation, ...],
    operation_results: tuple[TerminalSourceOperationResult, ...],
) -> CollectedEvidenceResult:
    terminal_outcome = canonical_terminal_source_outcome(operations, operation_results)
    search_acquisition = operation_results[1].acquisition
    terminal_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity(
            "source-task-terminal-outcome",
            terminal_outcome,
        ),
        operation_acquisition_ids=tuple(
            item.acquisition.acquisition_id for item in operation_results
        ),
        acquisition=AcquisitionOutcomeRef(
            run_id=_operation_run_id(task),
            source=SourceType.CADEC,
            acquisition_id=search_acquisition.acquisition_id,
            acquisition_intent_id=search_acquisition.acquisition_intent_id,
            acquisition_ordinal=1,
            operation="search",
            query_id=operations[1].query_id,
            source_outcome_id=search_acquisition.source_outcome_id,
            snapshot_id=search_acquisition.snapshot_id,
        ),
        outcome=terminal_outcome,
    )
    evidence_refs = tuple(
        observation.evidence_reference
        for result in operation_results
        for observation in result.observations
    )
    return CollectedEvidenceResult(
        attempt=operation_results[0].attempt,
        required_operations=operations,
        operation_results=operation_results,
        terminal_outcome_ref=terminal_ref,
        evidence_refs=evidence_refs,
        limitations=tuple(CADEC_MANDATORY_LIMITATIONS),
    )


def _cadec_acquisition_intent_id(
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
) -> str:
    return derive_identity(
        "acquisition-intent",
        {
            "run_id": operation.run_id,
            "task_id": operation.task_id,
            "attempt_id": attempt.attempt_id,
            "scope_id": operation.scope_id,
            "operation": operation,
        },
    )


__all__ = [
    "SourceCapabilities",
    "collect_cadec_capability",
    "plan_cadec_operations",
]
