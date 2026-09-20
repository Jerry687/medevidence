"""Local source ceilings remain truthful under a larger research budget."""

import pytest
from tests.unit.orchestration.test_pubmed_capability import _collect_terminal, _terminal_task
from tests.unit.tools.test_research import (
    Acquisitions,
    Catalog,
    Execution,
    Runs,
    Runtime,
    _outcome,
    _request,
    _scope,
)

from medevidence.domain import (
    ExecutionBounds,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceType,
)
from medevidence.domain.catalogs import LOCAL_RESEARCH_CATALOG_HASH
from medevidence.orchestration.contracts import (
    SourceTaskState,
    SourceTaskStatus,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.pubmed_capability import (
    plan_pubmed_operations,
    validate_pubmed_terminal_task,
)
from medevidence.tools.contracts import ResolvedConceptCatalog, SearchPubMedRequest
from medevidence.tools.pubmed_local import LocalResearchPubMedRequest, LocalSearchPubMedRequest
from medevidence.tools.research import PubMedBoundsPolicy, PubMedResearchService


def scope_with_budget(**overrides: int) -> ResearchScope:
    original = _scope()
    query = {"max_query_characters": 512, "max_pages": 5, "max_total_seconds": 60}
    result = {"max_records": 100, "max_payload_bytes": 5_242_880}
    for key, value in overrides.items():
        (query if key in query else result)[key] = value
    return ResearchScope.create(
        drugs=original.drugs,
        date_range=None,
        adverse_reactions=original.adverse_reactions,
        selected_sources=original.selected_sources,
        comparison_intent=original.comparison_intent,
        query_bounds=QueryBounds(**query),
        result_bounds=ResultBounds(**result),
    )


class LocalCatalog:
    def __init__(self, scope: ResearchScope) -> None:
        self.scope = scope

    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        assert scope_id == self.scope.scope_id
        return ResolvedConceptCatalog(
            catalog_version="m3.local-research-input.v1",
            catalog_content_hash=LOCAL_RESEARCH_CATALOG_HASH,
            drugs=self.scope.drugs,
            adverse_reactions=self.scope.adverse_reactions,
        )


def service_for(
    scope: ResearchScope,
    calls: list[str],
    *,
    policy: PubMedBoundsPolicy = PubMedBoundsPolicy.LOCAL_PUBLIC_V1,
    execution: Execution | None = None,
) -> PubMedResearchService:
    return PubMedResearchService(
        catalog=LocalCatalog(scope),
        execution=execution or Execution(calls),
        acquisitions=Acquisitions(calls),
        runs=Runs(calls),
        runtime=Runtime(),
        bounds_policy=policy,
    )


def local_request(scope: ResearchScope) -> LocalResearchPubMedRequest:
    return LocalResearchPubMedRequest.model_validate(
        {**_request().model_dump(mode="python"), "scope": scope}
    )


def test_collection_keeps_real_search_fetch_and_aggregate_limits() -> None:
    scope = scope_with_budget()
    calls: list[str] = []
    collection = service_for(scope, calls).collect(local_request(scope))
    expected = ExecutionBounds.from_scope(_scope())
    assert expected != ExecutionBounds.from_scope(scope)
    assert collection.searched.request.scope == scope
    assert collection.searched.response.source_outcome.configured_bounds == expected
    assert collection.fetches[0].source_outcome.configured_bounds == expected
    assert collection.source_outcome.configured_bounds == expected
    assert calls.count("execute-search") == calls.count("execute-fetch-10") == 1


def test_default_legacy_policy_still_requires_exact_scope() -> None:
    scope = scope_with_budget()
    with pytest.raises(ValueError, match="bounds differ"):
        service_for(scope, [], policy=PubMedBoundsPolicy.EXACT_SCOPE).search(
            LocalSearchPubMedRequest(scope=scope)
        )


@pytest.mark.parametrize(
    "field,value",
    (
        ("max_query_characters", 511),
        ("max_records", 99),
        ("max_payload_bytes", 5_242_879),
        ("max_total_seconds", 29),
    ),
)
def test_small_budget_fails_before_execution_or_persistence(field: str, value: int) -> None:
    scope = scope_with_budget(**{field: value})
    calls: list[str] = []
    with pytest.raises(ValueError, match="exceeds the requested budget"):
        service_for(scope, calls).collect(local_request(scope))
    assert calls == []


def test_local_profile_rejects_legacy_catalog_before_execution() -> None:
    calls: list[str] = []
    service = PubMedResearchService(
        catalog=Catalog(),
        execution=Execution(calls),
        acquisitions=Acquisitions(calls),
        runs=Runs(calls),
        runtime=Runtime(),
        bounds_policy=PubMedBoundsPolicy.LOCAL_PUBLIC_V1,
    )
    with pytest.raises(ValueError, match="exact local research catalog"):
        service.search(SearchPubMedRequest(scope=_scope()))
    assert calls == []


def test_adapter_cannot_return_master_budget_instead_of_actual_limits() -> None:
    scope = scope_with_budget()
    calls: list[str] = []
    outcome = _outcome(result=ResultStatus.MATCHES, count=1).model_copy(
        update={"configured_bounds": ExecutionBounds.from_scope(scope)}
    )
    with pytest.raises(ValueError, match="bounds differ"):
        service_for(scope, calls, execution=Execution(calls, search_outcome=outcome)).collect(
            local_request(scope)
        )
    assert "persist-search" not in calls


def test_fetch_bounds_must_match_the_same_fixed_profile() -> None:
    scope = scope_with_budget()
    calls: list[str] = []
    outcome = _outcome(result=ResultStatus.MATCHES, count=1).model_copy(
        update={"configured_bounds": ExecutionBounds.from_scope(scope)}
    )
    with pytest.raises(ValueError, match="bounds differ"):
        service_for(scope, calls, execution=Execution(calls, fetch_outcome=outcome)).collect(
            local_request(scope)
        )
    assert not any(call.startswith("persist-fetch") for call in calls)


def test_local_capability_can_resume_and_verify_without_resending() -> None:
    scope = scope_with_budget()
    calls: list[str] = []
    service = service_for(scope, calls)
    request = local_request(scope)
    task_id = source_task_id(request.run_id, SourceType.PUBMED)
    attempt = source_task_attempt(task_id, 1)
    operations = plan_pubmed_operations(
        task=SourceTaskState(task_id=task_id, source=SourceType.PUBMED),
        scope=scope,
        attempt=attempt,
        request=request,
        service=service,
    )
    assert calls == []
    task = SourceTaskState(
        task_id=task_id,
        source=SourceType.PUBMED,
        required_operations=operations,
        status=SourceTaskStatus.RUNNING,
        attempts=1,
        active_attempt=attempt,
    )
    _progress, terminal = _collect_terminal(service, request, task, attempt)
    before = list(calls)
    validate_pubmed_terminal_task(
        task=_terminal_task(task, terminal),
        scope=scope,
        request=request,
        service=service,
    )
    assert [call for call in calls if call.startswith("execute-")] == [
        call for call in before if call.startswith("execute-")
    ]
    assert terminal.terminal_outcome_ref.outcome.configured_bounds == ExecutionBounds.from_scope(
        _scope()
    )
