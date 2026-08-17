"""Exact offline benchmark adapter for the Owner-confirmed Dev-40 corpus."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
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
from typing import Any, Final, Protocol, cast

from evaluation.dev40_corpus import (
    Dev40CorpusError,
    load_and_validate_freeze,
    validate_retrieval_units,
)
from evaluation.medcpt import MedCPTIndex
from evaluation.metrics import ndcg_at_k, percentile, recall_at_k, reciprocal_rank_at_k
from medevidence.retrieval.core import BM25Index, component_ranks, reciprocal_rank_fusion

WORK_ITEM: Final = "M2-006-MEDEVIDENCE-DEV40"
DATASET: Final = "MEDEVIDENCE_DEV40"
SCHEMA_VERSION: Final = "medevidence.dev40.benchmark.v1"
EVIDENCE_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-006-MEDEVIDENCE-DEV40")
FREEZE_ROOT: Final = EVIDENCE_ROOT / "corpus-freeze-001"
OWNER_BUNDLE_ROOT: Final = EVIDENCE_ROOT / "owner-confirmed-bundle-001"
BENCHMARK_RUN_ID: Final = "M2-006-MEDEVIDENCE-DEV40-BENCHMARK-001"
BENCHMARK_OUTPUT_ROOT: Final = EVIDENCE_ROOT / "benchmark-001"

CORPUS_BYTES: Final = 1_111_679
CORPUS_SHA256: Final = "249e4157c142d9738af6d5b5c5a88d6515461416b10e8f7bf8b38226c1a93e4a"
PACKET_BYTES: Final = 13_408_759
PACKET_SHA256: Final = "b3ff81d2a76aa21a16cee40b9f530e345bd92830c478a4d9c1c66048a1720203"
QRELS_BYTES: Final = 1_257_098
QRELS_SHA256: Final = "3d871bae8ffd2be46e2546da01d5e67c93b25d2450b8dc8a09a579c0a905777d"
NONZERO_QRELS_BYTES: Final = 245_738
NONZERO_QRELS_SHA256: Final = "0b69ecb73ef4ba592658a56373e1cdf46b785286d67345dd96f7bb601dc69393"
ADJUDICATION_BYTES: Final = 328_121
ADJUDICATION_SHA256: Final = "6bba185b62b9bcd172c7cf694a9012a55eb91d880aec35bef9ee52c37ae2559f"
CONTRACT_BYTES: Final = 3_269
CONTRACT_SHA256: Final = "a8d2f92266ec1d12ca9889c80d19b9b1b10dd2ce5f2ef8d8851011740995d50b"
BUNDLE_MANIFEST_BYTES: Final = 1_452
BUNDLE_MANIFEST_SHA256: Final = "1269869d85821286dbadccdaaacdb5975ca18dbdf743782bf477a67628d623e0"

RUN_PLAN_BYTES: Final = 327
RUN_PLAN_SHA256: Final = "33305f4495562a4b9aea4609318304e893d491374bf177ffd87d4b50d5b1b8ac"
RECONCILIATION_BYTES: Final = 1_804
RECONCILIATION_SHA256: Final = "25b2100b801d0b88f7d75352893250d11eea262792f6912cd912d81cc81442dd"
FROZEN_SOURCE_STATE_BYTES: Final = 8_201
FROZEN_SOURCE_STATE_SHA256: Final = (
    "a29bd4cad20c5497e270f0da1bbba30b29b9fbd981079c25034fc21ecac01173"
)

MODE_BM25: Final = "BM25"
MODE_MEDCPT: Final = "MedCPT"
MODE_RRF: Final = "RRF(BM25,MedCPT)"
MODES: Final = (MODE_BM25, MODE_MEDCPT, MODE_RRF)
MODE_FILENAMES: Final = {
    MODE_BM25: "per-question-bm25.jsonl",
    MODE_MEDCPT: "per-question-medcpt.jsonl",
    MODE_RRF: "per-question-rrf-bm25-medcpt.jsonl",
}
BM25_K1: Final = 0.9
BM25_B: Final = 0.4
RRF_K: Final = 60
CORPUS_SIZE: Final = 214
QUESTION_COUNT: Final = 23
JUDGMENT_COUNT: Final = 4_922
NONZERO_JUDGMENT_COUNT: Final = 857
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
ADJUDICATION_PROVENANCE: Final = (
    "blinded AI adjudication from the frozen packet plus supplemental source metadata; "
    "Owner-confirmed; not independently human-authored"
)

QUESTION_IDS: Final = (
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "Q5",
    "Q6",
    "Q7",
    "Q8",
    "Q9",
    "Q10",
    "Q11",
    "Q12",
    "Q13",
    "Q14",
    "Q15",
    "Q16",
    "Q18",
    "Q24",
    "Q26",
    "Q28",
    "Q29",
    "Q33",
    "Q38",
)
RANKING_METRIC_QUESTION_IDS: Final = QUESTION_IDS[:18] + QUESTION_IDS[21:]
SOURCE_STATE_QUESTION_IDS: Final = ("Q26", "Q28", "Q29")
DIRECT_METRIC_QUESTION_IDS: Final = (
    "Q1",
    "Q3",
    "Q4",
    "Q5",
    "Q6",
    "Q7",
    "Q8",
    "Q9",
    "Q10",
    "Q11",
    "Q12",
    "Q13",
    "Q14",
    "Q15",
    "Q24",
    "Q33",
    "Q38",
)
DIRECT_EXCLUDED_QUESTION_IDS: Final = ("Q2", "Q16", "Q18", "Q26", "Q28", "Q29")

QRELS_HEADER: Final = (
    "question_id",
    "retrieval_unit_id",
    "relevance_grade",
    "source",
    "title",
    "adjudication_note",
)
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
PUBMED_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {
    "abstract_sections",
    "query_memberships",
    "reused_from_work_item",
    "source_artifact_sha256",
}
PUBMED_BOOK_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {
    "abstract_sections",
    "authors",
    "book_accession",
    "book_title",
    "content_identity",
    "languages",
    "lineage",
    "mapping_disposition",
    "medium",
    "pmid",
    "provider_record_kind",
    "publication_date",
    "publication_types",
    "publisher_location",
    "publisher_name",
    "query_memberships",
    "retrieval_unit_kind",
    "source_artifact_sha256",
    "source_identity",
}
DAILYMED_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {
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
PACKET_CANDIDATE_FIELDS: Final = COMMON_DOCUMENT_FIELDS | {"candidate_ordinal"}
PACKET_BOOK_CANDIDATE_FIELDS: Final = PACKET_CANDIDATE_FIELDS | {
    "book_accession",
    "book_title",
    "content_identity",
    "pmid",
    "provider_record_kind",
    "retrieval_unit_kind",
    "source_identity",
}


class Dev40BenchmarkError(RuntimeError):
    """Fail-closed Dev-40 input, execution, or persistence error."""


@dataclass(frozen=True, slots=True)
class Dev40InputPaths:
    """The seven exact Owner-approved Dev-40 evidence paths."""

    corpus: Path
    packet: Path
    qrels: Path
    nonzero_qrels: Path
    adjudication: Path
    contract: Path
    bundle_manifest: Path

    @classmethod
    def canonical(cls) -> Dev40InputPaths:
        return cls(
            corpus=FREEZE_ROOT / "corpus-manifest.json",
            packet=FREEZE_ROOT / "blinded-adjudication-packet.json",
            qrels=OWNER_BUNDLE_ROOT / "dev40-owner-confirmed-qrels-v1.tsv",
            nonzero_qrels=(OWNER_BUNDLE_ROOT / "dev40-owner-confirmed-nonzero-qrels-v1.tsv"),
            adjudication=(OWNER_BUNDLE_ROOT / "dev40-owner-confirmed-ai-adjudication-v1.json"),
            contract=OWNER_BUNDLE_ROOT / "dev40-owner-confirmed-metric-contract-v1.json",
            bundle_manifest=(OWNER_BUNDLE_ROOT / "dev40-owner-confirmed-bundle-manifest.json"),
        )


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Exact identity of one trusted external input."""

    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Dev40Document:
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
class Dev40Question:
    """One adjudicated development question and its metric eligibility."""

    question_id: str
    text: str
    judgments: Mapping[str, int]
    notes: Mapping[str, str]
    ranking_metric_eligible: bool
    direct_answer_eligible: bool
    metric_exclusion_reason: str | None


