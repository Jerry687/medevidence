"""Retrieval metrics required by `EVALUATION_PLAN` section 6.3.

Definitions follow the TREC/BEIR conventions so that numbers produced here are
comparable to published results:

- `DCG@k = sum_i (2^rel_i - 1) / log2(i + 1)` over 1-based positions;
- `nDCG@k = DCG@k / IDCG@k`, where `IDCG@k` sorts all judged grades
  descending; `nDCG` is `0.0` when no positive grade exists;
- `Recall@k` divides by the count of *all* judged-relevant documents, not by
  the number retrieved, so truncating the candidate list can only lower it;
- `MRR@k` is `0.0` when no relevant document appears in the top `k`.

Grade semantics (`0/1/2`) come from the adjudication guide, not from this
module. `relevant_grade_min` therefore parameterizes what counts as relevant
for the binary metrics; the project's "directly relevant" wording may map to
grade `2` once `M2-ADJUDICATION` designates an adjudicator.

This module is pure: no I/O, no project imports, no global state.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

DEFAULT_RELEVANT_GRADE_MIN = 1


def _relevant_ids(judgments: Mapping[str, int], grade_min: int) -> set:
    return {doc_id for doc_id, grade in judgments.items() if grade >= grade_min}


def precision_at_k(
    ranked_ids: Sequence[str],
    judgments: Mapping[str, int],
    k: int,
    *,
    grade_min: int = DEFAULT_RELEVANT_GRADE_MIN,
) -> float:
    """Relevant results in the top `k` divided by `k`."""

    if k < 1:
        raise ValueError("k must be positive")
    relevant = _relevant_ids(judgments, grade_min)
    hits = sum(1 for doc_id in ranked_ids[:k] if doc_id in relevant)
    return hits / k


def recall_at_k(
    ranked_ids: Sequence[str],
    judgments: Mapping[str, int],
    k: int,
    *,
    grade_min: int = DEFAULT_RELEVANT_GRADE_MIN,
) -> float:
    """Relevant results in the top `k` divided by all judged-relevant ids.

    Returns `0.0` when the query has no relevant judgment, rather than
    dividing by zero; such queries should normally be excluded upstream.
    """

    if k < 1:
        raise ValueError("k must be positive")
    relevant = _relevant_ids(judgments, grade_min)
    if not relevant:
        return 0.0
    hits = sum(1 for doc_id in ranked_ids[:k] if doc_id in relevant)
    return hits / len(relevant)


def reciprocal_rank_at_k(
    ranked_ids: Sequence[str],
    judgments: Mapping[str, int],
    k: int,
    *,
    grade_min: int = DEFAULT_RELEVANT_GRADE_MIN,
) -> float:
    """Reciprocal rank of the first relevant result within the top `k`."""

    if k < 1:
        raise ValueError("k must be positive")
    relevant = _relevant_ids(judgments, grade_min)
    for position, doc_id in enumerate(ranked_ids[:k], start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


def dcg_at_k(ranked_ids: Sequence[str], judgments: Mapping[str, int], k: int) -> float:
    """Discounted cumulative gain with exponential gain `2^rel - 1`."""

    if k < 1:
        raise ValueError("k must be positive")
    total = 0.0
    for position, doc_id in enumerate(ranked_ids[:k], start=1):
        grade = judgments.get(doc_id, 0)
        if grade > 0:
            total += (2.0**grade - 1.0) / math.log2(position + 1)
    return total


def ndcg_at_k(ranked_ids: Sequence[str], judgments: Mapping[str, int], k: int) -> float:
    """Normalized DCG against the ideal ordering of all judged grades."""

    ideal_grades = sorted((g for g in judgments.values() if g > 0), reverse=True)[:k]
    ideal = sum(
        (2.0**grade - 1.0) / math.log2(position + 1)
        for position, grade in enumerate(ideal_grades, start=1)
    )
    if ideal == 0.0:
        return 0.0
    return dcg_at_k(ranked_ids, judgments, k) / ideal


def percentile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolated percentile; `fraction` in `[0, 1]`."""

    if not values:
        raise ValueError("percentile of an empty sequence is undefined")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be within [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[int(position)])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def aggregate(
    per_query: Mapping[str, Mapping[str, float]],
    latencies_ms: Iterable[float] = (),
) -> dict[str, float]:
    """Mean each metric across queries and summarize latency.

    Uses the macro average — every query counts once regardless of how many
    relevant documents it has — which is the TREC convention.
    """

    if not per_query:
        return {}
    names: list[str] = sorted({name for scores in per_query.values() for name in scores})
    summary: dict[str, float] = {}
    for name in names:
        values = [float(scores[name]) for scores in per_query.values() if name in scores]
        summary[name] = sum(values) / len(values) if values else 0.0
    summary["queries"] = float(len(per_query))
    latency = [float(value) for value in latencies_ms]
    if latency:
        summary["latency_p50_ms"] = percentile(latency, 0.50)
        summary["latency_p95_ms"] = percentile(latency, 0.95)
        summary["latency_mean_ms"] = sum(latency) / len(latency)
    return summary


def evaluate_query(
    ranked_ids: Sequence[str],
    judgments: Mapping[str, int],
    *,
    cutoffs: Sequence[int] = (5, 10),
    mrr_k: int = 10,
    ndcg_k: int = 10,
    grade_min: int = DEFAULT_RELEVANT_GRADE_MIN,
) -> dict[str, float]:
    """Compute the reported metric set for a single query."""

    scores: dict[str, float] = {}
    for k in cutoffs:
        scores[f"recall@{k}"] = recall_at_k(ranked_ids, judgments, k, grade_min=grade_min)
        scores[f"precision@{k}"] = precision_at_k(ranked_ids, judgments, k, grade_min=grade_min)
    scores[f"mrr@{mrr_k}"] = reciprocal_rank_at_k(ranked_ids, judgments, mrr_k, grade_min=grade_min)
    scores[f"ndcg@{ndcg_k}"] = ndcg_at_k(ranked_ids, judgments, ndcg_k)
    return scores
