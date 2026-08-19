"""Unit tests for the frozen M2-009 source-scope routing policy."""

from __future__ import annotations

import inspect
from typing import cast

import pytest

import medevidence.retrieval.source_scope_routing as routing
from medevidence.domain.scope import SourceType
from medevidence.retrieval.contracts import RetrievalMode
from medevidence.retrieval.source_scope_routing import (
    UnsupportedSourceScopeError,
    select_retrieval_mode,
)


@pytest.mark.parametrize(
    ("selected_sources", "expected"),
    [
        ((SourceType.PUBMED,), RetrievalMode.DENSE),
        ((SourceType.DAILYMED,), RetrievalMode.SPARSE),
        (
            (SourceType.PUBMED, SourceType.DAILYMED),
            RetrievalMode.HYBRID_RRF,
        ),
        (
            (SourceType.DAILYMED, SourceType.PUBMED),
            RetrievalMode.HYBRID_RRF,
        ),
    ],
)
def test_selects_frozen_mode_for_supported_scope(
    selected_sources: tuple[SourceType, ...],
    expected: RetrievalMode,
) -> None:
    assert select_retrieval_mode(selected_sources) is expected


@pytest.mark.parametrize(
    ("selected_sources", "reason"),
    [
        ((), "selected_sources_empty"),
        ((SourceType.PUBMED, SourceType.PUBMED), "duplicate_source"),
        ((SourceType.FAERS,), "source_scope_unsupported"),
        ((SourceType.CADEC,), "source_scope_unsupported"),
        (
            (SourceType.PUBMED, SourceType.FAERS),
            "source_scope_unsupported",
        ),
        (
            (SourceType.DAILYMED, SourceType.CADEC),
            "source_scope_unsupported",
        ),
    ],
)
def test_rejects_unsupported_scope(
    selected_sources: tuple[SourceType, ...],
    reason: str,
) -> None:
    with pytest.raises(UnsupportedSourceScopeError) as caught:
        select_retrieval_mode(selected_sources)

    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("selected_sources", "reason"),
    [
        (
            cast(tuple[SourceType, ...], [SourceType.PUBMED]),
            "selected_sources_not_tuple",
        ),
        (cast(tuple[SourceType, ...], ("pubmed",)), "source_type_invalid"),
    ],
)
def test_rejects_malformed_source_container_or_item(
    selected_sources: tuple[SourceType, ...],
    reason: str,
) -> None:
    with pytest.raises(UnsupportedSourceScopeError) as caught:
        select_retrieval_mode(selected_sources)

    assert caught.value.reason == reason


def test_selection_is_deterministic_and_stateless() -> None:
    selected_sources = (SourceType.PUBMED, SourceType.DAILYMED)

    first = select_retrieval_mode(selected_sources)
    second = select_retrieval_mode(selected_sources)

    assert first is second is RetrievalMode.HYBRID_RRF
    assert not hasattr(select_retrieval_mode, "cache_info")


def test_signature_exposes_only_structured_selected_sources() -> None:
    signature = inspect.signature(select_retrieval_mode)

    assert tuple(signature.parameters) == ("selected_sources",)
    assert signature.return_annotation == "RetrievalMode"


def test_implementation_contains_no_outcome_derived_routing_inputs() -> None:
    source = inspect.getsource(routing).casefold()
    forbidden_terms = (
        "question_id",
        "question_text",
        "qrels",
        "relevance_grade",
        "ranking_position",
        "retrieval_score",
        "benchmark_metric",
        "threshold",
    )

    assert all(term not in source for term in forbidden_terms)
