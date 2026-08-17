"""Offline-only Dev-40 corpus freeze and blinded-packet validation.

The module reuses exact retained evidence and has no import-time I/O.  Its
evaluation-owned retrieval union admits one source-native PubMed book document
without weakening or coercing the production ``PublicationRecord`` contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, cast

from medevidence.connectors.pubmed.parsing import (
    PubMedArticle,
    PubMedBookDocument,
    parse_fetch_response,
)

WORK_ITEM: Final = "M2-006-MEDEVIDENCE-DEV40"
DATASET: Final = "MEDEVIDENCE_DEV40"
SCHEMA_VERSION: Final = "medevidence.dev40.corpus.v1"
EVIDENCE_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-006-MEDEVIDENCE-DEV40")
OUTPUT_ROOT: Final = EVIDENCE_ROOT / "corpus-freeze-001"
ACQUISITION_ROOT: Final = EVIDENCE_ROOT / "acquisition-001"
BOOK_SUCCESSOR_ROOT: Final = EVIDENCE_ROOT / "acquisition-001-successor-001"
FAERS_SUCCESSOR_ROOT: Final = EVIDENCE_ROOT / "acquisition-001-successor-002"
QUESTIONS_PATH: Final = (
    EVIDENCE_ROOT / "question-drafting" / "additional-development-30-frozen-candidate.json"
)
GAP_PATH: Final = EVIDENCE_ROOT / "evidence-gap-inventory" / "evidence-gap-inventory-001.json"
GOLD_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-005-MEDEVIDENCE-GOLD10-V2")
GOLD_MANIFEST_PATH: Final = GOLD_ROOT / "corpus-manifest.json"
GOLD_PACKET_PATH: Final = GOLD_ROOT / "blinded-adjudication-packet.json"

QUESTIONS_SHA256: Final = "379f721506eb58f9163e735ca96088847aa04d63e56740c4a8d7c7d47caf7a2f"
GAP_SHA256: Final = "850c4e3b7c55b2427df24dfabf33d5b4e50fd1624431cdecbb2281de2aea9389"
GOLD_MANIFEST_SHA256: Final = "716b35ae8cb0e4a843a9e67e44f75e3b2577bec5859940087ad1c3976e38e459"
GOLD_PACKET_SHA256: Final = "14bbcf0b51e56ad2eec377a129a491006626893e13220d151379e0f3ff1e2974"
BOOK_SUCCESSOR_SHA256: Final = "4a5ef660ea93f6609fea3b74e76216365a46bcde6292757ccb71018bc5dc60b5"
FAERS_SUCCESS_SHA256: Final = "ff8d646eefdfc6fe51c1104809cec9d482cbe35edf8520ba3b8cb90860da4b96"
ORIGINAL_STOP_SHA256: Final = "1b49208f1daa90fea33f6a95c24f01125b4b55040d4b7805204e703d456cc8dc"

EXPECTED_PUBMED_ARTICLES: Final = 198
EXPECTED_PUBMED_BOOKS: Final = 1
EXPECTED_DAILYMED: Final = 15
EXPECTED_TOTAL: Final = 214
BOOK_PMID: Final = "31644235"
BOOK_ACCESSION: Final = "NBK548929"
BOOK_RETRIEVAL_ID: Final = f"pubmed-book:{BOOK_PMID}"
RETRIEVAL_QUESTION_IDS: Final = (
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
FORBIDDEN_PACKET_KEY_PARTS: Final = (
    "qrel",
    "grade",
    "rank",
    "score",
    "retriever",
    "bm25",
    "medcpt",
    "rrf",
    "nominat",
)


class Dev40CorpusError(RuntimeError):
    """A fail-closed retained-evidence or corpus-contract failure."""


@dataclass(frozen=True, slots=True)
class FreezeResult:
    """Exact identities of one completed offline freeze."""

    output_root: Path
    corpus_manifest_sha256: str
    blinded_packet_sha256: str
    source_reconciliation_sha256: str
    source_state_inventory_sha256: str
    corpus_units: int
    adjudication_questions: int


@dataclass(frozen=True, slots=True)
class _PubMedBinding:
    pair_id: str
    operation_sha256: str
    binding_sha256: str
    raw_sha256: str
    raw_relative_path: str


_PUBMED_BINDINGS: Final = (
    _PubMedBinding(
        "pubmed-A-semaglutide-vomiting-treatment-limiting",
        "30481f8618493be763f899e8e2216e08369cb4667470811b3ceecf2b4b3b869a",
        "0da5626f8f0257fdc56416b41b290cb7cedab1c989cbfbed82681d843419f14f",
        "7cc3829213067e5b82798db23eca8daf687f3faf177d99125a0b119b35f101ea",
        "raw/pubmed-A-semaglutide-vomiting-treatment-limiting-efetch-01-"
        "sha256-7cc3829213067e5b82798db23eca8daf687f3faf177d99125a0b119b35f101ea.raw",
    ),
    _PubMedBinding(
        "pubmed-B-semaglutide-gi-2020-2025",
        "6019c1512d9f8e443df9ff2b112632b1533dd2c4b02c0452c215514b54d668ea",
        "6b86d80674e216adc19d2512b7fe7343f2d58a19d114da0e306d201ba70b9679",
        "20d771db474c82bbcbb03e94695a5c2f971963bf8b317f5a541cce1fa47f48d4",
        "raw/pubmed-B-semaglutide-gi-2020-2025-efetch-01-"
        "sha256-20d771db474c82bbcbb03e94695a5c2f971963bf8b317f5a541cce1fa47f48d4.raw",
    ),
    _PubMedBinding(
        "pubmed-C-tirzepatide-gi-2020-2025",
        "03dc8f4a3ab40b75448afe5add68b814dab0469cf40ee8c11e3f53783579a4d8",
        "4d5f926bfbc46481ad0ae09938e5f40ab8fb66edafa053b65ff01bff2bd39d48",
        "b02aec0b657566f31f5bc86f481e74847b8f7615a4192a12946124f49024b0f8",
        "raw/pubmed-C-tirzepatide-gi-2020-2025-efetch-01-"
        "sha256-b02aec0b657566f31f5bc86f481e74847b8f7615a4192a12946124f49024b0f8.raw",
    ),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise Dev40CorpusError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path, expected_sha256: str) -> Mapping[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Dev40CorpusError(f"required evidence is unavailable: {path}") from error
    if _sha256(data) != expected_sha256:
        raise Dev40CorpusError(f"evidence identity mismatch: {path.name}")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Dev40CorpusError(f"malformed JSON evidence: {path.name}") from error
    if not isinstance(value, dict):
        raise Dev40CorpusError(f"JSON evidence must be an object: {path.name}")
    return value


def _verified_bytes(path: Path, expected_sha256: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Dev40CorpusError(f"required retained artifact is unavailable: {path}") from error
    if _sha256(data) != expected_sha256:
        raise Dev40CorpusError(f"retained artifact identity mismatch: {path.name}")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    if pending.exists():
        raise Dev40CorpusError(f"stale pending evidence exists: {pending.name}")
    try:
        pending.write_bytes(data)
        if pending.read_bytes() != data:
            raise Dev40CorpusError(f"pending evidence verification failed: {path.name}")
        pending.replace(path)
    except Exception:
        with suppress(OSError):
            pending.unlink()
        raise


def _write_json(path: Path, value: Any) -> str:
    data = _canonical_json_bytes(value)
    digest = _sha256(data)
    _atomic_write(path, data)
    _atomic_write(
        path.with_suffix(path.suffix + ".sha256"),
        f"{digest}  {path.name}\n".encode("ascii"),
    )
    return digest


def _sidecar_valid(path: Path) -> str:
    digest = _sha256(path.read_bytes())
    sidecar = path.with_suffix(path.suffix + ".sha256")
    try:
        line = sidecar.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise Dev40CorpusError(f"missing evidence sidecar: {path.name}") from error
    if line != f"{digest}  {path.name}\n":
        raise Dev40CorpusError(f"evidence sidecar mismatch: {path.name}")
    return digest


def _artifact(path: Path, expected_sha256: str) -> dict[str, Any]:
    data = _verified_bytes(path, expected_sha256)
    return {"external_path": str(path), "bytes": len(data), "sha256": expected_sha256}


def _abstract_sections(article: PubMedArticle | PubMedBookDocument) -> list[dict[str, Any]]:
    return [
        {"label": section.label, "nlm_category": section.nlm_category, "text": section.text}
        for section in article.abstract_sections
    ]


def _article_item(
    article: PubMedArticle,
    *,
    memberships: Sequence[str],
    source_artifact_sha256: str,
) -> dict[str, Any]:
    sections = _abstract_sections(article)
    text = "\n".join(section["text"] for section in sections)
    if not text.strip():
        # PubMed can return an admitted citation without an abstract.  The
        # provider title is still source-native retrieval text; do not invent
        # an abstract or omit the provider record from corpus reconciliation.
        text = article.title
    content = {"pmid": article.pmid, "title": article.title, "abstract_sections": sections}
    return {
        "abstract_sections": sections,
        "query_memberships": list(memberships),
        "retrieval_unit_id": f"pubmed:{article.pmid}",
        "reused_from_work_item": WORK_ITEM,
        "source": "pubmed",
        "source_artifact_sha256": source_artifact_sha256,
        "source_locator": f"https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/",
        "source_version_identity": (
            f"pmid:{article.pmid}:content-sha256:{_sha256(_canonical_json_bytes(content))}"
        ),
        "stable_source_id": article.pmid,
        "text": text,
        "text_sha256": _sha256(text.encode("utf-8")),
        "title": article.title,
    }


def _book_item(
    book: PubMedBookDocument,
    *,
    binding: _PubMedBinding,
) -> dict[str, Any]:
    sections = _abstract_sections(book)
    text = "\n".join(section["text"] for section in sections)
    if (
        book.pmid != BOOK_PMID
        or book.book_accession != BOOK_ACCESSION
        or not book.title.strip()
        or not book.book_title.strip()
        or not text.strip()
    ):
        raise Dev40CorpusError("the exact PubMed book document identity or content drifted")
    content = {
        "pmid": book.pmid,
        "book_accession": book.book_accession,
        "title": book.title,
        "book_title": book.book_title,
        "abstract_sections": sections,
    }
    content_identity = _sha256(_canonical_json_bytes(content))
    item: dict[str, Any] = {
        "retrieval_unit_kind": "pubmed_book_document",
        "provider_record_kind": "PubmedBookArticle",
        "mapping_disposition": "source_native_retained_not_coerced",
        "retrieval_unit_id": BOOK_RETRIEVAL_ID,
        "source": "pubmed",
        "stable_source_id": book.pmid,
        "pmid": book.pmid,
        "book_accession": book.book_accession,
        "title": book.title,
        "book_title": book.book_title,
        "text": text,
        "text_sha256": _sha256(text.encode("utf-8")),
        "abstract_sections": sections,
        "authors": [asdict(author) for author in book.authors],
        "languages": list(book.languages),
        "publication_types": list(book.publication_types),
        "publication_date": asdict(book.publication_date) if book.publication_date else None,
        "publisher_name": book.publisher_name,
        "publisher_location": book.publisher_location,
        "medium": book.medium,
        "source_locator": f"https://pubmed.ncbi.nlm.nih.gov/{book.pmid}/",
        "source_artifact_sha256": binding.raw_sha256,
        "source_version_identity": f"pmid:{book.pmid}:book-content-sha256:{content_identity}",
        "content_identity": f"sha256:{content_identity}",
        "source_identity": f"pubmed-book-document:{book.pmid}:{book.book_accession}",
        "query_memberships": [binding.pair_id],
        "lineage": {
            "acquisition_operation_sha256": binding.operation_sha256,
            "dynamic_binding_sha256": binding.binding_sha256,
            "raw_artifact_sha256": binding.raw_sha256,
            "raw_artifact_relative_path": binding.raw_relative_path,
            "offline_successor_sha256": BOOK_SUCCESSOR_SHA256,
        },
    }
    if "journal" in item:
        raise Dev40CorpusError("book retrieval unit must never contain journal semantics")
    return item


def _parse_pubmed_extensions() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    article_items: dict[str, dict[str, Any]] = {}
    article_content: dict[str, tuple[str, str, str]] = {}
    books: list[dict[str, Any]] = []
    pair_counts: dict[str, Any] = {}
    for binding in _PUBMED_BINDINGS:
        operation_path = ACQUISITION_ROOT / "operations" / f"{binding.pair_id}-efetch.json"
        operation = _load_json(operation_path, binding.operation_sha256)
        binding_path = ACQUISITION_ROOT / "bindings" / f"{binding.pair_id}-efetch-binding.json"
        dynamic = _load_json(binding_path, binding.binding_sha256)
        requested = dynamic.get("ordered_unique_pmids")
        if (
            not isinstance(requested, list)
            or not 1 <= len(requested) <= 100
            or any(not isinstance(pmid, str) or not pmid.isdecimal() for pmid in requested)
            or operation.get("binding_sha256") != binding.binding_sha256
            or operation.get("raw_responses", [{}])[0].get("sha256") != binding.raw_sha256
            or operation.get("raw_responses", [{}])[0].get("relative_path")
            != binding.raw_relative_path
        ):
            raise Dev40CorpusError(f"PubMed {binding.pair_id} lineage is inconsistent")
        raw = _verified_bytes(ACQUISITION_ROOT / binding.raw_relative_path, binding.raw_sha256)
        parsed = parse_fetch_response(raw, cast(list[str], requested), max_items=len(requested))
        if (
            parsed.malformed_records
            or parsed.duplicate_pmids
            or parsed.unexpected_pmids
            or parsed.missing_expected_pmids
            or parsed.article_occurrence_count + parsed.book_document_occurrence_count
            != len(requested)
        ):
            raise Dev40CorpusError(f"PubMed {binding.pair_id} does not reconcile completely")
        for article in parsed.records:
            item = _article_item(
                article,
                memberships=[binding.pair_id],
                source_artifact_sha256=binding.raw_sha256,
            )
            identity = cast(str, item["retrieval_unit_id"])
            signature = (
                cast(str, item["title"]),
                cast(str, item["text_sha256"]),
                cast(str, item["stable_source_id"]),
            )
            if identity in article_content and article_content[identity] != signature:
                raise Dev40CorpusError(f"cross-query PubMed content collision: {identity}")
            if identity in article_items:
                existing = article_items[identity]
                memberships = cast(list[str], existing["query_memberships"])
                if binding.pair_id not in memberships:
                    memberships.append(binding.pair_id)
            else:
                article_items[identity] = item
                article_content[identity] = signature
        for book in parsed.book_documents:
            books.append(_book_item(book, binding=binding))
        pair_counts[binding.pair_id] = {
            "requested": len(requested),
            "pubmed_articles": parsed.article_occurrence_count,
            "pubmed_book_documents": parsed.book_document_occurrence_count,
            "operation_sha256": binding.operation_sha256,
            "binding_sha256": binding.binding_sha256,
            "raw_sha256": binding.raw_sha256,
        }
    if len(books) != 1 or books[0]["retrieval_unit_id"] != BOOK_RETRIEVAL_ID:
        raise Dev40CorpusError("the exact PubMed book document must occur once across extensions")
    return [*article_items.values(), *books], pair_counts


def _validate_book_unit(item: Mapping[str, Any]) -> None:
    required = {
        "retrieval_unit_kind",
        "provider_record_kind",
        "mapping_disposition",
        "retrieval_unit_id",
        "source",
        "stable_source_id",
        "pmid",
        "book_accession",
        "title",
        "book_title",
        "text",
        "text_sha256",
        "source_locator",
        "source_version_identity",
        "content_identity",
        "source_identity",
        "lineage",
    }
    if not required.issubset(item) or "journal" in item:
        raise Dev40CorpusError("PubMed book retrieval-unit schema is incomplete or coerced")
    if (
        item["retrieval_unit_kind"] != "pubmed_book_document"
        or item["provider_record_kind"] != "PubmedBookArticle"
        or item["mapping_disposition"] != "source_native_retained_not_coerced"
        or item["retrieval_unit_id"] != BOOK_RETRIEVAL_ID
        or item["pmid"] != BOOK_PMID
        or item["book_accession"] != BOOK_ACCESSION
        or item["title"] == item["book_title"]
    ):
        raise Dev40CorpusError("PubMed book retrieval-unit identity drifted")


def validate_retrieval_units(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Validate the evaluation-only union and return exact source counts."""

    identities: set[str] = set()
    counts = {"pubmed_article": 0, "pubmed_book_document": 0, "dailymed_section": 0}
    for item in items:
        identity = item.get("retrieval_unit_id")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise Dev40CorpusError("retrieval-unit identity is missing or duplicated")
        identities.add(identity)
        text = item.get("text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or item.get("text_sha256")
            not in {
                _sha256(text.encode("utf-8")),
                f"sha256:{_sha256(text.encode('utf-8'))}",
            }
        ):
            raise Dev40CorpusError(f"retrieval text identity mismatch: {identity}")
        if item.get("retrieval_unit_kind") == "pubmed_book_document":
            _validate_book_unit(item)
            counts["pubmed_book_document"] += 1
        elif item.get("source") == "pubmed" and identity.startswith("pubmed:"):
            counts["pubmed_article"] += 1
        elif item.get("source") == "dailymed" and identity.startswith("dailymed:"):
            counts["dailymed_section"] += 1
        else:
            raise Dev40CorpusError(f"unknown retrieval-unit variant: {identity}")
    expected = {
        "pubmed_article": EXPECTED_PUBMED_ARTICLES,
        "pubmed_book_document": EXPECTED_PUBMED_BOOKS,
        "dailymed_section": EXPECTED_DAILYMED,
    }
    if counts != expected or len(items) != EXPECTED_TOTAL:
        raise Dev40CorpusError(f"Dev-40 corpus count drift: {counts}")
    return counts


