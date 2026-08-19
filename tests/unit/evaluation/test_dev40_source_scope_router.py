from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from evaluation import dev40_benchmark as benchmark
from evaluation import dev40_source_scope_router as routed
from evaluation.dev40_benchmark import (
    ADJUDICATION_PROVENANCE,
    CORPUS_SIZE,
    DIRECT_METRIC_QUESTION_IDS,
    MODE_BM25,
    MODE_MEDCPT,
    MODE_RRF,
    QUESTION_IDS,
    RANKING_METRIC_QUESTION_IDS,
    SOURCE_STATE_QUESTION_IDS,
    ArtifactIdentity,
    Dev40BenchmarkDataset,
    Dev40BenchmarkRunner,
    Dev40Document,
    Dev40Question,
)
from evaluation.dev40_source_scope_router import (
    Dev40SourceScopeRouterError,
    Dev40SourceScopeRouterRunner,
    RoutingDecision,
    RoutingEvidence,
    RoutingEvidencePaths,
    load_routing_evidence,
    save_routed_execution,
)
from evaluation.run_dev40_source_scope_router import OFFLINE_ENVIRONMENT, main

from medevidence.domain.scope import SourceType
from medevidence.retrieval.source_scope_routing import (
    select_retrieval_mode as production_select_retrieval_mode,
)


class _FakeArtifacts:
    def provenance(self) -> dict[str, Any]:
        return {"manifest": {"sha256": "a" * 64}, "repositories": ["query", "article"]}


class _FakeMedCPT:
    def __init__(self, doc_ids: tuple[str, ...]) -> None:
        self.doc_ids = doc_ids
        self.artifacts = _FakeArtifacts()
        self.device = "cpu"
        self.dimensions = 768
        self.query_batch_size = 1
        self.document_batch_size = 8
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        self.queries.append(query)
        return [
            (doc_id, float(len(self.doc_ids) - ordinal))
            for ordinal, doc_id in enumerate(self.doc_ids[:limit])
        ]

    def runtime_provenance(self) -> dict[str, Any]:
        return {
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
            "dense_index_memory_limitation": benchmark.DENSE_INDEX_MEMORY_LIMITATION,
        }


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
        name: ArtifactIdentity(f"D:/external/{name}", 1, str(index) * 64)
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


def _decisions() -> tuple[RoutingDecision, ...]:
    dailymed = {"Q1", "Q2", "Q15", "Q16", "Q18"}
    decisions: list[RoutingDecision] = []
    for question_id in QUESTION_IDS:
        source_scope: tuple[SourceType, ...]
        if question_id == "Q10":
            source_scope = (SourceType.PUBMED, SourceType.DAILYMED)
            scope_class = "mixed_pubmed_dailymed"
            mode: str | None = MODE_RRF
            execution = "select_persisted_ranking"
        elif question_id in dailymed:
            source_scope = (SourceType.DAILYMED,)
            scope_class = "dailymed_only"
            mode = MODE_BM25
            execution = "select_persisted_ranking"
        elif question_id in SOURCE_STATE_QUESTION_IDS:
            source_scope = (SourceType.FAERS,) if question_id == "Q26" else (SourceType.CADEC,)
            scope_class = "source_state_only"
            mode = None
            execution = "no_retrieval_execution"
        else:
            source_scope = (SourceType.PUBMED,)
            scope_class = "pubmed_only"
            mode = MODE_MEDCPT
            execution = "select_persisted_ranking"
        decisions.append(
            RoutingDecision(
                question_id=question_id,
                source_scope=source_scope,
                scope_class=scope_class,
                benchmark_mode=mode,
                execution=execution,
                scope_id=f"scope:{question_id}",
                evidence={"bytes": 1, "path": "D:/evidence", "sha256": "e" * 64},
            )
        )
    return tuple(decisions)


def _reference_evidence(
    dataset: Dev40BenchmarkDataset,
) -> tuple[RoutingEvidence, dict[str, float], _FakeMedCPT]:
    index = _FakeMedCPT(dataset.document_ids)
    all_modes = Dev40BenchmarkRunner(
        dataset,
        index,
        medcpt_build_seconds=0.25,
        clock=_Clock(),
    ).run()
    decisions = _decisions()
    selected: dict[str, dict[str, Any]] = {}
    records = []
    for decision in decisions:
        if decision.benchmark_mode is None:
            continue
        record = next(
            item
            for item in all_modes.modes[decision.benchmark_mode].records
            if item.question_id == decision.question_id
        )
        selected[decision.question_id] = asdict(record)
        records.append(record)
    metrics, _denominators = benchmark._macro_metrics(records)
    evidence = RoutingEvidence(
        decisions=decisions,
        selected_records=selected,
        identities={},
        m2_006_manifest={"model_identity": {"artifact_provenance": index.artifacts.provenance()}},
    )
    return evidence, metrics, index


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _contract_decision(decision: RoutingDecision) -> dict[str, Any]:
    return {
        "question_id": decision.question_id,
        "source_scope": [source.value for source in decision.source_scope],
        "scope_class": decision.scope_class,
        "decision": decision.benchmark_mode or "source_state_only_no_retrieval",
        "execution": decision.execution,
        "scope_id": decision.scope_id,
        "evidence": dict(decision.evidence),
    }


