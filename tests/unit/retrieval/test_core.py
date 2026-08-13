"""Unit tests for the numeric retrieval core."""

from __future__ import annotations

import pytest

from medevidence.retrieval.core import (
    BM25Index,
    DenseIndex,
    component_ranks,
    reciprocal_rank_fusion,
    tokenize,
)

CORPUS = {
    "d1": "Semaglutide nausea and vomiting gastrointestinal adverse events",
    "d2": "Tirzepatide diarrhea and nausea gastrointestinal tolerability",
    "d3": "Metformin renal dosing chronic kidney disease",
    "d4": "Gastrointestinal adverse reactions of GLP-1 receptor agonists",
}
IDS = sorted(CORPUS)
TEXTS = [CORPUS[i] for i in IDS]


class TestTokenize:
    def test_casefolds_and_splits_on_alphanumeric_runs(self) -> None:
        assert tokenize("Semaglutide, 2.4mg — GI!") == ["semaglutide", "2", "4mg", "gi"]

    def test_normalizes_compatibility_forms(self) -> None:
        assert tokenize("ﬁle") == tokenize("file")

    def test_empty_text_yields_no_tokens(self) -> None:
        assert tokenize("   ") == []


class TestBM25Index:
    def test_rejects_mismatched_inputs(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            BM25Index(["a"], ["x", "y"])

    def test_rejects_empty_corpus(self) -> None:
        with pytest.raises(ValueError, match="empty corpus"):
            BM25Index([], [])

    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            BM25Index(["a", "a"], ["x", "y"])

    def test_rejects_nonpositive_limit(self) -> None:
        index = BM25Index(IDS, TEXTS)
        with pytest.raises(ValueError, match="limit must be positive"):
            index.search("nausea", 0)

    def test_ranks_the_on_topic_document_first(self) -> None:
        index = BM25Index(IDS, TEXTS)
        assert index.search("semaglutide nausea", 4)[0][0] == "d1"

    def test_unmatched_query_returns_nothing(self) -> None:
        index = BM25Index(IDS, TEXTS)
        assert index.search("zzzz nonexistent", 4) == []

    def test_respects_the_limit(self) -> None:
        index = BM25Index(IDS, TEXTS)
        assert len(index.search("gastrointestinal", 2)) == 2

    def test_is_deterministic_across_calls(self) -> None:
        index = BM25Index(IDS, TEXTS)
        assert index.search("gastrointestinal nausea", 4) == index.search(
            "gastrointestinal nausea", 4
        )

    def test_ties_break_on_document_id(self) -> None:
        index = BM25Index(["b", "a"], ["same text here", "same text here"])
        assert [doc for doc, _ in index.search("same text here", 2)] == ["a", "b"]

    def test_parameters_are_recorded(self) -> None:
        index = BM25Index(IDS, TEXTS, k1=1.2, b=0.75)
        assert (index.k1, index.b, index.size) == (1.2, 0.75, 4)


class TestDenseIndex:
    def test_rejects_duplicate_ids(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            DenseIndex(["a", "a"], ["x", "y"])

    def test_ranks_the_on_topic_document_first(self) -> None:
        index = DenseIndex(IDS, TEXTS, dimensions=8)
        assert index.search("semaglutide nausea vomiting", 4)[0][0] == "d1"

    def test_dimensionality_is_capped_by_corpus_size(self) -> None:
        index = DenseIndex(IDS, TEXTS, dimensions=4096)
        assert 2 <= index.dimensions <= len(IDS)

    def test_is_deterministic_across_calls(self) -> None:
        index = DenseIndex(IDS, TEXTS, dimensions=8)
        assert index.search("nausea", 4) == index.search("nausea", 4)

    def test_transform_before_fit_is_rejected(self) -> None:
        from medevidence.retrieval.core import TfidfSvdBackend

        with pytest.raises(RuntimeError, match="fit_transform"):
            TfidfSvdBackend().transform(["x"])


class TestReciprocalRankFusion:
    def test_rewards_agreement_between_lists(self) -> None:
        fused = reciprocal_rank_fusion([[("a", 9.0), ("b", 1.0)], [("a", 0.9), ("c", 0.1)]], k=60)
        assert fused[0][0] == "a"

    def test_score_matches_the_definition(self) -> None:
        fused = dict(reciprocal_rank_fusion([[("a", 1.0)], [("a", 1.0)]], k=60))
        assert fused["a"] == pytest.approx(2.0 / 61.0)

    def test_ignores_component_score_scale(self) -> None:
        small = reciprocal_rank_fusion(
            [[("a", 0.001), ("b", 0.0)], [("b", 0.002), ("a", 0.0)]], k=60
        )
        large = reciprocal_rank_fusion(
            [[("a", 1000.0), ("b", 0.0)], [("b", 2000.0), ("a", 0.0)]], k=60
        )
        assert [doc for doc, _ in small] == [doc for doc, _ in large]

    def test_rejects_nonpositive_k(self) -> None:
        with pytest.raises(ValueError, match="k must be positive"):
            reciprocal_rank_fusion([[("a", 1.0)]], k=0)

    def test_applies_the_limit(self) -> None:
        fused = reciprocal_rank_fusion([[("a", 1.0), ("b", 0.5), ("c", 0.1)]], k=60, limit=2)
        assert len(fused) == 2

    def test_ties_break_on_document_id(self) -> None:
        fused = reciprocal_rank_fusion([[("b", 1.0)], [("a", 1.0)]], k=60)
        assert [doc for doc, _ in fused] == ["a", "b"]


class TestComponentRanks:
    def test_positions_are_one_based(self) -> None:
        assert component_ranks([("a", 1.0), ("b", 0.5)]) == {"a": 1, "b": 2}
