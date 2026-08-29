"""Explicit DailyMed and FAERS source-task capability adapters."""

from __future__ import annotations

from typing import Literal, Protocol, Self, final

from pydantic import Field, TypeAdapter, model_validator

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    AcquisitionOutcomeRef,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    LabelSelectionStatus,
    M1BResearchRequestV1,
    ResearchScope,
    RunId,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.domain.identifiers import DurableModel, LongText
from medevidence.tools.contracts import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    FaersAggregateExecution,
)
from medevidence.tools.dailymed import (
    DailyMedDiscoveryExecutionProjection,
    DailyMedDiscoveryProvenanceProjection,
    DailyMedFetchExecutionProjection,
    DailyMedFetchProvenanceProjection,
    discover_dailymed_labels,
    fetch_dailymed_label,
)
from medevidence.tools.faers import (
    FaersAggregateExecutionProjection,
    FaersAggregateProvenanceProjection,
    execute_faers_aggregate,
)
from medevidence.tools.ports import (
    DailyMedExecutionPort,
    FaersExecutionPort,
    FaersPersistencePort,
)

from .contracts import (
    CollectedEvidenceResult,
    RequiredSourceOperation,
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    SourceTaskAttemptRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    StableWorkflowId,
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    source_task_id,
    validate_required_operation_plan,
    validate_source_limitations,
)
from .source_task_projection import (
    aggregate_source_operation_disposition,
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)

FAERS_MANDATORY_WARNING = "faers_mandatory_limitations"


