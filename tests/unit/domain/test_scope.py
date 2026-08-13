"""Unit tests for strict identifiers, bounds, and research scopes."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    GI_PT_DISPLAY_MAPPING_M1B_V1,
    GI_PT_EXCLUSIONS_M1B_V1,
    GI_PT_SET_M1B_V1,
    MAX_ADVERSE_REACTIONS,
    MAX_DRUGS,
    MAX_PAGES,
    MAX_PAYLOAD_BYTES,
    MAX_QUERY_CHARACTERS,
    MAX_RECORDS,
    MAX_TOTAL_EXECUTION_SECONDS,
    AdverseEventConcept,
    ComparisonIntent,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DrugConcept,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    InclusiveDateRange,
    M1BResearchRequestV1,
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


def dailymed_request(**changes: object) -> DailyMedSelectionRequestV1:
    values: dict[str, object] = {
        "drug_concept_id": "drug:semaglutide",
        "pinned_setid": None,
        "pinned_spl_version": None,
        "requested_section_codes": ("34066-1", "34084-4"),
        "selection_mode": DailyMedSelectionMode.STRICT_IDENTITY,
    }
    values.update(changes)
    return DailyMedSelectionRequestV1(**values)


def test_dailymed_request_freezes_exact_section_and_pin_contract() -> None:
    request = dailymed_request()
    assert request.requested_section_codes == ("34066-1", "34084-4")

    pinned = dailymed_request(
        pinned_setid="11111111-1111-1111-1111-111111111111",
        pinned_spl_version="7",
        selection_mode=DailyMedSelectionMode.PINNED_VERSION,
    )
    assert pinned.pinned_spl_version == "7"

    for changes in (
        {"pinned_setid": "11111111-1111-1111-1111-111111111111"},
        {"pinned_spl_version": "1"},
        {
            "pinned_setid": "11111111-1111-1111-1111-111111111111",
            "pinned_spl_version": "1",
        },
        {
            "selection_mode": DailyMedSelectionMode.PINNED_VERSION,
        },
        {"requested_section_codes": ("34084-4", "34066-1")},
        {"requested_section_codes": ("34084-4", "34084-4")},
        {"requested_section_codes": ("99999-9",)},
    ):
        with pytest.raises(ValidationError):
            dailymed_request(**changes)


@pytest.mark.parametrize(
    "invalid_setid",
    [
        "00000000-0000-0000-0000-000000000000",
        "11111111-1111-1111-1111-11111111111A",
        "{11111111-1111-1111-1111-111111111111}",
        "urn:uuid:11111111-1111-1111-1111-111111111111",
        " 11111111-1111-1111-1111-111111111111",
        "11111111%2d1111-1111-1111-111111111111",
        "111111111111-1111-1111-111111111111",
        "x11111111-1111-1111-1111-111111111111",
    ],
)
def test_setid_rejects_every_noncanonical_or_nil_form(invalid_setid: str) -> None:
    with pytest.raises(ValidationError):
        dailymed_request(
            pinned_setid=invalid_setid,
            pinned_spl_version="1",
            selection_mode=DailyMedSelectionMode.PINNED_VERSION,
        )


@pytest.mark.parametrize("valid_setid", ["11111111-1111-1111-1111-111111111111"])
def test_setid_does_not_restrict_uuid_version_or_variant(valid_setid: str) -> None:
    assert (
        dailymed_request(
            pinned_setid=valid_setid,
            pinned_spl_version="1",
            selection_mode=DailyMedSelectionMode.PINNED_VERSION,
        ).pinned_setid
        == valid_setid
    )


def test_parallel_m1b_request_binds_canonical_scope_sources() -> None:
    scope = make_scope(
        drugs=(DrugConcept(concept_id="drug:semaglutide", preferred_term="semaglutide"),),
        sources=(SourceType.DAILYMED,),
    )
    request = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000001",
        scope=scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(dailymed_request(),),
    )
    assert request.schema_version == "m1b.request.v1"
    assert "source_plan" not in type(request).model_fields
    assert M1BResearchRequestV1.model_validate_json(request.model_dump_json()) == request

    drifted_dailymed_request = request.dailymed_selection_requests[0].model_copy(
        update={"requested_section_codes": ("34084-4", "34066-1")}
    )
    with pytest.raises(ValidationError):
        M1BResearchRequestV1.model_validate(
            request.model_copy(update={"dailymed_selection_requests": (drifted_dailymed_request,)})
        )
    with pytest.raises(ValidationError):
        M1BResearchRequestV1.model_validate(
            request.model_copy(update={"requested_sources": (SourceType.PUBMED,)})
        )

    with pytest.raises(ValidationError):
        M1BResearchRequestV1(
            request_id="request:00000000-0000-4000-8000-000000000001",
            scope=scope,
            requested_sources=(SourceType.PUBMED,),
            dailymed_selection_requests=(dailymed_request(),),
        )


def faers_request(**changes: object) -> FaersAggregateRequestV1:
    values: dict[str, object] = {
        "drug_concept_id": "drug:semaglutide",
        "identity_strategy": FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
        "identity_exact_value": "SEMAGLUTIDE",
        "pt_values": GI_PT_SET_M1B_V1,
        "inclusive_date_range": FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
        ),
        "execution_bounds": FaersExecutionBoundsV1(
            max_date_difference_days=365,
            max_inclusive_calendar_dates=366,
        ),
        "statistical_unit": "provider_count_occurrence",
    }
    values.update(changes)
    return FaersAggregateRequestV1(**values)


def test_faers_pt_set_is_exact_bounded_reference_only_mapping() -> None:
    assert GI_PT_SET_M1B_V1 == ("DIARRHOEA", "NAUSEA", "VOMITING")
    assert GI_PT_DISPLAY_MAPPING_M1B_V1 == (
        ("DIARRHOEA", "Diarrhoea"),
        ("NAUSEA", "Nausea"),
        ("VOMITING", "Vomiting"),
    )
    assert GI_PT_EXCLUSIONS_M1B_V1 == ("ABDOMINAL PAIN", "CONSTIPATION")
    request = faers_request()
    assert request.pt_values == GI_PT_SET_M1B_V1
    assert request.statistical_unit == "provider_count_occurrence"
    dumped = request.model_dump(mode="python")
    assert dumped["pt_values"] == GI_PT_SET_M1B_V1
    assert dumped["statistical_unit"] == "provider_count_occurrence"

    for field in ("pt_values", "statistical_unit"):
        missing = request.model_dump(mode="python")
        del missing[field]
        with pytest.raises(ValidationError):
            FaersAggregateRequestV1.model_validate(missing)

    for value in (
        ("NAUSEA", "DIARRHOEA", "VOMITING"),
        ("DIARRHOEA", "NAUSEA"),
        ("DIARRHOEA", "NAUSEA", "VOMITING", "CONSTIPATION"),
        ("DIARRHOEA", "Nausea", "VOMITING"),
        ("DIARRHEA", "NAUSEA", "VOMITING"),
        ("DIARRHOEA", "NAUSEA", "VOMITING\u0301"),
    ):
        with pytest.raises(ValidationError):
            FaersAggregateRequestV1(**{**request.model_dump(mode="python"), "pt_values": value})

    with pytest.raises(ValidationError):
        FaersAggregateRequestV1(
            **{
                **request.model_dump(mode="python"),
                "statistical_unit": "patient",
            }
        )

    drifted = request.model_copy(update={"pt_values": ("NAUSEA",)})
    with pytest.raises(ValidationError):
        FaersAggregateRequestV1.model_validate(drifted)


def test_faers_receivedate_window_accepts_one_and_366_dates_only() -> None:
    for end in (date(2025, 1, 1), date(2026, 1, 1)):
        window = FaersInclusiveDateRangeV1(start_date=date(2025, 1, 1), end_date=end)
        assert window.date_field == "receivedate"
    for end in (date(2026, 1, 2), date(2026, 1, 3)):
        with pytest.raises(ValidationError):
            FaersInclusiveDateRangeV1(start_date=date(2025, 1, 1), end_date=end)
    with pytest.raises(ValidationError):
        FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            date_field="receiptdate",
        )


def test_faers_date_bounds_are_required_exact_and_non_bypassable() -> None:
    bounds = faers_request().execution_bounds
    dumped = bounds.model_dump(mode="python")
    assert dumped["max_date_difference_days"] == 365
    assert dumped["max_inclusive_calendar_dates"] == 366

    for field, drift in (
        ("max_date_difference_days", 364),
        ("max_inclusive_calendar_dates", 365),
    ):
        missing = dict(dumped)
        del missing[field]
        with pytest.raises(ValidationError):
            FaersExecutionBoundsV1.model_validate(missing)
        with pytest.raises(ValidationError):
            FaersExecutionBoundsV1.model_validate({**dumped, field: drift})
        forged = bounds.model_copy(update={field: drift})
        with pytest.raises(ValidationError):
            FaersExecutionBoundsV1.model_validate(forged)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aggregation_mode", "raw_latest_report"),
        ("role_policy", "primary_suspect"),
        ("effective_total_deadline_ms", 30_001),
        ("execution_profile_id", "ordinary"),
        ("identity_exact_value", "SEMAGLUTIDE%20INJECTION"),
        ("identity_exact_value", "e\u0301"),
    ],
)
def test_faers_request_rejects_every_closed_contract_drift(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        FaersAggregateRequestV1(**{**faers_request().model_dump(mode="python"), field: value})
    assert "role" not in FaersAggregateRequestV1.model_fields
    assert "role_predicate" not in FaersAggregateRequestV1.model_fields


def test_m1b_faers_request_envelope_is_exact_bounded_and_canonical() -> None:
    drugs = tuple(
        DrugConcept(concept_id=f"drug:{index}", preferred_term=f"drug {index}")
        for index in range(4)
    )
    faers_scope = make_scope(drugs=drugs, sources=(SourceType.FAERS,))
    requests = tuple(
        faers_request(
            drug_concept_id=drug.concept_id,
            identity_strategy=strategy,
            identity_exact_value=f"DRUG {drug.concept_id[-1]}",
        )
        for drug in drugs
        for strategy in (
            FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT,
        )
    )
    envelope = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000001",
        scope=faers_scope,
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=requests,
    )
    assert len(envelope.faers_query_requests) == 8
    assert M1BResearchRequestV1.model_validate(envelope.model_dump(mode="python")) == envelope

    with pytest.raises(ValidationError):
        M1BResearchRequestV1(
            request_id=envelope.request_id,
            scope=faers_scope,
            requested_sources=(SourceType.FAERS,),
            faers_query_requests=(*requests, requests[0]),
        )
    with pytest.raises(ValidationError, match="canonically sorted"):
        M1BResearchRequestV1(
            request_id=envelope.request_id,
            scope=faers_scope,
            requested_sources=(SourceType.FAERS,),
            faers_query_requests=(requests[1], requests[0]),
        )
    with pytest.raises(ValidationError, match="unique by drug and identity strategy"):
        M1BResearchRequestV1(
            request_id=envelope.request_id,
            scope=faers_scope,
            requested_sources=(SourceType.FAERS,),
            faers_query_requests=(requests[0], requests[0]),
        )


def test_m1b_faers_request_envelope_rejects_selection_and_scope_drift() -> None:
    selected_scope = make_scope(sources=(SourceType.FAERS,))
    selected_request = faers_request()
    with pytest.raises(ValidationError, match="exactly when FAERS is requested"):
        M1BResearchRequestV1(
            request_id="request:00000000-0000-4000-8000-000000000001",
            scope=selected_scope,
            requested_sources=(SourceType.FAERS,),
        )

    dailymed_scope = make_scope(sources=(SourceType.DAILYMED,))
    with pytest.raises(ValidationError, match="exactly when FAERS is requested"):
        M1BResearchRequestV1(
            request_id="request:00000000-0000-4000-8000-000000000001",
            scope=dailymed_scope,
            requested_sources=(SourceType.DAILYMED,),
            dailymed_selection_requests=(dailymed_request(),),
            faers_query_requests=(selected_request,),
        )

    with pytest.raises(ValidationError, match="must belong to the request scope"):
        M1BResearchRequestV1(
            request_id="request:00000000-0000-4000-8000-000000000001",
            scope=selected_scope,
            requested_sources=(SourceType.FAERS,),
            faers_query_requests=(faers_request(drug_concept_id="drug:foreign"),),
        )

    drifted = selected_request.model_copy(update={"pt_values": ("NAUSEA",)})
    with pytest.raises(ValidationError):
        M1BResearchRequestV1(
            request_id="request:00000000-0000-4000-8000-000000000001",
            scope=selected_scope,
            requested_sources=(SourceType.FAERS,),
            faers_query_requests=(drifted,),
        )
