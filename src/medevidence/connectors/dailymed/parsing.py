"""Fail-closed DailyMed JSON, SPL XML, and historical ZIP parsing."""

from __future__ import annotations

import io
import json
import re
import stat
import struct
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final
from xml.etree import ElementTree as etree

from defusedxml import ElementTree as defused_etree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from medevidence.domain.sources import (
    DOMAIN_MODEL_VALIDATION_ERROR,
    DailyMedSourceNativeSectionV1,
)

from .policy import (
    MAX_CANDIDATES,
    MAX_PAGES,
    MAX_PAYLOAD_BYTES,
    validate_setid,
    validate_spl_version,
)

HL7_NAMESPACE: Final = "urn:hl7-org:v3"
HL7_DOCUMENT: Final = f"{{{HL7_NAMESPACE}}}document"
HL7_SETID: Final = f"{{{HL7_NAMESPACE}}}setId"
HL7_VERSION: Final = f"{{{HL7_NAMESPACE}}}versionNumber"
HL7_COMPONENT: Final = f"{{{HL7_NAMESPACE}}}component"
HL7_STRUCTURED_BODY: Final = f"{{{HL7_NAMESPACE}}}structuredBody"
HL7_SECTION: Final = f"{{{HL7_NAMESPACE}}}section"
HL7_CODE: Final = f"{{{HL7_NAMESPACE}}}code"
HL7_TITLE: Final = f"{{{HL7_NAMESPACE}}}title"
HL7_TEXT: Final = f"{{{HL7_NAMESPACE}}}text"
XINCLUDE_NAMESPACE: Final = "http://www.w3.org/2001/XInclude"
XSLT_NAMESPACE: Final = "http://www.w3.org/1999/XSL/Transform"
XML_SCHEMA_NAMESPACE: Final = "http://www.w3.org/2001/XMLSchema"
XML_SCHEMA_INSTANCE_NAMESPACE: Final = "http://www.w3.org/2001/XMLSchema-instance"

MAXIMUM_DEPTH: Final = 64
MAXIMUM_ELEMENTS: Final = 50_000
MAXIMUM_ATTRIBUTES_PER_ELEMENT: Final = 64
MAXIMUM_DECODED_CHARACTERS: Final = 5_000_000
MAXIMUM_TEXT_NODE_CHARACTERS: Final = 262_144
MAXIMUM_LABEL_SECTIONS: Final = 128
MAXIMUM_ZIP_ENTRIES: Final = 128
MAXIMUM_PROVIDER_TOTAL: Final = 2_147_483_647

LOINC_SECTION_TITLES: Final[dict[str, str]] = {
    "34084-4": "FDA package insert Adverse reactions section",
    "43685-7": "FDA package insert Warnings and precautions section",
    "34066-1": "FDA package insert Boxed warning section",
    "34067-9": "FDA package insert Indications and usage section",
}
_DEVICE_NAMES: Final = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)
_SPL_VERSION_KEYS: Final = ("spl_version", "splVersion", "version_number", "versionNumber")
_SETID_KEYS: Final = ("setid", "set_id", "setId")


class DailyMedParseError(ValueError):
    """A malformed, unsafe, unbounded, or identity-drifted provider payload."""


@dataclass(frozen=True, slots=True)
class DailyMedDiscoverySummaryRecord:
    """Provider summary identity; never an authoritative selection candidate."""

    setid: str
    spl_versions: tuple[str, ...]


# Preserve the connector package's existing import name without granting the
# provider summary any enrichment or selection authority.
DailyMedCandidateRecord = DailyMedDiscoverySummaryRecord


@dataclass(frozen=True, slots=True)
class DailyMedCandidatePage:
    """Bounded candidate page with provider pagination metadata."""

    candidates: tuple[DailyMedDiscoverySummaryRecord, ...]
    page: int
    pagesize: int
    total: int
    next_page: int | None


@dataclass(frozen=True, slots=True)
class DailyMedHistoryRecord:
    """One exact SETID/version history item."""

    setid: str
    spl_version: str
    effective_date: date | None
    published_date: date | None
    marketing_state: str


