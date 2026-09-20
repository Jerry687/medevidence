"""Pure DailyMed packaging enrichment planning and candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedDiscoverySummaryV2,
    DailyMedEnrichedCandidateV2,
    DailyMedEnrichmentReason,
    DailyMedEnrichmentStatus,
    DailyMedPackagingExecutionV2,
    DailyMedSelectionDecisionV2,
)
from medevidence.domain.identifiers import (
    CanonicalSetId,
    CanonicalSplVersion,
    DurableModel,
    derive_identity,
)
from medevidence.domain.sources import DailyMedMeaningfulDimension


class DailyMedPackagingRequestV2(DurableModel):
    summary_id: str
    discovery_query_id: str
    setid: CanonicalSetId
    expected_current_spl_version: CanonicalSplVersion
    pagesize: Literal[100] = 100


@dataclass(frozen=True, slots=True)
class DailyMedEnrichmentGroupPlan:
    discovery_query_id: str
    requests: tuple[DailyMedPackagingRequestV2, ...]
    reserved_selected_fetch: bool
    reason: DailyMedEnrichmentReason | None


class DailyMedPackagingExecutionPort(Protocol):
    def enrich(self, request: DailyMedPackagingRequestV2) -> DailyMedPackagingExecutionV2: ...


def plan_dailymed_enrichment_groups(
    groups: tuple[DailyMedDiscoveryGroupV2, ...],
    *,
    acquisition_limit: int = 8,
) -> tuple[DailyMedEnrichmentGroupPlan, ...]:
    """Admit only complete candidate groups with one reserved selected fetch each."""

    if type(groups) is not tuple or not 1 <= len(groups) <= 4 or acquisition_limit != 8:
        raise ValueError("DailyMed enrichment groups exceed the frozen plan")
    discovery_count = len(groups)
    remaining = acquisition_limit - discovery_count
    plans = []
    for group in groups:
        if type(group) is not DailyMedDiscoveryGroupV2:
            raise ValueError("DailyMed discovery group type is invalid")
        exact_group = DailyMedDiscoveryGroupV2.model_validate(
            BaseModel.model_dump(group, mode="python"), strict=True
        )
        if exact_group != group:
            raise ValueError("DailyMed discovery group reconstruction drift")
        group = exact_group
        query_id, summaries = group.discovery_query_id, group.summaries
        if not group.coverage_complete:
            plans.append(
                DailyMedEnrichmentGroupPlan(
                    query_id, (), False, DailyMedEnrichmentReason.DISCOVERY_PARTIAL
                )
            )
            continue
        if group.historical_pin:
            plans.append(
                DailyMedEnrichmentGroupPlan(
                    query_id,
                    (),
                    False,
                    DailyMedEnrichmentReason.HISTORICAL_PIN_UNAVAILABLE,
                )
            )
            continue
        if not summaries:
            plans.append(
                DailyMedEnrichmentGroupPlan(
                    query_id, (), False, DailyMedEnrichmentReason.NO_CANDIDATE
                )
            )
            continue
        needed = len(summaries) + 1
        if needed > remaining:
            plans.append(
                DailyMedEnrichmentGroupPlan(
                    query_id,
                    (),
                    False,
                    DailyMedEnrichmentReason.ENRICHMENT_BUDGET_EXCEEDED,
                )
            )
            continue
        requests = tuple(
            DailyMedPackagingRequestV2(
                summary_id=item.summary_id,
                discovery_query_id=query_id,
                setid=item.setid,
                expected_current_spl_version=item.current_spl_version,
            )
            for item in summaries
        )
        remaining -= needed
        plans.append(DailyMedEnrichmentGroupPlan(query_id, requests, True, None))
    return tuple(plans)


def build_enriched_candidate(
    summary: DailyMedDiscoverySummaryV2,
    execution: DailyMedPackagingExecutionV2,
) -> DailyMedEnrichedCandidateV2:
    """Bind packaging products to both exact raw acquisition parents."""

    if type(execution) is not DailyMedPackagingExecutionV2:
        raise ValueError("DailyMed packaging execution type is invalid")
    exact = DailyMedPackagingExecutionV2.model_validate(execution.model_dump(mode="python"))
    if exact != execution or not exact.products:
        raise ValueError("DailyMed packaging execution is incomplete")
    enrichment_parent = exact.parent
    if enrichment_parent.query_id != derive_identity(
        "dailymed-packaging-query-v2",
        {
            "summary_id": summary.summary_id,
            "setid": summary.setid,
            "spl_version": summary.current_spl_version,
        },
    ):
        raise ValueError("DailyMed packaging query differs from frozen summary")
    return DailyMedEnrichedCandidateV2.create(
        summary=summary,
        enrichment_parent=enrichment_parent,
        products=exact.products,
        observed_dimensions=tuple(
            sorted(
                {
                    DailyMedMeaningfulDimension.NDC,
                    DailyMedMeaningfulDimension.PRODUCT_NAME,
                    DailyMedMeaningfulDimension.INGREDIENT_SET,
                    DailyMedMeaningfulDimension.STRENGTH,
                },
                key=lambda item: item.value,
            )
        ),
    )


def select_enriched_candidates(
    groups: tuple[DailyMedDiscoveryGroupV2, ...],
    group_index: int,
    candidates: tuple[DailyMedEnrichedCandidateV2, ...],
) -> DailyMedSelectionDecisionV2:
    """Select one fully enriched candidate or require review without guessing metadata."""

    plans = plan_dailymed_enrichment_groups(groups)
    if type(group_index) is not int or not 0 <= group_index < len(groups):
        raise ValueError("DailyMed selection group index is invalid")
    group, plan = groups[group_index], plans[group_index]
    if type(candidates) is not tuple or any(
        type(item) is not DailyMedEnrichedCandidateV2 for item in candidates
    ):
        raise ValueError("DailyMed enriched candidate set has a foreign type")
    exact_candidates = tuple(
        DailyMedEnrichedCandidateV2.model_validate(
            BaseModel.model_dump(item, mode="python"), strict=True
        )
        for item in candidates
    )
    if exact_candidates != candidates:
        raise ValueError("DailyMed enriched candidate set reconstruction drift")
    candidates = exact_candidates
    query_id, summaries = group.discovery_query_id, group.summaries
    if plan.reason is DailyMedEnrichmentReason.NO_CANDIDATE:
        return DailyMedSelectionDecisionV2.create(
            discovery_query_id=query_id,
            summary_ids=(),
            candidate_ids=(),
            status=DailyMedEnrichmentStatus.NO_CANDIDATE,
            reason=DailyMedEnrichmentReason.NO_CANDIDATE,
        )
    if plan.reason is not None:
        return DailyMedSelectionDecisionV2.create(
            discovery_query_id=query_id,
            summary_ids=tuple(item.summary_id for item in summaries),
            candidate_ids=(),
            status=(
                DailyMedEnrichmentStatus.UNAVAILABLE
                if plan.reason is DailyMedEnrichmentReason.HISTORICAL_PIN_UNAVAILABLE
                else DailyMedEnrichmentStatus.REVIEW_REQUIRED
            ),
            reason=plan.reason,
        )
    if tuple(item.summary.summary_id for item in candidates) != tuple(
        item.summary_id for item in summaries
    ):
        raise ValueError("DailyMed enriched candidate set is incomplete")
    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(candidates) == 1:
        candidate = candidates[0]
        return DailyMedSelectionDecisionV2.create(
            discovery_query_id=query_id,
            summary_ids=tuple(item.summary_id for item in summaries),
            candidate_ids=candidate_ids,
            status=DailyMedEnrichmentStatus.SELECTED,
            selected_candidate_id=candidate.candidate_id,
            selected_setid=candidate.summary.setid,
            selected_spl_version=candidate.summary.current_spl_version,
        )
    all_dimensions = set(DailyMedMeaningfulDimension)
    if any(set(item.observed_dimensions) != all_dimensions for item in candidates):
        reason = DailyMedEnrichmentReason.MEANINGFUL_DIMENSION_UNOBSERVED
    else:
        reason = DailyMedEnrichmentReason.CLINICALLY_DISTINCT_CANDIDATES
    return DailyMedSelectionDecisionV2.create(
        discovery_query_id=query_id,
        summary_ids=tuple(item.summary_id for item in summaries),
        candidate_ids=candidate_ids,
        status=DailyMedEnrichmentStatus.REVIEW_REQUIRED,
        reason=reason,
    )


def unavailable_enrichment_decision(
    group: DailyMedDiscoveryGroupV2,
    *,
    reason: DailyMedEnrichmentReason,
) -> DailyMedSelectionDecisionV2:
    """Record a source-backed enrichment failure without selecting a candidate."""

    if type(group) is not DailyMedDiscoveryGroupV2 or reason not in {
        DailyMedEnrichmentReason.ENRICHMENT_UNAVAILABLE,
        DailyMedEnrichmentReason.ENRICHMENT_PAGINATION_UNSUPPORTED,
    }:
        raise ValueError("DailyMed enrichment failure reason is invalid")
    exact = DailyMedDiscoveryGroupV2.model_validate(group.model_dump(mode="python"), strict=True)
    if exact != group or not group.coverage_complete or not group.summaries:
        raise ValueError("DailyMed enrichment failure requires complete positive discovery")
    return DailyMedSelectionDecisionV2.create(
        discovery_query_id=group.discovery_query_id,
        summary_ids=tuple(item.summary_id for item in group.summaries),
        candidate_ids=(),
        status=DailyMedEnrichmentStatus.REVIEW_REQUIRED,
        reason=reason,
    )
