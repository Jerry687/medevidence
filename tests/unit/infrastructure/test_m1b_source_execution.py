from __future__ import annotations

import pytest

from medevidence.infrastructure.m1b_source_execution import (
    DailyMedSourceExecutionBridge,
    M1BSourceExecutionUnavailable,
)


class _Native:
    def resolve(self, request):  # type: ignore[no-untyped-def]
        raise AssertionError(f"must not resolve without enrichment: {request!r}")


def test_dailymed_bridge_fails_unavailable_before_any_native_query_or_io() -> None:
    with pytest.raises(
        M1BSourceExecutionUnavailable,
        match="dailymed_candidate_enrichment_unavailable",
    ):
        DailyMedSourceExecutionBridge(
            native_requests=_Native(),
            candidate_enrichment=None,
        )
