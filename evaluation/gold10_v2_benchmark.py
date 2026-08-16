"""Exact offline benchmark adapter for the adjudicated Gold-10 V2 corpus."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, Protocol

from evaluation.medcpt import MedCPTIndex
from evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank_at_k
from medevidence.retrieval.core import BM25Index, component_ranks, reciprocal_rank_fusion

DATASET: Final = "MEDEVIDENCE_GOLD10_V2"
SCHEMA_VERSION: Final = "medevidence.gold10.v2.benchmark.v1"
CANONICAL_INPUT_ROOT: Final = Path(
    r"D:\Projects\medevidence-external-evidence\M2-005-MEDEVIDENCE-GOLD10-V2"
)
BENCHMARK_RUN_ID: Final = "M2-005-GOLD10-V2-BENCHMARK-001"
BENCHMARK_OUTPUT_ROOT: Final = CANONICAL_INPUT_ROOT / "benchmark-001"

CORPUS_BYTES: Final = 340_963
CORPUS_SHA256: Final = "716b35ae8cb0e4a843a9e67e44f75e3b2577bec5859940087ad1c3976e38e459"
PACKET_BYTES: Final = 1_920_236
PACKET_SHA256: Final = "14bbcf0b51e56ad2eec377a129a491006626893e13220d151379e0f3ff1e2974"
QRELS_BYTES: Final = 154_526
QRELS_SHA256: Final = "88900032e0051a3a3b2b6dae919a96054728b4a2cffdb2e2e6a6c858aded6a93"
ADJUDICATION_BYTES: Final = 2_074_837
ADJUDICATION_SHA256: Final = "d0dfc03d6665ff49773252794ee2aad881a2d1af86abac6311b5cb448b552acb"
CONTRACT_BYTES: Final = 1_470
CONTRACT_SHA256: Final = "c5a46b6b684fca02c516934ac87abfb0ba71decf4096c64456de634e441f7796"

MODE_BM25: Final = "BM25"
MODE_MEDCPT: Final = "MedCPT"
MODE_RRF: Final = "RRF(BM25,MedCPT)"
MODES: Final = (MODE_BM25, MODE_MEDCPT, MODE_RRF)
MODE_FILENAMES: Final = {
    MODE_BM25: "per-query-bm25.jsonl",
    MODE_MEDCPT: "per-query-medcpt.jsonl",
    MODE_RRF: "per-query-rrf-bm25-medcpt.jsonl",
}
BM25_K1: Final = 0.9
BM25_B: Final = 0.4
RRF_K: Final = 60
CORPUS_SIZE: Final = 65
QUESTION_COUNT: Final = 10
TOP_K: Final = 10
MEDCPT_DIMENSIONS: Final = 768
MEDCPT_QUERY_BATCH_SIZE: Final = 1
MEDCPT_DOCUMENT_BATCH_SIZE: Final = 8
MEDCPT_DEVICE: Final = "cpu"
DENSE_INDEX_MEMORY_BYTES: Final = CORPUS_SIZE * MEDCPT_DIMENSIONS * 4
DENSE_INDEX_MEMORY_LIMITATION: Final = (
    "Document embedding matrix only; not Python process RSS, allocator overhead, "
    "model memory, or total application memory."
)
ADJUDICATION_PROVENANCE: Final = "blinded AI adjudication, Owner-confirmed"

CORPUS_TOP_FIELDS: Final = {
    "counts",
    "dataset",
    "items",
    "schema_version",
    "status",
    "structural_provenance",
}
PACKET_TOP_FIELDS: Final = {
    "authoritative_qrels_status",
    "corpus_manifest_sha256",
    "dataset",
    "ordering",
    "questions",
    "schema_version",
}
ADJUDICATION_TOP_FIELDS: Final = PACKET_TOP_FIELDS | {"adjudication_basis"}
QUESTION_FIELDS: Final = {"candidates", "question", "question_id"}
CANDIDATE_FIELDS: Final = {
    "candidate_ordinal",
    "owner_adjudication_notes",
    "owner_relevance_grade",
    "retrieval_unit_id",
    "source",
    "source_locator",
    "source_version_identity",
    "stable_source_id",
    "text",
    "text_sha256",
    "title",
}
COMMON_DOCUMENT_FIELDS: Final = {
    "retrieval_unit_id",
    "source",
    "source_locator",
    "source_version_identity",
    "stable_source_id",
    "text",
    "text_sha256",
    "title",
}
PUBMED_DOCUMENT_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {
    "abstract_sections",
    "query_memberships",
    "reused_from_work_item",
    "source_artifact_sha256",
}
DAILYMED_DOCUMENT_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {
    "acquisition_operation_id",
    "brand",
    "normalized_loinc_name",
    "observed_code_system",
    "observed_loinc_code",
    "ordinal",
    "parent_ordinal",
    "provider_title",
    "retrieval_eligible",
    "section_occurrence_id",
    "setid",
    "source_raw_artifact_sha256",
    "spl_version",
    "transformation_chain_sha256",
    "xml_path",
}
QRELS_HEADER: Final = (
    "question_id",
    "retrieval_unit_id",
    "relevance_grade",
    "source",
    "title",
    "adjudication_note",
)


class Gold10BenchmarkError(RuntimeError):
    """Fail-closed Gold-10 input, execution, or persistence error."""


@dataclass(frozen=True, slots=True)
class Gold10InputPaths:
    """The five exact Owner-approved Gold-10 evidence paths."""

    corpus: Path
    packet: Path
    qrels: Path
    adjudication: Path
    contract: Path

    @classmethod
    def canonical(cls) -> Gold10InputPaths:
        owner = CANONICAL_INPUT_ROOT / "owner-adjudication"
        return cls(
            corpus=CANONICAL_INPUT_ROOT / "corpus-manifest.json",
            packet=CANONICAL_INPUT_ROOT / "blinded-adjudication-packet.json",
            qrels=owner / "gold10-authoritative-qrels-v2.tsv",
            adjudication=owner / "gold10-authoritative-adjudication-v2.json",
            contract=owner / "gold10-authoritative-metric-contract-v1.json",
        )


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Exact identity of one trusted external input."""

    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Gold10Document:
    """One source-native retrieval unit with exact title/text preservation."""

    retrieval_unit_id: str
    source: str
    stable_source_id: str
    source_locator: str
    source_version_identity: str
    title: str
    text: str
    text_sha256: str


