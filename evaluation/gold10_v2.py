"""Offline reuse and one-shot recovery for MEDEVIDENCE_GOLD10_V2.

This evaluation-only module has no import-time I/O.  It reconstructs the
immutable M2-003 evidence before exposing the separately acknowledged,
one-logical-operation MOUNJARO recovery.  Provider-original bytes and safe
parsing derivatives remain outside Git.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
from defusedxml import ElementTree as safe_etree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from medevidence.connectors.dailymed.parsing import (
    HL7_DOCUMENT,
    HL7_SETID,
    HL7_VERSION,
    ParsedSourceNativeSplDocument,
    parse_source_native_spl_document,
)
from medevidence.connectors.dailymed.policy import (
    MAX_PAYLOAD_BYTES,
    REDIRECT_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    DailyMedConnectorConfig,
    DailyMedOperation,
    build_dailymed_request,
    parse_retry_after,
    retry_delay_seconds,
    validate_dailymed_url,
    validate_setid,
    validate_spl_version,
)
from medevidence.connectors.pubmed.parsing import parse_fetch_response, parse_search_page

DATASET: Final = "MEDEVIDENCE_GOLD10_V2"
SCHEMA_VERSION: Final = "medevidence.gold10.v2"
CANONICAL_OUTPUT_ROOT: Final = Path(
    r"D:\Projects\medevidence-external-evidence\M2-005-MEDEVIDENCE-GOLD10-V2"
)
M2_003_ROOT: Final = Path(r"D:\Projects\medevidence-external-evidence\M2-003-MEDEVIDENCE-GOLD10")
M2_003_RUN_PLAN_SHA256: Final = "2ec7279d8202f70628cdca7c86d31859ae50adf4cbb6cd1d3871df4627032dd4"
M2_003_STOP_SHA256: Final = "58bd84a5b70f5b7ac40e5beeb823fd1801f93cc6489958f573938f3bd71fa965"
M2_003_EFETCH_SHA256: Final = "e2ee69ae5567f4e5c2886f4b2318d6e33ffec2d6f4e1bda24c55550d62084df4"
OZEMPIC_SETID: Final = "adec4fd2-6858-4c99-91d4-531f5f2a2d79"
OZEMPIC_VERSION: Final = "20"
OZEMPIC_RAW_BYTES: Final = 627_087
OZEMPIC_RAW_SHA256: Final = "cc9ecba8cce6eec215db9a0db28ef3c1c63dce3ba746aaf3caa5c3e9cd956626"
OZEMPIC_PI_RANGE: Final = (38, 133)
OZEMPIC_PI_REMOVED_SHA256: Final = (
    "30a1f72319881be269709c1acc3e11887791c4dab78e84d6a24020c1e4a8d823"
)
OZEMPIC_AFTER_PI_SHA256: Final = "8a6a067b167db86d6ba5de532a68e78f34470f6b3cb46a14bce758a8eaf619b9"
OZEMPIC_SCHEMA_RAW_RANGE: Final = (220, 306)
OZEMPIC_SCHEMA_PIPELINE_RANGE: Final = (125, 211)
OZEMPIC_SCHEMA_REMOVED_SHA256: Final = (
    "0ac6f88a3cea1e008ece4eff8106e69537c529b5d9451e84d861cb6a2bec6bad"
)
OZEMPIC_FINAL_SHA256: Final = "71fe03bf90e72a6e74c856f402a1ac95031528b87206dee0be931c1984217eaa"
MOUNJARO_SETID: Final = "d2d7da5d-ad07-4228-955f-cf7e355c8cc0"
MOUNJARO_URL: Final = f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{MOUNJARO_SETID}.xml"
LIVE_ACKNOWLEDGEMENT: Final = "M2-005-MOUNJARO-ONE-LOGICAL-OPERATION"
COMBINED_RAW_BYTE_CEILING: Final = 15_728_640
M2_003_RECEIVED_RAW_BYTES: Final = 2_422_569
MAX_PMIDS: Final = 80
MAX_M2_003_OPERATIONS: Final = 6
FORBIDDEN_BLIND_FIELDS: Final = (
    "score",
    "rank",
    "retriever",
    "nominat",
    "bm25",
    "medcpt",
    "rrf",
)
OPERATIONAL_RESPONSE_HEADERS: Final = frozenset(
    {b"content-length", b"transfer-encoding", b"content-encoding", b"location", b"retry-after"}
)

QUESTIONS: Final[tuple[str, ...]] = (
    "What gastrointestinal adverse reactions are reported in the reference current "
    "manufacturer label for OZEMPIC (semaglutide injection)?",
    "What gastrointestinal adverse reactions are reported in the reference current "
    "manufacturer label for MOUNJARO (tirzepatide injection)?",
    "What published evidence reports nausea associated with semaglutide?",
    "What published evidence reports vomiting associated with semaglutide?",
    "What published evidence reports diarrhoea associated with semaglutide?",
    "What published evidence reports nausea associated with tirzepatide?",
    "What published evidence reports vomiting associated with tirzepatide?",
    "What published evidence reports diarrhoea associated with tirzepatide?",
    "What published evidence directly compares gastrointestinal adverse events between "
    "semaglutide and tirzepatide?",
    "What evidence reports serious, severe, or treatment-limiting gastrointestinal adverse "
    "events for semaglutide or tirzepatide?",
)


class Gold10V2Error(RuntimeError):
    """A fail-closed offline reuse, transformation, or recovery failure."""


@dataclass(frozen=True, slots=True)
class TransformationStep:
    """Exact byte-deletion lineage for one safe-parsing derivative."""

    transformation_id: str
    input_bytes: int
    input_sha256: str
    removed_start: int
    removed_end: int
    removed_bytes: int
    removed_sha256: str
    output_bytes: int
    output_sha256: str
    exact_splice_equality: bool

    def as_dict(self) -> dict[str, Any]:
        """Return canonical JSON-ready lineage."""

        return {
            "transformation_id": self.transformation_id,
            "input_bytes": self.input_bytes,
            "input_sha256": self.input_sha256,
            "removed_start": self.removed_start,
            "removed_end": self.removed_end,
            "removed_bytes": self.removed_bytes,
            "removed_sha256": self.removed_sha256,
            "output_bytes": self.output_bytes,
            "output_sha256": self.output_sha256,
            "exact_splice_equality": self.exact_splice_equality,
        }


@dataclass(frozen=True, slots=True)
class DerivativeResult:
    """A derivative explicitly distinguished from provider-original bytes."""

    payload: bytes
    lineage: tuple[TransformationStep, ...]


@dataclass(frozen=True, slots=True)
class PreNetworkResult:
    """Identity of the completed offline reuse gate."""

    output_root: Path
    manifest_path: Path
    manifest_sha256: str
    pubmed_items: int
    ozempic_retrieval_items: int
    ozempic_structural_occurrences: int


@dataclass(frozen=True, slots=True)
class LiveRecoveryResult:
    """Identity of a successful one-shot MOUNJARO recovery and corpus freeze."""

    output_root: Path
    corpus_manifest_sha256: str
    adjudication_packet_sha256: str
    mounjaro_retrieval_items: int
    mounjaro_structural_occurrences: int
    http_attempts: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Gold10V2Error(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _strict_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Gold10V2Error(f"cannot load exact JSON evidence {path.name}") from error


def _write_json(path: Path, value: Any) -> str:
    data = _canonical_json_bytes(value)
    _atomic_write(path, data)
    digest = _sha256(data)
    _atomic_write(
        path.with_suffix(path.suffix + ".sha256"),
        f"{digest}  {path.name}\n".encode("ascii"),
    )
    return digest


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace one evidence file only after its complete bytes are durable locally."""

    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    if pending.exists():
        raise Gold10V2Error(f"stale pending evidence file exists: {pending.name}")
    try:
        pending.write_bytes(data)
        if pending.read_bytes() != data:
            raise Gold10V2Error(f"pending evidence verification failed: {path.name}")
        pending.replace(path)
    except Exception:
        with suppress(OSError):
            pending.unlink()
        raise


def _write_binary_with_sidecar(path: Path, data: bytes) -> str:
    _atomic_write(path, data)
    digest = _sha256(data)
    _atomic_write(
        path.with_suffix(path.suffix + ".sha256"),
        f"{digest}  {path.name}\n".encode("ascii"),
    )
    return digest


