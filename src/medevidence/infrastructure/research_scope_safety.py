"""Closed public local-input catalog and stateless V1 scope safety policy."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from types import MappingProxyType
from typing import Final, Literal, final

from medevidence.domain import (
    MAX_ADVERSE_REACTIONS,
    MAX_DRUGS,
    MAX_PAGES,
    MAX_PAYLOAD_BYTES,
    MAX_QUERY_CHARACTERS,
    MAX_RECORDS,
    MAX_TOTAL_EXECUTION_SECONDS,
    AdverseEventConcept,
    DrugConcept,
    ResearchScope,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.orchestration.contracts import (
    SafetyDecision,
    SafetyOutcome,
    SafetyReason,
    ScopeSafetyEvaluation,
)

LOCAL_RESEARCH_INPUT_CATALOG_VERSION: Final = "m3.local-research-input.v1"
LOCAL_RESEARCH_SAFETY_POLICY_VERSION: Final = "m3.local-research-safety.v1"
LOCAL_RESEARCH_INPUT_CATALOG_HASH: Final = (
    "sha256:60ad5de184b4ab9972ca6179e4df8fd0f56d8e6741852f48331b465772b0e4ba"
)
_DRUG_NAMES: Final = ("Semaglutide", "Tirzepatide")
_REACTION_NAMES: Final = ("Nausea", "Vomiting", "Diarrhoea")
_SOURCES: Final = (
    SourceType.PUBMED,
    SourceType.DAILYMED,
    SourceType.FAERS,
    SourceType.CADEC,
)
_EARLIEST_DATE: Final = date(1900, 1, 1)
_PHI_PATTERN: Final = re.compile(
    r"(?i)(?:\b(?:patient|mrn|medical record|account number|date of birth|dob|ssn|social security|"
    r"phone|telephone|email|address|clinical note|case history|my mother|my father|my child|"
    r"my wife|my husband|name is|born on)\b|"
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{3}[-. ]\d{2}[-. ]\d{4}\b|"
    r"\b\d{1,5}\s+[A-Za-z ]+\s+(?:street|st|avenue|ave|road|rd|lane|ln)\b)"
)
_PERSON_NAME_PATTERN: Final = re.compile(r"^[A-Z][a-z]{1,40}\s+[A-Z][a-z]{1,40}$")
_ADVICE_PATTERN: Final = re.compile(
    r"(?i)\b(?:diagnos\w*|treat\w*|prescrib\w*|dose|dosage|mg|mcg|"
    r"emergency|should i|how much|for me|personal risk)\b"
)


def _input_id(kind: Literal["drug", "reaction"], term: str) -> str:
    if type(term) is not str or not term.isascii() or not term:
        raise ValueError("local input term is invalid")
    digest = sha256((kind + "\0" + term.casefold()).encode("utf-8")).hexdigest()
    return f"input-{kind}:{digest}"


@dataclass(frozen=True, slots=True)
class LocalResearchInputCatalog:
    """Literal public terms and UI-local identities, without ontology mapping."""

    version: str
    content_hash: str
    drugs_by_term: Mapping[str, DrugConcept]
    reactions_by_term: Mapping[str, AdverseEventConcept]
    sources: tuple[SourceType, ...]

    def matches_drug(self, concept: DrugConcept) -> bool:
        if type(concept) is not DrugConcept or not concept.preferred_term.isascii():
            return False
        expected = self.drugs_by_term.get(concept.preferred_term.lower())
        return expected is not None and concept.concept_id == expected.concept_id

    def matches_reaction(self, concept: AdverseEventConcept) -> bool:
        if type(concept) is not AdverseEventConcept or not concept.preferred_term.isascii():
            return False
        expected = self.reactions_by_term.get(concept.preferred_term.lower())
        return expected is not None and concept.concept_id == expected.concept_id


def _catalog_payload() -> dict[str, object]:
    return {
        "version": LOCAL_RESEARCH_INPUT_CATALOG_VERSION,
        "drugs": tuple((name, _input_id("drug", name)) for name in _DRUG_NAMES),
        "reactions": tuple((name, _input_id("reaction", name)) for name in _REACTION_NAMES),
        "sources": tuple(source.value for source in _SOURCES),
    }


def load_local_research_input_catalog() -> LocalResearchInputCatalog:
    """Verify the additive local terms and return immutable typed lookup tables."""

    if sha256_digest(canonical_json(_catalog_payload())) != LOCAL_RESEARCH_INPUT_CATALOG_HASH:
        raise RuntimeError("local research input catalog identity drift")
    drugs = {
        name.casefold(): DrugConcept(concept_id=_input_id("drug", name), preferred_term=name)
        for name in _DRUG_NAMES
    }
    reactions = {
        name.casefold(): AdverseEventConcept(
            concept_id=_input_id("reaction", name), preferred_term=name
        )
        for name in _REACTION_NAMES
    }
    return LocalResearchInputCatalog(
        version=LOCAL_RESEARCH_INPUT_CATALOG_VERSION,
        content_hash=LOCAL_RESEARCH_INPUT_CATALOG_HASH,
        drugs_by_term=MappingProxyType(drugs),
        reactions_by_term=MappingProxyType(reactions),
        sources=_SOURCES,
    )


def _classified_reason(
    scope: ResearchScope, catalog: LocalResearchInputCatalog, today: date
) -> SafetyReason:
    terms = tuple(item.preferred_term for item in scope.drugs) + tuple(
        item.preferred_term for item in scope.adverse_reactions
    )
    if any(_PHI_PATTERN.search(term) or _PERSON_NAME_PATTERN.fullmatch(term) for term in terms):
        return SafetyReason.SUSPECTED_PHI
    if any(_ADVICE_PATTERN.search(term) for term in terms):
        return SafetyReason.UNRESOLVED_MEDICAL_BOUNDARY
    if (
        not 1 <= len(scope.drugs) <= MAX_DRUGS
        or not 1 <= len(scope.adverse_reactions) <= MAX_ADVERSE_REACTIONS
        or any(not catalog.matches_drug(item) for item in scope.drugs)
        or any(not catalog.matches_reaction(item) for item in scope.adverse_reactions)
        or not scope.selected_sources
        or any(source not in catalog.sources for source in scope.selected_sources)
        or scope.query_bounds.max_query_characters > MAX_QUERY_CHARACTERS
        or scope.query_bounds.max_pages > MAX_PAGES
        or scope.query_bounds.max_total_seconds > MAX_TOTAL_EXECUTION_SECONDS
        or scope.result_bounds.max_records > MAX_RECORDS
        or scope.result_bounds.max_payload_bytes > MAX_PAYLOAD_BYTES
    ):
        return SafetyReason.UNSAFE_SCOPE
    date_range = scope.date_range
    if date_range is not None and (
        date_range.start_date < _EARLIEST_DATE or date_range.end_date > today
    ):
        return SafetyReason.UNSAFE_SCOPE
    return SafetyReason.PERMITTED_RESEARCH_SCOPE


@final
class LocalResearchScopeSafety:
    """Classify one exact typed public scope without persistence or external I/O."""

    __slots__ = ("_catalog", "_today")
    _catalog: LocalResearchInputCatalog
    _today: Callable[[], date]

    def __init__(
        self,
        *,
        catalog: LocalResearchInputCatalog,
        today: Callable[[], date] = date.today,
    ) -> None:
        if type(catalog) is not LocalResearchInputCatalog:
            raise TypeError("scope safety requires the exact local input catalog")
        trusted = load_local_research_input_catalog()
        if catalog != trusted:
            raise ValueError("scope safety catalog identity drift")
        object.__setattr__(self, "_catalog", trusted)
        object.__setattr__(self, "_today", today)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("scope safety policy is immutable")

    def evaluate(self, scope: ResearchScope) -> ScopeSafetyEvaluation:
        """Return a redacted decision while preserving the exact scope identity."""

        if type(scope) is not ResearchScope:
            raise ValueError("scope safety requires exact ResearchScope")
        copied = ResearchScope.model_validate_json(scope.model_dump_json(), strict=True)
        if copied != scope:
            raise ValueError("scope safety typed reconstruction drift")
        today = self._today()
        if type(today) is not date:
            raise ValueError("scope safety clock must return an exact date")
        reason = _classified_reason(copied, self._catalog, today)
        decision = SafetyDecision(
            outcome=(
                SafetyOutcome.PERMITTED
                if reason is SafetyReason.PERMITTED_RESEARCH_SCOPE
                else SafetyOutcome.BLOCKED
            ),
            reason=reason,
            policy_version=LOCAL_RESEARCH_SAFETY_POLICY_VERSION,
        )
        return ScopeSafetyEvaluation(interpreted_scope=copied, decision=decision)
