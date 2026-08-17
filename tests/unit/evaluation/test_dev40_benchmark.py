from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from evaluation import dev40_benchmark as benchmark
from evaluation.dev40_benchmark import (
    ADJUDICATION_PROVENANCE,
    CORPUS_SIZE,
    DIRECT_METRIC_QUESTION_IDS,
    MODE_BM25,
    MODE_MEDCPT,
    MODE_RRF,
    MODES,
    QUESTION_IDS,
    RANKING_METRIC_QUESTION_IDS,
    SOURCE_STATE_QUESTION_IDS,
    ArtifactIdentity,
    Dev40BenchmarkDataset,
    Dev40BenchmarkError,
    Dev40BenchmarkRunner,
    Dev40Document,
    Dev40InputPaths,
    Dev40Question,
    load_dev40_dataset,
    save_benchmark_run,
)
from evaluation.run_dev40_benchmark import OFFLINE_ENVIRONMENT, main


class _FakeArtifacts:
    def provenance(self) -> dict[str, Any]:
        return {"manifest": {"sha256": "a" * 64}, "repositories": ["query", "article"]}


class _FakeMedCPT:
    def __init__(self, doc_ids: tuple[str, ...], *, tied: bool = False) -> None:
        self.doc_ids = doc_ids
        self.artifacts = _FakeArtifacts()
        self.tied = tied
        self.device = "cpu"
        self.dimensions = 768
        self.query_batch_size = 1
        self.document_batch_size = 8
        self.queries: list[str] = []
        self.runtime = {
            "pytorch_intra_op_threads_observed": 1,
            "pytorch_inter_op_threads_observed": 1,
            "model_parameter_dtype_observed": {
                "query_encoder": "torch.float32",
                "article_encoder": "torch.float32",
            },
            "query_embedding_dtype_observed": "float32",
            "document_embedding_index_dtype_observed": "float32",
            "dense_index_memory_bytes": 657_408,
            "dense_index_memory_measurement": "numpy.ndarray.nbytes",
            "dense_index_memory_limitation": (
                "Document embedding matrix only; not Python process RSS, allocator overhead, "
                "model memory, or total application memory."
            ),
        }

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        self.queries.append(query)
        if self.tied:
            return [(doc_id, 1.0) for doc_id in sorted(self.doc_ids)[:limit]]
        return [
            (doc_id, float(len(self.doc_ids) - ordinal))
            for ordinal, doc_id in enumerate(self.doc_ids[:limit])
        ]

    def runtime_provenance(self) -> dict[str, Any]:
        return self.runtime


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.001
        return self.value


def _dataset() -> Dev40BenchmarkDataset:
    documents = tuple(
        Dev40Document(
            retrieval_unit_id=f"doc-{ordinal:03d}",
            source="pubmed" if ordinal < 199 else "dailymed",
            stable_source_id=str(ordinal),
            source_locator=f"https://example.invalid/{ordinal}",
            source_version_identity=f"version:{ordinal}",
            title="alpha" if ordinal == 0 else f"Title {ordinal}",
            text=f"Exact text {ordinal}",
            text_sha256=hashlib.sha256(f"Exact text {ordinal}".encode()).hexdigest(),
        )
        for ordinal in range(CORPUS_SIZE)
    )
    questions: list[Dev40Question] = []
    for question_id in QUESTION_IDS:
        judgments = {document.retrieval_unit_id: 0 for document in documents}
        ranking_eligible = question_id in RANKING_METRIC_QUESTION_IDS
        direct_eligible = question_id in DIRECT_METRIC_QUESTION_IDS
        if ranking_eligible:
            judgments[documents[0].retrieval_unit_id] = 2 if direct_eligible else 1
            judgments[documents[1].retrieval_unit_id] = 1
        questions.append(
            Dev40Question(
                question_id=question_id,
                text=f"{question_id} alpha",
                judgments=judgments,
                notes={doc_id: "note" for doc_id in judgments},
                ranking_metric_eligible=ranking_eligible,
                direct_answer_eligible=direct_eligible,
                metric_exclusion_reason=(
                    f"source-state exclusion for {question_id}"
                    if question_id in SOURCE_STATE_QUESTION_IDS
                    else None
                ),
            )
        )
    identities = {
        name: ArtifactIdentity(f"D:/external/{name}", 1, f"{index:x}" * 64)
        for index, name in enumerate(
            (
                "corpus",
                "packet",
                "qrels",
                "nonzero_qrels",
                "adjudication",
                "contract",
                "bundle_manifest",
            ),
            start=1,
        )
    }
    freeze = {
        name: ArtifactIdentity(f"D:/external/{name}", 1, "f" * 64)
        for name in ("run_plan", "source_reconciliation", "frozen_source_state")
    }
    return Dev40BenchmarkDataset(
        documents=documents,
        questions=tuple(questions),
        input_identities=identities,
        freeze_identities=freeze,
        freeze_validation="test",
        adjudication_provenance=ADJUDICATION_PROVENANCE,
    )