class DailyMedRequestProjection(DurableModel):
    """Exact pre-execution DailyMed discovery tuple bound to one attempt."""

    schema_version: Literal["m3.dailymed-request-projection.v1"] = (
        "m3.dailymed-request-projection.v1"
    )
    run_id: RunId
    scope_id: StableWorkflowId
    task_id: StableWorkflowId
    attempt_id: StableWorkflowId
    requests: tuple[DailyMedDiscoveryRequest, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_requests(self) -> Self:
        query_ids = tuple(item.query_id for item in self.requests)
        if len(set(query_ids)) != len(query_ids):
            raise ValueError("DailyMed discovery query identities must be unique")
        drug_ids = tuple(item.selection_request.drug_concept_id for item in self.requests)
        if drug_ids != tuple(sorted(set(drug_ids))):
            raise ValueError("DailyMed discovery requests must be unique and sorted by drug")
        return self


class FaersRequestProjection(DurableModel):
    """Exact pre-execution FAERS aggregate tuple bound to one attempt."""

    schema_version: Literal["m3.faers-request-projection.v1"] = "m3.faers-request-projection.v1"
    run_id: RunId
    scope_id: StableWorkflowId
    task_id: StableWorkflowId
    attempt_id: StableWorkflowId
    requests: tuple[FaersAggregateRequestV1, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_requests(self) -> Self:
        keys = tuple((item.drug_concept_id, item.identity_strategy.value) for item in self.requests)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("FAERS requests must be unique and sorted by drug and strategy")
        return self


class SourceTaskTerminalProjection(DurableModel):
    """Source-specific terminal numerical projection bound to one exact attempt."""

    schema_version: Literal["m3.source-task-terminal-projection.v1"] = (
        "m3.source-task-terminal-projection.v1"
    )
    run_id: RunId
    scope_id: StableWorkflowId
    task_id: StableWorkflowId
    attempt_id: StableWorkflowId
    terminal_outcome_ref: TerminalSourceOutcomeRef
    limitations: tuple[LongText, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_limitations(self) -> Self:
        if self.limitations != tuple(sorted(set(self.limitations))):
            raise ValueError("source limitations must be unique and canonically sorted")
        return self


class DailyMedCapabilityProjectionPort(Protocol):
    """Supply stable DailyMed request and provenance projections."""

    def freeze_discovery_requests(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> DailyMedRequestProjection: ...

    def project_discovery(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        request: DailyMedDiscoveryRequest,
        response: DailyMedDiscoveryResponse,
    ) -> DailyMedDiscoveryExecutionProjection: ...

    def freeze_fetch_request(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        discovery: DailyMedDiscoveryExecutionProjection,
    ) -> DailyMedFetchRequest: ...

    def project_fetch(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        request: DailyMedFetchRequest,
        response: DailyMedFetchResponse,
    ) -> DailyMedFetchExecutionProjection: ...

    def reconstruct_fetch_request(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        operation: RequiredSourceOperation,
    ) -> DailyMedFetchRequest: ...

    def project_terminal(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        required_operations: tuple[RequiredSourceOperation, ...],
        operation_results: tuple[TerminalSourceOperationResult, ...],
    ) -> SourceTaskTerminalProjection: ...


class FaersCapabilityProjectionPort(Protocol):
    """Supply stable FAERS request, evidence, and terminal projections."""

    def freeze_requests(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> FaersRequestProjection: ...

    def project_execution(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        execution: FaersAggregateExecution,
    ) -> FaersAggregateExecutionProjection: ...

    def project_terminal(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        required_operations: tuple[RequiredSourceOperation, ...],
        operation_results: tuple[TerminalSourceOperationResult, ...],
    ) -> SourceTaskTerminalProjection: ...


class DailyMedPersistedProvenancePort(Protocol):
    """Load only already-persisted DailyMed acquisition and section identities."""

    def load_discovery(
        self,
        *,
        request: DailyMedDiscoveryRequest,
        response: DailyMedDiscoveryResponse,
    ) -> DailyMedDiscoveryProvenanceProjection: ...

    def load_fetch(
        self,
        *,
        request: DailyMedFetchRequest,
        response: DailyMedFetchResponse,
    ) -> DailyMedFetchProvenanceProjection: ...


class DailyMedReplayStorePort(Protocol):
    """Persist and reload immutable canonical DailyMed execution projections."""

    def persist_discovery(
        self,
        record: DailyMedDiscoveryExecutionProjection,
    ) -> DailyMedDiscoveryExecutionProjection: ...

    def persist_fetch(
        self,
        record: DailyMedFetchExecutionProjection,
    ) -> DailyMedFetchExecutionProjection: ...

    def load_discovery(
        self,
        *,
        acquisition_intent_id: str,
        run_id: RunId,
        task_id: StableWorkflowId,
        attempt_id: StableWorkflowId,
        query_id: StableWorkflowId,
    ) -> DailyMedDiscoveryExecutionProjection: ...

    def load_fetch(
        self,
        *,
        acquisition_intent_id: str,
        run_id: RunId,
        task_id: StableWorkflowId,
        attempt_id: StableWorkflowId,
        query_id: StableWorkflowId,
    ) -> DailyMedFetchExecutionProjection: ...


class FaersPersistedProvenancePort(Protocol):
    """Load only already-persisted FAERS bucket/content identities."""

    def load_aggregate(
        self,
        *,
        execution: FaersAggregateExecution,
    ) -> FaersAggregateProvenanceProjection: ...


class FaersReplayStorePort(Protocol):
    """Persist and reload immutable canonical FAERS execution projections."""

    def persist_aggregate(
        self,
        record: FaersAggregateExecutionProjection,
    ) -> FaersAggregateExecutionProjection: ...

    def load_aggregate(
        self,
        *,
        acquisition_intent_id: str,
        run_id: RunId,
        task_id: StableWorkflowId,
        attempt_id: StableWorkflowId,
        query_id: StableWorkflowId,
    ) -> FaersAggregateExecutionProjection: ...


@final
class CanonicalDailyMedProjectionAuthority:
    """Sealed production authority for exact DailyMed request and task projection."""

    _frozen: bool
    _limitations: tuple[LongText, ...]
    _provenance: DailyMedPersistedProvenancePort
    _replay_store: DailyMedReplayStorePort
    _request: M1BResearchRequestV1
    _run_id: RunId

    __slots__ = (
        "_frozen",
        "_limitations",
        "_provenance",
        "_replay_store",
        "_request",
        "_run_id",
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalDailyMedProjectionAuthority is sealed")

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("CanonicalDailyMedProjectionAuthority is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        request: M1BResearchRequestV1,
        run_id: RunId,
        limitations: tuple[LongText, ...],
        provenance: DailyMedPersistedProvenancePort,
        replay_store: DailyMedReplayStorePort,
    ) -> None:
        request = M1BResearchRequestV1.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        validated_run_id: RunId = TypeAdapter(RunId).validate_python(run_id, strict=True)
        if SourceType.DAILYMED not in request.requested_sources:
            raise ValueError("canonical DailyMed authority requires DailyMed requested")
        validated_limitations = TypeAdapter(tuple[LongText, ...]).validate_python(
            limitations, strict=True
        )
        if len(validated_limitations) > 16:
            raise ValueError("DailyMed limitations exceed the terminal bound")
        validate_source_limitations(SourceType.DAILYMED, validated_limitations)
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_run_id", validated_run_id)
        object.__setattr__(self, "_limitations", validated_limitations)
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "_replay_store", replay_store)
        object.__setattr__(self, "_frozen", True)

    def freeze_discovery_requests(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> DailyMedRequestProjection:
        """Construct the complete exact discovery tuple from the governed request."""

        CanonicalDailyMedProjectionAuthority._validate_context(self, task, scope, attempt)
        requests = tuple(
            DailyMedDiscoveryRequest(
                selection_request=item,
                query_id=derive_identity(
                    "dailymed-discovery-query",
                    {
                        "run_id": self._run_id,
                        "scope_id": scope.scope_id,
                        "request": item,
                    },
                ),
            )
            for item in self._request.dailymed_selection_requests
        )
        return DailyMedRequestProjection(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            requests=requests,
        )

    def project_discovery(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        request: DailyMedDiscoveryRequest,
        response: DailyMedDiscoveryResponse,
    ) -> DailyMedDiscoveryExecutionProjection:
        """Bind the authoritative tool response to persisted provenance only."""

        CanonicalDailyMedProjectionAuthority._validate_context(self, task, scope, attempt)
        request = DailyMedDiscoveryRequest.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        response = DailyMedDiscoveryResponse.model_validate(
            response.model_dump(mode="python"), strict=True
        )
        if (
            request
            not in self.freeze_discovery_requests(task=task, scope=scope, attempt=attempt).requests
        ):
            raise ValueError("DailyMed discovery is outside the governed request tuple")
        raw = self._provenance.load_discovery(request=request, response=response)
        if type(raw) is not DailyMedDiscoveryProvenanceProjection:
            raise ValueError("DailyMed discovery provenance returned a noncanonical type")
        persisted = DailyMedDiscoveryProvenanceProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_persisted_context(persisted, task, scope, attempt, self._run_id)
        acquisition = persisted.acquisition
        if (
            acquisition.query_id != response.query_id
            or acquisition.source_outcome_id != response.source_outcome_id
            or acquisition.snapshot_id != response.candidate_set_snapshot_id
        ):
            raise ValueError("DailyMed discovery persisted provenance drift")
        record = DailyMedDiscoveryExecutionProjection(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            response=response,
            acquisition=acquisition,
        )
        stored = self._replay_store.persist_discovery(record)
        if type(stored) is not DailyMedDiscoveryExecutionProjection:
            raise ValueError("DailyMed replay store returned a noncanonical discovery")
        stored = DailyMedDiscoveryExecutionProjection.model_validate(
            stored.model_dump(mode="python"), strict=True
        )
        if stored != record:
            raise ValueError("DailyMed replay store changed the discovery record")
        return stored

    def freeze_fetch_request(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        discovery: DailyMedDiscoveryExecutionProjection,
    ) -> DailyMedFetchRequest:
        """Derive the exact fetch solely from the authoritative selected response."""

        self._validate_context(task, scope, attempt)
        discovery = DailyMedDiscoveryExecutionProjection.model_validate(
            discovery.model_dump(mode="python"), strict=True
        )
        response = discovery.response
        if response.selection_status is not LabelSelectionStatus.SELECTED:
            raise ValueError("DailyMed fetch requires an authoritative selected discovery")
        selected = (
            response.decision_id,
            response.selected_candidate_id,
            response.selected_setid,
            response.selected_spl_version,
        )
        if any(item is None for item in selected):
            raise ValueError("selected DailyMed discovery lacks its exact fetch identity")
        decision_id, candidate_id, setid, spl_version = selected
        assert decision_id is not None
        assert candidate_id is not None
        assert setid is not None
        assert spl_version is not None
        return DailyMedFetchRequest(
            selection_request=response.selection_request,
            query_id=response.query_id,
            decision_id=decision_id,
            selected_candidate_id=candidate_id,
            selected_setid=setid,
            selected_spl_version=spl_version,
        )

    def project_fetch(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        request: DailyMedFetchRequest,
        response: DailyMedFetchResponse,
    ) -> DailyMedFetchExecutionProjection:
        """Bind the exact fetch response to persisted section identities only."""

        self._validate_context(task, scope, attempt)
        request = DailyMedFetchRequest.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        response = DailyMedFetchResponse.model_validate(
            response.model_dump(mode="python"), strict=True
        )
        if response.request != request:
            raise ValueError("DailyMed fetch provenance request drift")
        raw = self._provenance.load_fetch(request=request, response=response)
        if type(raw) is not DailyMedFetchProvenanceProjection:
            raise ValueError("DailyMed fetch provenance returned a noncanonical type")
        persisted = DailyMedFetchProvenanceProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_persisted_context(persisted, task, scope, attempt, self._run_id)
        acquisition = persisted.acquisition
        if (
            acquisition.query_id != response.request.query_id
            or acquisition.source_outcome_id != response.source_outcome_id
            or acquisition.snapshot_id != response.fetch_snapshot_id
            or tuple(item.section_id for item in persisted.section_evidence) != response.section_ids
        ):
            raise ValueError("DailyMed fetch persisted provenance drift")
        record = DailyMedFetchExecutionProjection(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            response=response,
            acquisition=acquisition,
            section_evidence=persisted.section_evidence,
        )
        stored = self._replay_store.persist_fetch(record)
        if type(stored) is not DailyMedFetchExecutionProjection:
            raise ValueError("DailyMed replay store returned a noncanonical fetch")
        stored = DailyMedFetchExecutionProjection.model_validate(
            stored.model_dump(mode="python"), strict=True
        )
        if stored != record:
            raise ValueError("DailyMed replay store changed the fetch record")
        return stored

    def reconstruct_fetch_request(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        operation: RequiredSourceOperation,
    ) -> DailyMedFetchRequest:
        """Reconstruct one checkpointed fetch solely from governed typed refs."""

        CanonicalDailyMedProjectionAuthority._validate_context(self, task, scope, attempt)
        operation = RequiredSourceOperation.model_validate(
            operation.model_dump(mode="python"), strict=True
        )
        discovery_result = next(
            (
                item
                for item in task.operation_results
                if item.operation.kind is SourceOperationKind.DAILYMED_DISCOVERY
                and item.operation.query_id == operation.query_id
            ),
            None,
        )
        if operation.kind is not SourceOperationKind.DAILYMED_FETCH or discovery_result is None:
            raise ValueError("checkpointed DailyMed fetch lacks its governed discovery")
        discovery = CanonicalDailyMedProjectionAuthority._reload_discovery(
            self, task, scope, attempt, discovery_result
        )
        if (
            discovery.acquisition.acquisition_intent_id
            != discovery_result.acquisition.acquisition_intent_id
            or discovery.response.source_outcome != discovery_result.outcome
            or discovery.response.candidate_set_snapshot_id
            != discovery_result.acquisition.snapshot_id
        ):
            raise ValueError("DailyMed durable discovery progress drift")
        expected = CanonicalDailyMedProjectionAuthority.freeze_fetch_request(
            self,
            task=task,
            scope=scope,
            attempt=attempt,
            discovery=discovery,
        )
        expected_operation = _dailymed_fetch_operations(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            ordinal_base=operation.ordinal,
            requests=(expected,),
        )[0]
        if expected_operation != operation:
            raise ValueError("checkpointed DailyMed fetch suffix differs from persisted selection")
        return expected

    def project_terminal(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        required_operations: tuple[RequiredSourceOperation, ...],
        operation_results: tuple[TerminalSourceOperationResult, ...],
    ) -> SourceTaskTerminalProjection:
        """Own all DailyMed terminal outcome business metadata."""

        self._validate_context(task, scope, attempt)
        return _canonical_terminal_projection(
            run_id=self._run_id,
            task=task,
            scope=scope,
            attempt=attempt,
            operations=required_operations,
            results=operation_results,
            limitations=self._limitations,
        )

    def validate_terminal_task(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
    ) -> None:
        """Replay a DailyMed terminal task from durable provenance without source I/O."""

        task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        if task.status is not SourceTaskStatus.TERMINAL or not task.operation_results:
            raise ValueError("DailyMed terminal replay requires a terminal task")
        attempt = task.operation_results[0].attempt
        CanonicalDailyMedProjectionAuthority._validate_context(self, task, scope, attempt)
        discovery_requests = CanonicalDailyMedProjectionAuthority.freeze_discovery_requests(
            self, task=task, scope=scope, attempt=attempt
        ).requests
        discovery_operations = _dailymed_operations_from_requests(
            self._run_id, scope.scope_id, discovery_requests
        )
        if task.required_operations[: len(discovery_operations)] != discovery_operations:
            raise ValueError("DailyMed terminal discovery plan drift")
        persisted_discoveries: list[DailyMedDiscoveryExecutionProjection] = []
        expected_results: list[TerminalSourceOperationResult] = []
        for operation, request, actual in zip(
            discovery_operations,
            discovery_requests,
            task.operation_results[: len(discovery_operations)],
            strict=True,
        ):
            persisted = CanonicalDailyMedProjectionAuthority._reload_discovery(
                self, task, scope, attempt, actual
            )
            if persisted.response.selection_request != request.selection_request or (
                persisted.response.query_id != request.query_id
            ):
                raise ValueError("DailyMed terminal discovery request drift")
            persisted_discoveries.append(persisted)
            expected_results.append(
                _operation_result(
                    operation,
                    attempt,
                    persisted.acquisition.acquisition_intent_id,
                    persisted.response.source_outcome,
                    persisted.response.candidate_set_snapshot_id,
                )
            )
        selected = tuple(
            item
            for item in persisted_discoveries
            if item.response.selection_status is LabelSelectionStatus.SELECTED
        )
        fetch_requests = tuple(
            CanonicalDailyMedProjectionAuthority.freeze_fetch_request(
                self,
                task=task,
                scope=scope,
                attempt=attempt,
                discovery=item,
            )
            for item in selected
        )
        expected_operations = (
            *discovery_operations,
            *_dailymed_fetch_operations(
                run_id=self._run_id,
                scope_id=scope.scope_id,
                ordinal_base=len(discovery_operations),
                requests=fetch_requests,
            ),
        )
        if task.required_operations != expected_operations:
            raise ValueError("DailyMed terminal fetch suffix drift")
        for operation, fetch_request, actual in zip(
            expected_operations[len(discovery_operations) :],
            fetch_requests,
            task.operation_results[len(discovery_operations) :],
            strict=True,
        ):
            persisted_fetch = CanonicalDailyMedProjectionAuthority._reload_fetch(
                self, task, scope, attempt, actual
            )
            if persisted_fetch.response.request != fetch_request:
                raise ValueError("DailyMed terminal fetch request drift")
            expected_results.append(
                _dailymed_fetch_operation_result(operation, attempt, persisted_fetch)
            )
        _require_exact_terminal_task(
            task=task,
            scope=scope,
            attempt=attempt,
            operations=expected_operations,
            results=tuple(expected_results),
            limitations=self._limitations,
        )

    def _reload_discovery(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        actual: TerminalSourceOperationResult,
    ) -> DailyMedDiscoveryExecutionProjection:
        try:
            raw = self._replay_store.load_discovery(
                acquisition_intent_id=actual.acquisition.acquisition_intent_id,
                run_id=self._run_id,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
                query_id=actual.operation.query_id,
            )
        except LookupError as error:
            raise ValueError("DailyMed durable discovery progress is missing") from error
        if type(raw) is not DailyMedDiscoveryExecutionProjection:
            raise ValueError("DailyMed durable discovery progress is noncanonical")
        persisted = DailyMedDiscoveryExecutionProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_execution_projection(
            persisted,
            persisted.response,
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=self._run_id,
        )
        return persisted

    def _reload_fetch(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        actual: TerminalSourceOperationResult,
    ) -> DailyMedFetchExecutionProjection:
        try:
            raw = self._replay_store.load_fetch(
                acquisition_intent_id=actual.acquisition.acquisition_intent_id,
                run_id=self._run_id,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
                query_id=actual.operation.query_id,
            )
        except LookupError as error:
            raise ValueError("DailyMed durable fetch progress is missing") from error
        if type(raw) is not DailyMedFetchExecutionProjection:
            raise ValueError("DailyMed durable fetch progress is noncanonical")
        persisted = DailyMedFetchExecutionProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_execution_projection(
            persisted,
            persisted.response,
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=self._run_id,
        )
        return persisted

    def _validate_context(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> None:
        if scope != self._request.scope or (
            task.task_id != source_task_id(self._run_id, SourceType.DAILYMED)
            or task.source is not SourceType.DAILYMED
            or attempt.task_id != task.task_id
        ):
            raise ValueError("canonical DailyMed authority context is foreign or stale")


@final
class CanonicalFaersProjectionAuthority:
    """Sealed production authority for exact FAERS request and task projection."""

    _frozen: bool
    _provenance: FaersPersistedProvenancePort
    _replay_store: FaersReplayStorePort
    _request: M1BResearchRequestV1
    _run_id: RunId

    __slots__ = ("_frozen", "_provenance", "_replay_store", "_request", "_run_id")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalFaersProjectionAuthority is sealed")

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("CanonicalFaersProjectionAuthority is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        *,
        request: M1BResearchRequestV1,
        run_id: RunId,
        provenance: FaersPersistedProvenancePort,
        replay_store: FaersReplayStorePort,
    ) -> None:
        request = M1BResearchRequestV1.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        validated_run_id: RunId = TypeAdapter(RunId).validate_python(run_id, strict=True)
        if SourceType.FAERS not in request.requested_sources:
            raise ValueError("canonical FAERS authority requires FAERS requested")
        object.__setattr__(self, "_request", request)
        object.__setattr__(self, "_run_id", validated_run_id)
        object.__setattr__(self, "_provenance", provenance)
        object.__setattr__(self, "_replay_store", replay_store)
        object.__setattr__(self, "_frozen", True)

    def freeze_requests(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> FaersRequestProjection:
        """Return the exact canonical aggregate tuple from the governed request."""

        CanonicalFaersProjectionAuthority._validate_context(self, task, scope, attempt)
        return FaersRequestProjection(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            requests=self._request.faers_query_requests,
        )

    def project_execution(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        execution: FaersAggregateExecution,
    ) -> FaersAggregateExecutionProjection:
        """Bind the exact persisted execution to content-only provenance."""

        self._validate_context(task, scope, attempt)
        execution = FaersAggregateExecution.model_validate(
            execution.model_dump(mode="python"), strict=True
        )
        if execution.request not in self._request.faers_query_requests:
            raise ValueError("FAERS execution is outside the governed request tuple")
        raw = self._provenance.load_aggregate(execution=execution)
        if type(raw) is not FaersAggregateProvenanceProjection:
            raise ValueError("FAERS provenance returned a noncanonical type")
        persisted = FaersAggregateProvenanceProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_persisted_context(persisted, task, scope, attempt, self._run_id)
        result = execution.result
        if (
            persisted.query_id != result.query.query_id
            or persisted.snapshot_id != result.snapshot_id
            or persisted.manifest_id != result.manifest_id
            or tuple(item.bucket_ordinal for item in persisted.bucket_evidence)
            != tuple(item.bucket_ordinal for item in result.buckets)
        ):
            raise ValueError("FAERS persisted provenance drift")
        record = FaersAggregateExecutionProjection(
            run_id=self._run_id,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            execution=execution,
            bucket_evidence=persisted.bucket_evidence,
        )
        stored = self._replay_store.persist_aggregate(record)
        if type(stored) is not FaersAggregateExecutionProjection:
            raise ValueError("FAERS replay store returned a noncanonical aggregate")
        stored = FaersAggregateExecutionProjection.model_validate(
            stored.model_dump(mode="python"), strict=True
        )
        if stored != record:
            raise ValueError("FAERS replay store changed the aggregate record")
        return stored

    def project_terminal(
        self,
        *,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        required_operations: tuple[RequiredSourceOperation, ...],
        operation_results: tuple[TerminalSourceOperationResult, ...],
    ) -> SourceTaskTerminalProjection:
        """Own all FAERS terminal outcome business metadata."""

        self._validate_context(task, scope, attempt)
        return _canonical_terminal_projection(
            run_id=self._run_id,
            task=task,
            scope=scope,
            attempt=attempt,
            operations=required_operations,
            results=operation_results,
            limitations=FAERS_MANDATORY_LIMITATIONS,
        )

    def validate_terminal_task(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
    ) -> None:
        """Replay a FAERS terminal task from durable provenance without source I/O."""

        task = SourceTaskState.model_validate(task.model_dump(mode="python"), strict=True)
        scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
        if task.status is not SourceTaskStatus.TERMINAL or not task.operation_results:
            raise ValueError("FAERS terminal replay requires a terminal task")
        attempt = task.operation_results[0].attempt
        CanonicalFaersProjectionAuthority._validate_context(self, task, scope, attempt)
        operations = _faers_operations_from_requests(
            self._run_id,
            scope.scope_id,
            self._request.faers_query_requests,
        )
        if task.required_operations != operations:
            raise ValueError("FAERS terminal operation plan drift")
        expected_results: list[TerminalSourceOperationResult] = []
        for operation, request, actual in zip(
            operations,
            self._request.faers_query_requests,
            task.operation_results,
            strict=True,
        ):
            persisted = CanonicalFaersProjectionAuthority._reload_aggregate(
                self, task, scope, attempt, actual
            )
            if persisted.execution.request != request:
                raise ValueError("FAERS terminal request drift")
            expected_results.append(_faers_operation_result(operation, attempt, persisted))
        _require_exact_terminal_task(
            task=task,
            scope=scope,
            attempt=attempt,
            operations=operations,
            results=tuple(expected_results),
            limitations=FAERS_MANDATORY_LIMITATIONS,
        )

    def _reload_aggregate(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        actual: TerminalSourceOperationResult,
    ) -> FaersAggregateExecutionProjection:
        try:
            raw = self._replay_store.load_aggregate(
                acquisition_intent_id=actual.acquisition.acquisition_intent_id,
                run_id=self._run_id,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
                query_id=actual.operation.query_id,
            )
        except LookupError as error:
            raise ValueError("FAERS durable aggregate progress is missing") from error
        if type(raw) is not FaersAggregateExecutionProjection:
            raise ValueError("FAERS durable aggregate progress is noncanonical")
        persisted = FaersAggregateExecutionProjection.model_validate(
            raw.model_dump(mode="python"), strict=True
        )
        _validate_execution_projection(
            persisted,
            persisted.execution,
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=self._run_id,
        )
        return persisted

    def _validate_context(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> None:
        if scope != self._request.scope or (
            task.task_id != source_task_id(self._run_id, SourceType.FAERS)
            or task.source is not SourceType.FAERS
            or attempt.task_id != task.task_id
        ):
            raise ValueError("canonical FAERS authority context is foreign or stale")


def _dailymed_operations_from_requests(
    run_id: RunId,
    scope_id: StableWorkflowId,
    requests: tuple[DailyMedDiscoveryRequest, ...],
) -> tuple[RequiredSourceOperation, ...]:
    requests = tuple(
        DailyMedDiscoveryRequest.model_validate(item.model_dump(mode="python")) for item in requests
    )
    return tuple(
        required_source_operation(
            run_id=run_id,
            scope_id=scope_id,
            source=SourceType.DAILYMED,
            ordinal=ordinal,
            kind=SourceOperationKind.DAILYMED_DISCOVERY,
            query_id=request.query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.REQUEST,
                    value=derive_identity("dailymed-discovery-request", request),
                ),
            ),
        )
        for ordinal, request in enumerate(requests)
    )


def _faers_operations_from_requests(
    run_id: RunId,
    scope_id: StableWorkflowId,
    requests: tuple[FaersAggregateRequestV1, ...],
) -> tuple[RequiredSourceOperation, ...]:
    requests = tuple(
        FaersAggregateRequestV1.model_validate(item.model_dump(mode="python")) for item in requests
    )
    return tuple(
        required_source_operation(
            run_id=run_id,
            scope_id=scope_id,
            source=SourceType.FAERS,
            ordinal=ordinal,
            kind=SourceOperationKind.FAERS_AGGREGATE,
            query_id=FaersAggregateQueryV1.create(request).query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.REQUEST,
                    value=derive_identity("faers-aggregate-request", request),
                ),
            ),
        )
        for ordinal, request in enumerate(requests)
    )


def plan_dailymed_operations(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: DailyMedCapabilityProjectionPort,
) -> tuple[RequiredSourceOperation, ...]:
    """Freeze and validate the complete DailyMed discovery prefix without source I/O."""

    return _prepare_dailymed_plan(task, scope, attempt, projection=projection)[-1]


def plan_faers_operations(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: FaersCapabilityProjectionPort,
) -> tuple[RequiredSourceOperation, ...]:
    """Freeze and validate the complete FAERS operation plan without source I/O."""

    return _prepare_faers_plan(task, scope, attempt, projection=projection)[-1]


def collect_dailymed_capability(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: DailyMedCapabilityProjectionPort,
    execution: DailyMedExecutionPort,
) -> CollectedEvidenceResult | SourceTaskProgressResult:
    """Execute exactly one durable DailyMed discovery or fetch stage."""

    task, scope, attempt, run_id, frozen, discovery_plan = _prepare_dailymed_plan(
        task,
        scope,
        attempt,
        projection=projection,
    )
    if task.status is not SourceTaskStatus.RUNNING:
        raise ValueError("DailyMed collection requires a planned running task")

    if task.operation_results:
        if tuple(item.operation for item in task.operation_results) != discovery_plan or len(
            task.required_operations
        ) <= len(discovery_plan):
            raise ValueError("DailyMed resumed fetch stage requires exact discovery progress")
        fetch_operations = task.required_operations[len(discovery_plan) :]
        fetch_requests = tuple(
            DailyMedFetchRequest.model_validate(
                projection.reconstruct_fetch_request(
                    task=task,
                    scope=scope,
                    attempt=attempt,
                    operation=operation,
                ).model_dump(mode="python"),
                strict=True,
            )
            for operation in fetch_operations
        )
        fetch_results = _execute_dailymed_fetch_suffix(
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=run_id,
            operations=fetch_operations,
            requests=fetch_requests,
            projection=projection,
            execution=execution,
        )
        final_operations = task.required_operations
        final_results = (*task.operation_results, *fetch_results)
    else:
        discovery_results: list[TerminalSourceOperationResult] = []
        selected: list[tuple[DailyMedDiscoveryRequest, DailyMedDiscoveryExecutionProjection]] = []
        for discovery_operation, request in zip(discovery_plan, frozen.requests, strict=True):
            response = discover_dailymed_labels(request, execution=execution)
            discovery = DailyMedDiscoveryExecutionProjection.model_validate(
                projection.project_discovery(
                    task=task,
                    scope=scope,
                    attempt=attempt,
                    request=request,
                    response=response,
                ).model_dump(mode="python"),
                strict=True,
            )
            _validate_execution_projection(
                discovery,
                response,
                task=task,
                scope=scope,
                attempt=attempt,
                run_id=run_id,
            )
            discovery_results.append(
                _operation_result(
                    discovery_operation,
                    attempt,
                    discovery.acquisition.acquisition_intent_id,
                    discovery.response.source_outcome,
                    discovery.response.candidate_set_snapshot_id,
                )
            )
            if discovery.response.selection_status is LabelSelectionStatus.SELECTED:
                selected.append((request, discovery))

        frozen_fetches = tuple(
            DailyMedFetchRequest.model_validate(
                projection.freeze_fetch_request(
                    task=task,
                    scope=scope,
                    attempt=attempt,
                    discovery=discovery,
                ).model_dump(mode="python"),
                strict=True,
            )
            for _request, discovery in selected
        )
        for (request, discovery), fetch_request in zip(selected, frozen_fetches, strict=True):
            _validate_fetch_request(request, discovery, fetch_request)
        fetch_operations = _dailymed_fetch_operations(
            run_id=run_id,
            scope_id=scope.scope_id,
            ordinal_base=len(discovery_plan),
            requests=frozen_fetches,
        )
        final_operations = (*discovery_plan, *fetch_operations)
        final_results = tuple(discovery_results)
        validate_required_operation_plan(SourceType.DAILYMED, final_operations)
        if fetch_operations:
            return SourceTaskProgressResult(
                attempt=attempt,
                required_operations=final_operations,
                operation_results=final_results,
            )

    terminal = projection.project_terminal(
        task=task,
        scope=scope,
        attempt=attempt,
        required_operations=final_operations,
        operation_results=final_results,
    )
    return _finish_collection(
        task=task,
        scope=scope,
        attempt=attempt,
        run_id=run_id,
        operations=final_operations,
        results=final_results,
        terminal=terminal,
    )


def _dailymed_fetch_operations(
    *,
    run_id: RunId,
    scope_id: StableWorkflowId,
    ordinal_base: int,
    requests: tuple[DailyMedFetchRequest, ...],
) -> tuple[RequiredSourceOperation, ...]:
    return tuple(
        required_source_operation(
            run_id=run_id,
            scope_id=scope_id,
            source=SourceType.DAILYMED,
            ordinal=ordinal_base + offset,
            kind=SourceOperationKind.DAILYMED_FETCH,
            query_id=request.query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.DAILYMED_DECISION,
                    value=request.decision_id,
                ),
                SourceOperationInputRef(
                    role=SourceOperationInputRole.CANDIDATE,
                    value=request.selected_candidate_id,
                ),
                SourceOperationInputRef(
                    role=SourceOperationInputRole.SETID,
                    value=request.selected_setid,
                ),
                SourceOperationInputRef(
                    role=SourceOperationInputRole.SPL_VERSION,
                    value=request.selected_spl_version,
                ),
            ),
        )
        for offset, request in enumerate(requests)
    )


def _execute_dailymed_fetch_suffix(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: RunId,
    operations: tuple[RequiredSourceOperation, ...],
    requests: tuple[DailyMedFetchRequest, ...],
    projection: DailyMedCapabilityProjectionPort,
    execution: DailyMedExecutionPort,
) -> tuple[TerminalSourceOperationResult, ...]:
    results: list[TerminalSourceOperationResult] = []
    for operation, request in zip(operations, requests, strict=True):
        response = fetch_dailymed_label(request, execution=execution)
        fetched = DailyMedFetchExecutionProjection.model_validate(
            projection.project_fetch(
                task=task,
                scope=scope,
                attempt=attempt,
                request=request,
                response=response,
            ).model_dump(mode="python"),
            strict=True,
        )
        _validate_execution_projection(
            fetched,
            response,
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=run_id,
        )
        results.append(_dailymed_fetch_operation_result(operation, attempt, fetched))
    return tuple(results)


def collect_faers_capability(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: FaersCapabilityProjectionPort,
    execution: FaersExecutionPort,
    persistence: FaersPersistencePort,
) -> CollectedEvidenceResult:
    """Execute one to eight exact narrative-free FAERS aggregate operations."""

    task, scope, attempt, run_id, frozen, operations = _prepare_faers_plan(
        task,
        scope,
        attempt,
        projection=projection,
    )
    if task.status is not SourceTaskStatus.RUNNING:
        raise ValueError("FAERS collection requires a planned running task")

    results: list[TerminalSourceOperationResult] = []
    for operation, request in zip(operations, frozen.requests, strict=True):
        executed = execute_faers_aggregate(
            request,
            execution=execution,
            persistence=persistence,
        )
        projected = FaersAggregateExecutionProjection.model_validate(
            projection.project_execution(
                task=task,
                scope=scope,
                attempt=attempt,
                execution=executed,
            ).model_dump(mode="python")
        )
        _validate_execution_projection(
            projected,
            executed,
            task=task,
            scope=scope,
            attempt=attempt,
            run_id=run_id,
        )
        results.append(_faers_operation_result(operation, attempt, projected))
    final_results = tuple(results)
    terminal = projection.project_terminal(
        task=task,
        scope=scope,
        attempt=attempt,
        required_operations=operations,
        operation_results=final_results,
    )
    return _finish_collection(
        task=task,
        scope=scope,
        attempt=attempt,
        run_id=run_id,
        operations=operations,
        results=final_results,
        terminal=terminal,
    )


def _prepare_dailymed_plan(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: DailyMedCapabilityProjectionPort,
) -> tuple[
    SourceTaskState,
    ResearchScope,
    SourceTaskAttemptRef,
    RunId,
    DailyMedRequestProjection,
    tuple[RequiredSourceOperation, ...],
]:
    task = SourceTaskState.model_validate(task.model_dump(mode="python"))
    scope = ResearchScope.model_validate(scope.model_dump(mode="python"))
    attempt = SourceTaskAttemptRef.model_validate(attempt.model_dump(mode="python"))
    _validate_plan_context(task, scope, attempt, source=SourceType.DAILYMED)
    frozen = DailyMedRequestProjection.model_validate(
        projection.freeze_discovery_requests(task=task, scope=scope, attempt=attempt).model_dump(
            mode="python"
        )
    )
    run_id = frozen.run_id
    _validate_projection_binding(frozen, task, scope, attempt, run_id)
    scope_drug_ids = {item.concept_id for item in scope.drugs}
    if any(
        item.selection_request.drug_concept_id not in scope_drug_ids for item in frozen.requests
    ):
        raise ValueError("DailyMed projected request contains a foreign scope drug")
    operations = _dailymed_operations_from_requests(run_id, scope.scope_id, frozen.requests)
    if task.required_operations and (task.required_operations[: len(operations)] != operations):
        raise ValueError("DailyMed request tuple differs from the pre-execution task plan")
    return task, scope, attempt, run_id, frozen, operations


def _prepare_faers_plan(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    projection: FaersCapabilityProjectionPort,
) -> tuple[
    SourceTaskState,
    ResearchScope,
    SourceTaskAttemptRef,
    RunId,
    FaersRequestProjection,
    tuple[RequiredSourceOperation, ...],
]:
    task = SourceTaskState.model_validate(task.model_dump(mode="python"))
    scope = ResearchScope.model_validate(scope.model_dump(mode="python"))
    attempt = SourceTaskAttemptRef.model_validate(attempt.model_dump(mode="python"))
    _validate_plan_context(task, scope, attempt, source=SourceType.FAERS)
    frozen = FaersRequestProjection.model_validate(
        projection.freeze_requests(task=task, scope=scope, attempt=attempt).model_dump(
            mode="python"
        )
    )
    run_id = frozen.run_id
    _validate_projection_binding(frozen, task, scope, attempt, run_id)
    scope_drug_ids = {item.concept_id for item in scope.drugs}
    if any(item.drug_concept_id not in scope_drug_ids for item in frozen.requests):
        raise ValueError("FAERS projected request contains a foreign scope drug")
    operations = _faers_operations_from_requests(run_id, scope.scope_id, frozen.requests)
    if task.required_operations and task.required_operations != operations:
        raise ValueError("FAERS request tuple differs from the pre-execution task plan")
    return task, scope, attempt, run_id, frozen, operations


def _validate_plan_context(
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    *,
    source: SourceType,
) -> None:
    if (
        source not in scope.selected_sources
        or task.source is not source
        or attempt.task_id != task.task_id
    ):
        raise ValueError("source capability context is foreign or stale")
    if task.status is SourceTaskStatus.PENDING:
        if task.attempts != 0 or attempt.attempt_number != 1:
            raise ValueError("pending source planning requires the first exact attempt")
    elif task.status is SourceTaskStatus.RUNNING:
        if task.active_attempt != attempt or task.attempts != attempt.attempt_number:
            raise ValueError("running source planning requires the exact active attempt")
    else:
        raise ValueError("source operation planning requires pending or running state")
    if task.operation_results and not (
        source is SourceType.DAILYMED and task.status is SourceTaskStatus.RUNNING
    ):
        raise ValueError("only running DailyMed tasks may retain progress results")
    if task.terminal_outcome_ref is not None or task.evidence_refs:
        raise ValueError("source operation planning requires an unpopulated task")


def _validate_projection_binding(
    projection: DailyMedRequestProjection | FaersRequestProjection,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: RunId,
) -> None:
    if (
        projection.run_id != run_id
        or projection.scope_id != scope.scope_id
        or projection.task_id != task.task_id
        or projection.attempt_id != attempt.attempt_id
        or task.task_id != source_task_id(run_id, task.source)
    ):
        raise ValueError("request projection is foreign or stale")


def _validate_execution_projection(
    projection: (
        DailyMedDiscoveryExecutionProjection
        | DailyMedFetchExecutionProjection
        | FaersAggregateExecutionProjection
    ),
    expected: DailyMedDiscoveryResponse | DailyMedFetchResponse | FaersAggregateExecution,
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: RunId,
) -> None:
    if isinstance(projection, FaersAggregateExecutionProjection):
        if projection.execution != expected:
            raise ValueError("execution projection is foreign or stale")
        acquisition = projection.execution.acquisition_outcome_ref
    else:
        if projection.response != expected:
            raise ValueError("execution projection is foreign or stale")
        acquisition = projection.acquisition
    if (
        projection.run_id != run_id
        or projection.scope_id != scope.scope_id
        or projection.task_id != task.task_id
        or projection.attempt_id != attempt.attempt_id
        or acquisition.run_id != run_id
    ):
        raise ValueError("execution projection is foreign or stale")


def _validate_fetch_request(
    discovery_request: DailyMedDiscoveryRequest,
    discovery: DailyMedDiscoveryExecutionProjection,
    fetch: DailyMedFetchRequest,
) -> None:
    response = discovery.response
    expected = (
        discovery_request.selection_request,
        discovery_request.query_id,
        response.decision_id,
        response.selected_candidate_id,
        response.selected_setid,
        response.selected_spl_version,
    )
    actual = (
        fetch.selection_request,
        fetch.query_id,
        fetch.decision_id,
        fetch.selected_candidate_id,
        fetch.selected_setid,
        fetch.selected_spl_version,
    )
    if actual != expected:
        raise ValueError("DailyMed fetch request differs from the selected discovery path")


def _operation_result(
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
    acquisition_intent_id: str,
    outcome: SourceOutcome,
    snapshot_id: str,
) -> TerminalSourceOperationResult:
    acquisition = source_operation_acquisition(
        operation=operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=acquisition_intent_id,
        outcome=outcome,
        snapshot_id=snapshot_id,
    )
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=acquisition,
        outcome=outcome,
    )


def _dailymed_fetch_operation_result(
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
    persisted: DailyMedFetchExecutionProjection,
) -> TerminalSourceOperationResult:
    acquisition = source_operation_acquisition(
        operation=operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=persisted.acquisition.acquisition_intent_id,
        outcome=persisted.response.source_outcome,
        snapshot_id=persisted.response.fetch_snapshot_id,
    )
    observations = tuple(
        source_operation_observation(
            operation=operation,
            acquisition=acquisition,
            evidence_id=item.evidence_id,
            content_hash=item.content_hash,
            locator_ref=item.locator_ref,
        )
        for item in persisted.section_evidence
    )
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=acquisition,
        outcome=persisted.response.source_outcome,
        observations=observations,
    )


def _faers_operation_result(
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
    persisted: FaersAggregateExecutionProjection,
) -> TerminalSourceOperationResult:
    outcome = _faers_policy_outcome(persisted.execution.result.source_outcome)
    acquisition = source_operation_acquisition(
        operation=operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=(persisted.execution.acquisition_outcome_ref.acquisition_intent_id),
        outcome=outcome,
        snapshot_id=persisted.execution.result.snapshot_id,
    )
    observations = tuple(
        source_operation_observation(
            operation=operation,
            acquisition=acquisition,
            evidence_id=item.evidence_id,
            content_hash=item.content_hash,
            locator_ref=item.locator_ref,
        )
        for item in persisted.bucket_evidence
    )
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=acquisition,
        outcome=outcome,
        observations=observations,
    )