@dataclass(frozen=True, slots=True)
class DailyMedHistoryPage:
    """Bounded history page."""

    records: tuple[DailyMedHistoryRecord, ...]
    page: int
    pagesize: int
    total: int
    next_page: int | None


@dataclass(frozen=True, slots=True)
class ParsedSplSection:
    """Canonical requested label section with exact text span and XML path."""

    section_code: str
    title: str
    section_ordinal: int
    parent_section_ordinal: int | None
    xml_path: str
    text: str
    text_start: int
    text_end: int


@dataclass(frozen=True, slots=True)
class ParsedSplDocument:
    """Identity-validated SPL document and canonical allowlisted sections."""

    setid: str
    spl_version: str
    sections: tuple[ParsedSplSection, ...]
    canonical_text: str
    source_member_name: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedSourceNativeSplDocument:
    """Identity-validated SPL with every allowlisted source occurrence retained."""

    setid: str
    spl_version: str
    sections: tuple[DailyMedSourceNativeSectionV1, ...]


def parse_candidate_page(
    payload: bytes, *, expected_page: int = 1, expected_pagesize: int | None = None
) -> DailyMedCandidatePage:
    """Parse a bounded provider discovery page into non-authoritative summaries."""

    root = _json_object(payload)
    rows = _list_from_keys(root, ("data", "results", "spls"))
    if len(rows) > MAX_CANDIDATES:
        raise DailyMedParseError("candidate page exceeds the 100-candidate bound")
    candidates = tuple(_candidate(row) for row in rows)
    page, pagesize, total, next_page = _pagination(
        root, len(rows), expected_page, expected_pagesize
    )
    return DailyMedCandidatePage(candidates, page, pagesize, total, next_page)


def parse_history_page(
    payload: bytes,
    *,
    expected_setid: str,
    expected_page: int = 1,
    expected_pagesize: int | None = None,
) -> DailyMedHistoryPage:
    """Parse bounded history JSON with exact response SETID parity."""

    canonical_setid = validate_setid(expected_setid)
    root = _json_object(payload)
    rows = _list_from_keys(root, ("data", "results", "history", "spls"))
    if len(rows) > MAX_CANDIDATES:
        raise DailyMedParseError("history page exceeds the 100-record bound")
    records: list[DailyMedHistoryRecord] = []
    for raw in rows:
        row = _mapping(raw, "history record")
        row_setid = validate_setid(_required_alias(row, _SETID_KEYS, "SETID"))
        if row_setid != canonical_setid:
            raise DailyMedParseError("history response SETID differs from the typed request")
        records.append(
            DailyMedHistoryRecord(
                setid=row_setid,
                spl_version=validate_spl_version(
                    _required_alias(row, _SPL_VERSION_KEYS, "SPL version")
                ),
                effective_date=_optional_date(row, ("effective_date", "effectiveDate")),
                published_date=_optional_date(row, ("published_date", "publishedDate")),
                marketing_state=_marketing_state(row),
            )
        )
    page, pagesize, total, next_page = _pagination(
        root, len(records), expected_page, expected_pagesize
    )
    return DailyMedHistoryPage(tuple(records), page, pagesize, total, next_page)


