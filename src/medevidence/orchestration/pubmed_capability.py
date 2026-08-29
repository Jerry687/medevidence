"""Thin PubMed source capability over the existing persisted research tool."""

from __future__ import annotations

from pydantic import BaseModel

from medevidence.domain import (
    AcquisitionOutcomeRef,
    ResearchScope,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.tools.contracts import ResearchPubMedRequest, SearchPubMedResponse
from medevidence.tools.ports import (
    PubMedSearchProgressRecord,
    PubMedTerminalEvidenceRecord,
    PubMedTerminalOperationRecord,
    PubMedTerminalProgressRecord,
)
from medevidence.tools.research import (
    PubMedCollectionPreparation,
    PubMedResearchService,
    PubMedSearchCollection,
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
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    source_task_id,
)
from .source_task_projection import (
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)


def _reconstruct(model: BaseModel) -> dict[str, object]:
    return model.model_dump(mode="python")


def _require_exact_service(service: PubMedResearchService) -> None:
    if type(service) is not PubMedResearchService:
        raise TypeError("PubMed capability requires the exact sealed research service")


def _search_request_identity(prepared: PubMedCollectionPreparation) -> str:
    return derive_identity(
        "pubmed-search-request",
        {
            "scope": prepared.request.scope,
            "query": prepared.query,
            "query_id": prepared.query_id,
            "catalog_version": prepared.catalog.catalog_version,
            "catalog_content_hash": prepared.catalog.catalog_content_hash,
            "run_intent_id": prepared.run_intent_id,
        },
    )


def _validate_task_identity(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    request: ResearchPubMedRequest,
) -> None:
    if request.scope != scope:
        raise ValueError("PubMed capability request must bind the exact current scope")
    if SourceType.PUBMED not in scope.selected_sources:
        raise ValueError("PubMed capability requires PubMed selected in the current scope")
    expected_task_id = source_task_id(request.run_id, SourceType.PUBMED)
    if task.task_id != expected_task_id or task.source is not SourceType.PUBMED:
        raise ValueError("PubMed capability task must bind the exact current run")
    if attempt.task_id != task.task_id:
        raise ValueError("PubMed capability attempt must bind the exact source task")
    if task.terminal_outcome_ref is not None or task.evidence_refs or task.limitations:
        raise ValueError("PubMed capability cannot execute an already terminal task")


def _planned_search_operation(
    prepared: PubMedCollectionPreparation,
) -> RequiredSourceOperation:
    return required_source_operation(
        run_id=prepared.request.run_id,
        scope_id=prepared.request.scope.scope_id,
        source=SourceType.PUBMED,
        ordinal=0,
        kind=SourceOperationKind.PUBMED_SEARCH,
        query_id=prepared.query_id,
        input_refs=(
            SourceOperationInputRef(
                role=SourceOperationInputRole.QUERY_PLAN,
                value=_search_request_identity(prepared),
            ),
        ),
    )


def plan_pubmed_operations(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    request: ResearchPubMedRequest,
    service: PubMedResearchService,
) -> tuple[RequiredSourceOperation, ...]:
    """Plan the exact search using local catalog resolution and no source I/O."""

    _require_exact_service(service)
    task = SourceTaskState.model_validate(_reconstruct(task))
    scope = ResearchScope.model_validate(_reconstruct(scope))
    attempt = SourceTaskAttemptRef.model_validate(_reconstruct(attempt))
    request = ResearchPubMedRequest.model_validate(_reconstruct(request))
    _validate_task_identity(task=task, scope=scope, attempt=attempt, request=request)
    if task.status is SourceTaskStatus.PENDING:
        if task.required_operations or attempt.attempt_number != 1:
            raise ValueError("pending PubMed planning requires an empty plan and first attempt")
    elif task.status is SourceTaskStatus.RUNNING:
        if task.active_attempt != attempt or task.attempts != attempt.attempt_number:
            raise ValueError("running PubMed planning requires the exact active task attempt")
        if not task.required_operations:
            raise ValueError("running PubMed planning requires a search operation")
    else:
        raise ValueError("PubMed planning accepts only pending or running tasks")

    # Catalog resolution is application planning only; this method performs no
    # PubMed execution, acquisition persistence, or report persistence.
    prepared = PubMedResearchService.prepare_collection(service, request)
    planned = (_planned_search_operation(prepared),)
    if task.status is SourceTaskStatus.RUNNING and task.required_operations[:1] != planned:
        raise ValueError("running PubMed task does not match the exact planned search")
    return planned


def _operation_result(
    *,
    operation: RequiredSourceOperation,
    attempt: SourceTaskAttemptRef,
    outcome: SourceOutcome,
    acquisition_intent_id: str,
    snapshot_id: str,
    evidence: tuple[tuple[str, str, str], ...] = (),
) -> TerminalSourceOperationResult:
    acquisition = source_operation_acquisition(
        operation=operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=acquisition_intent_id,
        outcome=outcome,
        snapshot_id=snapshot_id,
    )
    observations = tuple(
        source_operation_observation(
            operation=operation,
            acquisition=acquisition,
            evidence_id=evidence_id,
            content_hash=content_hash,
            locator_ref=locator_ref,
        )
        for evidence_id, content_hash, locator_ref in evidence
    )
    return TerminalSourceOperationResult(
        operation=operation,
        attempt=attempt,
        acquisition=acquisition,
        outcome=outcome,
        observations=observations,
    )


def _fetch_operations(
    *,
    prepared: PubMedCollectionPreparation,
    pmids: tuple[str, ...],
) -> tuple[RequiredSourceOperation, ...]:
    return tuple(
        required_source_operation(
            run_id=prepared.request.run_id,
            scope_id=prepared.request.scope.scope_id,
            source=SourceType.PUBMED,
            ordinal=ordinal,
            kind=SourceOperationKind.PUBMED_FETCH,
            query_id=prepared.query_id,
            input_refs=(
                SourceOperationInputRef(
                    role=SourceOperationInputRole.PUBMED_PMID,
                    value=pmid,
                ),
            ),
        )
        for ordinal, pmid in enumerate(pmids, start=1)
    )


def _terminal_result(
    *,
    request: ResearchPubMedRequest,
    attempt: SourceTaskAttemptRef,
    operations: tuple[RequiredSourceOperation, ...],
    results: tuple[TerminalSourceOperationResult, ...],
) -> CollectedEvidenceResult:
    terminal_outcome = canonical_terminal_source_outcome(operations, results)
    search_acquisition = results[0].acquisition
    terminal_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=derive_identity(
            "source-task-terminal-outcome",
            terminal_outcome,
        ),
        operation_acquisition_ids=tuple(item.acquisition.acquisition_id for item in results),
        acquisition=AcquisitionOutcomeRef(
            run_id=request.run_id,
            source=SourceType.PUBMED,
            acquisition_id=search_acquisition.acquisition_id,
            acquisition_intent_id=search_acquisition.acquisition_intent_id,
            acquisition_ordinal=0,
            operation="search",
            query_id=search_acquisition.query_id,
            source_outcome_id=search_acquisition.source_outcome_id,
            snapshot_id=search_acquisition.snapshot_id,
        ),
        outcome=terminal_outcome,
    )
    evidence_refs = tuple(
        observation.evidence_reference for result in results for observation in result.observations
    )
    return CollectedEvidenceResult(
        attempt=attempt,
        required_operations=operations,
        operation_results=results,
        terminal_outcome_ref=terminal_ref,
        evidence_refs=evidence_refs,
        limitations=(),
    )


