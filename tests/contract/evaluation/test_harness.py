"""Contract tests for the evaluation harness.

These assert the reproducibility guarantees the evaluation plan depends on:
identical controlled variables across modes, deterministic results, complete
raw artifacts, and no summary emitted without its configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from evaluation.datasets import EvaluationDataset, load_jsonl_dataset
from evaluation.harness import RetrievalHarness, RunConfig
from evaluation.medcpt import MedCPTIndex

from medevidence.retrieval.core import reciprocal_rank_fusion

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/retrieval/harness_smoke.json"
MODES = ("sparse", "dense", "hybrid_rrf")


class StubMedCPTIndex:
    dimensions = 768

    def __init__(self, doc_ids: list[str]) -> None:
        self.doc_ids = doc_ids

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        offset = float(sum(ord(character) for character in query) % 7)
        return [
            (doc_id, float(len(self.doc_ids) - rank) + offset)
            for rank, doc_id in enumerate(sorted(self.doc_ids)[:limit])
        ]

    def provenance(self) -> dict[str, object]:
        return {"schema_version": "offline_fake_medcpt_v1"}

    def runtime_provenance(self) -> dict[str, object]:
        return {
            "pytorch_intra_op_threads_observed": 1,
            "pytorch_inter_op_threads_observed": 1,
            "model_parameter_dtype_observed": {
                "query_encoder": "torch.float32",
                "article_encoder": "torch.float32",
            },
            "query_embedding_dtype_observed": "float32",
            "document_embedding_index_dtype_observed": "float32",
            "dense_index_memory_bytes": 6_144,
            "dense_index_memory_measurement": "numpy.ndarray.nbytes",
            "dense_index_memory_limitation": (
                "Document embedding matrix only; not Python process RSS, allocator overhead, "
                "model memory, or total application memory."
            ),
        }


@pytest.fixture(scope="module")
def harness() -> RetrievalHarness:
    return RetrievalHarness(load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=32))


class TestControlledVariables:
    def test_every_mode_sees_the_same_corpus(self, harness: RetrievalHarness) -> None:
        assert harness.bm25.doc_ids == harness.dense.doc_ids

    def test_corpus_identity_is_content_addressed(self, harness: RetrievalHarness) -> None:
        assert harness.corpus_id.startswith("sha256:")

    def test_every_mode_evaluates_the_same_queries(self, harness: RetrievalHarness) -> None:
        results = harness.run_all(MODES)
        query_sets = {
            mode: [record.query_id for record in result.records] for mode, result in results.items()
        }
        assert len({tuple(ids) for ids in query_sets.values()}) == 1

    def test_runner_sets_native_environment_before_numerical_imports(self) -> None:
        script = """
import builtins
import os
import sys

variables = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
native_roots = {"numpy", "scipy", "sklearn"}
if native_roots.intersection(sys.modules):
    raise AssertionError("numerical stack loaded before import guard")
