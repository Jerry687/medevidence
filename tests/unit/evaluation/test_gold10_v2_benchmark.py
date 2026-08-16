from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from evaluation import gold10_v2_benchmark as benchmark
from evaluation.gold10_v2_benchmark import (
    ADJUDICATION_PROVENANCE,
    CORPUS_SIZE,
    MODE_BM25,
    MODE_MEDCPT,
    MODE_RRF,
    MODES,
    ArtifactIdentity,
    Gold10BenchmarkDataset,
    Gold10BenchmarkError,
    Gold10BenchmarkRunner,
    Gold10Document,
    Gold10InputPaths,
    Gold10Question,
    load_gold10_v2_dataset,
    save_benchmark_run,
)
from evaluation.run_gold10_v2_benchmark import main


class _FakeArtifacts:
    def provenance(self) -> dict[str, Any]:
        return {
            "manifest": {"sha256": "a" * 64},
            "repositories": ["query", "article"],
        }


class _FakeMedCPT:
    def __init__(self, doc_ids: tuple[str, ...], *, tied: bool = False) -> None:
        self.doc_ids = doc_ids
        self.artifacts = _FakeArtifacts()
        self.tied = tied
        self.device = "cpu"
        self.dimensions = 768
        self.query_batch_size = 1
        self.document_batch_size = 8
        self.runtime = {
            "pytorch_intra_op_threads_observed": 1,
            "pytorch_inter_op_threads_observed": 1,
            "model_parameter_dtype_observed": {
                "query_encoder": "torch.float32",
                "article_encoder": "torch.float32",
            },
            "query_embedding_dtype_observed": "float32",
            "document_embedding_index_dtype_observed": "float32",
            "dense_index_memory_bytes": 199_680,
            "dense_index_memory_measurement": "numpy.ndarray.nbytes",
            "dense_index_memory_limitation": (
                "Document embedding matrix only; not Python process RSS, allocator overhead, "
                "model memory, or total application memory."
            ),
        }

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        del query
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


def _dataset() -> Gold10BenchmarkDataset:
    documents = tuple(
        Gold10Document(
            retrieval_unit_id=f"doc-{ordinal:02d}",
            source="pubmed" if ordinal < 50 else "dailymed",
            stable_source_id=str(ordinal),
            source_locator=f"https://example.invalid/{ordinal}",
            source_version_identity=f"version:{ordinal}",
            title="alpha" if ordinal == 0 else f"Title {ordinal}",
            text=f"Exact text {ordinal}",
            text_sha256=hashlib.sha256(f"Exact text {ordinal}".encode()).hexdigest(),
        )
        for ordinal in range(CORPUS_SIZE)
    )
    questions = []
    for ordinal in range(1, 11):
        judgments = {document.retrieval_unit_id: 0 for document in documents}
        judgments[documents[0].retrieval_unit_id] = 1 if ordinal == 2 else 2
        judgments[documents[1].retrieval_unit_id] = 1
        questions.append(
            Gold10Question(
                question_id=f"Q{ordinal}",
                text="alpha",
                judgments=judgments,
                notes={doc_id: "note" for doc_id in judgments},
                direct_answer_eligible=ordinal != 2,
            )
        )
    identities = {
        name: ArtifactIdentity(f"D:/external/{name}", 1, str(index) * 64)
        for index, name in enumerate(
            ("corpus", "packet", "qrels", "adjudication", "contract"), start=1
        )
    }
    return Gold10BenchmarkDataset(
        documents=documents,
        questions=tuple(questions),
        input_identities=identities,
        adjudication_provenance=ADJUDICATION_PROVENANCE,
    )


def _run() -> tuple[Gold10BenchmarkDataset, _FakeMedCPT, benchmark.BenchmarkRun]:
    dataset = _dataset()
    index = _FakeMedCPT(dataset.document_ids)
    runner = Gold10BenchmarkRunner(
        dataset,
        index,
        medcpt_build_seconds=0.25,
        clock=_Clock(),
    )
    return dataset, index, runner.run()


def _qrels_bytes(*, duplicate_last: bool = False) -> bytes:
    lines = ["\t".join(benchmark.QRELS_HEADER)]
    for question in range(1, 11):
        for document in range(CORPUS_SIZE):
            lines.append(f"Q{question}\tdoc-{document:02d}\t0\tpubmed\tTitle {document}\tnote")
    if duplicate_last:
        lines[-1] = lines[-2]
    return ("\n".join(lines) + "\n").encode()


