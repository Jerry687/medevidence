"""Literal source filters and finite FAERS scope are selected before execution."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.infrastructure.test_research_scope_safety import _scope

from medevidence.domain import (
    InclusiveDateRange,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
    derive_identity,
)
from medevidence.infrastructure.local_source_policy import (
    LocalSourceQueryPolicy,
    SourceAwareLocalScopeSafety,
)
from medevidence.infrastructure.research_scope_safety import load_local_research_input_catalog
from medevidence.orchestration.contracts import SafetyOutcome
from medevidence.tools.contracts import DailyMedDiscoveryRequest

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
REQUEST = "request:00000000-0000-4000-8000-000000000001"


def complete_scope(
    interval: InclusiveDateRange | None = None,
    *,
    sources: tuple[SourceType, ...] = (SourceType.DAILYMED, SourceType.FAERS, SourceType.PUBMED),
) -> ResearchScope:
    catalog = load_local_research_input_catalog()
    template = _scope()
    return ResearchScope.create(
        drugs=tuple(catalog.drugs_by_term.values()),
        adverse_reactions=tuple(catalog.reactions_by_term.values()),
        date_range=interval,
        selected_sources=sources,
        comparison_intent=template.comparison_intent,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def test_reference_plan_uses_exact_literal_stratum_and_persisted_anchor_window() -> None:
    scope = complete_scope()
    policy = LocalSourceQueryPolicy(scope, NOW)
    request = policy.build_request(REQUEST)
    assert request.scope == scope
    assert len(request.faers_query_requests) == len(request.dailymed_selection_requests) == 2
    assert {item.identity_exact_value for item in request.faers_query_requests} == {
        "SEMAGLUTIDE",
        "TIRZEPATIDE",
    }
    for item in request.faers_query_requests:
        assert item.identity_strategy.value == "harmonized_substance"
        assert item.pt_values == ("DIARRHOEA", "NAUSEA", "VOMITING")
        assert item.inclusive_date_range.end_date == NOW.date()
        assert item.inclusive_date_range.start_date == NOW.date() - timedelta(days=365)
    assert policy.build_request(REQUEST) == request
    for selection in request.dailymed_selection_requests:
        discovery = DailyMedDiscoveryRequest(
            selection_request=selection,
            query_id=derive_identity("dailymed-discovery-query", {"request": selection}),
        )
        native = policy.resolve(discovery)
        assert dict(native.query)["drug_name"] in {"semaglutide", "tirzepatide"}
        assert dict(native.query)["pagesize"] == "100"
        assert native.url.startswith("https://dailymed.nlm.nih.gov/")


def test_explicit_supported_dates_are_not_silently_narrowed() -> None:
    interval = InclusiveDateRange(
        start_date=NOW.date() - timedelta(days=90), end_date=NOW.date() - timedelta(days=1)
    )
    request = LocalSourceQueryPolicy(
        complete_scope(interval, sources=(SourceType.FAERS, SourceType.PUBMED)), NOW
    ).build_request(REQUEST)
    for item in request.faers_query_requests:
        assert item.inclusive_date_range.start_date == interval.start_date
        assert item.inclusive_date_range.end_date == interval.end_date


def test_broad_faers_dates_and_partial_pt_scope_fail_before_source_activity() -> None:
    policy = SourceAwareLocalScopeSafety(today=lambda: NOW.date())
    broad = complete_scope(
        InclusiveDateRange(start_date=NOW.date() - timedelta(days=366), end_date=NOW.date()),
        sources=(SourceType.FAERS,),
    )
    partial_template = _scope(sources=(SourceType.FAERS,))
    partial = ResearchScope.create(
        drugs=partial_template.drugs,
        adverse_reactions=partial_template.adverse_reactions,
        date_range=None,
        selected_sources=partial_template.selected_sources,
        comparison_intent=partial_template.comparison_intent,
        query_bounds=complete_scope().query_bounds,
        result_bounds=complete_scope().result_bounds,
    )
    for scope in (broad, partial):
        assert policy.evaluate(scope).decision.outcome is SafetyOutcome.BLOCKED
        with pytest.raises(ValueError):
            LocalSourceQueryPolicy(scope, NOW)
    assert (
        policy.evaluate(complete_scope(sources=(SourceType.PUBMED,))).decision.outcome
        is SafetyOutcome.PERMITTED
    )


def test_no_naive_clock_or_cross_scope_discovery() -> None:
    with pytest.raises(ValueError):
        LocalSourceQueryPolicy(complete_scope(), NOW.replace(tzinfo=None))
    pubmed_only = LocalSourceQueryPolicy(complete_scope(sources=(SourceType.PUBMED,)), NOW)
    selection = (
        LocalSourceQueryPolicy(complete_scope(), NOW)
        .build_request(REQUEST)
        .dailymed_selection_requests[0]
    )
    with pytest.raises(ValueError):
        pubmed_only.resolve(
            DailyMedDiscoveryRequest(
                selection_request=selection,
                query_id=derive_identity("dailymed-discovery-query", {"request": selection}),
            )
        )


@pytest.mark.parametrize(
    "sources", ((SourceType.DAILYMED,), (SourceType.DAILYMED, SourceType.FAERS))
)
def test_dailymed_cannot_silently_ignore_an_explicit_date_interval(sources) -> None:
    interval = InclusiveDateRange(
        start_date=NOW.date() - timedelta(days=90), end_date=NOW.date() - timedelta(days=1)
    )
    scope = complete_scope(interval, sources=sources)
    policy = SourceAwareLocalScopeSafety(today=lambda: NOW.date())
    assert policy.evaluate(scope).decision.outcome is SafetyOutcome.BLOCKED
    with pytest.raises(ValueError, match="outside the configured local source capabilities"):
        LocalSourceQueryPolicy(scope, NOW)
    assert (
        policy.evaluate(complete_scope(sources=sources)).decision.outcome is SafetyOutcome.PERMITTED
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("max_query_characters", 511),
        ("max_pages", 4),
        ("max_total_seconds", 29),
        ("max_records", 99),
        ("max_payload_bytes", 100_000),
    ),
)
def test_source_limits_never_override_a_smaller_requested_budget(field: str, value: int) -> None:
    original = complete_scope()
    query = original.query_bounds.model_dump()
    result = original.result_bounds.model_dump()
    (query if field in query else result)[field] = value
    narrowed = ResearchScope.create(
        drugs=original.drugs,
        adverse_reactions=original.adverse_reactions,
        date_range=original.date_range,
        selected_sources=original.selected_sources,
        comparison_intent=original.comparison_intent,
        query_bounds=QueryBounds(**query),
        result_bounds=ResultBounds(**result),
    )
    policy = SourceAwareLocalScopeSafety(today=lambda: NOW.date())
    assert policy.evaluate(narrowed).decision.outcome is SafetyOutcome.BLOCKED
    with pytest.raises(ValueError):
        LocalSourceQueryPolicy(narrowed, NOW)