def _packet_candidate(item: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    candidate = {
        "candidate_ordinal": ordinal,
        "retrieval_unit_id": item["retrieval_unit_id"],
        "source": item["source"],
        "stable_source_id": item["stable_source_id"],
        "source_version_identity": item["source_version_identity"],
        "source_locator": item["source_locator"],
        "title": item["title"],
        "text": item["text"],
        "text_sha256": item["text_sha256"],
    }
    if item.get("retrieval_unit_kind") == "pubmed_book_document":
        candidate.update(
            {
                "retrieval_unit_kind": "pubmed_book_document",
                "provider_record_kind": item["provider_record_kind"],
                "pmid": item["pmid"],
                "book_accession": item["book_accession"],
                "book_title": item["book_title"],
                "content_identity": item["content_identity"],
                "source_identity": item["source_identity"],
            }
        )
    return candidate


def _validate_packet_blindness(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(part in normalized for part in FORBIDDEN_PACKET_KEY_PARTS):
                raise Dev40CorpusError(f"blinded packet contains forbidden field: {key}")
            _validate_packet_blindness(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_packet_blindness(nested)


def _question_records() -> tuple[list[dict[str, Any]], dict[str, str]]:
    gold_packet = _load_json(GOLD_PACKET_PATH, GOLD_PACKET_SHA256)
    questions_doc = _load_json(QUESTIONS_PATH, QUESTIONS_SHA256)
    gap_doc = _load_json(GAP_PATH, GAP_SHA256)
    gold_questions = gold_packet.get("questions")
    additional = questions_doc.get("questions")
    mappings = gap_doc.get("mapping_rows")
    if (
        not isinstance(gold_questions, list)
        or len(gold_questions) != 10
        or not isinstance(additional, list)
        or len(additional) != 30
        or not isinstance(mappings, list)
        or len(mappings) != 30
    ):
        raise Dev40CorpusError("frozen Dev-40 question evidence is incomplete")
    layer_by_id: dict[str, str] = {}
    for row in mappings:
        if not isinstance(row, dict):
            raise Dev40CorpusError("evaluation-layer row is malformed")
        question_id, layer = row.get("question_id"), row.get("primary_layer")
        if not isinstance(question_id, str) or not isinstance(layer, str):
            raise Dev40CorpusError("evaluation-layer identity is malformed")
        layer_by_id[question_id] = layer
    all_questions: list[dict[str, Any]] = []
    for row in gold_questions:
        if not isinstance(row, dict):
            raise Dev40CorpusError("Gold-10 question row is malformed")
        all_questions.append({"question_id": row["question_id"], "question": row["question"]})
    for row in additional:
        if not isinstance(row, dict):
            raise Dev40CorpusError("additional-development question row is malformed")
        all_questions.append(
            {
                "question_id": row["question_id"],
                "question": row["question"],
                "intended_research_scope": row["intended_research_scope"],
                "allowed_source_classes": row["allowed_source_classes"],
                "prohibited_source_classes": row["prohibited_source_classes"],
                "provenance": "AI-drafted, Owner-confirmed, corpus-conditioned development data",
            }
        )
    expected = [f"Q{index}" for index in range(1, 41)]
    if [row["question_id"] for row in all_questions] != expected:
        raise Dev40CorpusError("Dev-40 question IDs are not exact Q1 through Q40")
    actual_retrieval = [
        row["question_id"]
        for row in all_questions
        if row["question_id"] in {f"Q{index}" for index in range(1, 11)}
        or layer_by_id.get(cast(str, row["question_id"])) == "retrieval"
    ]
    if tuple(actual_retrieval) != RETRIEVAL_QUESTION_IDS:
        raise Dev40CorpusError("retrieval adjudication question selection drifted")
    return all_questions, layer_by_id


def _packet(
    items: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    layers: Mapping[str, str],
    corpus_sha256: str,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    by_id = {cast(str, row["question_id"]): row for row in questions}
    for question_id in RETRIEVAL_QUESTION_IDS:
        question = by_id[question_id]
        ordered = sorted(
            items,
            key=lambda item: _sha256(
                f"{DATASET}\0{question_id}\0{item['retrieval_unit_id']}".encode()
            ),
        )
        candidates = [_packet_candidate(item, index) for index, item in enumerate(ordered, 1)]
        if (
            len(candidates) != EXPECTED_TOTAL
            or len({candidate["retrieval_unit_id"] for candidate in candidates}) != EXPECTED_TOTAL
        ):
            raise Dev40CorpusError("one blinded candidate set is incomplete or duplicated")
        selected.append(
            {
                "question_id": question_id,
                "question": question["question"],
                "evaluation_layer": "retrieval",
                "candidate_count": EXPECTED_TOTAL,
                "candidates": candidates,
            }
        )
    excluded = [
        {"question_id": row["question_id"], "evaluation_layer": layers[row["question_id"]]}
        for row in questions
        if row["question_id"] not in RETRIEVAL_QUESTION_IDS and row["question_id"] in layers
    ]
    packet = {
        "schema_version": f"{SCHEMA_VERSION}.blinded-adjudication-packet.v1",
        "work_item": WORK_ITEM,
        "dataset": DATASET,
        "corpus_manifest_sha256": corpus_sha256,
        "question_provenance": {
            "Q1-Q10": "immutable MEDEVIDENCE_GOLD10_V2 questions",
            "Q11-Q40": "AI-drafted, Owner-confirmed, corpus-conditioned development data",
        },
        "ordering": "sha256(dataset NUL question_id NUL retrieval_unit_id)",
        "adjudication_status": "OWNER_ADJUDICATION_REQUIRED",
        "retrieval_question_count": len(selected),
        "excluded_non_retrieval_questions": excluded,
        "questions": selected,
    }
    _validate_packet_blindness(packet)
    return packet


def _verify_dailymed_and_gold() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gold = _load_json(GOLD_MANIFEST_PATH, GOLD_MANIFEST_SHA256)
    items = gold.get("items")
    counts = gold.get("counts")
    if not isinstance(items, list) or not isinstance(counts, dict) or counts.get("total") != 65:
        raise Dev40CorpusError("Gold-10 V2 corpus manifest is not the exact 65-item freeze")
    typed_items = [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
    if len(typed_items) != 65:
        raise Dev40CorpusError("Gold-10 V2 corpus item shape is malformed")
    artifact_bindings = {
        "gold_corpus_manifest": _artifact(GOLD_MANIFEST_PATH, GOLD_MANIFEST_SHA256),
        "gold_blinded_packet": _artifact(GOLD_PACKET_PATH, GOLD_PACKET_SHA256),
        "ozempic_sections": _artifact(
            GOLD_ROOT / "ozempic-source-native-sections.json",
            "2af8c10df8fdf6905039cf768a0c67720f836bff89cb349a5592f1c93891f313",
        ),
        "mounjaro_sections": _artifact(
            GOLD_ROOT / "mounjaro-source-native-sections.json",
            "c91057d3cb62cece421fcbad22f65fbb258a1e72fed84a5fa5c09d684f2ba887",
        ),
        "mounjaro_raw": _artifact(
            GOLD_ROOT
            / "raw"
            / "dailymed"
            / "sha256-948cbec7cff61ad191e229292f3b4cb8ee63ffa14e3a1d6e49a1663e5291576a.raw",
            "948cbec7cff61ad191e229292f3b4cb8ee63ffa14e3a1d6e49a1663e5291576a",
        ),
        "mounjaro_derivative": _artifact(
            GOLD_ROOT
            / "derived"
            / "mounjaro"
            / "sha256-836aa8e41ce40c2c69416ba3f8a538c3af84140762c364dcbca740ab82fca7c8.xml",
            "836aa8e41ce40c2c69416ba3f8a538c3af84140762c364dcbca740ab82fca7c8",
        ),
    }
    return typed_items, artifact_bindings


def _source_file_state() -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[1]
    files: dict[str, Any] = {}
    for relative in (
        "evaluation/dev40_corpus.py",
        "evaluation/run_dev40_corpus.py",
        "tests/unit/evaluation/test_dev40_corpus.py",
        "evaluation/dev40_acquisition.py",
        "tests/unit/evaluation/test_dev40_acquisition.py",
        "src/medevidence/connectors/pubmed/parsing.py",
    ):
        data = (repo / relative).read_bytes()
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
    return files


def _run_plan_document() -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.run-plan.v1",
        "work_item": WORK_ITEM,
        "mode": "offline_retained_evidence_only",
        "medical_source_requests": 0,
        "holdout_accessed": False,
        "authoritative_qrels_created": False,
        "rankings_scores_models_used": False,
        "expected_corpus_units": EXPECTED_TOTAL,
        "expected_retrieval_questions": len(RETRIEVAL_QUESTION_IDS),
    }


def _source_state_document() -> dict[str, Any]:
    """Rehash every retained artifact represented by the source-state record."""

    _, gold_bindings = _verify_dailymed_and_gold()
    pubmed_lineage: dict[str, Any] = {}
    for binding in _PUBMED_BINDINGS:
        pubmed_lineage[f"{binding.pair_id}_operation"] = _artifact(
            ACQUISITION_ROOT / "operations" / f"{binding.pair_id}-efetch.json",
            binding.operation_sha256,
        )
        pubmed_lineage[f"{binding.pair_id}_binding"] = _artifact(
            ACQUISITION_ROOT / "bindings" / f"{binding.pair_id}-efetch-binding.json",
            binding.binding_sha256,
        )
        pubmed_lineage[f"{binding.pair_id}_raw"] = _artifact(
            ACQUISITION_ROOT / binding.raw_relative_path,
            binding.raw_sha256,
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.source-state-inventory.v1",
        "work_item": WORK_ITEM,
        "network_operations": 0,
        "holdout_accessed": False,
        "qrels_rankings_scores_accessed": False,
        "repository_source_state": _source_file_state(),
        "retained_evidence": {
            **gold_bindings,
            **pubmed_lineage,
            "frozen_questions": _artifact(QUESTIONS_PATH, QUESTIONS_SHA256),
            "evaluation_layer_mapping": _artifact(GAP_PATH, GAP_SHA256),
            "original_acquisition_stop": _artifact(
                ACQUISITION_ROOT / "stop.json", ORIGINAL_STOP_SHA256
            ),
            "pubmed_book_successor": _artifact(
                BOOK_SUCCESSOR_ROOT / "pubmed-c-offline-successor-reconciliation.json",
                BOOK_SUCCESSOR_SHA256,
            ),
            "faers_d_successor": _artifact(
                FAERS_SUCCESSOR_ROOT / "success-manifest.json", FAERS_SUCCESS_SHA256
            ),
        },
        "mounjaro_retained_raw_rematerialization": {
            "method": "exact-byte rehash plus reuse of accepted parsed section records",
            "medical_source_requests": 0,
            "raw_sha256": "948cbec7cff61ad191e229292f3b4cb8ee63ffa14e3a1d6e49a1663e5291576a",
            "derivative_sha256": "836aa8e41ce40c2c69416ba3f8a538c3af84140762c364dcbca740ab82fca7c8",
            "setid": "d2d7da5d-ad07-4228-955f-cf7e355c8cc0",
            "spl_version": "38",
            "retrieval_units": 3,
        },
        "source_selection_fixtures": {
            "OZEMPIC": {
                "setid": "adec4fd2-6858-4c99-91d4-531f5f2a2d79",
                "spl_version": "20",
                "selection_state": "accepted_exact_retained_label",
            },
            "MOUNJARO": {
                "setid": "d2d7da5d-ad07-4228-955f-cf7e355c8cc0",
                "spl_version": "38",
                "selection_state": "accepted_exact_retained_label",
            },
            "rejected_candidate_fixture_status": "not_materialized_no_retrieval_qrels_impact",
        },
        "cadec": {
            "status": "unavailable_not_materialized",
            "archive_expected_sha256": (
                "4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a"
            ),
            "current_accepted_local_path": None,
            "corpus_units": 0,
            "limitation": "accepted archive path is unavailable; no text was fabricated",
        },
        "faers_d": {
            "query_id": (
                "faers-query:sha256:a8a4e1086e2f9003b33edda1eb9dd4c70d0ebe54b5d1df78b031778b3e191f4c"
            ),
            "status": "complete_scoped_no_match_source_selection_fixture_only",
            "corpus_units": 0,
            "raw_sha256": "57b1e7534d003e4246182162fd2469cdf038de39405056f44fc006715e5496da",
        },
    }


def _expected_corpus() -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    """Reconstruct the exact corpus from retained immutable source evidence."""

    gold_items, _ = _verify_dailymed_and_gold()
    extension_items, pair_counts = _parse_pubmed_extensions()
    all_by_id = {cast(str, item["retrieval_unit_id"]): item for item in gold_items}
    for item in extension_items:
        identity = cast(str, item["retrieval_unit_id"])
        if identity in all_by_id:
            existing = all_by_id[identity]
            if existing.get("title") != item.get("title") or existing.get(
                "text_sha256"
            ) != item.get("text_sha256"):
                raise Dev40CorpusError(f"Gold-10 compatibility content drift: {identity}")
            continue
        all_by_id[identity] = item
    items = sorted(all_by_id.values(), key=lambda item: cast(str, item["retrieval_unit_id"]))
    return items, validate_retrieval_units(items), pair_counts


def _reconciliation_document(
    pair_counts: Mapping[str, Any], counts: Mapping[str, int]
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.source-reconciliation.v1",
        "work_item": WORK_ITEM,
        "status": "COMPLETE",
        "network_operations": 0,
        "pubmed_pairs": dict(pair_counts),
        "pubmed_union": {
            "articles": counts["pubmed_article"],
            "book_documents": counts["pubmed_book_document"],
            "provider_records": counts["pubmed_article"] + counts["pubmed_book_document"],
            "book_pmid": BOOK_PMID,
            "book_mapping": "source_native_retained_not_coerced",
        },
        "dailymed": {"ozempic_sections": 12, "mounjaro_sections": 3},
        "faers_d": "complete_scoped_no_match_fixture_not_corpus",
        "cadec": "unavailable_not_materialized_zero_corpus_units",
        "limitations": [
            "CADEC text-bearing local materialization is unavailable.",
            "FAERS complete no-match applies only to the exact frozen query coordinate.",
            "Retained PubMed searches are bounded and do not establish exhaustive "
            "literature coverage.",
        ],
    }


def _manifest_document(
    items: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    limitations: Any,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.manifest.v1",
        "work_item": WORK_ITEM,
        "dataset": DATASET,
        "split": "Development-40",
        "status": "FROZEN_AWAITING_OWNER_ADJUDICATION",
        "gold10_v2_immutable_binding": GOLD_MANIFEST_SHA256,
        "question_set_binding": QUESTIONS_SHA256,
        "counts": {**counts, "pubmed_total": 199, "total": EXPECTED_TOTAL},
        "source_coverage_limitations": limitations,
        "items": list(items),
    }


def freeze_dev40(
    output_root: str | Path = OUTPUT_ROOT,
    *,
    _allow_test_root: bool = False,
) -> FreezeResult:
    """Freeze the exact retained-evidence Dev-40 corpus without network access."""

    root = Path(output_root).resolve()
    if not _allow_test_root and root != OUTPUT_ROOT.resolve():
        raise Dev40CorpusError("Dev-40 freeze requires the exact external evidence root")
    if root.exists():
        raise Dev40CorpusError("Dev-40 corpus-freeze evidence root already exists")

    corpus_items, counts, pair_counts = _expected_corpus()
    questions, layers = _question_records()

    book_successor = _load_json(
        BOOK_SUCCESSOR_ROOT / "pubmed-c-offline-successor-reconciliation.json",
        BOOK_SUCCESSOR_SHA256,
    )
    faers_success = _load_json(FAERS_SUCCESSOR_ROOT / "success-manifest.json", FAERS_SUCCESS_SHA256)
    _load_json(ACQUISITION_ROOT / "stop.json", ORIGINAL_STOP_SHA256)
    if (
        book_successor.get("status") != "OFFLINE_SUCCESSOR_RECONCILIATION_COMPLETE"
        or faers_success.get("status") != "FAERS_D_COMPLETE_OFFLINE_RECONCILIATION_ONLY"
        or faers_success.get("raw_response_bytes") != 80
    ):
        raise Dev40CorpusError("accepted successor evidence status drifted")

    source_state = _source_state_document()
    reconciliation = _reconciliation_document(pair_counts, counts)
    run_plan = _run_plan_document()
    manifest = _manifest_document(corpus_items, counts, reconciliation["limitations"])

    root.mkdir(parents=True, exist_ok=False)
    _write_json(root / "run-plan.json", run_plan)
    state_sha = _write_json(root / "source-state-inventory.json", source_state)
    reconciliation_sha = _write_json(root / "source-reconciliation.json", reconciliation)
    manifest_sha = _write_json(root / "corpus-manifest.json", manifest)
    packet = _packet(corpus_items, questions, layers, manifest_sha)
    packet_sha = _write_json(root / "blinded-adjudication-packet.json", packet)
    load_and_validate_freeze(root)
    return FreezeResult(
        root,
        manifest_sha,
        packet_sha,
        reconciliation_sha,
        state_sha,
        EXPECTED_TOTAL,
        len(RETRIEVAL_QUESTION_IDS),
    )


def load_and_validate_freeze(root: str | Path = OUTPUT_ROOT) -> FreezeResult:
    """Rehash and strictly validate a completed Dev-40 freeze."""

    path = Path(root).resolve()
    required = (
        "run-plan.json",
        "source-state-inventory.json",
        "source-reconciliation.json",
        "corpus-manifest.json",
        "blinded-adjudication-packet.json",
    )
    digests = {name: _sidecar_valid(path / name) for name in required}
    manifest = _load_json(path / "corpus-manifest.json", digests["corpus-manifest.json"])
    packet = _load_json(
        path / "blinded-adjudication-packet.json",
        digests["blinded-adjudication-packet.json"],
    )
    source_state = _load_json(
        path / "source-state-inventory.json", digests["source-state-inventory.json"]
    )
    run_plan = _load_json(path / "run-plan.json", digests["run-plan.json"])
    reconciliation = _load_json(
        path / "source-reconciliation.json", digests["source-reconciliation.json"]
    )
    items = manifest.get("items")
    questions = packet.get("questions")
    if not isinstance(items, list) or not isinstance(questions, list):
        raise Dev40CorpusError("frozen corpus or packet collection is malformed")
    typed_items = [cast(dict[str, Any], item) for item in items]
    validate_retrieval_units(typed_items)
    _validate_packet_blindness(packet)
    expected_items, expected_counts, expected_pair_counts = _expected_corpus()
    expected_reconciliation = _reconciliation_document(expected_pair_counts, expected_counts)
    expected_manifest = _manifest_document(
        expected_items, expected_counts, expected_reconciliation["limitations"]
    )
    expected_questions, expected_layers = _question_records()
    expected_packet = _packet(
        expected_items,
        expected_questions,
        expected_layers,
        digests["corpus-manifest.json"],
    )
    if (
        manifest != expected_manifest
        or reconciliation != expected_reconciliation
        or packet != expected_packet
        or run_plan != _run_plan_document()
        or source_state != _source_state_document()
        or packet.get("corpus_manifest_sha256") != digests["corpus-manifest.json"]
        or len(questions) != len(RETRIEVAL_QUESTION_IDS)
        or [row.get("question_id") for row in questions if isinstance(row, dict)]
        != list(RETRIEVAL_QUESTION_IDS)
        or any(
            not isinstance(row, dict)
            or row.get("candidate_count") != EXPECTED_TOTAL
            or len(cast(list[Any], row.get("candidates"))) != EXPECTED_TOTAL
            for row in questions
        )
    ):
        raise Dev40CorpusError("frozen blinded packet does not bind the exact corpus")
    return FreezeResult(
        path,
        digests["corpus-manifest.json"],
        digests["blinded-adjudication-packet.json"],
        digests["source-reconciliation.json"],
        digests["source-state-inventory.json"],
        len(items),
        len(questions),
    )


__all__ = [
    "BOOK_RETRIEVAL_ID",
    "OUTPUT_ROOT",
    "RETRIEVAL_QUESTION_IDS",
    "Dev40CorpusError",
    "FreezeResult",
    "freeze_dev40",
    "load_and_validate_freeze",
    "validate_retrieval_units",
]
