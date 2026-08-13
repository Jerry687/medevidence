"""Contract tests for the evaluation harness.

These assert the reproducibility guarantees the evaluation plan depends on:
identical controlled variables across modes, deterministic results, complete
raw artifacts, and no summary emitted without its configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.datasets import load_jsonl_dataset
from evaluation.harness import RetrievalHarness, RunConfig

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/retrieval/harness_smoke.json"
MODES = ("sparse", "dense", "hybrid_rrf")


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


class TestDeterminism:
    def test_repeated_runs_agree(self, harness: RetrievalHarness) -> None:
        first = harness.run_mode("hybrid_rrf")
        second = harness.run_mode("hybrid_rrf")
        assert [r.ranked_ids for r in first.records] == [r.ranked_ids for r in second.records]

    def test_config_id_is_stable_and_sensitive(self) -> None:
        assert RunConfig().config_id() == RunConfig().config_id()
        assert RunConfig().config_id() != RunConfig(rrf_k=10).config_id()


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

    def test_single_mode_records_only_its_own_component(self, harness: RetrievalHarness) -> None:
        assert set(harness.run_mode("sparse").records[0].component_scores) == {"sparse"}

    def test_summary_reports_the_required_metrics(self, harness: RetrievalHarness) -> None:
        summary = harness.run_mode("dense").summary
        assert {"recall@5", "recall@10", "mrr@10", "ndcg@10"} <= set(summary)

    def test_unsupported_mode_is_rejected(self, harness: RetrievalHarness) -> None:
        with pytest.raises(ValueError, match="unsupported mode"):
            harness.run_mode("magic")


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
        ):
            assert key in manifest, f"manifest missing {key}"
        assert "ME-000C is open" in manifest["approval_status"]

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

    def test_dataset_warnings_propagate_into_the_manifest(self, tmp_path: Path) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        dataset.warnings.append("synthetic warning")
        harness = RetrievalHarness(dataset, RunConfig(embedding_dimensions=16))
        run_dir = harness.save(harness.run_all(("sparse",)), tmp_path)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert "synthetic warning" in manifest["dataset_warnings"]
