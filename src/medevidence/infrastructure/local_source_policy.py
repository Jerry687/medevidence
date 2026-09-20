"""Fixed local source-query policy; search literals are not identity evidence."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from medevidence.connectors.dailymed.policy import (
    DailyMedOperation,
    DailyMedRequest,
    build_dailymed_request,
)
from medevidence.domain import (
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    M1BResearchRequestV1,
    ResearchScope,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.domain.scope import GI_PT_SET_M1B_V1
from medevidence.orchestration.contracts import (
    SafetyDecision,
    SafetyOutcome,
    SafetyReason,
    ScopeSafetyEvaluation,
)
from medevidence.tools.contracts import DailyMedDiscoveryRequest
from medevidence.tools.runtime_source_bounds import RUNTIME_SOURCE_BOUNDS_V3

from .research_scope_safety import LocalResearchScopeSafety, load_local_research_input_catalog

LOCAL_SOURCE_POLICY_VERSION = "m3.local-source-query-policy.v1"
_NATIVE_TERMS = (
    ("semaglutide", "semaglutide", "SEMAGLUTIDE"),
    ("tirzepatide", "tirzepatide", "TIRZEPATIDE"),
)
_EXECUTION_CEILINGS: tuple[tuple[str, int, int, int, int, int], ...] = tuple(
    (source.value, *bounds) for source, bounds in RUNTIME_SOURCE_BOUNDS_V3
)
_BUILT_POLICY_HASH = sha256_digest(
    canonical_json(
        {
            "version": LOCAL_SOURCE_POLICY_VERSION,
            "native_terms": _NATIVE_TERMS,
            "dailymed_sections": ("34084-4",),
            "dailymed_selection": "strict_identity",
            "dailymed_explicit_date_range": "unsupported",
            "faers_strategy": "harmonized_substance",
            "faers_pt_values": GI_PT_SET_M1B_V1,
            "faers_default_date_difference": 365,
            "execution_ceilings": _EXECUTION_CEILINGS,
        }
    )
)
LOCAL_SOURCE_POLICY_HASH = "sha256:33581c3efc9758923cd02b8020f31fdff790afde50f420a1f9f443d515811e13"
if _BUILT_POLICY_HASH != LOCAL_SOURCE_POLICY_HASH:
    raise RuntimeError("local source-query policy identity drift")


def _faers_scope_supported(scope: ResearchScope) -> bool:
    return SourceType.FAERS not in scope.selected_sources or (
        {item.preferred_term.lower() for item in scope.adverse_reactions}
        == {"diarrhoea", "nausea", "vomiting"}
        and (
            scope.date_range is None
            or (scope.date_range.end_date - scope.date_range.start_date).days <= 365
        )
    )


def _source_budgets_supported(scope: ResearchScope) -> bool:
    requested = (
        scope.query_bounds.max_query_characters,
        scope.query_bounds.max_pages,
        scope.result_bounds.max_records,
        scope.result_bounds.max_payload_bytes,
        scope.query_bounds.max_total_seconds,
    )
    return all(
        all(effective <= ceiling for effective, ceiling in zip(profile[1:], requested, strict=True))
        for profile in _EXECUTION_CEILINGS
        if SourceType(profile[0]) in scope.selected_sources
    )


class SourceAwareLocalScopeSafety:
    """Apply the literal public catalog and existing finite FAERS source contract."""

    def __init__(self, *, today: Callable[[], date] = date.today) -> None:
        self._base = LocalResearchScopeSafety(
            catalog=load_local_research_input_catalog(), today=today
        )

    def evaluate(self, scope: ResearchScope) -> ScopeSafetyEvaluation:
        checked = self._base.evaluate(scope)
        if checked.decision.outcome is not SafetyOutcome.PERMITTED:
            return checked
        permitted = (
            _faers_scope_supported(scope)
            and _source_budgets_supported(scope)
            and (SourceType.DAILYMED not in scope.selected_sources or scope.date_range is None)
        )
        return ScopeSafetyEvaluation(
            interpreted_scope=checked.interpreted_scope,
            decision=SafetyDecision(
                outcome=SafetyOutcome.PERMITTED if permitted else SafetyOutcome.BLOCKED,
                reason=SafetyReason.PERMITTED_RESEARCH_SCOPE
                if permitted
                else SafetyReason.UNSAFE_SCOPE,
                policy_version=LOCAL_SOURCE_POLICY_VERSION,
            ),
        )


@dataclass(frozen=True, slots=True)
class LocalSourceQueryPolicy:
    scope: ResearchScope
    run_created_at_utc: datetime

    def __post_init__(self) -> None:
        instant = self.run_created_at_utc
        if (
            type(instant) is not datetime
            or instant.tzinfo is None
            or instant.utcoffset() != timedelta(0)
        ):
            raise ValueError("source policy requires the persisted UTC run creation time")
        checked = SourceAwareLocalScopeSafety(today=lambda: instant.date()).evaluate(self.scope)
        if checked.decision.outcome is not SafetyOutcome.PERMITTED:
            raise ValueError("scope is outside the configured local source capabilities")

    @property
    def configuration_hash(self) -> str:
        return LOCAL_SOURCE_POLICY_HASH

    def build_request(self, request_id: str) -> M1BResearchRequestV1:
        daily = (
            tuple(
                DailyMedSelectionRequestV1(
                    drug_concept_id=drug.concept_id,
                    requested_section_codes=("34084-4",),
                    selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
                )
                for drug in self.scope.drugs
            )
            if SourceType.DAILYMED in self.scope.selected_sources
            else ()
        )
        faers: tuple[FaersAggregateRequestV1, ...] = ()
        if SourceType.FAERS in self.scope.selected_sources:
            interval = self.scope.date_range
            end = self.run_created_at_utc.date() if interval is None else interval.end_date
            start = end - timedelta(days=365) if interval is None else interval.start_date
            names = {name: faers_name for name, _daily_name, faers_name in _NATIVE_TERMS}
            faers = tuple(
                FaersAggregateRequestV1(
                    drug_concept_id=drug.concept_id,
                    identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
                    identity_exact_value=names[drug.preferred_term.lower()],
                    pt_values=GI_PT_SET_M1B_V1,
                    statistical_unit="provider_count_occurrence",
                    inclusive_date_range=FaersInclusiveDateRangeV1(start_date=start, end_date=end),
                    execution_bounds=FaersExecutionBoundsV1(
                        max_date_difference_days=365, max_inclusive_calendar_dates=366
                    ),
                )
                for drug in self.scope.drugs
            )
        return M1BResearchRequestV1(
            request_id=request_id,
            scope=self.scope,
            requested_sources=self.scope.selected_sources,
            dailymed_selection_requests=daily,
            faers_query_requests=faers,
        )

    def resolve(self, request: DailyMedDiscoveryRequest) -> DailyMedRequest:
        if SourceType.DAILYMED not in self.scope.selected_sources:
            raise ValueError("DailyMed was not requested")
        request = DailyMedDiscoveryRequest.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        selection = request.selection_request
        if selection.selection_mode is not DailyMedSelectionMode.STRICT_IDENTITY:
            raise ValueError("local policy has no unreviewed pinned-label selection")
        names = {name: daily_name for name, daily_name, _faers_name in _NATIVE_TERMS}
        drug = next(
            (item for item in self.scope.drugs if item.concept_id == selection.drug_concept_id),
            None,
        )
        if drug is None:
            raise ValueError("DailyMed request belongs to another scope")
        return build_dailymed_request(
            DailyMedOperation.DISCOVERY,
            query={"drug_name": names[drug.preferred_term.lower()], "pagesize": 100},
        )