def parse_spl_document(
    payload: bytes,
    *,
    expected_setid: str,
    expected_spl_version: str,
    source_member_name: str | None = None,
) -> ParsedSplDocument:
    """Parse one safe bounded HL7 SPL document with exact selected identity."""

    canonical_setid = validate_setid(expected_setid)
    canonical_version = validate_spl_version(expected_spl_version)
    root = _bounded_xml_root(payload)
    if root.tag != HL7_DOCUMENT:
        raise DailyMedParseError("SPL root must equal {urn:hl7-org:v3}document")
    setid = _direct_identity(root, HL7_SETID, "root", validate_setid, "SETID")
    version = _direct_identity(root, HL7_VERSION, "value", validate_spl_version, "SPL version")
    if (setid, version) != (canonical_setid, canonical_version):
        raise DailyMedParseError("parsed SPL identity differs from the selected SETID/version")

    structured_bodies = root.findall(f"./{HL7_COMPONENT}/{HL7_STRUCTURED_BODY}")
    if len(structured_bodies) > 1:
        raise DailyMedParseError("SPL contains duplicate direct structured bodies")
    retained: list[tuple[str, str, str, int, int | None]] = []
    retained_ordinals: dict[int, int] = {}
    for element, path, ordinal, parent in _section_elements(root):
        codes = element.findall(f"./{HL7_CODE}")
        if len(codes) != 1:
            continue
        code = codes[0].attrib.get("code")
        code_system = codes[0].attrib.get("codeSystem")
        if code not in LOINC_SECTION_TITLES or code_system != "2.16.840.1.113883.6.1":
            continue
        displayed = _single_child_text(element, HL7_TITLE, required=False)
        if displayed is not None and displayed != LOINC_SECTION_TITLES[code]:
            raise DailyMedParseError("LOINC section code/title pair drifted from release 2.82")
        text = _single_child_text(element, HL7_TEXT, required=True)
        if text is None:
            raise RuntimeError("required section text unexpectedly resolved to None")
        parent_ordinal = retained_ordinals.get(id(parent)) if parent is not None else None
        retained.append((code, text, path, ordinal, parent_ordinal))
        retained_ordinals[id(element)] = ordinal
    if len(retained) > MAXIMUM_LABEL_SECTIONS:
        raise DailyMedParseError("SPL exceeds the retained-section bound")
    if len({code for code, *_ in retained}) != len(retained):
        raise DailyMedParseError("SPL repeats an allowlisted LOINC section")

    canonical_parts: list[str] = []
    sections: list[ParsedSplSection] = []
    cursor = 0
    for code, text, path, ordinal, parent_ordinal in retained:
        if canonical_parts:
            canonical_parts.append("\n")
            cursor += 1
        start = cursor
        canonical_parts.append(text)
        cursor += len(text)
        sections.append(
            ParsedSplSection(
                section_code=code,
                title=LOINC_SECTION_TITLES[code],
                section_ordinal=ordinal,
                parent_section_ordinal=parent_ordinal,
                xml_path=path,
                text=text,
                text_start=start,
                text_end=cursor,
            )
        )
    return ParsedSplDocument(
        setid=setid,
        spl_version=version,
        sections=tuple(sections),
        canonical_text="".join(canonical_parts),
        source_member_name=source_member_name,
    )