def _faers_policy_outcome(outcome: SourceOutcome) -> SourceOutcome:
    values = outcome.model_dump(mode="python")
    values["warning_codes"] = tuple(sorted({*outcome.warning_codes, FAERS_MANDATORY_WARNING}))
    return SourceOutcome.model_validate(values)


def _validate_persisted_context(
    persisted: (
        DailyMedDiscoveryProvenanceProjection
        | DailyMedFetchProvenanceProjection
        | FaersAggregateProvenanceProjection
    ),
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: RunId,
) -> None:
    if (
        persisted.run_id != run_id
        or persisted.scope_id != scope.scope_id
        or persisted.task_id != task.task_id
        or persisted.attempt_id != attempt.attempt_id
    ):
        raise ValueError("persisted source provenance is foreign or stale")


def _canonical_terminal_projection(
    *,
    run_id: RunId,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    operations: tuple[RequiredSourceOperation, ...],
    results: tuple[TerminalSourceOperationResult, ...],
    limitations: tuple[LongText, ...],
) -> SourceTaskTerminalProjection:
    """Construct terminal metadata only from exact operations and child outcomes."""

    validate_required_operation_plan(task.source, operations)
    if not results:
        raise ValueError("terminal source projection requires child results")
    terminal_outcome = canonical_terminal_source_outcome(operations, results)
    representative = results[0].acquisition
    representative_operation = results[0].operation
    terminal_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity("source-task-terminal-outcome", terminal_outcome),
        operation_acquisition_ids=tuple(result.acquisition.acquisition_id for result in results),
        acquisition=AcquisitionOutcomeRef(
            run_id=run_id,
            source=task.source,
            acquisition_id=representative.acquisition_id,
            acquisition_intent_id=representative.acquisition_intent_id,
            acquisition_ordinal=representative.ordinal,
            operation=(
                "fetch"
                if representative_operation.kind is SourceOperationKind.DAILYMED_FETCH
                else "search"
            ),
            query_id=representative.query_id,
            source_outcome_id=representative.source_outcome_id,
            snapshot_id=representative.snapshot_id,
        ),
        outcome=terminal_outcome,
    )
    validate_source_limitations(task.source, limitations)
    return SourceTaskTerminalProjection(
        run_id=run_id,
        scope_id=scope.scope_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        terminal_outcome_ref=terminal_ref,
        limitations=limitations,
    )