def _write_evidence_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dataset: Dev40BenchmarkDataset,
    evidence: RoutingEvidence,
    metrics: dict[str, float],
) -> RoutingEvidencePaths:
    contract_path = tmp_path / "contract.json"
    contract_path.write_bytes(
        _canonical(
            {
                "schema": "medevidence.m2_008.routing_contract.successor_001.v1",
                "status": "FROZEN_PRE_REPLAY_SUCCESSOR_001",
                "baseline": {"commit": routed.BASELINE_MAIN, "ref": "main"},
                "denominators": {
                    "broad_metric_questions": 20,
                    "direct_metric_questions": 17,
                    "source_state_questions": 3,
                    "total_decisions": 23,
                },
                "ranking_inputs_accessed_during_freeze": False,
                "decisions": [_contract_decision(item) for item in evidence.decisions],
            }
        )
    )
    contract_identity = (
        contract_path.stat().st_size,
        hashlib.sha256(contract_path.read_bytes()).hexdigest(),
    )
    stage_records = bytearray()
    for decision in evidence.decisions:
        if decision.benchmark_mode is None:
            continue
        stage_records.extend(
            _canonical(
                {
                    "routing": {
                        "question_id": decision.question_id,
                        "contract_sha256": contract_identity[1],
                        "source_scope": [source.value for source in decision.source_scope],
                        "scope_class": decision.scope_class,
                        "decision": decision.benchmark_mode,
                    },
                    "selected_complete_record": evidence.selected_records[decision.question_id],
                }
            )
        )
    stage_path = tmp_path / "stage.jsonl"
    stage_path.write_bytes(stage_records)
    stage_identity = (stage_path.stat().st_size, hashlib.sha256(stage_records).hexdigest())
    validation_path = tmp_path / "validation.json"
    validation_path.write_bytes(
        _canonical(
            {
                "status": "PASS_PRE_REPLAY_SUCCESSOR_001",
                "contract_binding": {"sha256": contract_identity[1]},
                "assertions": {"routing_distribution": routed.EXPECTED_ROUTING_DISTRIBUTION},
            }
        )
    )
    replay_path = tmp_path / "replay.json"
    replay_path.write_bytes(
        _canonical(
            {
                "routing_contract": {"sha256": contract_identity[1]},
                "denominators": {"broad": 20, "direct": 17},
                "routing_distribution": routed.EXPECTED_STAGE_A_REPLAY_DISTRIBUTION,
                "m2_007_nonintegrable_executable_provenance_used": False,
                "output_artifacts": [
                    {"filename": "per-question-routed.jsonl", "sha256": stage_identity[1]}
                ],
            }
        )
    )
    closure_path = tmp_path / "closure.json"
    closure_path.write_bytes(
        _canonical(
            {
                "status": "M2-008_COMPLETE_WITH_DISCLOSED_GOVERNANCE_EXCEPTION",
                "markers": [
                    "M2-008_TECHNICAL_REPLAY_ACCEPTED",
                    "M2-008_OWNER_EXCEPTION_ACCEPTED_READONLY_GIT_METADATA",
                    "M2-008_COMPLETE_WITH_DISCLOSED_GOVERNANCE_EXCEPTION",
                    "READY_FOR_M2-009_SOURCE_SCOPE_ROUTER",
                ],
                "stage_b_authorization": {"authorized": True},
                "accepted_technical_replay": {"metrics": metrics},
            }
        )
    )
    m2_path = tmp_path / "m2.json"
    m2_path.write_bytes(
        _canonical(
            {
                "run_id": "M2-006-MEDEVIDENCE-DEV40-BENCHMARK-001",
                "schema_version": "medevidence.dev40.benchmark.v1",
                "adjudication": {"ranking_execution_question_count": 20},
                "input_identities": {
                    name: asdict(identity) for name, identity in dataset.input_identities.items()
                },
                "model_identity": dict(evidence.m2_006_manifest["model_identity"]),
            }
        )
    )
    path_and_identity = {
        "M2_006_MANIFEST": (
            m2_path,
            m2_path.stat().st_size,
            hashlib.sha256(m2_path.read_bytes()).hexdigest(),
        ),
        "ROUTING_CONTRACT": (contract_path, *contract_identity),
        "ROUTING_VALIDATION": (
            validation_path,
            validation_path.stat().st_size,
            hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        ),
        "STAGE_A_REPLAY_MANIFEST": (
            replay_path,
            replay_path.stat().st_size,
            hashlib.sha256(replay_path.read_bytes()).hexdigest(),
        ),
        "STAGE_A_ROUTED": (stage_path, *stage_identity),
        "OWNER_EXCEPTION_CLOSURE": (
            closure_path,
            closure_path.stat().st_size,
            hashlib.sha256(closure_path.read_bytes()).hexdigest(),
        ),
    }
    for prefix, (path, size, digest) in path_and_identity.items():
        monkeypatch.setattr(routed, f"{prefix}_PATH", path)
        monkeypatch.setattr(routed, f"{prefix}_IDENTITY", (size, digest))
    monkeypatch.setattr(routed, "EXPECTED_ROUTED_METRICS", metrics)
    return RoutingEvidencePaths.canonical()


