"""Unit tests for strict identifiers, bounds, and research scopes."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    MAX_ADVERSE_REACTIONS,
    MAX_DRUGS,
    MAX_PAGES,
    MAX_PAYLOAD_BYTES,
    MAX_QUERY_CHARACTERS,
    MAX_RECORDS,
    MAX_TOTAL_EXECUTION_SECONDS,
    AdverseEventConcept,
    ComparisonIntent,
    DrugConcept,
    InclusiveDateRange,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)


def query_bounds() -> QueryBounds:
    return QueryBounds(
        max_query_characters=MAX_QUERY_CHARACTERS,
        max_pages=MAX_PAGES,
        max_total_seconds=MAX_TOTAL_EXECUTION_SECONDS,
    )


def result_bounds() -> ResultBounds:
    return ResultBounds(
        max_records=MAX_RECORDS,
        max_payload_bytes=MAX_PAYLOAD_BYTES,
    )


def make_scope(
    *,
    drugs: tuple[DrugConcept, ...] | None = None,
    reactions: tuple[AdverseEventConcept, ...] | None = None,
    sources: tuple[SourceType, ...] = (SourceType.PUBMED,),
    intent: ComparisonIntent = ComparisonIntent.COMPARE,
) -> ResearchScope:
    return ResearchScope.create(
        drugs=drugs
        or (
            DrugConcept(
                concept_id="drug:semaglutide",
                preferred_term="semaglutide",
            ),
            DrugConcept(
                concept_id="drug:tirzepatide",
                preferred_term="tirzepatide",
            ),
        ),
        adverse_reactions=reactions
        or (
            AdverseEventConcept(
                concept_id="event:gastrointestinal",
                preferred_term="gastrointestinal adverse reactions",
            ),
        ),
        date_range=InclusiveDateRange(
            start_date=date(2020, 1, 1),
            end_date=date(2026, 7, 27),
        ),
        selected_sources=sources,
        comparison_intent=intent,
        query_bounds=query_bounds(),
        result_bounds=result_bounds(),
    )


@pytest.mark.parametrize(
    ("model", "field", "maximum"),
    [
        (QueryBounds, "max_query_characters", MAX_QUERY_CHARACTERS),
        (QueryBounds, "max_pages", MAX_PAGES),
        (QueryBounds, "max_total_seconds", MAX_TOTAL_EXECUTION_SECONDS),
        (ResultBounds, "max_records", MAX_RECORDS),
        (ResultBounds, "max_payload_bytes", MAX_PAYLOAD_BYTES),
    ],
)
def test_every_numeric_bound_accepts_minimum_and_maximum(
    model: type[QueryBounds] | type[ResultBounds],
    field: str,
    maximum: int,
) -> None:
    values = (
        {
            "max_query_characters": 1,
            "max_pages": 1,
            "max_total_seconds": 1,
        }
        if model is QueryBounds
        else {"max_records": 1, "max_payload_bytes": 1}
    )
    model(**values)
    values[field] = maximum
    model(**values)


@pytest.mark.parametrize(
    ("model", "field", "maximum"),
    [
        (QueryBounds, "max_query_characters", MAX_QUERY_CHARACTERS),
        (QueryBounds, "max_pages", MAX_PAGES),
        (QueryBounds, "max_total_seconds", MAX_TOTAL_EXECUTION_SECONDS),
        (ResultBounds, "max_records", MAX_RECORDS),
        (ResultBounds, "max_payload_bytes", MAX_PAYLOAD_BYTES),
    ],
)
def test_every_numeric_bound_rejects_zero_and_above_maximum(
    model: type[QueryBounds] | type[ResultBounds],
    field: str,
    maximum: int,
) -> None:
    values = (
        {
            "max_query_characters": 1,
            "max_pages": 1,
            "max_total_seconds": 1,
        }
        if model is QueryBounds
        else {"max_records": 1, "max_payload_bytes": 1}
    )
    for invalid in (0, maximum + 1):
        values[field] = invalid
        with pytest.raises(ValidationError):
            model(**values)


def test_reference_and_synthetic_scopes_use_the_same_contract() -> None:
    reference = make_scope()
    synthetic = make_scope(
        drugs=(
            DrugConcept(concept_id="drug:alpha", preferred_term="alpha"),
            DrugConcept(concept_id="drug:beta", preferred_term="beta"),
        ),
        reactions=(
            AdverseEventConcept(
                concept_id="event:synthetic",
                preferred_term="synthetic event",
            ),
        ),
        intent=ComparisonIntent.SUMMARIZE,
    )

    assert type(reference) is type(synthetic) is ResearchScope
    assert reference.scope_id != synthetic.scope_id
    assert ResearchScope.model_validate_json(reference.model_dump_json()) == reference


def test_scope_canonicalizes_through_create_and_identity_is_stable() -> None:
    first = make_scope(
        drugs=(
            DrugConcept(concept_id="drug:beta", preferred_term="beta"),
            DrugConcept(concept_id="drug:alpha", preferred_term="alpha"),
        ),
        sources=(SourceType.PUBMED, SourceType.CADEC),
    )
    second = make_scope(
        drugs=(
            DrugConcept(concept_id="drug:alpha", preferred_term="alpha"),
            DrugConcept(concept_id="drug:beta", preferred_term="beta"),
        ),
        sources=(SourceType.CADEC, SourceType.PUBMED),
    )

    assert first == second
    assert first.scope_id == second.scope_id
    assert first.drugs[0].concept_id == "drug:alpha"
    assert first.selected_sources == (SourceType.CADEC, SourceType.PUBMED)


def test_scope_limits_drug_and_reaction_cardinality() -> None:
    maximum_drugs = tuple(
        DrugConcept(concept_id=f"drug:{index}", preferred_term=f"drug {index}")
        for index in range(MAX_DRUGS)
    )
    maximum_reactions = tuple(
        AdverseEventConcept(
            concept_id=f"event:{index}",
            preferred_term=f"event {index}",
        )
        for index in range(MAX_ADVERSE_REACTIONS)
    )
    make_scope(drugs=maximum_drugs, reactions=maximum_reactions)

    with pytest.raises(ValidationError):
        make_scope(
            drugs=(
                *maximum_drugs,
                DrugConcept(concept_id="drug:extra", preferred_term="extra"),
            )
        )
    with pytest.raises(ValidationError):
        make_scope(
            reactions=(
                *maximum_reactions,
                AdverseEventConcept(
                    concept_id="event:extra",
                    preferred_term="extra",
                ),
            )
        )


def test_scope_rejects_duplicates_tampered_identity_and_reversed_date() -> None:
    scope = make_scope()
    duplicate = (scope.drugs[0], scope.drugs[0])
    with pytest.raises(ValidationError):
        ResearchScope(
            **{
                **scope.model_dump(mode="python"),
                "drugs": duplicate,
            }
        )
    with pytest.raises(ValidationError):
        ResearchScope(
            **{
                **scope.model_dump(mode="python"),
                "scope_id": f"scope:sha256:{'0' * 64}",
            }
        )
    with pytest.raises(ValidationError):
        InclusiveDateRange(
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 1),
        )


def test_scope_is_strict_frozen_versioned_and_forbids_extras() -> None:
    scope = make_scope()
    assert scope.schema_version == "1.0"
    with pytest.raises(ValidationError):
        QueryBounds(
            max_query_characters="512",
            max_pages=5,
            max_total_seconds=60,
        )
    with pytest.raises(ValidationError):
        DrugConcept(
            concept_id="drug:test",
            preferred_term="test",
            provider_payload="forbidden",
        )
    with pytest.raises(ValidationError):
        scope.comparison_intent = ComparisonIntent.SUMMARIZE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("comparison_intent", "rank"),
        ("language", "fr"),
        ("schema_version", "2.0"),
    ],
)
def test_scope_rejects_unapproved_vocabulary(
    field: str,
    value: str,
) -> None:
    scope = make_scope()
    data = scope.model_dump(mode="python")
    data[field] = value
    with pytest.raises(ValidationError):
        ResearchScope(**data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("concept_id", " leading"),
        ("concept_id", ""),
        ("preferred_term", "   "),
    ],
)
def test_typed_concept_identifiers_and_terms_reject_invalid_values(
    field: str,
    value: str,
) -> None:
    data = {"concept_id": "drug:valid", "preferred_term": "valid"}
    data[field] = value
    with pytest.raises(ValidationError):
        DrugConcept(**data)