@dataclass(frozen=True, slots=True)
class Dev40BenchmarkDataset:
    """Fully reconciled 23-question, 214-document Dev-40 dataset."""

    documents: tuple[Dev40Document, ...]
    questions: tuple[Dev40Question, ...]
    input_identities: Mapping[str, ArtifactIdentity]
    freeze_identities: Mapping[str, ArtifactIdentity]
    freeze_validation: str
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
    """One question/mode result with metrics and complete ranking evidence."""

    question_id: str
    question: str
    mode: str
    ranking_metric_eligible: bool
    direct_answer_eligible: bool
    metric_exclusion_reason: str | None
    latency_ms: float
    metrics: Mapping[str, float | None]
    rankings: tuple[RankingEntry, ...]


@dataclass(frozen=True, slots=True)
class ModeResult:
    """One exact retrieval mode over the 20 ordered ranking-evaluable questions."""

    mode: str
    records: tuple[QueryResult, ...]
    macro_metrics: Mapping[str, float]
    metric_denominators: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """All three frozen modes and measured build timings."""

    modes: Mapping[str, ModeResult]
    build_timings_seconds: Mapping[str, float]
    source_state: Mapping[str, Any]


class _ArtifactProvenance(Protocol):
    def provenance(self) -> Mapping[str, Any]: ...