def _run() -> tuple[Dev40BenchmarkDataset, _FakeMedCPT, benchmark.BenchmarkRun]:
    dataset = _dataset()
    index = _FakeMedCPT(dataset.document_ids)
    run = Dev40BenchmarkRunner(dataset, index, medcpt_build_seconds=0.25, clock=_Clock()).run()
    return dataset, index, run


def test_exact_external_bundle_reconciles_all_questions_and_pairs() -> None:
    paths = Dev40InputPaths.canonical()
    if not paths.corpus.exists():
        pytest.skip("exact external Dev-40 evidence is unavailable")
    dataset = load_dev40_dataset(paths)
    assert len(dataset.documents) == 214
    assert tuple(question.question_id for question in dataset.questions) == QUESTION_IDS
    assert sum(len(question.judgments) for question in dataset.questions) == 4_922
    assert (
        tuple(
            question.question_id
            for question in dataset.questions
            if question.ranking_metric_eligible
        )
        == RANKING_METRIC_QUESTION_IDS
    )
    assert (
        tuple(
            question.question_id
            for question in dataset.questions
            if question.direct_answer_eligible
        )
        == DIRECT_METRIC_QUESTION_IDS
    )
    assert dataset.input_identities["contract"].sha256.endswith("d50b")
    assert "historical frozen source-state" in dataset.freeze_validation


def test_dataset_preserves_exact_source_ids_titles_and_text() -> None:
    paths = Dev40InputPaths.canonical()
    if not paths.corpus.exists():
        pytest.skip("exact external Dev-40 evidence is unavailable")
    raw = json.loads(paths.corpus.read_text(encoding="utf-8"))
    dataset = load_dev40_dataset(paths)
    source = {item["retrieval_unit_id"]: item for item in raw["items"]}
    assert set(dataset.document_ids) == set(source)
    for document in dataset.documents:
        assert document.title == source[document.retrieval_unit_id]["title"]
        assert document.text == source[document.retrieval_unit_id]["text"]


def test_modes_retain_complete_rankings_components_and_exact_denominators() -> None:
    dataset, _index, run = _run()
    assert tuple(run.modes) == MODES
    for mode, result in run.modes.items():
        assert len(result.records) == 20
        assert tuple(record.question_id for record in result.records) == (
            RANKING_METRIC_QUESTION_IDS
        )
        assert result.metric_denominators == {
            "nDCG@10": 20,
            "Recall@5": 20,
            "Recall@10": 20,
            "MRR@10": 20,
            "DirectHit@10": 17,
            "DirectMRR@10": 17,
        }
        expected_components = {mode} if mode != MODE_RRF else {MODE_BM25, MODE_MEDCPT}
        for record in result.records:
            assert len(record.rankings) == 214
            assert {entry.retrieval_unit_id for entry in record.rankings} == set(
                dataset.document_ids
            )
            assert all(
                set(entry.component_ranks) == expected_components for entry in record.rankings
            )


def test_metric_formulas_direct_nulls_and_source_state_nulls_are_exact() -> None:
    dataset = _dataset()
    direct_question = dataset.questions[0]
    ranking = [(dataset.document_ids[1], 2.0), (dataset.document_ids[0], 1.0)] + [
        (doc_id, 0.0) for doc_id in dataset.document_ids[2:]
    ]
    metrics = benchmark._query_metrics(ranking, direct_question)
    expected_dcg = 1.0 + 3.0 / math.log2(3.0)
    ideal_dcg = 3.0 + 1.0 / math.log2(3.0)
    assert metrics["nDCG@10"] == pytest.approx(expected_dcg / ideal_dcg)
    assert metrics["Recall@5"] == 1.0
    assert metrics["DirectHit@10"] == 1.0
    assert metrics["DirectMRR@10"] == 0.5
    _dataset_value, _index, run = _run()
    for result in run.modes.values():
        q2 = next(record for record in result.records if record.question_id == "Q2")
        assert q2.metrics["nDCG@10"] is not None
        assert q2.metrics["DirectHit@10"] is None
        for question_id in SOURCE_STATE_QUESTION_IDS:
            assert all(item.question_id != question_id for item in result.records)
    source_state_question = next(
        question
        for question in dataset.questions
        if question.question_id == SOURCE_STATE_QUESTION_IDS[0]
    )
    with pytest.raises(Dev40BenchmarkError, match="cannot enter ranking metrics"):
        benchmark._query_metrics(ranking, source_state_question)


