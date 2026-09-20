"""Additive local PubMed requests with a master budget and fixed source ceilings."""

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from medevidence.domain import ExecutionBounds, ResearchScope, SourceType

from .contracts import FetchPubMedArticleRequest, ResearchPubMedRequest, SearchPubMedRequest
from .runtime_source_bounds import RUNTIME_SOURCE_BOUNDS_V3


class PubMedBoundsPolicy(StrEnum):
    """Explicit compatibility boundary for collection execution limits."""

    EXACT_SCOPE = "exact_scope"
    LOCAL_PUBLIC_V1 = "local_public_v1"


def pubmed_execution_bounds(scope: ResearchScope, policy: PubMedBoundsPolicy) -> ExecutionBounds:
    """Resolve fixed source limits without relabelling the caller's scope."""
    if type(policy) is not PubMedBoundsPolicy:
        raise TypeError("PubMed bounds policy must be an explicit admitted enum")
    requested = ExecutionBounds.from_scope(scope)
    if policy is PubMedBoundsPolicy.EXACT_SCOPE:
        return requested
    characters, pages, records, payload, seconds = dict(RUNTIME_SOURCE_BOUNDS_V3)[SourceType.PUBMED]
    effective = ExecutionBounds(
        max_query_characters=characters,
        max_pages=pages,
        max_records=records,
        max_payload_bytes=payload,
        max_total_seconds=seconds,
    )
    budget = requested.model_dump()
    if any(value > budget[key] for key, value in effective.model_dump().items()):
        raise ValueError("fixed PubMed execution profile exceeds the requested budget")
    return effective


def _validate_local_scope(scope: ResearchScope) -> None:
    if SourceType.PUBMED not in scope.selected_sources:
        raise ValueError("local PubMed requests require PubMed in the selected scope")
    if len(scope.drugs) > 4 or len(scope.adverse_reactions) > 4:
        raise ValueError("local PubMed requests support at most four terms per concept group")
    pubmed_execution_bounds(scope, PubMedBoundsPolicy.LOCAL_PUBLIC_V1)


class LocalSearchPubMedRequest(SearchPubMedRequest):
    """Local search budget; source execution still uses the fixed PubMed profile."""

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_local_scope(self.scope)
        return self


class LocalFetchPubMedArticleRequest(FetchPubMedArticleRequest):
    """Local fetch retaining exact query and singular PMID identity."""

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_local_scope(self.scope)
        if len(self.pmid) > 16:
            raise ValueError("PubMed identifiers must contain at most 16 digits")
        return self


class LocalResearchPubMedRequest(ResearchPubMedRequest):
    """Local collection request with unchanged master scope identity."""

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_local_scope(self.scope)
        return self


def reconstruct_pubmed_request(request: ResearchPubMedRequest) -> ResearchPubMedRequest:
    """Revalidate only a named admitted request type, including model-copy fields."""
    if type(request) not in (ResearchPubMedRequest, LocalResearchPubMedRequest):
        raise TypeError("unknown PubMed research request contract")
    return type(request).model_validate(request.model_dump(mode="python"))
