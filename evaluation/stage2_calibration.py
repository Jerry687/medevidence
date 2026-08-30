"""Append-only calibration evidence for the independent Stage-2 evaluator.

No approved calibration packet is bundled and this framework makes no calibration claim.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from medevidence.domain import canonical_json
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    MAX_EVALUATION_OUTPUT_TOKENS,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    SEMANTIC_EVALUATION_CONFIG_VERSION,
    SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    SEMANTIC_EVALUATION_METHOD,
    SEMANTIC_EVALUATION_MODEL,
    SEMANTIC_EVALUATION_PROMPT_BYTES,
    SEMANTIC_EVALUATION_PROMPT_HASH,
    SEMANTIC_EVALUATION_PROMPT_VERSION,
    SEMANTIC_EVALUATION_REASONING_EFFORT,
    SEMANTIC_EVALUATION_RUBRIC_HASH,
    SEMANTIC_EVALUATION_RUBRIC_VERSION,
    SEMANTIC_EVALUATION_SCHEMA_HASH,
    SEMANTIC_EVALUATION_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_VERSION,
    SemanticEvaluationCandidate,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluationUsage,
    build_semantic_evaluation_result,
    parse_semantic_evaluation_candidate,
    parse_semantic_evaluation_request,
    reconstruct_semantic_evaluation_usage,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
    semantic_evaluation_response_schema,
    validate_semantic_evaluation_response_id,
)

SCHEMA_VERSION: Final = "medevidence.stage2.calibration.v3"
FRAMEWORK_STATUS: Final = "AWAITING_APPROVED_CALIBRATION_PACKET"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
MAX_CASES: Final = 200
MAX_NOTES_CHARACTERS: Final = 4_000
_DIGEST_PREFIX: Final = "sha256:"


class Stage2CalibrationError(ValueError):
    """Fail-closed calibration contract error."""


class CalibrationSplit(StrEnum):
    DEVELOPMENT = "development"
    SYNTHETIC = "synthetic"


class ProvenanceKind(StrEnum):
    CASE_SOURCE = "case_source"
    HUMAN_RESOLUTION_PACKET = "human_resolution_packet"


@dataclass(frozen=True, slots=True)
class CalibrationConfiguration:
    evaluator_method: str
    evaluator_version: str
    prompt_version: str
    prompt_hash: str
    rubric_version: str
    rubric_hash: str
    schema_version: str
    schema_hash: str
    configuration_version: str
    configuration_hash: str
    model: str
    reasoning_effort: str
    code_revision: str
    implementation_manifest_hash: str
    calibration_dataset_identity: str
    human_resolution_packet_identity: str


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    kind: ProvenanceKind
    source_id: str
    content_hash: str
    locator: str


@dataclass(frozen=True, slots=True)
class GatewayObservation:
    """Exact provider-neutral primitives emitted by the semantic gateway."""

    evaluator_input_hash: str
    provider_request_hash: str
    raw_provider_request_bytes: bytes
    provider_response_id: str
    provider_response_hash: str
    raw_response_envelope_bytes: bytes
    structured_output_bytes: bytes
    structured_output_hash: str
    attempts: int
    usage: SemanticEvaluationUsage
    started_at_utc: datetime
    completed_at_utc: datetime


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    case_id: str
    category: str
    split: CalibrationSplit
    synthetic_only: bool
    semantic_request_bytes_hex: str
    semantic_request_bytes: int
    semantic_request_hash: str
    evaluator_input_hash: str
    provider_request_hash: str
    raw_provider_request_hex: str
    raw_provider_request_bytes: int
    provider_response_id: str
    provider_response_hash: str
    raw_response_envelope_hex: str
    raw_response_envelope_bytes: int
    structured_output_hex: str
    structured_output_bytes: int
    structured_output_hash: str
    attempts: int
    usage: SemanticEvaluationUsage
    started_at_utc: str
    completed_at_utc: str
    parsed_state: SemanticSupport
    parsed_rationale_codes: tuple[str, ...]
    parsed_rationale_codes_hash: str
    parsed_explanation: str
    parsed_explanation_hash: str
    parsed_human_review_required: bool
    human_resolution: SemanticSupport
    human_expected_state: SemanticSupport
    human_authority: str
    human_notes: str
    human_resolution_packet_identity: str
    human_resolution_hash: str
    provenance: tuple[ProvenanceRef, ...]


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _sha256(value: bytes) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(value).hexdigest()


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise Stage2CalibrationError(f"{field} is invalid")
    if any(ord(character) < 32 for character in value):
        raise Stage2CalibrationError(f"{field} contains control characters")
    return value


def _digest(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith(_DIGEST_PREFIX)
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise Stage2CalibrationError(f"{field} must be a lowercase sha256 digest")
    return value


def calibration_configuration(
    *,
    code_revision: str,
    implementation_manifest_hash: str,
    calibration_dataset_identity: str,
    human_resolution_packet_identity: str,
) -> CalibrationConfiguration:
    """Bind current evaluator authority plus exact code and calibration inputs."""

    value = CalibrationConfiguration(
        SEMANTIC_EVALUATION_METHOD,
        SEMANTIC_EVALUATION_VERSION,
        SEMANTIC_EVALUATION_PROMPT_VERSION,
        SEMANTIC_EVALUATION_PROMPT_HASH,
        SEMANTIC_EVALUATION_RUBRIC_VERSION,
        SEMANTIC_EVALUATION_RUBRIC_HASH,
        SEMANTIC_EVALUATION_SCHEMA_VERSION,
        SEMANTIC_EVALUATION_SCHEMA_HASH,
        SEMANTIC_EVALUATION_CONFIG_VERSION,
        SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        SEMANTIC_EVALUATION_MODEL,
        SEMANTIC_EVALUATION_REASONING_EFFORT,
        code_revision,
        implementation_manifest_hash,
        calibration_dataset_identity,
        human_resolution_packet_identity,
    )
    _validate_configuration(value)
    return value


def _validate_configuration(value: CalibrationConfiguration) -> None:
    if type(value) is not CalibrationConfiguration:
        raise Stage2CalibrationError("calibration configuration type is invalid")
    current = (
        SEMANTIC_EVALUATION_METHOD,
        SEMANTIC_EVALUATION_VERSION,
        SEMANTIC_EVALUATION_PROMPT_VERSION,
        SEMANTIC_EVALUATION_PROMPT_HASH,
        SEMANTIC_EVALUATION_RUBRIC_VERSION,
        SEMANTIC_EVALUATION_RUBRIC_HASH,
        SEMANTIC_EVALUATION_SCHEMA_VERSION,
        SEMANTIC_EVALUATION_SCHEMA_HASH,
        SEMANTIC_EVALUATION_CONFIG_VERSION,
        SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        SEMANTIC_EVALUATION_MODEL,
        SEMANTIC_EVALUATION_REASONING_EFFORT,
    )
    observed = (
        value.evaluator_method,
        value.evaluator_version,
        value.prompt_version,
        value.prompt_hash,
        value.rubric_version,
        value.rubric_hash,
        value.schema_version,
        value.schema_hash,
        value.configuration_version,
        value.configuration_hash,
        value.model,
        value.reasoning_effort,
    )
    if observed != current:
        raise Stage2CalibrationError("calibration evaluator authority drift")
    if (
        type(value.code_revision) is not str
        or len(value.code_revision) != 40
        or any(character not in "0123456789abcdef" for character in value.code_revision)
    ):
        raise Stage2CalibrationError("code revision must be an exact lowercase 40-hex commit")
    _digest(value.implementation_manifest_hash, "implementation manifest")
    _digest(value.calibration_dataset_identity, "calibration dataset identity")
    _digest(value.human_resolution_packet_identity, "human resolution packet identity")


def _candidate_hashes(candidate: SemanticEvaluationCandidate) -> tuple[str, str]:
    rationale = tuple(code.value for code in candidate.rationale_codes)
    return _sha256(_canonical_bytes(rationale)), _sha256(candidate.explanation.encode("utf-8"))


def _response_format() -> dict[str, object]:
    return {
        "name": "medevidence_semantic_evaluation",
        "schema": semantic_evaluation_response_schema(),
        "strict": True,
        "type": "json_schema",
    }


def canonical_provider_request_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Reconstruct the exact credential-free OpenAI Responses JSON request body."""

    if type(request) is not SemanticEvaluationRequest:
        raise Stage2CalibrationError("semantic request has the wrong type")
    try:
        content = semantic_evaluation_input_bytes(request).decode("utf-8", errors="strict")
    except (SemanticEvaluationContractError, UnicodeDecodeError) as error:
        raise Stage2CalibrationError("evaluator input reconstruction failed") from error
    body = {
        "background": False,
        "input": content,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "model": SEMANTIC_EVALUATION_MODEL,
        "parallel_tool_calls": False,
        "reasoning": {"effort": SEMANTIC_EVALUATION_REASONING_EFFORT},
        "store": False,
        "text": {"format": _response_format()},
        "tool_choice": "none",
        "tools": [],
        "truncation": "disabled",
    }
    return _canonical_bytes(body)