def test_exact_external_bundle_loads_and_reconciles_all_pairs() -> None:
    paths = Gold10InputPaths.canonical()
    if not paths.corpus.exists():
        pytest.skip("exact external Gold-10 V2 evidence is unavailable")
    dataset = load_gold10_v2_dataset(paths)
    assert len(dataset.documents) == 65
    assert len(dataset.questions) == 10
    assert sum(len(question.judgments) for question in dataset.questions) == 650
    assert [
        question.question_id
        for question in dataset.questions
        if not question.direct_answer_eligible
    ] == ["Q2"]
    assert dataset.adjudication_provenance == "blinded AI adjudication, Owner-confirmed"


def test_dataset_adapter_preserves_exact_source_ids_titles_and_text() -> None:
    paths = Gold10InputPaths.canonical()
    if not paths.corpus.exists():
        pytest.skip("exact external Gold-10 V2 evidence is unavailable")
    raw = json.loads(paths.corpus.read_text(encoding="utf-8"))
    dataset = load_gold10_v2_dataset(paths)
    source = {item["retrieval_unit_id"]: item for item in raw["items"]}
    assert set(dataset.document_ids) == set(source)
    for document in dataset.documents:
        assert document.title == source[document.retrieval_unit_id]["title"]
        assert document.text == source[document.retrieval_unit_id]["text"]


def test_modes_are_exact_and_every_ranking_retains_all_65_candidates() -> None:
    dataset, _index, run = _run()
    assert tuple(run.modes) == (MODE_BM25, MODE_MEDCPT, MODE_RRF)
    assert tuple(run.modes) == MODES
    for mode, result in run.modes.items():
        assert len(result.records) == 10
        assert all(len(record.rankings) == 65 for record in result.records)
        assert all(
            {entry.retrieval_unit_id for entry in record.rankings} == set(dataset.document_ids)
            for record in result.records
        )
        expected_components = {mode} if mode != MODE_RRF else {MODE_BM25, MODE_MEDCPT}
        assert all(
            set(entry.component_ranks) == expected_components
            for record in result.records
            for entry in record.rankings
        )


def test_metric_formulas_and_direct_denominators_are_exact() -> None:
    dataset = _dataset()
    question = dataset.questions[0]
    ranking = [(dataset.document_ids[1], 2.0), (dataset.document_ids[0], 1.0)] + [
        (doc_id, 0.0) for doc_id in dataset.document_ids[2:]
    ]
    metrics = benchmark._query_metrics(ranking, question)
    expected_dcg = 1.0 + 3.0 / math.log2(3.0)
    ideal_dcg = 3.0 + 1.0 / math.log2(3.0)
    assert metrics["nDCG@10"] == pytest.approx(expected_dcg / ideal_dcg)
    assert metrics["Recall@5"] == 1.0
    assert metrics["Recall@10"] == 1.0
    assert metrics["MRR@10"] == 1.0
    assert metrics["DirectHit@10"] == 1.0
    assert metrics["DirectMRR@10"] == 0.5
    _dataset_value, _index, run = _run()
    for result in run.modes.values():
        assert result.metric_denominators == {
            "nDCG@10": 10,
            "Recall@5": 10,
            "Recall@10": 10,
            "MRR@10": 10,
            "DirectHit@10": 9,
            "DirectMRR@10": 9,
        }
        q2 = next(record for record in result.records if record.question_id == "Q2")
        assert q2.metrics["DirectHit@10"] is None
        assert q2.metrics["DirectMRR@10"] is None


def test_score_ties_break_by_exact_document_id() -> None:
    dataset = _dataset()
    index = _FakeMedCPT(dataset.document_ids, tied=True)
    run = Gold10BenchmarkRunner(dataset, index, medcpt_build_seconds=0.0, clock=_Clock()).run()
    medcpt = run.modes[MODE_MEDCPT].records[0]
    assert [entry.retrieval_unit_id for entry in medcpt.rankings] == sorted(dataset.document_ids)
    bm25 = run.modes[MODE_BM25].records[0]
    zero_score_ids = [entry.retrieval_unit_id for entry in bm25.rankings if entry.score == 0.0]
    assert zero_score_ids == sorted(zero_score_ids)


def test_rrf_reconciliation_rejects_score_or_component_drift() -> None:
    dataset, _index, run = _run()
    result = run.modes[MODE_RRF]
    record = result.records[0]
    broken_entry = replace(record.rankings[0], score=record.rankings[0].score + 0.01)
    broken_record = replace(record, rankings=(broken_entry, *record.rankings[1:]))
    broken_result = replace(result, records=(broken_record, *result.records[1:]))
    with pytest.raises(Gold10BenchmarkError, match="RRF evidence"):
        benchmark._validate_mode_result(broken_result, dataset)