def _terminal_progress_record(
    *,
    result: CollectedEvidenceResult,
    search_progress: PubMedSearchProgressRecord,
) -> PubMedTerminalProgressRecord:
    children: list[PubMedTerminalOperationRecord] = []
    for operation_result in result.operation_results:
        operation = operation_result.operation
        evidence = tuple(
            PubMedTerminalEvidenceRecord(
                evidence_id=item.evidence_id,
                snapshot_id=item.snapshot_id,
                content_hash=item.content_hash,
                locator_ref=item.locator_ref,
            )
            for item in operation_result.observations
        )
        children.append(
            PubMedTerminalOperationRecord(
                ordinal=operation.ordinal,
                operation=(
                    "search" if operation.kind is SourceOperationKind.PUBMED_SEARCH else "fetch"
                ),
                pmid=(
                    None
                    if operation.kind is SourceOperationKind.PUBMED_SEARCH
                    else operation.input_refs[0].value
                ),
                acquisition_intent_id=(operation_result.acquisition.acquisition_intent_id),
                snapshot_id=operation_result.acquisition.snapshot_id,
                source_outcome_id=operation_result.acquisition.source_outcome_id,
                source_outcome=operation_result.outcome,
                evidence=evidence,
            )
        )
    return PubMedTerminalProgressRecord.create(
        run_id=result.required_operations[0].run_id,
        scope_id=result.required_operations[0].scope_id,
        attempt_id=result.attempt.attempt_id,
        search_progress_record_id=search_progress.record_id,
        search_progress_content_hash=search_progress.content_hash,
        query_id=result.required_operations[0].query_id,
        fetch_pmids=tuple(item.pmid for item in children[1:] if item.pmid is not None),
        operations=tuple(children),
        terminal_outcome=result.terminal_outcome_ref.outcome,
        evidence=tuple(item for child in children for item in child.evidence),
        limitations=result.limitations,
    )