class MedCPTSearchIndex(Protocol):
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


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Dev40BenchmarkError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strict_json(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Dev40BenchmarkError(f"{label} is not strict UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise Dev40BenchmarkError(f"{label} must be a JSON object")
    return value


def _input_specs() -> dict[str, tuple[Path, int, str]]:
    paths = Dev40InputPaths.canonical()
    return {
        "corpus": (paths.corpus, CORPUS_BYTES, CORPUS_SHA256),
        "packet": (paths.packet, PACKET_BYTES, PACKET_SHA256),
        "qrels": (paths.qrels, QRELS_BYTES, QRELS_SHA256),
        "nonzero_qrels": (
            paths.nonzero_qrels,
            NONZERO_QRELS_BYTES,
            NONZERO_QRELS_SHA256,
        ),
        "adjudication": (
            paths.adjudication,
            ADJUDICATION_BYTES,
            ADJUDICATION_SHA256,
        ),
        "contract": (paths.contract, CONTRACT_BYTES, CONTRACT_SHA256),
        "bundle_manifest": (
            paths.bundle_manifest,
            BUNDLE_MANIFEST_BYTES,
            BUNDLE_MANIFEST_SHA256,
        ),
    }


def _read_exact_inputs(
    paths: Dev40InputPaths,
) -> tuple[dict[str, bytes], dict[str, ArtifactIdentity]]:
    supplied = asdict(paths)
    payloads: dict[str, bytes] = {}
    identities: dict[str, ArtifactIdentity] = {}
    for label, (expected_path, expected_bytes, expected_sha256) in _input_specs().items():
        path = Path(supplied[label])
        if path.is_symlink() or not path.is_file():
            raise Dev40BenchmarkError(f"{label} input must be an exact regular file")
        actual = path.resolve(strict=True)
        expected = expected_path.resolve(strict=True)
        if actual != expected:
            raise Dev40BenchmarkError(f"{label} input path differs from the frozen path")
        data = actual.read_bytes()
        if len(data) != expected_bytes or _sha256(data) != expected_sha256:
            raise Dev40BenchmarkError(f"{label} input identity drifted")
        payloads[label] = data
        identities[label] = ArtifactIdentity(str(actual), len(data), _sha256(data))
    return payloads, identities


def _read_freeze_context() -> tuple[dict[str, ArtifactIdentity], str]:
    """Bind immutable freeze evidence without requiring stale repository bytes."""

    specs = {
        "run_plan": (FREEZE_ROOT / "run-plan.json", RUN_PLAN_BYTES, RUN_PLAN_SHA256),
        "source_reconciliation": (
            FREEZE_ROOT / "source-reconciliation.json",
            RECONCILIATION_BYTES,
            RECONCILIATION_SHA256,
        ),
        "frozen_source_state": (
            FREEZE_ROOT / "source-state-inventory.json",
            FROZEN_SOURCE_STATE_BYTES,
            FROZEN_SOURCE_STATE_SHA256,
        ),
    }
    identities: dict[str, ArtifactIdentity] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for label, (path, size, digest) in specs.items():
        if path.is_symlink() or not path.is_file():
            raise Dev40BenchmarkError(f"{label} freeze evidence is unavailable")
        data = path.read_bytes()
        if len(data) != size or _sha256(data) != digest:
            raise Dev40BenchmarkError(f"{label} freeze evidence identity drifted")
        sidecar = path.with_suffix(path.suffix + ".sha256")
        try:
            sidecar_text = sidecar.read_text(encoding="ascii")
        except (OSError, UnicodeError) as error:
            raise Dev40BenchmarkError(f"{label} freeze sidecar is unavailable") from error
        if sidecar_text != f"{digest}  {path.name}\n":
            raise Dev40BenchmarkError(f"{label} freeze sidecar drifted")
        identities[label] = ArtifactIdentity(str(path.resolve()), size, digest)
        payloads[label] = _strict_json(data, label=label)
    if payloads["run_plan"] != {
        "authoritative_qrels_created": False,
        "expected_corpus_units": CORPUS_SIZE,
        "expected_retrieval_questions": QUESTION_COUNT,
        "holdout_accessed": False,
        "medical_source_requests": 0,
        "mode": "offline_retained_evidence_only",
        "rankings_scores_models_used": False,
        "schema_version": "medevidence.dev40.corpus.v1.run-plan.v1",
        "work_item": WORK_ITEM,
    }:
        raise Dev40BenchmarkError("frozen run plan semantics drifted")
    reconciliation = payloads["source_reconciliation"]
    if (
        set(reconciliation)
        != {
            "cadec",
            "dailymed",
            "faers_d",
            "limitations",
            "network_operations",
            "pubmed_pairs",
            "pubmed_union",
            "schema_version",
            "status",
            "work_item",
        }
        or reconciliation.get("network_operations") != 0
        or reconciliation.get("status") != "COMPLETE"
        or reconciliation.get("work_item") != WORK_ITEM
        or reconciliation.get("dailymed") != {"mounjaro_sections": 3, "ozempic_sections": 12}
        or reconciliation.get("pubmed_union", {}).get("provider_records") != 199
    ):
        raise Dev40BenchmarkError("frozen source reconciliation semantics drifted")
    try:
        load_and_validate_freeze(FREEZE_ROOT)
    except Dev40CorpusError as error:
        if str(error) != "frozen blinded packet does not bind the exact corpus":
            raise Dev40BenchmarkError("Dev-40 freeze verifier failed unexpectedly") from error
        validation = (
            "independent_exact_byte_validation_required: historical frozen source-state "
            "does not equal current repository source-state"
        )
    else:
        validation = "load_and_validate_freeze_passed"
    return identities, validation


def _parse_corpus(data: bytes) -> tuple[Dev40Document, ...]:
    payload = _strict_json(data, label="Dev-40 corpus")
    if set(payload) != {
        "counts",
        "dataset",
        "gold10_v2_immutable_binding",
        "items",
        "question_set_binding",
        "schema_version",
        "source_coverage_limitations",
        "split",
        "status",
        "work_item",
    }:
        raise Dev40BenchmarkError("corpus top-level schema is not exact")
    if (
        payload.get("schema_version") != "medevidence.dev40.corpus.v1.manifest.v1"
        or payload.get("dataset") != DATASET
        or payload.get("split") != "Development-40"
        or payload.get("work_item") != WORK_ITEM
        or payload.get("status") != "FROZEN_AWAITING_OWNER_ADJUDICATION"
        or payload.get("counts")
        != {
            "dailymed_section": 15,
            "pubmed_article": 198,
            "pubmed_book_document": 1,
            "pubmed_total": 199,
            "total": CORPUS_SIZE,
        }
    ):
        raise Dev40BenchmarkError("corpus identity, status, or counts drifted")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != CORPUS_SIZE:
        raise Dev40BenchmarkError("corpus must contain exactly 214 items")
    typed_items: list[Mapping[str, Any]] = []
    documents: list[Dev40Document] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise Dev40BenchmarkError("corpus item must be an object")
        if item.get("retrieval_unit_kind") == "pubmed_book_document":
            expected_fields = PUBMED_BOOK_FIELDS
        elif item.get("source") == "pubmed":
            expected_fields = PUBMED_FIELDS
        else:
            expected_fields = DAILYMED_FIELDS
        if set(item) != expected_fields:
            raise Dev40BenchmarkError("corpus retrieval-unit schema is not exact")
        if item.get("source") not in {"pubmed", "dailymed"}:
            raise Dev40BenchmarkError("corpus source is not exact")
        if item.get("source") == "dailymed" and item.get("retrieval_eligible") is not True:
            raise Dev40BenchmarkError("structural DailyMed evidence cannot enter retrieval")
        values = {field: item.get(field) for field in COMMON_DOCUMENT_FIELDS}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise Dev40BenchmarkError("corpus identity/title/text fields must be non-empty")
        document = Dev40Document(**cast(dict[str, str], values))
        if document.retrieval_unit_id in seen:
            raise Dev40BenchmarkError("corpus retrieval unit ids must be unique")
        seen.add(document.retrieval_unit_id)
        typed_items.append(item)
        documents.append(document)
    try:
        counts = validate_retrieval_units(typed_items)
    except Dev40CorpusError as error:
        raise Dev40BenchmarkError("corpus retrieval units failed shared validation") from error
    if counts != {
        "pubmed_article": 198,
        "pubmed_book_document": 1,
        "dailymed_section": 15,
    }:
        raise Dev40BenchmarkError("corpus source counts do not reconcile")
    return tuple(sorted(documents, key=lambda document: document.retrieval_unit_id))


def _parse_packet(data: bytes, documents: Mapping[str, Dev40Document]) -> dict[str, Any]:
    payload = _strict_json(data, label="Dev-40 blinded packet")
    if set(payload) != {
        "adjudication_status",
        "corpus_manifest_sha256",
        "dataset",
        "excluded_non_retrieval_questions",
        "ordering",
        "question_provenance",
        "questions",
        "retrieval_question_count",
        "schema_version",
        "work_item",
    }:
        raise Dev40BenchmarkError("blinded packet top-level schema is not exact")
    if (
        payload.get("schema_version")
        != "medevidence.dev40.corpus.v1.blinded-adjudication-packet.v1"
        or payload.get("dataset") != DATASET
        or payload.get("work_item") != WORK_ITEM
        or payload.get("corpus_manifest_sha256") != CORPUS_SHA256
        or payload.get("adjudication_status") != "OWNER_ADJUDICATION_REQUIRED"
        or payload.get("ordering") != "sha256(dataset NUL question_id NUL retrieval_unit_id)"
        or payload.get("retrieval_question_count") != QUESTION_COUNT
    ):
        raise Dev40BenchmarkError("blinded packet identity or status drifted")
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != QUESTION_COUNT:
        raise Dev40BenchmarkError("blinded packet must contain exactly 23 questions")
    if tuple(question.get("question_id") for question in questions) != QUESTION_IDS:
        raise Dev40BenchmarkError("blinded packet question ids/order drifted")
    for question in questions:
        if not isinstance(question, dict) or set(question) != {
            "candidate_count",
            "candidates",
            "evaluation_layer",
            "question",
            "question_id",
        }:
            raise Dev40BenchmarkError("blinded packet question schema is not exact")
        if (
            question.get("candidate_count") != CORPUS_SIZE
            or not isinstance(question.get("question"), str)
            or not question["question"]
            or not isinstance(question.get("evaluation_layer"), str)
        ):
            raise Dev40BenchmarkError("blinded packet question identity drifted")
        candidates = question.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != CORPUS_SIZE:
            raise Dev40BenchmarkError("every question must contain 214 candidates")
        seen: set[str] = set()
        for ordinal, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                raise Dev40BenchmarkError("packet candidate must be an object")
            fields = (
                PACKET_BOOK_CANDIDATE_FIELDS
                if candidate.get("retrieval_unit_kind") == "pubmed_book_document"
                else PACKET_CANDIDATE_FIELDS
            )
            if set(candidate) != fields:
                raise Dev40BenchmarkError("packet candidate schema is not exact")
            doc_id = candidate.get("retrieval_unit_id")
            if candidate.get("candidate_ordinal") != ordinal or doc_id not in documents:
                raise Dev40BenchmarkError("packet candidate ordinal or identity drifted")
            if doc_id in seen:
                raise Dev40BenchmarkError("packet candidate identity is duplicated")
            seen.add(str(doc_id))
            document = documents[str(doc_id)]
            for field in COMMON_DOCUMENT_FIELDS:
                if candidate.get(field) != getattr(document, field):
                    raise Dev40BenchmarkError("packet candidate differs from frozen corpus")
        if seen != set(documents):
            raise Dev40BenchmarkError("packet candidate set does not equal the corpus")
    return payload


def _parse_tsv(data: bytes, *, label: str, expected_rows: int) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise Dev40BenchmarkError(f"{label} are not strict UTF-8") from error
    if "\x00" in text or not text.endswith("\n"):
        raise Dev40BenchmarkError(f"{label} must be newline-terminated TSV")
    if "\r" in text:
        raise Dev40BenchmarkError(f"{label} must use canonical LF-only line endings")
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True))
    except csv.Error as error:
        raise Dev40BenchmarkError(f"{label} are not canonical quoted TSV") from error
    if not rows or tuple(rows[0]) != QRELS_HEADER or len(set(rows[0])) != len(rows[0]):
        raise Dev40BenchmarkError(f"{label} header is not exact and unique")
    if len(rows) != expected_rows + 1:
        raise Dev40BenchmarkError(f"{label} row count is not exact")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows[1:]:
        if len(raw) != len(QRELS_HEADER):
            raise Dev40BenchmarkError(f"{label} row must have exactly six fields")
        row = dict(zip(QRELS_HEADER, raw, strict=True))
        pair = (row["question_id"], row["retrieval_unit_id"])
        if pair in seen:
            raise Dev40BenchmarkError(f"{label} contain a duplicate pair")
        seen.add(pair)
        if row["relevance_grade"] not in {"0", "1", "2"} or not row["adjudication_note"]:
            raise Dev40BenchmarkError(f"{label} grade or note is invalid")
        result.append(row)
    return result


