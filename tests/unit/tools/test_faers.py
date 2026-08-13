"""Offline tests for the stable narrative-free FAERS aggregate tool."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from medevidence.composition import create_faers_aggregate_tool
from medevidence.domain import (
    AcquisitionOutcomeRef,
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
from medevidence.tools import (
    FaersAggregateExecution,
    PersistedFaersAggregate,
    fetch_faers_aggregate,
)
from medevidence.tools.ports import FaersExecutionPort, FaersPersistencePort

RUN_ID = "run:00000000-0000-4000-8000-000000000001"
ACQUISITION_INTENT_ID = "acquisition-intent:sha256:" + "1" * 64


def _request(**changes: object) -> FaersAggregateRequestV1:
    values: dict[str, object] = {
        "drug_concept_id": "drug:synthetic",
        "identity_strategy": FaersIdentityStrategy.HARMONIZED_SUBSTANCE,
        "identity_exact_value": "SYNTHETIC INGREDIENT",
        "pt_values": ("DIARRHOEA", "NAUSEA", "VOMITING"),
        "inclusive_date_range": FaersInclusiveDateRangeV1(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        ),
        "statistical_unit": "provider_count_occurrence",
        "execution_bounds": FaersExecutionBoundsV1(
            max_date_difference_days=365,
            max_inclusive_calendar_dates=366,
        ),
    }
    values.update(changes)
    return FaersAggregateRequestV1(**values)


def _outcome(
    query: FaersAggregateQueryV1,
    *,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    status: ResultStatus = ResultStatus.MATCHES,
    count: int = 1,
) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.FAERS,
        query_id=query.query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=status,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=count,
        pages_completed=1 if coverage is not CoverageStatus.UNAVAILABLE else 0,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=("incomplete_coverage",) if coverage is not CoverageStatus.COMPLETE else (),
        failure_id="failure:synthetic" if execution is ExecutionStatus.FAILED else None,
    )


def _execution(
    request: FaersAggregateRequestV1,
    *,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    status: ResultStatus = ResultStatus.MATCHES,
) -> FaersAggregateExecution:
    query = FaersAggregateQueryV1.create(request)
    matches = status is ResultStatus.MATCHES
    buckets = (
        (
            FaersAggregateBucketV1(
                query_id=query.query_id,
                bucket_ordinal=0,
                reaction_pt="NAUSEA",
                report_count=7,
                identity_stratum=query.identity_stratum,
            ),
        )
        if matches
        else ()
    )
    result = FaersAggregateResult(
        query=query,
        buckets=buckets,
        source_outcome=_outcome(
            query,
            execution=execution,
            coverage=coverage,
            status=status,
            count=len(buckets),
        ),
        retrieved_at_utc=datetime(2025, 2, 1, tzinfo=UTC),
        provider_as_of_utc=None,
        snapshot_id="snapshot:synthetic-faers",
        manifest_id="artifact:synthetic-faers-manifest",
    )
    return FaersAggregateExecution(
        request=request,
        acquisition_outcome_ref=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.FAERS,
            acquisition_id="acquisition:synthetic-faers",
            acquisition_intent_id=ACQUISITION_INTENT_ID,
            acquisition_ordinal=0,
            operation="search",
            query_id=query.query_id,
            source_outcome_id="source-outcome:synthetic-faers",
            snapshot_id=result.snapshot_id,
        ),
        result=result,
    )


class _ExecutionPort:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0
        self.events: list[str] = []

    def execute(self, query: FaersAggregateQueryV1) -> FaersAggregateExecution:
        self.calls += 1
        self.events.append("execute")
        return cast(FaersAggregateExecution, self.value)


class _RawExecution:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "python"
        return deepcopy(self.value)


class _PersistencePort:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.foreign: FaersAggregateExecution | None = None

    def persist(self, execution: FaersAggregateExecution) -> PersistedFaersAggregate:
        self.events.append("persist")
        return PersistedFaersAggregate(execution=self.foreign or execution)


def _run(
    request: FaersAggregateRequestV1,
    executed: FaersAggregateExecution,
) -> tuple[FaersAggregateResult, _ExecutionPort, _PersistencePort]:
    execution = _ExecutionPort(executed)
    persistence = _PersistencePort(execution.events)
    result = fetch_faers_aggregate(
        request,
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, persistence),
    )
    return result, execution, persistence


def test_faers_tool_persists_exact_execution_before_return() -> None:
    request = _request()
    executed = _execution(request)
    result, execution, _persistence = _run(request, executed)
    assert result == executed.result
    assert result is not executed.result
    assert execution.events == ["execute", "persist"]


def test_faers_composition_is_inert_until_the_returned_tool_is_called() -> None:
    request = _request()
    execution = _ExecutionPort(_execution(request))
    persistence = _PersistencePort(execution.events)
    application = create_faers_aggregate_tool(
        execution=cast(FaersExecutionPort, execution),
        persistence=cast(FaersPersistencePort, persistence),
    )
    assert execution.events == []
    assert application(request).query == FaersAggregateQueryV1.create(request)
    assert execution.events == ["execute", "persist"]


@pytest.mark.parametrize(
    "foreign_request",
    [
        _request(identity_exact_value="FOREIGN INGREDIENT"),
        _request(identity_strategy=FaersIdentityStrategy.NATIVE_MEDICINAL_PRODUCT),
        _request(
            inclusive_date_range=FaersInclusiveDateRangeV1(
                start_date=date(2025, 1, 2), end_date=date(2025, 1, 31)
            )
        ),
    ],
)
def test_faers_tool_rejects_one_field_request_query_identity_drift(
    foreign_request: FaersAggregateRequestV1,
) -> None:
    request = _request()
    execution = _ExecutionPort(_execution(foreign_request))
    persistence = _PersistencePort(execution.events)
    with pytest.raises(ValueError, match="another exact request or query"):
        fetch_faers_aggregate(
            request,
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )
    assert execution.events == ["execute"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("request", "pt_values"), ("DIARRHOEA", "NAUSEA")),
        (("request", "statistical_unit"), "raw_case"),
        (("request", "role_policy"), "primary_suspect_only"),
        (("request", "execution_bounds", "max_pages"), 4),
        (("result", "query", "pt_values"), ("DIARRHOEA", "NAUSEA")),
        (("result", "query", "statistical_unit"), "raw_case"),
        (("result", "query", "role_policy"), "primary_suspect_only"),
        (("result", "buckets", 0, "bucket_ordinal"), 1),
        (("result", "buckets", 0, "reaction_pt"), "CONSTIPATION"),
        (("result", "buckets", 0, "statistical_unit"), "raw_case"),
        (("result", "buckets", 0, "role_policy"), "primary_suspect_only"),
        (("result", "source_outcome", "query_id"), "query:foreign"),
        (("acquisition_outcome_ref", "source"), "pubmed"),
        (("acquisition_outcome_ref", "snapshot_id"), "snapshot:foreign"),
    ],
)
def test_faers_tool_revalidates_each_closed_execution_dimension(
    path: tuple[str | int, ...], value: object
) -> None:
    request = _request()
    payload: Any = _execution(request).model_dump(mode="python")
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    execution = _ExecutionPort(_RawExecution(payload))
    persistence = _PersistencePort(execution.events)
    with pytest.raises(ValueError):
        fetch_faers_aggregate(
            request,
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )
    assert execution.events == ["execute"]


def test_faers_tool_rejects_noncanonical_bucket_order() -> None:
    request = _request()
    first = _execution(request)
    values = first.result.model_dump(mode="python")
    query = first.result.query
    values["buckets"] = (
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=0,
            reaction_pt="DIARRHOEA",
            report_count=7,
            identity_stratum=query.identity_stratum,
        ),
        FaersAggregateBucketV1(
            query_id=query.query_id,
            bucket_ordinal=1,
            reaction_pt="NAUSEA",
            report_count=7,
            identity_stratum=query.identity_stratum,
        ),
    )
    values["source_outcome"]["valid_result_count"] = 2
    valid = FaersAggregateExecution(
        request=request,
        acquisition_outcome_ref=first.acquisition_outcome_ref,
        result=FaersAggregateResult.model_validate(values),
    )
    payload = valid.model_dump(mode="python")
    payload["result"]["buckets"] = tuple(reversed(payload["result"]["buckets"]))
    execution = _ExecutionPort(_RawExecution(payload))
    persistence = _PersistencePort(execution.events)
    with pytest.raises(ValueError, match="report_count DESC"):
        fetch_faers_aggregate(
            request,
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )
    assert execution.events == ["execute"]


@pytest.mark.parametrize(
    ("execution_status", "coverage", "result_status"),
    [
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE),
        (ExecutionStatus.FAILED, CoverageStatus.UNAVAILABLE, ResultStatus.INDETERMINATE),
    ],
)
def test_faers_tool_preserves_complete_empty_partial_and_unavailable_outcomes(
    execution_status: ExecutionStatus,
    coverage: CoverageStatus,
    result_status: ResultStatus,
) -> None:
    request = _request()
    executed = _execution(
        request,
        execution=execution_status,
        coverage=coverage,
        status=result_status,
    )
    result, _execution_port, _persistence = _run(request, executed)
    assert result.source_outcome == executed.result.source_outcome
    assert result.buckets == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "run:00000000-0000-4000-8000-000000000002"),
        ("acquisition_id", "acquisition:foreign"),
        ("acquisition_intent_id", "acquisition-intent:sha256:" + "2" * 64),
        ("acquisition_ordinal", 1),
        ("source_outcome_id", "source-outcome:foreign"),
        ("snapshot_id", "snapshot:foreign"),
        ("manifest_id", "artifact:foreign-manifest"),
    ],
)
def test_faers_tool_rejects_each_persisted_identity_drift(field: str, value: object) -> None:
    request = _request()
    executed = _execution(request)
    execution = _ExecutionPort(executed)
    persistence = _PersistencePort(execution.events)
    foreign_values = executed.model_dump(mode="python")
    if field == "manifest_id":
        foreign_values["result"][field] = value
    else:
        foreign_values["acquisition_outcome_ref"][field] = value
        if field == "snapshot_id":
            foreign_values["result"][field] = value
    persistence.foreign = FaersAggregateExecution.model_validate(foreign_values)
    with pytest.raises(ValueError, match="differs from the exact execution"):
        fetch_faers_aggregate(
            request,
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )
    assert execution.events == ["execute", "persist"]


def test_faers_tool_validates_request_before_execution() -> None:
    request = _request()
    values = {name: getattr(request, name) for name in type(request).model_fields}
    values["identity_exact_value"] = " percent%encoded"
    invalid = FaersAggregateRequestV1.model_construct(**values)
    execution = _ExecutionPort(_execution(request))
    persistence = _PersistencePort(execution.events)
    with pytest.raises(ValueError):
        fetch_faers_aggregate(
            invalid,
            execution=cast(FaersExecutionPort, execution),
            persistence=cast(FaersPersistencePort, persistence),
        )
    assert execution.calls == 0
    assert execution.events == []