def _persist_terminal_result(
    *,
    result: CollectedEvidenceResult,
    search_progress: PubMedSearchProgressRecord,
    service: PubMedResearchService,
) -> CollectedEvidenceResult:
    receipt = _terminal_progress_record(result=result, search_progress=search_progress)
    persisted = PubMedResearchService.persist_terminal_progress(service, receipt)
    if persisted != receipt:
        raise ValueError("persisted PubMed terminal receipt changed exact content")
    return result


def collect_pubmed(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt: SourceTaskAttemptRef,
    request: ResearchPubMedRequest,
    service: PubMedResearchService,
) -> SourceTaskProgressResult | CollectedEvidenceResult:
    """Checkpoint search before executing any exact persisted PMID fetch suffix."""

    _require_exact_service(service)
    task = SourceTaskState.model_validate(_reconstruct(task))
    scope = ResearchScope.model_validate(_reconstruct(scope))
    attempt = SourceTaskAttemptRef.model_validate(_reconstruct(attempt))
    request = ResearchPubMedRequest.model_validate(_reconstruct(request))
    if task.status is not SourceTaskStatus.RUNNING:
        raise ValueError("PubMed collection requires a running source task")
    planned_operations = plan_pubmed_operations(
        task=task,
        scope=scope,
        attempt=attempt,
        request=request,
        service=service,
    )

    prepared = PubMedResearchService.prepare_collection(service, request)
    search_operation = _planned_search_operation(prepared)
    if planned_operations != (search_operation,):
        raise ValueError("PubMed query planning drifted before search execution")
    if not task.operation_results:
        if task.required_operations != (search_operation,):
            raise ValueError("initial PubMed collection requires only the frozen search")
        searched: PubMedSearchCollection = PubMedResearchService.collect_search(service, prepared)
        if searched.query_id != search_operation.query_id:
            raise ValueError("PubMed persisted search changed the frozen query identity")
        progress_record = searched.progress_record
        pmids = progress_record.pmids
        if (
            pmids != searched.response.pmids
            or searched.response.source_outcome.valid_result_count != len(set(pmids))
        ):
            raise ValueError("PubMed search candidate count must equal unique returned PMIDs")
        operations = (search_operation, *_fetch_operations(prepared=prepared, pmids=pmids))
        search_result = _operation_result(
            operation=search_operation,
            attempt=attempt,
            outcome=searched.response.source_outcome,
            acquisition_intent_id=searched.acquisition.acquisition_intent_id,
            snapshot_id=searched.acquisition.snapshot_id,
        )
        if len(operations) > 1:
            return SourceTaskProgressResult(
                attempt=attempt,
                required_operations=operations,
                operation_results=(search_result,),
            )
        return _persist_terminal_result(
            result=_terminal_result(
                request=request,
                attempt=attempt,
                operations=operations,
                results=(search_result,),
            ),
            search_progress=progress_record,
            service=service,
        )

    if len(task.operation_results) != 1:
        raise ValueError("resumed PubMed collection requires exactly one persisted search result")
    search_result = task.operation_results[0]
    if search_result.operation != search_operation:
        raise ValueError("resumed PubMed search result changed the exact planned search")
    pmids = tuple(item.input_refs[0].value for item in task.required_operations[1:])
    persisted_progress = PubMedResearchService.load_search_progress(
        service,
        run_id=request.run_id,
        acquisition_intent_id=search_result.acquisition.acquisition_intent_id,
    )
    if (
        persisted_progress.run_id != request.run_id
        or persisted_progress.scope_id != request.scope.scope_id
        or persisted_progress.query != prepared.query
        or persisted_progress.query_id != prepared.query_id
        or persisted_progress.acquisition_intent_id
        != search_result.acquisition.acquisition_intent_id
        or persisted_progress.snapshot_id != search_result.acquisition.snapshot_id
        or persisted_progress.manifest_id != search_result.acquisition.snapshot_id
        or persisted_progress.pmids != pmids
        or persisted_progress.search_source_outcome_id
        != search_result.acquisition.source_outcome_id
        or persisted_progress.valid_result_count != search_result.outcome.valid_result_count
    ):
        raise ValueError("persisted PubMed search progress differs from checkpointed exact state")
    expected_operations = (
        search_operation,
        *_fetch_operations(prepared=prepared, pmids=pmids),
    )
    if task.required_operations != expected_operations:
        raise ValueError("resumed PubMed fetch suffix differs from its exact PMID plan")
    if search_result.outcome.valid_result_count != len(set(pmids)):
        raise ValueError("persisted PubMed search count must equal unique PMID fetch inputs")
    search_response = SearchPubMedResponse(
        query=prepared.query,
        query_id=prepared.query_id,
        pmids=pmids,
        total_available=None,
        source_outcome=search_result.outcome,
    )
    stage = PubMedResearchService.collect_fetch_stage(
        service,
        prepared=prepared,
        search_response=search_response,
    )
    if tuple(item.pmid for item in stage.fetches) != pmids:
        raise ValueError("PubMed fetch execution changed the checkpointed PMID suffix")

    results: list[TerminalSourceOperationResult] = [search_result]
    for operation, fetched in zip(expected_operations[1:], stage.fetches, strict=True):
        evidence: tuple[tuple[str, str, str], ...] = ()
        if fetched.publication is not None:
            binding = fetched.acquisition.publication_bindings[0]
            if (
                fetched.publication.provenance.snapshot_id != binding.snapshot_id
                or fetched.publication.content_hash != binding.publication_artifact_id
            ):
                raise ValueError("PubMed evidence must bind the exact persisted publication")
            evidence = (
                (
                    fetched.publication.publication_version_id,
                    binding.publication_artifact_id,
                    fetched.publication.provenance.source_lookup_key,
                ),
            )
        results.append(
            _operation_result(
                operation=operation,
                attempt=attempt,
                outcome=fetched.source_outcome,
                acquisition_intent_id=fetched.acquisition.acquisition_intent_id,
                snapshot_id=fetched.acquisition.snapshot_id,
                evidence=evidence,
            )
        )
    return _persist_terminal_result(
        result=_terminal_result(
            request=request,
            attempt=attempt,
            operations=expected_operations,
            results=tuple(results),
        ),
        search_progress=persisted_progress,
        service=service,
    )


