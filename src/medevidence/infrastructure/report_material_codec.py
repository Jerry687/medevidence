"""Closed, deterministic JSON codec for rebuilding verified report material."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import TypeAdapter, ValidationError

from medevidence.domain import canonical_json
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import CanonicalReportRequest
from medevidence.tools.report_validation_source_bindings_v3 import TerminalTaskInputV3

_MAX_MATERIAL_BYTES = 16_777_216
_MAX_NODES = 100_000
_MAX_DEPTH = 32
_REQUEST_ADAPTER: TypeAdapter[CanonicalReportRequest] = TypeAdapter(CanonicalReportRequest)
_V3_TASK_ADAPTER: TypeAdapter[TerminalTaskInputV3] = TypeAdapter(TerminalTaskInputV3)
_PROVENANCE_ADAPTER: TypeAdapter[tuple[EvidenceProvenanceV1, ...]] = TypeAdapter(
    tuple[EvidenceProvenanceV1, ...]
)


class ReportMaterialError(ValueError):
    """Stored report material is outside the one closed typed JSON contract."""


def _plain(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ReportMaterialError("material timestamp must be UTC")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if type(value) is tuple:
        return [_plain(item) for item in value]
    if type(value) is frozenset:
        return sorted((_plain(item) for item in value), key=canonical_json)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    raise ReportMaterialError("material contains a value outside the closed schema")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportMaterialError("material contains duplicate JSON keys")
        result[key] = value
    return result


def _bounded_json(value: str) -> object:
    if type(value) is not str or len(value.encode("utf-8")) > _MAX_MATERIAL_BYTES:
        raise ReportMaterialError("material exceeds the JSON byte bound")
    try:
        parsed = json.loads(value, object_pairs_hook=_unique_object)
    except ReportMaterialError:
        raise
    except (TypeError, ValueError, RecursionError) as error:
        raise ReportMaterialError("material is not closed JSON") from error
    stack: list[tuple[object, int]] = [(parsed, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise ReportMaterialError("material exceeds JSON structure bounds")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in (str, int, bool):
            raise ReportMaterialError("material contains a noncanonical scalar")
    return parsed


def _encode(value: object) -> str:
    result = canonical_json(_plain(value))
    _bounded_json(result)
    return result


def _decode[T](raw: str, adapter: TypeAdapter[T]) -> T:
    parsed = _bounded_json(raw)
    try:
        rebuilt = adapter.validate_json(raw, strict=True)
    except ValidationError as error:
        raise ReportMaterialError("material violates the closed typed schema") from error
    if canonical_json(parsed) != _encode(rebuilt):
        raise ReportMaterialError("material differs from canonical typed reconstruction")
    return rebuilt


def encode_report_request(request: CanonicalReportRequest) -> str:
    if type(request) is not CanonicalReportRequest:
        raise ReportMaterialError("request must use the exact canonical type")
    raw = _encode(request)
    decode_report_request(raw)
    return raw


def decode_report_request(raw: str) -> CanonicalReportRequest:
    parsed = _bounded_json(raw)
    if type(parsed) is not dict or type(parsed.get("tasks")) is not list:
        raise ReportMaterialError("material request task shape is invalid")
    try:
        rebuilt = _REQUEST_ADAPTER.validate_json(raw, strict=True)
        tasks = parsed["tasks"]
        if any(type(task) is dict and "operation_acquisition_ids" in task for task in tasks):
            if not all(
                type(task) is dict
                and {"operation_acquisition_ids", "evidence_child_bindings"} <= set(task)
                for task in tasks
            ):
                raise ReportMaterialError("material mixes legacy and child-bound tasks")
            rebuilt = replace(
                rebuilt,
                tasks=tuple(
                    _V3_TASK_ADAPTER.validate_json(canonical_json(task), strict=True)
                    for task in tasks
                ),
            )
    except ValidationError as error:
        raise ReportMaterialError("material violates the closed typed schema") from error
    if canonical_json(parsed) != _encode(rebuilt):
        raise ReportMaterialError("material differs from canonical typed reconstruction")
    return rebuilt


def encode_provenance(value: tuple[EvidenceProvenanceV1, ...]) -> str:
    if type(value) is not tuple or any(type(item) is not EvidenceProvenanceV1 for item in value):
        raise ReportMaterialError("provenance must use exact typed entries")
    raw = _encode(value)
    _decode(raw, _PROVENANCE_ADAPTER)
    return raw


def decode_provenance(raw: str) -> tuple[EvidenceProvenanceV1, ...]:
    return _decode(raw, _PROVENANCE_ADAPTER)