def _verified_bytes(path: Path, *, expected_bytes: int, expected_sha256: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Gold10V2Error(f"required retained artifact is unavailable: {path.name}") from error
    if len(data) != expected_bytes or _sha256(data) != expected_sha256:
        raise Gold10V2Error(f"retained artifact identity mismatch: {path.name}")
    return data


def _verified_json(path: Path, expected_sha256: str) -> Mapping[str, Any]:
    data = _verified_bytes(
        path, expected_bytes=path.stat().st_size, expected_sha256=expected_sha256
    )
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Gold10V2Error(f"retained JSON is malformed: {path.name}") from error
    if not isinstance(value, dict):
        raise Gold10V2Error(f"retained JSON must be an object: {path.name}")
    return value


def _operation_map(stop: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    operations = stop.get("operations")
    if not isinstance(operations, list) or len(operations) != MAX_M2_003_OPERATIONS:
        raise Gold10V2Error("M2-003 operation inventory is incomplete")
    result: dict[str, Mapping[str, Any]] = {}
    for operation in operations:
        if not isinstance(operation, dict) or not isinstance(operation.get("operation_id"), str):
            raise Gold10V2Error("M2-003 operation record is malformed")
        operation_id = operation["operation_id"]
        if operation_id in result:
            raise Gold10V2Error("M2-003 operation IDs are not unique")
        if operation.get("terminal_status") != "completed":
            raise Gold10V2Error("M2-003 reused operation is not complete")
        result[operation_id] = operation
    expected = {
        "pubmed-esearch-1",
        "pubmed-esearch-2",
        "pubmed-esearch-3",
        "pubmed-esearch-4",
        "pubmed-efetch-union",
        "dailymed-current-ozempic",
    }
    if set(result) != expected:
        raise Gold10V2Error("M2-003 operation identities differ from the frozen six")
    return result


def _raw_from_operation(root: Path, operation: Mapping[str, Any]) -> bytes:
    attempts = operation.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise Gold10V2Error("completed operation has no attempt evidence")
    successful = [
        item for item in attempts if isinstance(item, dict) and item.get("status_code") == 200
    ]
    if len(successful) != 1:
        raise Gold10V2Error("completed operation must have exactly one HTTP 200 attempt")
    raw = successful[0].get("raw")
    if not isinstance(raw, dict):
        raise Gold10V2Error("completed operation omits raw artifact identity")
    relative = raw.get("relative_path")
    size = raw.get("bytes")
    digest = raw.get("sha256")
    if not isinstance(relative, str) or not isinstance(size, int) or not isinstance(digest, str):
        raise Gold10V2Error("raw artifact identity is malformed")
    candidate = (root / relative).resolve()
    trusted = root.resolve()
    if candidate == trusted or trusted not in candidate.parents:
        raise Gold10V2Error("raw artifact path escapes the retained evidence root")
    data = _verified_bytes(candidate, expected_bytes=size, expected_sha256=digest)
    if operation.get("terminal_raw_sha256") != digest:
        raise Gold10V2Error("terminal raw identity differs from attempt evidence")
    return data


def reconstruct_retained_pubmed(
    root: Path, stop: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, ...]]]:
    """Reconstruct the exact 50-PMID corpus and four query memberships offline."""

    operations = _operation_map(stop)
    memberships: dict[str, list[str]] = {}
    for index in range(1, 5):
        operation_id = f"pubmed-esearch-{index}"
        operation = operations[operation_id]
        body = _raw_from_operation(root, operation)
        parsed = parse_search_page(body, 0, max_items=20)
        recorded = operation.get("returned_pmids")
        if not isinstance(recorded, list) or tuple(recorded) != parsed.pmids:
            raise Gold10V2Error(f"{operation_id} membership differs from retained raw XML")
        for pmid in parsed.pmids:
            memberships.setdefault(pmid, []).append(operation_id)
    unique_pmids = sorted(memberships, key=int)
    if len(unique_pmids) != 50:
        raise Gold10V2Error("retained PubMed union must contain exactly 50 unique PMIDs")

    fetch_operation = operations["pubmed-efetch-union"]
    if fetch_operation.get("requested_pmids") != unique_pmids:
        raise Gold10V2Error("retained EFetch request does not equal the ESearch union")
    fetch_body = _raw_from_operation(root, fetch_operation)
    if _sha256(fetch_body) != M2_003_EFETCH_SHA256:
        raise Gold10V2Error("retained EFetch artifact differs from the frozen identity")
    parsed_fetch = parse_fetch_response(fetch_body, unique_pmids, max_items=MAX_PMIDS)
    if (
        parsed_fetch.malformed_records
        or parsed_fetch.duplicate_pmids
        or parsed_fetch.unexpected_pmids
        or parsed_fetch.missing_expected_pmids
        or len(parsed_fetch.records) != 50
    ):
        raise Gold10V2Error("retained EFetch corpus coverage is not exact")
    items: list[dict[str, Any]] = []
    for record in sorted(parsed_fetch.records, key=lambda item: int(item.pmid)):
        abstract_sections = [
            {"label": section.label, "nlm_category": section.nlm_category, "text": section.text}
            for section in record.abstract_sections
        ]
        text = "\n".join(section.text for section in record.abstract_sections)
        if not text.strip():
            raise Gold10V2Error("one of the frozen 50 PubMed records lacks an abstract")
        content = {
            "pmid": record.pmid,
            "title": record.title,
            "abstract_sections": abstract_sections,
        }
        items.append(
            {
                "source": "pubmed",
                "retrieval_unit_id": f"pubmed:{record.pmid}",
                "stable_source_id": record.pmid,
                "source_version_identity": (
                    f"pmid:{record.pmid}:content-sha256:{_sha256(_canonical_json_bytes(content))}"
                ),
                "source_locator": f"https://pubmed.ncbi.nlm.nih.gov/{record.pmid}/",
                "title": record.title,
                "text": text,
                "text_sha256": _sha256(text.encode("utf-8")),
                "abstract_sections": abstract_sections,
                "query_memberships": memberships[record.pmid],
                "source_artifact_sha256": M2_003_EFETCH_SHA256,
                "reused_from_work_item": "M2-003-MEDEVIDENCE-GOLD10",
            }
        )
    frozen_memberships = {key: tuple(value) for key, value in memberships.items()}
    return items, frozen_memberships


def _deletion(
    payload: bytes, start: int, end: int, transformation_id: str
) -> tuple[bytes, TransformationStep]:
    if not 0 <= start < end <= len(payload):
        raise Gold10V2Error(f"{transformation_id} byte range is invalid")
    removed = payload[start:end]
    output = payload[:start] + payload[end:]
    proof = output == payload[:start] + payload[end:]
    if not proof or len(output) != len(payload) - len(removed):
        raise Gold10V2Error(f"{transformation_id} exact splice proof failed")
    return output, TransformationStep(
        transformation_id=transformation_id,
        input_bytes=len(payload),
        input_sha256=_sha256(payload),
        removed_start=start,
        removed_end=end,
        removed_bytes=len(removed),
        removed_sha256=_sha256(removed),
        output_bytes=len(output),
        output_sha256=_sha256(output),
        exact_splice_equality=proof,
    )


@dataclass(frozen=True, slots=True)
class _ProcessingInstruction:
    target: bytes
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _XmlLexicalView:
    root_start: int
    root_end: int
    root_name: bytes
    processing_instructions: tuple[_ProcessingInstruction, ...]


def _xml_name_end(payload: bytes, start: int, limit: int) -> int:
    allowed = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    cursor = start
    while cursor < limit and payload[cursor] in allowed:
        cursor += 1
    if cursor == start:
        raise Gold10V2Error("XML markup contains a missing or invalid name")
    return cursor


def _markup_end(payload: bytes, start: int) -> int:
    """Find a bounded markup close while respecting quotes and DTD subsets."""

    quote: int | None = None
    subset_depth = 0
    for index in range(start, min(len(payload), start + MAX_PAYLOAD_BYTES)):
        byte = payload[index]
        if quote is None and byte in (34, 39):
            quote = byte
        elif quote == byte:
            quote = None
        elif quote is None and byte == 91:
            subset_depth += 1
        elif quote is None and byte == 93 and subset_depth:
            subset_depth -= 1
        elif quote is None and subset_depth == 0 and byte == 62:
            return index + 1
    raise Gold10V2Error("XML markup is unterminated or exceeds the bounded scan")


