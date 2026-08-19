"""Exact offline M2-009 Dev-40 source-scope router execution."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from evaluation import dev40_benchmark as benchmark
from evaluation.dev40_benchmark import (
    ADJUDICATION_PROVENANCE,
    CORPUS_SIZE,
    MODE_BM25,
    MODE_MEDCPT,
    MODE_RRF,
    QUESTION_IDS,
    RANKING_METRIC_QUESTION_IDS,
    SOURCE_STATE_QUESTION_IDS,
    ArtifactIdentity,
    Dev40BenchmarkDataset,
    Dev40BenchmarkError,
    Dev40BenchmarkRunner,
    MedCPTSearchIndex,
    QueryResult,
)
from medevidence.domain.scope import SourceType
from medevidence.retrieval.contracts import RetrievalMode
from medevidence.retrieval.source_scope_routing import select_retrieval_mode

WORK_ITEM: Final = "M2-009-SOURCE-SCOPE-ROUTER"
SCHEMA_VERSION: Final = "medevidence.m2_009.dev40_routed_execution.v1"
RUN_ID: Final = "M2-009-SOURCE-SCOPE-ROUTER-DEV40-EXECUTION-001"
BASELINE_MAIN: Final = "3199960f74a312fa23f1d99cfd8bf382bf7933df"

M2_006_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-006-MEDEVIDENCE-DEV40")
M2_008_ROOT: Final = Path(
    r"D:\Projects\medevidence-external-evidence\M2-008-QUERY-SOURCE-ROUTING-PLANNING"
)
M2_009_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-009-SOURCE-SCOPE-ROUTER")
M2_006_MANIFEST_PATH: Final = M2_006_ROOT / "benchmark-001" / "manifest.json"
ROUTING_CONTRACT_PATH: Final = M2_008_ROOT / "routing-contract-001-successor-001.json"
ROUTING_VALIDATION_PATH: Final = M2_008_ROOT / "routing-contract-validation-001-successor-001.json"
STAGE_A_REPLAY_MANIFEST_PATH: Final = M2_008_ROOT / "replay-001-successor-002" / "manifest.json"
STAGE_A_ROUTED_PATH: Final = M2_008_ROOT / "replay-001-successor-002" / "per-question-routed.jsonl"
OWNER_EXCEPTION_CLOSURE_PATH: Final = M2_008_ROOT / "owner-exception-closure-001.json"
OUTPUT_ROOT: Final = M2_009_ROOT / "routed-execution-001"

M2_006_MANIFEST_IDENTITY: Final = (
    93871,
    "0258c25d986bdb084ff6f87af87fac18a389cc1aceb1c57c509fe2ae4d29f14b",
)
ROUTING_CONTRACT_IDENTITY: Final = (
    16570,
    "d62556c1e1fa5ca7fbd304a2e4cbe87f7f4e455c5e7a2d388342a7ace714a596",
)
ROUTING_VALIDATION_IDENTITY: Final = (
    2575,
    "ae142d861a434315ffde2155ca4f5d4ea5d5e034ce28e949854cec2160478e4b",
)
STAGE_A_REPLAY_MANIFEST_IDENTITY: Final = (
    5038,
    "4a1c89b0682e3de3f1127afab1f1226406e1ab1ba2296b1dbba91455cbbd362d",
)
STAGE_A_ROUTED_IDENTITY: Final = (
    813943,
    "7aa751bdf6623a12183e2278c8624320b273b4070b88419d0674c34c72f5b6c8",
)
OWNER_EXCEPTION_CLOSURE_IDENTITY: Final = (
    6557,
    "1dec574bc36ab4aeb98d6ed4341b7ae2030e3c1f53d9ba88acb02aeef6c2782f",
)

EXPECTED_ROUTED_METRICS: Final = {
    "nDCG@10": 0.44642304480349304,
    "Recall@5": 0.08614420999984652,
    "Recall@10": 0.16614228425791394,
    "MRR@10": 0.775,
    "DirectHit@10": 1.0,
    "DirectMRR@10": 0.5872549019607842,
}
EXPECTED_DENOMINATORS: Final = {
    "nDCG@10": 20,
    "Recall@5": 20,
    "Recall@10": 20,
    "MRR@10": 20,
    "DirectHit@10": 17,
    "DirectMRR@10": 17,
}
MODE_BY_RETRIEVAL_MODE: Final = {
    RetrievalMode.DENSE: MODE_MEDCPT,
    RetrievalMode.SPARSE: MODE_BM25,
    RetrievalMode.HYBRID_RRF: MODE_RRF,
}
EXPECTED_SCOPE_POLICY: Final = {
    "pubmed_only": ((SourceType.PUBMED,), MODE_MEDCPT),
    "dailymed_only": ((SourceType.DAILYMED,), MODE_BM25),
    "mixed_pubmed_dailymed": ((SourceType.PUBMED, SourceType.DAILYMED), MODE_RRF),
}
EXPECTED_ROUTING_DISTRIBUTION: Final = {
    "pubmed_only": 14,
    "dailymed_only": 5,
    "mixed_pubmed_dailymed": 1,
}
EXPECTED_STAGE_A_REPLAY_DISTRIBUTION: Final = {
    "pubmed_only": 14,
    "dailymed_only": 5,
    "mixed": 1,
}
OUTPUT_FILENAMES: Final = (
    "routing-decisions.json",
    "per-question-routed.jsonl",
    "summary.json",
)


class Dev40SourceScopeRouterError(RuntimeError):
    """Fail-closed M2-009 routing, execution, or persistence error."""


@dataclass(frozen=True, slots=True)
class RoutingEvidencePaths:
    """Exact accepted Stage-A and M2-006 evidence paths."""

    m2_006_manifest: Path
    routing_contract: Path
    routing_validation: Path
    stage_a_replay_manifest: Path
    stage_a_routed: Path
    owner_exception_closure: Path

    @classmethod
    def canonical(cls) -> RoutingEvidencePaths:
        """Return the only authorized evidence paths."""

        return cls(
            m2_006_manifest=M2_006_MANIFEST_PATH,
            routing_contract=ROUTING_CONTRACT_PATH,
            routing_validation=ROUTING_VALIDATION_PATH,
            stage_a_replay_manifest=STAGE_A_REPLAY_MANIFEST_PATH,
            stage_a_routed=STAGE_A_ROUTED_PATH,
            owner_exception_closure=OWNER_EXCEPTION_CLOSURE_PATH,
        )


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """One frozen structured-scope decision; question ID is join metadata only."""

    question_id: str
    source_scope: tuple[SourceType, ...]
    scope_class: str
    benchmark_mode: str | None
    execution: str
    scope_id: str | None
    evidence: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RoutingEvidence:
    """Validated Stage-A contract and selected-component reference evidence."""

    decisions: tuple[RoutingDecision, ...]
    selected_records: Mapping[str, Mapping[str, Any]]
    identities: Mapping[str, ArtifactIdentity]
    m2_006_manifest: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RoutedExecution:
    """One fresh 20-question routed execution with complete rankings."""

    records: tuple[QueryResult, ...]
    decisions: tuple[RoutingDecision, ...]
    retrieval_modes: Mapping[str, str]
    macro_metrics: Mapping[str, float]
    metric_denominators: Mapping[str, int]
    build_timings_seconds: Mapping[str, float]
    source_state: Mapping[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _expected_evidence_specs() -> Mapping[str, tuple[Path, int, str]]:
    return {
        "m2_006_manifest": (M2_006_MANIFEST_PATH, *M2_006_MANIFEST_IDENTITY),
        "routing_contract": (ROUTING_CONTRACT_PATH, *ROUTING_CONTRACT_IDENTITY),
        "routing_validation": (ROUTING_VALIDATION_PATH, *ROUTING_VALIDATION_IDENTITY),
        "stage_a_replay_manifest": (
            STAGE_A_REPLAY_MANIFEST_PATH,
            *STAGE_A_REPLAY_MANIFEST_IDENTITY,
        ),
        "stage_a_routed": (STAGE_A_ROUTED_PATH, *STAGE_A_ROUTED_IDENTITY),
        "owner_exception_closure": (
            OWNER_EXCEPTION_CLOSURE_PATH,
            *OWNER_EXCEPTION_CLOSURE_IDENTITY,
        ),
    }


def _read_exact_evidence(paths: RoutingEvidencePaths) -> dict[str, tuple[bytes, ArtifactIdentity]]:
    supplied = asdict(paths)
    result: dict[str, tuple[bytes, ArtifactIdentity]] = {}
    for name, (
        expected_path,
        expected_bytes,
        expected_sha256,
    ) in _expected_evidence_specs().items():
        path = Path(supplied[name])
        if path.resolve(strict=False) != expected_path.resolve(strict=False):
            raise Dev40SourceScopeRouterError(f"{name} path differs from the accepted identity")
        try:
            data = path.read_bytes()
        except OSError as error:
            raise Dev40SourceScopeRouterError(f"cannot read accepted {name}") from error
        digest = _sha256(data)
        if len(data) != expected_bytes or digest != expected_sha256:
            raise Dev40SourceScopeRouterError(f"{name} exact bytes or SHA-256 drifted")
        result[name] = (data, ArtifactIdentity(str(path), len(data), digest))
    return result


def _load_json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], benchmark._strict_json(data, label=label))
    except Dev40BenchmarkError as error:
        raise Dev40SourceScopeRouterError(str(error)) from error


def _parse_decisions(contract: Mapping[str, Any]) -> tuple[RoutingDecision, ...]:
    raw_decisions = contract.get("decisions")
    if not isinstance(raw_decisions, list) or len(raw_decisions) != len(QUESTION_IDS):
        raise Dev40SourceScopeRouterError("routing contract must contain exactly 23 decisions")
    decisions: list[RoutingDecision] = []
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            raise Dev40SourceScopeRouterError("routing decision must be an object")
        question_id = raw.get("question_id")
        raw_scope = raw.get("source_scope")
        if not isinstance(question_id, str) or not isinstance(raw_scope, list):
            raise Dev40SourceScopeRouterError(
                "routing decision identity or source scope is invalid"
            )
        try:
            source_scope = tuple(SourceType(value) for value in raw_scope)
        except (TypeError, ValueError) as error:
            raise Dev40SourceScopeRouterError(
                "routing decision source type is unsupported"
            ) from error
        if len(set(source_scope)) != len(source_scope):
            raise Dev40SourceScopeRouterError("routing decision source scope contains duplicates")
        scope_class = raw.get("scope_class")
        execution = raw.get("execution")
        decision = raw.get("decision")
        if not isinstance(scope_class, str) or not isinstance(execution, str):
            raise Dev40SourceScopeRouterError(
                "routing decision scope class or execution is invalid"
            )
        benchmark_mode: str | None
        if question_id in SOURCE_STATE_QUESTION_IDS:
            if (
                scope_class != "source_state_only"
                or execution != "no_retrieval_execution"
                or decision != "source_state_only_no_retrieval"
            ):
                raise Dev40SourceScopeRouterError("source-state routing decision drifted")
            benchmark_mode = None
        else:
            expected = EXPECTED_SCOPE_POLICY.get(scope_class)
            if expected is None or source_scope != expected[0] or decision != expected[1]:
                raise Dev40SourceScopeRouterError("routing decision differs from the frozen policy")
            if execution != "select_persisted_ranking":
                raise Dev40SourceScopeRouterError("routing execution declaration drifted")
            benchmark_mode = expected[1]
        evidence = raw.get("evidence")
        if not isinstance(evidence, dict):
            raise Dev40SourceScopeRouterError("routing decision evidence binding is missing")
        scope_id = raw.get("scope_id")
        if scope_id is not None and not isinstance(scope_id, str):
            raise Dev40SourceScopeRouterError("routing scope identity is invalid")
        decisions.append(
            RoutingDecision(
                question_id=question_id,
                source_scope=source_scope,
                scope_class=scope_class,
                benchmark_mode=benchmark_mode,
                execution=execution,
                scope_id=scope_id,
                evidence=evidence,
            )
        )
    if tuple(item.question_id for item in decisions) != QUESTION_IDS:
        raise Dev40SourceScopeRouterError("routing decisions must follow the exact Dev-40 order")
    distribution = Counter(
        item.scope_class for item in decisions if item.question_id in RANKING_METRIC_QUESTION_IDS
    )
    if dict(distribution) != EXPECTED_ROUTING_DISTRIBUTION:
        raise Dev40SourceScopeRouterError("routing distribution differs from exact 14/5/1")
    return tuple(decisions)


def _parse_stage_a_records(
    data: bytes, decisions: Sequence[RoutingDecision]
) -> dict[str, Mapping[str, Any]]:
    lines = data.splitlines(keepends=True)
    if len(lines) != len(RANKING_METRIC_QUESTION_IDS) or any(
        not line.endswith(b"\n") for line in lines
    ):
        raise Dev40SourceScopeRouterError("Stage-A routed evidence must contain 20 LF records")
    decision_by_id = {item.question_id: item for item in decisions}
    selected: dict[str, Mapping[str, Any]] = {}
    for line in lines:
        payload = _load_json(line, label="Stage-A routed record")
        routing = payload.get("routing")
        record = payload.get("selected_complete_record")
        if not isinstance(routing, dict) or not isinstance(record, dict):
            raise Dev40SourceScopeRouterError("Stage-A routed record schema is incomplete")
        question_id = routing.get("question_id")
        if not isinstance(question_id, str) or question_id in selected:
            raise Dev40SourceScopeRouterError("Stage-A routed record question identity is invalid")
        decision = decision_by_id.get(question_id)
        if (
            decision is None
            or decision.benchmark_mode is None
            or routing.get("contract_sha256") != ROUTING_CONTRACT_IDENTITY[1]
            or routing.get("source_scope") != [source.value for source in decision.source_scope]
            or routing.get("scope_class") != decision.scope_class
            or routing.get("decision") != decision.benchmark_mode
            or record.get("question_id") != question_id
            or record.get("mode") != decision.benchmark_mode
        ):
            raise Dev40SourceScopeRouterError("Stage-A routed record differs from its contract row")
        rankings = record.get("rankings")
        if not isinstance(rankings, list) or len(rankings) != CORPUS_SIZE:
            raise Dev40SourceScopeRouterError("Stage-A routed record lacks a complete ranking")
        selected[question_id] = record
    if tuple(selected) != RANKING_METRIC_QUESTION_IDS:
        raise Dev40SourceScopeRouterError("Stage-A routed records are not the exact 20 questions")
    return selected


def load_routing_evidence(
    paths: RoutingEvidencePaths,
    dataset: Dev40BenchmarkDataset,
) -> RoutingEvidence:
    """Load and reconcile only accepted exact-byte M2-006/M2-008 evidence."""

    raw = _read_exact_evidence(paths)
    parsed = {
        name: _load_json(data, label=name)
        for name, (data, _identity) in raw.items()
        if name != "stage_a_routed"
    }
    contract = parsed["routing_contract"]
    if (
        contract.get("schema") != "medevidence.m2_008.routing_contract.successor_001.v1"
        or contract.get("status") != "FROZEN_PRE_REPLAY_SUCCESSOR_001"
        or contract.get("baseline") != {"commit": BASELINE_MAIN, "ref": "main"}
        or contract.get("denominators")
        != {
            "broad_metric_questions": 20,
            "direct_metric_questions": 17,
            "source_state_questions": 3,
            "total_decisions": 23,
        }
        or contract.get("ranking_inputs_accessed_during_freeze") is not False
    ):
        raise Dev40SourceScopeRouterError("routing contract authority or denominators drifted")
    decisions = _parse_decisions(contract)
    validation = parsed["routing_validation"]
    if (
        validation.get("status") != "PASS_PRE_REPLAY_SUCCESSOR_001"
        or validation.get("contract_binding", {}).get("sha256") != ROUTING_CONTRACT_IDENTITY[1]
        or validation.get("assertions", {}).get("routing_distribution")
        != EXPECTED_ROUTING_DISTRIBUTION
    ):
        raise Dev40SourceScopeRouterError("routing contract validation is not exact PASS evidence")
    replay_manifest = parsed["stage_a_replay_manifest"]
    if (
        replay_manifest.get("routing_contract", {}).get("sha256") != ROUTING_CONTRACT_IDENTITY[1]
        or replay_manifest.get("denominators") != {"broad": 20, "direct": 17}
        or replay_manifest.get("routing_distribution") != EXPECTED_STAGE_A_REPLAY_DISTRIBUTION
        or replay_manifest.get("m2_007_nonintegrable_executable_provenance_used") is not False
    ):
        raise Dev40SourceScopeRouterError("accepted Stage-A replay manifest drifted")
    replay_artifacts = {
        item.get("filename"): item.get("sha256")
        for item in replay_manifest.get("output_artifacts", [])
        if isinstance(item, dict)
    }
    if replay_artifacts.get("per-question-routed.jsonl") != STAGE_A_ROUTED_IDENTITY[1]:
        raise Dev40SourceScopeRouterError("Stage-A replay does not bind the selected rankings")
    closure = parsed["owner_exception_closure"]
    required_markers = {
        "M2-008_TECHNICAL_REPLAY_ACCEPTED",
        "M2-008_OWNER_EXCEPTION_ACCEPTED_READONLY_GIT_METADATA",
        "M2-008_COMPLETE_WITH_DISCLOSED_GOVERNANCE_EXCEPTION",
        "READY_FOR_M2-009_SOURCE_SCOPE_ROUTER",
    }
    if (
        closure.get("status") != "M2-008_COMPLETE_WITH_DISCLOSED_GOVERNANCE_EXCEPTION"
        or set(closure.get("markers", [])) != required_markers
        or closure.get("stage_b_authorization", {}).get("authorized") is not True
        or closure.get("accepted_technical_replay", {}).get("metrics") != EXPECTED_ROUTED_METRICS
    ):
        raise Dev40SourceScopeRouterError("Owner exception closure does not authorize M2-009")
    m2_006_manifest = parsed["m2_006_manifest"]
    if (
        m2_006_manifest.get("run_id") != "M2-006-MEDEVIDENCE-DEV40-BENCHMARK-001"
        or m2_006_manifest.get("schema_version") != "medevidence.dev40.benchmark.v1"
        or m2_006_manifest.get("adjudication", {}).get("ranking_execution_question_count") != 20
    ):
        raise Dev40SourceScopeRouterError("M2-006 benchmark manifest identity is invalid")
    manifest_inputs = m2_006_manifest.get("input_identities")
    if not isinstance(manifest_inputs, dict):
        raise Dev40SourceScopeRouterError("M2-006 manifest input identities are missing")
    for name, identity in dataset.input_identities.items():
        saved = manifest_inputs.get(name)
        if not isinstance(saved, dict) or (saved.get("bytes"), saved.get("sha256")) != (
            identity.bytes,
            identity.sha256,
        ):
            raise Dev40SourceScopeRouterError("M2-006 manifest and dataset identities differ")
    selected = _parse_stage_a_records(raw["stage_a_routed"][0], decisions)
    return RoutingEvidence(
        decisions=decisions,
        selected_records=selected,
        identities={name: identity for name, (_data, identity) in raw.items()},
        m2_006_manifest=m2_006_manifest,
    )


def _without_latency(record: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(record)
    value.pop("latency_ms", None)
    return value


def _validate_selected_component(
    record: QueryResult,
    expected: Mapping[str, Any],
) -> None:
    if _canonical_json_bytes(_without_latency(asdict(record))) != _canonical_json_bytes(
        _without_latency(expected)
    ):
        raise Dev40SourceScopeRouterError(
            f"fresh routed result for {record.question_id} differs from Stage-A selected component"
        )


def _validate_routed_execution(
    run: RoutedExecution,
    dataset: Dev40BenchmarkDataset,
    evidence: RoutingEvidence,
) -> None:
    if tuple(record.question_id for record in run.records) != RANKING_METRIC_QUESTION_IDS:
        raise Dev40SourceScopeRouterError("routed execution must contain the exact 20 questions")
    if run.decisions != evidence.decisions:
        raise Dev40SourceScopeRouterError("routed execution decisions differ from frozen evidence")
    questions = {question.question_id: question for question in dataset.questions}
    decisions = {decision.question_id: decision for decision in evidence.decisions}
    expected_ids = set(dataset.document_ids)
    for record in run.records:
        question = questions[record.question_id]
        decision = decisions[record.question_id]
        if decision.benchmark_mode != record.mode:
            raise Dev40SourceScopeRouterError("routed record mode differs from frozen decision")
        ranking = [(entry.retrieval_unit_id, entry.score) for entry in record.rankings]
        benchmark._validate_ranking(ranking, expected_ids, label=record.mode)
        if record.metrics != benchmark._query_metrics(ranking, question):
            raise Dev40SourceScopeRouterError("routed per-question metrics do not recompute")
        expected_components = {MODE_BM25, MODE_MEDCPT} if record.mode == MODE_RRF else {record.mode}
        if any(
            set(entry.component_scores) != expected_components
            or set(entry.component_ranks) != expected_components
            for entry in record.rankings
        ):
            raise Dev40SourceScopeRouterError("routed component provenance is incomplete")
        _validate_selected_component(record, evidence.selected_records[record.question_id])
    metrics, denominators = benchmark._macro_metrics(run.records)
    if dict(run.macro_metrics) != metrics or dict(run.metric_denominators) != denominators:
        raise Dev40SourceScopeRouterError("routed macro metrics do not recompute")
    if dict(run.macro_metrics) != EXPECTED_ROUTED_METRICS:
        raise Dev40SourceScopeRouterError("routed metrics differ from accepted Stage-A values")
    if dict(run.metric_denominators) != EXPECTED_DENOMINATORS:
        raise Dev40SourceScopeRouterError("routed metric denominators differ from 20/17")
    q15 = next(record for record in run.records if record.question_id == "Q15")
    if (
        q15.mode != MODE_BM25
        or q15.metrics["DirectHit@10"] != 1.0
        or q15.metrics["DirectMRR@10"] != 1.0
    ):
        raise Dev40SourceScopeRouterError("Q15 BM25 direct-answer advantage was not preserved")
    if set(run.retrieval_modes) != set(RANKING_METRIC_QUESTION_IDS):
        raise Dev40SourceScopeRouterError("production retrieval-mode evidence is incomplete")
    retrieval_mode_by_benchmark_mode = {
        mode: retrieval_mode.value for retrieval_mode, mode in MODE_BY_RETRIEVAL_MODE.items()
    }
    if any(
        run.retrieval_modes[record.question_id] != retrieval_mode_by_benchmark_mode[record.mode]
        for record in run.records
    ):
        raise Dev40SourceScopeRouterError("production and benchmark mode evidence differs")
    if set(run.build_timings_seconds) != {MODE_BM25, MODE_MEDCPT, MODE_RRF} or any(
        value < 0.0 or not math.isfinite(value) for value in run.build_timings_seconds.values()
    ):
        raise Dev40SourceScopeRouterError("build timing evidence is incomplete")
    if run.build_timings_seconds[MODE_RRF] != (
        run.build_timings_seconds[MODE_BM25] + run.build_timings_seconds[MODE_MEDCPT]
    ):
        raise Dev40SourceScopeRouterError("RRF build timing is not the exact component sum")


class Dev40SourceScopeRouterRunner:
    """Execute one frozen production-selected retrieval mode per Dev-40 question."""

    def __init__(
        self,
        dataset: Dev40BenchmarkDataset,
        medcpt_index: MedCPTSearchIndex,
        evidence: RoutingEvidence,
        *,
        medcpt_build_seconds: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.dataset = dataset
        self.evidence = evidence
        self._clock = clock
        self._benchmark = Dev40BenchmarkRunner(
            dataset,
            medcpt_index,
            medcpt_build_seconds=medcpt_build_seconds,
            clock=clock,
        )

    def run(self) -> RoutedExecution:
        """Run exactly 20 production-selected modes without routing source-state cases."""

        decision_by_id = {decision.question_id: decision for decision in self.evidence.decisions}
        records: list[QueryResult] = []
        retrieval_modes: dict[str, str] = {}
        for question in self.dataset.questions:
            decision = decision_by_id[question.question_id]
            if not question.ranking_metric_eligible:
                if question.question_id not in SOURCE_STATE_QUESTION_IDS:
                    raise Dev40SourceScopeRouterError("unexpected non-ranking question")
                continue
            selected_mode = select_retrieval_mode(decision.source_scope)
            try:
                benchmark_mode = MODE_BY_RETRIEVAL_MODE[selected_mode]
            except KeyError as error:
                raise Dev40SourceScopeRouterError(
                    "production selector returned a forbidden mode"
                ) from error
            if benchmark_mode != decision.benchmark_mode:
                raise Dev40SourceScopeRouterError(
                    "production selector differs from frozen contract"
                )
            started = self._clock()
            ranking, components = self._benchmark._search_mode(benchmark_mode, question.text)
            latency_ms = (self._clock() - started) * 1000.0
            if latency_ms < 0.0 or not math.isfinite(latency_ms):
                raise Dev40SourceScopeRouterError(
                    "query clock moved backwards or became non-finite"
                )
            record = QueryResult(
                question_id=question.question_id,
                question=question.text,
                mode=benchmark_mode,
                ranking_metric_eligible=question.ranking_metric_eligible,
                direct_answer_eligible=question.direct_answer_eligible,
                metric_exclusion_reason=question.metric_exclusion_reason,
                latency_ms=latency_ms,
                metrics=benchmark._query_metrics(ranking, question),
                rankings=benchmark._ranking_entries(ranking, question, components),
            )
            records.append(record)
            retrieval_modes[question.question_id] = selected_mode.value
        metrics, denominators = benchmark._macro_metrics(records)
        result = RoutedExecution(
            records=tuple(records),
            decisions=self.evidence.decisions,
            retrieval_modes=retrieval_modes,
            macro_metrics=metrics,
            metric_denominators=denominators,
            build_timings_seconds=self._benchmark.build_timings_seconds,
            source_state=_source_state(),
        )
        _validate_routed_execution(result, self.dataset, self.evidence)
        return result


def _source_state() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    relative_paths = (
        "evaluation/dev40_source_scope_router.py",
        "evaluation/run_dev40_source_scope_router.py",
        "evaluation/dev40_benchmark.py",
        "evaluation/medcpt.py",
        "evaluation/metrics.py",
        "src/medevidence/domain/scope.py",
        "src/medevidence/retrieval/contracts.py",
        "src/medevidence/retrieval/source_scope_routing.py",
    )
    files: dict[str, dict[str, int | str]] = {}
    for relative in relative_paths:
        data = (repository / relative).read_bytes()
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
    return {"binding": "exact current production and evaluation source bytes", "files": files}


def _runtime_identity() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("numpy", "torch", "transformers"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise Dev40SourceScopeRouterError(
                f"required runtime package {name!r} is missing"
            ) from error
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "packages": packages,
        "process_id": os.getpid(),
    }


def _artifact_record(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    return {"filename": path.name, "bytes": len(data), "sha256": _sha256(data)}


def validate_output_root(output_root: str | Path) -> Path:
    """Require the exact absent external routed-execution-001 path."""

    root = Path(output_root)
    if not root.is_absolute() or root.exists() or root.is_symlink():
        raise Dev40SourceScopeRouterError("output root must be a new absent absolute path")
    repository = Path(__file__).resolve().parents[1]
    try:
        parent = root.parent.resolve(strict=True)
    except OSError as error:
        raise Dev40SourceScopeRouterError("output parent must already exist") from error
    candidate = (parent / root.name).resolve(strict=False)
    if candidate != OUTPUT_ROOT.resolve(strict=False):
        raise Dev40SourceScopeRouterError("output root differs from routed-execution-001")
    try:
        candidate.relative_to(repository)
    except ValueError:
        pass
    else:
        raise Dev40SourceScopeRouterError("routed results must remain outside the repository")
    if candidate.parent != parent or not root.name or root.name in {".", ".."}:
        raise Dev40SourceScopeRouterError("output root is not one exact child of its parent")
    staging = parent / f".{root.name}.pending"
    if staging.exists() or staging.is_symlink():
        raise Dev40SourceScopeRouterError("stale routed output transaction exists")
    return candidate


def _routing_decisions_payload(run: RoutedExecution) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.routing_decisions",
        "work_item": WORK_ITEM,
        "routing_contract_sha256": ROUTING_CONTRACT_IDENTITY[1],
        "distribution": EXPECTED_ROUTING_DISTRIBUTION,
        "selector_call_count": len(run.records),
        "decisions": [
            {
                "question_id": decision.question_id,
                "scope_id": decision.scope_id,
                "scope_class": decision.scope_class,
                "source_scope": [source.value for source in decision.source_scope],
                "execution": (
                    "fresh_offline_retrieval"
                    if decision.benchmark_mode is not None
                    else decision.execution
                ),
                "production_retrieval_mode": run.retrieval_modes.get(decision.question_id),
                "benchmark_mode": decision.benchmark_mode,
                "contract_evidence": dict(decision.evidence),
            }
            for decision in run.decisions
        ],
    }


def _query_timing(records: Sequence[QueryResult]) -> dict[str, Any]:
    values = [record.latency_ms for record in records]
    by_mode: dict[str, Any] = {}
    for mode in (MODE_BM25, MODE_MEDCPT, MODE_RRF):
        selected = [record.latency_ms for record in records if record.mode == mode]
        by_mode[mode] = {
            "question_count": len(selected),
            "mean": sum(selected) / len(selected),
            "p50": benchmark.percentile(selected, 0.50),
            "p95": benchmark.percentile(selected, 0.95),
            "total": sum(selected),
        }
    return {
        "overall": {
            "question_count": len(values),
            "mean": sum(values) / len(values),
            "p50": benchmark.percentile(values, 0.50),
            "p95": benchmark.percentile(values, 0.95),
            "total": sum(values),
        },
        "by_selected_mode": by_mode,
    }


def save_routed_execution(
    run: RoutedExecution,
    dataset: Dev40BenchmarkDataset,
    evidence: RoutingEvidence,
    medcpt_index: MedCPTSearchIndex,
    evidence_paths: RoutingEvidencePaths,
    output_root: str | Path,
    *,
    executed_at_utc: datetime | None = None,
) -> Path:
    """Exact-byte rebind and atomically retain the fresh routed execution."""

    _validate_routed_execution(run, dataset, evidence)
    if dataset.adjudication_provenance != ADJUDICATION_PROVENANCE:
        raise Dev40SourceScopeRouterError("adjudication provenance is not exact")
    if dict(run.source_state) != _source_state():
        raise Dev40SourceScopeRouterError("production or evaluation source bytes drifted")
    rebound_dataset = benchmark._rebind_dataset_inputs(dataset)
    if rebound_dataset != dataset:
        raise Dev40SourceScopeRouterError("Dev-40 inputs drifted during execution")
    rebound_evidence = load_routing_evidence(evidence_paths, dataset)
    if rebound_evidence != evidence:
        raise Dev40SourceScopeRouterError("routing evidence drifted during execution")
    if medcpt_index.artifacts is None:
        raise Dev40SourceScopeRouterError("verified MedCPT artifact provenance is required")
    artifact_provenance = medcpt_index.artifacts.provenance()
    expected_model = evidence.m2_006_manifest.get("model_identity")
    if not isinstance(expected_model, dict) or artifact_provenance != expected_model.get(
        "artifact_provenance"
    ):
        raise Dev40SourceScopeRouterError("MedCPT model/cache identity differs from M2-006")
    model_runtime = benchmark._validated_medcpt_runtime_provenance(medcpt_index)
    candidate = validate_output_root(output_root)
    observed = executed_at_utc or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise Dev40SourceScopeRouterError("execution timestamp must be timezone-aware")
    staging = candidate.parent / f".{candidate.name}.pending"
    staging.mkdir()
    try:
        decisions_path = staging / OUTPUT_FILENAMES[0]
        decisions_path.write_bytes(_canonical_json_bytes(_routing_decisions_payload(run)))
        per_question_path = staging / OUTPUT_FILENAMES[1]
        decision_by_id = {item.question_id: item for item in run.decisions}
        with per_question_path.open("wb") as handle:
            for record in run.records:
                decision = decision_by_id[record.question_id]
                handle.write(
                    _canonical_json_bytes(
                        {
                            "schema_version": f"{SCHEMA_VERSION}.routed_question",
                            "work_item": WORK_ITEM,
                            "routing": {
                                "contract_sha256": ROUTING_CONTRACT_IDENTITY[1],
                                "question_id": record.question_id,
                                "scope_class": decision.scope_class,
                                "source_scope": [source.value for source in decision.source_scope],
                                "production_retrieval_mode": run.retrieval_modes[
                                    record.question_id
                                ],
                                "benchmark_mode": record.mode,
                            },
                            "result": asdict(record),
                        }
                    )
                )
        summary_path = staging / OUTPUT_FILENAMES[2]
        summary_path.write_bytes(
            _canonical_json_bytes(
                {
                    "schema_version": f"{SCHEMA_VERSION}.summary",
                    "work_item": WORK_ITEM,
                    "dataset": "MEDEVIDENCE_DEV40",
                    "metrics": dict(run.macro_metrics),
                    "expected_stage_a_metrics": EXPECTED_ROUTED_METRICS,
                    "selected_component_equality": True,
                    "denominators": dict(run.metric_denominators),
                    "routing_distribution": EXPECTED_ROUTING_DISTRIBUTION,
                    "q15_bm25_direct_answer_advantage_preserved": True,
                    "timings": {
                        "build_seconds": dict(run.build_timings_seconds),
                        "query_timing_ms": _query_timing(run.records),
                        "limitation": (
                            "machine-local serial timing; not portable production performance"
                        ),
                    },
                    "development_status": (
                        "Descriptive Development-40 evidence only; no statistical superiority, "
                        "production-generalization, release, clinical, or Holdout-20 claim"
                    ),
                }
            )
        )
        artifacts = [_artifact_record(staging / name) for name in OUTPUT_FILENAMES]
        source_state_cases = {
            decision.question_id: {
                "scope_class": decision.scope_class,
                "source_scope": [source.value for source in decision.source_scope],
                "reason": next(
                    question.metric_exclusion_reason
                    for question in dataset.questions
                    if question.question_id == decision.question_id
                ),
                "execution": {
                    "selector_call": False,
                    "ranking": False,
                    "component_ranks_or_scores": False,
                    "metrics": False,
                    "query_timing": False,
                },
            }
            for decision in run.decisions
            if decision.question_id in SOURCE_STATE_QUESTION_IDS
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": RUN_ID,
            "status": "completed_execution_evidence_awaiting_independent_review",
            "work_item": WORK_ITEM,
            "baseline_main": BASELINE_MAIN,
            "dataset": "MEDEVIDENCE_DEV40",
            "development_status": (
                "Descriptive Development-40 evidence only; no statistical superiority, "
                "production-generalization, release, clinical, or Holdout-20 claim"
            ),
            "executed_at_utc": observed.astimezone(UTC).isoformat(),
            "input_identities": {
                "dev40": {
                    name: asdict(identity)
                    for name, identity in sorted(dataset.input_identities.items())
                },
                "m2_006_and_stage_a": {
                    name: asdict(identity) for name, identity in sorted(evidence.identities.items())
                },
            },
            "m2_006_model_identity": evidence.m2_006_manifest["model_identity"],
            "configuration": {
                "routing_contract_sha256": ROUTING_CONTRACT_IDENTITY[1],
                "routing_policy": {
                    "pubmed_only": MODE_MEDCPT,
                    "dailymed_only": MODE_BM25,
                    "mixed_pubmed_dailymed": MODE_RRF,
                },
                "production_mode_mapping": {
                    RetrievalMode.DENSE.value: MODE_MEDCPT,
                    RetrievalMode.SPARSE.value: MODE_BM25,
                    RetrievalMode.HYBRID_RRF.value: MODE_RRF,
                },
                "routing_features": (
                    "structured source scope only; no question text or performance lookup"
                ),
                "parameter_tuning": "none",
                "reranker": "none",
                "bm25": {"k1": benchmark.BM25_K1, "b": benchmark.BM25_B},
                "rrf": {"k": benchmark.RRF_K, "components": [MODE_BM25, MODE_MEDCPT]},
                "medcpt": {
                    "device": benchmark.MEDCPT_DEVICE,
                    "dimensions": benchmark.MEDCPT_DIMENSIONS,
                    "query_batch_size": benchmark.MEDCPT_QUERY_BATCH_SIZE,
                    "document_batch_size": benchmark.MEDCPT_DOCUMENT_BATCH_SIZE,
                },
            },
            "routing_execution": {
                "question_count": len(run.records),
                "distribution": EXPECTED_ROUTING_DISTRIBUTION,
                "selector_call_count": len(run.records),
                "source_state_question_count": len(SOURCE_STATE_QUESTION_IDS),
            },
            "source_state_behavior_cases": source_state_cases,
            "summary": {
                "metrics": dict(run.macro_metrics),
                "denominators": dict(run.metric_denominators),
                "expected_stage_a_metrics": EXPECTED_ROUTED_METRICS,
                "selected_component_equality": True,
                "q15_bm25_direct_answer_advantage_preserved": True,
                "query_timing_ms": _query_timing(run.records),
            },
            "timings": {
                "build_seconds": dict(run.build_timings_seconds),
                "query_latency": "fresh serial wall-clock milliseconds in each per-question record",
                "limitation": "machine-local evidence; not portable production performance",
            },
            "runtime_identity": _runtime_identity(),
            "model_identity": {
                "artifact_provenance": artifact_provenance,
                "runtime_provenance": model_runtime,
            },
            "current_source_state": dict(run.source_state),
            "execution_policy": {
                "network_operations": 0,
                "medical_source_operations": 0,
                "holdout_access": False,
                "model_downloads": 0,
                "package_or_advisory_operations": 0,
                "m2_007_nonintegrable_executable_provenance_used": False,
                "m2_007_artifacts_read": 0,
                "query_execution": "serial_single_process",
                "ranking_questions": len(RANKING_METRIC_QUESTION_IDS),
                "complete_candidate_ranks_per_question": CORPUS_SIZE,
            },
            "output_artifacts": artifacts,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_bytes(_canonical_json_bytes(manifest))
        digest = _sha256(manifest_path.read_bytes())
        (staging / "manifest.sha256").write_text(
            f"{digest}  manifest.json\n", encoding="ascii", newline="\n"
        )
        staging.rename(candidate)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return candidate
