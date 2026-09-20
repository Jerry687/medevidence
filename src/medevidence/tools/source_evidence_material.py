"""Pure canonical evidence material derived from verified source records."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.identifiers import DurableModel

from .contracts import FaersAggregateExecution
from .report_validation import (
    _FAERS_NUMBER,
    ClaimClass,
    EvidenceInput,
    InferenceUse,
    NumericalContextInput,
    NumericalFactInput,
    canonical_evidence_id,
    canonical_numerical_text,
)

MAX_SOURCE_EXECUTION_INTENT_BYTES = 65_536


class FaersSourceExecutionIntentV1(DurableModel):
    """Immutable exact START record written before one FAERS HTTP operation."""

    marker: Literal["M1B_FAERS_SOURCE_EXECUTION_INTENT_V1"] = "M1B_FAERS_SOURCE_EXECUTION_INTENT_V1"
    acquisition_intent_id: Annotated[
        str, StringConstraints(pattern=r"^acquisition-intent:sha256:[0-9a-f]{64}$")
    ]
    run_id: str
    scope_id: str
    task_id: str
    attempt_id: str
    acquisition_id: str
    acquisition_ordinal: int = Field(ge=0, le=7)
    query_id: str
    request_hash: str
    query: FaersAggregateQueryV1
    created_at_utc: datetime
    code_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]

    @model_validator(mode="after")
    def validate_request_binding(self) -> FaersSourceExecutionIntentV1:
        exact = FaersAggregateQueryV1.model_validate(
            self.query.model_dump(mode="python"), strict=True
        )
        if exact != self.query or self.query.query_id != self.query_id:
            raise ValueError("FAERS source execution intent query differs")
        if self.request_hash != sha256_digest(canonical_json(exact)):
            raise ValueError("FAERS source execution intent request hash differs")
        if self.acquisition_intent_id != faers_source_execution_intent_id(
            run_id=self.run_id,
            scope_id=self.scope_id,
            task_id=self.task_id,
            attempt_id=self.attempt_id,
            acquisition_ordinal=self.acquisition_ordinal,
            query_id=self.query_id,
            request_hash=self.request_hash,
            code_revision=self.code_revision,
        ):
            raise ValueError("FAERS source execution intent identity differs")
        return self

    def canonical_bytes(self) -> bytes:
        raw = canonical_json(self).encode("utf-8")
        if len(raw) > MAX_SOURCE_EXECUTION_INTENT_BYTES:
            raise ValueError("FAERS source execution intent exceeds its byte bound")
        return raw


def faers_source_execution_intent_id(
    *,
    run_id: str,
    scope_id: str,
    task_id: str,
    attempt_id: str,
    acquisition_ordinal: int,
    query_id: str,
    request_hash: str,
    code_revision: str,
) -> str:
    """Derive the replay key without clock-dependent fields."""

    return derive_identity(
        "acquisition-intent",
        {
            "schema_version": "m1b.faers.source-execution-intent.v1",
            "run_id": run_id,
            "scope_id": scope_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "acquisition_ordinal": acquisition_ordinal,
            "query_id": query_id,
            "request_hash": request_hash,
            "code_revision": code_revision,
        },
    )


def canonical_faers_bucket_bytes(execution: FaersAggregateExecution, ordinal: int) -> bytes:
    """Return the exact normalized bucket bytes consumed by M1B provenance."""

    exact = FaersAggregateExecution.model_validate(execution.model_dump(mode="python"), strict=True)
    if type(ordinal) is not int or not 0 <= ordinal < len(exact.result.buckets):
        raise ValueError("FAERS bucket ordinal is outside the exact result")
    bucket = exact.result.buckets[ordinal]
    if type(bucket) is not FaersAggregateBucketV1 or bucket.bucket_ordinal != ordinal:
        raise ValueError("FAERS bucket order differs from the canonical result")
    return canonical_json(
        {
            "query_id": exact.result.query.query_id,
            "bucket_ordinal": bucket.bucket_ordinal,
            "reaction_pt": bucket.reaction_pt,
            "report_count": bucket.report_count,
            "statistical_unit": bucket.statistical_unit,
            "identity_stratum": bucket.identity_stratum,
            "role_policy": bucket.role_policy,
        }
    ).encode("utf-8")


def canonical_faers_bucket_evidence(
    execution: FaersAggregateExecution,
    ordinal: int,
) -> EvidenceInput:
    """Build one descriptive count fact from exact provider bucket fields only."""

    exact = FaersAggregateExecution.model_validate(execution.model_dump(mode="python"), strict=True)
    if type(ordinal) is not int or not 0 <= ordinal < len(exact.result.buckets):
        raise ValueError("FAERS bucket ordinal is outside the exact result")
    bucket = exact.result.buckets[ordinal]
    acquisition = exact.acquisition_outcome_ref
    query = exact.result.query
    record_id = derive_identity(
        "faers-bucket",
        {
            "query_id": query.query_id,
            "source_outcome_id": acquisition.source_outcome_id,
            "bucket_ordinal": ordinal,
            "reaction_pt": bucket.reaction_pt,
        },
    )
    locator = derive_identity(
        "faers-bucket-locator",
        {
            "query_id": query.query_id,
            "snapshot_id": exact.result.snapshot_id,
            "bucket_ordinal": ordinal,
            "reaction_pt": bucket.reaction_pt,
        },
    )
    context = NumericalContextInput(str(bucket.report_count), *_FAERS_NUMBER)
    statement = canonical_numerical_text(context)
    excerpt = (
        f"FAERS provider count bucket: reaction_pt={bucket.reaction_pt}; "
        f"identity_stratum={query.identity_stratum}; "
        f"identity_value={query.identity_value}; "
        f"{query.date_field}="
        f"{query.inclusive_date_range.start_date.isoformat()}/"
        f"{query.inclusive_date_range.end_date.isoformat()}; "
        f"{statement}"
    )
    fact = NumericalFactInput(
        locator,
        statement,
        *(
            context.value,
            context.unit,
            context.denominator,
            context.comparator,
            context.time_basis,
            context.population_scope,
        ),
    )
    provisional = EvidenceInput(
        evidence_id="evidence:sha256:" + "0" * 64,
        authorized_run_id=acquisition.run_id,
        source=SourceType.FAERS,
        source_record_id=record_id,
        source_version="/".join(
            (query.execution_profile_id, query.ast_schema_version, query.serializer_version)
        ),
        snapshot_id=exact.result.snapshot_id,
        content_hash=sha256_digest(canonical_faers_bucket_bytes(exact, ordinal)),
        locators=(locator,),
        permitted_claim_classes=frozenset({ClaimClass.DESCRIPTIVE}),
        permitted_inference_uses=frozenset({InferenceUse.DESCRIPTIVE}),
        normalized_excerpt=excerpt,
        numerical_facts=(fact,),
    )
    return replace(provisional, evidence_id=canonical_evidence_id(provisional))


__all__ = [
    "MAX_SOURCE_EXECUTION_INTENT_BYTES",
    "FaersSourceExecutionIntentV1",
    "canonical_faers_bucket_bytes",
    "canonical_faers_bucket_evidence",
    "faers_source_execution_intent_id",
]
