"""DailyMed V2 enrichment identities, budget, and conservative selection."""

from __future__ import annotations

import pytest

from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedDiscoverySummaryV2,
    DailyMedEnrichmentReason,
    DailyMedEnrichmentStatus,
    DailyMedPackagingExecutionV2,
    DailyMedPackagingProductV2,
    DailyMedRawParentV2,
)
from medevidence.domain.identifiers import derive_identity
from medevidence.tools.dailymed_enrichment import (
    build_enriched_candidate,
    plan_dailymed_enrichment_groups,
    select_enriched_candidates,
)

SETID = "11111111-1111-4111-8111-111111111111"
HASH = "sha256:" + "a" * 64


def outcome(query: str, count: int, *, complete: bool = True) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.DAILYMED,
        query_id=query,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE if complete else CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES
        if count
        else (ResultStatus.NO_MATCH if complete else ResultStatus.INDETERMINATE),
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=count,
        pages_completed=1,
        truncated=not complete,
        warning_codes=() if complete else ("discovery_truncated",),
    )


def parent(kind: str, ordinal: int, query: str) -> DailyMedRawParentV2:
    return DailyMedRawParentV2(
        kind=kind,
        run_id="run:11111111-1111-4111-8111-111111111111",
        attempt_id="attempt:test",
        acquisition_id=f"acquisition:{ordinal}",
        acquisition_ordinal=ordinal,
        acquisition_intent_id=f"intent:{ordinal}",
        query_id=query,
        snapshot_id=f"snapshot:{ordinal}",
        manifest_id="sha256:" + f"{ordinal + 1:064x}",
        member_ordinal=0,
        link_id=f"link:{ordinal}",
        raw_artifact_id=HASH,
        raw_content_hash=HASH,
        byte_size=10,
    )


def summary(index: int, query: str = "query:discovery") -> DailyMedDiscoverySummaryV2:
    return DailyMedDiscoverySummaryV2.create(
        setid=SETID[:-12] + f"{index + 1:012d}",
        current_spl_version="1",
        title=f"Exact title {index}",
        candidate_ordinal=index,
        parent=parent("discovery_json", 0, query),
    )


def candidate(value: DailyMedDiscoverySummaryV2, ordinal: int = 1):
    query = derive_identity(
        "dailymed-packaging-query-v2",
        {
            "summary_id": value.summary_id,
            "setid": value.setid,
            "spl_version": value.current_spl_version,
        },
    )
    product = DailyMedPackagingProductV2(
        product_code="0001",
        product_name="Exact product",
        generic_name="Exact generic",
        ingredients=("Ingredient",),
        strengths=("1 mg",),
        ndcs=("0001-0001",),
    )
    return build_enriched_candidate(
        value,
        DailyMedPackagingExecutionV2(
            parent=parent("packaging_json", ordinal, query), products=(product,)
        ),
    )


def test_candidate_binds_distinct_discovery_and_packaging_parents() -> None:
    source = summary(0)
    enriched = candidate(source)
    assert enriched.summary.parent.kind == "discovery_json"
    assert enriched.enrichment_parent.kind == "packaging_json"
    assert enriched.summary.parent.acquisition_id != enriched.enrichment_parent.acquisition_id
    group = DailyMedDiscoveryGroupV2(
        discovery_query_id="query:discovery",
        summaries=(source,),
        outcome=outcome("query:discovery", 1),
    )
    decision = select_enriched_candidates((group,), 0, (enriched,))
    assert decision.status is DailyMedEnrichmentStatus.SELECTED
    assert decision.selected_candidate_id == enriched.candidate_id


def test_multiple_candidates_with_unobserved_dimensions_require_review() -> None:
    summaries = (summary(0), summary(1))
    candidates = tuple(candidate(item, index + 1) for index, item in enumerate(summaries))
    group = DailyMedDiscoveryGroupV2(
        discovery_query_id="query:discovery",
        summaries=summaries,
        outcome=outcome("query:discovery", 2),
    )
    decision = select_enriched_candidates((group,), 0, candidates)
    assert decision.status is DailyMedEnrichmentStatus.REVIEW_REQUIRED
    assert decision.reason is DailyMedEnrichmentReason.MEANINGFUL_DIMENSION_UNOBSERVED
    assert decision.selected_candidate_id is None


