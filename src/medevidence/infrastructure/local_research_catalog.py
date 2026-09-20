"""Scope-bound public catalog adapter for the existing bounded PubMed tool."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from medevidence.domain import ResearchScope
from medevidence.orchestration.contracts import SafetyOutcome
from medevidence.tools.contracts import ResolvedConceptCatalog

from .research_scope_safety import (
    LocalResearchScopeSafety,
    load_local_research_input_catalog,
)


@dataclass(frozen=True, slots=True, init=False)
class LocalResearchCatalogAdapter:
    _scope: ResearchScope

    def __init__(self, scope: ResearchScope, *, today: Callable[[], date] = date.today) -> None:
        policy = LocalResearchScopeSafety(catalog=load_local_research_input_catalog(), today=today)
        evaluated = policy.evaluate(scope)
        if evaluated.decision.outcome is not SafetyOutcome.PERMITTED:
            raise ValueError("scope is outside the local public catalog")
        object.__setattr__(self, "_scope", evaluated.interpreted_scope)

    def resolve(self, scope_id: str) -> ResolvedConceptCatalog:
        if scope_id != self._scope.scope_id:
            raise ValueError("catalog request belongs to another scope")
        catalog = load_local_research_input_catalog()
        return ResolvedConceptCatalog(
            catalog_version="m3.local-research-input.v1",
            catalog_content_hash=catalog.content_hash,
            drugs=self._scope.drugs,
            adverse_reactions=self._scope.adverse_reactions,
        )