def _require_exact_terminal_task(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    operations: tuple[RequiredSourceOperation, ...],
    results: tuple[TerminalSourceOperationResult, ...],
    limitations: tuple[LongText, ...],
) -> None:
    terminal = _canonical_terminal_projection(
        run_id=operations[0].run_id,
        task=task,
        scope=scope,
        attempt=attempt,
        operations=operations,
        results=results,
        limitations=limitations,
    )
    evidence_refs = tuple(
        observation.evidence_reference for result in results for observation in result.observations
    )
    expected = SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=operations,
        operation_results=results,
        status=SourceTaskStatus.TERMINAL,
        attempts=attempt.attempt_number,
        failure_history=task.failure_history,
        terminal_outcome_ref=terminal.terminal_outcome_ref,
        evidence_refs=evidence_refs,
        limitations=limitations,
    )
    if expected != task:
        raise ValueError("terminal source task differs from durable canonical replay")


def _finish_collection(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    run_id: RunId,
    operations: tuple[RequiredSourceOperation, ...],
    results: tuple[TerminalSourceOperationResult, ...],
    terminal: SourceTaskTerminalProjection,
) -> CollectedEvidenceResult:
    validate_required_operation_plan(task.source, operations)
    aggregate_source_operation_disposition(operations, results)
    terminal = SourceTaskTerminalProjection.model_validate(terminal.model_dump(mode="python"))
    if (
        terminal.run_id != run_id
        or terminal.scope_id != scope.scope_id
        or terminal.task_id != task.task_id
        or terminal.attempt_id != attempt.attempt_id
        or terminal.terminal_outcome_ref.acquisition.run_id != run_id
        or terminal.terminal_outcome_ref.outcome.source is not task.source
    ):
        raise ValueError("terminal source projection is foreign or stale")
    evidence_refs = tuple(
        observation.evidence_reference for result in results for observation in result.observations
    )
    return CollectedEvidenceResult(
        attempt=attempt,
        required_operations=operations,
        operation_results=results,
        terminal_outcome_ref=terminal.terminal_outcome_ref,
        evidence_refs=evidence_refs,
        limitations=terminal.limitations,
    )


__all__ = [
    "CanonicalDailyMedProjectionAuthority",
    "CanonicalFaersProjectionAuthority",
    "DailyMedCapabilityProjectionPort",
    "DailyMedPersistedProvenancePort",
    "DailyMedReplayStorePort",
    "DailyMedRequestProjection",
    "FaersCapabilityProjectionPort",
    "FaersPersistedProvenancePort",
    "FaersReplayStorePort",
    "FaersRequestProjection",
    "SourceTaskTerminalProjection",
    "collect_dailymed_capability",
    "collect_faers_capability",
    "plan_dailymed_operations",
    "plan_faers_operations",
]
