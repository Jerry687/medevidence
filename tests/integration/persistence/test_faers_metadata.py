"""Conditional PostgreSQL tests for immutable FAERS aggregate metadata."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    FaersAggregateBucketV1,
    FaersAggregateQueryV1,
    FaersAggregateRequestV1,
    FaersAggregateResult,
    FaersExecutionBoundsV1,
    FaersIdentityStrategy,
    FaersInclusiveDateRangeV1,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.persistence import (
    DATABASE_URL_ENV,
    PersistenceConflict,
    PersistenceRepository,
    PersistenceSettings,
)

RUN_ID = "run:00000000-0000-4000-8000-000000000099"
ACQUISITION_ID = "acquisition:faers-persistence-synthetic"
SNAPSHOT_ID = "snapshot:faers-persistence-synthetic"
MANIFEST_ID = "manifest:faers-persistence-synthetic"
NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _repository() -> PersistenceRepository:
    value = os.environ.get(DATABASE_URL_ENV)
    if value is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    return PersistenceRepository(PersistenceSettings(value))


def _result() -> FaersAggregateResult:
    query = FaersAggregateQueryV1.create(
        FaersAggregateRequestV1(
            drug_concept_id="drug:synthetic",
            identity_strategy=FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
            identity_exact_value="SYNTHETIC",
            pt_values=("DIARRHOEA", "NAUSEA", "VOMITING"),
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
            ),
            statistical_unit="provider_count_occurrence",
            execution_bounds=FaersExecutionBoundsV1(
                max_date_difference_days=365,
                max_inclusive_calendar_dates=366,
            ),
        )
    )
    buckets = tuple(
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=ordinal,
            reaction_pt=pt,
            report_count=count,
            identity_stratum=query.identity_stratum,
        )
        for ordinal, (pt, count) in enumerate((("NAUSEA", 8), ("VOMITING", 4)))
    )
    outcome = SourceOutcome(
        source=SourceType.FAERS,
        query_id=query.query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=2,
        pages_completed=1,
        truncated=False,
    )
    return FaersAggregateResult(
        query=query,
        buckets=buckets,
        source_outcome=outcome,
        retrieved_at_utc=NOW,
        provider_as_of_utc=None,
        snapshot_id=SNAPSHOT_ID,
        manifest_id=MANIFEST_ID,
        limitations=FAERS_MANDATORY_LIMITATIONS,
    )


def _register_parents(repository: PersistenceRepository, result: FaersAggregateResult) -> None:
    repository.insert_or_verify_m1b(
        "m1b_artifacts",
        {
            "artifact_id": MANIFEST_ID,
            "artifact_kind": "faers_aggregate_manifest",
            "source_partition": "faers",
            "content_hash": f"sha256:{'9' * 64}",
            "byte_size": 1,
            "media_type": "application/json",
            "relative_storage_label": "faers/manifests/synthetic.json",
            "schema_version": "m1b.faers.snapshot-manifest.v1",
            "created_at_utc": NOW,
            "corpus_id": None,
            "corpus_version": None,
            "split": None,
        },
    )
    repository.insert_or_verify_m1b(
        "m1b_runs",
        {
            "run_id": RUN_ID,
            "request_id": "request:00000000-0000-4000-8000-000000000099",
            "scope_id": f"scope:sha256:{'9' * 64}",
            "status": "completed",
            "created_at_utc": NOW,
            "completed_at_utc": NOW,
            "schema_version": "m1b.run.v1",
        },
    )
    repository.insert_or_verify_m1b(
        "m1b_acquisitions",
        {
            "acquisition_intent_id": f"acquisition-intent:sha256:{'9' * 64}",
            "acquisition_ordinal": 0,
            "attempt_id": "attempt:00000000-0000-4000-8000-000000000099",
            "run_id": RUN_ID,
            "acquisition_id": ACQUISITION_ID,
            "source": "faers",
            "operation": "search",
            "request_identity": "synthetic-faers-aggregate",
            "query_id": result.query.query_id,
            "execution_profile_id": "FAERS_M1B_CONSTRAINED_V1",
            "started_at_utc": NOW,
            "completed_at_utc": NOW,
            "schema_version": "m1b.acquisition.v1",
        },
    )
    repository.insert_or_verify_m1b(
        "m1b_snapshots",
        {
            "query_id": result.query.query_id,
            "acquisition_intent_id": f"acquisition-intent:sha256:{'9' * 64}",
            "acquisition_ordinal": 0,
            "attempt_id": "attempt:00000000-0000-4000-8000-000000000099",
            "run_id": RUN_ID,
            "snapshot_id": SNAPSHOT_ID,
            "acquisition_id": ACQUISITION_ID,
            "source": "faers",
            "manifest_artifact_id": MANIFEST_ID,
            "retrieved_at_utc": NOW,
            "connector_version": "m1b-faers-002",
            "schema_version": "m1b.faers.snapshot.v1",
        },
    )
    repository.insert_or_verify_m1b(
        "m1b_source_outcomes",
        {
            "source_outcome_id": "source-outcome:faers-persistence-synthetic",
            "snapshot_id": SNAPSHOT_ID,
            "run_id": RUN_ID,
            "query_id": result.query.query_id,
            "acquisition_id": ACQUISITION_ID,
            "source": "faers",
            "acquisition_intent_id": f"acquisition-intent:sha256:{'9' * 64}",
            "acquisition_ordinal": 0,
            "operation": "search",
            "execution_status": "succeeded",
            "coverage_status": "complete",
            "result_status": "matches",
            "max_query_characters": 512,
            "max_pages": 5,
            "max_records": 100,
            "max_payload_bytes": 5_242_880,
            "max_total_seconds": 30,
            "valid_result_count": 2,
            "pages_completed": 1,
            "truncated": False,
            "failure_id": None,
            "warning_codes": [],
            "schema_version": "1.0",
        },
    )


def test_faers_insert_or_verify_is_complete_and_rejects_bucket_drift() -> None:
    repository = _repository()
    try:
        result = _result()
        _register_parents(repository, result)
        first = repository.insert_or_verify_faers_result(
            run_id=RUN_ID, acquisition_id=ACQUISITION_ID, result=result
        )
        second = repository.insert_or_verify_faers_result(
            run_id=RUN_ID, acquisition_id=ACQUISITION_ID, result=result
        )
        assert first == second
        assert first[0]["role_predicate_json"] is None
        assert [row["reaction_pt"] for row in first[1]] == ["NAUSEA", "VOMITING"]
        drift_bucket = result.buckets[0].model_copy(update={"report_count": 7})
        drift = FaersAggregateResult(
            **{
                **result.model_dump(mode="python"),
                "buckets": (drift_bucket, result.buckets[1]),
            }
        )
        with pytest.raises(PersistenceConflict):
            repository.insert_or_verify_faers_result(
                run_id=RUN_ID, acquisition_id=ACQUISITION_ID, result=drift
            )
    finally:
        repository.close()


def test_faers_snapshot_membership_rejects_duplicate_retry_artifact() -> None:
    repository = _repository()
    try:
        result = _result()
        _register_parents(repository, result)
        artifact_id = f"sha256:{'8' * 64}"
        repository.insert_or_verify_m1b_artifact(
            {
                "artifact_id": artifact_id,
                "artifact_kind": "faers_http_response",
                "source_partition": "faers",
                "content_hash": artifact_id,
                "byte_size": 58,
                "media_type": "application/json",
                "relative_storage_label": f"faers/raw/sha256/88/{'8' * 64}.bin",
                "schema_version": "m1b.faers.raw-response.v1",
                "created_at_utc": NOW,
                "corpus_id": None,
                "corpus_version": None,
                "split": None,
            }
        )
        first = {
            "acquisition_id": ACQUISITION_ID,
            "source": "faers",
            "run_id": RUN_ID,
            "snapshot_id": SNAPSHOT_ID,
            "ordinal": 0,
            "link_id": f"artifact-link:sha256:{'7' * 64}",
            "artifact_id": artifact_id,
            "content_hash": artifact_id,
            "body_complete": False,
            "termination_reason": "read_timeout",
            "http_status": 503,
            "observed_at_utc": NOW,
            "corpus_id": None,
            "corpus_version": None,
            "split": None,
            "artifact_kind": "faers_http_response",
        }
        repository.insert_or_verify_m1b("m1b_snapshot_artifacts", first)
        duplicate_retry = {
            **first,
            "ordinal": 1,
            "link_id": f"artifact-link:sha256:{'6' * 64}",
            "body_complete": True,
            "termination_reason": "complete_response",
            "http_status": 200,
        }
        with pytest.raises(
            PersistenceConflict,
            match="uq_m1b_snapshot_artifacts_membership",
        ):
            repository.insert_or_verify_m1b(
                "m1b_snapshot_artifacts",
                duplicate_retry,
            )
    finally:
        repository.close()
