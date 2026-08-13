"""Retrieval evaluation harness.

Runs the baselines of `EVALUATION_PLAN` section 6.1 over one frozen corpus
under the controlled variables of section 6.2, and saves every raw artifact
section 6.3 requires: per-query rankings, component scores, component ranks,
fused rank, latency, configuration, and warnings.

The design rule this enforces is `V1-NFR-008`: no summary number is emitted
without the raw per-query record and the exact configuration that produced it,
so any reported figure can be recomputed from saved artifacts alone.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medevidence.retrieval.core import (
    BM25Index,
    DenseIndex,
    component_ranks,
    reciprocal_rank_fusion,
)

from .datasets import EvaluationDataset, relevance_grade_histogram
from .metrics import aggregate, evaluate_query

HARNESS_VERSION = "m2.harness.v1"


@dataclass(frozen=True)
class RunConfig:
    """Exact experiment configuration.

    Not an approved configuration: decision gate `ME-000C` is open. These are
    the values actually used, recorded so the run can be reproduced.
    """

    bm25_k1: float = 0.9
    bm25_b: float = 0.4
    tokenizer: str = "unicode_lower_alnum_v1"
    embedding_method: str = "tfidf_svd_v1"
    embedding_dimensions: int = 256
    rrf_k: int = 60
    candidate_limit: int = 100
    final_limit: int = 10
    cutoffs: Sequence[int] = (5, 10)
    mrr_k: int = 10
    ndcg_k: int = 10
    relevant_grade_min: int = 1
    random_state: int = 0

    def config_id(self) -> str:
        """Deterministic identity of this configuration."""

        payload = json.dumps(asdict(self), sort_keys=True, default=list)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class QueryRecord:
    """One query under one mode, with everything needed to recompute it."""

    query_id: str
    mode: str
    ranked_ids: list[str]
    scores: list[float]
    component_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    component_ranks: dict[str, dict[str, int]] = field(default_factory=dict)
    latency_ms: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ModeResult:
    """Aggregated outcome for one baseline."""

    mode: str
    summary: dict[str, float]
    records: list[QueryRecord]


class RetrievalHarness:
    """Builds one index set over a frozen corpus and evaluates every baseline.

    All modes share the same corpus, tokenizer, judgments, and limits — the
    controlled variables of section 6.2 — so differences between modes are
    attributable to the retrieval method rather than to the setup.
    """

    def __init__(self, dataset: EvaluationDataset, config: RunConfig | None = None) -> None:
        self.dataset = dataset
        self.config = config or RunConfig()
        self.doc_ids: list[str] = sorted(dataset.corpus)
        self.documents: list[str] = [dataset.document_text(doc_id) for doc_id in self.doc_ids]
        self._build_seconds: dict[str, float] = {}

        started = time.perf_counter()
        self.bm25 = BM25Index(
            self.doc_ids,
            self.documents,
            k1=self.config.bm25_k1,
            b=self.config.bm25_b,
        )
        self._build_seconds["sparse"] = time.perf_counter() - started

        started = time.perf_counter()
        self.dense = DenseIndex(
            self.doc_ids,
            self.documents,
            dimensions=self.config.embedding_dimensions,
        )
        self._build_seconds["dense"] = time.perf_counter() - started

    @property
    def corpus_id(self) -> str:
        """Content identity of the exact indexed corpus."""

        digest = hashlib.sha256()
        for doc_id, text in zip(self.doc_ids, self.documents, strict=True):
            digest.update(doc_id.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(text.encode("utf-8"))
            digest.update(b"\x00")
        return "sha256:" + digest.hexdigest()

    def _search(self, mode: str, query: str) -> tuple[list[tuple[str, float]], dict, dict]:
        limit = self.config.candidate_limit
        if mode == "sparse":
            ranking = self.bm25.search(query, limit)
            return ranking, {"sparse": dict(ranking)}, {"sparse": component_ranks(ranking)}
        if mode == "dense":
            ranking = self.dense.search(query, limit)
            return ranking, {"dense": dict(ranking)}, {"dense": component_ranks(ranking)}
        if mode == "hybrid_rrf":
            sparse = self.bm25.search(query, limit)
            dense = self.dense.search(query, limit)
            fused = reciprocal_rank_fusion([sparse, dense], k=self.config.rrf_k, limit=limit)
            return (
                fused,
                {"sparse": dict(sparse), "dense": dict(dense)},
                {"sparse": component_ranks(sparse), "dense": component_ranks(dense)},
            )
        raise ValueError(f"unsupported mode {mode!r}")

    def run_mode(self, mode: str) -> ModeResult:
        """Evaluate every judged query under one baseline."""

        records: list[QueryRecord] = []
        latencies: list[float] = []
        per_query: dict[str, dict[str, float]] = {}

        for query_id in self.dataset.judged_queries:
            text = self.dataset.queries[query_id]
            started = time.perf_counter()
            ranking, comp_scores, comp_ranks = self._search(mode, text)
            latency_ms = (time.perf_counter() - started) * 1000.0

            final = ranking[: self.config.final_limit]
            ranked_ids = [doc_id for doc_id, _score in final]
            judgments = self.dataset.qrels.get(query_id, {})
            scores = evaluate_query(
                ranked_ids,
                judgments,
                cutoffs=self.config.cutoffs,
                mrr_k=self.config.mrr_k,
                ndcg_k=self.config.ndcg_k,
                grade_min=self.config.relevant_grade_min,
            )
            kept = set(ranked_ids)
            records.append(
                QueryRecord(
                    query_id=query_id,
                    mode=mode,
                    ranked_ids=ranked_ids,
                    scores=[float(score) for _doc, score in final],
                    component_scores={
                        name: {d: float(s) for d, s in values.items() if d in kept}
                        for name, values in comp_scores.items()
                    },
                    component_ranks={
                        name: {d: r for d, r in values.items() if d in kept}
                        for name, values in comp_ranks.items()
                    },
                    latency_ms=latency_ms,
                    metrics=scores,
                )
            )
            latencies.append(latency_ms)
            per_query[query_id] = scores

        summary = aggregate(per_query, latencies)
        summary["index_build_seconds"] = self._build_seconds.get(
            mode, self._build_seconds.get("sparse", 0.0) + self._build_seconds.get("dense", 0.0)
        )
        return ModeResult(mode=mode, summary=summary, records=records)

    def run_all(
        self, modes: Sequence[str] = ("sparse", "dense", "hybrid_rrf")
    ) -> dict[str, ModeResult]:
        """Evaluate every requested baseline over the same frozen corpus."""

        return {mode: self.run_mode(mode) for mode in modes}

    def environment(self) -> dict[str, str]:
        """Recorded hardware and software context (section 6.2)."""

        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "harness_version": HARNESS_VERSION,
        }

    def save(self, results: dict[str, ModeResult], output_dir: str | Path) -> Path:
        """Write summary and per-query raw artifacts; return the run directory."""

        output_dir = Path(output_dir)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = output_dir / f"run-{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "harness_version": HARNESS_VERSION,
            "executed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_id": self.dataset.dataset_id,
            "dataset_source": self.dataset.source_path,
            "dataset_summary": self.dataset.summary(),
            "grade_histogram": {
                str(g): c for g, c in relevance_grade_histogram(self.dataset.qrels).items()
            },
            "dataset_warnings": list(self.dataset.warnings),
            "corpus_id": self.corpus_id,
            "config": asdict(self.config),
            "config_id": self.config.config_id(),
            "environment": self.environment(),
            "index_build_seconds": self._build_seconds,
            "dense_dimensions_actual": self.dense.dimensions,
            "modes": sorted(results),
            "summary": {mode: result.summary for mode, result in results.items()},
            "approval_status": (
                "EXPERIMENT ONLY. ME-000C is open; no value here is an approved "
                "configuration. No release threshold is proposed or implied."
            ),
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )

        for mode, result in results.items():
            path = run_dir / f"per-query-{mode}.jsonl"
            with path.open("w", encoding="utf-8") as handle:
                for record in result.records:
                    handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
        return run_dir
