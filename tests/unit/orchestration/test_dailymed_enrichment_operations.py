"""DailyMed operation ordering with explicit candidate enrichment."""

from __future__ import annotations

import pytest

from medevidence.domain import SourceType
from medevidence.orchestration.contracts import (
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    validate_required_operation_plan,
)
from medevidence.orchestration.source_task_projection import required_source_operation

RUN = "run:11111111-1111-4111-8111-111111111111"
SCOPE = "scope:test"


def operation(ordinal: int, kind: SourceOperationKind):
    roles = {
        SourceOperationKind.DAILYMED_DISCOVERY: (
            (SourceOperationInputRole.REQUEST, "request:test"),
        ),
        SourceOperationKind.DAILYMED_CANDIDATE_ENRICHMENT: (
            (SourceOperationInputRole.DISCOVERY_SUMMARY, "summary:test"),
            (SourceOperationInputRole.DAILYMED_DISCOVERY_QUERY, "query:discovery"),
            (SourceOperationInputRole.SETID, "11111111-1111-4111-8111-111111111111"),
            (SourceOperationInputRole.SPL_VERSION, "1"),
        ),
        SourceOperationKind.DAILYMED_FETCH: (
            (SourceOperationInputRole.DAILYMED_DECISION, "decision:test"),
            (SourceOperationInputRole.CANDIDATE, "candidate:test"),
            (SourceOperationInputRole.SETID, "11111111-1111-4111-8111-111111111111"),
            (SourceOperationInputRole.SPL_VERSION, "1"),
        ),
    }[kind]
    return required_source_operation(
        run_id=RUN,
        scope_id=SCOPE,
        source=SourceType.DAILYMED,
        ordinal=ordinal,
        kind=kind,
        query_id=(
            "query:discovery"
            if kind is not SourceOperationKind.DAILYMED_CANDIDATE_ENRICHMENT
            else "query:packaging"
        ),
        input_refs=tuple(SourceOperationInputRef(role=role, value=value) for role, value in roles),
    )


def test_discovery_enrichment_fetch_order_is_accepted() -> None:
    operations = tuple(
        operation(index, kind)
        for index, kind in enumerate(
            (
                SourceOperationKind.DAILYMED_DISCOVERY,
                SourceOperationKind.DAILYMED_CANDIDATE_ENRICHMENT,
                SourceOperationKind.DAILYMED_FETCH,
            )
        )
    )
    validate_required_operation_plan(SourceType.DAILYMED, operations)
    with pytest.raises(ValueError, match="order"):
        validate_required_operation_plan(
            SourceType.DAILYMED,
            (
                operation(0, SourceOperationKind.DAILYMED_DISCOVERY),
                operation(1, SourceOperationKind.DAILYMED_FETCH),
                operation(2, SourceOperationKind.DAILYMED_CANDIDATE_ENRICHMENT),
            ),
        )