@dataclass(frozen=True, slots=True)
class Gold10Question:
    """One adjudicated development question."""

    question_id: str
    text: str
    judgments: Mapping[str, int]
    notes: Mapping[str, str]
    direct_answer_eligible: bool


@dataclass(frozen=True, slots=True)
class Gold10BenchmarkDataset:
    """Fully reconciled 10-question, 65-document, 650-pair dataset."""

    documents: tuple[Gold10Document, ...]
    questions: tuple[Gold10Question, ...]
    input_identities: Mapping[str, ArtifactIdentity]
    adjudication_provenance: str

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(document.retrieval_unit_id for document in self.documents)


@dataclass(frozen=True, slots=True)
class RankingEntry:
    """One complete-corpus ranked candidate with reconstructible components."""

    rank: int
    retrieval_unit_id: str
    score: float
    relevance_grade: int
    component_scores: Mapping[str, float]
    component_ranks: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class QueryResult:
    """One query/mode result with metrics and complete ranking evidence."""

    question_id: str
    question: str
    mode: str
    direct_answer_eligible: bool
    latency_ms: float
    metrics: Mapping[str, float | None]
    rankings: tuple[RankingEntry, ...]


@dataclass(frozen=True, slots=True)
class ModeResult:
    """One exact retrieval mode over all ten questions."""

    mode: str
    records: tuple[QueryResult, ...]
    macro_metrics: Mapping[str, float]
    metric_denominators: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """All three frozen Gold-10 retrieval modes and measured build timings."""

    modes: Mapping[str, ModeResult]
    build_timings_seconds: Mapping[str, float]
    source_state: Mapping[str, Any]


class _ArtifactProvenance(Protocol):
    def provenance(self) -> Mapping[str, Any]: ...


class MedCPTSearchIndex(Protocol):
    """Small injectable surface used by unit tests and the frozen MedCPT index."""

    @property
    def doc_ids(self) -> Sequence[str]: ...

    @property
    def artifacts(self) -> _ArtifactProvenance | None: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def query_batch_size(self) -> int: ...

    @property
    def document_batch_size(self) -> int: ...

    def search(self, query: str, limit: int) -> list[tuple[str, float]]: ...

    def runtime_provenance(self) -> Mapping[str, Any]: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Gold10BenchmarkError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strict_json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Gold10BenchmarkError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise Gold10BenchmarkError(f"{label} must be a JSON object")
    return value


def _input_specs() -> dict[str, tuple[Path, int, str]]:
    paths = Gold10InputPaths.canonical()
    return {
        "corpus": (paths.corpus, CORPUS_BYTES, CORPUS_SHA256),
        "packet": (paths.packet, PACKET_BYTES, PACKET_SHA256),
        "qrels": (paths.qrels, QRELS_BYTES, QRELS_SHA256),
        "adjudication": (
            paths.adjudication,
            ADJUDICATION_BYTES,
            ADJUDICATION_SHA256,
        ),
        "contract": (paths.contract, CONTRACT_BYTES, CONTRACT_SHA256),
    }


def _read_exact_inputs(
    paths: Gold10InputPaths,
) -> tuple[dict[str, bytes], dict[str, ArtifactIdentity]]:
    supplied = asdict(paths)
    payloads: dict[str, bytes] = {}
    identities: dict[str, ArtifactIdentity] = {}
    for label, (expected_path, expected_bytes, expected_sha256) in _input_specs().items():
        path = Path(supplied[label])
        if path.is_symlink() or not path.is_file():
            raise Gold10BenchmarkError(f"{label} input must be an exact regular file")
        actual = path.resolve(strict=True)
        expected = expected_path.resolve(strict=True)
        if actual != expected:
            raise Gold10BenchmarkError(f"{label} input path differs from the frozen path")
        data = actual.read_bytes()
        if len(data) != expected_bytes or _sha256(data) != expected_sha256:
            raise Gold10BenchmarkError(f"{label} input identity drifted")
        payloads[label] = data
        identities[label] = ArtifactIdentity(str(actual), len(data), _sha256(data))
    return payloads, identities


def _require_text_hash(item: Mapping[str, Any]) -> None:
    text = item.get("text")
    identity = item.get("text_sha256")
    if not isinstance(text, str) or not text:
        raise Gold10BenchmarkError("corpus text must be a non-empty string")
    digest = _sha256(text.encode("utf-8"))
    expected = f"sha256:{digest}" if item.get("source") == "dailymed" else digest
    if identity != expected:
        raise Gold10BenchmarkError("corpus text SHA-256 does not match exact text")


def _parse_corpus(data: bytes) -> tuple[Gold10Document, ...]:
    payload = _strict_json(data, label="Gold-10 corpus")
    if set(payload) != CORPUS_TOP_FIELDS:
        raise Gold10BenchmarkError("corpus top-level schema is not exact")
    if (
        payload["schema_version"] != "medevidence.gold10.v2.corpus-manifest.v1"
        or payload["dataset"] != DATASET
        or payload["status"] != "frozen_before_adjudication"
        or payload["counts"]
        != {"mounjaro_retrieval": 3, "ozempic_retrieval": 12, "pubmed": 50, "total": 65}
        or payload["structural_provenance"] != {"indexed": 0, "mounjaro": 1, "ozempic": 1}
    ):
        raise Gold10BenchmarkError("corpus identity, status, or counts drifted")
    items = payload["items"]
    if not isinstance(items, list) or len(items) != CORPUS_SIZE:
        raise Gold10BenchmarkError("corpus must contain exactly 65 items")
    documents: list[Gold10Document] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise Gold10BenchmarkError("corpus item must be an object")
        source = item.get("source")
        expected_fields = PUBMED_DOCUMENT_FIELDS if source == "pubmed" else DAILYMED_DOCUMENT_FIELDS
        if source not in {"pubmed", "dailymed"} or set(item) != expected_fields:
            raise Gold10BenchmarkError("corpus item schema or source is not exact")
        if source == "dailymed" and item.get("retrieval_eligible") is not True:
            raise Gold10BenchmarkError("structural DailyMed evidence cannot enter retrieval")
        _require_text_hash(item)
        values = {name: item.get(name) for name in COMMON_DOCUMENT_FIELDS}
        if any(not isinstance(values[name], str) or not values[name] for name in values):
            raise Gold10BenchmarkError(
                "corpus identity/title/text fields must be non-empty strings"
            )
        doc_id = str(values["retrieval_unit_id"])
        if doc_id in seen:
            raise Gold10BenchmarkError("corpus retrieval unit ids must be unique")
        seen.add(doc_id)
        documents.append(
            Gold10Document(
                retrieval_unit_id=doc_id,
                source=str(values["source"]),
                stable_source_id=str(values["stable_source_id"]),
                source_locator=str(values["source_locator"]),
                source_version_identity=str(values["source_version_identity"]),
                title=str(values["title"]),
                text=str(values["text"]),
                text_sha256=str(values["text_sha256"]),
            )
        )
    if sum(document.source == "pubmed" for document in documents) != 50:
        raise Gold10BenchmarkError("corpus source counts do not reconcile")
    return tuple(sorted(documents, key=lambda document: document.retrieval_unit_id))


