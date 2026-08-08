"""Offline public-contract checks for the stable PubMed tools boundary."""

from __future__ import annotations

import inspect

from medevidence.domain import ResearchReport
from medevidence.tools import (
    FetchPubMedArticleRequest,
    FetchPubMedArticleResponse,
    PubMedResearchService,
    ResearchPubMedRequest,
    SearchPubMedRequest,
    SearchPubMedResponse,
    fetch_pubmed_article,
    research_pubmed_draft,
    search_pubmed,
)


def test_public_operations_have_the_frozen_injected_service_signatures() -> None:
    search = inspect.signature(search_pubmed)
    fetch = inspect.signature(fetch_pubmed_article)
    research = inspect.signature(research_pubmed_draft)

    assert tuple(search.parameters) == ("request", "service")
    assert search.parameters["service"].kind is inspect.Parameter.KEYWORD_ONLY
    assert tuple(fetch.parameters) == ("request", "service")
    assert fetch.parameters["service"].kind is inspect.Parameter.KEYWORD_ONLY
    assert tuple(research.parameters) == ("request", "service")
    assert research.parameters["service"].kind is inspect.Parameter.KEYWORD_ONLY


def test_public_contracts_are_source_neutral_and_provider_object_free() -> None:
    public_models = (
        SearchPubMedRequest,
        SearchPubMedResponse,
        FetchPubMedArticleRequest,
        FetchPubMedArticleResponse,
        ResearchPubMedRequest,
        ResearchReport,
    )
    forbidden = {
        "client",
        "connector",
        "database",
        "filesystem",
        "headers",
        "httpx",
        "path",
        "response",
        "session",
        "sqlalchemy",
        "transport",
        "url",
    }
    for model in public_models:
        assert forbidden.isdisjoint(model.model_fields)


def test_tools_package_import_has_no_concrete_adapter_construction() -> None:
    source = inspect.getsource(PubMedResearchService)
    assert "for_production" not in source
    assert "PubMedConnector" not in source
    assert "PersistenceRepository" not in source