def test_runner_never_searches_source_state_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    bm25_queries: list[str] = []

    class _SpyBM25:
        def __init__(
            self,
            doc_ids: tuple[str, ...],
            documents: list[str],
            *,
            k1: float,
            b: float,
        ) -> None:
            del documents, k1, b
            self.doc_ids = doc_ids

        def search(self, query: str, limit: int) -> list[tuple[str, float]]:
            bm25_queries.append(query)
            return [
                (doc_id, float(len(self.doc_ids) - ordinal))
                for ordinal, doc_id in enumerate(self.doc_ids[:limit])
            ]

    monkeypatch.setattr(benchmark, "BM25Index", _SpyBM25)
    index = _FakeMedCPT(dataset.document_ids)
    Dev40BenchmarkRunner(dataset, index, medcpt_build_seconds=0.0, clock=_Clock()).run()
    expected_queries = {
        question.text for question in dataset.questions if question.ranking_metric_eligible
    }
    excluded_queries = {
        question.text for question in dataset.questions if not question.ranking_metric_eligible
    }
    assert len(bm25_queries) == 40
    assert len(index.queries) == 40
    assert set(bm25_queries) == expected_queries
    assert set(index.queries) == expected_queries
    assert excluded_queries.isdisjoint(bm25_queries)
    assert excluded_queries.isdisjoint(index.queries)


def test_score_ties_break_by_exact_document_id() -> None:
    dataset = _dataset()
    index = _FakeMedCPT(dataset.document_ids, tied=True)
    run = Dev40BenchmarkRunner(dataset, index, medcpt_build_seconds=0.0, clock=_Clock()).run()
    medcpt = run.modes[MODE_MEDCPT].records[0]
    assert [entry.retrieval_unit_id for entry in medcpt.rankings] == sorted(dataset.document_ids)
    bm25 = run.modes[MODE_BM25].records[0]
    zero_ids = [entry.retrieval_unit_id for entry in bm25.rankings if entry.score == 0.0]
    assert zero_ids == sorted(zero_ids)


def test_rrf_reconciliation_rejects_score_drift() -> None:
    dataset, _index, run = _run()
    result = run.modes[MODE_RRF]
    record = result.records[0]
    broken_entry = replace(record.rankings[0], score=record.rankings[0].score + 0.01)
    broken_record = replace(record, rankings=(broken_entry, *record.rankings[1:]))
    broken_result = replace(result, records=(broken_record, *result.records[1:]))
    with pytest.raises(Dev40BenchmarkError, match="RRF evidence"):
        benchmark._validate_mode_result(broken_result, dataset)


def test_strict_json_and_quoted_multiline_qrels_fail_closed() -> None:
    with pytest.raises(Dev40BenchmarkError, match="duplicate JSON key"):
        benchmark._strict_json(b'{"a":1,"a":2}', label="test")
    with pytest.raises(Dev40BenchmarkError, match="strict UTF-8 JSON"):
        benchmark._strict_json(b'{"a":"\xff"}', label="test")
    header = "\t".join(benchmark.QRELS_HEADER)
    data = (
        header
        + '\nQ1\tdoc-1\t1\tpubmed\tTitle\t"line one\nline two"'
        + "\nQ1\tdoc-2\t0\tpubmed\tTitle 2\tnote\n"
    ).encode()
    rows = benchmark._parse_tsv(data, label="qrels", expected_rows=2)
    assert rows[0]["adjudication_note"] == "line one\nline two"
    duplicate = data.replace(b"doc-2", b"doc-1")
    with pytest.raises(Dev40BenchmarkError, match="duplicate"):
        benchmark._parse_tsv(duplicate, label="qrels", expected_rows=2)
    with pytest.raises(Dev40BenchmarkError, match="LF-only"):
        benchmark._parse_tsv(data.replace(b"\n", b"\r\n"), label="qrels", expected_rows=2)


