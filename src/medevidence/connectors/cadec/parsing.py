"""Strict, payload-free parsing for provider-gold CADEC annotation rows."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from medevidence.domain import TextSpanSegmentV1, derive_identity

MAX_ANNOTATION_LINES: Final = 62
MAX_ANNOTATION_ROW_BYTES: Final = 206
_ENTITY_ID: Final = re.compile(r"T[1-9][0-9]*\Z")
_NOTE_ID: Final = re.compile(r"#[1-9][0-9]*\Z")
_NORMALIZATION_ID: Final = re.compile(r"TT[1-9][0-9]*\Z")
_LOCATION_SUFFIX: Final = re.compile(
    r"(?P<label>.+?) (?P<locations>[0-9]+ [0-9]+(?:;[0-9]+ [0-9]+)*)\Z"
)


class CadecParseError(ValueError):
    """A CADEC text member or annotation row violated the frozen contract."""


@dataclass(frozen=True, slots=True)
class ParsedCadecAnnotation:
    """Payload-free metadata for one admitted provider row."""

    annotation_id: str
    physical_line: int
    spans: tuple[TextSpanSegmentV1, ...]
    surface_text_sha256: str
    raw_row_sha256: str
    reference_binding_limited: bool


@dataclass(frozen=True, slots=True)
class ParsedCadecMember:
    """Parsed rows and bounded diagnostics for one annotation member."""

    annotations: tuple[ParsedCadecAnnotation, ...]
    physical_line_count: int
    skipped_note_count: int
    reference_binding_limitation_count: int
    raw_out_of_order_transition_count: int
    has_raw_out_of_order_transition: bool


def decode_text_member(payload: bytes, *, member_path: str, member_sha256: str) -> str:
    """Decode strict UTF-8, except the one exact SHA-bound CP1252 member."""

    if member_path == "cadec/sct/LIPITOR.253.ann":
        if member_sha256 != "0deeb944656f03381dd8adb2914570f4759e70cd43c8a7c81a5c56cfefb0da96":
            raise CadecParseError("CP1252 exception member hash differs from the freeze")
        encoding = "cp1252"
    else:
        encoding = "utf-8"
    try:
        decoded = payload.decode(encoding, errors="strict")
    except UnicodeError as error:
        raise CadecParseError("CADEC member violates its exact encoding policy") from error
    if decoded.encode(encoding, errors="strict") != payload:
        raise CadecParseError("CADEC member does not round-trip through its exact encoding")
    return decoded


def parse_annotation_member(
    payload: bytes,
    *,
    document_text: str,
    document_id: str,
    layer: Literal["original", "meddra", "sct"],
    member_path: str,
    member_sha256: str,
    limited_row_identities: frozenset[tuple[str, int, str, str]],
) -> ParsedCadecMember:
    """Validate raw spans, then source-sort unchanged pairs for the domain contract.

    Raw ordering remains bound by the row hash and is counted explicitly. Sorting is
    deterministic domain normalization; offsets are never repaired or reinterpreted.
    """

    decoded = decode_text_member(payload, member_path=member_path, member_sha256=member_sha256)
    raw_lines = payload.splitlines()
    text_lines = decoded.splitlines()
    if len(raw_lines) != len(text_lines) or len(raw_lines) > MAX_ANNOTATION_LINES:
        raise CadecParseError("annotation member violates the physical-line bound")
    annotations: list[ParsedCadecAnnotation] = []
    skipped_notes = 0
    limited_count = 0
    raw_out_of_order_transitions = 0
    for physical_line, (raw_row, row) in enumerate(zip(raw_lines, text_lines, strict=True), 1):
        if len(raw_row) > MAX_ANNOTATION_ROW_BYTES:
            raise CadecParseError("annotation row violates the byte bound")
        fields = row.split("\t")
        if len(fields) != 3:
            raise CadecParseError("annotation row must have exactly three tab-separated fields")
        row_id, descriptor, supplied_surface = fields
        if layer == "original" and row_id.startswith("#"):
            if _NOTE_ID.fullmatch(row_id) is None:
                raise CadecParseError("annotator-note identifier is not canonical")
            skipped_notes += 1
            continue
        pattern = _ENTITY_ID if layer == "original" else _NORMALIZATION_ID
        if pattern.fullmatch(row_id) is None:
            raise CadecParseError("annotation row identifier is invalid for its layer")
        match = _LOCATION_SUFFIX.fullmatch(descriptor)
        if match is None or not match.group("label").strip():
            raise CadecParseError("annotation row lacks a right-anchored span suffix")
        raw_pairs: list[tuple[int, int]] = []
        for pair in match.group("locations").split(";"):
            start_text, end_text = pair.split(" ")
            if start_text != str(int(start_text)) or end_text != str(int(end_text)):
                raise CadecParseError("annotation offsets must be canonical ASCII integers")
            start, end = int(start_text), int(end_text)
            if not 0 <= start < end <= len(document_text):
                raise CadecParseError("annotation span is outside the document code-point bounds")
            raw_pairs.append((start, end))
        if len(set(raw_pairs)) != len(raw_pairs):
            raise CadecParseError("annotation row contains a duplicate span")
        raw_out_of_order_transitions += sum(
            left[0] > right[0] for left, right in pairwise(raw_pairs)
        )
        sorted_pairs = sorted(raw_pairs)
        if any(left[1] > right[0] for left, right in pairwise(sorted_pairs)):
            raise CadecParseError("annotation spans overlap after deterministic source ordering")
        try:
            spans = tuple(
                TextSpanSegmentV1(ordinal=ordinal, start_offset=start, end_offset=end)
                for ordinal, (start, end) in enumerate(sorted_pairs)
            )
        except ValueError as error:
            raise CadecParseError("annotation span violates the domain contract") from error
        raw_surface = " ".join(document_text[start:end] for start, end in raw_pairs)
        domain_surface = " ".join(
            document_text[span.start_offset : span.end_offset] for span in spans
        )
        raw_row_sha256 = hashlib.sha256(raw_row).hexdigest()
        identity = (member_path, physical_line, member_sha256, raw_row_sha256)
        limited = identity in limited_row_identities
        if (raw_surface != supplied_surface) != limited:
            raise CadecParseError(
                "reference-binding state differs from the exact limitation ledger"
            )
        if limited:
            limited_count += 1
        annotation_id = derive_identity(
            "cadec-provider-row",
            {
                "document_id": document_id,
                "layer": layer,
                "member_path": member_path,
                "physical_line": physical_line,
                "member_sha256": member_sha256,
                "raw_row_sha256": raw_row_sha256,
            },
        )
        annotations.append(
            ParsedCadecAnnotation(
                annotation_id=annotation_id,
                physical_line=physical_line,
                spans=spans,
                surface_text_sha256=f"sha256:{hashlib.sha256(domain_surface.encode('utf-8')).hexdigest()}",
                raw_row_sha256=raw_row_sha256,
                reference_binding_limited=limited,
            )
        )
    return ParsedCadecMember(
        annotations=tuple(annotations),
        physical_line_count=len(raw_lines),
        skipped_note_count=skipped_notes,
        reference_binding_limitation_count=limited_count,
        raw_out_of_order_transition_count=raw_out_of_order_transitions,
        has_raw_out_of_order_transition=raw_out_of_order_transitions > 0,
    )


__all__ = [
    "MAX_ANNOTATION_LINES",
    "MAX_ANNOTATION_ROW_BYTES",
    "CadecParseError",
    "ParsedCadecAnnotation",
    "ParsedCadecMember",
    "decode_text_member",
    "parse_annotation_member",
]
