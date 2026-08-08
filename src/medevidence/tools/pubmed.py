"""Deterministic PubMed query construction and stable tool operations."""

from __future__ import annotations

from datetime import date

from medevidence.domain import ResearchScope, derive_identity

from .contracts import (
    FetchPubMedArticleRequest,
    FetchPubMedArticleResponse,
    ResolvedConceptCatalog,
    SearchPubMedRequest,
    SearchPubMedResponse,
)


def build_pubmed_query(
    scope: ResearchScope,
    catalog: ResolvedConceptCatalog,
) -> str:
    """Build the exact bounded Title/Abstract query from resolved catalog terms."""

    _validate_catalog_alignment(scope, catalog)
    drug_group = _query_group(tuple(item.preferred_term for item in catalog.drugs))
    event_group = _query_group(tuple(item.preferred_term for item in catalog.adverse_reactions))
    groups = [drug_group, event_group]
    if scope.date_range is not None:
        groups.append(_date_group(scope.date_range.start_date, scope.date_range.end_date))
    query = " AND ".join(groups)
    if len(query) > scope.query_bounds.max_query_characters:
        raise ValueError("resolved PubMed query exceeds the configured character bound")
    return query


def validate_query_terms(scope: ResearchScope) -> None:
    """Reject unsupported catalog-term syntax before any injected port call."""

    for drug_concept in scope.drugs:
        _validate_term(drug_concept.preferred_term)
    for event_concept in scope.adverse_reactions:
        _validate_term(event_concept.preferred_term)


def query_identity(scope: ResearchScope, query: str) -> str:
    """Derive the stable source-neutral identity of one exact bounded query."""

    return derive_identity("query", {"scope_id": scope.scope_id, "query": query})


def search_pubmed(
    request: SearchPubMedRequest,
    *,
    service: PubMedResearchService,
) -> SearchPubMedResponse:
    """Execute the stable source-neutral PubMed search operation."""

    return service.search(request)


def fetch_pubmed_article(
    request: FetchPubMedArticleRequest,
    *,
    service: PubMedResearchService,
) -> FetchPubMedArticleResponse:
    """Execute the stable source-neutral singular PubMed fetch operation."""

    return service.fetch(request)


def _query_group(terms: tuple[str, ...]) -> str:
    for term in terms:
        _validate_term(term)
    return "(" + " OR ".join(f'"{term}"[Title/Abstract]' for term in terms) + ")"


def _date_group(start: date, end: date) -> str:
    start_text = start.strftime("%Y/%m/%d")
    end_text = end.strftime("%Y/%m/%d")
    return f'("{start_text}"[Date - Publication] : "{end_text}"[Date - Publication])'


def _validate_term(term: str) -> None:
    if term != term.strip():
        raise ValueError("catalog terms must not contain leading or trailing whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in term):
        raise ValueError("catalog terms must not contain control characters")
    if any(character in term for character in {'"', "[", "]", "\\"}):
        raise ValueError("catalog term contains unsupported PubMed query syntax")


def _validate_catalog_alignment(
    scope: ResearchScope,
    catalog: ResolvedConceptCatalog,
) -> None:
    expected_drugs = tuple((item.concept_id, item.preferred_term) for item in scope.drugs)
    resolved_drugs = tuple((item.concept_id, item.preferred_term) for item in catalog.drugs)
    expected_events = tuple(
        (item.concept_id, item.preferred_term) for item in scope.adverse_reactions
    )
    resolved_events = tuple(
        (item.concept_id, item.preferred_term) for item in catalog.adverse_reactions
    )
    if resolved_drugs != expected_drugs or resolved_events != expected_events:
        raise ValueError("scope terms must exactly match case-sensitive resolved catalog terms")
    validate_query_terms(scope)


from .research import PubMedResearchService  # noqa: E402
