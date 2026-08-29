"""Stable structured FAERS aggregate operation over injected consumer ports."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    RunId,
    Sha256Digest,
)
from medevidence.domain.identifiers import DurableModel

from .contracts import FaersAggregateExecution, PersistedFaersAggregate
from .ports import FaersExecutionPort, FaersPersistencePort

type StableProjectionId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class FaersBucketEvidenceProjection(DurableModel):
    """Content-free persisted evidence identity for one aggregate bucket."""

    schema_version: Literal["m3.faers-bucket-evidence-projection.v1"] = (
        "m3.faers-bucket-evidence-projection.v1"
    )
    bucket_ordinal: int = Field(ge=0, lt=100)
    evidence_id: StableProjectionId
    content_hash: Sha256Digest
    locator_ref: StableProjectionId


class FaersAggregateProvenanceProjection(DurableModel):
    """Persisted aggregate evidence identities without query or outcome authority."""

    schema_version: Literal["m3.faers-aggregate-provenance.v1"] = "m3.faers-aggregate-provenance.v1"
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    query_id: StableProjectionId
    snapshot_id: StableProjectionId
    manifest_id: StableProjectionId
    bucket_evidence: tuple[FaersBucketEvidenceProjection, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        ordinals = tuple(item.bucket_ordinal for item in self.bucket_evidence)
        if ordinals != tuple(range(len(ordinals))):
            raise ValueError("FAERS persisted bucket provenance must use canonical ordinals")
        evidence_ids = tuple(item.evidence_id for item in self.bucket_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("FAERS persisted bucket evidence identities must be unique")
        return self


class FaersAggregateExecutionProjection(DurableModel):
    """Exact persisted aggregate execution plus content-free bucket identities."""

    schema_version: Literal["m3.faers-aggregate-execution-projection.v1"] = (
        "m3.faers-aggregate-execution-projection.v1"
    )
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    execution: FaersAggregateExecution
    bucket_evidence: tuple[FaersBucketEvidenceProjection, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        execution = FaersAggregateExecution.model_validate(self.execution.model_dump(mode="python"))
        if execution != self.execution:
            raise ValueError("FAERS projection contains an unvalidated execution")
        ordinals = tuple(item.bucket_ordinal for item in self.bucket_evidence)
        expected = tuple(item.bucket_ordinal for item in execution.result.buckets)
        if ordinals != expected:
            raise ValueError("FAERS bucket evidence must equal the exact aggregate bucket set")
        evidence_ids = tuple(item.evidence_id for item in self.bucket_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("FAERS bucket evidence identities must be unique")
        return self


class _ProjectionCapturePersistence:
    """Capture the same persistence echo validated by the legacy fetch authority."""

    def __init__(self, delegate: FaersPersistencePort) -> None:
        self._delegate = delegate
        self.returned: PersistedFaersAggregate | None = None

    def persist(self, execution: FaersAggregateExecution) -> PersistedFaersAggregate:
        """Delegate exactly once and retain the returned typed echo for projection."""

        returned = self._delegate.persist(execution)
        self.returned = returned
        return returned


def execute_faers_aggregate(
    request: FaersAggregateRequestV1,
    *,
    execution: FaersExecutionPort,
    persistence: FaersPersistencePort,
) -> FaersAggregateExecution:
    """Execute and return the exact persisted aggregate execution projection."""

    capture = _ProjectionCapturePersistence(persistence)
    result = fetch_faers_aggregate(
        request,
        execution=execution,
        persistence=capture,
    )
    if capture.returned is None:
        raise ValueError("FAERS persistence returned no execution projection")
    persisted = PersistedFaersAggregate.model_validate(capture.returned.model_dump(mode="python"))
    if persisted.execution.result != result:
        raise ValueError("FAERS projected execution differs from the validated result")
    return FaersAggregateExecution.model_validate(persisted.execution.model_dump(mode="python"))


def fetch_faers_aggregate(
    request: FaersAggregateRequestV1,
    *,
    execution: FaersExecutionPort,
    persistence: FaersPersistencePort,
) -> FaersAggregateResult:
    """Execute and persist one exact provider-count aggregate before returning it."""

    validated_request = FaersAggregateRequestV1.model_validate(request.model_dump(mode="python"))
    if validated_request != request:
        raise ValueError("FAERS tool request differs from closed validation")
    query = FaersAggregateQueryV1.create(validated_request)
    executed = FaersAggregateExecution.model_validate(
        execution.execute(query).model_dump(mode="python")
    )
    if executed.request != validated_request or executed.result.query != query:
        raise ValueError("FAERS execution belongs to another exact request or query")
    persisted = PersistedFaersAggregate.model_validate(
        persistence.persist(executed).model_dump(mode="python")
    )
    if persisted.execution != executed:
        raise ValueError("persisted FAERS evidence differs from the exact execution")
    return FaersAggregateResult.model_validate(persisted.execution.result.model_dump(mode="python"))