original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".", 1)[0] in native_roots:
        assert all(os.environ.get(variable) == "1" for variable in variables)
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import evaluation.run_evaluation
assert all(os.environ.get(variable) == "1" for variable in variables)
assert native_roots <= set(sys.modules)
"""
        environment = os.environ.copy()
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "BLIS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            environment[name] = "7"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    def test_native_stack_is_discovered_before_limit_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threadpoolctl

        events: list[str] = []
        original_info = threadpoolctl.threadpool_info
        original_limits = threadpoolctl.threadpool_limits

        def tracked_info() -> list[dict[str, object]]:
            events.append("info")
            return original_info()

        def tracked_limits(*args: object, **kwargs: object) -> object:
            events.append("limits")
            return original_limits(*args, **kwargs)

        monkeypatch.setattr(threadpoolctl, "threadpool_info", tracked_info)
        monkeypatch.setattr(threadpoolctl, "threadpool_limits", tracked_limits)
        RetrievalHarness(load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16))
        assert events[:2] == ["info", "limits"]


class TestDeterminism:
    def test_repeated_runs_agree(self, harness: RetrievalHarness) -> None:
        first = harness.run_mode("hybrid_rrf")
        second = harness.run_mode("hybrid_rrf")
        assert [r.ranked_ids for r in first.records] == [r.ranked_ids for r in second.records]

    def test_config_id_is_stable_and_sensitive(self) -> None:
        assert RunConfig().config_id() == RunConfig().config_id()
        assert RunConfig().config_id() != RunConfig(rrf_k=10).config_id()


class TestTransactionalThreadObservations:
    def test_success_persists_exact_entry_and_exit(self) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )
        local_harness.run_mode("sparse")

        observations = local_harness._native_thread_mode_observations["sparse"]
        assert [observation["boundary"] for observation in observations] == ["entry", "exit"]
        assert {observation["context"] for observation in observations} == {"query_latency:sparse"}

    def test_unsupported_mode_persists_no_observation(self) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )
        before = dict(local_harness._native_thread_mode_observations)

        with pytest.raises(ValueError, match="unsupported mode"):
            local_harness.run_mode("magic")

        assert local_harness._native_thread_mode_observations == before

    def test_post_observation_pre_acceptance_exception_persists_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )

        def reject_result(_mode: str, _result: object) -> None:
            raise RuntimeError("post-observation validation failure")

        monkeypatch.setattr(local_harness, "_validate_result", reject_result)
        with pytest.raises(RuntimeError, match="post-observation validation failure"):
            local_harness.run_mode("sparse")

        assert "sparse" not in local_harness._native_thread_mode_observations

    def test_failed_mode_cannot_contaminate_later_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )
        original_search = local_harness._search

        def fail_search(_mode: str, _query: str) -> object:
            raise RuntimeError("query failure")

        monkeypatch.setattr(local_harness, "_search", fail_search)
        with pytest.raises(RuntimeError, match="query failure"):
            local_harness.run_mode("dense")
        assert "dense" not in local_harness._native_thread_mode_observations

        monkeypatch.setattr(local_harness, "_search", original_search)
        local_harness.run_mode("dense")
        observations = local_harness._native_thread_mode_observations["dense"]
        assert [observation["boundary"] for observation in observations] == ["entry", "exit"]

    def test_repeated_success_replaces_observations(self) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )
        local_harness.run_mode("sparse")
        first = local_harness._native_thread_mode_observations["sparse"]
        local_harness.run_mode("sparse")
        second = local_harness._native_thread_mode_observations["sparse"]

        assert second is not first
        assert len(second) == 2


class TestResultShape:
    def test_hits_respect_the_final_limit(self) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        harness = RetrievalHarness(dataset, RunConfig(final_limit=3, embedding_dimensions=16))
        result = harness.run_mode("sparse")
        assert all(len(record.ranked_ids) <= 3 for record in result.records)

    def test_no_document_repeats_within_one_ranking(self, harness: RetrievalHarness) -> None:
        for record in harness.run_mode("hybrid_rrf").records:
            assert len(set(record.ranked_ids)) == len(record.ranked_ids)

    def test_hybrid_retains_both_component_score_sets(self, harness: RetrievalHarness) -> None:
        record = harness.run_mode("hybrid_rrf").records[0]
        assert set(record.component_scores) == {"sparse", "dense"}
        assert set(record.component_ranks) == {"sparse", "dense"}
        assert len(record.candidate_ranked_ids) == 30
        assert all(
            0 < len(scores) <= harness.config.candidate_limit
            for scores in record.component_scores.values()
        )
        assert all(
            set(record.component_scores[name]) == set(record.component_ranks[name])
            for name in record.component_scores
        )

    def test_single_mode_records_only_its_own_component(self, harness: RetrievalHarness) -> None:
        assert set(harness.run_mode("sparse").records[0].component_scores) == {"sparse"}

    def test_summary_reports_the_required_metrics(self, harness: RetrievalHarness) -> None:
        summary = harness.run_mode("dense").summary
        assert {"recall@5", "recall@10", "mrr@10", "ndcg@10"} <= set(summary)

    def test_unsupported_mode_is_rejected(self, harness: RetrievalHarness) -> None:
        with pytest.raises(ValueError, match="unsupported mode"):
            harness.run_mode("magic")

    def test_medcpt_mode_requires_verified_local_artifacts(self, harness: RetrievalHarness) -> None:
        with pytest.raises(ValueError, match="verified local-only artifacts"):
            harness.run_mode("medcpt")

    def test_medcpt_and_two_way_rrf_retain_complete_evidence(self, tmp_path: Path) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        doc_ids = sorted(dataset.corpus)
        local_harness = RetrievalHarness(
            dataset,
            RunConfig(embedding_dimensions=16),
            medcpt_index=cast(MedCPTIndex, StubMedCPTIndex(doc_ids)),
        )

        results = local_harness.run_all(("medcpt", "hybrid_rrf_medcpt"))

        assert all(
            set(record.component_scores) == {"medcpt"} for record in results["medcpt"].records
        )
        for record in results["hybrid_rrf_medcpt"].records:
            assert set(record.component_scores) == {"sparse", "medcpt"}
            assert set(record.component_ranks) == {"sparse", "medcpt"}
            assert "dense" not in record.component_scores
            components = []
            for component in ("sparse", "medcpt"):
                ranks = record.component_ranks[component]
                scores = record.component_scores[component]
                components.append(
                    [
                        (doc_id, scores[doc_id])
                        for doc_id in sorted(ranks, key=lambda item: ranks[item])
                    ]
                )
            rebuilt = reciprocal_rank_fusion(
                components,
                k=local_harness.config.rrf_k,
                limit=local_harness.config.candidate_limit,
            )
            assert [doc_id for doc_id, _score in rebuilt] == record.candidate_ranked_ids
        run_dir = local_harness.save(results, tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["mode_display_names"] == {
            "hybrid_rrf_medcpt": "rrf_bm25_medcpt",
            "medcpt": "medcpt_dense",
        }
        configuration = manifest["medcpt_configuration"]
        assert configuration["dimensions"] == 768
        assert configuration["query_max_length"] == 64
        assert configuration["article_max_length"] == 512
        assert configuration["query_batch_size"] == 1
        assert configuration["document_batch_size"] == 8
        assert configuration["pooling"] == "last_hidden_state_cls"
        assert configuration["normalization"] == "none"
        assert configuration["similarity"] == "inner_product"
        assert configuration["device"] == "cpu"
        assert configuration["artifact_provenance"] == {"schema_version": "offline_fake_medcpt_v1"}
        assert configuration["runtime_provenance"] == {
            "pytorch_intra_op_threads_observed": 1,
            "pytorch_inter_op_threads_observed": 1,
            "model_parameter_dtype_observed": {
                "query_encoder": "torch.float32",
                "article_encoder": "torch.float32",
            },
            "query_embedding_dtype_observed": "float32",
            "document_embedding_index_dtype_observed": "float32",
            "dense_index_memory_bytes": 6_144,
            "dense_index_memory_measurement": "numpy.ndarray.nbytes",
            "dense_index_memory_limitation": (
                "Document embedding matrix only; not Python process RSS, allocator overhead, "
                "model memory, or total application memory."
            ),
        }

    def test_missing_runtime_provenance_fails_before_artifact_creation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        stub = StubMedCPTIndex(sorted(dataset.corpus))
        local_harness = RetrievalHarness(
            dataset,
            RunConfig(embedding_dimensions=16),
            medcpt_index=cast(MedCPTIndex, stub),
        )
        results = local_harness.run_all(("medcpt",))

        def unavailable() -> dict[str, object]:
            raise ValueError("required runtime observation unavailable")

        monkeypatch.setattr(stub, "runtime_provenance", unavailable)

        with pytest.raises(ValueError, match="required runtime observation unavailable"):
            local_harness.save(results, tmp_path, run_id="must-not-exist")
        assert list(tmp_path.iterdir()) == []


class TestRawArtifacts:
    def test_saved_run_is_self_describing(self, harness: RetrievalHarness, tmp_path: Path) -> None:
        results = harness.run_all(MODES)
        run_dir = harness.save(results, tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

        for key in (
            "config",
            "config_id",
            "corpus_id",
            "dataset_summary",
            "environment",
            "summary",
            "approval_status",
            "repository_git_revision",
            "retrieval_configuration",
            "random_seed_actual",
            "output_artifacts",
            "repository_source_state",
            "execution_policy",
            "build_index_timing",
            "runtime_provenance",
        ):
            assert key in manifest, f"manifest missing {key}"
        assert "ME-000C remains open" in manifest["approval_status"]
        assert manifest["mode_display_names"] == {
            "dense": "classical_lsi_dense",
            "hybrid_rrf": "rrf_bm25_lsi",
            "sparse": "BM25",
        }
        assert len(manifest["repository_git_revision"]) == 40
        assert manifest["random_seed_actual"] == harness.config.random_state
        assert manifest["dataset_name"] == harness.dataset.dataset_id
        assert manifest["dataset_source"] == "local_jsonl_fixture"
        assert (
            manifest["distribution_identity"]["sha256"]
            == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
        )
        assert manifest["consumed_files"] == [manifest["distribution_identity"]]
        source_state = manifest["repository_source_state"]
        assert source_state["head"] == manifest["repository_git_revision"]
        assert (
            source_state["tracked_patch_sha256"]
            == hashlib.sha256((run_dir / "source.patch").read_bytes()).hexdigest()
        )
        assert source_state["source_state_sha256"]
        assert (
            source_state["untracked_snapshot_sha256"]
            == hashlib.sha256((run_dir / "source-untracked-snapshot.json").read_bytes()).hexdigest()
        )
        assert manifest["execution_policy"]["query_execution"] == "serial_single_process"
        assert manifest["execution_policy"]["query_concurrency"] == 1
        native_threading = manifest["execution_policy"]["native_threading"]
        assert native_threading["requested_limit"] == 1
        assert set(native_threading["environment"].values()) == {"1"}
        assert native_threading["discovered_pools_before_limits"]
        observations = native_threading["observed_in_context_pools"]
        assert {observation["context"] for observation in observations} == {
            "index_build",
            "query_latency:dense",
            "query_latency:hybrid_rrf",
            "query_latency:sparse",
        }
        assert all(
            pool["num_threads"] == 1
            for observation in observations
            for pool in observation["pools"]
        )
        provenance = manifest["runtime_provenance"]
        assert provenance["python"] == sys.version.split()[0]
        assert provenance["numpy"] == manifest["environment"]["dependency:numpy"]
        assert provenance["scikit_learn"] == manifest["environment"]["dependency:scikit-learn"]
        assert provenance["git_revision"] == manifest["repository_git_revision"]
        assert provenance["platform"] == manifest["environment"]["platform"]
        lock_path = Path(__file__).resolve().parents[3] / "uv.lock"
        assert provenance["uv_lock"] == {
            "path": "uv.lock",
            "bytes": lock_path.stat().st_size,
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        }
        assert manifest["build_index_timing"]["sparse"]["kind"] == "measured_index_build"
        assert manifest["build_index_timing"]["hybrid_rrf"]["kind"].startswith("derived_sum")

    def test_save_rejects_missing_dataset_provenance(self, tmp_path: Path) -> None:
        dataset = EvaluationDataset(
            dataset_id="unbound",
            corpus={"d1": "alpha text", "d2": "beta text", "d3": "gamma text"},
            corpus_titles={"d1": "", "d2": "", "d3": ""},
            queries={"q1": "text"},
            qrels={"q1": {"d1": 1}},
        )
        local_harness = RetrievalHarness(dataset, RunConfig(embedding_dimensions=2))
        results = local_harness.run_all(("sparse",))
        with pytest.raises(ValueError, match="dataset source identity"):
            local_harness.save(results, tmp_path)
        assert not list(tmp_path.iterdir())

    def test_native_thread_mismatch_fails_before_artifacts(self, tmp_path: Path) -> None:
        local_harness = RetrievalHarness(
            load_jsonl_dataset(FIXTURE), RunConfig(embedding_dimensions=16)
        )
        results = local_harness.run_all(("sparse",))
        local_harness._native_thread_build_observations[0]["pools"][0]["num_threads"] = 2

        with pytest.raises(RuntimeError, match="native thread limit mismatch"):
            local_harness.save(results, tmp_path)
        assert not list(tmp_path.iterdir())

    def test_every_query_has_a_raw_record(self, harness: RetrievalHarness, tmp_path: Path) -> None:
        results = harness.run_all(MODES)
        run_dir = harness.save(results, tmp_path)
        expected = len(harness.dataset.judged_queries)
        for mode in MODES:
            lines = (run_dir / f"per-query-{mode}.jsonl").read_text(encoding="utf-8").splitlines()
            assert len(lines) == expected

    def test_raw_records_allow_metric_recomputation(
        self, harness: RetrievalHarness, tmp_path: Path
    ) -> None:
        from evaluation.metrics import ndcg_at_k

        results = harness.run_all(("sparse",))
        run_dir = harness.save(results, tmp_path)
        line = (run_dir / "per-query-sparse.jsonl").read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        recomputed = ndcg_at_k(record["ranked_ids"], harness.dataset.qrels[record["query_id"]], 10)
        assert recomputed == pytest.approx(record["metrics"]["ndcg@10"])

    def test_output_hashes_recompute_and_manifest_has_external_sidecar(
        self, harness: RetrievalHarness, tmp_path: Path
    ) -> None:
        run_dir = harness.save(harness.run_all(MODES), tmp_path)
        manifest_path = run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["manifest_integrity"] == {
            "sidecar": "manifest.sha256",
            "strategy": "external_sha256_sidecar",
        }
        for artifact in manifest["output_artifacts"]:
            path = run_dir / artifact["filename"]
            assert artifact["bytes"] == path.stat().st_size
            assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

        expected_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        assert (run_dir / "manifest.sha256").read_text(encoding="ascii") == (
            f"{expected_manifest_hash}  manifest.json\n"
        )

    def test_manifest_records_software_versions_and_complete_query_records(
        self, harness: RetrievalHarness, tmp_path: Path
    ) -> None:
        run_dir = harness.save(harness.run_all(("dense",)), tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["environment"]["dependency:numpy"] == "2.5.1"
        assert manifest["environment"]["dependency:scikit-learn"] == "1.9.0"
        assert manifest["environment"]["dependency:scipy"]
        assert manifest["dataset_summary"]["judgments"] > 0
        assert manifest["build_index_timing"]["dense"]["seconds"] >= 0.0

        lines = (run_dir / "per-query-dense.jsonl").read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        assert all(record["ranked_ids"] for record in records)
        assert all("latency_ms" in record and "metrics" in record for record in records)
        assert all(len(record["candidate_ranked_ids"]) == 30 for record in records)

    def test_rrf_top10_reconstructs_from_full_component_artifacts(
        self, harness: RetrievalHarness, tmp_path: Path
    ) -> None:
        run_dir = harness.save(harness.run_all(("hybrid_rrf",)), tmp_path)
        path = run_dir / "per-query-hybrid_rrf.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            components = []
            for component in ("sparse", "dense"):
                ranks = record["component_ranks"][component]
                scores = record["component_scores"][component]
                components.append(
                    [
                        (doc_id, scores[doc_id])
                        for doc_id in sorted(ranks, key=lambda item: ranks[item])
                    ]
                )
            rebuilt = reciprocal_rank_fusion(
                components,
                k=harness.config.rrf_k,
                limit=harness.config.candidate_limit,
            )
            assert [doc_id for doc_id, _score in rebuilt[:10]] == record["ranked_ids"]
            assert [score for _doc_id, score in rebuilt[:10]] == pytest.approx(record["scores"])

    @pytest.mark.parametrize("defect", ["missing_query", "duplicate_query", "bad_summary"])
    def test_save_rejects_incomplete_or_nonrecomputable_results(
        self, harness: RetrievalHarness, tmp_path: Path, defect: str
    ) -> None:
        result = harness.run_mode("sparse")
        if defect == "missing_query":
            result.records.pop()
        elif defect == "duplicate_query":
            result.records.append(result.records[0])
        else:
            result.summary["recall@10"] = -1.0
        with pytest.raises(ValueError):
            harness.save({"sparse": result}, tmp_path)
        assert not list(tmp_path.iterdir())

    def test_deterministic_run_id_selects_exact_tracked_path(
        self, harness: RetrievalHarness, tmp_path: Path
    ) -> None:
        run_dir = harness.save(harness.run_all(("sparse",)), tmp_path, run_id="nfcorpus-real-final")
        assert run_dir == tmp_path / "nfcorpus-real-final"

    def test_dataset_warnings_propagate_into_the_manifest(self, tmp_path: Path) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        dataset.warnings.append("synthetic warning")
        harness = RetrievalHarness(dataset, RunConfig(embedding_dimensions=16))
        run_dir = harness.save(harness.run_all(("sparse",)), tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert "synthetic warning" in manifest["dataset_warnings"]
