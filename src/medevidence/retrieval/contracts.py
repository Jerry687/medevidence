"""Source-neutral retrieval contracts.

These contracts intentionally expose no vendor-native object. A Qdrant, FAISS,
or in-memory backend must all satisfy the same `RetrievalPort` and return the
same `RetrievalHit` shape, so that swapping the backend cannot change what
crosses the layer boundary (ARCHITECTURE INV, `V1-NFR-005`).

Configuration values carried here (`k1`, `b`, embedding dimensionality, RRF
`k`, candidate/final limits) are **experiment configuration, not approved
values**. Decision gate `ME-000C` remains open; nothing in this module may be
read as freezing it. Every result therefore carries the exact
`RetrievalConfig` that produced it.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, StringConstraints, model_validator

from ..domain.identifiers import DurableModel, SchemaVersion, canonical_json

CHUNKER_VERSION = "m2.chunker.v1"
"""Deterministic chunker identity. Any behavioural change requires a new value."""

MAX_QUERY_CHARACTERS = 512
MAX_CANDIDATE_LIMIT = 1000
MAX_FINAL_LIMIT = 100
MAX_CHUNK_CHARACTERS = 4096

type ChunkId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
type RecordId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
type QueryId = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class RetrievalMode(StrEnum):
    """The four baselines required by `EVALUATION_PLAN` section 6.1."""

    SPARSE = "sparse"
    DENSE = "dense"
    HYBRID_RRF = "hybrid_rrf"
    HYBRID_RRF_RERANKED = "hybrid_rrf_reranked"


class DocumentChunk(DurableModel):
    """Derived retrievable text with an exact locator back into its record.

    The chunk is *derived*; the source record remains authoritative. `char_start`
    and `char_end` are offsets into the exact normalized record text, so a
    citation built from a chunk can always be resolved back to a span.
    """

    schema_version: SchemaVersion = "1.0"
    chunk_id: ChunkId
    record_id: RecordId
    source: str
    ordinal: int = Field(ge=0)
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_CHUNK_CHARACTERS)]
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    content_hash: str
    chunker_version: str = CHUNKER_VERSION
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Reject spans that cannot describe the chunk they claim to locate."""

        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("span width must equal the chunk text length")
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.content_hash != f"sha256:{expected}":
            raise ValueError("content_hash must be sha256 of the exact chunk text")
        return self


class RetrievalConfig(DurableModel):
    """Exact, versioned configuration for one retrieval run.

    Recorded with every result so that a measurement can never be reported
    without the configuration that produced it (`V1-NFR-008`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: SchemaVersion = "1.0"
    mode: RetrievalMode
    candidate_limit: int = Field(ge=1, le=MAX_CANDIDATE_LIMIT)
    final_limit: int = Field(ge=1, le=MAX_FINAL_LIMIT)
    # Sparse
    bm25_k1: float = Field(default=0.9, ge=0.0, le=10.0)
    bm25_b: float = Field(default=0.4, ge=0.0, le=1.0)
    tokenizer: Literal["unicode_lower_alnum_v1"] = "unicode_lower_alnum_v1"
    # Dense
    embedding_method: Literal["tfidf_svd_v1", "external_vectors_v1"] = "tfidf_svd_v1"
    embedding_dimensions: int = Field(default=256, ge=2, le=4096)
    # Fusion
    rrf_k: int = Field(default=60, ge=1, le=1000)
    # Provenance
    corpus_id: str = "unspecified"
    notes: str = ""

    @property
    def config_id(self) -> str:
        """Deterministic identity of this exact configuration."""

        payload = self.model_dump(mode="json")
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest[:32]}"


class RetrievalQuery(DurableModel):
    """A normalized retrieval request. Callers never supply backend syntax."""

    schema_version: SchemaVersion = "1.0"
    query_id: QueryId
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_QUERY_CHARACTERS)]
    mode: RetrievalMode
    candidate_limit: int = Field(default=100, ge=1, le=MAX_CANDIDATE_LIMIT)
    final_limit: int = Field(default=10, ge=1, le=MAX_FINAL_LIMIT)
    filters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        """A final limit above the candidate limit cannot be satisfied."""

        if self.final_limit > self.candidate_limit:
            raise ValueError("final_limit cannot exceed candidate_limit")
        return self


class RetrievalHit(DurableModel):
    """One ranked result with its component scores preserved.

    Component scores are retained separately from the fused score so that a
    hybrid ranking can be explained and reproduced rather than asserted.
    """

    schema_version: SchemaVersion = "1.0"
    chunk_id: ChunkId
    record_id: RecordId
    rank: int = Field(ge=1)
    score: float
    method: RetrievalMode
    component_scores: dict[str, float] = Field(default_factory=dict)
    component_ranks: dict[str, int] = Field(default_factory=dict)


class RetrievalResult(DurableModel):
    """The complete, self-describing outcome of one retrieval call."""

    schema_version: SchemaVersion = "1.0"
    query_id: QueryId
    mode: RetrievalMode
    config_id: str
    hits: tuple[RetrievalHit, ...]
    candidates_considered: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_ranks(self) -> Self:
        """Ranks must be dense, ascending, and start at one."""

        expected = tuple(range(1, len(self.hits) + 1))
        if tuple(hit.rank for hit in self.hits) != expected:
            raise ValueError("hit ranks must be 1..n in ascending order")
        seen: set[str] = set()
        for hit in self.hits:
            if hit.chunk_id in seen:
                raise ValueError("a chunk may not appear twice in one result")
            seen.add(hit.chunk_id)
        return self


def as_jsonable(value: Any) -> Any:
    """Return a plain-JSON view for raw-artifact persistence."""

    if isinstance(value, DurableModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: as_jsonable(item) for key, item in value.items()}
    return value
