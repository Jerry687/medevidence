"""Exhaustive tests for source planning and all 18 terminal triples."""

from __future__ import annotations

from itertools import product

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    PlanningStatus,
    ResultStatus,
    SourceOutcome,
    SourcePlanEntry,
    SourcePlanReasonCode,
    SourceType,
)

VALID_TRIPLES = {
    (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
    (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
    (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
    (
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    ),
    (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
    (
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    ),
    (
        ExecutionStatus.FAILED,
        CoverageStatus.UNAVAILABLE,
        ResultStatus.INDETERMINATE,
    ),
}


def bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )


def outcome_for(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=bounds(),
        valid_result_count=1 if result is ResultStatus.MATCHES else 0,
        pages_completed=0 if coverage is CoverageStatus.UNAVAILABLE else 1,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=(
            () if coverage is CoverageStatus.COMPLETE else ("source_coverage_incomplete",)
        ),
        failure_id="failure:test" if execution is ExecutionStatus.FAILED else None,
    )


@pytest.mark.parametrize(
    ("execution", "coverage", "result"),
    list(
        product(
            tuple(ExecutionStatus),
            tuple(CoverageStatus),
            tuple(ResultStatus),
        )
    ),
)
def test_all_eighteen_terminal_triples(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
    result: ResultStatus,
) -> None:
    triple = (execution, coverage, result)
    if triple in VALID_TRIPLES:
        terminal = outcome_for(*triple)
        assert (
            terminal.execution_status,
            terminal.coverage_status,
            terminal.result_status,
        ) == triple
    else:
        with pytest.raises(ValidationError):
            outcome_for(*triple)


@pytest.mark.parametrize(
    "entry",
    [
        SourcePlanEntry(
            source=SourceType.PUBMED,
            planning_status=PlanningStatus.SELECTED,
        ),
        SourcePlanEntry(
            source=SourceType.CADEC,
            planning_status=PlanningStatus.SKIPPED_NOT_APPLICABLE,
            reason_code=SourcePlanReasonCode.NOT_APPLICABLE_TO_SCOPE,
            reason="The auxiliary corpus does not apply to this scope.",
        ),
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="Only PubMed execution is authorized in M1A.",
        ),
    ],
)
def test_all_planning_statuses_are_explicit(entry: SourcePlanEntry) -> None:
    assert "source_outcome" not in type(entry).model_fields


def test_skipped_plan_cannot_contain_or_fabricate_outcome() -> None:
    with pytest.raises(ValidationError):
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SKIPPED_BY_POLICY,
            reason_code=SourcePlanReasonCode.SOURCE_EXECUTION_NOT_AUTHORIZED,
            reason="Not authorized.",
            source_outcome=outcome_for(
                ExecutionStatus.SUCCEEDED,
                CoverageStatus.COMPLETE,
                ResultStatus.NO_MATCH,
            ),
        )
    with pytest.raises(ValidationError):
        SourcePlanEntry(
            source=SourceType.FAERS,
            planning_status=PlanningStatus.SELECTED,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_result_count": 0},
        {"valid_result_count": 101},
        {"pages_completed": 6},
        {"warning_codes": ("duplicate_warning", "duplicate_warning")},
    ],
)
def test_matches_enforces_counts_bounds_and_unique_warnings(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.PARTIAL,
        ResultStatus.MATCHES,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"truncated": True},
        {"failure_id": "failure:unexpected"},
    ],
)
def test_complete_success_forbids_truncation_and_failure_identity(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.COMPLETE,
        ResultStatus.NO_MATCH,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"failure_id": None},
        {"warning_codes": ()},
    ],
)
def test_failed_partial_requires_failure_and_warning(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.FAILED,
        CoverageStatus.PARTIAL,
        ResultStatus.INDETERMINATE,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_result_count": 1},
        {"pages_completed": 1},
        {"warning_codes": ()},
    ],
)
def test_unavailable_requires_zero_progress_and_visible_warning(
    changes: dict[str, object],
) -> None:
    terminal = outcome_for(
        ExecutionStatus.FAILED,
        CoverageStatus.UNAVAILABLE,
        ResultStatus.INDETERMINATE,
    )
    with pytest.raises(ValidationError):
        SourceOutcome(**{**terminal.model_dump(mode="python"), **changes})
