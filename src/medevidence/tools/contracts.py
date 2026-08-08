"""Strict source-neutral contracts for bounded PubMed application tools."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    AdverseEventConcept,
    DrugConcept,
    Pmid,
    PublicationRecord,
    QueryId,
    RequestId,
    ResearchScope,
    RunId,
    Sha256Digest,
    SourceOutcome,
    SourceType,
    UtcDateTime,
)
from medevidence.domain.identifiers import (
    AcquisitionIntentId,
    AttemptId,
    DurableModel,
    RunIntentId,
    derive_m1a_journal_identity,
)

type CodeRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class ResolvedConceptCatalog(DurableModel):
    """Exact case-sensitive catalog resolution used to construct a query."""

    schema_version: Literal["1.0"] = "1.0"
    catalog_version: Literal["m1a-concepts-v1"] = "m1a-concepts-v1"
    catalog_content_hash: Sha256Digest
    drugs: tuple[DrugConcept, ...] = Field(min_length=1, max_length=4)
    adverse_reactions: tuple[AdverseEventConcept, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        for values in (self.drugs, self.adverse_reactions):
            ids = tuple(item.concept_id for item in values)
            if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
                raise ValueError("resolved catalog concepts must be sorted and unique")
        return self


class SearchPubMedRequest(DurableModel):
    """Validated bounded request for deterministic PubMed query construction."""

    schema_version: Literal["1.0"] = "1.0"
    scope: ResearchScope

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_scope(self.scope)
        return self


class SearchPubMedResponse(DurableModel):
    """Bounded source-neutral PubMed search response."""

    schema_version: Literal["1.0"] = "1.0"
    query: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    query_id: QueryId
    pmids: tuple[Pmid, ...] = Field(max_length=100)
    total_available: int | None = Field(default=None, ge=0)
    source_outcome: SourceOutcome

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if any(len(pmid) > 16 for pmid in self.pmids):
            raise ValueError("PubMed identifiers must contain at most 16 digits")
        if self.pmids != tuple(sorted(set(self.pmids), key=int)):
            raise ValueError("PubMed identifiers must be unique and numerically sorted")
        if self.source_outcome.source is not SourceType.PUBMED:
            raise ValueError("search outcome must be PubMed")
        if self.source_outcome.query_id != self.query_id:
            raise ValueError("search query identity must match its outcome")
        if self.source_outcome.valid_result_count != len(self.pmids):
            raise ValueError("search outcome count must match returned PMIDs")
        if self.total_available is not None and self.total_available < len(self.pmids):
            raise ValueError("total_available cannot be smaller than returned PMIDs")
        if (
            self.total_available is not None
            and self.total_available > len(self.pmids)
            and (
                self.source_outcome.coverage_status.value != "partial"
                or not self.source_outcome.truncated
            )
        ):
            raise ValueError("excess total_available requires partial truncated search coverage")
        return self


class FetchPubMedArticleRequest(DurableModel):
    """Validated singular PubMed fetch request."""

    schema_version: Literal["1.0"] = "1.0"
    scope: ResearchScope
    pmid: Pmid
    query_id: QueryId

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_scope(self.scope)
        if len(self.pmid) > 16:
            raise ValueError("PubMed identifiers must contain at most 16 digits")
        return self


class FetchPubMedArticleResponse(DurableModel):
    """Source-neutral singular PubMed publication response."""

    schema_version: Literal["1.0"] = "1.0"
    requested_pmid: Pmid
    query_id: QueryId
    publication: PublicationRecord | None = None
    source_outcome: SourceOutcome

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.source_outcome.source is not SourceType.PUBMED:
            raise ValueError("fetch outcome must be PubMed")
        if self.source_outcome.query_id != self.query_id:
            raise ValueError("fetch query identity must match its outcome")
        expected_count = 1 if self.publication is not None else 0
        if self.source_outcome.valid_result_count != expected_count:
            raise ValueError("fetch outcome count must match its publication")
        if self.publication is not None and self.publication.pmid != self.requested_pmid:
            raise ValueError("fetch publication must match the requested PMID")
        if self.publication is not None and (
            self.publication.provenance.query_id != self.query_id
            or self.publication.provenance.source_outcome != self.source_outcome
        ):
            raise ValueError("fetch publication provenance must match the fetch outcome")
        return self


class ResearchPubMedRequest(DurableModel):
    """Complete caller-owned identity context for one deterministic M1A run."""

    schema_version: Literal["1.0"] = "1.0"
    request_id: RequestId
    run_id: RunId
    created_at_utc: UtcDateTime
    code_revision: CodeRevision
    scope: ResearchScope

    @model_validator(mode="after")
    def validate_m1a_profile(self) -> Self:
        _validate_scope(self.scope)
        return self


class RunIntentInput(DurableModel):
    """Consumer-owned input mapped to the frozen run journal by composition."""

    schema_version: Literal["1.0"] = "1.0"
    request_id: RequestId
    run_id: RunId
    created_at_utc: UtcDateTime
    code_revision: CodeRevision
    scope_id: str
    catalog_version: Literal["m1a-concepts-v1"] = "m1a-concepts-v1"
    catalog_content_hash: Sha256Digest
    drug_concept_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    adverse_event_concept_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    start_date: date | None = None
    end_date: date | None = None
    pubmed_query: Annotated[str, StringConstraints(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        for values in (self.drug_concept_ids, self.adverse_event_concept_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("run concept identities must be sorted and unique")
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("run date bounds must be both present or both absent")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("run start date must not exceed end date")
        return self


class AcquisitionIntentInput(DurableModel):
    """Consumer-owned singular acquisition input for an injected adapter."""

    schema_version: Literal["1.0"] = "1.0"
    acquisition_intent_id: AcquisitionIntentId
    attempt_id: AttemptId
    run_id: RunId
    run_intent_id: RunIntentId
    created_at_utc: UtcDateTime
    acquisition_ordinal: int = Field(ge=0, le=100)
    operation: Literal["search", "fetch"]
    query: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    pmid: Pmid | None = None

    @classmethod
    def create(
        cls,
        *,
        attempt_id: AttemptId,
        run_id: RunId,
        run_intent_id: RunIntentId,
        created_at_utc: UtcDateTime,
        acquisition_ordinal: int,
        operation: Literal["search", "fetch"],
        query: str | None = None,
        pmid: Pmid | None = None,
    ) -> Self:
        """Construct the exact merged M1A acquisition-intent identity."""

        provisional = cls.model_construct(
            acquisition_intent_id=f"acquisition-intent:sha256:{'0' * 64}",
            attempt_id=attempt_id,
            run_id=run_id,
            run_intent_id=run_intent_id,
            created_at_utc=created_at_utc,
            acquisition_ordinal=acquisition_ordinal,
            operation=operation,
            query=query,
            pmid=pmid,
        )
        return cls(
            acquisition_intent_id=provisional.expected_identity(),
            attempt_id=attempt_id,
            run_id=run_id,
            run_intent_id=run_intent_id,
            created_at_utc=created_at_utc,
            acquisition_ordinal=acquisition_ordinal,
            operation=operation,
            query=query,
            pmid=pmid,
        )

    def expected_identity(self) -> AcquisitionIntentId:
        """Return the ADR-010 identity of the exact merged journal projection."""

        request: dict[str, object]
        if self.operation == "search":
            request = {
                "db": "pubmed",
                "path": "/entrez/eutils/esearch.fcgi",
                "retmax": 100,
                "retmode": "xml",
                "retstart": 0,
                "term": self.query,
            }
        else:
            request = {
                "db": "pubmed",
                "id": self.pmid,
                "path": "/entrez/eutils/efetch.fcgi",
                "retmode": "xml",
                "rettype": "abstract",
            }
        projection = {
            "schema_version": self.schema_version,
            "acquisition_intent_id": self.acquisition_intent_id,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "run_intent_id": self.run_intent_id,
            "created_at_utc": self.created_at_utc,
            "execution_profile_id": "M1A_CONSTRAINED_V1",
            "source": "pubmed",
            "operation": self.operation,
            "acquisition_ordinal": self.acquisition_ordinal,
            "request": request,
            "execution_limits": {
                "base_backoff_ms": 250,
                "cache_policy": "none",
                "connect_timeout_ms": 5_000,
                "jitter_ms": 100,
                "max_attempts": 2,
                "max_backoff_ms": 4_000,
                "max_payload_bytes": 5_242_880,
                "max_redirects": 1,
                "max_retry_after_ms": 10_000,
                "pool_timeout_ms": 5_000,
                "read_timeout_ms": 10_000,
                "total_deadline_ms": 30_000,
                "write_timeout_ms": 5_000,
            },
        }
        return derive_m1a_journal_identity(
            namespace="medevidence:m1a:acquisition-intent:v1",
            prefix="acquisition-intent:sha256:",
            self_field="acquisition_intent_id",
            value=projection,
        )

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        if self.operation == "search":
            if self.acquisition_ordinal != 0 or self.query is None or self.pmid is not None:
                raise ValueError("search acquisition requires ordinal zero and only a query")
        elif (
            not 1 <= self.acquisition_ordinal <= 100 or self.pmid is None or self.query is not None
        ):
            raise ValueError("fetch acquisition requires ordinal 1..100 and only a PMID")
        if self.acquisition_intent_id != self.expected_identity():
            raise ValueError("acquisition_intent_id does not match the merged journal intent")
        return self


def _validate_scope(scope: ResearchScope) -> None:
    if SourceType.PUBMED not in scope.selected_sources:
        raise ValueError("M1A PubMed tools require PubMed in the requested source scope")
    if len(scope.drugs) > 4 or len(scope.adverse_reactions) > 4:
        raise ValueError("M1A_CONSTRAINED_V1 supports at most four terms per concept group")
    if (
        scope.query_bounds.max_query_characters != 512
        or scope.query_bounds.max_pages != 1
        or scope.query_bounds.max_total_seconds != 30
        or scope.result_bounds.max_records != 100
        or scope.result_bounds.max_payload_bytes != 5_242_880
    ):
        raise ValueError("scope bounds must exactly match M1A_CONSTRAINED_V1")