def _canonical_result(
    request: SemanticEvaluationRequest, candidate: SemanticEvaluationCandidate
) -> SemanticEvaluationResult:
    try:
        return build_semantic_evaluation_result(request, candidate)
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError(
            "candidate failed canonical semantic result authority"
        ) from error


def _human_hash(
    case_id: str,
    resolution: SemanticSupport,
    expected: SemanticSupport,
    authority: str,
    notes: str,
    packet: str,
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "case_id": case_id,
                "human_resolution": resolution.value,
                "human_expected_state": expected.value,
                "human_authority": authority,
                "human_notes": notes,
                "human_resolution_packet_identity": packet,
            }
        )
    )


def make_calibration_case(
    *,
    case_id: str,
    category: str,
    split: CalibrationSplit,
    request: SemanticEvaluationRequest,
    assessment: GatewayObservation,
    human_resolution: SemanticSupport,
    human_expected_state: SemanticSupport,
    human_authority: str,
    human_notes: str,
    human_resolution_packet_identity: str,
    provenance: tuple[ProvenanceRef, ...],
) -> CalibrationCase:
    """Construct one adjudicated case from exact production gateway evidence."""

    if type(request) is not SemanticEvaluationRequest:
        raise Stage2CalibrationError("semantic request has the wrong type")
    if type(assessment) is not GatewayObservation:
        raise Stage2CalibrationError("semantic assessment has the wrong type")
    if (
        type(human_resolution) is not SemanticSupport
        or type(human_expected_state) is not SemanticSupport
    ):
        raise Stage2CalibrationError("human resolution and expected state are required")
    _text(human_authority, "human authority")
    _text(human_notes, "human notes", maximum=MAX_NOTES_CHARACTERS)
    _digest(human_resolution_packet_identity, "human resolution packet")
    try:
        request_bytes = semantic_evaluation_request_bytes(request)
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError("semantic request reconstruction failed") from error
    candidate = _parse_candidate(assessment.structured_output_bytes)
    result = _canonical_result(request, candidate)
    case = CalibrationCase(
        case_id=case_id,
        category=category,
        split=split,
        synthetic_only=split is CalibrationSplit.SYNTHETIC,
        semantic_request_bytes_hex=request_bytes.hex(),
        semantic_request_bytes=len(request_bytes),
        semantic_request_hash=_sha256(request_bytes),
        evaluator_input_hash=assessment.evaluator_input_hash,
        provider_request_hash=assessment.provider_request_hash,
        raw_provider_request_hex=assessment.raw_provider_request_bytes.hex(),
        raw_provider_request_bytes=len(assessment.raw_provider_request_bytes),
        provider_response_id=assessment.provider_response_id,
        provider_response_hash=assessment.provider_response_hash,
        raw_response_envelope_hex=assessment.raw_response_envelope_bytes.hex(),
        raw_response_envelope_bytes=len(assessment.raw_response_envelope_bytes),
        structured_output_hex=assessment.structured_output_bytes.hex(),
        structured_output_bytes=len(assessment.structured_output_bytes),
        structured_output_hash=assessment.structured_output_hash,
        attempts=assessment.attempts,
        usage=assessment.usage,
        started_at_utc=assessment.started_at_utc.isoformat(),
        completed_at_utc=assessment.completed_at_utc.isoformat(),
        parsed_state=result.result,
        parsed_rationale_codes=tuple(code.value for code in result.rationale_codes),
        parsed_rationale_codes_hash=result.rationale_codes_hash,
        parsed_explanation=result.explanation,
        parsed_explanation_hash=result.explanation_hash,
        parsed_human_review_required=result.human_review_required,
        human_resolution=human_resolution,
        human_expected_state=human_expected_state,
        human_authority=human_authority,
        human_notes=human_notes,
        human_resolution_packet_identity=human_resolution_packet_identity,
        human_resolution_hash=_human_hash(
            case_id,
            human_resolution,
            human_expected_state,
            human_authority,
            human_notes,
            human_resolution_packet_identity,
        ),
        provenance=provenance,
    )
    _validate_case(case)
    return case


