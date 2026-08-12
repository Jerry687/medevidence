"""Source-neutral research-scope contracts and approved execution bounds."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from .identifiers import (
    AdverseEventConceptId,
    CanonicalSetId,
    CanonicalSplVersion,
    DrugConceptId,
    DurableModel,
    NonBlankText,
    RequestId,
    SchemaVersion,
    ScopeId,
    derive_identity,
)

MAX_DRUGS = 4
MAX_ADVERSE_REACTIONS = 8
MAX_QUERY_CHARACTERS = 512
MAX_PAGES = 5
MAX_RECORDS = 100
MAX_PAYLOAD_BYTES = 5_242_880
MAX_TOTAL_EXECUTION_SECONDS = 60


class SourceType(StrEnum):
    """Approved source classifications represented by source-neutral contracts."""

    PUBMED = "pubmed"
    DAILYMED = "dailymed"
    FAERS = "faers"
    CADEC = "cadec"


class ComparisonIntent(StrEnum):
    """Owner-approved M1A comparison intents."""

    COMPARE = "compare"
    SUMMARIZE = "summarize"


class DrugConcept(DurableModel):
    """Typed drug identity without patient or provider-specific content."""

    concept_id: DrugConceptId
    preferred_term: NonBlankText


class AdverseEventConcept(DurableModel):
    """Typed adverse-reaction identity."""

    concept_id: AdverseEventConceptId
    preferred_term: NonBlankText


class InclusiveDateRange(DurableModel):
    """Inclusive day-precision research date range."""

    start_date: date
    end_date: date
    precision: Literal["day"] = "day"

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class QueryBounds(DurableModel):
    """Approved ordinary M1A query and time bounds."""

    max_query_characters: int = Field(ge=1, le=MAX_QUERY_CHARACTERS)
    max_pages: int = Field(ge=1, le=MAX_PAGES)
    max_total_seconds: int = Field(ge=1, le=MAX_TOTAL_EXECUTION_SECONDS)


class ResultBounds(DurableModel):
    """Approved ordinary M1A result and payload bounds."""

    max_records: int = Field(ge=1, le=MAX_RECORDS)
    max_payload_bytes: int = Field(ge=1, le=MAX_PAYLOAD_BYTES)


class ExecutionBounds(DurableModel):
    """Flattened immutable bounds carried by an executed source outcome."""

    max_query_characters: int = Field(ge=1, le=MAX_QUERY_CHARACTERS)
    max_pages: int = Field(ge=1, le=MAX_PAGES)
    max_records: int = Field(ge=1, le=MAX_RECORDS)
    max_payload_bytes: int = Field(ge=1, le=MAX_PAYLOAD_BYTES)
    max_total_seconds: int = Field(ge=1, le=MAX_TOTAL_EXECUTION_SECONDS)

    @classmethod
    def from_scope(cls, scope: ResearchScope) -> Self:
        """Copy the configured scope bounds into an execution contract."""

        return cls(
            max_query_characters=scope.query_bounds.max_query_characters,
            max_pages=scope.query_bounds.max_pages,
            max_records=scope.result_bounds.max_records,
            max_payload_bytes=scope.result_bounds.max_payload_bytes,
            max_total_seconds=scope.query_bounds.max_total_seconds,
        )


class ResearchScope(DurableModel):
    """Strict, versioned, source-neutral research scope."""

    schema_version: SchemaVersion = "1.0"
    scope_id: ScopeId
    drugs: tuple[DrugConcept, ...] = Field(min_length=1, max_length=MAX_DRUGS)
    adverse_reactions: tuple[AdverseEventConcept, ...] = Field(
        min_length=1,
        max_length=MAX_ADVERSE_REACTIONS,
    )
    date_range: InclusiveDateRange | None = None
    selected_sources: tuple[SourceType, ...] = Field(min_length=1)
    language: Literal["en"] = "en"
    comparison_intent: ComparisonIntent
    query_bounds: QueryBounds
    result_bounds: ResultBounds

    @classmethod
    def create(
        cls,
        *,
        drugs: tuple[DrugConcept, ...],
        adverse_reactions: tuple[AdverseEventConcept, ...],
        date_range: InclusiveDateRange | None,
        selected_sources: tuple[SourceType, ...],
        comparison_intent: ComparisonIntent,
        query_bounds: QueryBounds,
        result_bounds: ResultBounds,
    ) -> Self:
        """Construct a scope with its deterministic canonical identity."""

        canonical_drugs = tuple(sorted(drugs, key=lambda item: item.concept_id))
        canonical_reactions = tuple(sorted(adverse_reactions, key=lambda item: item.concept_id))
        canonical_sources = tuple(sorted(selected_sources, key=lambda item: item.value))
        payload = {
            "schema_version": "1.0",
            "drugs": canonical_drugs,
            "adverse_reactions": canonical_reactions,
            "date_range": date_range,
            "selected_sources": canonical_sources,
            "language": "en",
            "comparison_intent": comparison_intent,
            "query_bounds": query_bounds,
            "result_bounds": result_bounds,
        }
        return cls(
            scope_id=derive_identity("scope", payload),
            drugs=canonical_drugs,
            adverse_reactions=canonical_reactions,
            date_range=date_range,
            selected_sources=canonical_sources,
            comparison_intent=comparison_intent,
            query_bounds=query_bounds,
            result_bounds=result_bounds,
        )

    @model_validator(mode="after")
    def validate_canonical_content(self) -> Self:
        drug_ids = tuple(item.concept_id for item in self.drugs)
        reaction_ids = tuple(item.concept_id for item in self.adverse_reactions)
        if len(set(drug_ids)) != len(drug_ids):
            raise ValueError("drug concepts must be unique")
        if len(set(reaction_ids)) != len(reaction_ids):
            raise ValueError("adverse-reaction concepts must be unique")
        if len(set(self.selected_sources)) != len(self.selected_sources):
            raise ValueError("selected sources must be unique")
        if drug_ids != tuple(sorted(drug_ids)):
            raise ValueError("drug concepts must be sorted by concept_id")
        if reaction_ids != tuple(sorted(reaction_ids)):
            raise ValueError("adverse-reaction concepts must be sorted by concept_id")
        if self.selected_sources != tuple(
            sorted(self.selected_sources, key=lambda item: item.value)
        ):
            raise ValueError("selected sources must be canonically sorted")

        expected = derive_identity(
            "scope",
            self.model_dump(mode="python", exclude={"scope_id"}),
        )
        if self.scope_id != expected:
            raise ValueError("scope_id does not match canonical scope content")
        return self


class DailyMedSelectionMode(StrEnum):
    """Closed request mode; a pin is still subject to executed discovery."""

    STRICT_IDENTITY = "strict_identity"
    PINNED_VERSION = "pinned_version"


type DailyMedSectionCode = Literal["34084-4", "43685-7", "34066-1", "34067-9"]


class DailyMedSelectionRequestV1(DurableModel):
    """One bounded product/section request for the additive M1B contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.dailymed.request.v1"] = "m1b.dailymed.request.v1"
    drug_concept_id: DrugConceptId
    pinned_setid: CanonicalSetId | None = None
    pinned_spl_version: CanonicalSplVersion | None = None
    requested_section_codes: tuple[DailyMedSectionCode, ...] = Field(
        min_length=1,
        max_length=4,
    )
    selection_mode: DailyMedSelectionMode

    @model_validator(mode="after")
    def validate_selection_request(self) -> Self:
        if self.requested_section_codes != tuple(sorted(set(self.requested_section_codes))):
            raise ValueError("requested section codes must be unique and canonically sorted")
        has_setid = self.pinned_setid is not None
        has_version = self.pinned_spl_version is not None
        if has_setid != has_version:
            raise ValueError("pinned SETID and SPL version are both-or-neither")
        if self.selection_mode is DailyMedSelectionMode.PINNED_VERSION and not has_setid:
            raise ValueError("pinned_version mode requires the exact SETID/version pair")
        if self.selection_mode is DailyMedSelectionMode.STRICT_IDENTITY and has_setid:
            raise ValueError("strict_identity mode forbids pinned identity fields")
        return self