@pytest.mark.parametrize(
    "records",
    [
        lambda values: (*values[:-1], values[0]),
        lambda values: (values[1], values[0], *values[2:]),
        lambda values: (replace(values[0], question_id="Q11"), *values[1:]),
    ],
    ids=("duplicate-q1-omit-q10", "order-drift", "unknown-question"),
)
def test_mode_result_requires_exact_unique_ordered_q1_through_q10(
    records: Any,
) -> None:
    dataset, _index, run = _run()
    result = run.modes[MODE_BM25]
    broken = replace(result, records=tuple(records(result.records)))
    with pytest.raises(Gold10BenchmarkError, match="exactly one ordered record"):
        benchmark._validate_mode_result(broken, dataset)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda index: index.runtime.pop("query_embedding_dtype_observed"), "schema"),
        (
            lambda index: index.runtime.__setitem__("unexpected", "value"),
            "schema",
        ),
        (
            lambda index: index.runtime.__setitem__("pytorch_intra_op_threads_observed", 2),
            "intra_op",
        ),
        (
            lambda index: index.runtime.__setitem__("pytorch_inter_op_threads_observed", 2),
            "inter_op",
        ),
        (
            lambda index: index.runtime["model_parameter_dtype_observed"].__setitem__(
                "query_encoder", "torch.float16"
            ),
            "parameter dtypes",
        ),
        (
            lambda index: index.runtime.__setitem__("query_embedding_dtype_observed", "float64"),
            "query embedding dtype",
        ),
        (
            lambda index: index.runtime.__setitem__(
                "document_embedding_index_dtype_observed", "float64"
            ),
            "document embedding/index dtype",
        ),
        (
            lambda index: index.runtime.__setitem__("dense_index_memory_bytes", 1),
            "dense index memory",
        ),
        (lambda index: index.runtime.pop("dense_index_memory_bytes"), "schema"),
        (lambda index: setattr(index, "device", "cuda"), "device"),
        (lambda index: delattr(index, "device"), "configuration evidence"),
        (lambda index: setattr(index, "dimensions", 384), "dimensions"),
        (lambda index: setattr(index, "query_batch_size", 2), "batch sizes"),
        (lambda index: delattr(index, "query_batch_size"), "configuration evidence"),
        (lambda index: setattr(index, "document_batch_size", 16), "batch sizes"),
    ],
)
def test_runtime_provenance_fails_closed_on_missing_or_wrong_values(
    mutation: Any,
    message: str,
) -> None:
    dataset = _dataset()
    index = _FakeMedCPT(dataset.document_ids)
    mutation(index)
    with pytest.raises(Gold10BenchmarkError, match=message):
        benchmark._validated_medcpt_runtime_provenance(index)


def test_duplicate_json_keys_and_malformed_utf8_fail_closed() -> None:
    with pytest.raises(Gold10BenchmarkError, match="duplicate JSON key"):
        benchmark._strict_json(b'{"a":1,"a":2}', label="test")
    with pytest.raises(Gold10BenchmarkError, match="strict UTF-8 JSON"):
        benchmark._strict_json(b'{"a":"\xff"}', label="test")


def test_qrels_reject_duplicate_pairs_bad_header_and_noncanonical_encoding() -> None:
    with pytest.raises(Gold10BenchmarkError, match="duplicate"):
        benchmark._parse_qrels(_qrels_bytes(duplicate_last=True))
    malformed_header = _qrels_bytes().replace(b"question_id", b"question", 1)
    with pytest.raises(Gold10BenchmarkError, match="header"):
        benchmark._parse_qrels(malformed_header)
    mixed = _qrels_bytes().replace(b"\n", b"\r\n", 1)
    with pytest.raises(Gold10BenchmarkError, match="mixed or bare-CR"):
        benchmark._parse_qrels(mixed)


def test_qrels_adjudication_grade_note_and_corpus_identity_must_match() -> None:
    dataset = _dataset()
    documents = {document.retrieval_unit_id: document for document in dataset.documents}
    questions: list[dict[str, Any]] = []
    rows: list[dict[str, str]] = []
    for question in dataset.questions:
        candidates = []
        for ordinal, document in enumerate(dataset.documents, start=1):
            grade = question.judgments[document.retrieval_unit_id]
            candidates.append(
                {
                    "candidate_ordinal": ordinal,
                    "retrieval_unit_id": document.retrieval_unit_id,
                    "owner_relevance_grade": grade,
                    "owner_adjudication_notes": "note",
                }
            )
            rows.append(
                {
                    "question_id": question.question_id,
                    "retrieval_unit_id": document.retrieval_unit_id,
                    "relevance_grade": str(grade),
                    "source": document.source,
                    "title": document.title,
                    "adjudication_note": "note",
                }
            )
        questions.append(
            {
                "question_id": question.question_id,
                "question": question.text,
                "candidates": candidates,
            }
        )
    adjudication = {"questions": questions}
    rows[0]["adjudication_note"] = "drift"
    with pytest.raises(Gold10BenchmarkError, match="differ"):
        benchmark._reconcile_questions(adjudication, rows, documents)