def test_runner_routes_structured_scopes_exactly_once_and_preserves_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    evidence, metrics, _reference_index = _reference_evidence(dataset)
    monkeypatch.setattr(routed, "EXPECTED_ROUTED_METRICS", metrics)
    calls: list[tuple[SourceType, ...]] = []

    def spy(selected_sources: tuple[SourceType, ...]) -> Any:
        calls.append(selected_sources)
        return production_select_retrieval_mode(selected_sources)

    monkeypatch.setattr(routed, "select_retrieval_mode", spy)
    index = _FakeMedCPT(dataset.document_ids)
    run = Dev40SourceScopeRouterRunner(
        dataset,
        index,
        evidence,
        medcpt_build_seconds=0.25,
        clock=_Clock(),
    ).run()

    assert len(calls) == 20
    assert Counter(calls) == {
        (SourceType.PUBMED,): 14,
        (SourceType.DAILYMED,): 5,
        (SourceType.PUBMED, SourceType.DAILYMED): 1,
    }
    assert all(all(type(source) is SourceType for source in sources) for sources in calls)
    assert len(index.queries) == 15
    assert not {
        question.text
        for question in dataset.questions
        if question.question_id in SOURCE_STATE_QUESTION_IDS
    }.intersection(index.queries)
    assert tuple(record.question_id for record in run.records) == RANKING_METRIC_QUESTION_IDS
    assert run.metric_denominators == routed.EXPECTED_DENOMINATORS
    assert run.macro_metrics == metrics
    assert Counter(run.retrieval_modes.values()) == {
        "dense": 14,
        "sparse": 5,
        "hybrid_rrf": 1,
    }
    for record in run.records:
        assert len(record.rankings) == CORPUS_SIZE
        components = {MODE_BM25, MODE_MEDCPT} if record.mode == MODE_RRF else {record.mode}
        assert all(set(entry.component_ranks) == components for entry in record.rankings)
    q15 = next(record for record in run.records if record.question_id == "Q15")
    assert q15.mode == MODE_BM25
    assert q15.metrics["DirectHit@10"] == 1.0
    assert q15.metrics["DirectMRR@10"] == 1.0


def test_exact_evidence_load_rejects_hash_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    evidence, metrics, _index = _reference_evidence(dataset)
    paths = _write_evidence_files(tmp_path, monkeypatch, dataset, evidence, metrics)
    loaded = load_routing_evidence(paths, dataset)
    assert loaded.decisions == evidence.decisions
    assert tuple(loaded.selected_records) == RANKING_METRIC_QUESTION_IDS

    paths.routing_validation.write_bytes(paths.routing_validation.read_bytes() + b" ")
    with pytest.raises(Dev40SourceScopeRouterError, match="drifted"):
        load_routing_evidence(paths, dataset)


def test_selected_component_drift_fails_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    evidence, metrics, _reference_index = _reference_evidence(dataset)
    monkeypatch.setattr(routed, "EXPECTED_ROUTED_METRICS", metrics)
    changed = dict(evidence.selected_records)
    changed_q1 = dict(changed["Q1"])
    changed_q1["mode"] = MODE_MEDCPT
    changed["Q1"] = changed_q1
    broken = replace(evidence, selected_records=changed)
    with pytest.raises(Dev40SourceScopeRouterError, match="selected component"):
        Dev40SourceScopeRouterRunner(
            dataset,
            _FakeMedCPT(dataset.document_ids),
            broken,
            medcpt_build_seconds=0.0,
            clock=_Clock(),
        ).run()


