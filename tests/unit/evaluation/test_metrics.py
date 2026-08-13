"""Unit tests for retrieval metrics, checked against hand-computed values."""

from __future__ import annotations

import math

import pytest
from evaluation.metrics import (
    aggregate,
    dcg_at_k,
    evaluate_query,
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)

RANKED = ["a", "b", "c", "d", "e"]
JUDGMENTS = {"a": 2, "c": 1, "e": 2}


class TestDcgAndNdcg:
    def test_dcg_matches_hand_computation(self) -> None:
        expected = (2**2 - 1) / math.log2(2) + (2**1 - 1) / math.log2(4) + (2**2 - 1) / math.log2(6)
        assert dcg_at_k(RANKED, JUDGMENTS, 5) == pytest.approx(expected)

    def test_ndcg_matches_hand_computation(self) -> None:
        dcg = (2**2 - 1) / math.log2(2) + (2**1 - 1) / math.log2(4) + (2**2 - 1) / math.log2(6)
        idcg = (2**2 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3) + (2**1 - 1) / math.log2(4)
        assert ndcg_at_k(RANKED, JUDGMENTS, 5) == pytest.approx(dcg / idcg)

    def test_ideal_ordering_scores_one(self) -> None:
        assert ndcg_at_k(["a", "e", "c"], JUDGMENTS, 3) == pytest.approx(1.0)

    def test_no_positive_judgment_scores_zero(self) -> None:
        assert ndcg_at_k(["a"], {"a": 0}, 5) == 0.0

    def test_ideal_is_truncated_at_k(self) -> None:
        # Only one of three relevant documents can be counted at k=1.
        assert ndcg_at_k(["a"], JUDGMENTS, 1) == pytest.approx(1.0)

    def test_grade_two_outweighs_two_grade_ones(self) -> None:
        assert (2**2 - 1) > 2 * (2**1 - 1) - 1  # exponential gain is superlinear


class TestBinaryMetrics:
    def test_recall_divides_by_all_relevant(self) -> None:
        assert recall_at_k(RANKED, JUDGMENTS, 2) == pytest.approx(1 / 3)

    def test_recall_reaches_one_when_all_found(self) -> None:
        assert recall_at_k(RANKED, JUDGMENTS, 5) == pytest.approx(1.0)

    def test_precision_divides_by_k(self) -> None:
        assert precision_at_k(RANKED, JUDGMENTS, 5) == pytest.approx(3 / 5)

    def test_reciprocal_rank_uses_first_relevant(self) -> None:
        assert reciprocal_rank_at_k(["x", "y", "c"], JUDGMENTS, 10) == pytest.approx(1 / 3)

    def test_reciprocal_rank_is_zero_outside_the_cutoff(self) -> None:
        assert reciprocal_rank_at_k(["x", "y", "c"], JUDGMENTS, 2) == 0.0

    def test_grade_threshold_changes_the_relevant_set(self) -> None:
        assert precision_at_k(RANKED, JUDGMENTS, 5, grade_min=2) == pytest.approx(2 / 5)

    def test_no_relevant_judgment_returns_zero_not_error(self) -> None:
        assert recall_at_k(["x"], {}, 5) == 0.0

    @pytest.mark.parametrize("function", [recall_at_k, precision_at_k, reciprocal_rank_at_k])
    def test_nonpositive_k_is_rejected(self, function) -> None:
        with pytest.raises(ValueError, match="k must be positive"):
            function(RANKED, JUDGMENTS, 0)


class TestPercentile:
    def test_median_of_even_length(self) -> None:
        assert percentile([float(i) for i in range(1, 11)], 0.5) == pytest.approx(5.5)

    def test_p95_interpolates(self) -> None:
        assert percentile([float(i) for i in range(1, 11)], 0.95) == pytest.approx(9.55)

    def test_single_value(self) -> None:
        assert percentile([4.2], 0.5) == pytest.approx(4.2)

    def test_empty_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty sequence"):
            percentile([], 0.5)

    def test_out_of_range_fraction_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"within \[0, 1\]"):
            percentile([1.0], 1.5)


class TestAggregate:
    def test_macro_averages_each_metric(self) -> None:
        summary = aggregate({"q1": {"recall@5": 1.0}, "q2": {"recall@5": 0.0}})
        assert summary["recall@5"] == pytest.approx(0.5)
        assert summary["queries"] == 2.0

    def test_reports_latency_percentiles(self) -> None:
        summary = aggregate({"q1": {"recall@5": 1.0}}, [10.0, 20.0, 30.0])
        assert summary["latency_p50_ms"] == pytest.approx(20.0)
        assert "latency_p95_ms" in summary

    def test_empty_input_returns_empty(self) -> None:
        assert aggregate({}) == {}


class TestEvaluateQuery:
    def test_reports_the_required_metric_set(self) -> None:
        scores = evaluate_query(RANKED, JUDGMENTS)
        assert {"recall@5", "recall@10", "mrr@10", "ndcg@10"} <= set(scores)