def _lex_xml(payload: bytes) -> _XmlLexicalView:
    """Classify XML markup without interpreting or reserializing source bytes."""

    if not payload or len(payload) > MAX_PAYLOAD_BYTES:
        raise Gold10V2Error("XML lexical input is empty or exceeds the payload bound")
    cursor = 0
    root_start: int | None = None
    root_end: int | None = None
    root_name: bytes | None = None
    depth = 0
    instructions: list[_ProcessingInstruction] = []
    while cursor < len(payload):
        opening = payload.find(b"<", cursor)
        if opening < 0:
            break
        if payload.startswith(b"<!--", opening):
            close = payload.find(b"-->", opening + 4)
            if close < 0:
                raise Gold10V2Error("XML comment is unterminated")
            cursor = close + 3
            continue
        if payload.startswith(b"<![CDATA[", opening):
            close = payload.find(b"]]>", opening + 9)
            if close < 0:
                raise Gold10V2Error("XML CDATA section is unterminated")
            cursor = close + 3
            continue
        if payload.startswith(b"<?", opening):
            close = payload.find(b"?>", opening + 2)
            if close < 0:
                raise Gold10V2Error("processing instruction is unterminated")
            name_end = _xml_name_end(payload, opening + 2, close)
            if name_end < close and payload[name_end] not in b" \t\r\n?":
                raise Gold10V2Error("processing-instruction target is malformed")
            instructions.append(
                _ProcessingInstruction(payload[opening + 2 : name_end], opening, close + 2)
            )
            cursor = close + 2
            continue
        if payload.startswith(b"<!", opening):
            cursor = _markup_end(payload, opening + 2)
            continue
        if payload.startswith(b"</", opening):
            close = _markup_end(payload, opening + 2)
            depth -= 1
            if depth < 0:
                raise Gold10V2Error("XML end-tag depth is invalid")
            cursor = close
            continue
        close = _markup_end(payload, opening + 1)
        name_end = _xml_name_end(payload, opening + 1, close - 1)
        name = payload[opening + 1 : name_end]
        if root_start is None:
            root_start, root_end, root_name = opening, close, name
        self_closing = payload[opening:close].rstrip().endswith(b"/>")
        if not self_closing:
            depth += 1
        cursor = close
    if root_start is None or root_end is None or root_name is None:
        raise Gold10V2Error("SPL document root is unavailable")
    return _XmlLexicalView(root_start, root_end, root_name, tuple(instructions))


def _stylesheet_pi_range(payload: bytes) -> tuple[int, int] | None:
    view = _lex_xml(payload)
    stylesheet = [
        instruction
        for instruction in view.processing_instructions
        if instruction.target == b"xml-stylesheet"
    ]
    if len(stylesheet) > 1:
        raise Gold10V2Error("xml-stylesheet PI must occur at most once")
    for instruction in view.processing_instructions:
        is_declaration = instruction.target == b"xml" and instruction.start == 0
        if instruction not in stylesheet and not is_declaration:
            raise Gold10V2Error("another processing instruction requires interpretation")
    if not stylesheet:
        return None
    instruction = stylesheet[0]
    if instruction.start > view.root_start:
        raise Gold10V2Error("xml-stylesheet PI must be in the prolog before the root")
    return instruction.start, instruction.end


def _root_opening_end(payload: bytes, root_start: int) -> int:
    quote: int | None = None
    for index in range(root_start, min(len(payload), root_start + 16_384)):
        byte = payload[index]
        if quote is None and byte in (34, 39):
            quote = byte
        elif quote == byte:
            quote = None
        elif quote is None and byte == 62:
            return index + 1
    raise Gold10V2Error("root opening tag is unterminated or exceeds the bounded scan")