def test_save_is_atomic_no_clobber_and_records_offline_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _dataset()
    evidence, metrics, _reference_index = _reference_evidence(dataset)
    paths = _write_evidence_files(tmp_path, monkeypatch, dataset, evidence, metrics)
    evidence = load_routing_evidence(paths, dataset)
    index = _FakeMedCPT(dataset.document_ids)
    run = Dev40SourceScopeRouterRunner(
        dataset,
        index,
        evidence,
        medcpt_build_seconds=0.25,
        clock=_Clock(),
    ).run()
    output = tmp_path / "routed-execution-001"
    monkeypatch.setattr(routed, "OUTPUT_ROOT", output)
    monkeypatch.setattr(benchmark, "_rebind_dataset_inputs", lambda value: value)
    monkeypatch.setattr(
        routed,
        "_runtime_identity",
        lambda: {"python": "3.12.13", "platform": "test", "processor": "test"},
    )
    with pytest.raises(Dev40SourceScopeRouterError, match="source bytes drifted"):
        save_routed_execution(
            replace(run, source_state={"binding": "drift", "files": {}}),
            dataset,
            evidence,
            index,
            paths,
            output,
        )
    saved = save_routed_execution(
        run,
        dataset,
        evidence,
        index,
        paths,
        output,
        executed_at_utc=datetime(2026, 8, 19, tzinfo=UTC),
    )

    assert {path.name for path in saved.iterdir()} == {
        "routing-decisions.json",
        "per-question-routed.jsonl",
        "summary.json",
        "manifest.json",
        "manifest.sha256",
    }
    manifest_bytes = (saved / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    assert (saved / "manifest.sha256").read_text() == f"{digest}  manifest.json\n"
    assert manifest["status"] == "completed_execution_evidence_awaiting_independent_review"
    assert manifest["routing_execution"] == {
        "question_count": 20,
        "distribution": routed.EXPECTED_ROUTING_DISTRIBUTION,
        "selector_call_count": 20,
        "source_state_question_count": 3,
    }
    assert manifest["execution_policy"] == {
        "network_operations": 0,
        "medical_source_operations": 0,
        "holdout_access": False,
        "model_downloads": 0,
        "package_or_advisory_operations": 0,
        "m2_007_nonintegrable_executable_provenance_used": False,
        "m2_007_artifacts_read": 0,
        "query_execution": "serial_single_process",
        "ranking_questions": 20,
        "complete_candidate_ranks_per_question": 214,
    }
    assert manifest["model_identity"]["artifact_provenance"] == index.artifacts.provenance()
    assert manifest["model_identity"]["runtime_provenance"]["device"] == "cpu"
    assert set(manifest["current_source_state"]["files"]) == {
        "evaluation/dev40_source_scope_router.py",
        "evaluation/run_dev40_source_scope_router.py",
        "evaluation/dev40_benchmark.py",
        "evaluation/medcpt.py",
        "evaluation/metrics.py",
        "src/medevidence/domain/scope.py",
        "src/medevidence/retrieval/contracts.py",
        "src/medevidence/retrieval/source_scope_routing.py",
    }
    assert tuple(manifest["source_state_behavior_cases"]) == SOURCE_STATE_QUESTION_IDS
    assert all(
        not value["execution"]["selector_call"]
        and not value["execution"]["ranking"]
        and not value["execution"]["metrics"]
        for value in manifest["source_state_behavior_cases"].values()
    )
    records = [
        json.loads(line) for line in (saved / "per-question-routed.jsonl").read_text().splitlines()
    ]
    assert len(records) == 20
    assert all(len(record["result"]["rankings"]) == 214 for record in records)
    with pytest.raises(Dev40SourceScopeRouterError, match="new absent"):
        save_routed_execution(run, dataset, evidence, index, paths, output)


def test_cli_rejects_existing_output_before_any_input_or_model_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "routed-execution-001"
    output.mkdir()
    monkeypatch.setattr(routed, "OUTPUT_ROOT", output)
    names = (
        "corpus-manifest",
        "blinded-packet",
        "qrels",
        "nonzero-qrels",
        "adjudication",
        "metric-contract",
        "bundle-manifest",
        "model-manifest",
        "model-cache",
        "m2-006-manifest",
        "routing-contract",
        "routing-validation",
        "stage-a-replay-manifest",
        "stage-a-routed",
        "owner-exception-closure",
    )
    arguments = [item for name in names for item in (f"--{name}", str(tmp_path / name))]
    arguments.extend(("--output-root", str(output)))
    with pytest.raises(Dev40SourceScopeRouterError, match="new absent"):
        main(arguments)
    assert all(os.environ[name] == value for name, value in OFFLINE_ENVIRONMENT.items())