def _parse_candidate(raw: bytes) -> SemanticEvaluationCandidate:
    try:
        return parse_semantic_evaluation_candidate(raw)
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError("structured output failed public semantic parser") from error


def _bytes_from_hex(
    value: object,
    byte_count: object,
    field: str,
    *,
    maximum: int | None = None,
) -> bytes:
    if type(value) is not str or type(byte_count) is not int or byte_count < 1:
        raise Stage2CalibrationError(f"{field} byte evidence is invalid")
    if maximum is not None and (byte_count > maximum or len(value) > maximum * 2):
        raise Stage2CalibrationError(f"{field} exceeds shared byte bound")
    if len(value) != byte_count * 2:
        raise Stage2CalibrationError(f"{field} bytes/hex/count drift")
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise Stage2CalibrationError(f"{field} hex is invalid") from error
    if raw.hex() != value or len(raw) != byte_count:
        raise Stage2CalibrationError(f"{field} bytes/hex/count drift")
    return raw


def _parse_request(raw: bytes) -> SemanticEvaluationRequest:
    try:
        request = parse_semantic_evaluation_request(raw)
        if semantic_evaluation_request_bytes(request) != raw:
            raise Stage2CalibrationError("semantic request bytes are not canonical")
        return request
    except Stage2CalibrationError:
        raise
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError("semantic request failed public request parser") from error


def validate_semantic_request_bytes(raw: bytes) -> SemanticEvaluationRequest:
    """Public calibration wrapper around the canonical request parser."""

    if type(raw) is not bytes:
        raise Stage2CalibrationError("semantic request bytes have the wrong type")
    return _parse_request(raw)