def parse_source_native_spl_document(
    payload: bytes,
    *,
    expected_setid: str,
    expected_spl_version: str,
) -> ParsedSourceNativeSplDocument:
    """Parse allowlisted SPL occurrences while preserving provider-native structure."""

    canonical_setid = validate_setid(expected_setid)
    canonical_version = validate_spl_version(expected_spl_version)
    root = _bounded_xml_root(payload)
    if root.tag != HL7_DOCUMENT:
        raise DailyMedParseError("SPL root must equal {urn:hl7-org:v3}document")
    setid = _direct_identity(root, HL7_SETID, "root", validate_setid, "SETID")
    version = _direct_identity(root, HL7_VERSION, "value", validate_spl_version, "SPL version")
    if (setid, version) != (canonical_setid, canonical_version):
        raise DailyMedParseError("parsed SPL identity differs from the selected SETID/version")

    structured_bodies = root.findall(f"./{HL7_COMPONENT}/{HL7_STRUCTURED_BODY}")
    if len(structured_bodies) > 1:
        raise DailyMedParseError("SPL contains duplicate direct structured bodies")
    source_sections = _section_elements(root)
    source_ordinals = {id(element): ordinal for element, _, ordinal, _ in source_sections}
    retained: list[DailyMedSourceNativeSectionV1] = []
    for element, path, ordinal, parent in source_sections:
        codes = element.findall(f"./{HL7_CODE}")
        if len(codes) != 1:
            continue
        code = codes[0].attrib.get("code")
        code_system = codes[0].attrib.get("codeSystem")
        if code not in LOINC_SECTION_TITLES or code_system != "2.16.840.1.113883.6.1":
            continue
        provider_title = _source_native_child_text(element, HL7_TITLE, required=True)
        if provider_title is None:
            raise RuntimeError("required provider title unexpectedly resolved to None")
        extracted_text = _source_native_child_text(element, HL7_TEXT, required=False) or ""
        parent_ordinal = source_ordinals[id(parent)] if parent is not None else None
        try:
            section = DailyMedSourceNativeSectionV1.create(
                setid=setid,
                spl_version=version,
                code_system_oid=code_system,
                section_code=code,
                normalized_section_name=LOINC_SECTION_TITLES[code],
                provider_title=provider_title,
                section_ordinal=ordinal,
                parent_section_ordinal=parent_ordinal,
                xml_path=path,
                extracted_text=extracted_text,
            )
        except DOMAIN_MODEL_VALIDATION_ERROR as error:
            raise DailyMedParseError(
                "source-native section violates the bounded domain contract"
            ) from error
        retained.append(section)
    if len(retained) > MAXIMUM_LABEL_SECTIONS:
        raise DailyMedParseError("SPL exceeds the retained-section bound")
    return ParsedSourceNativeSplDocument(
        setid=setid,
        spl_version=version,
        sections=tuple(retained),
    )


def parse_historical_zip(
    payload: bytes,
    *,
    expected_setid: str,
    expected_spl_version: str,
) -> ParsedSplDocument:
    """Validate a complete ZIP inventory and parse its sole HL7 SPL member in memory."""

    if len(payload) > MAX_PAYLOAD_BYTES:
        raise DailyMedParseError("compressed historical ZIP exceeds the frozen byte bound")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        entries = archive.infolist()
    except (zipfile.BadZipFile, OSError) as error:
        raise DailyMedParseError("historical payload is not a valid ZIP archive") from error
    if len(entries) > MAXIMUM_ZIP_ENTRIES:
        raise DailyMedParseError("historical ZIP exceeds the central-directory entry bound")
    raw_names = _raw_central_names(payload)
    if len(raw_names) != len(entries):
        raise DailyMedParseError("ZIP central-directory inventory count is inconsistent")

    normalized_names: set[str] = set()
    total_uncompressed = 0
    xml_entries: list[tuple[zipfile.ZipInfo, str]] = []
    for info, raw_name in zip(entries, raw_names, strict=True):
        normalized = _validated_member_name(raw_name, is_directory=info.is_dir())
        if normalized != info.filename:
            raise DailyMedParseError("ZIP library filename differs from the validated raw name")
        duplicate_key = normalized.removesuffix("/")
        if duplicate_key in normalized_names:
            raise DailyMedParseError("historical ZIP contains duplicate normalized member names")
        normalized_names.add(duplicate_key)
        if info.flag_bits & 0x1:
            raise DailyMedParseError("encrypted ZIP entries are forbidden")
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise DailyMedParseError("symlink, device, and special ZIP entries are forbidden")
        if info.file_size > MAX_PAYLOAD_BYTES:
            raise DailyMedParseError("ZIP member exceeds the per-member byte bound")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_PAYLOAD_BYTES:
            raise DailyMedParseError("ZIP exceeds the cumulative uncompressed byte bound")
        if not info.is_dir() and normalized.casefold().endswith(".xml"):
            xml_entries.append((info, normalized))

    candidates: list[ParsedSplDocument] = []
    read_total = 0
    for info, normalized in xml_entries:
        body = _read_zip_member(archive, info)
        read_total += len(body)
        if read_total > MAX_PAYLOAD_BYTES:
            raise DailyMedParseError("ZIP exceeded the byte bound while reading members")
        try:
            parsed = parse_spl_document(
                body,
                expected_setid=expected_setid,
                expected_spl_version=expected_spl_version,
                source_member_name=normalized,
            )
        except DailyMedParseError as error:
            try:
                root = _bounded_xml_root(body)
            except DailyMedParseError:
                raise DailyMedParseError("ZIP contains malformed or unclassifiable XML") from error
            if root.tag == HL7_DOCUMENT:
                raise
            continue
        candidates.append(parsed)
    archive.close()
    if len(candidates) != 1:
        raise DailyMedParseError("historical ZIP must contain exactly one HL7 SPL document")
    return candidates[0]


