"""Unit tests for source-neutral provenance and failure alignment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    CoverageStatus,
    DomainWarning,
    ExecutionBounds,
    ExecutionStatus,
    FailureCode,
    Provenance,
    ResultStatus,
    SourceFailure,
    SourceOutcome,
    SourceType,
    sha256_digest,
)


def bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )


def complete_outcome() -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:one",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=bounds(),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
    )


def successful_provenance() -> Provenance:
    return Provenance(
        source=SourceType.PUBMED,
        source_record_id="12345",
        query_id="query:one",
        source_lookup_key="pubmed:12345",
        retrieved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b"raw publication bytes"),
        snapshot_id=None,
        artifact_ids=(),
        transformation_lineage=(),
        warnings=(),
        failure=None,
        source_outcome=complete_outcome(),
        configured_bounds=bounds(),
    )


def test_provenance_serializes_utc_with_z_and_round_trips() -> None:
    provenance = successful_provenance()
    serialized = provenance.model_dump_json()

    assert '"retrieved_at":"2026-07-27T12:00:00Z"' in serialized
    assert Provenance.model_validate_json(serialized) == provenance


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 27, 12, 0),
        datetime(2026, 7, 27, 12, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_provenance_rejects_naive_and_non_utc_timestamps(
    timestamp: datetime,
) -> None:
    data = successful_provenance().model_dump(mode="python")
    data["retrieved_at"] = timestamp
    with pytest.raises(ValidationError):
        Provenance(**data)


def test_failed_unavailable_provenance_preserves_typed_failure_without_record() -> None:
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:failed",
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=bounds(),
        valid_result_count=0,
        pages_completed=0,
        truncated=False,
        warning_codes=("source_unavailable",),
        failure_id="failure:timeout",
    )
    provenance = Provenance(
        source=SourceType.PUBMED,
        source_record_id=None,
        query_id="query:failed",
        source_lookup_key="pubmed:bounded-query",
        retrieved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b""),
        warnings=(
            DomainWarning(
                code="source_unavailable",
                message="No usable source response was obtained.",
            ),
        ),
        failure=SourceFailure(
            failure_id="failure:timeout",
            failure_code=FailureCode.TIMEOUT,
            retryable=True,
        ),
        source_outcome=outcome,
        configured_bounds=bounds(),
    )

    assert provenance.source_record_id is None
    assert provenance.failure is not None
    assert provenance.failure.failure_code is FailureCode.TIMEOUT


@pytest.mark.parametrize(
    "changes",
    [
        {"source": SourceType.CADEC},
        {"query_id": "query:other"},
        {
            "configured_bounds": ExecutionBounds(
                max_query_characters=100,
                max_pages=1,
                max_records=1,
                max_payload_bytes=100,
                max_total_seconds=1,
            )
        },
        {
            "warnings": (
                DomainWarning(code="z_warning", message="z"),
                DomainWarning(code="a_warning", message="a"),
            )
        },
    ],
)
def test_provenance_rejects_source_query_bounds_and_warning_drift(
    changes: dict[str, object],
) -> None:
    data = successful_provenance().model_dump(mode="python")
    data.update(changes)
    with pytest.raises(ValidationError):
        Provenance(**data)


def test_provenance_is_strict_frozen_and_forbids_extras() -> None:
    provenance = successful_provenance()
    with pytest.raises(ValidationError):
        provenance.query_id = "query:mutated"
    with pytest.raises(ValidationError):
        Provenance(
            **{
                **provenance.model_dump(mode="python"),
                "provider_response": object(),
            }
        )