def _response_document(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Stage2CalibrationError("response envelope contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Stage2CalibrationError("response envelope is not strict UTF-8 JSON") from error
    if type(value) is not dict:
        raise Stage2CalibrationError("response envelope must be an object")
    allowed = {
        "background",
        "conversation",
        "created_at",
        "error",
        "id",
        "incomplete_details",
        "instructions",
        "max_output_tokens",
        "max_tool_calls",
        "metadata",
        "model",
        "object",
        "output",
        "parallel_tool_calls",
        "previous_response_id",
        "prompt",
        "prompt_cache_key",
        "prompt_cache_options",
        "prompt_cache_retention",
        "reasoning",
        "safety_identifier",
        "service_tier",
        "status",
        "store",
        "temperature",
        "text",
        "tool_choice",
        "tools",
        "top_p",
        "truncation",
        "usage",
    }
    tool_fields = {
        "computer_call",
        "file_search_call",
        "function_call",
        "mcp_call",
        "tool_calls",
        "web_search_call",
    }
    if set(value) & tool_fields:
        raise Stage2CalibrationError("response envelope contains tool output")
    if set(value) - allowed:
        raise Stage2CalibrationError("response envelope contains unknown fields")
    created_at = value.get("created_at")
    reasoning = value.get("reasoning")
    text = value.get("text")
    if (
        type(created_at) is not int
        or created_at < 0
        or value.get("object") != "response"
        or value.get("status") != "completed"
        or value.get("error") is not None
        or value.get("incomplete_details") is not None
        or value.get("model") != SEMANTIC_EVALUATION_MODEL
        or value.get("instructions") != SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8")
        or value.get("store") is not False
        or value.get("background") is not False
        or value.get("tools") != []
        or value.get("tool_choice") != "none"
        or value.get("parallel_tool_calls") is not False
        or value.get("max_output_tokens") != MAX_EVALUATION_OUTPUT_TOKENS
        or value.get("truncation") != "disabled"
        or value.get("service_tier") not in (None, "default")
        or type(reasoning) is not dict
        or set(reasoning) - {"effort", "summary"}
        or reasoning.get("effort") != SEMANTIC_EVALUATION_REASONING_EFFORT
        or reasoning.get("summary") is not None
        or type(text) is not dict
        or set(text) - {"format", "verbosity"}
        or text.get("format") != _response_format()
        or text.get("verbosity") not in (None, "medium")
        or value.get("prompt_cache_retention") not in (None, "in_memory")
        or value.get("prompt_cache_options") not in (None, {})
    ):
        raise Stage2CalibrationError("response envelope configuration/status drift")
    unrequested = {
        "conversation",
        "metadata",
        "previous_response_id",
        "prompt",
        "prompt_cache_key",
        "safety_identifier",
        "temperature",
        "top_p",
    }
    if any(value.get(field) is not None for field in unrequested):
        raise Stage2CalibrationError("response envelope contains unrequested configuration")
    return value


def _extract_output_text(document: Mapping[str, Any]) -> bytes:
    output = document.get("output")
    if type(output) is not list:
        raise Stage2CalibrationError("response envelope output shape is invalid")
    texts: list[str] = []
    messages = 0
    for item in output:
        if type(item) is not dict:
            raise Stage2CalibrationError("response output item is invalid")
        if item.get("type") == "reasoning":
            if (
                set(item) - {"id", "type", "summary", "status"}
                or type(item.get("id")) is not str
                or not item["id"].startswith("rs_")
                or item.get("status") not in (None, "completed")
                or item.get("summary") != []
            ):
                raise Stage2CalibrationError("response reasoning item is invalid")
            continue
        if item.get("type") != "message":
            raise Stage2CalibrationError("response contains tool or unknown output item")
        messages += 1
        if (
            set(item) != {"id", "type", "status", "role", "content"}
            or type(item.get("id")) is not str
            or not item["id"].startswith("msg_")
            or item.get("role") != "assistant"
            or item.get("status") != "completed"
        ):
            raise Stage2CalibrationError("response message item is invalid")
        content = item.get("content")
        if type(content) is not list:
            raise Stage2CalibrationError("response message content shape is invalid")
        for part in content:
            if type(part) is not dict:
                raise Stage2CalibrationError("response content part is invalid")
            if part.get("type") == "refusal":
                raise Stage2CalibrationError("response refusal is forbidden")
            if (
                set(part) != {"type", "text", "annotations", "logprobs"}
                or part.get("type") != "output_text"
                or part.get("annotations") != []
                or part.get("logprobs") != []
                or type(part.get("text")) is not str
            ):
                raise Stage2CalibrationError("response output_text part is invalid")
            texts.append(part["text"])
    if messages != 1 or len(texts) != 1:
        raise Stage2CalibrationError("response envelope must contain exactly one output_text")
    return texts[0].encode("utf-8")


def _validate_usage(
    value: SemanticEvaluationUsage, document: Mapping[str, Any]
) -> SemanticEvaluationUsage:
    try:
        observed = reconstruct_semantic_evaluation_usage(value)
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError("usage failed shared semantic authority") from error
    raw = document.get("usage")
    if type(raw) is not dict:
        raise Stage2CalibrationError("response envelope usage is missing")

    def detail(item: object, key: str) -> int:
        if item is None:
            return 0
        if type(item) is not dict:
            raise Stage2CalibrationError("response envelope usage details are invalid")
        observed = item.get(key, 0)
        if type(observed) is not int or observed < 0:
            raise Stage2CalibrationError("response envelope usage detail is invalid")
        return observed

    def count(key: str) -> int:
        observed = raw.get(key)
        if type(observed) is not int:
            raise Stage2CalibrationError("response envelope usage count is invalid")
        return observed

    try:
        expected = SemanticEvaluationUsage(
            input_tokens=count("input_tokens"),
            output_tokens=count("output_tokens"),
            total_tokens=count("total_tokens"),
            cached_input_tokens=detail(raw.get("input_tokens_details"), "cached_tokens"),
            reasoning_output_tokens=detail(raw.get("output_tokens_details"), "reasoning_tokens"),
        )
        expected = reconstruct_semantic_evaluation_usage(expected)
    except (ValidationError, SemanticEvaluationContractError) as error:
        raise Stage2CalibrationError("envelope usage failed shared semantic authority") from error
    if observed != expected:
        raise Stage2CalibrationError("usage does not bind the response envelope")
    return observed


def _validate_case(
    value: CalibrationCase,
) -> tuple[SemanticEvaluationRequest, SemanticEvaluationResult]:
    if type(value) is not CalibrationCase:
        raise Stage2CalibrationError("calibration case has the wrong type")
    _text(value.case_id, "case id")
    _text(value.category, "category")
    if type(value.split) is not CalibrationSplit:
        raise Stage2CalibrationError("calibration split is invalid")
    if value.synthetic_only is not (value.split is CalibrationSplit.SYNTHETIC):
        raise Stage2CalibrationError("split and synthetic-only binding drift")
    request_raw = _bytes_from_hex(
        value.semantic_request_bytes_hex,
        value.semantic_request_bytes,
        "semantic request",
    )
    if value.semantic_request_hash != _sha256(request_raw):
        raise Stage2CalibrationError("semantic request hash drift")
    request = _parse_request(request_raw)
    expected_input_hash = _sha256(semantic_evaluation_input_bytes(request))
    if value.evaluator_input_hash != expected_input_hash:
        raise Stage2CalibrationError("evaluator input hash does not bind canonical request")
    provider_request_raw = _bytes_from_hex(
        value.raw_provider_request_hex,
        value.raw_provider_request_bytes,
        "provider request",
    )
    if value.provider_request_hash != _sha256(provider_request_raw):
        raise Stage2CalibrationError("provider request hash drift")
    if provider_request_raw != canonical_provider_request_bytes(request):
        raise Stage2CalibrationError(
            "provider request body differs from canonical evaluator profile"
        )
    response_raw = _bytes_from_hex(
        value.raw_response_envelope_hex,
        value.raw_response_envelope_bytes,
        "response envelope",
        maximum=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    )
    if value.provider_response_hash != _sha256(response_raw):
        raise Stage2CalibrationError("provider response hash drift")
    structured_raw = _bytes_from_hex(
        value.structured_output_hex,
        value.structured_output_bytes,
        "structured output",
    )
    if value.structured_output_hash != _sha256(structured_raw):
        raise Stage2CalibrationError("structured output hash drift")
    document = _response_document(response_raw)
    try:
        response_id = validate_semantic_evaluation_response_id(value.provider_response_id)
    except SemanticEvaluationContractError as error:
        raise Stage2CalibrationError("response ID failed shared semantic authority") from error
    if document.get("id") != response_id:
        raise Stage2CalibrationError("provider response identity drift")
    if _extract_output_text(document) != structured_raw:
        raise Stage2CalibrationError("structured output does not bind response envelope")
    candidate = _parse_candidate(structured_raw)
    result = _canonical_result(request, candidate)
    observed = (
        value.parsed_state,
        value.parsed_rationale_codes,
        value.parsed_rationale_codes_hash,
        value.parsed_explanation,
        value.parsed_explanation_hash,
        value.parsed_human_review_required,
    )
    expected = (
        result.result,
        tuple(code.value for code in result.rationale_codes),
        result.rationale_codes_hash,
        result.explanation,
        result.explanation_hash,
        result.human_review_required,
    )
    if observed != expected:
        raise Stage2CalibrationError("parsed fields differ from public semantic parser")
    if type(value.attempts) is not int or not 1 <= value.attempts <= 3:
        raise Stage2CalibrationError("attempt count is invalid")
    _validate_usage(value.usage, document)
    started, completed = (
        _utc(value.started_at_utc, "started"),
        _utc(value.completed_at_utc, "completed"),
    )
    if completed < started:
        raise Stage2CalibrationError("gateway timestamps are reversed")
    if (
        type(value.human_resolution) is not SemanticSupport
        or type(value.human_expected_state) is not SemanticSupport
        or value.human_resolution is not value.human_expected_state
    ):
        raise Stage2CalibrationError("human resolution and expected state must be exact and equal")
    _text(value.human_authority, "human authority")
    _text(value.human_notes, "human notes", maximum=MAX_NOTES_CHARACTERS)
    packet = _digest(value.human_resolution_packet_identity, "human resolution packet")
    if value.human_resolution_hash != _human_hash(
        value.case_id,
        value.human_resolution,
        value.human_expected_state,
        value.human_authority,
        value.human_notes,
        packet,
    ):
        raise Stage2CalibrationError("human resolution hash drift")
    if type(value.provenance) is not tuple or not value.provenance:
        raise Stage2CalibrationError("case provenance is required")
    seen: set[tuple[str, str, str, str]] = set()
    packet_bound = False
    for item in value.provenance:
        if type(item) is not ProvenanceRef or type(item.kind) is not ProvenanceKind:
            raise Stage2CalibrationError("case provenance item is invalid")
        key = (
            item.kind.value,
            _text(item.source_id, "provenance source id"),
            _digest(item.content_hash, "provenance content hash"),
            _text(item.locator, "provenance locator", maximum=1_024),
        )
        if key in seen:
            raise Stage2CalibrationError("duplicate provenance is forbidden")
        seen.add(key)
        packet_bound |= (
            item.kind is ProvenanceKind.HUMAN_RESOLUTION_PACKET and item.content_hash == packet
        )
    if not packet_bound:
        raise Stage2CalibrationError("human resolution packet provenance is missing")
    return request, result


def _utc(value: object, field: str) -> datetime:
    if type(value) is not str:
        raise Stage2CalibrationError(f"{field} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise Stage2CalibrationError(f"{field} timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise Stage2CalibrationError(f"{field} timestamp must be UTC")
    return parsed


def _metrics(cases: Sequence[CalibrationCase]) -> dict[str, Any]:
    states = tuple(state.value for state in SemanticSupport)
    reparsed = [(case, _validate_case(case)[1].result) for case in cases]
    agreement = sum(result is case.human_expected_state for case, result in reparsed)
    confusion = {human: {predicted: 0 for predicted in states} for human in states}
    for case, result in reparsed:
        confusion[case.human_expected_state.value][result.value] += 1
    categories: dict[str, Any] = {}
    for category in sorted({case.category for case in cases}):
        selected = [(case, result) for case, result in reparsed if case.category == category]
        count = sum(result is case.human_expected_state for case, result in selected)
        categories[category] = {
            "agreement_count": count,
            "denominator": len(selected),
            "agreement_rate": count / len(selected),
        }
    disagreements = Counter(
        (case.human_expected_state.value, result.value)
        for case, result in reparsed
        if result is not case.human_expected_state
    )
    return {
        "agreement": {
            "agreement_count": agreement,
            "denominator": len(cases),
            "agreement_rate": agreement / len(cases) if cases else None,
            "unresolved_or_excluded": 0,
        },
        "confusion_matrix": confusion,
        "by_category": categories,
        "error_analysis": {
            "disagreement_pairs": {
                f"{human}->{predicted}": count
                for (human, predicted), count in sorted(disagreements.items())
            },
            "disagreement_case_ids": sorted(
                case.case_id for case, result in reparsed if result is not case.human_expected_state
            ),
        },
    }


def _case_configuration_binding(
    case: CalibrationCase, configuration: CalibrationConfiguration
) -> None:
    if case.human_resolution_packet_identity != configuration.human_resolution_packet_identity:
        raise Stage2CalibrationError("case human packet differs from configuration")
    if not any(
        item.kind is ProvenanceKind.CASE_SOURCE
        and item.content_hash == configuration.calibration_dataset_identity
        for item in case.provenance
    ):
        raise Stage2CalibrationError("case calibration dataset provenance is missing")


def build_calibration_artifact(
    *,
    calibration_set_name: str,
    configuration: CalibrationConfiguration,
    cases: Sequence[CalibrationCase],
    operational_timestamp_utc: datetime,
) -> dict[str, Any]:
    """Build one non-authoritative calibration evidence artifact."""

    _text(calibration_set_name, "calibration set name")
    _validate_configuration(configuration)
    if type(cases) not in {list, tuple} or not cases or len(cases) > MAX_CASES:
        raise Stage2CalibrationError("calibration cases must be a nonempty bounded sequence")
    ids: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for case in cases:
        _validate_case(case)
        if case.case_id in ids:
            raise Stage2CalibrationError("duplicate calibration case id")
        _case_configuration_binding(case, configuration)
        ids.add(case.case_id)
        payload = asdict(case)
        payload["usage"] = BaseModel.model_dump(case.usage, mode="json")
        payloads.append(payload)
    if (
        operational_timestamp_utc.tzinfo is None
        or operational_timestamp_utc.utcoffset() != UTC.utcoffset(operational_timestamp_utc)
    ):
        raise Stage2CalibrationError("operational timestamp must be UTC")
    semantic = {
        "schema_version": SCHEMA_VERSION,
        "framework_status": FRAMEWORK_STATUS,
        "calibration_claimed": False,
        "approved_calibration_packet_present": False,
        "holdout_accessed": False,
        "calibration_set": {
            "name": calibration_set_name,
            "identity": _sha256(_canonical_bytes(payloads)),
            "case_count": len(payloads),
            "splits": sorted({case.split.value for case in cases}),
        },
        "configuration": asdict(configuration),
        "cases": payloads,
        "metrics": _metrics(tuple(cases)),
    }
    artifact = {
        **semantic,
        "operational_timestamp_utc": operational_timestamp_utc.isoformat(),
        "artifact_semantic_id": _sha256(_canonical_bytes(semantic)),
    }
    validate_calibration_artifact(artifact)
    return artifact


def _object(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise Stage2CalibrationError(f"{field} schema is invalid")
    return value


def _support(value: object) -> SemanticSupport:
    if type(value) is SemanticSupport:
        return value
    if type(value) is not str:
        raise Stage2CalibrationError("semantic state is invalid")
    try:
        return SemanticSupport(value)
    except ValueError as error:
        raise Stage2CalibrationError("semantic state is invalid") from error


def _parse_case(value: object) -> CalibrationCase:
    raw = _object(
        value,
        {field.name for field in CalibrationCase.__dataclass_fields__.values()},
        "calibration case",
    )
    usage_raw = raw["usage"]
    try:
        usage = (
            reconstruct_semantic_evaluation_usage(usage_raw)
            if type(usage_raw) is SemanticEvaluationUsage
            else SemanticEvaluationUsage.model_validate(
                _object(
                    usage_raw,
                    {
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "cached_input_tokens",
                        "reasoning_output_tokens",
                    },
                    "usage",
                )
            )
        )
        usage = reconstruct_semantic_evaluation_usage(usage)
    except (ValidationError, SemanticEvaluationContractError) as error:
        raise Stage2CalibrationError("usage failed shared semantic authority") from error
    provenance_raw = raw["provenance"]
    if type(provenance_raw) not in {list, tuple}:
        raise Stage2CalibrationError("provenance collection is invalid")
    provenance: list[ProvenanceRef] = []
    for item in provenance_raw:
        item_raw = _object(item, {"kind", "source_id", "content_hash", "locator"}, "provenance")
        try:
            provenance.append(
                ProvenanceRef(
                    ProvenanceKind(item_raw["kind"]),
                    item_raw["source_id"],
                    item_raw["content_hash"],
                    item_raw["locator"],
                )
            )
        except (TypeError, ValueError) as error:
            raise Stage2CalibrationError("provenance value is invalid") from error
    rationale = raw["parsed_rationale_codes"]
    if type(rationale) not in {list, tuple} or any(type(item) is not str for item in rationale):
        raise Stage2CalibrationError("parsed rationale codes are invalid")
    try:
        split = CalibrationSplit(raw["split"])
    except (TypeError, ValueError) as error:
        raise Stage2CalibrationError("calibration split is invalid") from error
    case = CalibrationCase(
        case_id=raw["case_id"],
        category=raw["category"],
        split=split,
        synthetic_only=raw["synthetic_only"],
        semantic_request_bytes_hex=raw["semantic_request_bytes_hex"],
        semantic_request_bytes=raw["semantic_request_bytes"],
        semantic_request_hash=raw["semantic_request_hash"],
        evaluator_input_hash=raw["evaluator_input_hash"],
        provider_request_hash=raw["provider_request_hash"],
        raw_provider_request_hex=raw["raw_provider_request_hex"],
        raw_provider_request_bytes=raw["raw_provider_request_bytes"],
        provider_response_id=raw["provider_response_id"],
        provider_response_hash=raw["provider_response_hash"],
        raw_response_envelope_hex=raw["raw_response_envelope_hex"],
        raw_response_envelope_bytes=raw["raw_response_envelope_bytes"],
        structured_output_hex=raw["structured_output_hex"],
        structured_output_bytes=raw["structured_output_bytes"],
        structured_output_hash=raw["structured_output_hash"],
        attempts=raw["attempts"],
        usage=usage,
        started_at_utc=raw["started_at_utc"],
        completed_at_utc=raw["completed_at_utc"],
        parsed_state=_support(raw["parsed_state"]),
        parsed_rationale_codes=tuple(rationale),
        parsed_rationale_codes_hash=raw["parsed_rationale_codes_hash"],
        parsed_explanation=raw["parsed_explanation"],
        parsed_explanation_hash=raw["parsed_explanation_hash"],
        parsed_human_review_required=raw["parsed_human_review_required"],
        human_resolution=_support(raw["human_resolution"]),
        human_expected_state=_support(raw["human_expected_state"]),
        human_authority=raw["human_authority"],
        human_notes=raw["human_notes"],
        human_resolution_packet_identity=raw["human_resolution_packet_identity"],
        human_resolution_hash=raw["human_resolution_hash"],
        provenance=tuple(provenance),
    )
    _validate_case(case)
    return case


def validate_calibration_artifact(artifact: Mapping[str, Any]) -> None:
    """Reparse requests/responses and recompute all calibration evidence."""

    top = {
        "schema_version",
        "framework_status",
        "calibration_claimed",
        "approved_calibration_packet_present",
        "holdout_accessed",
        "calibration_set",
        "configuration",
        "cases",
        "metrics",
        "operational_timestamp_utc",
        "artifact_semantic_id",
    }
    if type(artifact) is not dict or set(artifact) != top:
        raise Stage2CalibrationError("artifact schema is invalid")
    if (
        artifact["schema_version"] != SCHEMA_VERSION
        or artifact["framework_status"] != FRAMEWORK_STATUS
        or artifact["calibration_claimed"] is not False
        or artifact["approved_calibration_packet_present"] is not False
        or artifact["holdout_accessed"] is not False
    ):
        raise Stage2CalibrationError("artifact boundary drift")
    _utc(artifact["operational_timestamp_utc"], "operational")
    semantic = dict(artifact)
    claimed = semantic.pop("artifact_semantic_id")
    semantic.pop("operational_timestamp_utc")
    if claimed != _sha256(_canonical_bytes(semantic)):
        raise Stage2CalibrationError("artifact semantic identity drift")
    config_raw = _object(
        artifact["configuration"],
        {field.name for field in CalibrationConfiguration.__dataclass_fields__.values()},
        "configuration",
    )
    configuration = CalibrationConfiguration(**config_raw)
    _validate_configuration(configuration)
    cases_raw = artifact["cases"]
    if type(cases_raw) is not list or not cases_raw or len(cases_raw) > MAX_CASES:
        raise Stage2CalibrationError("artifact cases are invalid")
    cases = tuple(_parse_case(item) for item in cases_raw)
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise Stage2CalibrationError("duplicate calibration case id")
    for case in cases:
        _case_configuration_binding(case, configuration)
    calibration_set = _object(
        artifact["calibration_set"],
        {"name", "identity", "case_count", "splits"},
        "calibration set",
    )
    if (
        calibration_set["identity"] != _sha256(_canonical_bytes(cases_raw))
        or calibration_set["case_count"] != len(cases)
        or calibration_set["splits"] != sorted({case.split.value for case in cases})
    ):
        raise Stage2CalibrationError("calibration set binding drift")
    if artifact["metrics"] != _metrics(cases):
        raise Stage2CalibrationError("metrics do not recompute from request/response evidence")


def _reject_output(output_root: Path) -> None:
    if not output_root.is_absolute():
        raise Stage2CalibrationError("output root must be absolute")
    resolved = output_root.resolve(strict=False)
    if resolved.is_relative_to(REPOSITORY_ROOT):
        raise Stage2CalibrationError("repository-contained output is forbidden")
    if output_root.exists() or output_root.is_symlink():
        raise Stage2CalibrationError("output exists; overwrite is forbidden")
    ancestor = output_root.parent
    while True:
        if ancestor.exists() and ancestor.is_symlink():
            raise Stage2CalibrationError("symlinked output ancestry is forbidden")
        if ancestor == ancestor.parent:
            break
        ancestor = ancestor.parent


def write_calibration_artifact(
    artifact: Mapping[str, Any], output_root: Path
) -> dict[str, dict[str, Any]]:
    """Atomically publish one absent external artifact directory and sidecar."""

    validate_calibration_artifact(artifact)
    _reject_output(output_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    pending = output_root.parent / f".{output_root.name}.pending"
    if pending.exists() or pending.is_symlink():
        raise Stage2CalibrationError("pending output exists")
    pending.mkdir()
    name, sidecar_name = "stage2-calibration.json", "stage2-calibration.sha256"
    data = _canonical_bytes(dict(artifact))
    try:
        with (pending / name).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        digest = hashlib.sha256(data).hexdigest()
        sidecar = f"{digest}  {name}\n".encode("ascii")
        with (pending / sidecar_name).open("xb") as handle:
            handle.write(sidecar)
            handle.flush()
            os.fsync(handle.fileno())
        pending.rename(output_root)
    except Exception:
        if pending.exists() and not pending.is_symlink():
            for child in pending.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            pending.rmdir()
        raise
    return {
        "artifact": {
            "path": str(output_root / name),
            "bytes": len(data),
            "sha256": _DIGEST_PREFIX + digest,
        },
        "sidecar": {
            "path": str(output_root / sidecar_name),
            "bytes": len(sidecar),
            "sha256": _sha256(sidecar),
        },
    }


def framework_status() -> dict[str, object]:
    return {
        "status": FRAMEWORK_STATUS,
        "approved_calibration_packet_present": False,
        "calibration_claimed": False,
        "holdout_accessed": False,
    }
