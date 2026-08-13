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

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

MAX_GRADE = 10


@dataclass(frozen=True)
class EvaluationDataset:
    """A corpus, its queries, and adjudicated relevance judgments."""

    dataset_id: str
    corpus: dict[str, str]
    corpus_titles: dict[str, str]
    queries: dict[str, str]
    qrels: dict[str, dict[str, int]]
    source_path: str = ""
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
            "positive_judgments": positives,
        }


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
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
    with qrels_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            query_id, doc_id, raw_grade = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if number == 1 and not raw_grade.lstrip("-").isdigit():
                continue  # header row
            try:
                grade = int(raw_grade)
            except ValueError as error:
                raise ValueError(
                    f"{qrels_path.name} line {number} has a non-integer grade"
                ) from error
            if not 0 <= grade <= MAX_GRADE:
                raise ValueError(f"{qrels_path.name} line {number} grade {grade} out of range")
            qrels.setdefault(query_id, {})[doc_id] = grade

    if max_documents is not None and len(corpus) > max_documents:
        keep = set(sorted(corpus)[:max_documents])
        for judgments in qrels.values():
            keep.update(doc_id for doc_id, grade in judgments.items() if grade > 0)
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
        warnings=warnings,
    )
    _validate(dataset)
    return dataset


def load_jsonl_dataset(path: str | Path, *, dataset_id: str | None = None) -> EvaluationDataset:
    """Load a single-file dataset: `{"corpus": [...], "queries": [...], "qrels": {...}}`."""

    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    corpus: dict[str, str] = {}
    titles: dict[str, str] = {}
    for row in payload.get("corpus", []):
        corpus[str(row["_id"])] = str(row.get("text", ""))
        titles[str(row["_id"])] = str(row.get("title", ""))
    queries = {str(row["_id"]): str(row["text"]) for row in payload.get("queries", [])}
    qrels = {
        str(query_id): {str(doc_id): int(grade) for doc_id, grade in judgments.items()}
        for query_id, judgments in payload.get("qrels", {}).items()
    }
    dataset = EvaluationDataset(
        dataset_id=dataset_id or payload.get("dataset_id", path.stem),
        corpus=corpus,
        corpus_titles=titles,
        queries=queries,
        qrels=qrels,
        source_path=str(path),
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
    unknown_queries = sorted(set(dataset.qrels) - set(dataset.queries))
    if unknown_queries:
        raise ValueError(f"qrels reference unknown query ids: {unknown_queries[:5]}")
    missing: list[str] = []
    for query_id, judgments in dataset.qrels.items():
        for doc_id, grade in judgments.items():
            if grade > 0 and doc_id not in dataset.corpus:
                missing.append(f"{query_id}->{doc_id}")
    if missing:
        raise ValueError(
            f"{len(missing)} positive judgments reference documents absent from the corpus; "
            f"first: {missing[:5]}"
        )


def relevance_grade_histogram(qrels: Mapping[str, Mapping[str, int]]) -> dict[int, int]:
    """Count judgments per grade, for the dataset report."""

    histogram: dict[int, int] = {}
    for judgments in qrels.values():
        for grade in judgments.values():
            histogram[grade] = histogram.get(grade, 0) + 1
    return dict(sorted(histogram.items()))
