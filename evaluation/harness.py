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

import base64
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NATIVE_THREAD_ENVIRONMENT_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _set_native_thread_environment() -> None:
    """Set native thread controls before importing the numerical stack."""

    for name in NATIVE_THREAD_ENVIRONMENT_VARIABLES:
        os.environ[name] = "1"


_set_native_thread_environment()

for _native_module in (
    "numpy",
    "scipy",
    "sklearn.decomposition",
    "sklearn.feature_extraction.text",
):
    importlib.import_module(_native_module)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medevidence.retrieval.core import (  # noqa: E402
    BM25Index,
    DenseIndex,
    component_ranks,
    reciprocal_rank_fusion,
)

from .datasets import EvaluationDataset, relevance_grade_histogram  # noqa: E402
from .metrics import aggregate, evaluate_query  # noqa: E402

HARNESS_VERSION = "m2.harness.v1"
NATIVE_THREAD_USER_APIS = frozenset({"blas", "openmp"})
MODE_DISPLAY_NAMES = {
    "sparse": "BM25",
    "dense": "classical_lsi_dense",
    "hybrid_rrf": "rrf_bm25_lsi",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_git_revision() -> str:
    """Return the exact repository revision, failing rather than guessing."""

    repository_root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("unable to determine repository Git revision") from error
    revision = completed.stdout.strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise RuntimeError("repository Git revision is not a full SHA-1 commit identity")
    return revision


def _git_bytes(*arguments: str) -> bytes:
    repository_root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"unable to capture repository source state: git {arguments}") from error
    return completed.stdout


