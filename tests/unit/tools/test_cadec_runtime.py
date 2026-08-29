"""Pure contract and planning tests for the CADEC tool boundary."""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

import pytest

import medevidence.tools.cadec_runtime as runtime
from medevidence.domain import (
    CADEC_ARCHIVE_SHA256,
    CADEC_EXTERNAL_MANIFEST_SHA256,
    AdverseEventConcept,
    ComparisonIntent,
    DrugConcept,
    InclusiveDateRange,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)


def _scope(
    *,
    drugs: tuple[tuple[str, str], ...] = (("drug-a", "Alpha"), ("drug-b", "Beta")),
    reactions: tuple[tuple[str, str], ...] = (("event-a", "Nausea"),),
    sources: tuple[SourceType, ...] = (SourceType.CADEC,),
    max_query_characters: int = 512,
) -> ResearchScope:
    return ResearchScope.create(
        drugs=tuple(DrugConcept(concept_id=key, preferred_term=term) for key, term in drugs),
        adverse_reactions=tuple(
            AdverseEventConcept(concept_id=key, preferred_term=term) for key, term in reactions
        ),
        date_range=InclusiveDateRange(start_date=date(2025, 1, 1), end_date=date(2025, 1, 2)),
        selected_sources=sources,
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=max_query_characters,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def test_plan_is_exact_deterministic_and_performs_zero_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pure CADEC planning must perform zero I/O")

    monkeypatch.setattr(Path, "open", forbidden)
    first = runtime.plan_cadec_local_search(scope)
    second = runtime.plan_cadec_local_search(scope)

    assert first == second
    assert first.scope_id == scope.scope_id
    assert first.query == "Alpha Beta Nausea"
    assert first.archive_sha256 == CADEC_ARCHIVE_SHA256
    assert first.manifest_sha256 == CADEC_EXTERNAL_MANIFEST_SHA256
    assert (first.bm25_k1, first.bm25_b, first.result_limit) == (0.9, 0.4, 20)
    assert first.tokenizer == "unicode_lower_alnum_v1"


@pytest.mark.parametrize(
    "changes",
    [
        {"query": "foreign query"},
        {"query_id": "foreign-query-id"},
        {"archive_sha256": "1" * 64},
        {"manifest_sha256": "2" * 64},
        {"bm25_k1": 1.0},
        {"bm25_b": 0.5},
        {"result_limit": 19},
    ],
)
def test_plan_reconstruction_rejects_every_frozen_field_drift(
    changes: dict[str, object],
) -> None:
    scope = _scope()
    drifted = runtime.plan_cadec_local_search(scope).model_copy(update=changes)

    with pytest.raises(runtime.CadecRuntimeError) as raised:
        runtime.reconstruct_cadec_local_search_plan(drifted, scope)

    assert raised.value.code is runtime.CadecRuntimeErrorCode.PLAN_INTEGRITY
    assert raised.value.evidence_refs == ()


def test_query_bound_and_unselected_scope_fail_closed() -> None:
    with pytest.raises(runtime.CadecRuntimeError) as over:
        runtime.plan_cadec_local_search(
            _scope(
                drugs=(("drug-a", "abcd"),),
                reactions=(("event-a", "efgh"),),
                max_query_characters=8,
            )
        )
    assert over.value.code is runtime.CadecRuntimeErrorCode.QUERY_BOUND

    with pytest.raises(runtime.CadecRuntimeError) as unselected:
        runtime.plan_cadec_local_search(_scope(sources=(SourceType.PUBMED,)))
    assert unselected.value.code is runtime.CadecRuntimeErrorCode.INVALID_SCOPE


def test_tool_module_is_contract_only_and_has_no_concrete_runtime_import() -> None:
    source = inspect.getsource(runtime)
    tree = ast.parse(source)
    imported = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }

    assert imported <= {
        "__future__",
        "enum",
        "pydantic",
        "typing",
        "medevidence.domain",
        "medevidence.domain.identifiers",
    }
    assert "medevidence.connectors" not in source
    assert "medevidence.retrieval" not in source
    assert "Path" not in runtime.__dict__
    assert "BM25Index" not in runtime.__dict__
    assert "search_cadec_local_archive" not in runtime.__dict__
    assert "text" not in runtime.CadecDocumentEvidenceRef.model_fields
    assert "text" not in runtime.CadecSearchResult.model_fields
    assert runtime.CadecRuntimeError.evidence_refs == ()