def test_input_path_drift_fails_before_content_is_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "exact"
    owner = root / "owner-adjudication"
    owner.mkdir(parents=True)
    canonical = Gold10InputPaths(
        root / "corpus-manifest.json",
        root / "blinded-adjudication-packet.json",
        owner / "gold10-authoritative-qrels-v2.tsv",
        owner / "gold10-authoritative-adjudication-v2.json",
        owner / "gold10-authoritative-metric-contract-v1.json",
    )
    for path in (
        canonical.corpus,
        canonical.packet,
        canonical.qrels,
        canonical.adjudication,
        canonical.contract,
    ):
        path.write_bytes(b"")
    wrong = tmp_path / "wrong.json"
    wrong.write_bytes(b"")
    monkeypatch.setattr(benchmark, "CANONICAL_INPUT_ROOT", root)
    with pytest.raises(Gold10BenchmarkError, match="path differs"):
        benchmark._read_exact_inputs(replace(canonical, corpus=wrong))


def test_exact_input_path_with_tampered_bytes_fails_hash_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "exact"
    owner = root / "owner-adjudication"
    owner.mkdir(parents=True)
    paths = Gold10InputPaths(
        root / "corpus-manifest.json",
        root / "blinded-adjudication-packet.json",
        owner / "gold10-authoritative-qrels-v2.tsv",
        owner / "gold10-authoritative-adjudication-v2.json",
        owner / "gold10-authoritative-metric-contract-v1.json",
    )
    for path in (paths.corpus, paths.packet, paths.qrels, paths.adjudication, paths.contract):
        path.write_bytes(b"tampered")
    monkeypatch.setattr(benchmark, "CANONICAL_INPUT_ROOT", root)
    with pytest.raises(Gold10BenchmarkError, match="identity drifted"):
        benchmark._read_exact_inputs(paths)


def test_save_is_canonical_no_clobber_and_records_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, index, run = _run()
    output = tmp_path / "benchmark-001"
    monkeypatch.setattr(benchmark, "BENCHMARK_OUTPUT_ROOT", output)
    monkeypatch.setattr(
        benchmark,
        "_runtime_identity",
        lambda: {"python": "3.12.13", "platform": "test", "processor": "test", "packages": {}},
    )
    monkeypatch.setattr(benchmark, "_rebind_dataset_inputs", lambda value: value)
    saved = save_benchmark_run(
        run,
        dataset,
        index,
        output,
        executed_at_utc=datetime(2026, 8, 16, tzinfo=UTC),
    )
    manifest_bytes = (saved / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    assert (saved / "manifest.sha256").read_text(encoding="ascii") == f"{digest}  manifest.json\n"
    assert manifest["run_id"] == "M2-005-GOLD10-V2-BENCHMARK-001"
    assert manifest["configuration"]["modes"] == list(MODES)
    assert manifest["configuration"]["medcpt"]["query_batch_size"] == 1
    assert manifest["configuration"]["medcpt"]["document_batch_size"] == 8
    assert manifest["model_identity"]["runtime_provenance"] == {
        **index.runtime,
        "device": "cpu",
        "embedding_dimensions": 768,
        "query_batch_size": 1,
        "document_batch_size": 8,
    }
    assert manifest["execution_policy"]["network_operations"] == 0
    assert len(manifest["corpus_documents"]) == 65
    assert len(manifest["output_artifacts"]) == 3
    with pytest.raises(Gold10BenchmarkError, match="new absent"):
        save_benchmark_run(run, dataset, index, output)


def test_cli_requires_all_exact_external_arguments() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_cli_rejects_existing_output_before_any_input_or_model_load(
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
        "--adjudication",
        str(tmp_path / "missing-adjudication"),
        "--metric-contract",
        str(tmp_path / "missing-contract"),
        "--model-manifest",
        str(tmp_path / "missing-model"),
        "--model-cache",
        str(tmp_path / "missing-cache"),
        "--output-root",
        str(output),
    ]
    with pytest.raises(Gold10BenchmarkError, match="new absent"):
        main(arguments)
