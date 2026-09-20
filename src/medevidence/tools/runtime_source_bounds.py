"""Closed source execution profiles for the additive runtime validation V3 policy."""

from __future__ import annotations

from typing import Final

from medevidence.domain import SourceType

SourceBoundsTuple = tuple[int, int, int, int, int]

# Order: query characters, pages, records, payload bytes, total seconds.
RUNTIME_SOURCE_BOUNDS_V3: Final[tuple[tuple[SourceType, SourceBoundsTuple], ...]] = (
    (SourceType.PUBMED, (512, 1, 100, 5_242_880, 30)),
    (SourceType.DAILYMED, (512, 5, 100, 5_242_880, 30)),
    (SourceType.FAERS, (512, 5, 100, 5_242_880, 30)),
)


def expected_runtime_source_bounds_v3(
    source: SourceType, master_budget: SourceBoundsTuple
) -> SourceBoundsTuple:
    """Return fixed external-source limits; local CADEC retains the master limits."""

    if type(source) is not SourceType:
        raise ValueError("runtime source is not one of the closed authorities")
    if (
        type(master_budget) is not tuple
        or len(master_budget) != 5
        or any(type(value) is not int or value <= 0 for value in master_budget)
    ):
        raise ValueError("runtime master source budget is invalid")
    if source is SourceType.CADEC:
        return master_budget
    try:
        expected = dict(RUNTIME_SOURCE_BOUNDS_V3)[source]
    except KeyError:
        raise ValueError("runtime source has no V3 bounds profile") from None
    if any(actual > budget for actual, budget in zip(expected, master_budget, strict=True)):
        raise ValueError("fixed source limits exceed the authorized master budget")
    return expected
