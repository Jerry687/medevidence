"""Source-neutral research-scope contracts and approved execution bounds."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from .identifiers import (
    AdverseEventConceptId,
    DrugConceptId,
    DurableModel,
    NonBlankText,
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