def _source_state() -> tuple[bytes, bytes, dict[str, Any]]:
    """Capture the exact dirty execution source relative to immutable HEAD."""

    revision = _repository_git_revision()
    patch = _git_bytes("diff", "--binary", "--full-index", "HEAD", "--", ".")
    changed_paths = sorted(
        path.decode("utf-8")
        for path in _git_bytes(
            "diff", "--name-only", "--diff-filter=ACDMRTUXB", "-z", "HEAD", "--", "."
        ).split(b"\0")
        if path
    )
    repository_root = Path(__file__).resolve().parents[1]
    untracked_paths = sorted(
        path.decode("utf-8")
        for path in _git_bytes("ls-files", "-z", "--others", "--exclude-standard").split(b"\0")
        if path
    )
    untracked = []
    untracked_snapshot_files = []
    for relative in untracked_paths:
        path = repository_root / relative
        if not path.is_file():
            raise RuntimeError(f"untracked source inventory entry is not a file: {relative}")
        untracked.append(
            {
                "path": relative.replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
        untracked_snapshot_files.append(
            {
                "path": relative.replace("\\", "/"),
                "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        )
    patch_sha256 = hashlib.sha256(patch).hexdigest()
    identity_payload = {
        "head": revision,
        "tracked_patch_sha256": patch_sha256,
        "tracked_changed_paths": changed_paths,
        "untracked_files": untracked,
    }
    state_bytes = json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
    untracked_snapshot = (
        json.dumps(
            {
                "format": "medevidence_untracked_source_snapshot_v1",
                "head": revision,
                "files": untracked_snapshot_files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return (
        patch,
        untracked_snapshot,
        {
            **identity_payload,
            "tracked_patch_bytes": len(patch),
            "untracked_snapshot_sha256": hashlib.sha256(untracked_snapshot).hexdigest(),
            "untracked_snapshot_bytes": len(untracked_snapshot),
            "source_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
            "reconstruction": (
                "HEAD plus source.patch; untracked files are identity-bound by "
                "path, size, and SHA-256"
            ),
        },
    )


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"required benchmark dependency {name!r} is not installed") from error


def _native_thread_environment() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in NATIVE_THREAD_ENVIRONMENT_VARIABLES}


def _native_pool_identity(pool: dict[str, Any]) -> dict[str, str | int | None]:
    filepath = pool.get("filepath")
    return {
        "user_api": str(pool.get("user_api", "unknown")),
        "internal_api": str(pool.get("internal_api", "unknown")),
        "library_id": str(pool.get("prefix") or "unknown"),
        "library_file": Path(str(filepath)).name if filepath else None,
        "version": str(pool["version"]) if pool.get("version") is not None else None,
        "num_threads": (
            pool.get("num_threads") if isinstance(pool.get("num_threads"), int) else None
        ),
    }


def _relevant_native_pools(pools: list[dict[str, Any]]) -> list[dict[str, str | int | None]]:
    return [
        _native_pool_identity(pool)
        for pool in pools
        if pool.get("user_api") in NATIVE_THREAD_USER_APIS
    ]


def _require_single_thread_pools(pools: list[dict[str, str | int | None]], *, context: str) -> None:
    if not pools:
        raise RuntimeError(f"no BLAS/OpenMP native thread pools discovered in {context}")
    mismatches = [pool for pool in pools if pool["num_threads"] != 1]
    if mismatches:
        identities = ", ".join(
            f"{pool['user_api']}:{pool['library_id']}={pool['num_threads']}" for pool in mismatches
        )
        raise RuntimeError(f"native thread limit mismatch in {context}: {identities}")


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
    query_concurrency: int = 1
    blas_threads: int = 1

    def __post_init__(self) -> None:
        if self.candidate_limit < self.final_limit or self.final_limit < 1:
            raise ValueError(
                "candidate_limit must be at least final_limit and both must be positive"
            )
        if self.query_concurrency != 1:
            raise ValueError("this pilot requires serial query execution")
        if self.blas_threads != 1:
            raise ValueError("this pilot requires one BLAS thread")

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
    candidate_ranked_ids: list[str] = field(default_factory=list)
    candidate_scores: list[float] = field(default_factory=list)
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
    build_timing: dict[str, float | str]


class RetrievalHarness:
    """Builds one index set over a frozen corpus and evaluates every baseline.

    All modes share the same corpus, tokenizer, judgments, and limits — the
    controlled variables of section 6.2 — so differences between modes are
    attributable to the retrieval method rather than to the setup.
    """

    def __init__(self, dataset: EvaluationDataset, config: RunConfig | None = None) -> None:
        if not dataset.judged_queries:
            raise ValueError("evaluation requires at least one judged query")
        self.dataset = dataset
        self.config = config or RunConfig()
        self.doc_ids: list[str] = sorted(dataset.corpus)
        self.documents: list[str] = [dataset.document_text(doc_id) for doc_id in self.doc_ids]
        self._build_seconds: dict[str, float] = {}
        self._native_thread_build_observations: list[dict[str, Any]] = []
        self._native_thread_mode_observations: dict[str, list[dict[str, Any]]] = {}

        from threadpoolctl import threadpool_info  # type: ignore[import-untyped]

        self._native_pools_discovered_before_limits = _relevant_native_pools(threadpool_info())
        if not self._native_pools_discovered_before_limits:
            raise RuntimeError("native BLAS/OpenMP stack is not discoverable before limiting")

        with self._native_thread_context("index_build") as build_observations:
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
                random_state=self.config.random_state,
            )
            self._build_seconds["dense"] = time.perf_counter() - started
        self._native_thread_build_observations = build_observations

    def _capture_native_thread_observation(self, context: str, boundary: str) -> dict[str, Any]:
        from threadpoolctl import threadpool_info  # type: ignore[import-untyped]

        pools = _relevant_native_pools(threadpool_info())
        _require_single_thread_pools(pools, context=f"{context}:{boundary}")
        return {"context": context, "boundary": boundary, "pools": pools}

    @contextmanager
    def _native_thread_context(self, context: str) -> Iterator[list[dict[str, Any]]]:
        from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

        with threadpool_limits(limits=self.config.blas_threads):
            staged = [self._capture_native_thread_observation(context, "entry")]
            yield staged
            staged.append(self._capture_native_thread_observation(context, "exit"))

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

    def _search(
        self, mode: str, query: str
    ) -> tuple[
        list[tuple[str, float]],
        dict[str, dict[str, float]],
        dict[str, dict[str, int]],
    ]:
        limit = self.config.candidate_limit
        return self._search_with_thread_limit(mode, query, limit)

    def _search_with_thread_limit(
        self, mode: str, query: str, limit: int
    ) -> tuple[
        list[tuple[str, float]],
        dict[str, dict[str, float]],
        dict[str, dict[str, int]],
    ]:
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

        if mode not in MODE_DISPLAY_NAMES:
            raise ValueError(f"unsupported mode {mode!r}")
        records: list[QueryRecord] = []
        latencies: list[float] = []
        per_query: dict[str, dict[str, float]] = {}

        with self._native_thread_context(f"query_latency:{mode}") as mode_observations:
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
                records.append(
                    QueryRecord(
                        query_id=query_id,
                        mode=mode,
                        ranked_ids=ranked_ids,
                        scores=[float(score) for _doc, score in final],
                        candidate_ranked_ids=[doc_id for doc_id, _score in ranking],
                        candidate_scores=[float(score) for _doc, score in ranking],
                        component_scores={
                            name: {d: float(s) for d, s in values.items()}
                            for name, values in comp_scores.items()
                        },
                        component_ranks={name: dict(values) for name, values in comp_ranks.items()},
                        latency_ms=latency_ms,
                        metrics=scores,
                    )
                )
                latencies.append(latency_ms)
                per_query[query_id] = scores

        summary = aggregate(per_query, latencies)
        if mode == "hybrid_rrf":
            build_timing: dict[str, float | str] = {
                "seconds": self._build_seconds["sparse"] + self._build_seconds["dense"],
                "kind": "derived_sum_of_measured_sparse_and_dense_builds",
            }
        else:
            build_timing = {
                "seconds": self._build_seconds[mode],
                "kind": "measured_index_build",
            }
        result = ModeResult(mode=mode, summary=summary, records=records, build_timing=build_timing)
        self._validate_result(mode, result)
        self._native_thread_mode_observations[mode] = mode_observations
        return result

    def run_all(
        self, modes: Sequence[str] = ("sparse", "dense", "hybrid_rrf")
    ) -> dict[str, ModeResult]:
        """Evaluate every requested baseline over the same frozen corpus."""

        return {mode: self.run_mode(mode) for mode in modes}

    def environment(self) -> dict[str, str]:
        """Recorded hardware and software context (section 6.2)."""

        environment = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
            "harness_version": HARNESS_VERSION,
        }
        for distribution in (
            "medevidence",
            "numpy",
            "scikit-learn",
            "scipy",
            "joblib",
            "narwhals",
            "threadpoolctl",
        ):
            environment[f"dependency:{distribution}"] = _distribution_version(distribution)
        return environment

    def _validate_result(self, mode: str, result: ModeResult) -> None:
        """Fail closed unless saved evidence exactly matches the executed dataset."""

        if mode not in MODE_DISPLAY_NAMES or result.mode != mode:
            raise ValueError(f"result mode {mode!r} is inconsistent or unsupported")
        expected_queries = self.dataset.judged_queries
        actual_queries = [record.query_id for record in result.records]
        if len(actual_queries) != len(set(actual_queries)):
            raise ValueError(f"result mode {mode!r} contains duplicate query records")
        if sorted(actual_queries) != expected_queries:
            raise ValueError(f"result mode {mode!r} does not exactly cover judged queries")

        recomputed_metrics: dict[str, dict[str, float]] = {}
        latencies: list[float] = []
        for record in result.records:
            if record.mode != mode:
                raise ValueError(f"query {record.query_id!r} has inconsistent mode")
            if len(record.ranked_ids) != len(record.scores):
                raise ValueError(f"query {record.query_id!r} final ids/scores differ in length")
            if len(record.candidate_ranked_ids) != len(record.candidate_scores):
                raise ValueError(f"query {record.query_id!r} candidate ids/scores differ in length")
            if len(record.candidate_ranked_ids) > self.config.candidate_limit:
                raise ValueError(f"query {record.query_id!r} exceeds candidate_limit")
            if len(set(record.candidate_ranked_ids)) != len(record.candidate_ranked_ids):
                raise ValueError(f"query {record.query_id!r} has duplicate candidates")
            if record.ranked_ids != record.candidate_ranked_ids[: self.config.final_limit]:
                raise ValueError(
                    f"query {record.query_id!r} final ranking is not the candidate prefix"
                )
            if record.scores != record.candidate_scores[: self.config.final_limit]:
                raise ValueError(
                    f"query {record.query_id!r} final scores are not the candidate prefix"
                )
            for component, ranks in record.component_ranks.items():
                scores = record.component_scores.get(component)
                if scores is None or set(scores) != set(ranks):
                    raise ValueError(
                        f"query {record.query_id!r} component {component!r} is not reconstructible"
                    )
                if sorted(ranks.values()) != list(range(1, len(ranks) + 1)):
                    raise ValueError(
                        f"query {record.query_id!r} component {component!r} "
                        "ranks are not contiguous"
                    )
            if mode == "hybrid_rrf":
                component_rankings = []
                for component in ("sparse", "dense"):
                    ranks = record.component_ranks.get(component, {})
                    scores = record.component_scores.get(component, {})
                    component_rankings.append(
                        [
                            (doc_id, scores[doc_id])
                            for doc_id in sorted(ranks, key=lambda item: ranks[item])
                        ]
                    )
                rebuilt = reciprocal_rank_fusion(
                    component_rankings,
                    k=self.config.rrf_k,
                    limit=self.config.candidate_limit,
                )
                if [doc_id for doc_id, _score in rebuilt] != record.candidate_ranked_ids:
                    raise ValueError(
                        f"query {record.query_id!r} RRF ranking cannot be reconstructed"
                    )
                if any(
                    not math.isclose(score, expected, rel_tol=0.0, abs_tol=1e-15)
                    for score, (_doc_id, expected) in zip(
                        record.candidate_scores, rebuilt, strict=True
                    )
                ):
                    raise ValueError(
                        f"query {record.query_id!r} RRF scores cannot be reconstructed"
                    )

            metrics = evaluate_query(
                record.ranked_ids,
                self.dataset.qrels[record.query_id],
                cutoffs=self.config.cutoffs,
                mrr_k=self.config.mrr_k,
                ndcg_k=self.config.ndcg_k,
                grade_min=self.config.relevant_grade_min,
            )
            if metrics != record.metrics:
                raise ValueError(f"query {record.query_id!r} metrics do not recompute")
            recomputed_metrics[record.query_id] = metrics
            latencies.append(record.latency_ms)

        summary = aggregate(recomputed_metrics, latencies)
        if summary != result.summary:
            raise ValueError(f"result mode {mode!r} aggregate summary does not recompute")

    @staticmethod
    def _artifact_identity(path: Path) -> dict[str, str | int]:
        return {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }

    def _validate_native_thread_evidence(self, result_modes: set[str]) -> list[dict[str, Any]]:
        expected_environment = {name: "1" for name in NATIVE_THREAD_ENVIRONMENT_VARIABLES}
        if _native_thread_environment() != expected_environment:
            raise RuntimeError("native thread environment changed before artifact persistence")

        selected_observations = list(self._native_thread_build_observations)
        for mode in sorted(result_modes):
            selected_observations.extend(self._native_thread_mode_observations.get(mode, ()))

        expected_contexts = [
            "index_build",
            *(f"query_latency:{mode}" for mode in sorted(result_modes)),
        ]
        actual_contexts = [
            (str(observation["context"]), str(observation["boundary"]))
            for observation in selected_observations
        ]
        expected_context_boundaries = [
            (context, boundary) for context in expected_contexts for boundary in ("entry", "exit")
        ]
        if actual_contexts != expected_context_boundaries:
            raise RuntimeError("native thread observations do not exactly cover selected execution")
        for observation in selected_observations:
            pools = observation.get("pools")
            if not isinstance(pools, list):
                raise RuntimeError("native thread observation pools are malformed")
            _require_single_thread_pools(
                pools,
                context=f"{observation.get('context')}:{observation.get('boundary')}",
            )
        return selected_observations

    @staticmethod
    def _runtime_provenance(git_revision: str) -> dict[str, Any]:
        repository_root = Path(__file__).resolve().parents[1]
        lock_path = repository_root / "uv.lock"
        if not lock_path.is_file():
            raise RuntimeError("uv.lock is required for benchmark provenance")
        return {
            "python": sys.version.split()[0],
            "numpy": _distribution_version("numpy"),
            "scikit_learn": _distribution_version("scikit-learn"),
            "uv_lock": {
                "path": "uv.lock",
                "bytes": lock_path.stat().st_size,
                "sha256": _sha256_file(lock_path),
            },
            "git_revision": git_revision,
            "platform": platform.platform(),
        }

    def save(
        self,
        results: dict[str, ModeResult],
        output_dir: str | Path,
        *,
        run_id: str | None = None,
    ) -> Path:
        """Write summary and per-query raw artifacts; return the run directory."""

        if not self.dataset.dataset_source:
            raise ValueError("dataset source identity is required before saving benchmark results")
        if self.dataset.distribution is None:
            raise ValueError(
                "downloaded distribution identity is required before saving benchmark results"
            )
        if not self.dataset.consumed_files:
            raise ValueError("consumed dataset file identities are required")
        if not results:
            raise ValueError("at least one mode result is required")
        for mode, result in sorted(results.items()):
            self._validate_result(mode, result)
        selected_native_thread_observations = self._validate_native_thread_evidence(set(results))
        source_patch, untracked_snapshot, source_state = _source_state()
        git_revision = source_state["head"]
        environment = self.environment()
        runtime_provenance = self._runtime_provenance(str(git_revision))
        output_dir = Path(output_dir)
        if run_id is None:
            run_id = "run-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
            raise ValueError("run_id must be one non-empty path segment")
        run_dir = output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        output_artifacts: list[dict[str, str | int]] = []
        patch_path = run_dir / "source.patch"
        patch_path.write_bytes(source_patch)
        source_state_path = run_dir / "source-state.json"
        source_state_path.write_text(
            json.dumps(source_state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        untracked_snapshot_path = run_dir / "source-untracked-snapshot.json"
        untracked_snapshot_path.write_bytes(untracked_snapshot)
        output_artifacts.extend(
            [
                self._artifact_identity(patch_path),
                self._artifact_identity(untracked_snapshot_path),
                self._artifact_identity(source_state_path),
            ]
        )
        for mode, result in sorted(results.items()):
            path = run_dir / f"per-query-{mode}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for record in result.records:
                    handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")
            output_artifacts.append(self._artifact_identity(path))

        distribution = asdict(self.dataset.distribution) if self.dataset.distribution else None
        manifest = {
            "harness_version": HARNESS_VERSION,
            "executed_at_utc": datetime.now(UTC).isoformat(),
            "dataset_id": self.dataset.dataset_id,
            "dataset_name": self.dataset.dataset_id,
            "dataset_source": self.dataset.dataset_source,
            "dataset_path": self.dataset.source_path,
            "distribution_identity": distribution,
            "consumed_files": [asdict(identity) for identity in self.dataset.consumed_files],
            "dataset_summary": self.dataset.summary(),
            "grade_histogram": {
                str(g): c for g, c in relevance_grade_histogram(self.dataset.qrels).items()
            },
            "dataset_warnings": list(self.dataset.warnings),
            "corpus_id": self.corpus_id,
            "config": asdict(self.config),
            "retrieval_configuration": asdict(self.config),
            "config_id": self.config.config_id(),
            "environment": environment,
            "repository_git_revision": git_revision,
            "repository_source_state": source_state,
            "runtime_provenance": runtime_provenance,
            "random_seed_actual": self.config.random_state,
            "build_index_timing": {
                mode: result.build_timing for mode, result in sorted(results.items())
            },
            "execution_policy": {
                "query_execution": "serial_single_process",
                "query_concurrency": self.config.query_concurrency,
                "native_threading": {
                    "requested_limit": self.config.blas_threads,
                    "environment": _native_thread_environment(),
                    "discovered_pools_before_limits": self._native_pools_discovered_before_limits,
                    "observed_in_context_pools": selected_native_thread_observations,
                },
                "limitation": (
                    "OS scheduling, filesystem cache, and unrelated host load are uncontrolled; "
                    "latency is local wall-clock evidence, not a production SLO."
                ),
            },
            "dense_dimensions_actual": self.dense.dimensions,
            "modes": sorted(results),
            "mode_display_names": {mode: MODE_DISPLAY_NAMES[mode] for mode in sorted(results)},
            "summary": {mode: result.summary for mode, result in results.items()},
            "output_artifacts": output_artifacts,
            "manifest_integrity": {
                "strategy": "external_sha256_sidecar",
                "sidecar": "manifest.sha256",
            },
            "approval_status": (
                "EXPERIMENT ONLY. The BM25, classical LSI, and RRF(BM25, LSI) pilot "
                "exception applies only to this M2 benchmark. ME-000C remains open for "
                "production/release indexes, Qdrant, transformer dense retrieval, "
                "rerankers, and later retrieval architecture."
            ),
        }
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (run_dir / "manifest.sha256").write_text(
            f"{_sha256_file(manifest_path)}  {manifest_path.name}\n",
            encoding="ascii",
            newline="\n",
        )
        return run_dir
