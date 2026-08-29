"""Tests for exact internal-operation planning and task aggregation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    FAERS_MANDATORY_LIMITATIONS,
    AcquisitionOutcomeRef,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    RequiredSourceOperation,
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    SourceTaskProgressResult,
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    source_task_attempt,
    validate_required_operation_plan,
)
from medevidence.orchestration.source_task_projection import (
    aggregate_source_operation_disposition,
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
SCOPE_ID = "scope:sha256:" + "d" * 64
BOUNDS = ExecutionBounds(
    max_query_characters=512,
    max_pages=5,
    max_records=100,
    max_payload_bytes=5_242_880,
    max_total_seconds=60,
)


def _operations(source: SourceType, kinds: tuple[SourceOperationKind, ...]):
    return tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=source,
            ordinal=index,
            kind=kind,
            query_id=(
                "query:pubmed:shared"
                if source is SourceType.PUBMED
                else f"query:{source.value}:{index}"
            ),
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


def _result(
    operation,
    *,
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
    count: int = 0,
    pages: int = 0,
    warnings: tuple[str, ...] = (),
    truncated: bool = False,
):
    attempt = source_task_attempt(operation.task_id, 1)
    outcome = SourceOutcome(
        source=operation.source,
        query_id=operation.query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=BOUNDS,
        valid_result_count=count,
        pages_completed=pages,
        truncated=truncated,
        warning_codes=warnings,
        failure_id=(
            f"failure:{operation.ordinal}" if execution is ExecutionStatus.FAILED else None
        ),
    )
    acquisition = source_operation_acquisition(
        operation=operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=derive_identity("acquisition-intent", operation.operation_id),
        outcome=outcome,
        snapshot_id=f"snapshot:{operation.ordinal}",
    )
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=acquisition,
        outcome=outcome,
    )


def _collected(
    operations,
    results,
    *,
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
    warnings: tuple[str, ...] = (),
    valid_result_count: int | None = None,
    pages_completed: int | None = None,
) -> CollectedEvidenceResult:
    source = operations[0].source
    canonical = canonical_terminal_source_outcome(operations, results)
    outcome_payload = canonical.model_dump(mode="python")
    outcome_payload.update(
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        warning_codes=warnings,
        valid_result_count=(
            canonical.valid_result_count if valid_result_count is None else valid_result_count
        ),
        pages_completed=(canonical.pages_completed if pages_completed is None else pages_completed),
        failure_id=(
            canonical.failure_id
            if execution is canonical.execution_status
            else "failure:forged"
            if execution is ExecutionStatus.FAILED
            else None
        ),
    )
    terminal_outcome = SourceOutcome.model_validate(outcome_payload)
    representative = results[0].acquisition
    terminal_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity("source-task-terminal-outcome", terminal_outcome),
        operation_acquisition_ids=tuple(item.acquisition.acquisition_id for item in results),
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
        outcome=terminal_outcome,
    )
    evidence_refs = tuple(
        observation.evidence_reference
        for operation_result in results
        for observation in operation_result.observations
    )
    return CollectedEvidenceResult(
        attempt=results[0].attempt,
        required_operations=operations,
        operation_results=results,
        terminal_outcome_ref=terminal_ref,
        evidence_refs=evidence_refs,
        limitations=(
            CADEC_MANDATORY_LIMITATIONS
            if source is SourceType.CADEC
            else FAERS_MANDATORY_LIMITATIONS
            if source is SourceType.FAERS
            else ()
        ),
    )


@pytest.mark.parametrize(
    ("children", "expected"),
    (
        (
            (("succeeded", "complete", "matches"), ("succeeded", "complete", "no_match")),
            ("succeeded", "complete", "matches"),
        ),
        (
            (("succeeded", "complete", "no_match"), ("succeeded", "complete", "no_match")),
            ("succeeded", "complete", "no_match"),
        ),
        (
            (("succeeded", "partial", "matches"), ("succeeded", "complete", "no_match")),
            ("succeeded", "partial", "matches"),
        ),
        (
            (("succeeded", "partial", "indeterminate"), ("succeeded", "complete", "no_match")),
            ("succeeded", "partial", "indeterminate"),
        ),
        (
            (("failed", "partial", "matches"), ("succeeded", "complete", "no_match")),
            ("failed", "partial", "matches"),
        ),
        (
            (("failed", "partial", "indeterminate"), ("succeeded", "complete", "no_match")),
            ("failed", "partial", "indeterminate"),
        ),
        (
            (
                ("failed", "unavailable", "indeterminate"),
                ("failed", "unavailable", "indeterminate"),
            ),
            ("failed", "unavailable", "indeterminate"),
        ),
    ),
)
def test_owner_frozen_seven_aggregate_outcomes(children, expected) -> None:
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    results = []
    for operation, (execution, coverage, result) in zip(operations, children, strict=True):
        result_status = ResultStatus(result)
        results.append(
            _result(
                operation,
                execution=ExecutionStatus(execution),
                coverage=CoverageStatus(coverage),
                result=result_status,
                count=1 if result_status is ResultStatus.MATCHES else 0,
                pages=0 if coverage == "unavailable" else 1,
                warnings=() if coverage == "complete" else ("a_warning", "z_warning"),
                truncated=coverage == "partial",
            )
        )

    aggregate = aggregate_source_operation_disposition(operations, tuple(results))

    assert (
        aggregate.execution_status.value,
        aggregate.coverage_status.value,
        aggregate.result_status.value,
    ) == expected
    assert aggregate.warning_codes == tuple(sorted(set(aggregate.warning_codes)))


def test_exact_maximum_operation_graph_passes_and_max_plus_one_fails_count_bound() -> None:
    exact = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH,) + (SourceOperationKind.PUBMED_FETCH,) * 100,
    )
    validate_required_operation_plan(SourceType.PUBMED, exact)
    assert len(exact) == 101

    with pytest.raises(ValueError, match="operation count exceeds"):
        validate_required_operation_plan(SourceType.PUBMED, (*exact, exact[-1]))

    faers_exact = _operations(SourceType.FAERS, (SourceOperationKind.FAERS_AGGREGATE,) * 8)
    validate_required_operation_plan(SourceType.FAERS, faers_exact)
    with pytest.raises(ValueError, match="one to eight"):
        validate_required_operation_plan(
            SourceType.FAERS,
            (
                *faers_exact,
                required_source_operation(
                    run_id=RUN_ID,
                    scope_id=SCOPE_ID,
                    source=SourceType.FAERS,
                    ordinal=8,
                    kind=SourceOperationKind.FAERS_AGGREGATE,
                    query_id="query:faers:8",
                    input_refs=_input_refs(SourceOperationKind.FAERS_AGGREGATE, 8),
                ),
            ),
        )


def test_pubmed_multi_fetches_share_search_query_and_differing_fetch_query_fails() -> None:
    shared = _operations(
        SourceType.PUBMED,
        (
            SourceOperationKind.PUBMED_SEARCH,
            SourceOperationKind.PUBMED_FETCH,
            SourceOperationKind.PUBMED_FETCH,
        ),
    )
    validate_required_operation_plan(SourceType.PUBMED, shared)
    assert {item.query_id for item in shared} == {"query:pubmed:shared"}
    assert len({item.operation_id for item in shared}) == 3

    foreign_fetch = required_source_operation(
        run_id=RUN_ID,
        scope_id=SCOPE_ID,
        source=SourceType.PUBMED,
        ordinal=2,
        kind=SourceOperationKind.PUBMED_FETCH,
        query_id="query:pubmed:foreign",
        input_refs=_input_refs(SourceOperationKind.PUBMED_FETCH, 2),
    )
    with pytest.raises(ValueError, match="share the exact search query"):
        validate_required_operation_plan(SourceType.PUBMED, (*shared[:2], foreign_fetch))


def test_pubmed_and_faers_use_bounded_task_level_operational_counts() -> None:
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    pubmed_results = (
        _result(
            operations[0],
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=1,
            pages=2,
        ),
        _result(
            operations[1],
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=1,
            pages=3,
        ),
    )
    disposition = aggregate_source_operation_disposition(operations, pubmed_results)
    assert disposition.result_status is ResultStatus.MATCHES
    pubmed_collection = _collected(
        operations,
        pubmed_results,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        valid_result_count=1,
        pages_completed=2,
    )
    assert pubmed_collection.terminal_outcome_ref.outcome.valid_result_count == 1

    faers_operations = _operations(
        SourceType.FAERS,
        (SourceOperationKind.FAERS_AGGREGATE,) * 8,
    )
    faers_results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=100,
            pages=5,
        )
        for operation in faers_operations
    )
    assert (
        aggregate_source_operation_disposition(faers_operations, faers_results).result_status
        is ResultStatus.MATCHES
    )
    faers_collection = _collected(
        faers_operations,
        faers_results,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        valid_result_count=8,
        pages_completed=5,
    )
    assert faers_collection.terminal_outcome_ref.outcome.pages_completed == 5


def test_canonical_task_counts_pass_exact_source_maxima() -> None:
    pubmed_operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH,) + (SourceOperationKind.PUBMED_FETCH,) * 100,
    )
    pubmed_results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=100 if operation.kind is SourceOperationKind.PUBMED_SEARCH else 1,
            pages=5 if operation.kind is SourceOperationKind.PUBMED_SEARCH else 0,
        )
        for operation in pubmed_operations
    )
    assert (
        canonical_terminal_source_outcome(pubmed_operations, pubmed_results).valid_result_count
        == 100
    )

    daily_operations = _operations(
        SourceType.DAILYMED,
        (SourceOperationKind.DAILYMED_DISCOVERY,) * 4,
    )
    daily_results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=100,
            pages=5,
        )
        for operation in daily_operations
    )
    assert (
        canonical_terminal_source_outcome(daily_operations, daily_results).valid_result_count == 4
    )

    faers_operations = _operations(
        SourceType.FAERS,
        (SourceOperationKind.FAERS_AGGREGATE,) * 8,
    )
    faers_results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=100,
            pages=5,
        )
        for operation in faers_operations
    )
    assert (
        canonical_terminal_source_outcome(faers_operations, faers_results).valid_result_count == 8
    )

    cadec_operations = _operations(
        SourceType.CADEC,
        (SourceOperationKind.CADEC_VERIFY, SourceOperationKind.CADEC_SEARCH),
    )
    verify_result = _result(
        cadec_operations[0],
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.NO_MATCH,
        pages=1,
    )
    search_base = _result(
        cadec_operations[1],
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        count=20,
        pages=1,
    )
    observations = tuple(
        source_operation_observation(
            operation=search_base.operation,
            acquisition=search_base.acquisition,
            evidence_id=f"evidence:cadec:{index}",
            content_hash="sha256:" + f"{index:064x}",
            locator_ref=f"locator:cadec:{index}",
        )
        for index in range(20)
    )
    search_result = TerminalSourceOperationResult(
        operation=search_base.operation,
        attempt=search_base.attempt,
        acquisition=search_base.acquisition,
        outcome=search_base.outcome,
        observations=observations,
    )
    assert (
        canonical_terminal_source_outcome(
            cadec_operations, (verify_result, search_result)
        ).valid_result_count
        == 20
    )
    extra_observation = source_operation_observation(
        operation=search_base.operation,
        acquisition=search_base.acquisition,
        evidence_id="evidence:cadec:20",
        content_hash="sha256:" + f"{20:064x}",
        locator_ref="locator:cadec:20",
    )
    with pytest.raises(ValueError, match="top-20"):
        canonical_terminal_source_outcome(
            cadec_operations,
            (
                verify_result,
                TerminalSourceOperationResult(
                    operation=search_base.operation,
                    attempt=search_base.attempt,
                    acquisition=search_base.acquisition,
                    outcome=search_base.outcome,
                    observations=(*observations, extra_observation),
                ),
            ),
        )


@pytest.mark.parametrize(
    ("child", "terminal"),
    (
        (
            (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("a",)),
            (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("a",)),
        ),
        (
            (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("a",)),
            (
                ExecutionStatus.FAILED,
                CoverageStatus.UNAVAILABLE,
                ResultStatus.INDETERMINATE,
                ("a",),
            ),
        ),
        (
            (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES, ("a",)),
            (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("a",)),
        ),
        (
            (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("a",)),
            (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE, ("b",)),
        ),
    ),
)
def test_collection_rejects_mismatch_in_each_frozen_dimension(child, terminal) -> None:
    operations = _operations(
        SourceType.PUBMED,
        (
            (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH)
            if child[2] is ResultStatus.MATCHES
            else (SourceOperationKind.PUBMED_SEARCH,)
        ),
    )
    child_execution, child_coverage, child_result, child_warnings = child
    results = tuple(
        _result(
            operation,
            execution=child_execution,
            coverage=child_coverage,
            result=child_result,
            count=1 if child_result is ResultStatus.MATCHES else 0,
            pages=1,
            warnings=child_warnings,
            truncated=child_coverage is CoverageStatus.PARTIAL,
        )
        for operation in operations
    )
    terminal_execution, terminal_coverage, terminal_result, terminal_warnings = terminal
    with pytest.raises(ValidationError, match="canonical child reconstruction"):
        _collected(
            operations,
            results,
            execution=terminal_execution,
            coverage=terminal_coverage,
            result=terminal_result,
            warnings=terminal_warnings,
            valid_result_count=1 if terminal_result is ResultStatus.MATCHES else 0,
            pages_completed=(0 if terminal_coverage is CoverageStatus.UNAVAILABLE else 1),
        )


def test_missing_extra_bad_order_foreign_and_provider_native_inputs_fail_closed() -> None:
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=(
                ResultStatus.MATCHES
                if operation.kind is SourceOperationKind.PUBMED_SEARCH
                else ResultStatus.NO_MATCH
            ),
            count=1 if operation.kind is SourceOperationKind.PUBMED_SEARCH else 0,
            pages=1,
        )
        for operation in operations
    )
    with pytest.raises(ValueError, match="exactly equal"):
        aggregate_source_operation_disposition(operations, results[:1])
    with pytest.raises(ValueError, match="exactly equal"):
        aggregate_source_operation_disposition(operations, (*results, results[-1]))
    with pytest.raises(ValueError, match="exactly equal"):
        aggregate_source_operation_disposition(operations, tuple(reversed(results)))

    foreign = results[0].model_dump(mode="python")
    foreign["attempt"] = source_task_attempt("source-task:foreign:pubmed", 1)
    with pytest.raises(ValidationError, match="attempt must bind"):
        TerminalSourceOperationResult.model_validate(foreign)

    stale_acquisition = results[0].acquisition.model_dump(mode="python")
    stale_acquisition["snapshot_id"] = "snapshot:substituted"
    with pytest.raises(ValidationError, match="acquisition identity"):
        type(results[0].acquisition).model_validate(stale_acquisition)

    drifted_input = operations[0].model_dump(mode="python")
    drifted_input["input_identity"] = "input:foreign"
    with pytest.raises(ValidationError, match="typed inputs"):
        RequiredSourceOperation.model_validate(drifted_input)

    class ProviderNativeObject:
        pass

    with pytest.raises(ValidationError):
        aggregate_source_operation_disposition((ProviderNativeObject(),), results)  # type: ignore[arg-type]


def test_typed_input_roles_and_input_identity_are_authoritative() -> None:
    search = required_source_operation(
        run_id=RUN_ID,
        scope_id=SCOPE_ID,
        source=SourceType.PUBMED,
        ordinal=0,
        kind=SourceOperationKind.PUBMED_SEARCH,
        query_id="query:pubmed:typed",
        input_refs=(
            SourceOperationInputRef(
                role=SourceOperationInputRole.REQUEST,
                value="request:wrong-role",
            ),
        ),
    )
    with pytest.raises(ValueError, match="exact typed input roles"):
        validate_required_operation_plan(SourceType.PUBMED, (search,))

    payload = search.model_dump(mode="python")
    payload["input_refs"] = (
        SourceOperationInputRef(
            role=SourceOperationInputRole.QUERY_PLAN,
            value="query-plan:substituted",
        ),
    )
    with pytest.raises(ValidationError, match="input identity"):
        RequiredSourceOperation.model_validate(payload)


def test_progress_result_checkpoints_exact_nonempty_plan_prefix() -> None:
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    search_result = _result(
        operations[0],
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        count=1,
        pages=1,
    )
    progress = SourceTaskProgressResult(
        attempt=search_result.attempt,
        required_operations=operations,
        operation_results=(search_result,),
    )
    assert progress.operation_results == (search_result,)
    assert not hasattr(progress, "terminal_outcome_ref")

    with pytest.raises(ValidationError):
        SourceTaskProgressResult(
            attempt=search_result.attempt,
            required_operations=operations,
            operation_results=(),
        )
    fetch_result = _result(
        operations[1],
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.NO_MATCH,
        pages=1,
    )
    with pytest.raises(ValidationError, match="exact plan prefix"):
        SourceTaskProgressResult(
            attempt=search_result.attempt,
            required_operations=operations,
            operation_results=(fetch_result,),
        )
    with pytest.raises(ValidationError, match="one exact attempt"):
        SourceTaskProgressResult(
            attempt=source_task_attempt("source-task:foreign:pubmed", 1),
            required_operations=operations,
            operation_results=(search_result,),
        )
    with pytest.raises(ValidationError):
        SourceTaskProgressResult.model_validate(
            {
                **progress.model_dump(mode="python"),
                "terminal_outcome_ref": "forbidden",
            }
        )


def test_terminal_outcome_and_operation_acquisition_bindings_fail_closed() -> None:
    operations = _operations(
        SourceType.PUBMED,
        (SourceOperationKind.PUBMED_SEARCH, SourceOperationKind.PUBMED_FETCH),
    )
    results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=(
                ResultStatus.MATCHES
                if operation.kind is SourceOperationKind.PUBMED_SEARCH
                else ResultStatus.NO_MATCH
            ),
            count=1 if operation.kind is SourceOperationKind.PUBMED_SEARCH else 0,
            pages=1,
        )
        for operation in operations
    )
    valid = _collected(
        operations,
        results,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
        pages_completed=1,
    )
    payload = valid.model_dump(mode="python")

    wrong_terminal = valid.terminal_outcome_ref.model_dump(mode="python")
    wrong_terminal["terminal_outcome_id"] = "terminal-outcome:foreign"
    with pytest.raises(ValidationError, match="terminal outcome identity"):
        TerminalSourceOutcomeRef.model_validate(wrong_terminal)

    expected_ids = valid.terminal_outcome_ref.operation_acquisition_ids
    for acquisition_ids in (
        expected_ids[:1],
        (*expected_ids, "source-operation-acquisition:extra"),
        tuple(reversed(expected_ids)),
    ):
        changed = valid.terminal_outcome_ref.model_dump(mode="python")
        changed["operation_acquisition_ids"] = acquisition_ids
        with pytest.raises(ValidationError, match="exact result order"):
            CollectedEvidenceResult.model_validate({**payload, "terminal_outcome_ref": changed})

    mismatched_representative = valid.terminal_outcome_ref.model_dump(mode="python")
    mismatched_representative["acquisition"]["source_outcome_id"] = (
        "source-operation-outcome:foreign"
    )
    with pytest.raises(ValidationError, match="exact operation binding"):
        CollectedEvidenceResult.model_validate(
            {**payload, "terminal_outcome_ref": mismatched_representative}
        )

    for field, value in (
        ("acquisition_intent_id", derive_identity("acquisition-intent", "foreign")),
        ("operation", "fetch"),
    ):
        mismatched = valid.terminal_outcome_ref.model_dump(mode="python")
        mismatched["acquisition"][field] = value
        with pytest.raises(ValidationError, match="exact operation binding"):
            CollectedEvidenceResult.model_validate({**payload, "terminal_outcome_ref": mismatched})

    forged_query = valid.terminal_outcome_ref.model_dump(mode="python")
    forged_query["outcome"]["query_id"] = "query:forged"
    forged_outcome = SourceOutcome.model_validate(forged_query["outcome"])
    forged_query["terminal_outcome_id"] = derive_identity(
        "source-task-terminal-outcome", forged_outcome
    )
    with pytest.raises(ValidationError, match="canonical child reconstruction"):
        CollectedEvidenceResult.model_validate({**payload, "terminal_outcome_ref": forged_query})

    matching_results = tuple(
        _result(
            operation,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.MATCHES,
            count=1,
            pages=1,
        )
        for operation in operations
    )
    matching = _collected(
        operations,
        matching_results,
        execution=ExecutionStatus.SUCCEEDED,
        coverage=CoverageStatus.COMPLETE,
        result=ResultStatus.MATCHES,
    )
    forged_count = matching.terminal_outcome_ref.model_dump(mode="python")
    forged_count["outcome"]["valid_result_count"] = 3
    forged_count_outcome = SourceOutcome.model_validate(forged_count["outcome"])
    forged_count["terminal_outcome_id"] = derive_identity(
        "source-task-terminal-outcome", forged_count_outcome
    )
    with pytest.raises(ValidationError, match="canonical child reconstruction"):
        CollectedEvidenceResult.model_validate(
            {
                **matching.model_dump(mode="python"),
                "terminal_outcome_ref": forged_count,
            }
        )


def test_governed_faers_and_cadec_limitations_are_exact() -> None:
    for source, kind in (
        (SourceType.FAERS, SourceOperationKind.FAERS_AGGREGATE),
        (SourceType.CADEC, SourceOperationKind.CADEC_VERIFY),
    ):
        kinds = (kind, SourceOperationKind.CADEC_SEARCH) if source is SourceType.CADEC else (kind,)
        operations = _operations(source, kinds)
        results = tuple(
            _result(
                operation,
                execution=ExecutionStatus.SUCCEEDED,
                coverage=CoverageStatus.COMPLETE,
                result=ResultStatus.NO_MATCH,
                pages=1,
            )
            for operation in operations
        )
        valid = _collected(
            operations,
            results,
            execution=ExecutionStatus.SUCCEEDED,
            coverage=CoverageStatus.COMPLETE,
            result=ResultStatus.NO_MATCH,
            pages_completed=1,
        )
        with pytest.raises(ValidationError, match="exact mandatory limitations"):
            CollectedEvidenceResult.model_validate(
                {**valid.model_dump(mode="python"), "limitations": ()}
            )


def test_failed_cadec_rejects_self_consistent_observation_and_evidence() -> None:
    operations = _operations(
        SourceType.CADEC,
        (SourceOperationKind.CADEC_VERIFY, SourceOperationKind.CADEC_SEARCH),
    )
    results = [
        _result(
            operation,
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.UNAVAILABLE,
            result=ResultStatus.INDETERMINATE,
            warnings=("cadec_mandatory_limitations",),
        )
        for operation in operations
    ]
    observed = results[1]
    observation = source_operation_observation(
        operation=observed.operation,
        acquisition=observed.acquisition,
        evidence_id="evidence:cadec:forbidden",
        content_hash="sha256:" + "b" * 64,
        locator_ref="locator:cadec:forbidden",
    )
    results[1] = TerminalSourceOperationResult(
        operation=observed.operation,
        attempt=observed.attempt,
        acquisition=observed.acquisition,
        outcome=observed.outcome,
        observations=(observation,),
    )
    with pytest.raises(ValidationError, match="degraded CADEC"):
        _collected(
            operations,
            tuple(results),
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.UNAVAILABLE,
            result=ResultStatus.INDETERMINATE,
            warnings=("cadec_mandatory_limitations",),
        )


def test_dailymed_four_discovery_fetch_groups_pass_at_exact_maximum() -> None:
    operations = tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=SourceType.DAILYMED,
            ordinal=ordinal,
            kind=(
                SourceOperationKind.DAILYMED_DISCOVERY
                if ordinal < 4
                else SourceOperationKind.DAILYMED_FETCH
            ),
            query_id=f"query:dailymed:{ordinal if ordinal < 4 else ordinal - 4}",
            input_refs=_input_refs(
                SourceOperationKind.DAILYMED_DISCOVERY
                if ordinal < 4
                else SourceOperationKind.DAILYMED_FETCH,
                ordinal,
            ),
        )
        for ordinal in range(8)
    )
    validate_required_operation_plan(SourceType.DAILYMED, operations)
    assert len(operations) == 8


def test_dailymed_discovery_plan_is_exact_prefix_of_selected_fetch_expansion() -> None:
    discovery_prefix = tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=SourceType.DAILYMED,
            ordinal=ordinal,
            kind=SourceOperationKind.DAILYMED_DISCOVERY,
            query_id=f"query:dailymed:{ordinal}",
            input_refs=_input_refs(SourceOperationKind.DAILYMED_DISCOVERY, ordinal),
        )
        for ordinal in range(4)
    )
    fetch_suffix_queries = ("query:dailymed:0", "query:dailymed:2", "query:dailymed:3")
    expanded = (
        *discovery_prefix,
        *(
            required_source_operation(
                run_id=RUN_ID,
                scope_id=SCOPE_ID,
                source=SourceType.DAILYMED,
                ordinal=4 + offset,
                kind=SourceOperationKind.DAILYMED_FETCH,
                query_id=query_id,
                input_refs=_input_refs(SourceOperationKind.DAILYMED_FETCH, offset),
            )
            for offset, query_id in enumerate(fetch_suffix_queries)
        ),
    )
    validate_required_operation_plan(SourceType.DAILYMED, discovery_prefix)
    validate_required_operation_plan(SourceType.DAILYMED, expanded)
    assert expanded[: len(discovery_prefix)] == discovery_prefix


def test_dailymed_fifth_discovery_group_fails_exact_group_bound() -> None:
    five_discoveries = _operations(
        SourceType.DAILYMED,
        (SourceOperationKind.DAILYMED_DISCOVERY,) * 5,
    )
    with pytest.raises(ValueError, match="one to four discovery groups"):
        validate_required_operation_plan(SourceType.DAILYMED, five_discoveries)


def test_dailymed_mixed_optional_fetch_pattern_is_canonical() -> None:
    discovery_only = _operations(SourceType.DAILYMED, (SourceOperationKind.DAILYMED_DISCOVERY,))
    validate_required_operation_plan(SourceType.DAILYMED, discovery_only)
    mixed_kinds = (
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_FETCH,
        SourceOperationKind.DAILYMED_FETCH,
    )
    mixed_queries = (
        "query:dailymed:0",
        "query:dailymed:1",
        "query:dailymed:2",
        "query:dailymed:0",
        "query:dailymed:2",
    )
    mixed = tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=SourceType.DAILYMED,
            ordinal=ordinal,
            kind=kind,
            query_id=query_id,
            input_refs=_input_refs(kind, ordinal),
        )
        for ordinal, (kind, query_id) in enumerate(zip(mixed_kinds, mixed_queries, strict=True))
    )
    validate_required_operation_plan(SourceType.DAILYMED, mixed)
    assert len(discovery_only) == 1


@pytest.mark.parametrize(
    ("kinds", "queries", "message"),
    (
        (
            (SourceOperationKind.DAILYMED_FETCH,),
            ("query:dailymed:0",),
            "nonempty discovery prefix",
        ),
        (
            (
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_FETCH,
                SourceOperationKind.DAILYMED_DISCOVERY,
            ),
            ("query:dailymed:0", "query:dailymed:0", "query:dailymed:1"),
            "cannot appear after",
        ),
        (
            (SourceOperationKind.DAILYMED_DISCOVERY, SourceOperationKind.DAILYMED_FETCH),
            ("query:dailymed:0", "query:dailymed:foreign"),
            "bind a prior discovery",
        ),
        (
            (
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_FETCH,
                SourceOperationKind.DAILYMED_FETCH,
            ),
            ("query:dailymed:0", "query:dailymed:0", "query:dailymed:0"),
            "at most one fetch",
        ),
        (
            (
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_FETCH,
                SourceOperationKind.DAILYMED_FETCH,
            ),
            (
                "query:dailymed:0",
                "query:dailymed:1",
                "query:dailymed:2",
                "query:dailymed:2",
                "query:dailymed:0",
            ),
            "preserve discovery order",
        ),
    ),
)
def test_dailymed_orphan_reordered_wrong_query_and_duplicate_fetch_fail(
    kinds, queries, message
) -> None:
    operations = tuple(
        required_source_operation(
            run_id=RUN_ID,
            scope_id=SCOPE_ID,
            source=SourceType.DAILYMED,
            ordinal=ordinal,
            kind=kind,
            query_id=query_id,
            input_refs=_input_refs(kind, ordinal),
        )
        for ordinal, (kind, query_id) in enumerate(zip(kinds, queries, strict=True))
    )
    with pytest.raises(ValueError, match=message):
        validate_required_operation_plan(SourceType.DAILYMED, operations)
