"""Deterministic projection of terminal source operations into one task outcome."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from medevidence.domain import (
    CoverageStatus,
    ExecutionStatus,
    ResultStatus,
    RunId,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.domain.identifiers import AcquisitionIntentId, DurableModel

from .contracts import (
    RequiredSourceOperation,
    SourceOperationAcquisitionRef,
    SourceOperationInputRef,
    SourceOperationKind,
    SourceOperationObservationRef,
    StableWorkflowId,
    TerminalSourceOperationResult,
    source_task_id,
    validate_required_operation_plan,
)


def _payload(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    return value


def required_source_operation(
    *,
    run_id: RunId,
    scope_id: StableWorkflowId,
    source: SourceType,
    ordinal: int,
    kind: SourceOperationKind,
    query_id: StableWorkflowId,
    input_refs: tuple[SourceOperationInputRef, ...],
) -> RequiredSourceOperation:
    """Construct one canonical required operation from primitive identities."""

    task_id = source_task_id(run_id, source)
    reconstructed_refs = tuple(
        SourceOperationInputRef.model_validate(_payload(item)) for item in input_refs
    )
    input_identity = derive_identity(
        "source-operation-input",
        {"kind": kind, "query_id": query_id, "input_refs": reconstructed_refs},
    )
    payload = {
        "run_id": run_id,
        "task_id": task_id,
        "scope_id": scope_id,
        "source": source,
        "ordinal": ordinal,
        "kind": kind,
        "query_id": query_id,
        "input_refs": reconstructed_refs,
        "input_identity": input_identity,
    }
    return RequiredSourceOperation(
        operation_id=derive_identity("source-operation", payload),
        run_id=run_id,
        task_id=task_id,
        scope_id=scope_id,
        source=source,
        ordinal=ordinal,
        kind=kind,
        query_id=query_id,
        input_refs=reconstructed_refs,
        input_identity=input_identity,
    )


def source_operation_acquisition(
    *,
    operation: RequiredSourceOperation,
    attempt_id: str,
    acquisition_intent_id: AcquisitionIntentId,
    outcome: SourceOutcome,
    snapshot_id: str,
) -> SourceOperationAcquisitionRef:
    """Construct an acquisition reference bound to exact operation outcome content."""

    operation = RequiredSourceOperation.model_validate(_payload(operation))
    outcome = SourceOutcome.model_validate(_payload(outcome))
    identity_payload = {
        "run_id": operation.run_id,
        "task_id": operation.task_id,
        "attempt_id": attempt_id,
        "acquisition_intent_id": acquisition_intent_id,
        "source": operation.source,
        "ordinal": operation.ordinal,
        "operation_id": operation.operation_id,
        "kind": operation.kind,
        "query_id": operation.query_id,
        "source_outcome_id": derive_identity("source-operation-outcome", outcome),
        "snapshot_id": snapshot_id,
    }
    return SourceOperationAcquisitionRef(
        acquisition_id=derive_identity("source-operation-acquisition", identity_payload),
        acquisition_intent_id=acquisition_intent_id,
        run_id=operation.run_id,
        task_id=operation.task_id,
        attempt_id=attempt_id,
        source=operation.source,
        ordinal=operation.ordinal,
        operation_id=operation.operation_id,
        kind=operation.kind,
        query_id=operation.query_id,
        source_outcome_id=derive_identity("source-operation-outcome", outcome),
        snapshot_id=snapshot_id,
    )


def source_operation_observation(
    *,
    operation: RequiredSourceOperation,
    acquisition: SourceOperationAcquisitionRef,
    evidence_id: str,
    content_hash: str,
    locator_ref: str,
) -> SourceOperationObservationRef:
    """Construct one content-free observation bound to its exact acquisition."""

    operation = RequiredSourceOperation.model_validate(_payload(operation))
    acquisition = SourceOperationAcquisitionRef.model_validate(_payload(acquisition))
    payload = {
        "run_id": operation.run_id,
        "task_id": operation.task_id,
        "attempt_id": acquisition.attempt_id,
        "source": operation.source,
        "ordinal": operation.ordinal,
        "operation_id": operation.operation_id,
        "query_id": operation.query_id,
        "acquisition_id": acquisition.acquisition_id,
        "snapshot_id": acquisition.snapshot_id,
        "evidence_id": evidence_id,
        "content_hash": content_hash,
        "locator_ref": locator_ref,
    }
    return SourceOperationObservationRef(
        observation_id=derive_identity("source-observation", payload),
        run_id=operation.run_id,
        task_id=operation.task_id,
        attempt_id=acquisition.attempt_id,
        source=operation.source,
        ordinal=operation.ordinal,
        operation_id=operation.operation_id,
        query_id=operation.query_id,
        acquisition_id=acquisition.acquisition_id,
        snapshot_id=acquisition.snapshot_id,
        evidence_id=evidence_id,
        content_hash=content_hash,
        locator_ref=locator_ref,
    )


class SourceTaskAggregateDisposition(DurableModel):
    """Only the four Owner-frozen dimensions shared across source adapters."""

    schema_version: Literal["m3.source-task-aggregate-disposition.v1"] = (
        "m3.source-task-aggregate-disposition.v1"
    )
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    warning_codes: tuple[str, ...]


def aggregate_source_operation_disposition(
    required_operations: tuple[RequiredSourceOperation, ...],
    operation_results: tuple[TerminalSourceOperationResult, ...],
) -> SourceTaskAggregateDisposition:
    """Recompute only the four Owner-frozen cross-source aggregate dimensions."""

    operations = tuple(
        RequiredSourceOperation.model_validate(_payload(item)) for item in required_operations
    )
    results = tuple(
        TerminalSourceOperationResult.model_validate(_payload(item)) for item in operation_results
    )
    source = operations[0].source if operations else None
    if source is None:
        raise ValueError("task aggregation requires at least one required operation")
    validate_required_operation_plan(source, operations)
    if tuple(item.operation for item in results) != operations:
        raise ValueError("terminal operation results must exactly equal the required plan")
    if len({item.attempt.attempt_id for item in results}) != 1:
        raise ValueError("terminal operation results must share one exact task attempt")
    outcomes = tuple(item.outcome for item in results)
    execution = (
        ExecutionStatus.FAILED
        if any(item.execution_status is ExecutionStatus.FAILED for item in outcomes)
        else ExecutionStatus.SUCCEEDED
    )
    if all(item.coverage_status is CoverageStatus.COMPLETE for item in outcomes):
        coverage = CoverageStatus.COMPLETE
    elif all(item.coverage_status is CoverageStatus.UNAVAILABLE for item in outcomes):
        coverage = CoverageStatus.UNAVAILABLE
    else:
        coverage = CoverageStatus.PARTIAL
    if any(item.result_status is ResultStatus.MATCHES for item in outcomes):
        result = ResultStatus.MATCHES
    elif all(
        item.execution_status is ExecutionStatus.SUCCEEDED
        and item.coverage_status is CoverageStatus.COMPLETE
        and item.result_status is ResultStatus.NO_MATCH
        for item in outcomes
    ):
        result = ResultStatus.NO_MATCH
    else:
        result = ResultStatus.INDETERMINATE

    warning_codes = tuple(sorted({code for item in outcomes for code in item.warning_codes}))
    return SourceTaskAggregateDisposition(
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        warning_codes=warning_codes,
    )


def canonical_terminal_source_outcome(
    required_operations: tuple[RequiredSourceOperation, ...],
    operation_results: tuple[TerminalSourceOperationResult, ...],
) -> SourceOutcome:
    """Reconstruct every terminal task-outcome field from bound child operations."""

    operations = tuple(
        RequiredSourceOperation.model_validate(_payload(item)) for item in required_operations
    )
    results = tuple(
        TerminalSourceOperationResult.model_validate(_payload(item)) for item in operation_results
    )
    aggregate = aggregate_source_operation_disposition(operations, results)
    bounds = results[0].outcome.configured_bounds
    if any(item.outcome.configured_bounds != bounds for item in results):
        raise ValueError("canonical terminal outcome requires one exact child bounds profile")
    source = operations[0].source
    if source is SourceType.PUBMED:
        search = next(
            item for item in results if item.operation.kind is SourceOperationKind.PUBMED_SEARCH
        )
        valid_result_count = sum(
            item.kind is SourceOperationKind.PUBMED_FETCH for item in operations
        )
        if search.outcome.valid_result_count != valid_result_count:
            raise ValueError("PubMed search candidate count must equal bound PMID fetch inputs")
        pages_completed = search.outcome.pages_completed
    elif source is SourceType.DAILYMED:
        matching_queries = {
            item.operation.query_id
            for item in results
            if item.outcome.result_status is ResultStatus.MATCHES
        }
        valid_result_count = sum(
            item.query_id in matching_queries
            for item in operations
            if item.kind is SourceOperationKind.DAILYMED_DISCOVERY
        )
        pages_completed = max(item.outcome.pages_completed for item in results)
    elif source is SourceType.FAERS:
        valid_result_count = sum(
            item.outcome.result_status is ResultStatus.MATCHES for item in results
        )
        pages_completed = max(item.outcome.pages_completed for item in results)
    else:
        search = next(
            item for item in results if item.operation.kind is SourceOperationKind.CADEC_SEARCH
        )
        valid_result_count = len(search.observations)
        if valid_result_count > 20:
            raise ValueError("canonical CADEC terminal outcome exceeds the top-20 bound")
        pages_completed = search.outcome.pages_completed
        if search.outcome.execution_status is ExecutionStatus.SUCCEEDED and pages_completed != 1:
            raise ValueError("successful CADEC search requires exactly one local search page")
    if aggregate.result_status is not ResultStatus.MATCHES:
        valid_result_count = 0
    failed_children = tuple(
        {
            "operation_id": item.operation.operation_id,
            "failure_id": item.outcome.failure_id,
        }
        for item in results
        if item.outcome.execution_status is ExecutionStatus.FAILED
    )
    failure_id = (
        derive_identity(
            "source-task-failure",
            {
                "run_id": operations[0].run_id,
                "task_id": operations[0].task_id,
                "attempt_id": results[0].attempt.attempt_id,
                "failed_children": failed_children,
            },
        )
        if failed_children
        else None
    )
    return SourceOutcome(
        source=source,
        query_id=derive_identity(
            "source-task-query",
            {
                "run_id": operations[0].run_id,
                "task_id": operations[0].task_id,
                "scope_id": operations[0].scope_id,
                "operation_input_identities": tuple(item.input_identity for item in operations),
            },
        ),
        execution_status=aggregate.execution_status,
        coverage_status=aggregate.coverage_status,
        result_status=aggregate.result_status,
        configured_bounds=bounds,
        valid_result_count=valid_result_count,
        pages_completed=pages_completed,
        truncated=any(item.outcome.truncated for item in results),
        warning_codes=aggregate.warning_codes,
        failure_id=failure_id,
    )


def validate_canonical_terminal_source_outcome(
    outcome: SourceOutcome,
    required_operations: tuple[RequiredSourceOperation, ...],
    operation_results: tuple[TerminalSourceOperationResult, ...],
) -> None:
    """Reject any adapter-supplied terminal field that differs from reconstruction."""

    reconstructed = SourceOutcome.model_validate(_payload(outcome))
    canonical = canonical_terminal_source_outcome(required_operations, operation_results)
    if reconstructed != canonical:
        raise ValueError("terminal source outcome must equal canonical child reconstruction")
