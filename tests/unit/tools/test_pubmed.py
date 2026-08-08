"""Pure PubMed query construction and no-I/O validation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    InclusiveDateRange,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.tools import (
    FetchPubMedArticleRequest,
    ResolvedConceptCatalog,
    SearchPubMedRequest,
    build_pubmed_query,
    fetch_pubmed_article,
)
from medevidence.tools.ports import PubMedFetchExecution, ResponseObservation
from medevidence.tools.pubmed import query_identity
from medevidence.tools.research import PubMedResearchService

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def _scope(
    *,
    drug_term: str = "semaglutide",
    date_range: InclusiveDateRange | None = None,
) -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="m1a.drug.semaglutide", preferred_term=drug_term),),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="m1a.event.gastrointestinal",
                preferred_term="gastrointestinal",
            ),
        ),
        date_range=date_range,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _catalog(scope: ResearchScope) -> ResolvedConceptCatalog:
    return ResolvedConceptCatalog(
        catalog_content_hash=f"sha256:{'a' * 64}",
        drugs=scope.drugs,
        adverse_reactions=scope.adverse_reactions,
    )


def test_query_uses_exact_quoted_title_abstract_groups() -> None:
    scope = _scope()
    assert build_pubmed_query(scope, _catalog(scope)) == (
        '("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])'
    )


def test_query_adds_exact_inclusive_publication_date_range() -> None:
    scope = _scope(
        date_range=InclusiveDateRange(
            start_date=date(2020, 1, 2),
            end_date=date(2024, 12, 31),
        )
    )
    assert build_pubmed_query(scope, _catalog(scope)).endswith(
        ' AND ("2020/01/02"[Date - Publication] : "2024/12/31"[Date - Publication])'
    )


@pytest.mark.parametrize("term", [" semaglutide", "semaglutide\n", 'semi"glutide'])
def test_invalid_term_is_rejected_before_any_port_call(term: str) -> None:
    scope = _scope(drug_term=term)

    class NoCall:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected I/O through {name}")

    service = PubMedResearchService(
        catalog=NoCall(),  # type: ignore[arg-type]
        execution=NoCall(),  # type: ignore[arg-type]
        acquisitions=NoCall(),  # type: ignore[arg-type]
        runs=NoCall(),  # type: ignore[arg-type]
        runtime=NoCall(),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match=r"whitespace|control|unsupported"):
        service.search(SearchPubMedRequest(scope=scope))


def test_catalog_term_case_drift_is_rejected() -> None:
    scope = _scope()
    drifted = ResolvedConceptCatalog(
        catalog_content_hash=f"sha256:{'a' * 64}",
        drugs=(
            DrugConcept(
                concept_id=scope.drugs[0].concept_id,
                preferred_term="Semaglutide",
            ),
        ),
        adverse_reactions=scope.adverse_reactions,
    )
    with pytest.raises(ValueError, match="case-sensitive"):
        build_pubmed_query(scope, drifted)


def test_standalone_fetch_binds_query_identity_before_execution() -> None:
    scope = _scope()
    expected_query_id = query_identity(scope, build_pubmed_query(scope, _catalog(scope)))
    calls: list[str] = []

    class Catalog:
        def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
            assert scope_id == scope.scope_id
            return _catalog(scope)

    class Execution:
        def search(self, *, query: str, query_id: str) -> object:
            raise AssertionError(f"unexpected search for {query_id}: {query}")

        def fetch(self, *, pmid: str, query_id: str) -> PubMedFetchExecution:
            calls.append(f"fetch:{pmid}:{query_id}")
            outcome = SourceOutcome(
                source=SourceType.PUBMED,
                query_id=query_id,
                execution_status=ExecutionStatus.SUCCEEDED,
                coverage_status=CoverageStatus.COMPLETE,
                result_status=ResultStatus.NO_MATCH,
                configured_bounds=ExecutionBounds.from_scope(scope),
                valid_result_count=0,
                pages_completed=1,
                truncated=False,
            )
            return PubMedFetchExecution(
                requested_pmid=pmid,
                query_id=query_id,
                publication=None,
                source_outcome=outcome,
                started_at_utc=NOW,
                completed_at_utc=NOW,
                attempts_used=1,
                observations=(
                    ResponseObservation(
                        body=b"<article-set/>",
                        observed_at_utc=NOW,
                        headers=(("content-type", "application/xml"),),
                        http_status=200,
                        body_complete=True,
                        termination_reason="complete_response",
                    ),
                ),
            )

    class NoCall:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected call through {name}")

    service = PubMedResearchService(
        catalog=Catalog(),
        execution=Execution(),
        acquisitions=NoCall(),  # type: ignore[arg-type]
        runs=NoCall(),  # type: ignore[arg-type]
        runtime=NoCall(),  # type: ignore[arg-type]
    )
    valid = fetch_pubmed_article(
        FetchPubMedArticleRequest(scope=scope, pmid="10", query_id=expected_query_id),
        service=service,
    )
    assert valid.requested_pmid == "10"
    assert calls == [f"fetch:10:{expected_query_id}"]

    calls.clear()
    with pytest.raises(ValueError, match="exact resolved query"):
        fetch_pubmed_article(
            FetchPubMedArticleRequest(scope=scope, pmid="10", query_id="query:unrelated"),
            service=service,
        )
    assert calls == []
