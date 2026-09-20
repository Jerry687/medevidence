"""Additive source-bound DailyMed candidate enrichment contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from .identifiers import (
    CanonicalSetId,
    CanonicalSplVersion,
    DurableModel,
    Sha256Digest,
    derive_identity,
)
from .scope import SourceType
from .sources import (
    CoverageStatus,
    DailyMedMarketingState,
    DailyMedMeaningfulDimension,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
)

type StableId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
type SplVersion = CanonicalSplVersion
type Text = Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class DailyMedEnrichmentReason(StrEnum):
    NO_CANDIDATE = "no_candidate"
    ENRICHMENT_BUDGET_EXCEEDED = "enrichment_budget_exceeded"
    DISCOVERY_PARTIAL = "discovery_partial"
    HISTORICAL_PIN_UNAVAILABLE = "historical_pin_enrichment_unavailable"
    MEANINGFUL_DIMENSION_UNOBSERVED = "meaningful_dimension_unobserved"
    CLINICALLY_DISTINCT_CANDIDATES = "clinically_distinct_candidates"
    ENRICHMENT_UNAVAILABLE = "enrichment_unavailable"
    ENRICHMENT_PAGINATION_UNSUPPORTED = "enrichment_pagination_unsupported"


class DailyMedEnrichmentStatus(StrEnum):
    NO_CANDIDATE = "no_candidate"
    SELECTED = "selected"
    REVIEW_REQUIRED = "review_required"
    UNAVAILABLE = "unavailable"


class DailyMedRawParentV2(DurableModel):
    """One exact raw member inside a source acquisition manifest."""

    schema_version: Literal["m3.dailymed-raw-parent.v2"] = "m3.dailymed-raw-parent.v2"
    kind: Literal["discovery_json", "packaging_json"]
    run_id: StableId
    attempt_id: StableId
    acquisition_id: StableId
    acquisition_ordinal: Annotated[int, Field(ge=0, le=7)]
    acquisition_intent_id: StableId
    query_id: StableId
    snapshot_id: StableId
    manifest_id: Sha256Digest
    member_ordinal: Annotated[int, Field(ge=0, le=99)]
    link_id: StableId
    raw_artifact_id: Sha256Digest
    raw_content_hash: Sha256Digest
    byte_size: Annotated[int, Field(ge=1, le=5_242_880)]
    body_complete: Literal[True] = True
    termination_reason: Literal["complete_response"] = "complete_response"

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.raw_artifact_id != self.raw_content_hash:
            raise ValueError("DailyMed raw parent artifact/hash drift")
        return self


class DailyMedDiscoveryRecordV2(DurableModel):
    setid: CanonicalSetId
    current_spl_version: SplVersion
    title: Text
    published_date: date | None = None


class DailyMedDiscoverySummaryV2(DurableModel):
    schema_version: Literal["m3.dailymed-discovery-summary.v2"] = "m3.dailymed-discovery-summary.v2"
    summary_id: StableId
    setid: CanonicalSetId
    current_spl_version: SplVersion
    title: Text
    published_date: date | None = None
    candidate_ordinal: Annotated[int, Field(ge=0, le=99)]
    parent: DailyMedRawParentV2

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {
            "schema_version": "m3.dailymed-discovery-summary.v2",
            "published_date": None,
            **values,
        }
        payload["summary_id"] = derive_identity("dailymed-discovery-summary-v2", payload)
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def exact_identity(self) -> Self:
        if self.parent.kind != "discovery_json":
            raise ValueError("DailyMed summary requires discovery JSON")
        payload = self.model_dump(mode="python", exclude={"summary_id"})
        if self.summary_id != derive_identity("dailymed-discovery-summary-v2", payload):
            raise ValueError("DailyMed discovery summary identity drift")
        return self


class DailyMedDiscoveryGroupV2(DurableModel):
    discovery_query_id: StableId
    summaries: tuple[DailyMedDiscoverySummaryV2, ...] = Field(max_length=100)
    outcome: SourceOutcome
    historical_pin: bool = False

    @model_validator(mode="after")
    def exact_group(self) -> Self:
        if type(self.historical_pin) is not bool or any(
            item.parent.query_id != self.discovery_query_id for item in self.summaries
        ):
            raise ValueError("DailyMed discovery group binding drift")
        if (
            self.outcome.source is not SourceType.DAILYMED
            or self.outcome.query_id != self.discovery_query_id
            or self.outcome.valid_result_count != len(self.summaries)
        ):
            raise ValueError("DailyMed discovery group outcome drift")
        if tuple(item.candidate_ordinal for item in self.summaries) != tuple(
            range(len(self.summaries))
        ):
            raise ValueError("DailyMed discovery summaries must use canonical ordinals")
        return self

    @property
    def coverage_complete(self) -> bool:
        return (
            self.outcome.execution_status is ExecutionStatus.SUCCEEDED
            and self.outcome.coverage_status is CoverageStatus.COMPLETE
            and not self.outcome.truncated
            and self.outcome.result_status in {ResultStatus.MATCHES, ResultStatus.NO_MATCH}
        )


class DailyMedPackagingProductV2(DurableModel):
    product_code: Text | None = None
    product_name: Text
    generic_name: Text | None = None
    ingredients: tuple[Text, ...] = Field(min_length=1, max_length=100)
    strengths: tuple[Text, ...] = Field(max_length=100)
    ndcs: tuple[Text, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def canonical_sets(self) -> Self:
        for name in ("ingredients", "strengths", "ndcs"):
            values = getattr(self, name)
            if values != tuple(sorted(set(values), key=lambda item: item.encode())):
                raise ValueError(f"DailyMed product {name} must be sorted and unique")
        return self


class DailyMedPackagingExecutionV2(DurableModel):
    """One fully captured single-page packaging response.

    Multi-page packaging remains unavailable for automatic selection.
    """

    parent: DailyMedRawParentV2
    products: tuple[DailyMedPackagingProductV2, ...] = Field(min_length=1, max_length=100)
    pages_completed: Literal[1] = 1
    truncated: Literal[False] = False
    next_page: Literal[None] = None

    @model_validator(mode="after")
    def exact_parent(self) -> Self:
        if self.parent.kind != "packaging_json":
            raise ValueError("DailyMed packaging execution requires packaging raw parent")
        return self


class DailyMedEnrichedCandidateV2(DurableModel):
    schema_version: Literal["m3.dailymed-enriched-candidate.v2"] = (
        "m3.dailymed-enriched-candidate.v2"
    )
    candidate_id: StableId
    source: Literal[SourceType.DAILYMED] = SourceType.DAILYMED
    summary: DailyMedDiscoverySummaryV2
    enrichment_parent: DailyMedRawParentV2
    products: tuple[DailyMedPackagingProductV2, ...] = Field(min_length=1, max_length=100)
    observed_dimensions: tuple[DailyMedMeaningfulDimension, ...]
    marketing_state: DailyMedMarketingState = DailyMedMarketingState.UNKNOWN

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {
            "schema_version": "m3.dailymed-enriched-candidate.v2",
            "source": SourceType.DAILYMED,
            "marketing_state": DailyMedMarketingState.UNKNOWN,
            **values,
        }
        payload["candidate_id"] = derive_identity("dailymed-enriched-candidate-v2", payload)
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def exact_binding(self) -> Self:
        if self.enrichment_parent.kind != "packaging_json":
            raise ValueError("DailyMed enrichment requires packaging JSON")
        if (
            self.enrichment_parent.run_id != self.summary.parent.run_id
            or self.enrichment_parent.attempt_id != self.summary.parent.attempt_id
            or self.enrichment_parent.acquisition_ordinal <= self.summary.parent.acquisition_ordinal
            or self.enrichment_parent.acquisition_id == self.summary.parent.acquisition_id
            or self.enrichment_parent.acquisition_intent_id
            == self.summary.parent.acquisition_intent_id
            or self.enrichment_parent.snapshot_id == self.summary.parent.snapshot_id
            or self.enrichment_parent.manifest_id == self.summary.parent.manifest_id
        ):
            raise ValueError("DailyMed enrichment parent does not follow discovery")
        expected_dimensions = tuple(
            sorted(
                {
                    DailyMedMeaningfulDimension.NDC,
                    DailyMedMeaningfulDimension.PRODUCT_NAME,
                    DailyMedMeaningfulDimension.INGREDIENT_SET,
                    DailyMedMeaningfulDimension.STRENGTH,
                },
                key=lambda item: item.value,
            )
        )
        if self.observed_dimensions != expected_dimensions:
            raise ValueError("DailyMed packaging observed dimensions drift")
        payload = self.model_dump(mode="python", exclude={"candidate_id"})
        if self.candidate_id != derive_identity("dailymed-enriched-candidate-v2", payload):
            raise ValueError("DailyMed enriched candidate identity drift")
        return self


class DailyMedSelectionDecisionV2(DurableModel):
    schema_version: Literal["m3.dailymed-selection-decision.v2"] = (
        "m3.dailymed-selection-decision.v2"
    )
    decision_id: StableId
    discovery_query_id: StableId
    summary_ids: tuple[StableId, ...] = Field(max_length=100)
    candidate_ids: tuple[StableId, ...] = Field(max_length=100)
    status: DailyMedEnrichmentStatus
    reason: DailyMedEnrichmentReason | None = None
    selected_candidate_id: StableId | None = None
    selected_setid: CanonicalSetId | None = None
    selected_spl_version: SplVersion | None = None

    @classmethod
    def create(cls, **values: object) -> Self:
        payload = {
            "schema_version": "m3.dailymed-selection-decision.v2",
            "reason": None,
            "selected_candidate_id": None,
            "selected_setid": None,
            "selected_spl_version": None,
            **values,
        }
        payload["decision_id"] = derive_identity("dailymed-selection-decision-v2", payload)
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def exact_decision(self) -> Self:
        selected = self.status is DailyMedEnrichmentStatus.SELECTED
        selected_fields = (
            self.selected_candidate_id,
            self.selected_setid,
            self.selected_spl_version,
        )
        if selected != all(item is not None for item in selected_fields):
            raise ValueError("DailyMed V2 selected fields drift")
        if selected and (
            self.reason is not None or self.selected_candidate_id not in self.candidate_ids
        ):
            raise ValueError("DailyMed V2 selection binding drift")
        if not selected and (
            self.reason is None or any(item is not None for item in selected_fields)
        ):
            raise ValueError("DailyMed V2 review/unavailable requires one reason")
        payload = self.model_dump(mode="python", exclude={"decision_id"})
        if self.decision_id != derive_identity("dailymed-selection-decision-v2", payload):
            raise ValueError("DailyMed V2 decision identity drift")
        return self