class M1BResearchRequestV1(DurableModel):
    """Parallel additive M1B request envelope; it never accepts planning state."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    schema_version: Literal["m1b.request.v1"] = "m1b.request.v1"
    request_id: RequestId
    scope: ResearchScope
    requested_sources: tuple[SourceType, ...] = Field(min_length=1, max_length=4)
    dailymed_selection_requests: tuple[DailyMedSelectionRequestV1, ...] = Field(
        default=(),
        max_length=4,
    )
    faers_query_requests: tuple[()] = ()
    cadec_query_requests: tuple[()] = ()

    @model_validator(mode="after")
    def validate_request_source_bindings(self) -> Self:
        if self.requested_sources != tuple(
            sorted(set(self.requested_sources), key=lambda item: item.value)
        ):
            raise ValueError("requested_sources must be unique and canonically sorted")
        if self.requested_sources != self.scope.selected_sources:
            raise ValueError("requested_sources must equal the scope source set")
        dailymed_selected = SourceType.DAILYMED in self.requested_sources
        if dailymed_selected != bool(self.dailymed_selection_requests):
            raise ValueError("DailyMed request elements exist exactly when DailyMed is requested")
        scope_drug_ids = {drug.concept_id for drug in self.scope.drugs}
        request_drug_ids = tuple(
            request.drug_concept_id for request in self.dailymed_selection_requests
        )
        if any(drug_id not in scope_drug_ids for drug_id in request_drug_ids):
            raise ValueError("DailyMed request drug must belong to the request scope")
        if len(set(request_drug_ids)) != len(request_drug_ids):
            raise ValueError("DailyMed selection requests must be unique by drug")
        if request_drug_ids != tuple(sorted(request_drug_ids)):
            raise ValueError("DailyMed selection requests must be canonically sorted by drug")
        return self
