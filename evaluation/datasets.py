"""Dataset loading for retrieval evaluation.

Two shapes are supported.

`load_beir_directory` reads the BEIR layout, which is the de-facto standard for
published IR benchmarks:

    <root>/corpus.jsonl        {"_id", "title", "text"}
    <root>/queries.jsonl       {"_id", "text"}
    <root>/qrels/test.tsv      query-id \t corpus-id \t score   (header row)

Any BEIR dataset (NFCorpus, TREC-COVID, SciFact, BioASQ, ...) therefore drops
in unchanged, and so does a project-authored dataset written in that layout.

`load_jsonl_dataset` reads a single self-contained file for small fixtures.

Loading is strict: unreadable rows, duplicate ids, qrels pointing at unknown
documents or queries, and non-integer grades all raise rather than being
silently dropped, because a silently shrunk qrel set inflates every metric.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_GRADE = 10


@dataclass(frozen=True)
class FileIdentity:
    """Exact local identity of a distribution or consumed dataset file."""

    path: str
    bytes: int
    sha256: str


def _file_identity(path: Path, *, recorded_path: str | None = None) -> FileIdentity:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return FileIdentity(
        path=recorded_path or str(path.resolve()),
        bytes=size,
        sha256=digest.hexdigest(),
    )


@dataclass(frozen=True)
class EvaluationDataset:
    """A corpus, its queries, and adjudicated relevance judgments."""

    dataset_id: str
    corpus: dict[str, str]
    corpus_titles: dict[str, str]
    queries: dict[str, str]
    qrels: dict[str, dict[str, int]]
    source_path: str = ""
    dataset_source: str = ""
    distribution: FileIdentity | None = None
    consumed_files: tuple[FileIdentity, ...] = ()
    notes: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def judged_queries(self) -> list[str]:
        """Query ids that have at least one positive judgment, sorted."""

        return sorted(
            query_id
            for query_id, judgments in self.qrels.items()
            if any(grade > 0 for grade in judgments.values())
        )

    def document_text(self, doc_id: str) -> str:
        """Title and body joined, which is the standard BEIR indexing unit."""

        title = self.corpus_titles.get(doc_id, "").strip()
        body = self.corpus[doc_id]
        return f"{title}\n{body}".strip() if title else body

    def summary(self) -> dict[str, int]:
        """Counts used in the dataset report required by the evaluation plan."""

        positives = sum(
            1 for judgments in self.qrels.values() for grade in judgments.values() if grade > 0
        )
        return {
            "documents": len(self.corpus),
            "queries": len(self.queries),
            "judged_queries": len(self.judged_queries),
            "judgments": sum(len(judgments) for judgments in self.qrels.values()),
            "positive_judgments": positives,
        }


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json_object_strict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} root is not a JSON object")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name} line {number} is not valid JSON") from error
            if not isinstance(parsed, dict):
                raise ValueError(f"{path.name} line {number} is not a JSON object")
            rows.append(parsed)
    return rows


def load_beir_directory(
    root: str | Path,
    *,
    split: str = "test",
    dataset_id: str | None = None,
    dataset_source: str = "",
    distribution_archive: str | Path | None = None,
    max_documents: int | None = None,
) -> EvaluationDataset:
    """Load a BEIR-layout dataset directory.

    `max_documents` truncates the corpus for a fast smoke run. Truncation
    records a warning and is never silent, because a truncated corpus changes
    every recall figure.
    """

    root = Path(root)
    corpus_path = root / "corpus.jsonl"
    queries_path = root / "queries.jsonl"
    qrels_path = root / "qrels" / f"{split}.tsv"
    for path in (corpus_path, queries_path, qrels_path):
        if not path.exists():
            raise FileNotFoundError(f"expected {path}")
    distribution = None
    if distribution_archive is not None:
        archive_path = Path(distribution_archive)
        if not archive_path.is_file():
            raise FileNotFoundError(f"expected distribution archive {archive_path}")
        distribution = _file_identity(archive_path)
    consumed_files = tuple(
        _file_identity(path, recorded_path=path.relative_to(root).as_posix())
        for path in (corpus_path, queries_path, qrels_path)
    )

    warnings: list[str] = []
    corpus: dict[str, str] = {}
    titles: dict[str, str] = {}
    for row in _read_jsonl(corpus_path):
        doc_id = str(row.get("_id", "")).strip()
        if not doc_id:
            raise ValueError("corpus row is missing _id")
        if doc_id in corpus:
            raise ValueError(f"duplicate corpus id {doc_id!r}")
        corpus[doc_id] = str(row.get("text", ""))
        titles[doc_id] = str(row.get("title", ""))

    queries: dict[str, str] = {}
    for row in _read_jsonl(queries_path):
        query_id = str(row.get("_id", "")).strip()
        if not query_id:
            raise ValueError("query row is missing _id")
        if query_id in queries:
            raise ValueError(f"duplicate query id {query_id!r}")
        queries[query_id] = str(row.get("text", ""))

    qrels: dict[str, dict[str, int]] = {}
    seen_judgments: set[tuple[str, str]] = set()
    with qrels_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            raw_line = line.rstrip("\r\n")
            if not raw_line:
                raise ValueError(f"{qrels_path.name} line {number} is blank")
            parts = raw_line.split("\t")
            if number == 1:
                if parts != ["query-id", "corpus-id", "score"]:
                    raise ValueError(f"{qrels_path.name} line 1 is not the expected header")
                continue
            if len(parts) != 3:
                message = "must contain exactly three tab-separated fields"
                raise ValueError(f"{qrels_path.name} line {number} {message}")
            query_id, doc_id, raw_grade = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if not query_id or not doc_id or not raw_grade:
                raise ValueError(f"{qrels_path.name} line {number} contains an empty field")
            try:
                grade = int(raw_grade)
            except ValueError as error:
                raise ValueError(
                    f"{qrels_path.name} line {number} has a non-integer grade"
                ) from error
            if not 0 <= grade <= MAX_GRADE:
                raise ValueError(f"{qrels_path.name} line {number} grade {grade} out of range")
            pair = (query_id, doc_id)
            if pair in seen_judgments:
                raise ValueError(
                    f"{qrels_path.name} line {number} duplicates judgment {query_id!r}->{doc_id!r}"
                )
            seen_judgments.add(pair)
            qrels.setdefault(query_id, {})[doc_id] = grade
    if not seen_judgments:
        raise ValueError(f"{qrels_path.name} contains no judgments")

    pre_truncation = EvaluationDataset(
        dataset_id=dataset_id or root.name,
        corpus=corpus,
        corpus_titles=titles,
        queries=queries,
        qrels=qrels,
    )
    _validate(pre_truncation)

    if max_documents is not None and len(corpus) > max_documents:
        keep = set(sorted(corpus)[:max_documents])
        for judgments in qrels.values():
            keep.update(judgments)
        removed = len(corpus) - len(keep)
        corpus = {doc_id: text for doc_id, text in corpus.items() if doc_id in keep}
        titles = {doc_id: text for doc_id, text in titles.items() if doc_id in keep}
        warnings.append(
            f"corpus truncated to {len(corpus)} documents ({removed} removed); "
            "recall figures are not comparable to the full corpus"
        )

    dataset = EvaluationDataset(
        dataset_id=dataset_id or root.name,
        corpus=corpus,
        corpus_titles=titles,
        queries=queries,
        qrels=qrels,
        source_path=str(root),
        dataset_source=dataset_source,
        distribution=distribution,
        consumed_files=consumed_files,
        warnings=warnings,
    )
    _validate(dataset)
    return dataset


def load_jsonl_dataset(path: str | Path, *, dataset_id: str | None = None) -> EvaluationDataset:
    """Load a single-file dataset: `{"corpus": [...], "queries": [...], "qrels": {...}}`."""

    path = Path(path)
    payload = _load_json_object_strict(path)
    for required_key in ("corpus", "queries", "qrels"):
        if required_key not in payload:
            raise ValueError(f"dataset is missing required {required_key!r}")
    if not isinstance(payload["corpus"], list):
        raise ValueError("corpus is not a JSON array")
    if not isinstance(payload["queries"], list):
        raise ValueError("queries is not a JSON array")
    corpus: dict[str, str] = {}
    titles: dict[str, str] = {}
    for row in payload.get("corpus", []):
        if not isinstance(row, dict):
            raise ValueError("corpus row is not a JSON object")
        doc_id = str(row.get("_id", "")).strip()
        if not doc_id:
            raise ValueError("corpus row is missing _id")
        if doc_id in corpus:
            raise ValueError(f"duplicate corpus id {doc_id!r}")
        corpus[doc_id] = str(row.get("text", ""))
        titles[doc_id] = str(row.get("title", ""))
    queries: dict[str, str] = {}
    for row in payload.get("queries", []):
        if not isinstance(row, dict):
            raise ValueError("query row is not a JSON object")
        query_id = str(row.get("_id", "")).strip()
        if not query_id:
            raise ValueError("query row is missing _id")
        if query_id in queries:
            raise ValueError(f"duplicate query id {query_id!r}")
        queries[query_id] = str(row.get("text", ""))
    raw_qrels = payload.get("qrels", {})
    if not isinstance(raw_qrels, dict):
        raise ValueError("qrels is not a JSON object")
    qrels: dict[str, dict[str, int]] = {}
    for raw_query_id, raw_judgments in raw_qrels.items():
        query_id = str(raw_query_id).strip()
        if not query_id or not isinstance(raw_judgments, dict):
            raise ValueError("qrels contains an invalid query entry")
        qrels[query_id] = {}
        for raw_doc_id, grade in raw_judgments.items():
            doc_id = str(raw_doc_id).strip()
            if not doc_id:
                raise ValueError(f"qrels for {query_id!r} contains an empty document id")
            if isinstance(grade, bool) or not isinstance(grade, int):
                raise ValueError(f"qrels judgment {query_id!r}->{doc_id!r} has a non-integer grade")
            if not 0 <= grade <= MAX_GRADE:
                raise ValueError(
                    f"qrels judgment {query_id!r}->{doc_id!r} grade {grade} out of range"
                )
            qrels[query_id][doc_id] = grade
    identity = _file_identity(path)
    dataset = EvaluationDataset(
        dataset_id=dataset_id or payload.get("dataset_id", path.stem),
        corpus=corpus,
        corpus_titles=titles,
        queries=queries,
        qrels=qrels,
        source_path=str(path),
        dataset_source=str(payload.get("dataset_source", "local_jsonl_fixture")),
        distribution=identity,
        consumed_files=(identity,),
        notes=str(payload.get("notes", "")),
    )
    _validate(dataset)
    return dataset


def _validate(dataset: EvaluationDataset) -> None:
    """Reject judgments that reference documents or queries that do not exist."""

    if not dataset.corpus:
        raise ValueError("dataset corpus is empty")
    if not dataset.queries:
        raise ValueError("dataset has no queries")
    if not dataset.qrels:
        raise ValueError("dataset has no qrels")
    empty_judgment_maps = sorted(
        query_id for query_id, judgments in dataset.qrels.items() if not judgments
    )
    if empty_judgment_maps:
        raise ValueError(f"qrels contain empty judgment maps: {empty_judgment_maps[:5]}")
    unknown_queries = sorted(set(dataset.qrels) - set(dataset.queries))
    if unknown_queries:
        raise ValueError(f"qrels reference unknown query ids: {unknown_queries[:5]}")
    missing: list[str] = []
    for query_id, judgments in dataset.qrels.items():
        for doc_id in judgments:
            if doc_id not in dataset.corpus:
                missing.append(f"{query_id}->{doc_id}")
    if missing:
        raise ValueError(
            f"{len(missing)} judgments reference documents absent from the corpus; "
            f"first: {missing[:5]}"
        )
    if not dataset.judged_queries:
        raise ValueError("dataset has zero judged queries with a positive judgment")


def relevance_grade_histogram(qrels: Mapping[str, Mapping[str, int]]) -> dict[int, int]:
    """Count judgments per grade, for the dataset report."""

    histogram: dict[int, int] = {}
    for judgments in qrels.values():
        for grade in judgments.values():
            histogram[grade] = histogram.get(grade, 0) + 1
    return dict(sorted(histogram.items()))