def _json_object(payload: bytes) -> Mapping[str, object]:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise DailyMedParseError("JSON payload exceeds the frozen byte bound")
    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(decoded)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DailyMedParseError("DailyMed JSON must be valid UTF-8 JSON") from error
    return _mapping(value, "JSON root")


def _candidate(value: object) -> DailyMedDiscoverySummaryRecord:
    row = _mapping(value, "candidate")
    return DailyMedDiscoverySummaryRecord(
        setid=validate_setid(_required_alias(row, _SETID_KEYS, "SETID")),
        spl_versions=_versions(row),
    )


def _versions(row: Mapping[str, object]) -> tuple[str, ...]:
    raw = _first(row, ("spl_versions", "versions", *_SPL_VERSION_KEYS))
    values = raw if isinstance(raw, list) else [raw]
    versions = tuple(sorted({_discovery_version(value) for value in values}, key=int))
    if not versions:
        raise DailyMedParseError("candidate requires at least one SPL version")
    return versions


def _discovery_version(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise DailyMedParseError("SPL version must be positive canonical text or an integer")
    if isinstance(value, int):
        if value <= 0:
            raise DailyMedParseError("SPL version integer must be positive")
        value = str(value)
    try:
        return validate_spl_version(value)
    except ValueError as error:
        raise DailyMedParseError("SPL version is not a positive canonical integer") from error


def _marketing_state(row: Mapping[str, object]) -> str:
    value = _optional_text(row, ("marketing_state", "marketingState")) or "unknown"
    normalized = value.casefold()
    if normalized not in {"active", "archived", "unknown"}:
        raise DailyMedParseError("marketing state must be active, archived, or unknown")
    return normalized


def _pagination(
    root: Mapping[str, object],
    observed: int,
    expected_page: int,
    expected_pagesize: int | None,
) -> tuple[int, int, int, int | None]:
    metadata_keys = [name for name in ("metadata", "meta") if name in root]
    if len(metadata_keys) > 1:
        raise DailyMedParseError("duplicate pagination metadata aliases are forbidden")
    metadata_value = root[metadata_keys[0]] if metadata_keys else root
    metadata = _mapping(metadata_value, "pagination metadata")
    page = _bounded_int(
        _pagination_value(metadata, ("page", "current_page"), expected_page),
        1,
        MAX_PAGES,
        "page",
    )
    if page != expected_page:
        raise DailyMedParseError("response page differs from the typed request")
    pagesize = _bounded_int(
        _pagination_value(metadata, ("pagesize", "page_size", "per_page"), max(observed, 1)),
        1,
        MAX_CANDIDATES,
        "pagesize",
    )
    if expected_pagesize is not None and pagesize != expected_pagesize:
        raise DailyMedParseError("response page size differs from the typed request")
    total = _bounded_int(
        _pagination_value(metadata, ("total", "total_elements", "total_records"), observed),
        0,
        MAXIMUM_PROVIDER_TOTAL,
        "total",
    )
    total_pages = (total + pagesize - 1) // pagesize if total else 1
    if observed > pagesize or observed > total:
        raise DailyMedParseError("observed rows contradict pagination size or total")
    if page > total_pages:
        raise DailyMedParseError("response page exceeds the provider total")
    expected_observed = pagesize if page < total_pages else total - ((page - 1) * pagesize)
    if observed != expected_observed:
        raise DailyMedParseError("observed rows contradict the provider page tuple")
    next_page = page + 1 if page < total_pages else None
    return page, pagesize, total, next_page


def _pagination_value(
    metadata: Mapping[str, object], aliases: Sequence[str], default: int
) -> object:
    present = [alias for alias in aliases if alias in metadata]
    if len(present) > 1:
        raise DailyMedParseError(f"duplicate aliases are forbidden: {present!r}")
    return default if not present else metadata[present[0]]


def _bounded_xml_root(payload: bytes) -> etree.Element:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise DailyMedParseError("XML payload exceeds the frozen byte bound")
    upper = payload.upper()
    for token in (b"<!DOCTYPE", b"<!ENTITY", b"<?XML-STYLESHEET"):
        if token in upper:
            raise DailyMedParseError("XML contains a forbidden resource or transform construct")
    try:
        root = defused_etree.fromstring(
            payload,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (DefusedXmlException, etree.ParseError, ValueError) as error:
        raise DailyMedParseError(
            "SPL XML is malformed or contains a forbidden construct"
        ) from error
    elements = 0
    decoded = 0
    stack: list[tuple[etree.Element, int]] = [(root, 1)]
    while stack:
        element, depth = stack.pop()
        elements += 1
        if elements > MAXIMUM_ELEMENTS or depth > MAXIMUM_DEPTH:
            raise DailyMedParseError("XML exceeds element or depth bounds")
        if len(element.attrib) > MAXIMUM_ATTRIBUTES_PER_ELEMENT:
            raise DailyMedParseError("XML element exceeds the attribute bound")
        namespace, _ = _expanded_name(element.tag)
        if namespace in {XINCLUDE_NAMESPACE, XSLT_NAMESPACE, XML_SCHEMA_NAMESPACE}:
            raise DailyMedParseError("XML contains a forbidden expanded-name construct")
        for name, attribute_value in element.attrib.items():
            attribute_namespace, local_name = _expanded_name(name)
            if attribute_namespace == XML_SCHEMA_INSTANCE_NAMESPACE and local_name in {
                "schemaLocation",
                "noNamespaceSchemaLocation",
            }:
                raise DailyMedParseError("XML contains forbidden schema resolution metadata")
            decoded += len(attribute_value)
            if decoded > MAXIMUM_DECODED_CHARACTERS:
                raise DailyMedParseError("XML exceeds the total decoded-character bound")
        for value in (element.text, element.tail):
            if value is not None:
                if len(value) > MAXIMUM_TEXT_NODE_CHARACTERS:
                    raise DailyMedParseError("XML text node exceeds the character bound")
                decoded += len(value)
                if decoded > MAXIMUM_DECODED_CHARACTERS:
                    raise DailyMedParseError("XML exceeds the total decoded-character bound")
        stack.extend((child, depth + 1) for child in reversed(list(element)))
    if not isinstance(root, etree.Element):
        raise DailyMedParseError("SPL parser did not return an XML element")
    return root


def _expanded_name(name: str) -> tuple[str | None, str]:
    if not isinstance(name, str) or not name:
        raise DailyMedParseError("XML expanded name is not classifiable")
    if name.startswith("{"):
        namespace, separator, local_name = name[1:].partition("}")
        if not separator or not namespace or not local_name:
            raise DailyMedParseError("XML expanded name is malformed")
        return namespace, local_name
    return None, name


def _direct_identity(
    root: etree.Element,
    tag: str,
    attribute: str,
    validator: Callable[[str], str],
    label: str,
) -> str:
    elements = root.findall(f"./{tag}")
    if len(elements) != 1:
        raise DailyMedParseError(f"SPL requires exactly one direct HL7 {label} selector")
    element = elements[0]
    if attribute not in element.attrib:
        raise DailyMedParseError(f"SPL {label} selector lacks its unqualified attribute")
    value = element.attrib[attribute]
    try:
        return validator(value)
    except ValueError as error:
        raise DailyMedParseError(f"SPL {label} selector is noncanonical") from error


def _section_elements(
    root: etree.Element,
) -> list[tuple[etree.Element, str, int, etree.Element | None]]:
    result: list[tuple[etree.Element, str, int, etree.Element | None]] = []
    stack: list[tuple[etree.Element, str, etree.Element | None]] = [(root, "/document", None)]
    while stack:
        element, path, parent_section = stack.pop()
        current_parent = parent_section
        if element.tag == HL7_SECTION:
            result.append((element, path, len(result), parent_section))
            current_parent = element
        children = list(element)
        positions: dict[str, int] = {}
        child_paths: list[str] = []
        for child in children:
            local_name = _local_name(child.tag)
            positions[local_name] = positions.get(local_name, 0) + 1
            child_paths.append(f"{path}/{local_name}[{positions[local_name]}]")
        stack.extend(
            (child, child_path, current_parent)
            for child, child_path in reversed(list(zip(children, child_paths, strict=True)))
        )
    return result


def _local_name(expanded_name: str) -> str:
    if not isinstance(expanded_name, str) or not expanded_name:
        raise DailyMedParseError("XML element name is not classifiable")
    return expanded_name.rsplit("}", 1)[-1]


def _single_child_text(element: etree.Element, tag: str, *, required: bool) -> str | None:
    children = element.findall(f"./{tag}")
    if len(children) > 1 or (required and len(children) != 1):
        raise DailyMedParseError("section child cardinality is invalid")
    if not children:
        return None
    text = _canonical_element_text(children[0])
    if required and not text:
        raise DailyMedParseError("section text must not be blank")
    return text or None


def _source_native_child_text(element: etree.Element, tag: str, *, required: bool) -> str | None:
    """Extract one direct child without rewriting provider display text."""

    children = element.findall(f"./{tag}")
    if len(children) > 1 or (required and len(children) != 1):
        raise DailyMedParseError("section child cardinality is invalid")
    if not children:
        return None
    text = "".join(children[0].itertext())
    if required and not text.strip():
        raise DailyMedParseError("section child text must not be blank")
    return text


def _canonical_element_text(element: etree.Element) -> str:
    pieces = [piece for piece in element.itertext()]
    text = " ".join(" ".join(pieces).split())
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _validated_member_name(name: str, *, is_directory: bool) -> str:
    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise DailyMedParseError("ZIP member name contains C0/DEL or is empty")
    if "\\" in name or name.startswith(("/", "//")) or re.match(r"[A-Za-z]:", name):
        raise DailyMedParseError(
            "ZIP member name is absolute, UNC, drive-qualified, or uses backslash"
        )
    candidate = name[:-1] if is_directory and name.endswith("/") else name
    segments = candidate.split("/")
    if not segments or any(segment in {"", ".", ".."} for segment in segments):
        raise DailyMedParseError("ZIP member contains an empty, dot, or traversal segment")
    for segment in segments:
        stem = segment.rstrip(" .").split(".", 1)[0].casefold()
        if stem in _DEVICE_NAMES:
            raise DailyMedParseError("ZIP member contains a Windows device name")
    return "/".join(segments) + ("/" if is_directory else "")


def _raw_central_names(payload: bytes) -> tuple[str, ...]:
    """Read exact central-directory filename bytes before platform normalization."""

    eocd = payload.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(payload):
        raise DailyMedParseError("ZIP end-of-central-directory record is missing")
    disk_number, central_disk, disk_entries, total_entries = struct.unpack_from(
        "<HHHH", payload, eocd + 4
    )
    central_size, central_offset = struct.unpack_from("<II", payload, eocd + 12)
    if disk_number or central_disk or disk_entries != total_entries:
        raise DailyMedParseError("multi-disk or inconsistent ZIP archives are forbidden")
    if total_entries > MAXIMUM_ZIP_ENTRIES:
        raise DailyMedParseError("historical ZIP exceeds the entry bound")
    end = central_offset + central_size
    if central_offset < 0 or end > eocd:
        raise DailyMedParseError("ZIP central-directory bounds are inconsistent")
    cursor = central_offset
    names: list[str] = []
    for _ in range(total_entries):
        if cursor + 46 > end or payload[cursor : cursor + 4] != b"PK\x01\x02":
            raise DailyMedParseError("ZIP central-directory entry is malformed")
        flags = struct.unpack_from("<H", payload, cursor + 8)[0]
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", payload, cursor + 28)
        name_start = cursor + 46
        name_end = name_start + name_length
        next_cursor = name_end + extra_length + comment_length
        if name_end > end or next_cursor > end:
            raise DailyMedParseError("ZIP central-directory name exceeds its declared bounds")
        encoding = "utf-8" if flags & 0x800 else "cp437"
        try:
            names.append(payload[name_start:name_end].decode(encoding, errors="strict"))
        except UnicodeError as error:
            raise DailyMedParseError("ZIP member name cannot be decoded exactly") from error
        cursor = next_cursor
    if cursor != end:
        raise DailyMedParseError("ZIP central-directory contains unaccounted bytes")
    return tuple(names)


def _read_zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    try:
        with archive.open(info, "r") as stream:
            while chunk := stream.read(65_536):
                observed += len(chunk)
                if observed > MAX_PAYLOAD_BYTES:
                    raise DailyMedParseError("ZIP member exceeded the byte bound while reading")
                chunks.append(chunk)
    except (RuntimeError, OSError, zipfile.BadZipFile) as error:
        raise DailyMedParseError("ZIP member could not be read safely") from error
    if observed != info.file_size:
        raise DailyMedParseError("ZIP central-directory size does not match the read member")
    return b"".join(chunks)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DailyMedParseError(f"{label} must be an object with string keys")
    return value


def _list_from_keys(root: Mapping[str, object], aliases: Sequence[str]) -> list[object]:
    value = _first(root, aliases)
    if not isinstance(value, list):
        raise DailyMedParseError("DailyMed result collection must be an array")
    return value


def _first(
    row: Mapping[str, object], aliases: Sequence[str], *, required: bool = True
) -> object | None:
    present = [alias for alias in aliases if alias in row]
    if len(present) > 1:
        raise DailyMedParseError(f"duplicate aliases are forbidden: {present!r}")
    if not present:
        if required:
            raise DailyMedParseError(f"required field is missing: {aliases[0]}")
        return None
    return row[present[0]]


def _required_alias(row: Mapping[str, object], aliases: Sequence[str], label: str) -> str:
    return _text(label, _first(row, aliases))


def _optional_text(row: Mapping[str, object], aliases: Sequence[str]) -> str | None:
    value = _first(row, aliases, required=False)
    return None if value is None else _text(aliases[0], value)


def _text(label: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DailyMedParseError(f"{label} must be exact nonblank text")
    if any(ord(char) < 32 and char not in "\t\n\r" for char in value) or "\x7f" in value:
        raise DailyMedParseError(f"{label} contains forbidden control text")
    return value


def _optional_date(row: Mapping[str, object], aliases: Sequence[str]) -> date | None:
    value = _optional_text(row, aliases)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise DailyMedParseError(f"{aliases[0]} must be an ISO calendar date") from error


def _bounded_int(value: object, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DailyMedParseError(f"{label} must be an integer")
    text = str(value)
    if not text.isascii() or not text.isdigit() or str(int(text)) != text:
        raise DailyMedParseError(f"{label} must be a canonical ASCII integer")
    number = int(text)
    if not minimum <= number <= maximum:
        raise DailyMedParseError(f"{label} is outside the frozen bound")
    return number


__all__ = [
    "LOINC_SECTION_TITLES",
    "DailyMedCandidatePage",
    "DailyMedCandidateRecord",
    "DailyMedDiscoverySummaryRecord",
    "DailyMedHistoryPage",
    "DailyMedHistoryRecord",
    "DailyMedParseError",
    "ParsedSourceNativeSplDocument",
    "ParsedSplDocument",
    "ParsedSplSection",
    "parse_candidate_page",
    "parse_historical_zip",
    "parse_history_page",
    "parse_source_native_spl_document",
    "parse_spl_document",
]
