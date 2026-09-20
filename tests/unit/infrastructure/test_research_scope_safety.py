"""Offline public-only local scope admission and redacted rejection classes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest

from medevidence.catalog import CATALOG_SHA256
from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    DrugConcept,
    InclusiveDateRange,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)
from medevidence.infrastructure.research_scope_safety import (
    LOCAL_RESEARCH_INPUT_CATALOG_HASH,
    LOCAL_RESEARCH_INPUT_CATALOG_VERSION,
    LocalResearchScopeSafety,
    load_local_research_input_catalog,
)
from medevidence.orchestration.contracts import SafetyOutcome, SafetyReason

TODAY = date(2026, 9, 14)


def _ui_id(kind: str, term: str) -> str:
    digest = sha256((kind + "\0" + term.casefold()).encode()).hexdigest()
    return f"input-{kind}:{digest}"


def _scope(
    *,
    drug: str = "Semaglutide",
    reaction: str = "Nausea",
    drug_id: str | None = None,
    reaction_id: str | None = None,
    sources: tuple[SourceType, ...] = (SourceType.PUBMED,),
    date_range: InclusiveDateRange | None = None,
) -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id=drug_id or _ui_id("drug", drug), preferred_term=drug),),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id=reaction_id or _ui_id("reaction", reaction),
                preferred_term=reaction,
            ),
        ),
        date_range=date_range,
        selected_sources=sources,
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=2, max_total_seconds=30),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=100_000),
    )


def _policy() -> LocalResearchScopeSafety:
    return LocalResearchScopeSafety(
        catalog=load_local_research_input_catalog(), today=lambda: TODAY
    )


@pytest.mark.parametrize("drug", ("Semaglutide", "semaglutide", "SEMAGLUTIDE", "Tirzepatide"))
@pytest.mark.parametrize("reaction", ("Nausea", "Vomiting", "Diarrhoea", "diarrhoea"))
def test_exact_public_terms_are_case_insensitive_without_rewriting_scope(
    drug: str, reaction: str
) -> None:
    scope = _scope(drug=drug, reaction=reaction)
    decision = _policy().evaluate(scope)
    assert decision.decision.outcome is SafetyOutcome.PERMITTED
    assert decision.decision.reason is SafetyReason.PERMITTED_RESEARCH_SCOPE
    assert decision.interpreted_scope == scope
    assert decision.interpreted_scope.scope_id == scope.scope_id


def test_catalog_is_additive_immutable_and_uses_ui_local_ids() -> None:
    catalog = load_local_research_input_catalog()
    assert catalog.version == LOCAL_RESEARCH_INPUT_CATALOG_VERSION
    assert catalog.content_hash == LOCAL_RESEARCH_INPUT_CATALOG_HASH
    assert tuple(catalog.drugs_by_term) == ("semaglutide", "tirzepatide")
    assert set(catalog.reactions_by_term) == {"nausea", "vomiting", "diarrhoea"}
    assert catalog.drugs_by_term["semaglutide"].concept_id == _ui_id("drug", "Semaglutide")
    assert catalog.reactions_by_term["diarrhoea"].concept_id == _ui_id("reaction", "Diarrhoea")
    with pytest.raises(TypeError):
        catalog.drugs_by_term["other"] = catalog.drugs_by_term["semaglutide"]  # type: ignore[index]
    assert CATALOG_SHA256 == "eaffc3ee01ecd46a134578838b0304474642bf5e4a0c6e87302825d52be7682e"


@pytest.mark.parametrize(
    "drug,reaction",
    (
        ("\u017femaglutide", "Nausea"),
        ("Semaglutide", "Nau\u017fea"),
        ("\uff33emaglutide", "Nausea"),
        ("Semaglutide", "Vom\u0131t\u0131ng"),
    ),
)
def test_unicode_casefold_aliases_cannot_expand_literal_public_catalog(
    drug: str, reaction: str
) -> None:
    decision = _policy().evaluate(_scope(drug=drug, reaction=reaction))
    assert decision.decision.outcome is SafetyOutcome.BLOCKED
    assert decision.decision.reason is SafetyReason.UNSAFE_SCOPE


def test_forged_or_mutated_catalog_cannot_expand_policy() -> None:
    trusted = load_local_research_input_catalog()
    mutable_drugs = dict(trusted.drugs_by_term)
    mutable_drugs["aspirin"] = DrugConcept(
        concept_id=_ui_id("drug", "Aspirin"), preferred_term="Aspirin"
    )
    forged = replace(trusted, drugs_by_term=mutable_drugs)
    with pytest.raises(ValueError, match="catalog identity drift"):
        LocalResearchScopeSafety(catalog=forged, today=lambda: TODAY)

    mutable_drugs.pop("aspirin")
    policy = LocalResearchScopeSafety(
        catalog=replace(trusted, drugs_by_term=mutable_drugs), today=lambda: TODAY
    )
    mutable_drugs["aspirin"] = DrugConcept(
        concept_id=_ui_id("drug", "Aspirin"), preferred_term="Aspirin"
    )
    assert policy.evaluate(_scope(drug="Aspirin")).decision.reason is SafetyReason.UNSAFE_SCOPE


def test_all_existing_v1_source_codes_are_admitted_as_scope_only() -> None:
    scope = _scope(
        sources=(
            SourceType.PUBMED,
            SourceType.DAILYMED,
            SourceType.FAERS,
            SourceType.CADEC,
        )
    )
    assert _policy().evaluate(scope).decision.outcome is SafetyOutcome.PERMITTED


@pytest.mark.parametrize(
    "kwargs",
    (
        {"drug": "Aspirin"},
        {"reaction": "Headache"},
        {"drug": " Semaglutide"},
        {"drug": "Semaglutide ", "drug_id": _ui_id("drug", "Semaglutide")},
        {"drug_id": "m1a.drug.semaglutide"},
        {"reaction_id": "input-reaction:" + "0" * 64},
    ),
)
def test_unknown_or_foreign_identity_is_rejected_without_ontology_inference(
    kwargs: dict[str, str],
) -> None:
    decision = _policy().evaluate(_scope(**kwargs))
    assert decision.decision.outcome is SafetyOutcome.BLOCKED
    assert decision.decision.reason is SafetyReason.UNSAFE_SCOPE


@pytest.mark.parametrize(
    "term",
    (
        "Patient Jane Doe",
        "Jane Doe",
        "MRN 123456",
        "DOB 2000-01-01",
        "123 Main Street",
        "jane@example.org",
        "clinical note: synthetic case",
        "phone 555-123-4567",
        "my mother has symptoms",
    ),
)
def test_suspected_patient_data_is_classified_before_unknown_term(term: str) -> None:
    decision = _policy().evaluate(_scope(drug=term))
    assert decision.decision.outcome is SafetyOutcome.BLOCKED
    assert decision.decision.reason is SafetyReason.SUSPECTED_PHI


@pytest.mark.parametrize(
    "term", ("what dose of Semaglutide", "5 mg", "diagnose nausea", "should I treat")
)
def test_dose_diagnosis_and_individualized_advice_are_blocked(term: str) -> None:
    decision = _policy().evaluate(_scope(reaction=term))
    assert decision.decision.outcome is SafetyOutcome.BLOCKED
    assert decision.decision.reason is SafetyReason.UNRESOLVED_MEDICAL_BOUNDARY


@pytest.mark.parametrize(
    "date_range",
    (
        InclusiveDateRange(start_date=date(1899, 1, 1), end_date=date(1900, 1, 1)),
        InclusiveDateRange(start_date=date(2026, 9, 1), end_date=date(2026, 9, 15)),
    ),
)
def test_date_window_is_finite_and_no_future_dates(date_range: InclusiveDateRange) -> None:
    decision = _policy().evaluate(_scope(date_range=date_range))
    assert decision.decision.reason is SafetyReason.UNSAFE_SCOPE
    supported = InclusiveDateRange(start_date=date(2020, 1, 1), end_date=TODAY)
    assert (
        _policy().evaluate(_scope(date_range=supported)).decision.outcome is SafetyOutcome.PERMITTED
    )


def test_invalid_constructed_scope_is_rejected_without_policy_side_effect() -> None:
    valid = _scope()
    forged = valid.model_copy(update={"scope_id": "scope:sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        _policy().evaluate(forged)