def _schema_location_range(payload: bytes) -> tuple[int, int] | None:
    view = _lex_xml(payload)
    if view.root_name != b"document":
        raise Gold10V2Error("SPL lexical root must be exact document")
    cursor = view.root_start + 1 + len(view.root_name)
    attributes: list[tuple[bytes, int, int, bytes]] = []
    while cursor < view.root_end - 1:
        whitespace_start = cursor
        while cursor < view.root_end and payload[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= view.root_end - 1 or payload[cursor : cursor + 2] == b"/>":
            break
        name_start = cursor
        name_end = _xml_name_end(payload, cursor, view.root_end - 1)
        name = payload[name_start:name_end]
        cursor = name_end
        while cursor < view.root_end and payload[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= view.root_end or payload[cursor] != 61:
            raise Gold10V2Error("root attribute is missing exact equals syntax")
        cursor += 1
        while cursor < view.root_end and payload[cursor] in b" \t\r\n":
            cursor += 1
        if cursor >= view.root_end or payload[cursor] not in (34, 39):
            raise Gold10V2Error("root attribute value is not exactly quoted")
        quote = payload[cursor]
        value_start = cursor + 1
        value_end = payload.find(bytes((quote,)), value_start, view.root_end)
        if value_end < 0:
            raise Gold10V2Error("root attribute value is unterminated")
        attributes.append((name, whitespace_start, value_end + 1, payload[value_start:value_end]))
        cursor = value_end + 1
    names = [name for name, _, _, _ in attributes]
    if len(names) != len(set(names)):
        raise Gold10V2Error("root attributes contain a repeated exact name")
    namespace = [value for name, _, _, value in attributes if name == b"xmlns:xsi"]
    targets = [item for item in attributes if item[0] == b"xsi:schemaLocation"]
    if not targets:
        return None
    if namespace != [b"http://www.w3.org/2001/XMLSchema-instance"]:
        raise Gold10V2Error("xsi:schemaLocation lacks the exact xsi namespace binding")
    _, start, end, _ = targets[0]
    return start, end


def derive_for_safe_parsing(payload: bytes) -> DerivativeResult:
    """Delete at most one stylesheet PI and one root schemaLocation attribute."""

    current = bytes(payload)
    lineage: list[TransformationStep] = []
    pi_range = _stylesheet_pi_range(current)
    if pi_range is not None:
        current, step = _deletion(current, *pi_range, "strip_xml_stylesheet_pi_v1")
        lineage.append(step)
    schema_range = _schema_location_range(current)
    if schema_range is not None:
        current, step = _deletion(current, *schema_range, "strip_root_xsi_schema_location_v1")
        lineage.append(step)
    return DerivativeResult(current, tuple(lineage))


def _observe_spl_identity(payload: bytes, expected_setid: str) -> str:
    try:
        root = safe_etree.fromstring(payload, forbid_dtd=True, forbid_entities=True)
    except (DefusedXmlException, safe_etree.ParseError, ValueError) as error:
        raise Gold10V2Error("safe derivative is not bounded parseable XML") from error
    if root.tag != HL7_DOCUMENT:
        raise Gold10V2Error("safe derivative is not an HL7 SPL document")
    setids = root.findall(f"./{HL7_SETID}")
    versions = root.findall(f"./{HL7_VERSION}")
    if len(setids) != 1 or len(versions) != 1:
        raise Gold10V2Error("safe derivative has ambiguous SPL identity")
    setid = setids[0].attrib.get("root")
    version = versions[0].attrib.get("value")
    try:
        if validate_setid(str(setid)) != expected_setid:
            raise Gold10V2Error("safe derivative SETID differs from the request")
        return validate_spl_version(str(version))
    except ValueError as error:
        raise Gold10V2Error("safe derivative has invalid SPL identity") from error


def _section_records(
    parsed: ParsedSourceNativeSplDocument,
    *,
    brand: str,
    raw_sha256: str,
    transformation_chain_sha256: str,
    operation_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    retrieval: list[dict[str, Any]] = []
    structural: list[dict[str, Any]] = []
    for section in parsed.sections:
        base = {
            "source": "dailymed",
            "stable_source_id": str(section.setid),
            "source_version_identity": (f"setid:{section.setid}:spl-version:{section.spl_version}"),
            "brand": brand,
            "setid": str(section.setid),
            "spl_version": str(section.spl_version),
            "section_occurrence_id": str(section.section_occurrence_id),
            "observed_loinc_code": section.section_code,
            "observed_code_system": section.code_system_oid,
            "normalized_loinc_name": str(section.normalized_section_name),
            "provider_title": str(section.provider_title),
            "ordinal": section.section_ordinal,
            "parent_ordinal": section.parent_section_ordinal,
            "xml_path": str(section.xml_path),
            "text_sha256": str(section.text_sha256),
            "source_raw_artifact_sha256": raw_sha256,
            "transformation_chain_sha256": transformation_chain_sha256,
            "acquisition_operation_id": operation_id,
        }
        if section.retrieval_eligible:
            retrieval.append(
                {
                    **base,
                    "retrieval_unit_id": f"dailymed:{section.section_occurrence_id}",
                    "source_locator": (
                        f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={section.setid}"
                    ),
                    "title": str(section.provider_title),
                    "text": section.extracted_text,
                    "retrieval_eligible": True,
                }
            )
        else:
            structural.append({**base, "retrieval_eligible": False, "provenance_only": True})
    return retrieval, structural


def _transformation_chain(
    *,
    brand: str,
    raw_path: str,
    raw: bytes,
    derivative: DerivativeResult,
    final_derivative_relative_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": "medevidence.safe-parsing-derivative.v1",
        "brand": brand,
        "raw_artifact": {
            "authoritative_provider_response": True,
            "external_path": raw_path,
            "bytes": len(raw),
            "sha256": _sha256(raw),
        },
        "derivative_disposition": "derived_for_safe_parsing",
        "steps": [step.as_dict() for step in derivative.lineage],
        "final_derivative": {
            "relative_path": final_derivative_relative_path,
            "bytes": len(derivative.payload),
            "sha256": _sha256(derivative.payload),
        },
    }


def _artifact_record(root: Path, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    digest = _sha256(data)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    sidecar_data = sidecar.read_bytes()
    if sidecar_data != f"{digest}  {path.name}\n".encode("ascii"):
        raise Gold10V2Error(f"artifact sidecar differs from retained bytes: {path.name}")
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": digest,
        "sidecar_relative_path": sidecar.relative_to(root).as_posix(),
        "sidecar_bytes": len(sidecar_data),
        "sidecar_sha256": _sha256(sidecar_data),
    }


def _verify_artifact_record(root: Path, record: object) -> bytes:
    if not isinstance(record, dict):
        raise Gold10V2Error("artifact inventory record is malformed")
    required = {
        "relative_path": str,
        "bytes": int,
        "sha256": str,
        "sidecar_relative_path": str,
        "sidecar_bytes": int,
        "sidecar_sha256": str,
    }
    if any(not isinstance(record.get(key), kind) for key, kind in required.items()):
        raise Gold10V2Error("artifact inventory fields are malformed")
    path = (root / str(record["relative_path"])).resolve()
    sidecar = (root / str(record["sidecar_relative_path"])).resolve()
    trusted = root.resolve()
    if trusted not in path.parents or trusted not in sidecar.parents:
        raise Gold10V2Error("artifact inventory path escapes the evidence root")
    data = _verified_bytes(
        path,
        expected_bytes=int(record["bytes"]),
        expected_sha256=str(record["sha256"]),
    )
    sidecar_data = _verified_bytes(
        sidecar,
        expected_bytes=int(record["sidecar_bytes"]),
        expected_sha256=str(record["sidecar_sha256"]),
    )
    expected_sidecar = f"{record['sha256']}  {path.name}\n".encode("ascii")
    if sidecar_data != expected_sidecar:
        raise Gold10V2Error("artifact sidecar content does not bind retained bytes")
    return data


def _validate_ozempic_derivative(raw: bytes, derivative: DerivativeResult) -> None:
    if len(derivative.lineage) != 2:
        raise Gold10V2Error("OZEMPIC requires exactly the two authorized transformations")
    pi, schema = derivative.lineage
    expected = (
        pi.removed_start == OZEMPIC_PI_RANGE[0]
        and pi.removed_end == OZEMPIC_PI_RANGE[1]
        and pi.removed_bytes == 95
        and pi.removed_sha256 == OZEMPIC_PI_REMOVED_SHA256
        and pi.output_bytes == 626_992
        and pi.output_sha256 == OZEMPIC_AFTER_PI_SHA256
        and schema.removed_start == OZEMPIC_SCHEMA_PIPELINE_RANGE[0]
        and schema.removed_end == OZEMPIC_SCHEMA_PIPELINE_RANGE[1]
        and schema.removed_bytes == 86
        and schema.removed_sha256 == OZEMPIC_SCHEMA_REMOVED_SHA256
        and schema.output_bytes == 626_906
        and schema.output_sha256 == OZEMPIC_FINAL_SHA256
        and len(raw) == OZEMPIC_RAW_BYTES
    )
    if not expected:
        raise Gold10V2Error("OZEMPIC derivative differs from the exact authorized chain")
    # The schema attribute's range in provider-original bytes is separately frozen.
    if (
        raw[OZEMPIC_SCHEMA_RAW_RANGE[0] : OZEMPIC_SCHEMA_RAW_RANGE[1]]
        != raw[
            OZEMPIC_PI_RANGE[1]
            + OZEMPIC_SCHEMA_PIPELINE_RANGE[0]
            - OZEMPIC_PI_RANGE[0] : OZEMPIC_PI_RANGE[1]
            + OZEMPIC_SCHEMA_PIPELINE_RANGE[1]
            - OZEMPIC_PI_RANGE[0]
        ]
    ):
        raise Gold10V2Error("OZEMPIC raw/pipeline schema ranges do not bind the same bytes")


def _source_state() -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[1]
    files: dict[str, dict[str, Any]] = {}
    for relative in (
        "docs/DATA_SOURCES.md",
        "docs/EVALUATION_PLAN.md",
        "docs/TRACEABILITY_MATRIX.md",
        "docs/decisions/ADR-015-m2-005-medevidence-gold10-v2.md",
        "docs/decisions/README.md",
        "evaluation/gold10_v2.py",
        "evaluation/run_gold10_v2_acquisition.py",
        "tests/unit/evaluation/test_gold10_v2.py",
        "src/medevidence/connectors/dailymed/parsing.py",
        "src/medevidence/connectors/dailymed/policy.py",
        "src/medevidence/domain/sources.py",
        "src/medevidence/connectors/pubmed/parsing.py",
    ):
        path = repo / relative
        data = path.read_bytes()
        files[relative] = {"bytes": len(data), "sha256": _sha256(data)}
    return {"binding": "exact runtime file bytes; no runtime Git invocation", "files": files}


def _prepare_root(root: Path, *, allow_test_root: bool) -> Path:
    canonical = root.resolve()
    if not allow_test_root and canonical != CANONICAL_OUTPUT_ROOT.resolve():
        raise Gold10V2Error("output root differs from the exact Owner-authorized root")
    if canonical.exists():
        raise Gold10V2Error("M2-005 evidence root must be absent before offline preparation")
    if not allow_test_root:
        repo = Path(__file__).resolve().parents[1]
        if canonical == repo or repo in canonical.parents or canonical in repo.parents:
            raise Gold10V2Error("medical-source evidence root must remain outside Git")
    canonical.mkdir(parents=True)
    (canonical / "derived" / "ozempic").mkdir(parents=True)
    return canonical


def prepare_pre_network(
    output_root: str | Path = CANONICAL_OUTPUT_ROOT,
    *,
    retained_root: Path = M2_003_ROOT,
    _allow_test_root: bool = False,
) -> PreNetworkResult:
    """Create the complete offline reuse evidence before any live request is possible."""

    root = _prepare_root(Path(output_root), allow_test_root=_allow_test_root)
    try:
        plan = _verified_json(retained_root / "run-plan.json", M2_003_RUN_PLAN_SHA256)
        stop = _verified_json(retained_root / "stop.json", M2_003_STOP_SHA256)
        if plan.get("work_item") != "M2-003-MEDEVIDENCE-GOLD10":
            raise Gold10V2Error("retained run plan has the wrong work-item identity")
        if stop.get("logical_requests") != 6 or stop.get("failed_operation_ids") != []:
            raise Gold10V2Error("retained M2-003 stop cannot be reused as the frozen six")
        pubmed_items, memberships = reconstruct_retained_pubmed(retained_root, stop)
        operation = _operation_map(stop)["dailymed-current-ozempic"]
        ozempic_raw = _raw_from_operation(retained_root, operation)
        if len(ozempic_raw) != OZEMPIC_RAW_BYTES or _sha256(ozempic_raw) != OZEMPIC_RAW_SHA256:
            raise Gold10V2Error("OZEMPIC provider-original identity mismatch")
        derivative = derive_for_safe_parsing(ozempic_raw)
        _validate_ozempic_derivative(ozempic_raw, derivative)
        parsed = parse_source_native_spl_document(
            derivative.payload,
            expected_setid=OZEMPIC_SETID,
            expected_spl_version=OZEMPIC_VERSION,
        )
        derivative_path = root / "derived" / "ozempic" / f"sha256-{OZEMPIC_FINAL_SHA256}.xml"
        derivative_relative = derivative_path.relative_to(root).as_posix()
        _write_binary_with_sidecar(derivative_path, derivative.payload)
        chain = _transformation_chain(
            brand="OZEMPIC",
            raw_path=str(retained_root / "raw" / "dailymed" / f"sha256-{OZEMPIC_RAW_SHA256}.raw"),
            raw=ozempic_raw,
            derivative=derivative,
            final_derivative_relative_path=derivative_relative,
        )
        chain_path = root / "ozempic-transformation-chain.json"
        chain_sha = _write_json(chain_path, chain)
        retrieval, structural = _section_records(
            parsed,
            brand="OZEMPIC",
            raw_sha256=OZEMPIC_RAW_SHA256,
            transformation_chain_sha256=chain_sha,
            operation_id="reused-m2-003-dailymed-current-ozempic",
        )
        if len(parsed.sections) != 13 or len(retrieval) != 12 or len(structural) != 1:
            raise Gold10V2Error("OZEMPIC source-native occurrence inventory drifted")
        if {str(item["transformation_chain_sha256"]) for item in [*retrieval, *structural]} != {
            chain_sha
        }:
            raise Gold10V2Error("OZEMPIC section records do not bind the retained chain bytes")

        pubmed_path = root / "reused-pubmed-corpus.json"
        memberships_path = root / "reused-pubmed-memberships.json"
        sections_path = root / "ozempic-source-native-sections.json"
        pubmed_sha = _write_json(pubmed_path, {"items": pubmed_items})
        memberships_sha = _write_json(
            memberships_path,
            {"memberships": {key: list(value) for key, value in sorted(memberships.items())}},
        )
        sections_sha = _write_json(
            sections_path,
            {"retrieval_items": retrieval, "structural_occurrences": structural},
        )
        artifact_inventory = {
            "ozempic_final_derivative": _artifact_record(root, derivative_path),
            "ozempic_source_native_sections": _artifact_record(root, sections_path),
            "ozempic_transformation_chain": _artifact_record(root, chain_path),
            "reused_pubmed_corpus": _artifact_record(root, pubmed_path),
            "reused_pubmed_memberships": _artifact_record(root, memberships_path),
        }
        manifest = {
            "schema_version": f"{SCHEMA_VERSION}.pre-network-manifest.v1",
            "work_item": "M2-005-MEDEVIDENCE-GOLD10-V2",
            "network_operations": 0,
            "live_authorization_status": "unconsumed",
            "m2_003_authority_status": "closed_non_transferable",
            "m2_003_reuse": {
                "external_root": str(retained_root.resolve()),
                "run_plan_sha256": M2_003_RUN_PLAN_SHA256,
                "stop_sha256": M2_003_STOP_SHA256,
                "completed_logical_operations_reused": 6,
                "pubmed_requests_to_repeat": 0,
                "ozempic_requests_to_repeat": 0,
            },
            "pubmed": {
                "unique_items": len(pubmed_items),
                "query_membership_sets": 4,
                "corpus_file_sha256": pubmed_sha,
                "memberships_file_sha256": memberships_sha,
                "efetch_raw_sha256": M2_003_EFETCH_SHA256,
            },
            "ozempic": {
                "raw_bytes": OZEMPIC_RAW_BYTES,
                "raw_sha256": OZEMPIC_RAW_SHA256,
                "provider_original_copied": False,
                "derivative_disposition": "derived_for_safe_parsing",
                "transformation_chain_sha256": chain_sha,
                "source_native_sections_sha256": sections_sha,
                "admitted_occurrences": 13,
                "retrieval_eligible": 12,
                "structural_provenance_only": 1,
            },
            "source_state": _source_state(),
            "artifact_inventory": artifact_inventory,
            "prohibitions": [
                "no PubMed request",
                "no OZEMPIC request",
                "no ranking or score generation",
                "no automatic qrels",
                "no MOUNJARO request before independent review PASS and explicit acknowledgement",
            ],
        }
        manifest_sha = _write_json(root / "pre-network-manifest.json", manifest)
        return PreNetworkResult(root, root / "pre-network-manifest.json", manifest_sha, 50, 12, 1)
    except Exception:
        # A failed preflight remains visibly non-successful; do not remove forensic output.
        with suppress(OSError):
            _write_json(
                root / "pre-network-stop.json",
                {
                    "schema_version": f"{SCHEMA_VERSION}.pre-network-stop.v1",
                    "status": "STOP",
                    "network_operations": 0,
                    "live_authorization_status": "unconsumed",
                },
            )
        raise


def _load_and_verify_pre_network(root: Path) -> Mapping[str, Any]:
    manifest_path = root / "pre-network-manifest.json"
    sidecar = manifest_path.with_suffix(".json.sha256")
    manifest = _strict_json(manifest_path)
    if not isinstance(manifest, dict):
        raise Gold10V2Error("pre-network manifest is not an object")
    try:
        digest_line = sidecar.read_text(encoding="ascii")
    except OSError as error:
        raise Gold10V2Error("pre-network manifest sidecar is missing") from error
    digest = _sha256(manifest_path.read_bytes())
    if digest_line != f"{digest}  pre-network-manifest.json\n":
        raise Gold10V2Error("pre-network manifest sidecar mismatch")
    if (
        manifest.get("network_operations") != 0
        or manifest.get("live_authorization_status") != "unconsumed"
        or manifest.get("work_item") != "M2-005-MEDEVIDENCE-GOLD10-V2"
    ):
        raise Gold10V2Error("pre-network gate is not an exact offline success")
    if manifest.get("source_state") != _source_state():
        raise Gold10V2Error("pre-network source-state binding is stale")
    inventory = manifest.get("artifact_inventory")
    if not isinstance(inventory, dict) or set(inventory) != {
        "ozempic_final_derivative",
        "ozempic_source_native_sections",
        "ozempic_transformation_chain",
        "reused_pubmed_corpus",
        "reused_pubmed_memberships",
    }:
        raise Gold10V2Error("pre-network artifact inventory is incomplete")
    retained = {name: _verify_artifact_record(root, record) for name, record in inventory.items()}
    try:
        chain = json.loads(
            retained["ozempic_transformation_chain"].decode("utf-8"),
            object_pairs_hook=_strict_object,
        )
        sections = json.loads(
            retained["ozempic_source_native_sections"].decode("utf-8"),
            object_pairs_hook=_strict_object,
        )
        pubmed_saved = json.loads(
            retained["reused_pubmed_corpus"].decode("utf-8"),
            object_pairs_hook=_strict_object,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Gold10V2Error("pre-network retained JSON artifact is malformed") from error
    chain_digest = _sha256(retained["ozempic_transformation_chain"])
    final_record = inventory["ozempic_final_derivative"]
    if (
        not isinstance(chain, dict)
        or not isinstance(chain.get("final_derivative"), dict)
        or chain["final_derivative"].get("relative_path") != final_record.get("relative_path")
        or chain["final_derivative"].get("sha256") != final_record.get("sha256")
        or manifest.get("ozempic", {}).get("transformation_chain_sha256") != chain_digest
    ):
        raise Gold10V2Error("retained OZEMPIC chain is not finalized and manifest-bound")
    if not isinstance(sections, dict):
        raise Gold10V2Error("retained OZEMPIC section artifact is malformed")
    section_items = [
        *sections.get("retrieval_items", []),
        *sections.get("structural_occurrences", []),
    ]
    if len(section_items) != 13 or any(
        not isinstance(item, dict) or item.get("transformation_chain_sha256") != chain_digest
        for item in section_items
    ):
        raise Gold10V2Error("all 13 OZEMPIC occurrences must bind the retained chain bytes")
    if not isinstance(pubmed_saved, dict) or len(pubmed_saved.get("items", [])) != 50:
        raise Gold10V2Error("saved PubMed corpus does not contain the exact 50 items")
    # Rebind every reused/derived input before allowing a socket-capable client.
    stop = _verified_json(M2_003_ROOT / "stop.json", M2_003_STOP_SHA256)
    pubmed_items, _ = reconstruct_retained_pubmed(M2_003_ROOT, stop)
    if len(pubmed_items) != 50:
        raise Gold10V2Error("pre-network PubMed rebind failed")
    if pubmed_saved.get("items") != pubmed_items:
        raise Gold10V2Error("saved PubMed corpus differs from reconstructed retained evidence")
    ozempic = _verified_bytes(
        M2_003_ROOT / "raw" / "dailymed" / f"sha256-{OZEMPIC_RAW_SHA256}.raw",
        expected_bytes=OZEMPIC_RAW_BYTES,
        expected_sha256=OZEMPIC_RAW_SHA256,
    )
    ozempic_derivative = derive_for_safe_parsing(ozempic)
    _validate_ozempic_derivative(ozempic, ozempic_derivative)
    parsed_ozempic = parse_source_native_spl_document(
        ozempic_derivative.payload,
        expected_setid=OZEMPIC_SETID,
        expected_spl_version=OZEMPIC_VERSION,
    )
    rebound_retrieval, rebound_structural = _section_records(
        parsed_ozempic,
        brand="OZEMPIC",
        raw_sha256=OZEMPIC_RAW_SHA256,
        transformation_chain_sha256=chain_digest,
        operation_id="reused-m2-003-dailymed-current-ozempic",
    )
    if sections != {
        "retrieval_items": rebound_retrieval,
        "structural_occurrences": rebound_structural,
    }:
        raise Gold10V2Error("saved OZEMPIC occurrences differ from rebound source evidence")
    return manifest


def _pre_network_review_binding(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = root / "pre-network-manifest.json"
    sidecar_path = manifest_path.with_suffix(".json.sha256")
    manifest_bytes = manifest_path.read_bytes()
    sidecar_bytes = sidecar_path.read_bytes()
    return {
        "pre_network_manifest": {
            "relative_path": "pre-network-manifest.json",
            "bytes": len(manifest_bytes),
            "sha256": _sha256(manifest_bytes),
            "sidecar_bytes": len(sidecar_bytes),
            "sidecar_sha256": _sha256(sidecar_bytes),
        },
        "source_state": manifest["source_state"],
        "artifact_inventory": manifest["artifact_inventory"],
    }


def _verify_review_record(
    root: Path, path: Path, expected_sha256: str, manifest: Mapping[str, Any]
) -> Mapping[str, Any]:
    data = _verified_bytes(
        path, expected_bytes=path.stat().st_size, expected_sha256=expected_sha256
    )
    try:
        review = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Gold10V2Error("pre-network review record is malformed") from error
    if not isinstance(review, dict):
        raise Gold10V2Error("pre-network review record must be an object")
    if review.get("status") != "PASS" or any(review.get(key) != 0 for key in ("p0", "p1", "p2")):
        raise Gold10V2Error("independent pre-network review is not PASS 0/0/0")
    if review.get("work_item") != "M2-005-MEDEVIDENCE-GOLD10-V2":
        raise Gold10V2Error("review record belongs to another work item")
    if review.get("schema_version") != f"{SCHEMA_VERSION}.pre-network-review.v1":
        raise Gold10V2Error("review record schema is not exact")
    if review.get("binding") != _pre_network_review_binding(root, manifest):
        raise Gold10V2Error("review record does not bind the exact pre-network candidate")
    return review


def _raw_header_values(headers: httpx.Headers, name: str) -> list[str]:
    values: list[str] = []
    for raw_name, raw_value in headers.raw:
        if raw_name.lower() != name.encode("ascii"):
            continue
        try:
            value = raw_value.decode("ascii", errors="strict")
        except UnicodeError as error:
            raise Gold10V2Error(f"{name} response header must be ASCII") from error
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise Gold10V2Error(f"{name} response header contains controls")
        values.append(value)
    return values


def _validated_headers(headers: httpx.Headers) -> tuple[dict[str, list[str]], int | None]:
    names = ("content-length", "transfer-encoding", "content-encoding", "location", "retry-after")
    evidence = {name: _raw_header_values(headers, name) for name in names}
    if any(len(values) > 1 for values in evidence.values()):
        raise Gold10V2Error("duplicate operational response header")
    if evidence["content-length"] and evidence["transfer-encoding"]:
        raise Gold10V2Error("Content-Length and Transfer-Encoding cannot coexist")
    if evidence["content-encoding"]:
        encoding = evidence["content-encoding"][0]
        if encoding != "identity":
            raise Gold10V2Error("Content-Encoding must exactly equal identity")
    declared: int | None = None
    if evidence["content-length"]:
        value = evidence["content-length"][0]
        if not value.isascii() or not value.isdecimal() or (value.startswith("0") and value != "0"):
            raise Gold10V2Error("Content-Length is not canonical")
        declared = int(value)
        if declared > MAX_PAYLOAD_BYTES:
            raise Gold10V2Error("declared MOUNJARO response exceeds the payload bound")
    return evidence, declared


def _retain_live_raw(root: Path, body: bytes) -> dict[str, Any]:
    digest = _sha256(body)
    path = root / "raw" / "dailymed" / f"sha256-{digest}.raw"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise Gold10V2Error("content-addressed MOUNJARO raw artifact conflicts")
    else:
        _write_binary_with_sidecar(path, body)
    sidecar = path.with_suffix(path.suffix + ".sha256")
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "bytes": len(body),
        "sha256": digest,
        "sidecar_relative_path": sidecar.relative_to(root).as_posix(),
        "sidecar_sha256": _sha256(sidecar.read_bytes()),
    }


def _safe_header_evidence(headers: httpx.Headers) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name, value in headers.raw:
        canonical_name = name.lower()
        if canonical_name not in OPERATIONAL_RESPONSE_HEADERS:
            continue
        records.append(
            {
                "name": canonical_name.decode("ascii"),
                "value_hex": value.hex(),
                "value_sha256": _sha256(value),
            }
        )
    return records


def _utc_evidence(utc_now: Callable[[], datetime]) -> str:
    observed = utc_now()
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise Gold10V2Error("evidence clock must return timezone-aware UTC")
    return observed.astimezone(UTC).isoformat()


def _persist_attempt_evidence(
    root: Path,
    attempts: Sequence[Mapping[str, Any]],
    *,
    terminal_status: str,
    failure: str | None = None,
) -> str:
    value: dict[str, Any] = {
        "schema_version": f"{SCHEMA_VERSION}.mounjaro-attempt-evidence.v1",
        "operation_id": "m2-005-dailymed-current-mounjaro",
        "logical_requests": 1,
        "maximum_attempts": 2,
        "maximum_redirects": 0,
        "attempt_count": len(attempts),
        "attempts": list(attempts),
        "terminal_status": terminal_status,
    }
    if failure is not None:
        value["failure_reason"] = failure
    return _write_json(root / "mounjaro-attempt-evidence.json", value)


def _request_mounjaro(
    root: Path,
    client: httpx.Client,
    *,
    monotonic: Callable[[], float],
    utc_now: Callable[[], datetime],
    sleep: Callable[[float], None],
    jitter: Callable[[], float],
) -> tuple[bytes, dict[str, Any]]:
    config = DailyMedConnectorConfig()
    request_contract = build_dailymed_request(DailyMedOperation.CURRENT_SPL, setid=MOUNJARO_SETID)
    if request_contract.url != MOUNJARO_URL:
        raise Gold10V2Error("MOUNJARO URL differs from the frozen typed request")
    operation_started = monotonic()
    attempts: list[dict[str, Any]] = []
    cumulative_new_bytes = 0
    for attempt in range(1, config.max_attempts + 1):
        remaining = config.total_deadline_seconds - (monotonic() - operation_started)
        if remaining <= 0:
            if attempts:
                _persist_attempt_evidence(
                    root,
                    attempts,
                    terminal_status="failed",
                    failure="MOUNJARO operation deadline expired before send",
                )
            raise Gold10V2Error("MOUNJARO operation deadline expired before send")
        timeout = httpx.Timeout(
            connect=min(config.connect_timeout_seconds, remaining),
            read=min(config.read_timeout_seconds, remaining),
            write=min(config.write_timeout_seconds, remaining),
            pool=min(config.pool_timeout_seconds, remaining),
        )
        response: httpx.Response | None = None
        request_url = request_contract.url
        try:
            request = client.build_request("GET", request_contract.url, timeout=timeout)
            validate_dailymed_url(str(request.url), request_contract)
            request_url = str(request.url)
            response = client.send(request, stream=True, follow_redirects=False)
            safe_headers = _safe_header_evidence(response.headers)
            headers: dict[str, list[str]] | None = None
            declared: int | None = None
            header_error: Gold10V2Error | None = None
            try:
                headers, declared = _validated_headers(response.headers)
            except Gold10V2Error as error:
                header_error = error
            chunks: list[bytes] = []
            received_from_transport = 0
            retained_this_attempt = 0
            read_error: Gold10V2Error | None = None
            raw_chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
            try:
                for chunk in raw_chunks:
                    received_from_transport += len(chunk)
                    remaining_retain = min(
                        config.max_payload_bytes - retained_this_attempt,
                        COMBINED_RAW_BYTE_CEILING
                        - M2_003_RECEIVED_RAW_BYTES
                        - cumulative_new_bytes,
                    )
                    if remaining_retain < 0:
                        remaining_retain = 0
                    accepted = chunk[:remaining_retain]
                    if accepted:
                        chunks.append(accepted)
                        retained_this_attempt += len(accepted)
                        cumulative_new_bytes += len(accepted)
                    if len(accepted) != len(chunk):
                        read_error = Gold10V2Error(
                            "MOUNJARO response exceeds the retained raw-byte ceiling"
                        )
                        break
                    if monotonic() - operation_started > config.total_deadline_seconds:
                        read_error = Gold10V2Error(
                            "MOUNJARO operation deadline expired during response"
                        )
                        break
            except (httpx.TimeoutException, httpx.TransportError) as error:
                read_error = Gold10V2Error("MOUNJARO response stream failed after partial receipt")
                read_error.__cause__ = error
            body = b"".join(chunks)
            raw = _retain_live_raw(root, body)
            record: dict[str, Any] = {
                "attempt": attempt,
                "request_url": request_url,
                "status_code": response.status_code,
                "observed_at_utc": _utc_evidence(utc_now),
                "raw_response_headers": safe_headers,
                "response_headers": headers,
                "raw": raw,
                "body_complete": read_error is None,
                "received_from_transport_bytes": received_from_transport,
                "retained_bytes": len(body),
            }
            if header_error is not None:
                record["header_validation_error"] = str(header_error)
            if read_error is not None:
                record["read_error"] = str(read_error)
            attempts.append(record)
            if read_error is not None:
                _persist_attempt_evidence(
                    root, attempts, terminal_status="failed", failure=str(read_error)
                )
                raise read_error
            if header_error is not None:
                _persist_attempt_evidence(
                    root, attempts, terminal_status="failed", failure=str(header_error)
                )
                raise header_error
            if declared is not None and declared != len(body):
                failure = "MOUNJARO body differs from Content-Length"
                record["body_complete"] = False
                record["read_error"] = failure
                _persist_attempt_evidence(root, attempts, terminal_status="failed", failure=failure)
                raise Gold10V2Error(failure)
            if response.status_code in REDIRECT_STATUS_CODES:
                failure = "MOUNJARO redirects are forbidden"
                _persist_attempt_evidence(root, attempts, terminal_status="failed", failure=failure)
                raise Gold10V2Error(failure)
            if response.status_code == 200:
                operation = {
                    "operation_id": "m2-005-dailymed-current-mounjaro",
                    "logical_requests": 1,
                    "attempt_count": len(attempts),
                    "redirect_count": 0,
                    "attempts": attempts,
                    "terminal_status": "completed",
                    "terminal_raw_sha256": _sha256(body),
                    "cumulative_prior_and_recovery_received_bytes": (
                        M2_003_RECEIVED_RAW_BYTES + cumulative_new_bytes
                    ),
                }
                operation["attempt_evidence_sha256"] = _persist_attempt_evidence(
                    root, attempts, terminal_status="completed"
                )
                return body, operation
            if response.status_code not in RETRYABLE_STATUS_CODES:
                failure = f"MOUNJARO returned terminal HTTP {response.status_code}"
                _persist_attempt_evidence(root, attempts, terminal_status="failed", failure=failure)
                raise Gold10V2Error(failure)
            if attempt == config.max_attempts:
                failure = "MOUNJARO retry budget exhausted"
                _persist_attempt_evidence(root, attempts, terminal_status="failed", failure=failure)
                raise Gold10V2Error(failure)
            assert headers is not None
            retry_values = headers["retry-after"]
            observed = utc_now()
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise Gold10V2Error("evidence clock must return timezone-aware UTC")
            now = observed.astimezone(UTC)
            parsed = parse_retry_after(
                retry_values[0] if retry_values else None,
                now=now,
                cap_seconds=config.max_retry_after_seconds,
            )
            delay = parsed if parsed is not None else retry_delay_seconds(attempt, jitter=jitter())
            if delay > config.total_deadline_seconds - (monotonic() - operation_started):
                _persist_attempt_evidence(
                    root,
                    attempts,
                    terminal_status="failed",
                    failure="MOUNJARO retry delay exceeds the deadline",
                )
                raise Gold10V2Error("MOUNJARO retry delay exceeds the deadline")
            record["retry"] = {"delay_seconds": delay, "used_retry_after": parsed is not None}
            _persist_attempt_evidence(root, attempts, terminal_status="retry_pending")
            sleep(delay)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            attempts.append(
                {
                    "attempt": attempt,
                    "request_url": request_contract.url,
                    "status_code": None,
                    "observed_at_utc": _utc_evidence(utc_now),
                    "raw_response_headers": [],
                    "response_headers": None,
                    "raw": None,
                    "body_complete": False,
                    "transport_error": type(error).__name__,
                }
            )
            if attempt == config.max_attempts:
                _persist_attempt_evidence(
                    root,
                    attempts,
                    terminal_status="failed",
                    failure="MOUNJARO transport retry budget exhausted",
                )
                raise Gold10V2Error("MOUNJARO transport retry budget exhausted") from error
            delay = retry_delay_seconds(attempt, jitter=jitter())
            if delay > config.total_deadline_seconds - (monotonic() - operation_started):
                _persist_attempt_evidence(
                    root,
                    attempts,
                    terminal_status="failed",
                    failure="MOUNJARO retry delay exceeds the deadline",
                )
                raise Gold10V2Error("MOUNJARO retry delay exceeds the deadline") from error
            attempts[-1]["retry"] = {"delay_seconds": delay, "used_retry_after": False}
            _persist_attempt_evidence(root, attempts, terminal_status="retry_pending")
            sleep(delay)
        finally:
            if response is not None:
                response.close()
    raise Gold10V2Error("bounded MOUNJARO request loop ended without a result")


def _blind_order(question_id: str, unit_id: str) -> str:
    return _sha256(f"{DATASET}\0{question_id}\0{unit_id}".encode())


def _validate_packet_blindness(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(token in key.casefold() for token in FORBIDDEN_BLIND_FIELDS):
                raise Gold10V2Error(f"blinded packet contains forbidden field {key!r}")
            _validate_packet_blindness(child)
    elif isinstance(value, list):
        for child in value:
            _validate_packet_blindness(child)


def _packet(items: Sequence[Mapping[str, Any]], corpus_sha256: str) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    for index, question in enumerate(QUESTIONS, start=1):
        question_id = f"Q{index}"
        candidates = sorted(
            items, key=lambda item: _blind_order(question_id, str(item["retrieval_unit_id"]))
        )
        questions.append(
            {
                "question_id": question_id,
                "question": question,
                "candidates": [
                    {
                        "candidate_ordinal": ordinal,
                        "retrieval_unit_id": item["retrieval_unit_id"],
                        "source": item["source"],
                        "stable_source_id": item["stable_source_id"],
                        "source_version_identity": item["source_version_identity"],
                        "source_locator": item["source_locator"],
                        "title": item["title"],
                        "text": item["text"],
                        "text_sha256": item["text_sha256"],
                        "owner_relevance_grade": None,
                        "owner_adjudication_notes": None,
                    }
                    for ordinal, item in enumerate(candidates, start=1)
                ],
            }
        )
    packet = {
        "schema_version": f"{SCHEMA_VERSION}.blinded-adjudication-packet.v1",
        "dataset": DATASET,
        "corpus_manifest_sha256": corpus_sha256,
        "authoritative_qrels_status": "not_created_owner_adjudication_required",
        "ordering": "sha256(dataset NUL question_id NUL retrieval_unit_id)",
        "questions": questions,
    }
    _validate_packet_blindness(packet)
    return packet


def run_live_recovery(
    output_root: str | Path,
    *,
    acknowledgement: str,
    review_record_path: str | Path,
    review_record_sha256: str,
    _client_factory: Callable[[], httpx.Client] | None = None,
    _monotonic: Callable[[], float] = time.monotonic,
    _utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    _sleep: Callable[[float], None] = time.sleep,
    _jitter: Callable[[], float] = lambda: random.uniform(0.0, 0.1),
) -> LiveRecoveryResult:
    """Consume the new one-shot authorization after all offline gates pass."""

    root = Path(output_root).resolve()
    if root != CANONICAL_OUTPUT_ROOT.resolve() and _client_factory is None:
        raise Gold10V2Error("live recovery requires the exact Owner-authorized evidence root")
    if acknowledgement != LIVE_ACKNOWLEDGEMENT:
        raise Gold10V2Error("exact live recovery acknowledgement is required")
    manifest = _load_and_verify_pre_network(root)
    _verify_review_record(root, Path(review_record_path), review_record_sha256, manifest)
    live_started = root / "live-started.json"
    if (
        live_started.exists()
        or (root / "live-stop.json").exists()
        or (root / "success.json").exists()
    ):
        raise Gold10V2Error("M2-005 MOUNJARO authorization has already been consumed")
    _write_json(
        live_started,
        {
            "schema_version": f"{SCHEMA_VERSION}.live-started.v1",
            "authorization": "new M2-005 authorization; M2-003 authority closed",
            "logical_operations_authorized": 1,
            "endpoint": MOUNJARO_URL,
            "status": "authorization_consumed_operation_beginning",
        },
    )
    client: httpx.Client | None = None
    try:
        client = (
            _client_factory()
            if _client_factory is not None
            else httpx.Client(follow_redirects=False)
        )
        body, operation = _request_mounjaro(
            root,
            client,
            monotonic=_monotonic,
            utc_now=_utc_now,
            sleep=_sleep,
            jitter=_jitter,
        )
        acquisition_sha = _write_json(root / "mounjaro-acquisition.json", operation)
        derivative = derive_for_safe_parsing(body)
        version = _observe_spl_identity(derivative.payload, MOUNJARO_SETID)
        parsed = parse_source_native_spl_document(
            derivative.payload,
            expected_setid=MOUNJARO_SETID,
            expected_spl_version=version,
        )
        derivative_path = (
            root / "derived" / "mounjaro" / f"sha256-{_sha256(derivative.payload)}.xml"
        )
        derivative_relative = derivative_path.relative_to(root).as_posix()
        _write_binary_with_sidecar(derivative_path, derivative.payload)
        chain = _transformation_chain(
            brand="MOUNJARO",
            raw_path=str(root / operation["attempts"][-1]["raw"]["relative_path"]),
            raw=body,
            derivative=derivative,
            final_derivative_relative_path=derivative_relative,
        )
        chain_sha = _write_json(root / "mounjaro-transformation-chain.json", chain)
        retrieval, structural = _section_records(
            parsed,
            brand="MOUNJARO",
            raw_sha256=_sha256(body),
            transformation_chain_sha256=chain_sha,
            operation_id="m2-005-dailymed-current-mounjaro",
        )
        if not retrieval:
            raise Gold10V2Error("MOUNJARO has no retrieval-eligible source-native sections")
        if {str(item["transformation_chain_sha256"]) for item in [*retrieval, *structural]} != {
            chain_sha
        }:
            raise Gold10V2Error("MOUNJARO occurrences do not bind retained chain bytes")
        _write_json(
            root / "mounjaro-source-native-sections.json",
            {"retrieval_items": retrieval, "structural_occurrences": structural},
        )
        # Rebind every saved offline input after the network operation and before freeze.
        _load_and_verify_pre_network(root)
        pubmed = _strict_json(root / "reused-pubmed-corpus.json")
        ozempic = _strict_json(root / "ozempic-source-native-sections.json")
        if not isinstance(pubmed, dict) or not isinstance(pubmed.get("items"), list):
            raise Gold10V2Error("reused PubMed corpus file is malformed")
        if not isinstance(ozempic, dict) or not isinstance(ozempic.get("retrieval_items"), list):
            raise Gold10V2Error("reused OZEMPIC section file is malformed")
        corpus_items = [*pubmed["items"], *ozempic["retrieval_items"], *retrieval]
        if len(pubmed["items"]) != 50 or len(ozempic["retrieval_items"]) != 12:
            raise Gold10V2Error("reused corpus inputs drifted before final freeze")
        corpus = {
            "schema_version": f"{SCHEMA_VERSION}.corpus-manifest.v1",
            "dataset": DATASET,
            "status": "frozen_before_adjudication",
            "counts": {
                "pubmed": 50,
                "ozempic_retrieval": 12,
                "mounjaro_retrieval": len(retrieval),
                "total": len(corpus_items),
            },
            "structural_provenance": {
                "ozempic": 1,
                "mounjaro": len(structural),
                "indexed": 0,
            },
            "items": corpus_items,
        }
        corpus_bytes = _canonical_json_bytes(corpus)
        corpus_sha = _sha256(corpus_bytes)
        packet = _packet(corpus_items, corpus_sha)
        packet_bytes = _canonical_json_bytes(packet)
        packet_sha = _sha256(packet_bytes)
        pending_root = root / ".finalization-pending"
        if pending_root.exists():
            raise Gold10V2Error("stale finalization transaction exists")
        pending_root.mkdir()
        try:
            _write_binary_with_sidecar(pending_root / "corpus-manifest.json", corpus_bytes)
            _write_binary_with_sidecar(
                pending_root / "blinded-adjudication-packet.json", packet_bytes
            )
            _atomic_write(root / "corpus-manifest.json", corpus_bytes)
            _atomic_write(
                root / "corpus-manifest.json.sha256",
                f"{corpus_sha}  corpus-manifest.json\n".encode("ascii"),
            )
            _atomic_write(root / "blinded-adjudication-packet.json", packet_bytes)
            _atomic_write(
                root / "blinded-adjudication-packet.json.sha256",
                f"{packet_sha}  blinded-adjudication-packet.json\n".encode("ascii"),
            )
        finally:
            for child in pending_root.glob("*"):
                with suppress(OSError):
                    child.unlink()
            with suppress(OSError):
                pending_root.rmdir()
        _write_json(
            root / "success.json",
            {
                "schema_version": f"{SCHEMA_VERSION}.success.v1",
                "status": "OWNER_DECISION_REQUIRED",
                "authoritative_qrels_status": "not_created",
                "logical_requests_new": 1,
                "http_attempts_new": operation["attempt_count"],
                "mounjaro_acquisition_sha256": acquisition_sha,
                "corpus_manifest_sha256": corpus_sha,
                "blinded_adjudication_packet_sha256": packet_sha,
            },
        )
        return LiveRecoveryResult(
            root,
            corpus_sha,
            packet_sha,
            len(retrieval),
            len(structural),
            int(operation["attempt_count"]),
        )
    except Exception as error:
        for generated in (
            root / "success.json",
            root / "success.json.sha256",
            root / "corpus-manifest.json",
            root / "corpus-manifest.json.sha256",
            root / "blinded-adjudication-packet.json",
            root / "blinded-adjudication-packet.json.sha256",
        ):
            with suppress(OSError):
                generated.unlink()
        attempt_path = root / "mounjaro-attempt-evidence.json"
        acquisition_path = root / "mounjaro-acquisition.json"
        evidence_links: dict[str, Any] = {}
        for name, path in (
            ("attempt_evidence", attempt_path),
            ("acquisition", acquisition_path),
        ):
            if path.exists():
                evidence_links[name] = {
                    "relative_path": path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path.read_bytes()),
                }
        _write_json(
            root / "live-stop.json",
            {
                "schema_version": f"{SCHEMA_VERSION}.live-stop.v1",
                "status": "STOP",
                "failure_type": type(error).__name__,
                "failure_reason": str(error),
                "authorization_consumed": True,
                "rerun_authorized": False,
                "evidence_links": evidence_links,
            },
        )
        raise
    finally:
        if client is not None:
            client.close()


__all__ = [
    "CANONICAL_OUTPUT_ROOT",
    "DATASET",
    "LIVE_ACKNOWLEDGEMENT",
    "M2_003_ROOT",
    "MOUNJARO_SETID",
    "MOUNJARO_URL",
    "DerivativeResult",
    "Gold10V2Error",
    "LiveRecoveryResult",
    "PreNetworkResult",
    "TransformationStep",
    "derive_for_safe_parsing",
    "prepare_pre_network",
    "reconstruct_retained_pubmed",
    "run_live_recovery",
]
