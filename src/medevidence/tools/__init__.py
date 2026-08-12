"""Stable source-neutral PubMed and DailyMed application operations."""

from .contracts import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    FetchPubMedArticleRequest,
    FetchPubMedArticleResponse,
    ResearchPubMedRequest,
    ResolvedConceptCatalog,
    SearchPubMedRequest,
    SearchPubMedResponse,
    TrustedDailyMedAcquisitionOutcome,
    TrustedDailyMedFetchEvidence,
    TrustedDailyMedSelectionDecision,
)
from .dailymed import discover_dailymed_labels, fetch_dailymed_label
from .dailymed_report import build_dailymed_report
from .pubmed import build_pubmed_query, fetch_pubmed_article, search_pubmed
from .research import PubMedResearchService, research_pubmed_draft

__all__ = [
    "DailyMedDiscoveryRequest",
    "DailyMedDiscoveryResponse",
    "DailyMedFetchRequest",
    "DailyMedFetchResponse",
    "FetchPubMedArticleRequest",
    "FetchPubMedArticleResponse",
    "PubMedResearchService",
    "ResearchPubMedRequest",
    "ResolvedConceptCatalog",
    "SearchPubMedRequest",
    "SearchPubMedResponse",
    "TrustedDailyMedAcquisitionOutcome",
    "TrustedDailyMedFetchEvidence",
    "TrustedDailyMedSelectionDecision",
    "build_dailymed_report",
    "build_pubmed_query",
    "discover_dailymed_labels",
    "fetch_dailymed_label",
    "fetch_pubmed_article",
    "research_pubmed_draft",
    "search_pubmed",
]