def test_input_path_drift_fails_before_content_is_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze = tmp_path / "freeze"
    owner = tmp_path / "owner"
    freeze.mkdir()
    owner.mkdir()
    monkeypatch.setattr(benchmark, "FREEZE_ROOT", freeze)
    monkeypatch.setattr(benchmark, "OWNER_BUNDLE_ROOT", owner)
    paths = Dev40InputPaths.canonical()
    for path in (
        paths.corpus,
        paths.packet,
        paths.qrels,
        paths.nonzero_qrels,
        paths.adjudication,
        paths.contract,
        paths.bundle_manifest,
    ):
        path.write_bytes(b"")
    wrong = tmp_path / "wrong.json"
    wrong.write_bytes(b"")
    with pytest.raises(Dev40BenchmarkError, match="path differs"):
        benchmark._read_exact_inputs(replace(paths, corpus=wrong))


def test_save_is_atomic_no_clobber_and_records_offline_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, index, run = _run()
    output = tmp_path / "benchmark-001"
    monkeypatch.setattr(benchmark, "BENCHMARK_OUTPUT_ROOT", output)
    monkeypatch.setattr(benchmark, "_rebind_dataset_inputs", lambda value: value)
    monkeypatch.setattr(
        benchmark,
        "_runtime_identity",
        lambda: {"python": "3.12.13", "platform": "test", "processor": "test", "packages": {}},
    )
    saved = save_benchmark_run(
        run,
        dataset,
        index,
        output,
        executed_at_utc=datetime(2026, 8, 17, tzinfo=UTC),
    )
    manifest_bytes = (saved / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    assert (saved / "manifest.sha256").read_text() == f"{digest}  manifest.json\n"
    assert manifest["run_id"] == "M2-006-MEDEVIDENCE-DEV40-BENCHMARK-001"
    assert manifest["execution_policy"] == {
        "network_operations": 0,
        "holdout_access": False,
        "model_downloads": 0,
        "network_declaration": (
            "offline-only frozen corpus and local MedCPT cache; no connector, client, "
            "medical-source, Hugging Face, or dependency-advisory request"
        ),
        "query_execution": "serial_single_process",
        "ranking_questions_per_mode": 20,
        "complete_candidate_ranks_per_question_mode": 214,
    }
    assert len(manifest["corpus_documents"]) == 214
    assert len(manifest["output_artifacts"]) == 3
    assert set(manifest["summary"][MODE_BM25]["query_timing_ms"]) == {
        "mean",
        "p50",
        "p95",
        "total",
    }
    assert tuple(manifest["source_state_behavior_cases"]) == SOURCE_STATE_QUESTION_IDS
    for question_id, value in manifest["source_state_behavior_cases"].items():
        assert value["reason"] == f"source-state exclusion for {question_id}"
        assert value["execution"] == {
            "ranking": False,
            "component_ranks_or_scores": False,
            "metrics": False,
            "query_timing": False,
        }
    for filename in benchmark.MODE_FILENAMES.values():
        records = [json.loads(line) for line in (saved / filename).read_text().splitlines()]
        assert tuple(record["question_id"] for record in records) == (RANKING_METRIC_QUESTION_IDS)
        assert not set(SOURCE_STATE_QUESTION_IDS).intersection(
            record["question_id"] for record in records
        )
    with pytest.raises(Dev40BenchmarkError, match="new absent"):
        save_benchmark_run(run, dataset, index, output)


def test_cli_rejects_existing_output_before_inputs_or_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "benchmark-001"
    output.mkdir()
    monkeypatch.setattr(benchmark, "BENCHMARK_OUTPUT_ROOT", output)
    arguments = [
        "--corpus-manifest",
        str(tmp_path / "missing-corpus"),
        "--blinded-packet",
        str(tmp_path / "missing-packet"),
        "--qrels",
        str(tmp_path / "missing-qrels"),
        "--nonzero-qrels",
        str(tmp_path / "missing-nonzero"),
        "--adjudication",
        str(tmp_path / "missing-adjudication"),
        "--metric-contract",
        str(tmp_path / "missing-contract"),
        "--bundle-manifest",
        str(tmp_path / "missing-bundle"),
        "--model-manifest",
        str(tmp_path / "missing-model"),
        "--model-cache",
        str(tmp_path / "missing-cache"),
        "--output-root",
        str(output),
    ]
    with pytest.raises(Dev40BenchmarkError, match="new absent"):
        main(arguments)
    assert all(os.environ[name] == value for name, value in OFFLINE_ENVIRONMENT.items())