def _parse_packet(data: bytes, documents: Mapping[str, Gold10Document]) -> dict[str, Any]:
    payload = _strict_json(data, label="Gold-10 blinded packet")
    if set(payload) != PACKET_TOP_FIELDS:
        raise Gold10BenchmarkError("blinded packet top-level schema is not exact")
    if (
        payload["schema_version"] != "medevidence.gold10.v2.blinded-adjudication-packet.v1"
        or payload["dataset"] != DATASET
        or payload["corpus_manifest_sha256"] != CORPUS_SHA256
        or payload["authoritative_qrels_status"] != "not_created_owner_adjudication_required"
        or payload["ordering"] != "sha256(dataset NUL question_id NUL retrieval_unit_id)"
    ):
        raise Gold10BenchmarkError("blinded packet identity or status drifted")
    _validate_questions(payload.get("questions"), documents, adjudicated=False)
    return payload


def _validate_questions(
    questions: Any,
    documents: Mapping[str, Gold10Document],
    *,
    adjudicated: bool,
) -> None:
    if not isinstance(questions, list) or len(questions) != QUESTION_COUNT:
        raise Gold10BenchmarkError("adjudication evidence must contain exactly ten questions")
    for ordinal, question in enumerate(questions, start=1):
        if not isinstance(question, dict) or set(question) != QUESTION_FIELDS:
            raise Gold10BenchmarkError("question schema is not exact")
        if question["question_id"] != f"Q{ordinal}" or not isinstance(question["question"], str):
            raise Gold10BenchmarkError("question ids/order/text are not exact")
        candidates = question["candidates"]
        if not isinstance(candidates, list) or len(candidates) != CORPUS_SIZE:
            raise Gold10BenchmarkError("every question must judge all 65 documents")
        seen: set[str] = set()
        for candidate_ordinal, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_FIELDS:
                raise Gold10BenchmarkError("candidate schema is not exact")
            doc_id = candidate.get("retrieval_unit_id")
            if candidate.get("candidate_ordinal") != candidate_ordinal or doc_id not in documents:
                raise Gold10BenchmarkError("candidate ordinal or document identity drifted")
            if doc_id in seen:
                raise Gold10BenchmarkError("candidate document identity is duplicated")
            seen.add(str(doc_id))
            document = documents[str(doc_id)]
            for field in COMMON_DOCUMENT_FIELDS:
                if candidate.get(field) != getattr(document, field):
                    raise Gold10BenchmarkError("candidate does not exactly match the frozen corpus")
            grade = candidate["owner_relevance_grade"]
            note = candidate["owner_adjudication_notes"]
            if adjudicated:
                if type(grade) is not int or grade not in {0, 1, 2}:
                    raise Gold10BenchmarkError("adjudicated grade must be exactly 0, 1, or 2")
                if not isinstance(note, str) or not note:
                    raise Gold10BenchmarkError("adjudication note must be a non-empty string")
            elif grade is not None or note is not None:
                raise Gold10BenchmarkError("blinded packet contains adjudication leakage")
        if seen != set(documents):
            raise Gold10BenchmarkError("question candidate set does not equal the corpus")


