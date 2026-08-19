"""Deterministic retrieval-mode selection from validated source scope."""

from __future__ import annotations

from typing import Literal

from medevidence.domain.scope import SourceType
from medevidence.retrieval.contracts import RetrievalMode

type UnsupportedSourceScopeReason = Literal[
    "selected_sources_not_tuple",
    "selected_sources_empty",
    "source_type_invalid",
    "duplicate_source",
    "source_scope_unsupported",
]


class UnsupportedSourceScopeError(ValueError):
    """A selected source scope cannot use the frozen M2-009 routing policy."""

    def __init__(self, reason: UnsupportedSourceScopeReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def select_retrieval_mode(selected_sources: tuple[SourceType, ...]) -> RetrievalMode:
    """Select the frozen mode from structured source classes only.

    ``DENSE`` is a source-neutral backend mode. The M2-009 evaluation binds it
    to the exact approved MedCPT configuration separately.
    """

    if not isinstance(selected_sources, tuple):
        raise UnsupportedSourceScopeError(
            "selected_sources_not_tuple",
            "selected_sources must be a tuple",
        )
    if not selected_sources:
        raise UnsupportedSourceScopeError(
            "selected_sources_empty",
            "selected_sources must not be empty",
        )
    if any(type(source) is not SourceType for source in selected_sources):
        raise UnsupportedSourceScopeError(
            "source_type_invalid",
            "selected_sources must contain only SourceType values",
        )
    if len(frozenset(selected_sources)) != len(selected_sources):
        raise UnsupportedSourceScopeError(
            "duplicate_source",
            "selected_sources must not contain duplicates",
        )

    source_scope = frozenset(selected_sources)
    if source_scope == {SourceType.PUBMED}:
        return RetrievalMode.DENSE
    if source_scope == {SourceType.DAILYMED}:
        return RetrievalMode.SPARSE
    if source_scope == {SourceType.PUBMED, SourceType.DAILYMED}:
        return RetrievalMode.HYBRID_RRF

    raise UnsupportedSourceScopeError(
        "source_scope_unsupported",
        "selected source scope is not supported by the frozen routing policy",
    )