def validate_pubmed_terminal_task(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    request: ResearchPubMedRequest,
    service: PubMedResearchService,
) -> None:
    """Replay durable PubMed receipts and require exact terminal checkpoint equality."""

    _require_exact_service(service)
    task = SourceTaskState.model_validate(_reconstruct(task))
    scope = ResearchScope.model_validate(_reconstruct(scope))
    request = ResearchPubMedRequest.model_validate(_reconstruct(request))
    if request.scope != scope:
        raise ValueError("PubMed terminal validation requires the exact current scope")
    if task.status is not SourceTaskStatus.TERMINAL or task.terminal_outcome_ref is None:
        raise ValueError("PubMed terminal validation requires one terminal source task")
    if task.source is not SourceType.PUBMED or task.task_id != source_task_id(
        request.run_id, SourceType.PUBMED
    ):
        raise ValueError("PubMed terminal validation requires the exact current run task")
    prepared = PubMedResearchService.prepare_collection(service, request)
    search_operation = _planned_search_operation(prepared)
    if task.required_operations[:1] != (search_operation,):
        raise ValueError("PubMed terminal search plan differs from canonical request")
    pmids = tuple(item.input_refs[0].value for item in task.required_operations[1:])
    expected_operations = (
        search_operation,
        *_fetch_operations(prepared=prepared, pmids=pmids),
    )
    if task.required_operations != expected_operations:
        raise ValueError("PubMed terminal fetch plan differs from exact PMID inputs")
    search_result = task.operation_results[0]
    search_progress = PubMedResearchService.load_search_progress(
        service,
        run_id=request.run_id,
        acquisition_intent_id=search_result.acquisition.acquisition_intent_id,
    )
    if (
        search_progress.scope_id != scope.scope_id
        or search_progress.query != prepared.query
        or search_progress.query_id != prepared.query_id
        or search_progress.pmids != pmids
        or search_progress.snapshot_id != search_result.acquisition.snapshot_id
        or search_progress.manifest_id != search_result.acquisition.snapshot_id
        or search_progress.search_source_outcome_id != search_result.acquisition.source_outcome_id
        or search_progress.valid_result_count != search_result.outcome.valid_result_count
    ):
        raise ValueError("PubMed terminal search receipt differs from checkpoint state")
    attempt = search_result.attempt
    checkpoint = CollectedEvidenceResult(
        attempt=attempt,
        required_operations=task.required_operations,
        operation_results=task.operation_results,
        terminal_outcome_ref=task.terminal_outcome_ref,
        evidence_refs=task.evidence_refs,
        limitations=task.limitations,
    )
    expected_receipt = _terminal_progress_record(
        result=checkpoint,
        search_progress=search_progress,
    )
    persisted_receipt = PubMedResearchService.load_terminal_progress(
        service,
        run_id=request.run_id,
        attempt_id=attempt.attempt_id,
    )
    if persisted_receipt != expected_receipt:
        raise ValueError("PubMed terminal receipt differs from exact checkpoint task")
