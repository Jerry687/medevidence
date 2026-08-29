"""Offline tests for explicit DailyMed and FAERS source capability adapters."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    AcquisitionOutcomeRef,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DailyMedCandidateLabel,
    DailyMedMarketingState,
    DailyMedResolution,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    LabelSelectionDecision,
    M1BResearchRequestV1,
    QueryBounds,
    ResearchScope,
    ResultBounds,
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
    SourceTaskState,
    SourceTaskStatus,
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    source_task_attempt,
)
from medevidence.orchestration.dailymed_faers_capability import (
    CanonicalDailyMedProjectionAuthority,
    CanonicalFaersProjectionAuthority,
    DailyMedRequestProjection,
    FaersRequestProjection,
    SourceTaskTerminalProjection,
    collect_dailymed_capability,
    collect_faers_capability,
    plan_dailymed_operations,
    plan_faers_operations,
)
from medevidence.orchestration.source_task_projection import (
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
)
from medevidence.tools.contracts import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    FaersAggregateExecution,
    PersistedFaersAggregate,
)
from medevidence.tools.dailymed import (
    DailyMedDiscoveryExecutionProjection,
    DailyMedDiscoveryProvenanceProjection,
    DailyMedFetchExecutionProjection,
    DailyMedFetchProvenanceProjection,
    DailyMedSectionEvidenceProjection,
)
from medevidence.tools.faers import (
    FaersAggregateExecutionProjection,
    FaersAggregateProvenanceProjection,
    FaersBucketEvidenceProjection,
)
from medevidence.tools.ports import (
    DailyMedExecutionPort,
    FaersExecutionPort,
    FaersPersistencePort,
)

RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
SETID = "11111111-1111-1111-1111-111111111111"
BOUNDS = ExecutionBounds(
    max_query_characters=512,
    max_pages=5,
    max_records=100,
    max_payload_bytes=5_242_880,
    max_total_seconds=30,
)


def _scope(source: SourceType, *, drug_ids: tuple[str, ...] = ("drug:test",)) -> ResearchScope:
    return ResearchScope.create(
        drugs=tuple(
            DrugConcept(concept_id=drug_id, preferred_term=f"Test drug {ordinal}")
            for ordinal, drug_id in enumerate(drug_ids)
        ),
        adverse_reactions=(
            AdverseEventConcept(concept_id="reaction:test", preferred_term="Test reaction"),
        ),
        date_range=None,
        selected_sources=(source,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=5,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _outcome(
    source: SourceType,
    query_id: str,
    *,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
    count: int = 1,
    warning_codes: tuple[str, ...] = (),
) -> SourceOutcome:
    if coverage is not CoverageStatus.COMPLETE and not warning_codes:
        warning_codes = ("source_incomplete",)
    return SourceOutcome(
        source=source,
        query_id=query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=BOUNDS,
        valid_result_count=count,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=warning_codes,
        failure_id=("failure:synthetic" if execution is ExecutionStatus.FAILED else None),
    )


def _running_task(
    source: SourceType,
    scope: ResearchScope,
    requests: tuple[DailyMedDiscoveryRequest, ...] | tuple[FaersAggregateRequestV1, ...],
):
    kind = {
        SourceType.DAILYMED: SourceOperationKind.DAILYMED_DISCOVERY,
        SourceType.FAERS: SourceOperationKind.FAERS_AGGREGATE,
    }[source]
    operations = []
    for ordinal, request in enumerate(requests):
        if isinstance(request, DailyMedDiscoveryRequest):
            query_id = request.query_id
            input_refs = (
                SourceOperationInputRef(
                    role=SourceOperationInputRole.REQUEST,
                    value=derive_identity("dailymed-discovery-request", request),
                ),
            )
        else:
            query = FaersAggregateQueryV1.create(request)
            query_id = query.query_id
            input_refs = (
                SourceOperationInputRef(
                    role=SourceOperationInputRole.REQUEST,
                    value=derive_identity("faers-aggregate-request", request),
                ),
            )
        operations.append(
            required_source_operation(
                run_id=RUN_ID,
                scope_id=scope.scope_id,
                source=source,
                ordinal=ordinal,
                kind=kind,
                query_id=query_id,
                input_refs=input_refs,
            )
        )
    operations = tuple(operations)
    task_id = operations[0].task_id
    attempt = source_task_attempt(task_id, 1)
    task = SourceTaskState(
        task_id=task_id,
        source=source,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    return task, attempt


def _terminal_projection(
    *,
    task: SourceTaskState,
    scope: ResearchScope,
    attempt,
    required_operations,
    operation_results,
) -> SourceTaskTerminalProjection:
    outcome = canonical_terminal_source_outcome(required_operations, operation_results)
    representative = operation_results[0].acquisition
    return SourceTaskTerminalProjection(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        terminal_outcome_ref=TerminalSourceOutcomeRef(
            terminal_outcome_id=derive_identity("source-task-terminal-outcome", outcome),
            operation_acquisition_ids=tuple(
                item.acquisition.acquisition_id for item in operation_results
            ),
            acquisition=AcquisitionOutcomeRef(
                run_id=RUN_ID,
                source=task.source,
                acquisition_id=representative.acquisition_id,
                acquisition_intent_id=representative.acquisition_intent_id,
                acquisition_ordinal=representative.ordinal,
                operation="search",
                query_id=representative.query_id,
                source_outcome_id=representative.source_outcome_id,
                snapshot_id=representative.snapshot_id,
            ),
            outcome=outcome,
        ),
        limitations=(
            FAERS_MANDATORY_LIMITATIONS
            if task.source is SourceType.FAERS
            else ("Synthetic DailyMed limitation.",)
        ),
    )


def _selection_request(
    drug_concept_id: str = "drug:test",
) -> DailyMedSelectionRequestV1:
    return DailyMedSelectionRequestV1(
        drug_concept_id=drug_concept_id,
        requested_section_codes=("34084-4",),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )


def _dailymed_candidate(query_id: str) -> DailyMedCandidateLabel:
    return DailyMedCandidateLabel.create(
        run_id=RUN_ID,
        attempt_id="attempt:00000000-0000-4000-8000-000000000001",
        acquisition_id=f"acquisition:{query_id}",
        acquisition_ordinal=0,
        acquisition_intent_id="acquisition-intent:sha256:" + "1" * 64,
        setid=SETID,
        spl_versions=("3",),
        ingredients=("ingredient",),
        brand_name="Brand",
        generic_name="Generic",
        application_number="APP-1",
        product_id="PRODUCT-1",
        labeler="Labeler",
        dosage_forms=("tablet",),
        routes=("oral",),
        strengths=("10 mg",),
        ndcs=("00000-0000",),
        marketing_state=DailyMedMarketingState.ACTIVE,
        effective_date=None,
        published_date=None,
        available_section_codes=("34084-4",),
        discovery_query_id=query_id,
        candidate_set_snapshot_id=f"snapshot:{query_id}",
        discovery_manifest_id=f"artifact:{query_id}:manifest",
        member_ordinal=0,
        link_id="artifact-link:sha256:" + "2" * 64,
        raw_artifact_id=f"artifact:{query_id}:candidate",
        raw_content_hash="sha256:" + "3" * 64,
        candidate_ordinal=0,
    )


def _discovery_bundle(
    request: DailyMedDiscoveryRequest,
    *,
    selected: bool,
):
    if selected:
        candidate = _dailymed_candidate(request.query_id)
        outcome = _outcome(SourceType.DAILYMED, request.query_id)
        decision = LabelSelectionDecision.from_discovery(
            candidates=(candidate,),
            outcome=outcome,
            resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
            source_outcome_id=f"source-outcome:{request.query_id}",
            discovery_manifest_content_hash="sha256:" + "4" * 64,
            decided_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert decision is not None
        response = DailyMedDiscoveryResponse(
            selection_request=request.selection_request,
            query_id=request.query_id,
            source_outcome_id=f"source-outcome:{request.query_id}",
            source_outcome=outcome,
            candidate_set_snapshot_id=candidate.candidate_set_snapshot_id,
            discovery_manifest_id=candidate.discovery_manifest_id,
            candidate_ids=(candidate.candidate_id,),
            decision_id=decision.decision_id,
            selection_status=decision.status,
            selected_candidate_id=decision.selected_candidate_id,
            selected_setid=decision.selected_setid,
            selected_spl_version=decision.selected_spl_version,
        )
        return response, (candidate,), decision

    outcome = _outcome(
        SourceType.DAILYMED,
        request.query_id,
        result=ResultStatus.NO_MATCH,
        count=0,
    )
    decision = LabelSelectionDecision.no_candidate_from_discovery(
        run_id=RUN_ID,
        attempt_id="attempt:00000000-0000-4000-8000-000000000001",
        acquisition_id=f"acquisition:{request.query_id}",
        acquisition_ordinal=0,
        acquisition_intent_id="acquisition-intent:sha256:" + "1" * 64,
        candidate_set_snapshot_id=f"snapshot:{request.query_id}",
        discovery_manifest_id=f"artifact:{request.query_id}:manifest",
        discovery_manifest_content_hash="sha256:" + "4" * 64,
        source_outcome_id=f"source-outcome:{request.query_id}",
        outcome=outcome,
        decided_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
    )
    response = DailyMedDiscoveryResponse(
        selection_request=request.selection_request,
        query_id=request.query_id,
        source_outcome_id=f"source-outcome:{request.query_id}",
        source_outcome=outcome,
        candidate_set_snapshot_id=decision.candidate_set_snapshot_id,
        discovery_manifest_id=decision.discovery_manifest_id,
        candidate_ids=(),
        decision_id=decision.decision_id,
        selection_status=decision.status,
    )
    return response, (), decision


class _DailyExecution:
    def __init__(self, selected_queries: set[str], events: list[str]) -> None:
        self.selected_queries = selected_queries
        self.events = events
        self.discovery_calls = 0
        self.fetch_calls = 0
        self.fetch_requests: list[DailyMedFetchRequest] = []

    def discover(self, request: DailyMedDiscoveryRequest):
        self.events.append(f"discover:{request.query_id}")
        self.discovery_calls += 1
        return _discovery_bundle(request, selected=request.query_id in self.selected_queries)

    def fetch(self, request: DailyMedFetchRequest) -> DailyMedFetchResponse:
        self.events.append(f"fetch:{request.query_id}")
        self.fetch_calls += 1
        self.fetch_requests.append(request)
        return DailyMedFetchResponse(
            request=request,
            source_outcome_id=f"source-outcome:{request.query_id}:fetch",
            source_outcome=_outcome(SourceType.DAILYMED, request.query_id),
            fetch_snapshot_id=f"snapshot:{request.query_id}:fetch",
            fetch_manifest_id=f"artifact:{request.query_id}:fetch-manifest",
            retained_response_id=f"retained:{request.query_id}",
            label_version_id=f"label-version:{request.query_id}",
            section_ids=(f"section:{request.query_id}",),
        )


class _DailyProjection:
    def __init__(
        self,
        requests: tuple[DailyMedDiscoveryRequest, ...],
        events: list[str],
        *,
        foreign_run: bool = False,
        stale_fetch: bool = False,
    ) -> None:
        self.requests = requests
        self.events = events
        self.foreign_run = foreign_run
        self.stale_fetch = stale_fetch

    def freeze_discovery_requests(self, *, task, scope, attempt):
        self.events.append("freeze_discoveries")
        return DailyMedRequestProjection(
            run_id=("run:00000000-0000-4000-8000-000000000002" if self.foreign_run else RUN_ID),
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            requests=self.requests,
        )

    def project_discovery(self, *, task, scope, attempt, request, response):
        self.events.append(f"project_discovery:{request.query_id}")
        return DailyMedDiscoveryExecutionProjection(
            run_id=RUN_ID,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            response=response,
            acquisition=AcquisitionOutcomeRef(
                run_id=RUN_ID,
                source=SourceType.DAILYMED,
                acquisition_id=f"acquisition:{request.query_id}:discovery",
                acquisition_intent_id="acquisition-intent:sha256:" + "5" * 64,
                acquisition_ordinal=0,
                operation="search",
                query_id=request.query_id,
                source_outcome_id=response.source_outcome_id,
                snapshot_id=response.candidate_set_snapshot_id,
            ),
        )

    def freeze_fetch_request(self, *, task, scope, attempt, discovery):
        self.events.append(f"freeze_fetch:{discovery.response.query_id}")
        response = discovery.response
        return DailyMedFetchRequest(
            selection_request=response.selection_request,
            query_id=response.query_id,
            decision_id=response.decision_id,
            selected_candidate_id=response.selected_candidate_id,
            selected_setid=response.selected_setid,
            selected_spl_version=("4" if self.stale_fetch else response.selected_spl_version),
        )

    def project_fetch(self, *, task, scope, attempt, request, response):
        self.events.append(f"project_fetch:{request.query_id}")
        return DailyMedFetchExecutionProjection(
            run_id=RUN_ID,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            response=response,
            acquisition=AcquisitionOutcomeRef(
                run_id=RUN_ID,
                source=SourceType.DAILYMED,
                acquisition_id=f"acquisition:{request.query_id}:fetch",
                acquisition_intent_id="acquisition-intent:sha256:" + "6" * 64,
                acquisition_ordinal=1,
                operation="fetch",
                query_id=request.query_id,
                source_outcome_id=response.source_outcome_id,
                snapshot_id=response.fetch_snapshot_id,
            ),
            section_evidence=(
                DailyMedSectionEvidenceProjection(
                    section_id=response.section_ids[0],
                    evidence_id=f"evidence:{request.query_id}",
                    content_hash="sha256:" + "7" * 64,
                    locator_ref=f"locator:{request.query_id}",
                ),
            ),
        )

    def reconstruct_fetch_request(self, *, task, scope, attempt, operation):
        selection = next(
            item.selection_request for item in self.requests if item.query_id == operation.query_id
        )
        values = {item.role: item.value for item in operation.input_refs}
        return DailyMedFetchRequest(
            selection_request=selection,
            query_id=operation.query_id,
            decision_id=values[SourceOperationInputRole.DAILYMED_DECISION],
            selected_candidate_id=values[SourceOperationInputRole.CANDIDATE],
            selected_setid=values[SourceOperationInputRole.SETID],
            selected_spl_version=values[SourceOperationInputRole.SPL_VERSION],
        )

    def project_terminal(self, **values):
        self.events.append("project_terminal")
        return _terminal_projection(**values)


def _daily_request(query_id: str, drug_concept_id: str = "drug:test") -> DailyMedDiscoveryRequest:
    return DailyMedDiscoveryRequest(
        selection_request=_selection_request(drug_concept_id), query_id=query_id
    )


def _resume_dailymed_progress(
    task: SourceTaskState,
    progress: SourceTaskProgressResult,
) -> SourceTaskState:
    return SourceTaskState(
        task_id=task.task_id,
        source=task.source,
        required_operations=progress.required_operations,
        operation_results=progress.operation_results,
        status=SourceTaskStatus.RUNNING,
        attempts=task.attempts,
        active_attempt=task.active_attempt,
    )


def _terminal_task_from_collection(
    task: SourceTaskState,
    result: CollectedEvidenceResult,
) -> SourceTaskState:
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


def test_dailymed_complete_no_match_has_no_fetch_or_evidence() -> None:
    scope = _scope(SourceType.DAILYMED)
    request = _daily_request("query:dailymed:zero")
    task, attempt = _running_task(SourceType.DAILYMED, scope, (request,))
    events: list[str] = []
    execution = _DailyExecution(set(), events)
    projection = _DailyProjection((request,), events)

    result = collect_dailymed_capability(
        task,
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )

    assert result.terminal_outcome_ref.outcome.result_status is ResultStatus.NO_MATCH
    assert result.evidence_refs == ()
    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 0
    assert events == [
        "freeze_discoveries",
        "discover:query:dailymed:zero",
        "project_discovery:query:dailymed:zero",
        "project_terminal",
    ]


def test_dailymed_plan_helper_is_pure_for_pending_task() -> None:
    scope = _scope(SourceType.DAILYMED)
    request = _daily_request("query:dailymed:plan")
    running, attempt = _running_task(SourceType.DAILYMED, scope, (request,))
    pending = SourceTaskState(
        task_id=running.task_id,
        source=running.source,
    )
    events: list[str] = []

    operations = plan_dailymed_operations(
        pending,
        scope,
        attempt,
        projection=_DailyProjection((request,), events),
    )

    assert operations == running.required_operations
    assert events == ["freeze_discoveries"]


def test_dailymed_selected_fetch_is_frozen_adjacent_and_projects_exact_section() -> None:
    scope = _scope(SourceType.DAILYMED)
    request = _daily_request("query:dailymed:selected")
    task, attempt = _running_task(SourceType.DAILYMED, scope, (request,))
    events: list[str] = []
    execution = _DailyExecution({request.query_id}, events)
    projection = _DailyProjection((request,), events)

    progress = collect_dailymed_capability(
        task,
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(progress, SourceTaskProgressResult)
    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 0
    result = collect_dailymed_capability(
        _resume_dailymed_progress(task, progress),
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(result, CollectedEvidenceResult)
    assert tuple(item.kind for item in result.required_operations) == (
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_FETCH,
    )
    assert len(result.evidence_refs) == 1
    assert result.evidence_refs[0].evidence_id == f"evidence:{request.query_id}"
    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 1


def test_dailymed_foreign_request_projection_fails_before_source_effect() -> None:
    scope = _scope(SourceType.DAILYMED)
    request = _daily_request("query:dailymed:foreign")
    task, attempt = _running_task(SourceType.DAILYMED, scope, (request,))
    events: list[str] = []
    execution = _DailyExecution(set(), events)

    with pytest.raises(ValueError, match="foreign or stale"):
        collect_dailymed_capability(
            task,
            scope,
            attempt,
            projection=_DailyProjection((request,), events, foreign_run=True),
            execution=cast(DailyMedExecutionPort, execution),
        )

    assert execution.discovery_calls == execution.fetch_calls == 0
    assert events == ["freeze_discoveries"]


def test_dailymed_stale_fetch_fails_before_fetch_effect() -> None:
    scope = _scope(SourceType.DAILYMED)
    request = _daily_request("query:dailymed:stale-fetch")
    task, attempt = _running_task(SourceType.DAILYMED, scope, (request,))
    events: list[str] = []
    execution = _DailyExecution({request.query_id}, events)

    with pytest.raises(ValueError, match="selected discovery path"):
        collect_dailymed_capability(
            task,
            scope,
            attempt,
            projection=_DailyProjection((request,), events, stale_fetch=True),
            execution=cast(DailyMedExecutionPort, execution),
        )

    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 0


def test_dailymed_mixed_selected_and_no_match_uses_discovery_then_fetch_plan() -> None:
    scope = _scope(SourceType.DAILYMED, drug_ids=("drug:a", "drug:b"))
    requests = (
        _daily_request("query:dailymed:a", "drug:a"),
        _daily_request("query:dailymed:b", "drug:b"),
    )
    task, attempt = _running_task(SourceType.DAILYMED, scope, requests)
    events: list[str] = []
    execution = _DailyExecution({requests[0].query_id}, events)
    projection = _DailyProjection(requests, events)

    progress = collect_dailymed_capability(
        task,
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(progress, SourceTaskProgressResult)
    assert execution.discovery_calls == 2
    assert execution.fetch_calls == 0
    result = collect_dailymed_capability(
        _resume_dailymed_progress(task, progress),
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(result, CollectedEvidenceResult)
    assert tuple(item.kind for item in result.required_operations) == (
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_FETCH,
    )
    assert result.terminal_outcome_ref.outcome.result_status is ResultStatus.MATCHES
    assert execution.discovery_calls == 2
    assert execution.fetch_calls == 1


def test_dailymed_freezes_complete_selected_fetch_suffix_before_first_fetch() -> None:
    scope = _scope(SourceType.DAILYMED, drug_ids=("drug:a", "drug:b"))
    requests = (
        _daily_request("query:dailymed:a", "drug:a"),
        _daily_request("query:dailymed:b", "drug:b"),
    )
    task, attempt = _running_task(SourceType.DAILYMED, scope, requests)
    events: list[str] = []
    execution = _DailyExecution({item.query_id for item in requests}, events)
    projection = _DailyProjection(requests, events)

    progress = collect_dailymed_capability(
        task,
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(progress, SourceTaskProgressResult)
    assert tuple(item.kind for item in progress.required_operations) == (
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_FETCH,
        SourceOperationKind.DAILYMED_FETCH,
    )
    assert not any(event.startswith("fetch:") for event in events)
    assert execution.discovery_calls == 2
    result = collect_dailymed_capability(
        _resume_dailymed_progress(task, progress),
        scope,
        attempt,
        projection=projection,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(result, CollectedEvidenceResult)
    assert execution.discovery_calls == 2
    assert execution.fetch_calls == 2


def _faers_request(strategy: FaersIdentityStrategy) -> FaersAggregateRequestV1:
    return FaersAggregateRequestV1(
        drug_concept_id="drug:test",
        identity_strategy=strategy,
        identity_exact_value="SYNTHETIC INGREDIENT",
        pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
        inclusive_date_range=FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)
        ),
        statistical_unit="provider_count_occurrence",
        execution_bounds=FaersExecutionBoundsV1(
            max_date_difference_days=365,
            max_inclusive_calendar_dates=366,
        ),
    )


def _faers_execution(
    request: FaersAggregateRequestV1,
    *,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
) -> FaersAggregateExecution:
    query = FaersAggregateQueryV1.create(request)
    buckets = (
        (
            FaersAggregateBucketV1(
                query_id=query.query_id,
                bucket_ordinal=0,
                reaction_pt="NAUSEA",
                report_count=7,
                identity_stratum=query.identity_stratum,
            ),
        )
        if result is ResultStatus.MATCHES
        else ()
    )
    aggregate = FaersAggregateResult(
        query=query,
        buckets=buckets,
        source_outcome=_outcome(
            SourceType.FAERS,
            query.query_id,
            execution=execution,
            coverage=coverage,
            result=result,
            count=len(buckets),
        ),
        retrieved_at_utc=datetime(2025, 2, 1, tzinfo=UTC),
        provider_as_of_utc=None,
        snapshot_id=f"snapshot:{query.query_id}",
        manifest_id=f"artifact:{query.query_id}:manifest",
    )
    return FaersAggregateExecution(
        request=request,
        acquisition_outcome_ref=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.FAERS,
            acquisition_id=f"acquisition:{query.query_id}",
            acquisition_intent_id="acquisition-intent:sha256:" + "8" * 64,
            acquisition_ordinal=0,
            operation="search",
            query_id=query.query_id,
            source_outcome_id=f"source-outcome:{query.query_id}",
            snapshot_id=aggregate.snapshot_id,
        ),
        result=aggregate,
    )


class _FaersExecution:
    def __init__(self, values: dict[str, FaersAggregateExecution], events: list[str]) -> None:
        self.values = values
        self.events = events
        self.calls = 0

    def execute(self, query: FaersAggregateQueryV1) -> FaersAggregateExecution:
        self.events.append(f"execute:{query.query_id}")
        self.calls += 1
        return self.values[query.query_id]


class _FaersPersistence:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    def persist(self, execution: FaersAggregateExecution) -> PersistedFaersAggregate:
        self.events.append(f"persist:{execution.result.query.query_id}")
        self.calls += 1
        return PersistedFaersAggregate(execution=execution)


class _FaersProjection:
    def __init__(
        self,
        requests: tuple[FaersAggregateRequestV1, ...],
        events: list[str],
        *,
        foreign_run: bool = False,
    ) -> None:
        self.requests = requests
        self.events = events
        self.foreign_run = foreign_run

    def freeze_requests(self, *, task, scope, attempt):
        self.events.append("freeze_faers")
        return FaersRequestProjection(
            run_id=("run:00000000-0000-4000-8000-000000000002" if self.foreign_run else RUN_ID),
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            requests=self.requests,
        )

    def project_execution(self, *, task, scope, attempt, execution):
        query_id = execution.result.query.query_id
        self.events.append(f"project:{query_id}")
        evidence = tuple(
            FaersBucketEvidenceProjection(
                bucket_ordinal=bucket.bucket_ordinal,
                evidence_id=f"evidence:{query_id}:{bucket.bucket_ordinal}",
                content_hash="sha256:" + str(bucket.bucket_ordinal + 1) * 64,
                locator_ref=f"locator:{query_id}:{bucket.bucket_ordinal}",
            )
            for bucket in execution.result.buckets
        )
        return FaersAggregateExecutionProjection(
            run_id=RUN_ID,
            scope_id=scope.scope_id,
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            execution=execution,
            bucket_evidence=evidence,
        )

    def project_terminal(self, **values):
        self.events.append("project_terminal")
        return _terminal_projection(**values)


def _faers_context(requests: tuple[FaersAggregateRequestV1, ...], events: list[str]):
    task, attempt = _running_task(SourceType.FAERS, _scope(SourceType.FAERS), requests)
    values = {
        FaersAggregateQueryV1.create(item).query_id: _faers_execution(item) for item in requests
    }
    execution = _FaersExecution(values, events)
    persistence = _FaersPersistence(events)
    return task, attempt, execution, persistence


def test_faers_complete_no_match_is_zero_evidence_with_mandatory_warning() -> None:
    request = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    events: list[str] = []
    task, attempt, execution, persistence = _faers_context((request,), events)
    query_id = FaersAggregateQueryV1.create(request).query_id
    execution.values[query_id] = _faers_execution(request, result=ResultStatus.NO_MATCH)

    result = collect_faers_capability(
        task,
        _scope(SourceType.FAERS),
        attempt,
        projection=_FaersProjection((request,), events),
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, persistence),
    )

    assert result.evidence_refs == ()
    assert result.terminal_outcome_ref.outcome.result_status is ResultStatus.NO_MATCH
    assert result.terminal_outcome_ref.outcome.warning_codes == ("faers_mandatory_limitations",)
    assert execution.calls == persistence.calls == 1
    assert events[0] == "freeze_faers"


def test_faers_plan_helper_is_pure_for_pending_task() -> None:
    request = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    events: list[str] = []
    running, attempt, execution, persistence = _faers_context((request,), events)
    pending = SourceTaskState(
        task_id=running.task_id,
        source=running.source,
    )

    operations = plan_faers_operations(
        pending,
        _scope(SourceType.FAERS),
        attempt,
        projection=_FaersProjection((request,), events),
    )

    assert operations == running.required_operations
    assert execution.calls == persistence.calls == 0
    assert events == ["freeze_faers"]


def test_faers_mixed_failure_is_not_hidden_and_all_effects_run_once() -> None:
    requests = (
        _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE),
        _faers_request(FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT),
    )
    events: list[str] = []
    task, attempt, execution, persistence = _faers_context(requests, events)
    failed_query = FaersAggregateQueryV1.create(requests[1]).query_id
    execution.values[failed_query] = _faers_execution(
        requests[1],
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        result=ResultStatus.INDETERMINATE,
    )

    result = collect_faers_capability(
        task,
        _scope(SourceType.FAERS),
        attempt,
        projection=_FaersProjection(requests, events),
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, persistence),
    )

    outcome = result.terminal_outcome_ref.outcome
    assert (
        outcome.execution_status,
        outcome.coverage_status,
        outcome.result_status,
    ) == (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
    )
    assert outcome.warning_codes == (
        "faers_mandatory_limitations",
        "source_incomplete",
    )
    assert execution.calls == persistence.calls == 2


def test_faers_foreign_projection_fails_before_execution_or_persistence() -> None:
    request = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    events: list[str] = []
    task, attempt, execution, persistence = _faers_context((request,), events)

    with pytest.raises(ValueError, match="foreign or stale"):
        collect_faers_capability(
            task,
            _scope(SourceType.FAERS),
            attempt,
            projection=_FaersProjection((request,), events, foreign_run=True),
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )

    assert execution.calls == persistence.calls == 0
    assert events == ["freeze_faers"]


def test_faers_substituted_exact_request_fails_before_any_effect() -> None:
    planned = _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE)
    substituted = _faers_request(FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT)
    events: list[str] = []
    task, attempt, execution, persistence = _faers_context((planned,), events)

    with pytest.raises(ValueError, match="differs from the pre-execution task plan"):
        collect_faers_capability(
            task,
            _scope(SourceType.FAERS),
            attempt,
            projection=_FaersProjection((substituted,), events),
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )

    assert execution.calls == persistence.calls == 0
    assert events == ["freeze_faers"]


class _CanonicalDailyProvenance:
    def __init__(self) -> None:
        self.progress: dict[tuple[str, str], DailyMedDiscoveryExecutionProjection] = {}
        self.fetch_progress: dict[tuple[str, str], DailyMedFetchExecutionProjection] = {}

    def load_discovery(self, *, request, response):
        persisted = DailyMedDiscoveryProvenanceProjection(
            run_id=RUN_ID,
            scope_id=self.scope_id,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            acquisition=AcquisitionOutcomeRef(
                run_id=RUN_ID,
                source=SourceType.DAILYMED,
                acquisition_id=f"acquisition:{request.query_id}:persisted-discovery",
                acquisition_intent_id="acquisition-intent:sha256:" + "a" * 64,
                acquisition_ordinal=0,
                operation="search",
                query_id=request.query_id,
                source_outcome_id=response.source_outcome_id,
                snapshot_id=response.candidate_set_snapshot_id,
            ),
        )
        self.progress[(persisted.acquisition.acquisition_intent_id, request.query_id)] = (
            DailyMedDiscoveryExecutionProjection(
                run_id=RUN_ID,
                scope_id=self.scope_id,
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                response=response,
                acquisition=persisted.acquisition,
            )
        )
        return persisted

    def load_fetch(self, *, request, response):
        persisted = DailyMedFetchProvenanceProjection(
            run_id=RUN_ID,
            scope_id=self.scope_id,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            acquisition=AcquisitionOutcomeRef(
                run_id=RUN_ID,
                source=SourceType.DAILYMED,
                acquisition_id=f"acquisition:{request.query_id}:persisted-fetch",
                acquisition_intent_id="acquisition-intent:sha256:" + "b" * 64,
                acquisition_ordinal=1,
                operation="fetch",
                query_id=request.query_id,
                source_outcome_id=response.source_outcome_id,
                snapshot_id=response.fetch_snapshot_id,
            ),
            section_evidence=tuple(
                DailyMedSectionEvidenceProjection(
                    section_id=section_id,
                    evidence_id=f"evidence:{section_id}",
                    content_hash="sha256:" + "c" * 64,
                    locator_ref=f"locator:{section_id}",
                )
                for section_id in response.section_ids
            ),
        )
        self.fetch_progress[(persisted.acquisition.acquisition_intent_id, request.query_id)] = (
            DailyMedFetchExecutionProjection(
                run_id=RUN_ID,
                scope_id=self.scope_id,
                task_id=self.task_id,
                attempt_id=self.attempt_id,
                response=response,
                acquisition=persisted.acquisition,
                section_evidence=persisted.section_evidence,
            )
        )
        return persisted

    def load_discovery_progress(
        self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id
    ):
        if run_id != RUN_ID or task_id != self.task_id or attempt_id != self.attempt_id:
            raise ValueError("foreign persisted discovery progress lookup")
        return self.progress[(acquisition_intent_id, query_id)]

    def load_fetch_progress(self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id):
        if run_id != RUN_ID or task_id != self.task_id or attempt_id != self.attempt_id:
            raise ValueError("foreign persisted fetch progress lookup")
        return self.fetch_progress[(acquisition_intent_id, query_id)]


class _DailyReplayStore:
    def __init__(self) -> None:
        self.discoveries: dict[tuple[str, str], DailyMedDiscoveryExecutionProjection] = {}
        self.fetches: dict[tuple[str, str], DailyMedFetchExecutionProjection] = {}

    def persist_discovery(self, record):
        key = (record.acquisition.acquisition_intent_id, record.response.query_id)
        self.discoveries[key] = DailyMedDiscoveryExecutionProjection.model_validate(
            record.model_dump(mode="python"), strict=True
        )
        return self.discoveries[key]

    def persist_fetch(self, record):
        key = (record.acquisition.acquisition_intent_id, record.response.request.query_id)
        self.fetches[key] = DailyMedFetchExecutionProjection.model_validate(
            record.model_dump(mode="python"), strict=True
        )
        return self.fetches[key]

    def load_discovery(self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id):
        del run_id, task_id, attempt_id
        return self.discoveries[(acquisition_intent_id, query_id)]

    def load_fetch(self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id):
        del run_id, task_id, attempt_id
        return self.fetches[(acquisition_intent_id, query_id)]


class _CanonicalFaersProvenance:
    def __init__(self) -> None:
        self.progress: dict[tuple[str, str], FaersAggregateExecutionProjection] = {}

    def load_aggregate(self, *, execution):
        result = execution.result
        persisted = FaersAggregateProvenanceProjection(
            run_id=RUN_ID,
            scope_id=self.scope_id,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            query_id=result.query.query_id,
            snapshot_id=result.snapshot_id,
            manifest_id=result.manifest_id,
            bucket_evidence=tuple(
                FaersBucketEvidenceProjection(
                    bucket_ordinal=bucket.bucket_ordinal,
                    evidence_id=f"evidence:{result.query.query_id}:{bucket.bucket_ordinal}",
                    content_hash="sha256:" + str(bucket.bucket_ordinal + 1) * 64,
                    locator_ref=f"locator:{result.query.query_id}:{bucket.bucket_ordinal}",
                )
                for bucket in result.buckets
            ),
        )
        self.progress[
            (
                execution.acquisition_outcome_ref.acquisition_intent_id,
                result.query.query_id,
            )
        ] = FaersAggregateExecutionProjection(
            run_id=RUN_ID,
            scope_id=self.scope_id,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            execution=execution,
            bucket_evidence=persisted.bucket_evidence,
        )
        return persisted

    def load_aggregate_progress(
        self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id
    ):
        if run_id != RUN_ID or task_id != self.task_id or attempt_id != self.attempt_id:
            raise ValueError("foreign persisted aggregate progress lookup")
        return self.progress[(acquisition_intent_id, query_id)]


class _FaersReplayStore:
    def __init__(self) -> None:
        self.aggregates: dict[tuple[str, str], FaersAggregateExecutionProjection] = {}

    def persist_aggregate(self, record):
        key = (
            record.execution.acquisition_outcome_ref.acquisition_intent_id,
            record.execution.result.query.query_id,
        )
        self.aggregates[key] = FaersAggregateExecutionProjection.model_validate(
            record.model_dump(mode="python"), strict=True
        )
        return self.aggregates[key]

    def load_aggregate(self, *, acquisition_intent_id, run_id, task_id, attempt_id, query_id):
        del run_id, task_id, attempt_id
        return self.aggregates[(acquisition_intent_id, query_id)]


def _canonical_task(source: SourceType):
    task_id = f"source-task:{RUN_ID.removeprefix('run:')}:{source.value}"
    attempt = source_task_attempt(task_id, 1)
    return SourceTaskState(task_id=task_id, source=source), attempt


def test_concrete_dailymed_authority_is_directly_reachable_and_owns_business_metadata() -> None:
    scope = _scope(SourceType.DAILYMED)
    envelope = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000001",
        scope=scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(_selection_request(),),
    )
    pending, attempt = _canonical_task(SourceType.DAILYMED)
    provenance = _CanonicalDailyProvenance()
    replay_store = _DailyReplayStore()
    provenance.scope_id = scope.scope_id
    provenance.task_id = pending.task_id
    provenance.attempt_id = attempt.attempt_id
    authority = CanonicalDailyMedProjectionAuthority(
        request=envelope,
        run_id=RUN_ID,
        limitations=("Synthetic DailyMed limitation.",),
        provenance=provenance,
        replay_store=replay_store,
    )
    operations = plan_dailymed_operations(pending, scope, attempt, projection=authority)
    assert len(operations) == 1
    discovery = authority.freeze_discovery_requests(
        task=pending, scope=scope, attempt=attempt
    ).requests[0]
    assert operations[0].input_refs == (
        SourceOperationInputRef(
            role=SourceOperationInputRole.REQUEST,
            value=derive_identity("dailymed-discovery-request", discovery),
        ),
    )
    running = SourceTaskState(
        task_id=pending.task_id,
        source=SourceType.DAILYMED,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    events: list[str] = []
    execution = _DailyExecution({discovery.query_id}, events)

    progress = collect_dailymed_capability(
        running,
        scope,
        attempt,
        projection=authority,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(progress, SourceTaskProgressResult)
    assert execution.fetch_calls == 0
    alternate = progress.required_operations[1].model_dump(mode="python")
    alternate["input_refs"][-1]["value"] = "4"
    with pytest.raises(ValidationError, match="input identity"):
        RequiredSourceOperation.model_validate(alternate)
    original_fetch = progress.required_operations[1]
    alternate_refs = (
        *original_fetch.input_refs[:-1],
        SourceOperationInputRef(
            role=SourceOperationInputRole.SPL_VERSION,
            value="4",
        ),
    )
    alternate_fetch = required_source_operation(
        run_id=RUN_ID,
        scope_id=scope.scope_id,
        source=SourceType.DAILYMED,
        ordinal=original_fetch.ordinal,
        kind=SourceOperationKind.DAILYMED_FETCH,
        query_id=original_fetch.query_id,
        input_refs=alternate_refs,
    )
    alternate_progress = SourceTaskProgressResult(
        attempt=attempt,
        required_operations=(progress.required_operations[0], alternate_fetch),
        operation_results=progress.operation_results,
    )
    crash_authority = CanonicalDailyMedProjectionAuthority(
        request=envelope,
        run_id=RUN_ID,
        limitations=("Synthetic DailyMed limitation.",),
        provenance=provenance,
        replay_store=replay_store,
    )
    durable_progress = dict(replay_store.discoveries)
    replay_store.discoveries.clear()
    with pytest.raises(ValueError, match="progress is missing"):
        collect_dailymed_capability(
            _resume_dailymed_progress(running, progress),
            scope,
            attempt,
            projection=crash_authority,
            execution=cast(DailyMedExecutionPort, execution),
        )
    assert execution.fetch_calls == 0
    replay_store.discoveries.update(durable_progress)
    with pytest.raises(ValueError, match="persisted selection"):
        collect_dailymed_capability(
            _resume_dailymed_progress(running, alternate_progress),
            scope,
            attempt,
            projection=crash_authority,
            execution=cast(DailyMedExecutionPort, execution),
        )
    assert execution.fetch_calls == 0
    result = collect_dailymed_capability(
        _resume_dailymed_progress(running, progress),
        scope,
        attempt,
        projection=crash_authority,
        execution=cast(DailyMedExecutionPort, execution),
    )
    assert isinstance(result, CollectedEvidenceResult)
    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 1
    assert tuple(item.kind for item in result.required_operations) == (
        SourceOperationKind.DAILYMED_DISCOVERY,
        SourceOperationKind.DAILYMED_FETCH,
    )
    fetch_request = execution.fetch_requests[0]
    assert result.required_operations[1].input_refs == (
        SourceOperationInputRef(
            role=SourceOperationInputRole.DAILYMED_DECISION,
            value=fetch_request.decision_id,
        ),
        SourceOperationInputRef(
            role=SourceOperationInputRole.CANDIDATE,
            value=fetch_request.selected_candidate_id,
        ),
        SourceOperationInputRef(
            role=SourceOperationInputRole.SETID,
            value=fetch_request.selected_setid,
        ),
        SourceOperationInputRef(
            role=SourceOperationInputRole.SPL_VERSION,
            value=fetch_request.selected_spl_version,
        ),
    )
    assert result.terminal_outcome_ref.operation_acquisition_ids == tuple(
        item.acquisition.acquisition_id for item in result.operation_results
    )
    assert result.terminal_outcome_ref.acquisition.source_outcome_id == (
        result.operation_results[0].acquisition.source_outcome_id
    )
    assert result.operation_results[0].acquisition.acquisition_intent_id == (
        "acquisition-intent:sha256:" + "a" * 64
    )
    assert result.terminal_outcome_ref.acquisition.acquisition_intent_id == (
        result.operation_results[0].acquisition.acquisition_intent_id
    )
    assert result.terminal_outcome_ref.outcome.valid_result_count == 1
    assert result.limitations == ("Synthetic DailyMed limitation.",)
    terminal_task = _terminal_task_from_collection(running, result)
    crash_authority.validate_terminal_task(terminal_task, scope)
    assert execution.discovery_calls == 1
    assert execution.fetch_calls == 1
    provenance.progress.clear()
    provenance.fetch_progress.clear()
    provenance.scope_id = "scope:foreign"
    crash_authority.validate_terminal_task(terminal_task, scope)
    first_child = result.operation_results[0]
    foreign_intent = "acquisition-intent:sha256:" + "d" * 64
    foreign_acquisition = source_operation_acquisition(
        operation=first_child.operation,
        attempt_id=attempt.attempt_id,
        acquisition_intent_id=foreign_intent,
        outcome=first_child.outcome,
        snapshot_id=first_child.acquisition.snapshot_id,
    )
    foreign_first = TerminalSourceOperationResult(
        operation=first_child.operation,
        attempt=attempt,
        acquisition=foreign_acquisition,
        outcome=first_child.outcome,
    )
    coordinated_results = (foreign_first, result.operation_results[1])
    coordinated_ref = TerminalSourceOutcomeRef(
        terminal_outcome_id=result.terminal_outcome_ref.terminal_outcome_id,
        operation_acquisition_ids=tuple(
            item.acquisition.acquisition_id for item in coordinated_results
        ),
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id=foreign_acquisition.acquisition_id,
            acquisition_intent_id=foreign_intent,
            acquisition_ordinal=foreign_acquisition.ordinal,
            operation="search",
            query_id=foreign_acquisition.query_id,
            source_outcome_id=foreign_acquisition.source_outcome_id,
            snapshot_id=foreign_acquisition.snapshot_id,
        ),
        outcome=result.terminal_outcome_ref.outcome,
    )
    coordinated_intent_task = SourceTaskState(
        task_id=terminal_task.task_id,
        source=terminal_task.source,
        required_operations=terminal_task.required_operations,
        operation_results=coordinated_results,
        status=SourceTaskStatus.TERMINAL,
        attempts=1,
        terminal_outcome_ref=coordinated_ref,
        evidence_refs=terminal_task.evidence_refs,
        limitations=terminal_task.limitations,
    )
    with pytest.raises(ValueError, match="discovery progress is missing"):
        crash_authority.validate_terminal_task(coordinated_intent_task, scope)
    fetch_child = result.operation_results[1]
    alternate_representative = TerminalSourceOutcomeRef(
        terminal_outcome_id=result.terminal_outcome_ref.terminal_outcome_id,
        operation_acquisition_ids=(result.terminal_outcome_ref.operation_acquisition_ids),
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id=fetch_child.acquisition.acquisition_id,
            acquisition_intent_id=fetch_child.acquisition.acquisition_intent_id,
            acquisition_ordinal=fetch_child.acquisition.ordinal,
            operation="fetch",
            query_id=fetch_child.acquisition.query_id,
            source_outcome_id=fetch_child.acquisition.source_outcome_id,
            snapshot_id=fetch_child.acquisition.snapshot_id,
        ),
        outcome=result.terminal_outcome_ref.outcome,
    )
    coordinated = terminal_task.model_copy(
        update={"terminal_outcome_ref": alternate_representative}
    )
    with pytest.raises(ValueError, match="durable canonical replay"):
        crash_authority.validate_terminal_task(coordinated, scope)
    for field, value in (
        ("query_id", "query:foreign"),
        ("valid_result_count", 2),
        ("configured_bounds", BOUNDS.model_copy(update={"max_records": 99})),
    ):
        stale_outcome = result.terminal_outcome_ref.outcome.model_copy(update={field: value})
        stale_ref = result.terminal_outcome_ref.model_copy(
            update={
                "terminal_outcome_id": derive_identity(
                    "source-task-terminal-outcome", stale_outcome
                ),
                "outcome": stale_outcome,
            }
        )
        stale_task = terminal_task.model_copy(update={"terminal_outcome_ref": stale_ref})
        with pytest.raises(ValidationError):
            crash_authority.validate_terminal_task(stale_task, scope)
    durable_fetch = dict(replay_store.fetches)
    replay_store.fetches.clear()
    with pytest.raises(ValueError, match="fetch progress is missing"):
        crash_authority.validate_terminal_task(terminal_task, scope)
    replay_store.fetches.update(durable_fetch)

    with pytest.raises(TypeError, match="sealed"):
        type("ForbiddenDailySubclass", (CanonicalDailyMedProjectionAuthority,), {})
    with pytest.raises(AttributeError):
        authority.project_terminal = lambda **_values: None  # type: ignore[method-assign]
    with pytest.raises(AttributeError, match="immutable"):
        authority._provenance = _CanonicalDailyProvenance()  # type: ignore[misc]
    with pytest.raises(AttributeError, match="immutable"):
        authority._replay_store = _DailyReplayStore()  # type: ignore[misc]


def test_concrete_faers_authority_binds_exact_request_and_owns_terminal_projection() -> None:
    scope = _scope(SourceType.FAERS)
    requests = (
        _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE),
        _faers_request(FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT),
    )
    envelope = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000002",
        scope=scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=requests,
    )
    pending, attempt = _canonical_task(SourceType.FAERS)
    provenance = _CanonicalFaersProvenance()
    replay_store = _FaersReplayStore()
    provenance.scope_id = scope.scope_id
    provenance.task_id = pending.task_id
    provenance.attempt_id = attempt.attempt_id
    provenance.fabricated_terminal_outcome = "must-be-ignored"
    authority = CanonicalFaersProjectionAuthority(
        request=envelope,
        run_id=RUN_ID,
        provenance=provenance,
        replay_store=replay_store,
    )
    operations = plan_faers_operations(pending, scope, attempt, projection=authority)
    assert operations[0].input_refs == (
        SourceOperationInputRef(
            role=SourceOperationInputRole.REQUEST,
            value=derive_identity("faers-aggregate-request", requests[0]),
        ),
    )
    assert operations[0].input_identity != operations[1].input_identity
    running = SourceTaskState(
        task_id=pending.task_id,
        source=SourceType.FAERS,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    events: list[str] = []
    execution = _FaersExecution(
        {
            FaersAggregateQueryV1.create(request).query_id: _faers_execution(request)
            for request in requests
        },
        events,
    )
    persistence = _FaersPersistence(events)

    result = collect_faers_capability(
        running,
        scope,
        attempt,
        projection=authority,
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, persistence),
    )

    assert result.terminal_outcome_ref.outcome.valid_result_count == 2
    assert result.limitations == FAERS_MANDATORY_LIMITATIONS
    assert result.terminal_outcome_ref.operation_acquisition_ids == tuple(
        item.acquisition.acquisition_id for item in result.operation_results
    )
    assert all(
        item.acquisition.acquisition_intent_id == "acquisition-intent:sha256:" + "8" * 64
        for item in result.operation_results
    )
    terminal_task = _terminal_task_from_collection(running, result)
    authority.validate_terminal_task(terminal_task, scope)
    assert execution.calls == persistence.calls == 2
    provenance.progress.clear()
    provenance.scope_id = "scope:foreign"
    authority.validate_terminal_task(terminal_task, scope)
    durable_aggregates = dict(replay_store.aggregates)
    replay_store.aggregates.clear()
    with pytest.raises(ValueError, match="aggregate progress is missing"):
        authority.validate_terminal_task(terminal_task, scope)
    replay_store.aggregates.update(durable_aggregates)
    assert not hasattr(provenance, "project_terminal")
    with pytest.raises(TypeError, match="sealed"):
        type("ForbiddenFaersSubclass", (CanonicalFaersProjectionAuthority,), {})
    with pytest.raises(AttributeError):
        authority.project_terminal = lambda **_values: None  # type: ignore[method-assign]
    with pytest.raises(AttributeError, match="immutable"):
        authority._provenance = _CanonicalFaersProvenance()  # type: ignore[misc]
    with pytest.raises(AttributeError, match="immutable"):
        authority._replay_store = _FaersReplayStore()  # type: ignore[misc]


def test_concrete_authorities_reject_omitted_source_request() -> None:
    dailymed_scope = _scope(SourceType.DAILYMED)
    faers_scope = _scope(SourceType.FAERS)
    dailymed_request = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000003",
        scope=dailymed_scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(_selection_request(),),
    )
    with pytest.raises(ValueError, match="requires FAERS requested"):
        CanonicalFaersProjectionAuthority(
            request=dailymed_request,
            run_id=RUN_ID,
            provenance=_CanonicalFaersProvenance(),
            replay_store=_FaersReplayStore(),
        )
    faers_request = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000004",
        scope=faers_scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=(_faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE),),
    )
    with pytest.raises(ValueError, match="requires DailyMed requested"):
        CanonicalDailyMedProjectionAuthority(
            request=faers_request,
            run_id=RUN_ID,
            limitations=("Synthetic DailyMed limitation.",),
            provenance=_CanonicalDailyProvenance(),
            replay_store=_DailyReplayStore(),
        )


def test_concrete_faers_authority_derives_failure_and_partial_metadata_from_children() -> None:
    scope = _scope(SourceType.FAERS)
    requests = (
        _faers_request(FaersIdentityStrategy.HARMONIZED_SUBSTANCE),
        _faers_request(FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT),
    )
    envelope = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000005",
        scope=scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=requests,
    )
    pending, attempt = _canonical_task(SourceType.FAERS)
    provenance = _CanonicalFaersProvenance()
    replay_store = _FaersReplayStore()
    provenance.scope_id = scope.scope_id
    provenance.task_id = pending.task_id
    provenance.attempt_id = attempt.attempt_id
    authority = CanonicalFaersProjectionAuthority(
        request=envelope,
        run_id=RUN_ID,
        provenance=provenance,
        replay_store=replay_store,
    )
    operations = plan_faers_operations(pending, scope, attempt, projection=authority)
    running = SourceTaskState(
        task_id=pending.task_id,
        source=SourceType.FAERS,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    first_query = FaersAggregateQueryV1.create(requests[0]).query_id
    second_query = FaersAggregateQueryV1.create(requests[1]).query_id
    events: list[str] = []
    execution = _FaersExecution(
        {
            first_query: _faers_execution(requests[0]),
            second_query: _faers_execution(
                requests[1],
                execution=ExecutionStatus.FAILED,
                coverage=CoverageStatus.UNAVAILABLE,
                result=ResultStatus.INDETERMINATE,
            ),
        },
        events,
    )

    collected = collect_faers_capability(
        running,
        scope,
        attempt,
        projection=authority,
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, _FaersPersistence(events)),
    )

    outcome = collected.terminal_outcome_ref.outcome
    assert (
        outcome.execution_status,
        outcome.coverage_status,
        outcome.result_status,
        outcome.valid_result_count,
        outcome.truncated,
    ) == (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
        1,
        False,
    )
    assert outcome.failure_id is not None
    assert collected.terminal_outcome_ref.terminal_outcome_id == derive_identity(
        "source-task-terminal-outcome", outcome
    )
