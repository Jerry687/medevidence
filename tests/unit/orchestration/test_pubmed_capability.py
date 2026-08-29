"""Offline regressions for the persisted PubMed source capability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests.unit.tools.test_research import (
    Acquisitions,
    Execution,
    _outcome,
    _request,
    _service,
)

from medevidence.domain import (
    CoverageStatus,
    ExecutionStatus,
    ResultStatus,
    SourceType,
    derive_identity,
)
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.pubmed_capability import (
    collect_pubmed,
    plan_pubmed_operations,
    validate_pubmed_terminal_task,
)
from medevidence.orchestration.source_task_projection import required_source_operation
from medevidence.tools.ports import PubMedSearchProgressRecord


def _running_task(service):
    request = _request()
    task_id = source_task_id(request.run_id, SourceType.PUBMED)
    attempt = source_task_attempt(task_id, 1)
    pending = SourceTaskState(task_id=task_id, source=SourceType.PUBMED)
    (operation,) = plan_pubmed_operations(
        task=pending,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    task = SourceTaskState(
        task_id=task_id,
        source=SourceType.PUBMED,
        required_operations=(operation,),
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    return request, task, attempt, operation


def _resume_task(
    task: SourceTaskState,
    progress: SourceTaskProgressResult,
) -> SourceTaskState:
    return SourceTaskState.model_validate(
        {
            **task.model_dump(mode="python"),
            "required_operations": progress.required_operations,
            "operation_results": progress.operation_results,
        }
    )


def _collect_terminal(service, request, task, attempt):
    first = collect_pubmed(
        task=task,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    if isinstance(first, CollectedEvidenceResult):
        return None, first
    resumed = _resume_task(task, first)
    terminal = collect_pubmed(
        task=resumed,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    assert isinstance(terminal, CollectedEvidenceResult)
    return first, terminal


def _terminal_task(task: SourceTaskState, result: CollectedEvidenceResult) -> SourceTaskState:
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=result.required_operations,
        operation_results=result.operation_results,
        status=SourceTaskStatus.TERMINAL,
        attempts=result.attempt.attempt_number,
        terminal_outcome_ref=result.terminal_outcome_ref,
        evidence_refs=result.evidence_refs,
        limitations=result.limitations,
    )


def test_pending_pubmed_plan_is_pure_search_only_application_planning() -> None:
    calls: list[str] = []
    service, runs = _service(calls)
    request = _request()
    task_id = source_task_id(request.run_id, SourceType.PUBMED)
    pending = SourceTaskState(task_id=task_id, source=SourceType.PUBMED)
    attempt = source_task_attempt(task_id, 1)

    planned = plan_pubmed_operations(
        task=pending,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )

    assert len(planned) == 1
    assert planned[0].kind is SourceOperationKind.PUBMED_SEARCH
    assert planned[0].run_id == request.run_id
    assert calls == []
    assert runs.finalization is None and runs.acquisitions is None


def test_pubmed_capability_rejects_nonexact_or_coordinated_fake_service() -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, _ = _running_task(service)

    with pytest.raises(TypeError, match="exact sealed research service"):
        plan_pubmed_operations(
            task=task,
            scope=request.scope,
            attempt=attempt,
            request=request,
            service=object(),  # type: ignore[arg-type]
        )

    assert calls == []


def test_collect_pubmed_binds_exact_persisted_acquisitions_and_publication() -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    execution = Execution(calls)
    service, runs = _service(calls, execution=execution, acquisitions=acquisitions)
    request, task, attempt, search_operation = _running_task(service)

    progress = collect_pubmed(
        task=task,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )

    assert isinstance(progress, SourceTaskProgressResult)
    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
    ]
    assert len(progress.operation_results) == 1
    assert len(progress.required_operations) == 2
    assert not any(call.startswith("execute-fetch") for call in calls)
    assert not any(call.startswith("persist-fetch") for call in calls)

    progress = SourceTaskProgressResult.model_validate_json(progress.model_dump_json())
    resume_service, resume_runs = _service(
        calls,
        execution=execution,
        acquisitions=acquisitions,
    )
    result = collect_pubmed(
        task=_resume_task(task, progress),
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=resume_service,
    )
    assert isinstance(result, CollectedEvidenceResult)
    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
        "load-search-progress",
        "execute-fetch-10",
        "persist-fetch-10",
        "persist-terminal-progress",
    ]
    assert runs.finalization is None and runs.acquisitions is None
    assert resume_runs.finalization is None and resume_runs.acquisitions is None
    assert result.required_operations[0] == search_operation
    assert tuple(item.operation.kind for item in result.operation_results) == (
        SourceOperationKind.PUBMED_SEARCH,
        SourceOperationKind.PUBMED_FETCH,
    )
    assert {item.operation.query_id for item in result.operation_results} == {
        search_operation.query_id
    }
    prepared = resume_service.prepare_collection(request)
    assert search_operation.input_refs == (
        SourceOperationInputRef(
            role=SourceOperationInputRole.QUERY_PLAN,
            value=derive_identity(
                "pubmed-search-request",
                {
                    "scope": request.scope,
                    "query": prepared.query,
                    "query_id": prepared.query_id,
                    "catalog_version": prepared.catalog.catalog_version,
                    "catalog_content_hash": prepared.catalog.catalog_content_hash,
                    "run_intent_id": prepared.run_intent_id,
                },
            ),
        ),
    )
    assert result.required_operations[1].input_refs == (
        SourceOperationInputRef(
            role=SourceOperationInputRole.PUBMED_PMID,
            value="10",
        ),
    )
    assert search_operation.input_identity == derive_identity(
        "source-operation-input",
        {
            "kind": SourceOperationKind.PUBMED_SEARCH,
            "query_id": prepared.query_id,
            "input_refs": search_operation.input_refs,
        },
    )
    assert len(result.evidence_refs) == 1
    evidence = result.evidence_refs[0]
    fetch_result = result.operation_results[1]
    assert evidence.snapshot_id == fetch_result.acquisition.snapshot_id
    assert evidence.content_hash.startswith("sha256:")
    assert evidence.evidence_id.startswith("pubmed:10:sha256:")
    assert evidence.locator_ref == "pubmed:10"
    terminal = result.terminal_outcome_ref
    persisted_search = acquisitions.raw_results[0]
    assert (
        terminal.acquisition.acquisition_id
        == result.operation_results[0].acquisition.acquisition_id
    )
    assert terminal.acquisition.snapshot_id == result.operation_results[0].acquisition.snapshot_id
    assert terminal.acquisition.acquisition_intent_id == persisted_search.acquisition_intent_id
    assert terminal.acquisition.snapshot_id == persisted_search.snapshot_id
    assert result.operation_results[0].acquisition.acquisition_intent_id == (
        persisted_search.acquisition_intent_id
    )
    assert result.operation_results[1].acquisition.acquisition_intent_id == (
        acquisitions.raw_results[1].acquisition_intent_id
    )
    assert terminal.outcome.valid_result_count == 1
    assert terminal.terminal_outcome_id == derive_identity(
        "source-task-terminal-outcome",
        terminal.outcome,
    )
    assert terminal.operation_acquisition_ids == tuple(
        item.acquisition.acquisition_id for item in result.operation_results
    )
    assert result.limitations == ()

    before_validation = tuple(calls)
    validation_service, _ = _service(
        calls,
        execution=execution,
        acquisitions=acquisitions,
    )
    validate_pubmed_terminal_task(
        task=_terminal_task(task, result),
        scope=request.scope,
        request=request,
        service=validation_service,
    )
    assert tuple(calls[: len(before_validation)]) == before_validation
    assert calls[-2:] == ["load-search-progress", "load-terminal-progress"]


def test_complete_no_match_freezes_only_search_and_performs_no_fetch() -> None:
    calls: list[str] = []
    search_outcome = _outcome(result=ResultStatus.NO_MATCH)
    service, runs = _service(
        calls,
        execution=Execution(calls, search_outcome=search_outcome),
    )
    request, task, attempt, _ = _running_task(service)

    result = collect_pubmed(
        task=task,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )

    assert isinstance(result, CollectedEvidenceResult)
    assert calls == [
        "persist-run-intent",
        "execute-search",
        "persist-search",
        "persist-search-progress",
        "persist-terminal-progress",
    ]
    assert len(result.required_operations) == len(result.operation_results) == 1
    assert result.evidence_refs == ()
    assert result.terminal_outcome_ref.outcome.result_status is ResultStatus.NO_MATCH
    assert runs.finalization is None


def test_search_match_with_failed_empty_fetch_is_operational_match_without_evidence() -> None:
    calls: list[str] = []
    failed_fetch = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.PARTIAL,
        execution=ExecutionStatus.FAILED,
        failure_id="failure:fetch-empty",
    )
    service, runs = _service(
        calls,
        execution=Execution(calls, fetch_outcome=failed_fetch),
    )
    request, task, attempt, _ = _running_task(service)

    progress, result = _collect_terminal(service, request, task, attempt)

    assert progress is not None
    outcome = result.terminal_outcome_ref.outcome
    assert (outcome.execution_status, outcome.coverage_status, outcome.result_status) == (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
    )
    assert outcome.valid_result_count == 1
    assert result.evidence_refs == ()
    representative = result.terminal_outcome_ref.acquisition
    search_child = result.operation_results[0].acquisition
    assert representative.source_outcome_id == search_child.source_outcome_id
    assert result.terminal_outcome_ref.terminal_outcome_id == derive_identity(
        "source-task-terminal-outcome",
        outcome,
    )
    assert representative.source_outcome_id != result.terminal_outcome_ref.terminal_outcome_id
    assert runs.finalization is None


def test_same_query_and_count_with_different_pmids_produce_different_fetch_plans() -> None:
    def collected(pmids: tuple[str, ...]):
        calls: list[str] = []
        service, _ = _service(
            calls,
            execution=Execution(
                calls,
                search_outcome=_outcome(result=ResultStatus.MATCHES, count=len(pmids)),
                search_pmids=pmids,
                search_total_available=len(pmids),
            ),
        )
        request, task, attempt, _ = _running_task(service)
        progress, terminal = _collect_terminal(service, request, task, attempt)
        assert progress is not None
        return terminal

    first = collected(("1", "2"))
    second = collected(("1", "3"))

    assert first.required_operations[0] == second.required_operations[0]
    assert first.required_operations[1] == second.required_operations[1]
    assert first.required_operations[2] != second.required_operations[2]
    assert (
        first.required_operations[2].input_identity != second.required_operations[2].input_identity
    )


def test_alternate_same_count_fetch_suffix_is_rejected_before_fetch() -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    service, _ = _service(calls, acquisitions=acquisitions)
    request, task, attempt, search = _running_task(service)
    progress = collect_pubmed(
        task=task,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    assert isinstance(progress, SourceTaskProgressResult)
    alternate = required_source_operation(
        run_id=request.run_id,
        scope_id=request.scope.scope_id,
        source=SourceType.PUBMED,
        ordinal=1,
        kind=SourceOperationKind.PUBMED_FETCH,
        query_id=search.query_id,
        input_refs=(
            SourceOperationInputRef(
                role=SourceOperationInputRole.PUBMED_PMID,
                value="11",
            ),
        ),
    )
    drifted = SourceTaskProgressResult(
        attempt=attempt,
        required_operations=(search, alternate),
        operation_results=progress.operation_results,
    )

    with pytest.raises(ValueError, match="persisted PubMed search progress"):
        collect_pubmed(
            task=_resume_task(task, drifted),
            scope=request.scope,
            attempt=attempt,
            request=request,
            service=service,
        )

    assert "load-search-progress" in calls
    assert not any(call.startswith("execute-fetch") for call in calls)
    assert not any(call.startswith("persist-fetch") for call in calls)


@pytest.mark.parametrize("mode", ["missing", "stale", "corrupt"])
def test_missing_stale_or_corrupt_search_progress_fails_before_fetch(mode: str) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    service, _ = _service(calls, acquisitions=acquisitions)
    request, task, attempt, _ = _running_task(service)
    progress = collect_pubmed(
        task=task,
        scope=request.scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    assert isinstance(progress, SourceTaskProgressResult)
    record = acquisitions.search_progress
    assert record is not None
    if mode == "missing":
        acquisitions.search_progress = None
    elif mode == "stale":
        acquisitions.search_progress = PubMedSearchProgressRecord.create(
            **{
                **record.payload(),
                "run_id": "run:ffffffff-ffff-4fff-8fff-ffffffffffff",
            }
        )
    else:
        acquisitions.search_progress = record.model_copy(
            update={"content_hash": f"sha256:{'f' * 64}"}
        )

    with pytest.raises((ValidationError, ValueError), match=r"progress|content hash|missing"):
        collect_pubmed(
            task=_resume_task(task, progress),
            scope=request.scope,
            attempt=attempt,
            request=request,
            service=service,
        )

    assert not any(call.startswith("execute-fetch") for call in calls)


@pytest.mark.parametrize(
    "drift",
    ["terminal_outcome_id", "operation_acquisition_ids", "representative_child_outcome"],
)
def test_terminal_v2_rejects_mismatched_aggregate_or_child_identities(drift: str) -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, _ = _running_task(service)
    _, result = _collect_terminal(service, request, task, attempt)
    payload = result.model_dump(mode="python")
    terminal = payload["terminal_outcome_ref"]
    if drift == "terminal_outcome_id":
        terminal["terminal_outcome_id"] = "terminal-outcome:foreign"
    elif drift == "operation_acquisition_ids":
        terminal["operation_acquisition_ids"] = tuple(
            reversed(terminal["operation_acquisition_ids"])
        )
    else:
        terminal["acquisition"]["source_outcome_id"] = terminal["terminal_outcome_id"]

    with pytest.raises(ValidationError, match=r"terminal|representative|acquisition"):
        CollectedEvidenceResult.model_validate(payload)


@pytest.mark.parametrize("drift", ["query", "intent", "representative", "bounds"])
def test_terminal_replay_rejects_checkpoint_field_drift_before_source_io(drift: str) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    service, _ = _service(calls, acquisitions=acquisitions)
    request, task, attempt, _ = _running_task(service)
    _, result = _collect_terminal(service, request, task, attempt)
    terminal_task = _terminal_task(task, result)
    if drift == "query":
        operations = list(terminal_task.required_operations)
        operations[0] = operations[0].model_copy(update={"query_id": "query:foreign"})
        drifted_task = terminal_task.model_copy(update={"required_operations": tuple(operations)})
    elif drift == "intent":
        results = list(terminal_task.operation_results)
        results[0] = results[0].model_copy(
            update={
                "acquisition": results[0].acquisition.model_copy(
                    update={"acquisition_intent_id": f"acquisition-intent:sha256:{'f' * 64}"}
                )
            }
        )
        drifted_task = terminal_task.model_copy(update={"operation_results": tuple(results)})
    elif drift == "representative":
        terminal = terminal_task.terminal_outcome_ref
        assert terminal is not None
        drifted_task = terminal_task.model_copy(
            update={
                "terminal_outcome_ref": terminal.model_copy(
                    update={
                        "acquisition": terminal.acquisition.model_copy(
                            update={"snapshot_id": f"sha256:{'f' * 64}"}
                        )
                    }
                )
            }
        )
    else:
        results = list(terminal_task.operation_results)
        outcome = results[0].outcome
        results[0] = results[0].model_copy(
            update={
                "outcome": outcome.model_copy(
                    update={
                        "configured_bounds": outcome.configured_bounds.model_copy(
                            update={"max_total_seconds": 61}
                        )
                    }
                )
            }
        )
        drifted_task = terminal_task.model_copy(update={"operation_results": tuple(results)})
    before = len(calls)

    with pytest.raises((ValidationError, ValueError)):
        validate_pubmed_terminal_task(
            task=drifted_task,
            scope=request.scope,
            request=request,
            service=service,
        )

    assert not any(call.startswith("execute-") for call in calls[before:])


def test_terminal_replay_rejects_coordinated_valid_checkpoint_rewrite() -> None:
    calls: list[str] = []
    durable = Acquisitions(calls)
    service, _ = _service(calls, acquisitions=durable)
    request, task, attempt, _ = _running_task(service)
    _, original = _collect_terminal(service, request, task, attempt)

    alternate_calls: list[str] = []
    failed_fetch = _outcome(
        result=ResultStatus.INDETERMINATE,
        coverage=CoverageStatus.PARTIAL,
        execution=ExecutionStatus.FAILED,
        failure_id="failure:coordinated-rewrite",
    )
    alternate_service, _ = _service(
        alternate_calls,
        execution=Execution(alternate_calls, fetch_outcome=failed_fetch),
    )
    alternate_request, alternate_task, alternate_attempt, _ = _running_task(alternate_service)
    _, rewritten = _collect_terminal(
        alternate_service,
        alternate_request,
        alternate_task,
        alternate_attempt,
    )
    rewritten_task = _terminal_task(alternate_task, rewritten)
    assert rewritten_task != _terminal_task(task, original)
    before = len(calls)

    with pytest.raises(ValueError, match="terminal receipt differs"):
        validate_pubmed_terminal_task(
            task=rewritten_task,
            scope=request.scope,
            request=request,
            service=service,
        )

    assert calls[before:] == ["load-search-progress", "load-terminal-progress"]


@pytest.mark.parametrize("mode", ["missing", "corrupt"])
def test_terminal_replay_rejects_missing_or_corrupt_terminal_receipt(mode: str) -> None:
    calls: list[str] = []
    acquisitions = Acquisitions(calls)
    service, _ = _service(calls, acquisitions=acquisitions)
    request, task, attempt, _ = _running_task(service)
    _, result = _collect_terminal(service, request, task, attempt)
    terminal_task = _terminal_task(task, result)
    if mode == "missing":
        acquisitions.terminal_progress = None
    else:
        receipt = acquisitions.terminal_progress
        assert receipt is not None
        acquisitions.terminal_progress = receipt.model_copy(
            update={"content_hash": f"sha256:{'f' * 64}"}
        )
    before = len(calls)

    with pytest.raises((ValidationError, ValueError), match=r"terminal progress|content hash"):
        validate_pubmed_terminal_task(
            task=terminal_task,
            scope=request.scope,
            request=request,
            service=service,
        )

    assert not any(call.startswith("execute-") for call in calls[before:])


@pytest.mark.parametrize("drift", ["extra", "missing", "reordered"])
def test_required_operation_drift_fails_before_any_effect(drift: str) -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, search = _running_task(service)
    fetch = required_source_operation(
        run_id=request.run_id,
        scope_id=request.scope.scope_id,
        source=SourceType.PUBMED,
        ordinal=1,
        kind=SourceOperationKind.PUBMED_FETCH,
        query_id=search.query_id,
        input_refs=(
            SourceOperationInputRef(
                role=SourceOperationInputRole.PUBMED_PMID,
                value="10",
            ),
        ),
    )
    operations = {
        "extra": (search, fetch),
        "missing": (),
        "reordered": (fetch, search),
    }[drift]
    drifted = task.model_copy(update={"required_operations": operations})

    with pytest.raises((ValidationError, ValueError), match=r"operation|search|source task"):
        collect_pubmed(
            task=drifted,
            scope=request.scope,
            attempt=attempt,
            request=request,
            service=service,
        )

    assert calls == []


def test_stale_or_foreign_attempt_fails_before_any_effect() -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, _, _ = _running_task(service)
    stale = source_task_attempt(task.task_id, 2)

    with pytest.raises(ValueError, match="exact active task attempt"):
        collect_pubmed(
            task=task,
            scope=request.scope,
            attempt=stale,
            request=request,
            service=service,
        )

    assert calls == []


def test_foreign_run_fails_before_any_effect() -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, _ = _running_task(service)
    foreign_request = request.model_copy(
        update={"run_id": "run:ffffffff-ffff-4fff-8fff-ffffffffffff"}
    )

    with pytest.raises(ValueError, match="exact current run"):
        collect_pubmed(
            task=task,
            scope=request.scope,
            attempt=attempt,
            request=foreign_request,
            service=service,
        )

    assert calls == []


def test_attempt_idempotency_drift_fails_before_any_effect() -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, _ = _running_task(service)
    drifted = attempt.model_copy(update={"idempotency_key": f"sha256:{'f' * 64}"})

    with pytest.raises(ValidationError, match="idempotency"):
        collect_pubmed(
            task=task,
            scope=request.scope,
            attempt=drifted,
            request=request,
            service=service,
        )

    assert calls == []


def test_exact_maximum_100_pmids_is_collected_without_truncating_operation_plan() -> None:
    calls: list[str] = []
    pmids = tuple(str(index) for index in range(1, 101))
    search_outcome = _outcome(result=ResultStatus.MATCHES, count=100)
    service, runs = _service(
        calls,
        execution=Execution(
            calls,
            search_outcome=search_outcome,
            search_pmids=pmids,
            search_total_available=100,
        ),
    )
    request, task, attempt, _ = _running_task(service)

    progress, result = _collect_terminal(service, request, task, attempt)

    assert progress is not None
    assert len(result.required_operations) == len(result.operation_results) == 101
    assert len(result.evidence_refs) == 100
    assert result.terminal_outcome_ref.outcome.valid_result_count == 100
    assert runs.finalization is None


def test_capability_result_contains_no_publication_or_transport_native_objects() -> None:
    calls: list[str] = []
    service, _ = _service(calls)
    request, task, attempt, _ = _running_task(service)

    _, result = _collect_terminal(service, request, task, attempt)
    payload = result.model_dump_json()

    assert "publication" not in payload
    assert "ResponseObservation" not in payload
    assert "<search" not in payload and "<article" not in payload