def _parse_contract(data: bytes) -> dict[str, Any]:
    payload = _strict_json(data, label="Dev-40 metric contract")
    if set(payload) != {
        "benchmark_scope_after_owner_confirmation",
        "bound_inputs",
        "direct_metrics",
        "interpretation",
        "owner_confirmation",
        "primary_metric",
        "relevance",
        "schema_version",
        "secondary_broad_metrics",
        "source_state_behavior_cases",
        "status",
        "work_item",
    }:
        raise Dev40BenchmarkError("metric contract top-level schema is not exact")
    scope = payload.get("benchmark_scope_after_owner_confirmation")
    primary = payload.get("primary_metric")
    direct = payload.get("direct_metrics")
    broad = payload.get("secondary_broad_metrics")
    interpretation = payload.get("interpretation")
    bindings = payload.get("bound_inputs")
    if (
        payload.get("schema_version") != "medevidence.dev40.metric_contract.authoritative.v1"
        or payload.get("work_item") != WORK_ITEM
        or payload.get("status") != "OWNER_CONFIRMED"
        or not isinstance(scope, dict)
        or scope.get("modes") != list(MODES)
        or scope.get("holdout_access") is not False
        or scope.get("parameter_tuning_authorized_by_this_contract") is not False
        or scope.get("reranker_authorized") is not False
        or not isinstance(primary, dict)
        or tuple(primary.get("macro_questions", ())) != RANKING_METRIC_QUESTION_IDS
        or primary.get("macro_question_count") != 20
        or tuple(primary.get("zero_relevant_questions_excluded", ())) != SOURCE_STATE_QUESTION_IDS
        or not isinstance(direct, dict)
        or direct.get("macro_question_count") != 17
        or tuple(direct.get("DirectHit@10", {}).get("macro_questions", ()))
        != DIRECT_METRIC_QUESTION_IDS
        or tuple(direct.get("DirectMRR@10", {}).get("macro_questions", ()))
        != DIRECT_METRIC_QUESTION_IDS
        or tuple(direct.get("excluded_no_grade2_questions", ())) != DIRECT_EXCLUDED_QUESTION_IDS
        or not isinstance(broad, dict)
        or any(
            tuple(broad.get(name, {}).get("macro_questions", ())) != RANKING_METRIC_QUESTION_IDS
            for name in ("Recall@5", "Recall@10", "MRR@10")
        )
        or interpretation
        != {
            "development_set": True,
            "note": (
                "Dev-40 may inform development decisions; Holdout-20 remains untouched for "
                "release-candidate evaluation."
            ),
            "results_descriptive_only": True,
            "statistical_superiority_claims_allowed": False,
        }
        or not isinstance(bindings, dict)
        or bindings.get("corpus_manifest_sha256") != CORPUS_SHA256
        or bindings.get("blinded_packet_sha256") != PACKET_SHA256
        or bindings.get("authoritative_full_qrels_sha256") != QRELS_SHA256
        or bindings.get("authoritative_nonzero_qrels_sha256") != NONZERO_QRELS_SHA256
        or bindings.get("authoritative_ai_adjudication_sha256") != ADJUDICATION_SHA256
        or set(payload.get("source_state_behavior_cases", {})) != set(SOURCE_STATE_QUESTION_IDS)
    ):
        raise Dev40BenchmarkError("metric contract semantics or bindings drifted")
    return payload


def _parse_bundle_manifest(data: bytes) -> dict[str, Any]:
    payload = _strict_json(data, label="Owner-confirmed bundle manifest")
    if set(payload) != {
        "bound_inputs",
        "files",
        "judgment_counts",
        "owner_confirmation",
        "provenance",
        "schema_version",
        "status",
        "work_item",
    }:
        raise Dev40BenchmarkError("bundle manifest top-level schema is not exact")
    files = payload.get("files")
    expected_files = {
        "dev40-owner-confirmed-ai-adjudication-v1.json": {
            "bytes": ADJUDICATION_BYTES,
            "sha256": ADJUDICATION_SHA256,
        },
        "dev40-owner-confirmed-metric-contract-v1.json": {
            "bytes": CONTRACT_BYTES,
            "sha256": CONTRACT_SHA256,
        },
        "dev40-owner-confirmed-nonzero-qrels-v1.tsv": {
            "bytes": NONZERO_QRELS_BYTES,
            "sha256": NONZERO_QRELS_SHA256,
        },
        "dev40-owner-confirmed-qrels-v1.tsv": {
            "bytes": QRELS_BYTES,
            "sha256": QRELS_SHA256,
        },
    }
    if (
        payload.get("schema_version") != "medevidence.dev40.owner_confirmed_bundle.v1"
        or payload.get("work_item") != WORK_ITEM
        or payload.get("status") != "OWNER_CONFIRMED"
        or files != expected_files
        or payload.get("bound_inputs", {}).get("corpus_manifest_sha256") != CORPUS_SHA256
        or payload.get("bound_inputs", {}).get("blinded_packet_sha256") != PACKET_SHA256
        or payload.get("judgment_counts")
        != {
            "candidates_per_question": CORPUS_SIZE,
            "direct_metric_questions": 17,
            "grade_0": 4_065,
            "grade_1": 380,
            "grade_2": 477,
            "nonzero_qrels": NONZERO_JUDGMENT_COUNT,
            "questions": QUESTION_COUNT,
            "retrieval_metric_questions": 20,
            "source_state_behavior_questions": list(SOURCE_STATE_QUESTION_IDS),
            "total_judgments": JUDGMENT_COUNT,
        }
    ):
        raise Dev40BenchmarkError("bundle manifest bindings or counts drifted")
    return payload