def test_whole_group_budget_never_partially_enriches() -> None:
    first = (summary(0, "query:first"), summary(1, "query:first"))
    second = tuple(summary(index, "query:second") for index in range(3))
    plans = plan_dailymed_enrichment_groups(
        (
            DailyMedDiscoveryGroupV2(
                discovery_query_id="query:first", summaries=first, outcome=outcome("query:first", 2)
            ),
            DailyMedDiscoveryGroupV2(
                discovery_query_id="query:second",
                summaries=second,
                outcome=outcome("query:second", 3),
            ),
        )
    )
    assert len(plans[0].requests) == 2 and plans[0].reserved_selected_fetch
    assert plans[1].requests == ()
    assert plans[1].reason is DailyMedEnrichmentReason.ENRICHMENT_BUDGET_EXCEEDED
    historical = plan_dailymed_enrichment_groups(
        (
            DailyMedDiscoveryGroupV2(
                discovery_query_id="query:first",
                summaries=first,
                outcome=outcome("query:first", 2),
                historical_pin=True,
            ),
        )
    )[0]
    assert historical.reason is DailyMedEnrichmentReason.HISTORICAL_PIN_UNAVAILABLE
    partial = plan_dailymed_enrichment_groups(
        (
            DailyMedDiscoveryGroupV2(
                discovery_query_id="query:first",
                summaries=first,
                outcome=outcome("query:first", 2, complete=False),
            ),
        )
    )[0]
    assert partial.requests == () and partial.reason is DailyMedEnrichmentReason.DISCOVERY_PARTIAL
    empty = DailyMedDiscoveryGroupV2(
        discovery_query_id="query:empty", summaries=(), outcome=outcome("query:empty", 0)
    )
    assert (
        plan_dailymed_enrichment_groups((empty,))[0].reason is DailyMedEnrichmentReason.NO_CANDIDATE
    )
    assert (
        select_enriched_candidates((empty,), 0, ()).status is DailyMedEnrichmentStatus.NO_CANDIDATE
    )
    partial_zero = DailyMedDiscoveryGroupV2(
        discovery_query_id="query:partial-zero",
        summaries=(),
        outcome=outcome("query:partial-zero", 0, complete=False),
    )
    zero_decision = select_enriched_candidates((partial_zero,), 0, ())
    assert zero_decision.status is DailyMedEnrichmentStatus.REVIEW_REQUIRED
    assert zero_decision.reason is DailyMedEnrichmentReason.DISCOVERY_PARTIAL
    assert (
        select_enriched_candidates(
            (
                DailyMedDiscoveryGroupV2(
                    discovery_query_id="query:first",
                    summaries=first,
                    outcome=outcome("query:first", 2, complete=False),
                ),
            ),
            0,
            tuple(candidate(item, index + 1) for index, item in enumerate(first)),
        ).status
        is DailyMedEnrichmentStatus.REVIEW_REQUIRED
    )


def test_partial_packaging_and_shared_acquisition_fail_closed() -> None:
    source = summary(0)
    enriched = candidate(source)
    query = enriched.enrichment_parent.query_id
    product = enriched.products[0]
    with pytest.raises(ValueError):
        DailyMedPackagingExecutionV2.model_validate(
            {
                "parent": parent("packaging_json", 1, query),
                "products": (product,),
                "pages_completed": 1,
                "truncated": True,
                "next_page": 2,
            }
        )
    with pytest.raises(ValueError, match="parent does not follow discovery"):
        build_enriched_candidate(
            source,
            DailyMedPackagingExecutionV2(
                parent=parent("packaging_json", 1, query).model_copy(
                    update={"acquisition_id": source.parent.acquisition_id}
                ),
                products=(product,),
            ),
        )