def _parse_adjudication(
    data: bytes,
    documents: Mapping[str, Gold10Document],
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _strict_json(data, label="Gold-10 adjudication")
    if set(payload) != ADJUDICATION_TOP_FIELDS:
        raise Gold10BenchmarkError("adjudication top-level schema is not exact")
    for field in PACKET_TOP_FIELDS - {"questions", "authoritative_qrels_status"}:
        if payload.get(field) != packet.get(field):
            raise Gold10BenchmarkError("adjudication does not bind the blinded packet")
    if payload.get("authoritative_qrels_status") != "owner_confirmed_blinded_ai_adjudication":
        raise Gold10BenchmarkError("adjudication status is not Owner-confirmed")
    basis = payload.get("adjudication_basis")
    if not isinstance(basis, dict) or set(basis) != {
        "source_packet_sha256",
        "grading_scale",
        "status_note",
        "consistency_pass",
        "owner_confirmation",
    }:
        raise Gold10BenchmarkError("adjudication basis schema is not exact")
    if (
        basis["source_packet_sha256"] != PACKET_SHA256
        or basis["grading_scale"]
        != {
            "0": "not relevant",
            "1": "relevant supporting/contextual",
            "2": "directly answer-bearing",
        }
        or basis["owner_confirmation"]
        != {"confirmed_scope": "second-pass qrels and metric semantics", "status": "confirmed"}
    ):
        raise Gold10BenchmarkError("adjudication authority or grading scale drifted")
    _validate_questions(payload.get("questions"), documents, adjudicated=True)
    packet_questions = packet["questions"]
    for packet_question, adjudicated_question in zip(
        packet_questions, payload["questions"], strict=True
    ):
        if (
            packet_question["question_id"] != adjudicated_question["question_id"]
            or packet_question["question"] != adjudicated_question["question"]
        ):
            raise Gold10BenchmarkError("adjudicated question differs from the blinded packet")
        for blinded, adjudicated in zip(
            packet_question["candidates"], adjudicated_question["candidates"], strict=True
        ):
            for field in CANDIDATE_FIELDS - {
                "owner_relevance_grade",
                "owner_adjudication_notes",
            }:
                if blinded[field] != adjudicated[field]:
                    raise Gold10BenchmarkError("adjudication changed blinded candidate evidence")
    return payload


def _parse_contract(data: bytes) -> dict[str, Any]:
    payload = _strict_json(data, label="Gold-10 metric contract")
    if set(payload) != {
        "schema_version",
        "dataset",
        "qrels_status",
        "primary_metric",
        "broad_metrics",
        "direct_answer_metrics",
        "interpretation",
        "adjudication_provenance",
    }:
        raise Gold10BenchmarkError("metric contract top-level schema is not exact")
    direct = payload.get("direct_answer_metrics")
    if (
        payload.get("schema_version") != "medevidence.gold10.v2.metric-contract.v1"
        or payload.get("dataset") != DATASET
        or payload.get("qrels_status") != "owner_confirmed"
        or payload.get("primary_metric")
        != {
            "name": "nDCG@10",
            "relevance": "graded 0/1/2",
            "gain": "2^relevance - 1",
            "discount": "1/log2(rank+1)",
            "aggregation": "macro mean over all 10 questions",
        }
        or payload.get("broad_metrics")
        != {
            "Recall@5": "binary relevant iff grade >= 1; macro mean over all 10 questions",
            "Recall@10": "binary relevant iff grade >= 1; macro mean over all 10 questions",
            "MRR@10": (
                "binary relevant iff grade >= 1; first relevant item; "
                "macro mean over all 10 questions"
            ),
        }
        or not isinstance(direct, dict)
        or direct.get("DirectHit@10") != "binary relevant iff grade == 2"
        or direct.get("DirectMRR@10") != "binary relevant iff grade == 2"
        or direct.get("eligibility") != "questions with at least one grade-2 corpus item only"
        or direct.get("expected_direct_answerable_questions") != 9
        or set(direct.get("excluded_questions", {})) != {"Q2"}
        or payload.get("adjudication_provenance") != ADJUDICATION_PROVENANCE
    ):
        raise Gold10BenchmarkError("metric semantics or adjudication provenance drifted")
    return payload


def _parse_qrels(data: bytes) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise Gold10BenchmarkError("qrels are not strict UTF-8") from error
    if "\x00" in text or not text.endswith("\n"):
        raise Gold10BenchmarkError("qrels must be newline-terminated TSV")
    if "\r" in text:
        if not text.endswith("\r\n") or "\r" in text.replace("\r\n", ""):
            raise Gold10BenchmarkError("qrels contain mixed or bare-CR line endings")
        normalized = text.replace("\r\n", "\n")
    else:
        normalized = text
    reader = csv.reader(normalized.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE)
    rows = list(reader)
    if not rows or tuple(rows[0]) != QRELS_HEADER or len(set(rows[0])) != len(rows[0]):
        raise Gold10BenchmarkError("qrels header is not exact and unique")
    if len(rows) != QUESTION_COUNT * CORPUS_SIZE + 1:
        raise Gold10BenchmarkError("qrels must contain exactly 650 judgment rows")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows[1:]:
        if len(raw) != len(QRELS_HEADER):
            raise Gold10BenchmarkError("qrels row does not have exactly six TSV fields")
        row = dict(zip(QRELS_HEADER, raw, strict=True))
        pair = (row["question_id"], row["retrieval_unit_id"])
        if pair in seen:
            raise Gold10BenchmarkError("qrels contain a duplicate question/document pair")
        seen.add(pair)
        if row["relevance_grade"] not in {"0", "1", "2"} or not row["adjudication_note"]:
            raise Gold10BenchmarkError("qrels grade or adjudication note is invalid")
        result.append(row)
    return result


def _reconcile_questions(
    adjudication: Mapping[str, Any],
    qrels: Sequence[Mapping[str, str]],
    documents: Mapping[str, Gold10Document],
) -> tuple[Gold10Question, ...]:
    row_by_pair = {(row["question_id"], row["retrieval_unit_id"]): row for row in qrels}
    expected_pairs = {
        (f"Q{ordinal}", doc_id) for ordinal in range(1, QUESTION_COUNT + 1) for doc_id in documents
    }
    if set(row_by_pair) != expected_pairs:
        raise Gold10BenchmarkError("qrels do not exactly cover the packet/corpus product")
    questions: list[Gold10Question] = []
    for question in adjudication["questions"]:
        question_id = question["question_id"]
        judgments: dict[str, int] = {}
        notes: dict[str, str] = {}
        for candidate in question["candidates"]:
            doc_id = candidate["retrieval_unit_id"]
            row = row_by_pair[(question_id, doc_id)]
            document = documents[doc_id]
            grade = candidate["owner_relevance_grade"]
            note = candidate["owner_adjudication_notes"]
            if (
                row["source"] != document.source
                or row["title"] != document.title.strip()
                or int(row["relevance_grade"]) != grade
                or row["adjudication_note"] != note
            ):
                raise Gold10BenchmarkError("qrels differ from corpus/adjudication evidence")
            judgments[doc_id] = int(grade)
            notes[doc_id] = str(note)
        questions.append(
            Gold10Question(
                question_id=question_id,
                text=question["question"],
                judgments=judgments,
                notes=notes,
                direct_answer_eligible=any(grade == 2 for grade in judgments.values()),
            )
        )
    eligible = {question.question_id for question in questions if question.direct_answer_eligible}
    if eligible != {"Q1", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10"}:
        raise Gold10BenchmarkError("Q2 must be the sole non-direct-answerable question")
    return tuple(questions)


def load_gold10_v2_dataset(paths: Gold10InputPaths) -> Gold10BenchmarkDataset:
    """Load and cross-reconcile the five exact external Gold-10 inputs."""

    payloads, identities = _read_exact_inputs(paths)
    documents = _parse_corpus(payloads["corpus"])
    documents_by_id = {document.retrieval_unit_id: document for document in documents}
    packet = _parse_packet(payloads["packet"], documents_by_id)
    adjudication = _parse_adjudication(payloads["adjudication"], documents_by_id, packet)
    _parse_contract(payloads["contract"])
    qrels = _parse_qrels(payloads["qrels"])
    questions = _reconcile_questions(adjudication, qrels, documents_by_id)
    return Gold10BenchmarkDataset(
        documents=documents,
        questions=questions,
        input_identities=identities,
        adjudication_provenance=ADJUDICATION_PROVENANCE,
    )


def _rank_order_is_valid(ranking: Sequence[tuple[str, float]]) -> bool:
    return all(
        left[1] > right[1] or (left[1] == right[1] and left[0] < right[0])
        for left, right in pairwise(ranking)
    )


def _validate_ranking(
    ranking: Sequence[tuple[str, float]], expected_ids: set[str], *, label: str
) -> list[tuple[str, float]]:
    normalized = [(str(doc_id), float(score)) for doc_id, score in ranking]
    if (
        len(normalized) != CORPUS_SIZE
        or {doc_id for doc_id, _score in normalized} != expected_ids
        or len({doc_id for doc_id, _score in normalized}) != CORPUS_SIZE
        or any(not math.isfinite(score) for _doc_id, score in normalized)
        or not _rank_order_is_valid(normalized)
    ):
        raise Gold10BenchmarkError(f"{label} did not return one exact full-corpus ranking")
    return normalized


def _full_bm25_ranking(
    index: BM25Index, query: str, expected_ids: set[str]
) -> list[tuple[str, float]]:
    scored = index.search(query, CORPUS_SIZE)
    if len({doc_id for doc_id, _score in scored}) != len(scored) or not {
        doc_id for doc_id, _score in scored
    }.issubset(expected_ids):
        raise Gold10BenchmarkError("BM25 returned duplicate or foreign document ids")
    seen = {doc_id for doc_id, _score in scored}
    complete = [*scored, *((doc_id, 0.0) for doc_id in sorted(expected_ids - seen))]
    return _validate_ranking(complete, expected_ids, label=MODE_BM25)


def _query_metrics(
    ranking: Sequence[tuple[str, float]], question: Gold10Question
) -> dict[str, float | None]:
    ranked_ids = [doc_id for doc_id, _score in ranking]
    metrics: dict[str, float | None] = {
        "nDCG@10": ndcg_at_k(ranked_ids, question.judgments, TOP_K),
        "Recall@5": recall_at_k(ranked_ids, question.judgments, 5, grade_min=1),
        "Recall@10": recall_at_k(ranked_ids, question.judgments, TOP_K, grade_min=1),
        "MRR@10": reciprocal_rank_at_k(ranked_ids, question.judgments, TOP_K, grade_min=1),
        "DirectHit@10": None,
        "DirectMRR@10": None,
    }
    if question.direct_answer_eligible:
        direct_mrr = reciprocal_rank_at_k(ranked_ids, question.judgments, TOP_K, grade_min=2)
        metrics["DirectHit@10"] = 1.0 if direct_mrr > 0.0 else 0.0
        metrics["DirectMRR@10"] = direct_mrr
    return metrics


def _macro_metrics(records: Sequence[QueryResult]) -> tuple[dict[str, float], dict[str, int]]:
    names = ("nDCG@10", "Recall@5", "Recall@10", "MRR@10", "DirectHit@10", "DirectMRR@10")
    metrics: dict[str, float] = {}
    denominators: dict[str, int] = {}
    for name in names:
        values: list[float] = []
        for record in records:
            value = record.metrics[name]
            if value is not None:
                values.append(float(value))
        if not values:
            raise Gold10BenchmarkError(f"metric {name} has no eligible questions")
        metrics[name] = sum(values) / len(values)
        denominators[name] = len(values)
    if any(denominators[name] != 10 for name in names[:4]) or any(
        denominators[name] != 9 for name in names[4:]
    ):
        raise Gold10BenchmarkError("metric denominators do not match the frozen contract")
    return metrics, denominators


def _ranking_entries(
    ranking: Sequence[tuple[str, float]],
    question: Gold10Question,
    components: Mapping[str, Sequence[tuple[str, float]]],
) -> tuple[RankingEntry, ...]:
    score_maps = {name: dict(values) for name, values in components.items()}
    rank_maps = {name: component_ranks(values) for name, values in components.items()}
    return tuple(
        RankingEntry(
            rank=rank,
            retrieval_unit_id=doc_id,
            score=float(score),
            relevance_grade=question.judgments[doc_id],
            component_scores={name: float(values[doc_id]) for name, values in score_maps.items()},
            component_ranks={name: values[doc_id] for name, values in rank_maps.items()},
        )
        for rank, (doc_id, score) in enumerate(ranking, start=1)
    )


def _validate_mode_result(result: ModeResult, dataset: Gold10BenchmarkDataset) -> None:
    if result.mode not in MODES or len(result.records) != QUESTION_COUNT:
        raise Gold10BenchmarkError("mode result identity or query count is invalid")
    expected_question_ids = tuple(f"Q{ordinal}" for ordinal in range(1, QUESTION_COUNT + 1))
    dataset_question_ids = tuple(question.question_id for question in dataset.questions)
    record_question_ids = tuple(record.question_id for record in result.records)
    if dataset_question_ids != expected_question_ids:
        raise Gold10BenchmarkError("dataset questions are not exact ordered Q1..Q10")
    if record_question_ids != expected_question_ids:
        raise Gold10BenchmarkError(
            "mode result questions must be exactly one ordered record for each Q1..Q10"
        )
    questions = {question.question_id: question for question in dataset.questions}
    expected_ids = set(dataset.document_ids)
    for record in result.records:
        question = questions.get(record.question_id)
        if (
            question is None
            or record.question != question.text
            or record.mode != result.mode
            or record.direct_answer_eligible != question.direct_answer_eligible
            or record.latency_ms < 0.0
            or not math.isfinite(record.latency_ms)
        ):
            raise Gold10BenchmarkError("query result identity drifted")
        ranking = [(entry.retrieval_unit_id, entry.score) for entry in record.rankings]
        _validate_ranking(ranking, expected_ids, label=result.mode)
        if tuple(entry.rank for entry in record.rankings) != tuple(range(1, CORPUS_SIZE + 1)):
            raise Gold10BenchmarkError("candidate ranks are not contiguous 1..65")
        if any(
            entry.relevance_grade != question.judgments[entry.retrieval_unit_id]
            for entry in record.rankings
        ):
            raise Gold10BenchmarkError("saved candidate grade differs from qrels")
        if dict(record.metrics) != _query_metrics(ranking, question):
            raise Gold10BenchmarkError("saved per-query metrics do not recompute")
        expected_components = {MODE_BM25, MODE_MEDCPT} if result.mode == MODE_RRF else {result.mode}
        if any(
            set(entry.component_scores) != expected_components
            or set(entry.component_ranks) != expected_components
            for entry in record.rankings
        ):
            raise Gold10BenchmarkError("saved component evidence is incomplete")
        for component in expected_components:
            ranks = [entry.component_ranks[component] for entry in record.rankings]
            if sorted(ranks) != list(range(1, CORPUS_SIZE + 1)) or any(
                not math.isfinite(entry.component_scores[component]) for entry in record.rankings
            ):
                raise Gold10BenchmarkError("saved component ranks or scores are invalid")
        if result.mode != MODE_RRF and any(
            entry.component_ranks[result.mode] != entry.rank
            or not math.isclose(
                entry.component_scores[result.mode], entry.score, rel_tol=0.0, abs_tol=0.0
            )
            for entry in record.rankings
        ):
            raise Gold10BenchmarkError("single-mode candidate and component evidence differ")
        if result.mode == MODE_RRF:
            component_rankings: list[list[tuple[str, float]]] = []
            for component in (MODE_BM25, MODE_MEDCPT):
                ordered = sorted(
                    record.rankings, key=lambda entry: entry.component_ranks[component]
                )
                component_rankings.append(
                    [
                        (entry.retrieval_unit_id, entry.component_scores[component])
                        for entry in ordered
                    ]
                )
            rebuilt = reciprocal_rank_fusion(component_rankings, k=RRF_K, limit=CORPUS_SIZE)
            if [doc_id for doc_id, _score in rebuilt] != [
                doc_id for doc_id, _score in ranking
            ] or any(
                not math.isclose(score, expected, rel_tol=0.0, abs_tol=1e-15)
                for (_doc_id, score), (_expected_id, expected) in zip(ranking, rebuilt, strict=True)
            ):
                raise Gold10BenchmarkError("saved RRF evidence does not reconstruct")
    metrics, denominators = _macro_metrics(result.records)
    if dict(result.macro_metrics) != metrics or dict(result.metric_denominators) != denominators:
        raise Gold10BenchmarkError("saved macro metrics do not recompute")


class Gold10BenchmarkRunner:
    """Run the frozen BM25, MedCPT, and two-way RRF modes over all 65 units."""

    def __init__(
        self,
        dataset: Gold10BenchmarkDataset,
        medcpt_index: MedCPTSearchIndex,
        *,
        medcpt_build_seconds: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if medcpt_build_seconds < 0.0 or not math.isfinite(medcpt_build_seconds):
            raise Gold10BenchmarkError("MedCPT build timing must be finite and non-negative")
        self.dataset = dataset
        self.medcpt = medcpt_index
        self._clock = clock
        self._doc_ids = tuple(sorted(dataset.document_ids))
        if tuple(medcpt_index.doc_ids) != self._doc_ids:
            raise Gold10BenchmarkError("MedCPT index document ids differ from the frozen corpus")
        documents = {document.retrieval_unit_id: document for document in dataset.documents}
        started = self._clock()
        self.bm25 = BM25Index(
            self._doc_ids,
            [f"{documents[doc_id].title}\n{documents[doc_id].text}" for doc_id in self._doc_ids],
            k1=BM25_K1,
            b=BM25_B,
        )
        bm25_seconds = self._clock() - started
        if bm25_seconds < 0.0 or not math.isfinite(bm25_seconds):
            raise Gold10BenchmarkError("BM25 build clock moved backwards or became non-finite")
        self.build_timings_seconds = {
            MODE_BM25: bm25_seconds,
            MODE_MEDCPT: medcpt_build_seconds,
            MODE_RRF: bm25_seconds + medcpt_build_seconds,
        }

    def _search_mode(
        self, mode: str, query: str
    ) -> tuple[list[tuple[str, float]], dict[str, list[tuple[str, float]]]]:
        expected = set(self._doc_ids)
        if mode == MODE_BM25:
            bm25 = _full_bm25_ranking(self.bm25, query, expected)
            return bm25, {MODE_BM25: bm25}
        if mode == MODE_MEDCPT:
            medcpt = _validate_ranking(
                self.medcpt.search(query, CORPUS_SIZE), expected, label=MODE_MEDCPT
            )
            return medcpt, {MODE_MEDCPT: medcpt}
        if mode == MODE_RRF:
            bm25 = _full_bm25_ranking(self.bm25, query, expected)
            medcpt = _validate_ranking(
                self.medcpt.search(query, CORPUS_SIZE), expected, label=MODE_MEDCPT
            )
            fused = _validate_ranking(
                reciprocal_rank_fusion([bm25, medcpt], k=RRF_K, limit=CORPUS_SIZE),
                expected,
                label=MODE_RRF,
            )
            return fused, {MODE_BM25: bm25, MODE_MEDCPT: medcpt}
        raise Gold10BenchmarkError(f"unsupported benchmark mode {mode!r}")

    def run(self) -> BenchmarkRun:
        """Execute exactly the three Owner-frozen modes, serially."""

        source_state = _source_state()
        results: dict[str, ModeResult] = {}
        for mode in MODES:
            records: list[QueryResult] = []
            for question in self.dataset.questions:
                started = self._clock()
                ranking, components = self._search_mode(mode, question.text)
                latency_ms = (self._clock() - started) * 1000.0
                if latency_ms < 0.0 or not math.isfinite(latency_ms):
                    raise Gold10BenchmarkError("query clock moved backwards or became non-finite")
                records.append(
                    QueryResult(
                        question_id=question.question_id,
                        question=question.text,
                        mode=mode,
                        direct_answer_eligible=question.direct_answer_eligible,
                        latency_ms=latency_ms,
                        metrics=_query_metrics(ranking, question),
                        rankings=_ranking_entries(ranking, question, components),
                    )
                )
            metrics, denominators = _macro_metrics(records)
            result = ModeResult(mode, tuple(records), metrics, denominators)
            _validate_mode_result(result, self.dataset)
            results[mode] = result
        if tuple(results) != MODES:
            raise Gold10BenchmarkError("benchmark did not execute exactly the three frozen modes")
        return BenchmarkRun(results, self.build_timings_seconds, source_state)


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_state() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    files: dict[str, dict[str, int | str]] = {}
    for relative in (
        "evaluation/gold10_v2_benchmark.py",
        "evaluation/medcpt.py",
        "evaluation/metrics.py",
        "evaluation/run_gold10_v2_benchmark.py",
        "src/medevidence/retrieval/core.py",
        "tests/unit/evaluation/test_gold10_v2_benchmark.py",
    ):
        path = repository / relative
        data = path.read_bytes()
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
    return {"binding": "exact benchmark adapter source bytes", "files": files}


def _artifact_record(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    return {"filename": path.name, "bytes": len(data), "sha256": _sha256(data)}


def _runtime_identity() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("numpy", "torch", "transformers"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise Gold10BenchmarkError(f"required runtime package {name!r} is missing") from error
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "packages": packages,
        "process_id": os.getpid(),
    }


def _validated_medcpt_runtime_provenance(
    medcpt_index: MedCPTSearchIndex,
) -> dict[str, Any]:
    """Validate exact observed MedCPT runtime evidence before persistence."""

    expected_fields = {
        "pytorch_intra_op_threads_observed",
        "pytorch_inter_op_threads_observed",
        "model_parameter_dtype_observed",
        "query_embedding_dtype_observed",
        "document_embedding_index_dtype_observed",
        "dense_index_memory_bytes",
        "dense_index_memory_measurement",
        "dense_index_memory_limitation",
    }
    observed = dict(medcpt_index.runtime_provenance())
    if set(observed) != expected_fields:
        raise Gold10BenchmarkError("MedCPT runtime provenance schema is not exact")
    for field in (
        "pytorch_intra_op_threads_observed",
        "pytorch_inter_op_threads_observed",
    ):
        if type(observed[field]) is not int or observed[field] != 1:
            raise Gold10BenchmarkError(f"MedCPT runtime {field} must be observed as exactly 1")
    parameter_dtypes = observed["model_parameter_dtype_observed"]
    if not isinstance(parameter_dtypes, dict) or parameter_dtypes != {
        "query_encoder": "torch.float32",
        "article_encoder": "torch.float32",
    }:
        raise Gold10BenchmarkError(
            "MedCPT query/article model parameter dtypes must be observed as torch.float32"
        )
    if observed["query_embedding_dtype_observed"] != "float32":
        raise Gold10BenchmarkError("MedCPT query embedding dtype must be observed as float32")
    if observed["document_embedding_index_dtype_observed"] != "float32":
        raise Gold10BenchmarkError(
            "MedCPT document embedding/index dtype must be observed as float32"
        )
    memory = observed["dense_index_memory_bytes"]
    if type(memory) is not int or memory <= 0 or memory != DENSE_INDEX_MEMORY_BYTES:
        raise Gold10BenchmarkError(
            "MedCPT dense index memory must be the observed 65x768 float32 matrix nbytes"
        )
    if observed["dense_index_memory_measurement"] != "numpy.ndarray.nbytes":
        raise Gold10BenchmarkError("MedCPT dense index memory measurement is not exact")
    if observed["dense_index_memory_limitation"] != DENSE_INDEX_MEMORY_LIMITATION:
        raise Gold10BenchmarkError("MedCPT dense index memory limitation is not exact")
    try:
        dimensions = medcpt_index.dimensions
        query_batch_size = medcpt_index.query_batch_size
        document_batch_size = medcpt_index.document_batch_size
    except AttributeError as error:
        raise Gold10BenchmarkError("MedCPT runtime configuration evidence is incomplete") from error
    if type(medcpt_index) is MedCPTIndex:
        device: Any = MEDCPT_DEVICE
    else:
        try:
            device = vars(medcpt_index)["device"]
        except (TypeError, KeyError) as error:
            raise Gold10BenchmarkError(
                "MedCPT runtime configuration evidence is incomplete"
            ) from error
    if type(device) is not str or device != MEDCPT_DEVICE:
        raise Gold10BenchmarkError("MedCPT runtime device must be CPU")
    if type(dimensions) is not int or dimensions != MEDCPT_DIMENSIONS:
        raise Gold10BenchmarkError("MedCPT runtime embedding dimensions must be exactly 768")
    if (
        type(query_batch_size) is not int
        or query_batch_size != MEDCPT_QUERY_BATCH_SIZE
        or type(document_batch_size) is not int
        or document_batch_size != MEDCPT_DOCUMENT_BATCH_SIZE
    ):
        raise Gold10BenchmarkError("MedCPT runtime batch sizes must be exactly query=1/document=8")
    return {
        **observed,
        "device": device,
        "embedding_dimensions": dimensions,
        "query_batch_size": query_batch_size,
        "document_batch_size": document_batch_size,
    }


def validate_benchmark_output_root(output_root: str | Path) -> Path:
    """Require the exact absent external benchmark-001 result path."""

    root = Path(output_root)
    if not root.is_absolute() or root.exists() or root.is_symlink():
        raise Gold10BenchmarkError("output root must be a new absent absolute path")
    repository = Path(__file__).resolve().parents[1]
    parent = root.parent.resolve(strict=True)
    candidate = (parent / root.name).resolve(strict=False)
    if candidate != BENCHMARK_OUTPUT_ROOT.resolve(strict=False):
        raise Gold10BenchmarkError("output root differs from the exact benchmark-001 path")
    try:
        candidate.relative_to(repository)
    except ValueError:
        pass
    else:
        raise Gold10BenchmarkError("benchmark results must remain outside the repository")
    if candidate.parent != parent or not root.name or root.name in {".", ".."}:
        raise Gold10BenchmarkError("output root is not one exact child of its parent")
    staging = parent / f".{root.name}.pending"
    if staging.exists() or staging.is_symlink():
        raise Gold10BenchmarkError("stale benchmark output transaction exists")
    return candidate


def _rebind_dataset_inputs(dataset: Gold10BenchmarkDataset) -> Gold10BenchmarkDataset:
    try:
        paths = Gold10InputPaths(
            corpus=Path(dataset.input_identities["corpus"].path),
            packet=Path(dataset.input_identities["packet"].path),
            qrels=Path(dataset.input_identities["qrels"].path),
            adjudication=Path(dataset.input_identities["adjudication"].path),
            contract=Path(dataset.input_identities["contract"].path),
        )
    except KeyError as error:
        raise Gold10BenchmarkError("dataset input identity inventory is incomplete") from error
    rebound = load_gold10_v2_dataset(paths)
    if rebound != dataset:
        raise Gold10BenchmarkError("Gold-10 inputs drifted after benchmark dataset load")
    return rebound


def save_benchmark_run(
    run: BenchmarkRun,
    dataset: Gold10BenchmarkDataset,
    medcpt_index: MedCPTSearchIndex,
    output_root: str | Path,
    *,
    executed_at_utc: datetime | None = None,
) -> Path:
    """Validate and atomically retain a new external-only result directory."""

    if tuple(run.modes) != MODES:
        raise Gold10BenchmarkError("saved run must contain exactly the three frozen modes")
    for mode in MODES:
        _validate_mode_result(run.modes[mode], dataset)
    if medcpt_index.artifacts is None:
        raise Gold10BenchmarkError("verified MedCPT artifact provenance is required")
    if dataset.adjudication_provenance != ADJUDICATION_PROVENANCE:
        raise Gold10BenchmarkError("adjudication provenance is not exact")
    if dict(run.source_state) != _source_state():
        raise Gold10BenchmarkError("benchmark source bytes drifted during execution")
    _rebind_dataset_inputs(dataset)
    if set(run.build_timings_seconds) != set(MODES) or any(
        value < 0.0 or not math.isfinite(value) for value in run.build_timings_seconds.values()
    ):
        raise Gold10BenchmarkError("benchmark build timing evidence is incomplete")
    if not math.isclose(
        run.build_timings_seconds[MODE_RRF],
        run.build_timings_seconds[MODE_BM25] + run.build_timings_seconds[MODE_MEDCPT],
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise Gold10BenchmarkError("RRF build timing must be the exact component sum")
    model_runtime = _validated_medcpt_runtime_provenance(medcpt_index)
    candidate = validate_benchmark_output_root(output_root)
    parent = candidate.parent
    staging = parent / f".{candidate.name}.pending"
    observed = executed_at_utc or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise Gold10BenchmarkError("benchmark timestamp must be timezone-aware")
    staging.mkdir()
    try:
        artifacts: list[dict[str, int | str]] = []
        for mode in MODES:
            path = staging / MODE_FILENAMES[mode]
            with path.open("wb") as handle:
                for record in run.modes[mode].records:
                    handle.write(_canonical_json_bytes(asdict(record)))
            artifacts.append(_artifact_record(path))
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": BENCHMARK_RUN_ID,
            "status": "completed_execution_evidence_awaiting_independent_review",
            "dataset": DATASET,
            "development_status": "Gold-10 development subset; not a held-out performance claim",
            "executed_at_utc": observed.astimezone(UTC).isoformat(),
            "input_identities": {
                name: asdict(identity)
                for name, identity in sorted(dataset.input_identities.items())
            },
            "adjudication": {
                "provenance": dataset.adjudication_provenance,
                "authority": (
                    "exact owner-adjudication bundle; acquisition success.json remains "
                    "immutable historical pre-adjudication state"
                ),
                "question_count": QUESTION_COUNT,
                "document_count": CORPUS_SIZE,
                "judgment_pairs": QUESTION_COUNT * CORPUS_SIZE,
                "grades": [0, 1, 2],
                "direct_answer_eligible_questions": 9,
                "direct_answer_excluded_questions": ["Q2"],
            },
            "configuration": {
                "modes": list(MODES),
                "bm25": {
                    "k1": BM25_K1,
                    "b": BM25_B,
                    "document_text": "exact title + LF + exact text",
                    "candidate_limit": CORPUS_SIZE,
                },
                "medcpt": {
                    "candidate_limit": CORPUS_SIZE,
                    "query_max_length": 64,
                    "article_max_length": 512,
                    "query_batch_size": MEDCPT_QUERY_BATCH_SIZE,
                    "document_batch_size": MEDCPT_DOCUMENT_BATCH_SIZE,
                    "pooling": "last_hidden_state_cls",
                    "dimensions": MEDCPT_DIMENSIONS,
                    "normalization": "none",
                    "similarity": "inner_product",
                    "device": MEDCPT_DEVICE,
                },
                "rrf": {"k": RRF_K, "components": [MODE_BM25, MODE_MEDCPT]},
                "final_metric_cutoff": TOP_K,
            },
            "metric_contract": {
                "primary": "nDCG@10, gain 2^relevance - 1, macro over 10",
                "broad": "Recall@5, Recall@10, MRR@10; relevant iff grade >= 1; macro over 10",
                "direct": (
                    "DirectHit@10 and DirectMRR@10; relevant iff grade == 2; "
                    "macro over 9 eligible questions; Q2 excluded"
                ),
            },
            "corpus_documents": [
                {
                    "retrieval_unit_id": document.retrieval_unit_id,
                    "source": document.source,
                    "stable_source_id": document.stable_source_id,
                    "source_locator": document.source_locator,
                    "source_version_identity": document.source_version_identity,
                    "text_sha256": document.text_sha256,
                }
                for document in dataset.documents
            ],
            "summary": {
                mode: {
                    "metrics": dict(run.modes[mode].macro_metrics),
                    "denominators": dict(run.modes[mode].metric_denominators),
                }
                for mode in MODES
            },
            "timings": {
                "build_seconds": dict(run.build_timings_seconds),
                "query_latency": "measured serial wall-clock milliseconds in each per-query record",
                "limitation": "machine-local evidence; not portable production performance",
            },
            "runtime_identity": _runtime_identity(),
            "model_identity": {
                "artifact_provenance": medcpt_index.artifacts.provenance(),
                "runtime_provenance": model_runtime,
            },
            "source_state": dict(run.source_state),
            "execution_policy": {
                "network_operations": 0,
                "network_declaration": (
                    "offline-only local corpus and frozen MedCPT cache; no connector, client, "
                    "medical-source, Hugging Face, or dependency-advisory request"
                ),
                "query_execution": "serial_single_process",
                "complete_candidate_ranks": CORPUS_SIZE,
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


def build_local_medcpt_index(
    dataset: Gold10BenchmarkDataset,
    *,
    manifest_path: str | Path,
    cache_root: str | Path,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[MedCPTIndex, float]:
    """Build the frozen local-only M2-002 MedCPT index and measure its build."""

    documents = {document.retrieval_unit_id: document for document in dataset.documents}
    doc_ids = sorted(documents)
    started = clock()
    index = MedCPTIndex.from_local_artifacts(
        doc_ids,
        [documents[doc_id].title for doc_id in doc_ids],
        [documents[doc_id].text for doc_id in doc_ids],
        manifest_path=manifest_path,
        cache_root=cache_root,
    )
    seconds = clock() - started
    if seconds < 0.0 or not math.isfinite(seconds):
        raise Gold10BenchmarkError("MedCPT build clock moved backwards or became non-finite")
    return index, seconds


__all__ = [
    "ADJUDICATION_PROVENANCE",
    "BENCHMARK_OUTPUT_ROOT",
    "BENCHMARK_RUN_ID",
    "CANONICAL_INPUT_ROOT",
    "CORPUS_SIZE",
    "MODES",
    "MODE_BM25",
    "MODE_MEDCPT",
    "MODE_RRF",
    "ArtifactIdentity",
    "BenchmarkRun",
    "Gold10BenchmarkDataset",
    "Gold10BenchmarkError",
    "Gold10BenchmarkRunner",
    "Gold10Document",
    "Gold10InputPaths",
    "Gold10Question",
    "ModeResult",
    "QueryResult",
    "RankingEntry",
    "build_local_medcpt_index",
    "load_gold10_v2_dataset",
    "save_benchmark_run",
    "validate_benchmark_output_root",
]