def _parse_adjudication(
    data: bytes,
    packet: Mapping[str, Any],
    qrels: Sequence[Mapping[str, str]],
    documents: Mapping[str, Dev40Document],
) -> dict[str, Any]:
    payload = _strict_json(data, label="Owner-confirmed adjudication")
    if set(payload) != {
        "access_constraints",
        "bound_inputs",
        "consistency_pass",
        "dataset",
        "grading_contract",
        "outputs",
        "owner_confirmation",
        "provenance",
        "questions",
        "schema_version",
        "status",
        "work_item",
        "zero_relevant_source_state_questions",
    }:
        raise Dev40BenchmarkError("adjudication top-level schema is not exact")
    access = payload.get("access_constraints")
    bindings = payload.get("bound_inputs")
    consistency = payload.get("consistency_pass")
    if (
        payload.get("schema_version") != "medevidence.dev40.owner_ai_adjudication.authoritative.v1"
        or payload.get("dataset") != DATASET
        or payload.get("work_item") != WORK_ITEM
        or payload.get("status") != "OWNER_CONFIRMED"
        or payload.get("provenance") != ADJUDICATION_PROVENANCE
        or not isinstance(access, dict)
        or access.get("holdout_accessed") is not False
        or access.get("medical_source_network_operations") != 0
        or access.get("retriever_rankings_accessed") is not False
        or not isinstance(bindings, dict)
        or bindings.get("corpus_manifest_sha256") != CORPUS_SHA256
        or bindings.get("blinded_packet_sha256") != PACKET_SHA256
        or not isinstance(consistency, dict)
        or tuple(consistency.get("retrieval_evaluable_questions", ()))
        != RANKING_METRIC_QUESTION_IDS
        or tuple(consistency.get("zero_relevant_retrieval_unit_questions", ()))
        != SOURCE_STATE_QUESTION_IDS
        or tuple(consistency.get("direct_answerable_questions", ())) != DIRECT_METRIC_QUESTION_IDS
        or consistency.get("total_judgments") != JUDGMENT_COUNT
        or set(payload.get("zero_relevant_source_state_questions", {}))
        != set(SOURCE_STATE_QUESTION_IDS)
    ):
        raise Dev40BenchmarkError("adjudication authority, access, or counts drifted")
    row_by_pair = {(row["question_id"], row["retrieval_unit_id"]): row for row in qrels}
    packet_questions = {row["question_id"]: row for row in packet["questions"]}
    questions = payload.get("questions")
    if not isinstance(questions, list) or len(questions) != QUESTION_COUNT:
        raise Dev40BenchmarkError("adjudication must contain exactly 23 questions")
    if tuple(question.get("question_id") for question in questions) != QUESTION_IDS:
        raise Dev40BenchmarkError("adjudication question order drifted")
    observed_nonzero: set[tuple[str, str]] = set()
    for question in questions:
        if not isinstance(question, dict) or set(question) != {
            "candidate_count",
            "grade_counts",
            "nonzero_judgments",
            "question",
            "question_id",
        }:
            raise Dev40BenchmarkError("adjudication question schema is not exact")
        question_id = question["question_id"]
        if (
            question.get("question") != packet_questions[question_id]["question"]
            or question.get("candidate_count") != CORPUS_SIZE
        ):
            raise Dev40BenchmarkError("adjudication question differs from blinded packet")
        judgments = question.get("nonzero_judgments")
        if not isinstance(judgments, list):
            raise Dev40BenchmarkError("nonzero adjudication judgments must be a list")
        counts = {"0": CORPUS_SIZE - len(judgments), "1": 0, "2": 0}
        for judgment in judgments:
            if not isinstance(judgment, dict) or set(judgment) != {
                "adjudication_note",
                "relevance_grade",
                "retrieval_unit_id",
                "source",
                "title",
            }:
                raise Dev40BenchmarkError("nonzero adjudication schema is not exact")
            doc_id = judgment["retrieval_unit_id"]
            pair = (question_id, doc_id)
            row = row_by_pair.get(pair)
            if pair in observed_nonzero or row is None or doc_id not in documents:
                raise Dev40BenchmarkError("nonzero adjudication pair is invalid or duplicated")
            observed_nonzero.add(pair)
            grade = judgment["relevance_grade"]
            if type(grade) is not int or grade not in {1, 2}:
                raise Dev40BenchmarkError("nonzero adjudication grade is invalid")
            counts[str(grade)] += 1
            if (
                row["relevance_grade"] != str(grade)
                or row["source"] != judgment["source"]
                or row["title"] != judgment["title"]
                or row["adjudication_note"] != judgment["adjudication_note"]
                or documents[doc_id].source != judgment["source"]
                or documents[doc_id].title != judgment["title"]
            ):
                raise Dev40BenchmarkError("qrels differ from adjudication/corpus evidence")
        if question.get("grade_counts") != counts:
            raise Dev40BenchmarkError("adjudication grade counts do not reconcile")
    expected_nonzero = {
        (row["question_id"], row["retrieval_unit_id"])
        for row in qrels
        if row["relevance_grade"] != "0"
    }
    if observed_nonzero != expected_nonzero:
        raise Dev40BenchmarkError("adjudication nonzero pairs differ from full qrels")
    return payload


def _reconcile_questions(
    packet: Mapping[str, Any],
    qrels: Sequence[Mapping[str, str]],
    documents: Mapping[str, Dev40Document],
    exclusion_reasons: Mapping[str, str],
) -> tuple[Dev40Question, ...]:
    row_by_pair = {(row["question_id"], row["retrieval_unit_id"]): row for row in qrels}
    expected_pairs = {(question_id, doc_id) for question_id in QUESTION_IDS for doc_id in documents}
    if set(row_by_pair) != expected_pairs:
        raise Dev40BenchmarkError("qrels do not exactly cover the question/corpus product")
    questions: list[Dev40Question] = []
    for packet_question in packet["questions"]:
        question_id = packet_question["question_id"]
        judgments: dict[str, int] = {}
        notes: dict[str, str] = {}
        for candidate in packet_question["candidates"]:
            doc_id = candidate["retrieval_unit_id"]
            row = row_by_pair[(question_id, doc_id)]
            document = documents[doc_id]
            if row["source"] != document.source or row["title"] != document.title:
                raise Dev40BenchmarkError("qrels source/title differ from corpus evidence")
            judgments[doc_id] = int(row["relevance_grade"])
            notes[doc_id] = row["adjudication_note"]
        questions.append(
            Dev40Question(
                question_id=question_id,
                text=packet_question["question"],
                judgments=judgments,
                notes=notes,
                ranking_metric_eligible=question_id in RANKING_METRIC_QUESTION_IDS,
                direct_answer_eligible=question_id in DIRECT_METRIC_QUESTION_IDS,
                metric_exclusion_reason=exclusion_reasons.get(question_id),
            )
        )
    if any(
        question.direct_answer_eligible != any(grade == 2 for grade in question.judgments.values())
        for question in questions
    ):
        raise Dev40BenchmarkError("direct metric eligibility differs from qrels")
    if any(
        question.ranking_metric_eligible != any(grade >= 1 for grade in question.judgments.values())
        for question in questions
    ):
        raise Dev40BenchmarkError("ranking metric eligibility differs from qrels")
    return tuple(questions)


def load_dev40_dataset(paths: Dev40InputPaths) -> Dev40BenchmarkDataset:
    """Load and cross-reconcile every exact external Dev-40 input."""

    payloads, identities = _read_exact_inputs(paths)
    freeze_identities, freeze_validation = _read_freeze_context()
    documents = _parse_corpus(payloads["corpus"])
    documents_by_id = {document.retrieval_unit_id: document for document in documents}
    packet = _parse_packet(payloads["packet"], documents_by_id)
    qrels = _parse_tsv(payloads["qrels"], label="qrels", expected_rows=JUDGMENT_COUNT)
    nonzero = _parse_tsv(
        payloads["nonzero_qrels"],
        label="nonzero qrels",
        expected_rows=NONZERO_JUDGMENT_COUNT,
    )
    expected_nonzero = [row for row in qrels if row["relevance_grade"] != "0"]
    if nonzero != expected_nonzero or any(row["relevance_grade"] == "0" for row in nonzero):
        raise Dev40BenchmarkError("nonzero qrels do not exactly equal the full-qrels subset")
    contract = _parse_contract(payloads["contract"])
    _parse_bundle_manifest(payloads["bundle_manifest"])
    _parse_adjudication(payloads["adjudication"], packet, qrels, documents_by_id)
    questions = _reconcile_questions(
        packet,
        qrels,
        documents_by_id,
        cast(Mapping[str, str], contract["source_state_behavior_cases"]),
    )
    return Dev40BenchmarkDataset(
        documents=documents,
        questions=questions,
        input_identities=identities,
        freeze_identities=freeze_identities,
        freeze_validation=freeze_validation,
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
        raise Dev40BenchmarkError(f"{label} did not return one exact full-corpus ranking")
    return normalized


def _full_bm25_ranking(
    index: BM25Index, query: str, expected_ids: set[str]
) -> list[tuple[str, float]]:
    scored = index.search(query, CORPUS_SIZE)
    if len({doc_id for doc_id, _score in scored}) != len(scored) or not {
        doc_id for doc_id, _score in scored
    }.issubset(expected_ids):
        raise Dev40BenchmarkError("BM25 returned duplicate or foreign document ids")
    seen = {doc_id for doc_id, _score in scored}
    complete = [*scored, *((doc_id, 0.0) for doc_id in sorted(expected_ids - seen))]
    return _validate_ranking(complete, expected_ids, label=MODE_BM25)


def _query_metrics(
    ranking: Sequence[tuple[str, float]], question: Dev40Question
) -> dict[str, float | None]:
    if not question.ranking_metric_eligible:
        raise Dev40BenchmarkError("source-state cases cannot enter ranking metrics")
    metrics: dict[str, float | None] = {
        "nDCG@10": 0.0,
        "Recall@5": 0.0,
        "Recall@10": 0.0,
        "MRR@10": 0.0,
        "DirectHit@10": None,
        "DirectMRR@10": None,
    }
    ranked_ids = [doc_id for doc_id, _score in ranking]
    metrics.update(
        {
            "nDCG@10": ndcg_at_k(ranked_ids, question.judgments, TOP_K),
            "Recall@5": recall_at_k(ranked_ids, question.judgments, 5, grade_min=1),
            "Recall@10": recall_at_k(ranked_ids, question.judgments, TOP_K, grade_min=1),
            "MRR@10": reciprocal_rank_at_k(ranked_ids, question.judgments, TOP_K, grade_min=1),
        }
    )
    if question.direct_answer_eligible:
        direct_mrr = reciprocal_rank_at_k(ranked_ids, question.judgments, TOP_K, grade_min=2)
        metrics["DirectHit@10"] = 1.0 if direct_mrr > 0.0 else 0.0
        metrics["DirectMRR@10"] = direct_mrr
    return metrics


def _macro_metrics(records: Sequence[QueryResult]) -> tuple[dict[str, float], dict[str, int]]:
    names = (
        "nDCG@10",
        "Recall@5",
        "Recall@10",
        "MRR@10",
        "DirectHit@10",
        "DirectMRR@10",
    )
    metrics: dict[str, float] = {}
    denominators: dict[str, int] = {}
    for name in names:
        values: list[float] = []
        for record in records:
            value = record.metrics[name]
            if value is not None:
                values.append(float(value))
        if not values:
            raise Dev40BenchmarkError(f"metric {name} has no eligible questions")
        metrics[name] = sum(values) / len(values)
        denominators[name] = len(values)
    if any(denominators[name] != 20 for name in names[:4]) or any(
        denominators[name] != 17 for name in names[4:]
    ):
        raise Dev40BenchmarkError("metric denominators do not match the authoritative contract")
    return metrics, denominators


def _ranking_entries(
    ranking: Sequence[tuple[str, float]],
    question: Dev40Question,
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


def _validate_mode_result(result: ModeResult, dataset: Dev40BenchmarkDataset) -> None:
    if result.mode not in MODES or len(result.records) != len(RANKING_METRIC_QUESTION_IDS):
        raise Dev40BenchmarkError("mode result identity or question count is invalid")
    dataset_question_ids = tuple(question.question_id for question in dataset.questions)
    record_question_ids = tuple(record.question_id for record in result.records)
    if dataset_question_ids != QUESTION_IDS or record_question_ids != RANKING_METRIC_QUESTION_IDS:
        raise Dev40BenchmarkError(
            "mode result questions must be exactly the 20 ordered ranking-evaluable questions"
        )
    questions = {question.question_id: question for question in dataset.questions}
    expected_ids = set(dataset.document_ids)
    for record in result.records:
        question = questions[record.question_id]
        if (
            record.question != question.text
            or record.mode != result.mode
            or record.ranking_metric_eligible != question.ranking_metric_eligible
            or record.direct_answer_eligible != question.direct_answer_eligible
            or record.metric_exclusion_reason != question.metric_exclusion_reason
            or record.latency_ms < 0.0
            or not math.isfinite(record.latency_ms)
        ):
            raise Dev40BenchmarkError("question result identity drifted")
        if not question.ranking_metric_eligible or record.metric_exclusion_reason is not None:
            raise Dev40BenchmarkError("source-state case entered ranking execution")
        ranking = [(entry.retrieval_unit_id, entry.score) for entry in record.rankings]
        _validate_ranking(ranking, expected_ids, label=result.mode)
        if tuple(entry.rank for entry in record.rankings) != tuple(range(1, CORPUS_SIZE + 1)):
            raise Dev40BenchmarkError("candidate ranks are not contiguous 1..214")
        if any(
            entry.relevance_grade != question.judgments[entry.retrieval_unit_id]
            for entry in record.rankings
        ):
            raise Dev40BenchmarkError("saved candidate grade differs from qrels")
        if dict(record.metrics) != _query_metrics(ranking, question):
            raise Dev40BenchmarkError("saved per-question metrics do not recompute")
        expected_components = {MODE_BM25, MODE_MEDCPT} if result.mode == MODE_RRF else {result.mode}
        if any(
            set(entry.component_scores) != expected_components
            or set(entry.component_ranks) != expected_components
            for entry in record.rankings
        ):
            raise Dev40BenchmarkError("saved component evidence is incomplete")
        for component in expected_components:
            ranks = [entry.component_ranks[component] for entry in record.rankings]
            if sorted(ranks) != list(range(1, CORPUS_SIZE + 1)) or any(
                not math.isfinite(entry.component_scores[component]) for entry in record.rankings
            ):
                raise Dev40BenchmarkError("saved component ranks or scores are invalid")
        if result.mode != MODE_RRF and any(
            entry.component_ranks[result.mode] != entry.rank
            or not math.isclose(
                entry.component_scores[result.mode], entry.score, rel_tol=0.0, abs_tol=0.0
            )
            for entry in record.rankings
        ):
            raise Dev40BenchmarkError("single-mode candidate and component evidence differ")
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
                raise Dev40BenchmarkError("saved RRF evidence does not reconstruct")
    metrics, denominators = _macro_metrics(result.records)
    if dict(result.macro_metrics) != metrics or dict(result.metric_denominators) != denominators:
        raise Dev40BenchmarkError("saved macro metrics do not recompute")


class Dev40BenchmarkRunner:
    """Run frozen BM25, MedCPT, and two-way RRF over all 214 units."""

    def __init__(
        self,
        dataset: Dev40BenchmarkDataset,
        medcpt_index: MedCPTSearchIndex,
        *,
        medcpt_build_seconds: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if medcpt_build_seconds < 0.0 or not math.isfinite(medcpt_build_seconds):
            raise Dev40BenchmarkError("MedCPT build timing must be finite and non-negative")
        self.dataset = dataset
        self.medcpt = medcpt_index
        self._clock = clock
        self._doc_ids = tuple(sorted(dataset.document_ids))
        if tuple(medcpt_index.doc_ids) != self._doc_ids:
            raise Dev40BenchmarkError("MedCPT index document ids differ from the frozen corpus")
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
            raise Dev40BenchmarkError("BM25 build clock moved backwards or became non-finite")
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
            ranking = _full_bm25_ranking(self.bm25, query, expected)
            return ranking, {MODE_BM25: ranking}
        if mode == MODE_MEDCPT:
            ranking = _validate_ranking(
                self.medcpt.search(query, CORPUS_SIZE), expected, label=MODE_MEDCPT
            )
            return ranking, {MODE_MEDCPT: ranking}
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
        raise Dev40BenchmarkError(f"unsupported benchmark mode {mode!r}")

    def run(self) -> BenchmarkRun:
        """Execute exactly the three Owner-frozen modes, serially."""

        source_state = _source_state()
        results: dict[str, ModeResult] = {}
        for mode in MODES:
            records: list[QueryResult] = []
            for question in self.dataset.questions:
                if not question.ranking_metric_eligible:
                    continue
                started = self._clock()
                ranking, components = self._search_mode(mode, question.text)
                latency_ms = (self._clock() - started) * 1000.0
                if latency_ms < 0.0 or not math.isfinite(latency_ms):
                    raise Dev40BenchmarkError("query clock moved backwards or became non-finite")
                records.append(
                    QueryResult(
                        question_id=question.question_id,
                        question=question.text,
                        mode=mode,
                        ranking_metric_eligible=question.ranking_metric_eligible,
                        direct_answer_eligible=question.direct_answer_eligible,
                        metric_exclusion_reason=question.metric_exclusion_reason,
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
            raise Dev40BenchmarkError("benchmark did not execute exactly the three frozen modes")
        return BenchmarkRun(results, self.build_timings_seconds, source_state)


def _source_state() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    files: dict[str, dict[str, int | str]] = {}
    for relative in (
        "evaluation/dev40_benchmark.py",
        "evaluation/dev40_corpus.py",
        "evaluation/medcpt.py",
        "evaluation/metrics.py",
        "evaluation/run_dev40_benchmark.py",
        "src/medevidence/retrieval/core.py",
        "tests/unit/evaluation/test_dev40_benchmark.py",
    ):
        path = repository / relative
        data = path.read_bytes()
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
    return {"binding": "exact current benchmark source bytes", "files": files}


def _artifact_record(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    return {"filename": path.name, "bytes": len(data), "sha256": _sha256(data)}


def _runtime_identity() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("numpy", "torch", "transformers"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise Dev40BenchmarkError(f"required runtime package {name!r} is missing") from error
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
        raise Dev40BenchmarkError("MedCPT runtime provenance schema is not exact")
    for field in ("pytorch_intra_op_threads_observed", "pytorch_inter_op_threads_observed"):
        if type(observed[field]) is not int or observed[field] != 1:
            raise Dev40BenchmarkError(f"MedCPT runtime {field} must be observed as exactly 1")
    if observed["model_parameter_dtype_observed"] != {
        "query_encoder": "torch.float32",
        "article_encoder": "torch.float32",
    }:
        raise Dev40BenchmarkError("MedCPT model dtypes must be observed as torch.float32")
    if observed["query_embedding_dtype_observed"] != "float32":
        raise Dev40BenchmarkError("MedCPT query embedding dtype must be float32")
    if observed["document_embedding_index_dtype_observed"] != "float32":
        raise Dev40BenchmarkError("MedCPT document index dtype must be float32")
    if observed["dense_index_memory_bytes"] != DENSE_INDEX_MEMORY_BYTES:
        raise Dev40BenchmarkError("MedCPT dense index memory must be exact 214x768 float32 nbytes")
    if observed["dense_index_memory_measurement"] != "numpy.ndarray.nbytes":
        raise Dev40BenchmarkError("MedCPT dense index memory measurement is not exact")
    if observed["dense_index_memory_limitation"] != DENSE_INDEX_MEMORY_LIMITATION:
        raise Dev40BenchmarkError("MedCPT dense index memory limitation is not exact")
    try:
        dimensions = medcpt_index.dimensions
        query_batch_size = medcpt_index.query_batch_size
        document_batch_size = medcpt_index.document_batch_size
    except AttributeError as error:
        raise Dev40BenchmarkError("MedCPT runtime configuration is incomplete") from error
    if type(medcpt_index) is MedCPTIndex:
        device: Any = MEDCPT_DEVICE
    else:
        try:
            device = vars(medcpt_index)["device"]
        except (TypeError, KeyError) as error:
            raise Dev40BenchmarkError("MedCPT runtime device evidence is incomplete") from error
    if device != MEDCPT_DEVICE:
        raise Dev40BenchmarkError("MedCPT runtime device must be CPU")
    if dimensions != MEDCPT_DIMENSIONS:
        raise Dev40BenchmarkError("MedCPT dimensions must be exactly 768")
    if (
        query_batch_size != MEDCPT_QUERY_BATCH_SIZE
        or document_batch_size != MEDCPT_DOCUMENT_BATCH_SIZE
    ):
        raise Dev40BenchmarkError("MedCPT batch sizes must be exactly query=1/document=8")
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
        raise Dev40BenchmarkError("output root must be a new absent absolute path")
    repository = Path(__file__).resolve().parents[1]
    parent = root.parent.resolve(strict=True)
    candidate = (parent / root.name).resolve(strict=False)
    if candidate != BENCHMARK_OUTPUT_ROOT.resolve(strict=False):
        raise Dev40BenchmarkError("output root differs from the exact benchmark-001 path")
    try:
        candidate.relative_to(repository)
    except ValueError:
        pass
    else:
        raise Dev40BenchmarkError("benchmark results must remain outside the repository")
    if candidate.parent != parent or not root.name or root.name in {".", ".."}:
        raise Dev40BenchmarkError("output root is not one exact child of its parent")
    staging = parent / f".{root.name}.pending"
    if staging.exists() or staging.is_symlink():
        raise Dev40BenchmarkError("stale benchmark output transaction exists")
    return candidate


def _rebind_dataset_inputs(dataset: Dev40BenchmarkDataset) -> Dev40BenchmarkDataset:
    try:
        paths = Dev40InputPaths(
            **{
                name: Path(dataset.input_identities[name].path)
                for name in (
                    "corpus",
                    "packet",
                    "qrels",
                    "nonzero_qrels",
                    "adjudication",
                    "contract",
                    "bundle_manifest",
                )
            }
        )
    except KeyError as error:
        raise Dev40BenchmarkError("dataset input identity inventory is incomplete") from error
    rebound = load_dev40_dataset(paths)
    if rebound != dataset:
        raise Dev40BenchmarkError("Dev-40 inputs drifted after benchmark dataset load")
    return rebound


def save_benchmark_run(
    run: BenchmarkRun,
    dataset: Dev40BenchmarkDataset,
    medcpt_index: MedCPTSearchIndex,
    output_root: str | Path,
    *,
    executed_at_utc: datetime | None = None,
) -> Path:
    """Validate, exact-byte rebind, and atomically retain external results."""

    if tuple(run.modes) != MODES:
        raise Dev40BenchmarkError("saved run must contain exactly the three frozen modes")
    for mode in MODES:
        _validate_mode_result(run.modes[mode], dataset)
    if medcpt_index.artifacts is None:
        raise Dev40BenchmarkError("verified MedCPT artifact provenance is required")
    if dataset.adjudication_provenance != ADJUDICATION_PROVENANCE:
        raise Dev40BenchmarkError("adjudication provenance is not exact")
    if dict(run.source_state) != _source_state():
        raise Dev40BenchmarkError("benchmark source bytes drifted during execution")
    _rebind_dataset_inputs(dataset)
    if set(run.build_timings_seconds) != set(MODES) or any(
        value < 0.0 or not math.isfinite(value) for value in run.build_timings_seconds.values()
    ):
        raise Dev40BenchmarkError("benchmark build timing evidence is incomplete")
    if not math.isclose(
        run.build_timings_seconds[MODE_RRF],
        run.build_timings_seconds[MODE_BM25] + run.build_timings_seconds[MODE_MEDCPT],
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise Dev40BenchmarkError("RRF build timing must be the exact component sum")
    source_state_cases = {
        question.question_id: {
            "question": question.text,
            "reason": question.metric_exclusion_reason,
            "execution": {
                "ranking": False,
                "component_ranks_or_scores": False,
                "metrics": False,
                "query_timing": False,
            },
        }
        for question in dataset.questions
        if not question.ranking_metric_eligible
    }
    if tuple(source_state_cases) != SOURCE_STATE_QUESTION_IDS or any(
        not value["reason"] for value in source_state_cases.values()
    ):
        raise Dev40BenchmarkError("source-state manifest metadata is incomplete")
    model_runtime = _validated_medcpt_runtime_provenance(medcpt_index)
    candidate = validate_benchmark_output_root(output_root)
    staging = candidate.parent / f".{candidate.name}.pending"
    observed = executed_at_utc or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise Dev40BenchmarkError("benchmark timestamp must be timezone-aware")
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
            "development_status": (
                "Descriptive Development-40 evidence only; no statistical superiority claim"
            ),
            "executed_at_utc": observed.astimezone(UTC).isoformat(),
            "input_identities": {
                name: asdict(identity)
                for name, identity in sorted(dataset.input_identities.items())
            },
            "freeze_evidence": {
                "identities": {
                    name: asdict(identity)
                    for name, identity in sorted(dataset.freeze_identities.items())
                },
                "validation": dataset.freeze_validation,
                "limitation": (
                    "The immutable freeze source-state inventory is retained as historical "
                    "evidence; current benchmark source bytes are bound separately."
                ),
            },
            "adjudication": {
                "provenance": dataset.adjudication_provenance,
                "question_count": QUESTION_COUNT,
                "ranking_execution_question_count": len(RANKING_METRIC_QUESTION_IDS),
                "document_count": CORPUS_SIZE,
                "judgment_pairs": JUDGMENT_COUNT,
                "grades": [0, 1, 2],
                "ranking_metric_questions": list(RANKING_METRIC_QUESTION_IDS),
                "source_state_questions": list(SOURCE_STATE_QUESTION_IDS),
                "direct_metric_questions": list(DIRECT_METRIC_QUESTION_IDS),
                "direct_metric_excluded_questions": list(DIRECT_EXCLUDED_QUESTION_IDS),
            },
            "source_state_behavior_cases": source_state_cases,
            "configuration": {
                "modes": list(MODES),
                "parameter_tuning": "none",
                "reranker": "none",
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
                "primary": "nDCG@10, gain 2^relevance - 1, macro over 20",
                "broad": ("Recall@5, Recall@10, MRR@10; relevant iff grade >= 1; macro over 20"),
                "direct": ("DirectHit@10 and DirectMRR@10; relevant iff grade == 2; macro over 17"),
                "source_state_cases": (
                    "Q26/Q28/Q29 retained only as manifest metadata with no ranking, "
                    "component score/rank, metric, or query-timing execution"
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
                    "query_timing_ms": {
                        "mean": sum(record.latency_ms for record in run.modes[mode].records)
                        / len(RANKING_METRIC_QUESTION_IDS),
                        "p50": percentile(
                            [record.latency_ms for record in run.modes[mode].records],
                            0.50,
                        ),
                        "p95": percentile(
                            [record.latency_ms for record in run.modes[mode].records],
                            0.95,
                        ),
                        "total": sum(record.latency_ms for record in run.modes[mode].records),
                    },
                }
                for mode in MODES
            },
            "timings": {
                "build_seconds": dict(run.build_timings_seconds),
                "query_latency": (
                    "measured serial wall-clock milliseconds in each per-question record"
                ),
                "limitation": "machine-local evidence; not portable production performance",
            },
            "runtime_identity": _runtime_identity(),
            "model_identity": {
                "artifact_provenance": medcpt_index.artifacts.provenance(),
                "runtime_provenance": model_runtime,
            },
            "current_benchmark_source_state": dict(run.source_state),
            "execution_policy": {
                "network_operations": 0,
                "holdout_access": False,
                "model_downloads": 0,
                "network_declaration": (
                    "offline-only frozen corpus and local MedCPT cache; no connector, client, "
                    "medical-source, Hugging Face, or dependency-advisory request"
                ),
                "query_execution": "serial_single_process",
                "ranking_questions_per_mode": len(RANKING_METRIC_QUESTION_IDS),
                "complete_candidate_ranks_per_question_mode": CORPUS_SIZE,
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
    dataset: Dev40BenchmarkDataset,
    *,
    manifest_path: str | Path,
    cache_root: str | Path,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[MedCPTIndex, float]:
    """Build the frozen local-only MedCPT index and measure its build."""

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
        raise Dev40BenchmarkError("MedCPT build clock moved backwards or became non-finite")
    return index, seconds


__all__ = [
    "ADJUDICATION_PROVENANCE",
    "BENCHMARK_OUTPUT_ROOT",
    "BENCHMARK_RUN_ID",
    "CORPUS_SIZE",
    "DIRECT_METRIC_QUESTION_IDS",
    "MODES",
    "MODE_BM25",
    "MODE_MEDCPT",
    "MODE_RRF",
    "QUESTION_IDS",
    "RANKING_METRIC_QUESTION_IDS",
    "SOURCE_STATE_QUESTION_IDS",
    "ArtifactIdentity",
    "BenchmarkRun",
    "Dev40BenchmarkDataset",
    "Dev40BenchmarkError",
    "Dev40BenchmarkRunner",
    "Dev40Document",
    "Dev40InputPaths",
    "Dev40Question",
    "ModeResult",
    "QueryResult",
    "RankingEntry",
    "build_local_medcpt_index",
    "load_dev40_dataset",
    "save_benchmark_run",
    "validate_benchmark_output_root",
]
