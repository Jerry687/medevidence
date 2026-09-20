"""DeepSeek Flash runtime contracts for the canonical Generation V2 candidate."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Annotated, Any, Literal, Never, Protocol, Self, final

from pydantic import BaseModel, Field, StringConstraints, model_validator

from medevidence.domain import RunId, ScopeId, Sha256Digest, UtcDateTime, canonical_json
from medevidence.domain.identifiers import DurableModel

from .generation import (
    MAX_GENERATION_INPUT_BYTES,
    MAX_GENERATION_OUTPUT_TOKENS,
    GenerationGatewayError,
    GenerationInput,
    GenerationUsage,
    generation_input_bytes,
    generation_input_hash,
    reconstruct_generation_input,
)
from .generation_v2 import (
    GENERATION_V2_CONFIG_HASH,
    GENERATION_V2_PROMPT_BYTES,
    GENERATION_V2_PROMPT_HASH,
    GENERATION_V2_SCHEMA_HASH,
    GenerationCandidateV2,
    generation_v2_candidate_bytes,
    generation_v2_response_schema,
    parse_generation_v2_candidate,
    validate_generation_v2_candidate,
)
from .report_validation import EvidenceInput, _copy_evidence
from .synthesis_mapping import generation_evidence_from_trusted

DEEPSEEK_GENERATION_V2_ENDPOINT = "https://api.deepseek.com/responses"
DEEPSEEK_GENERATION_V2_MODEL_ALIAS = "deepseek-flash"
DEEPSEEK_GENERATION_V2_CONFIGURATION_VERSION = "m3.generation.deepseek-flash-responses.v2"
DEEPSEEK_GENERATION_V2_RECEIPT_MARKER = "M3_DEEPSEEK_GENERATION_RECEIPT_V2"
DEEPSEEK_GENERATION_V2_RECEIPT_VERSION = "m3.generation.deepseek-receipt.v2"
MAX_DEEPSEEK_GENERATION_V2_REQUEST_BYTES = 262_144
MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES = 131_072
MAX_DEEPSEEK_GENERATION_V2_RECEIPT_BYTES = 65_536
_RESPONSE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class DeepSeekGenerationV2ContractError(ValueError):
    """Stable credential-free error for V2 runtime contract drift."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DeepSeekGenerationV2Configuration(DurableModel):
    configuration_version: Literal["m3.generation.deepseek-flash-responses.v2"] = (
        "m3.generation.deepseek-flash-responses.v2"
    )
    requested_model_alias: Literal["deepseek-flash"] = "deepseek-flash"
    reasoning_effort: Literal["none"] = "none"
    endpoint: Literal["https://api.deepseek.com/responses"] = "https://api.deepseek.com/responses"
    prompt_version: Literal["m3.generation.synthesis.v2"] = "m3.generation.synthesis.v2"
    prompt_hash: Sha256Digest = GENERATION_V2_PROMPT_HASH
    response_schema_version: Literal["m3.generation.candidate.v2"] = "m3.generation.candidate.v2"
    response_schema_hash: Sha256Digest = GENERATION_V2_SCHEMA_HASH
    candidate_configuration_version: Literal["m3.generation.deepseek-responses.v2"] = (
        "m3.generation.deepseek-responses.v2"
    )
    candidate_configuration_hash: Sha256Digest = GENERATION_V2_CONFIG_HASH
    store_requested: Literal[False] = False
    background_requested: Literal[False] = False
    continuation_requested: Literal[False] = False
    tools_requested: Literal[False] = False
    max_request_bytes: Literal[262144] = 262_144
    max_response_bytes: Literal[131072] = 131_072
    max_output_tokens: Literal[8192] = 8_192
    total_deadline_seconds: Literal[45] = 45
    connect_timeout_seconds: Literal[5] = 5
    read_timeout_seconds: Literal[30] = 30
    write_timeout_seconds: Literal[10] = 10
    pool_timeout_seconds: Literal[5] = 5
    max_attempts: Literal[3] = 3
    backoff_base_seconds: float = 0.25
    retry_after_cap_seconds: Literal[2] = 2
    retryable_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)

    @model_validator(mode="after")
    def exact_profile(self) -> Self:
        if (
            self.retryable_statuses != (429, 500, 502, 503, 504)
            or type(self.backoff_base_seconds) is not float
            or self.backoff_base_seconds != 0.25
        ):
            raise ValueError("DeepSeek V2 retry profile drift")
        return self


DEEPSEEK_GENERATION_V2_CONFIGURATION = DeepSeekGenerationV2Configuration()
DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH: Sha256Digest = (
    "sha256:"
    + hashlib.sha256(
        canonical_json(
            BaseModel.model_dump(DEEPSEEK_GENERATION_V2_CONFIGURATION, mode="json")
        ).encode("utf-8")
    ).hexdigest()
)


def _copy_trusted_evidence(
    generation_input: GenerationInput, trusted_evidence: tuple[EvidenceInput, ...]
) -> tuple[EvidenceInput, ...]:
    if type(trusted_evidence) is not tuple or any(
        type(item) is not EvidenceInput for item in trusted_evidence
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_trusted_evidence_wrong_type")
    try:
        copied = tuple(_copy_evidence(item) for item in trusted_evidence)
        projected = tuple(generation_evidence_from_trusted(item) for item in copied)
    except (TypeError, ValueError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_trusted_evidence_invalid") from error
    if copied != trusted_evidence or projected != generation_input.evidence:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_trusted_evidence_binding_drift")
    return copied


def _evidence_payload(value: EvidenceInput) -> dict[str, object]:
    return {
        "evidence_id": value.evidence_id,
        "authorized_run_id": value.authorized_run_id,
        "source": value.source.value,
        "source_record_id": value.source_record_id,
        "source_version": value.source_version,
        "snapshot_id": value.snapshot_id,
        "content_hash": value.content_hash,
        "locators": value.locators,
        "permitted_claim_classes": tuple(
            item.value for item in sorted(value.permitted_claim_classes, key=lambda row: row.value)
        ),
        "permitted_inference_uses": tuple(
            item.value for item in sorted(value.permitted_inference_uses, key=lambda row: row.value)
        ),
        "normalized_excerpt": value.normalized_excerpt,
        "numerical_facts": tuple(
            {field.name: getattr(fact, field.name) for field in fields(fact)}
            for fact in value.numerical_facts
        ),
    }


def _admit_material(
    generation_input: GenerationInput, trusted_evidence: tuple[EvidenceInput, ...]
) -> tuple[GenerationInput, tuple[EvidenceInput, ...]]:
    try:
        exact_input = reconstruct_generation_input(generation_input)
    except (TypeError, ValueError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_generation_input_invalid") from error
    return exact_input, _copy_trusted_evidence(exact_input, trusted_evidence)


def deepseek_generation_v2_input_bytes(
    generation_input: GenerationInput, trusted_evidence: tuple[EvidenceInput, ...]
) -> bytes:
    """Serialize exact input plus full canonical evidence facts inside a safe delimiter."""

    exact_input, exact_evidence = _admit_material(generation_input, trusted_evidence)
    generation_payload = json.loads(generation_input_bytes(exact_input))
    payload = canonical_json(
        {
            "generation_input": generation_payload,
            "trusted_evidence": tuple(_evidence_payload(item) for item in exact_evidence),
        }
    )
    safe = payload.replace("&", r"\u0026").replace("<", r"\u003c").replace(">", r"\u003e")
    raw = (
        b'<UNTRUSTED_RESEARCH_INPUT_V2 encoding="canonical-json-utf-8">\n'
        + safe.encode("utf-8")
        + b"\n</UNTRUSTED_RESEARCH_INPUT_V2>"
    )
    if not raw or len(raw) > MAX_GENERATION_INPUT_BYTES:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_input_material_too_large")
    return raw


def deepseek_generation_v2_trusted_evidence_hash(
    generation_input: GenerationInput, trusted_evidence: tuple[EvidenceInput, ...]
) -> Sha256Digest:
    exact_input, exact_evidence = _admit_material(generation_input, trusted_evidence)
    del exact_input
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json(tuple(_evidence_payload(item) for item in exact_evidence)).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def deepseek_generation_v2_response_format() -> dict[str, object]:
    return {
        "name": "medevidence_generation_candidate_v2",
        "schema": generation_v2_response_schema(),
        "strict": True,
        "type": "json_schema",
    }


def deepseek_generation_v2_request_bytes(
    generation_input: GenerationInput, trusted_evidence: tuple[EvidenceInput, ...]
) -> bytes:
    """Build the exact Flash/none, tool-free request for fully bound V2 evidence."""

    try:
        content = deepseek_generation_v2_input_bytes(generation_input, trusted_evidence).decode(
            "utf-8"
        )
        raw = canonical_json(
            {
                "input": content,
                "instructions": GENERATION_V2_PROMPT_BYTES.decode("utf-8"),
                "max_output_tokens": MAX_GENERATION_OUTPUT_TOKENS,
                "model": DEEPSEEK_GENERATION_V2_MODEL_ALIAS,
                "reasoning": {"effort": "none"},
                "text": {"format": deepseek_generation_v2_response_format()},
                "tool_choice": "none",
                "tools": [],
            }
        ).encode("utf-8")
    except DeepSeekGenerationV2ContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_request_invalid") from error
    if len(raw) > MAX_DEEPSEEK_GENERATION_V2_REQUEST_BYTES:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_request_too_large")
    return raw


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeepSeekGenerationV2ContractError("deepseek_v2_duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Never:
    raise DeepSeekGenerationV2ContractError("deepseek_v2_nonfinite")


def _json_tree(value: object, *, depth: int = 0) -> None:
    if depth > 64:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_nesting_invalid")
    if type(value) is str:
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise DeepSeekGenerationV2ContractError("deepseek_v2_text_invalid")
    elif type(value) is list:
        for item in value:
            _json_tree(item, depth=depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            _json_tree(key, depth=depth + 1)
            _json_tree(item, depth=depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise DeepSeekGenerationV2ContractError("deepseek_v2_nonfinite")
    elif type(value) not in (int, bool, type(None)):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_type_invalid")


def _usage(value: object) -> GenerationUsage:
    if type(value) is not dict or set(value) != {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_tokens_details",
        "output_tokens_details",
    }:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_usage_invalid")
    details_in, details_out = value["input_tokens_details"], value["output_tokens_details"]
    if (
        type(details_in) is not dict
        or set(details_in) != {"cached_tokens"}
        or type(details_out) is not dict
        or set(details_out) != {"reasoning_tokens"}
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_usage_invalid")
    values = (
        value["input_tokens"],
        value["output_tokens"],
        value["total_tokens"],
        details_in["cached_tokens"],
        details_out["reasoning_tokens"],
    )
    if any(type(item) is not int for item in values):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_usage_invalid")
    if values[4] != 0:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_reasoning_profile_mismatch")
    try:
        return GenerationUsage(
            input_tokens=values[0],
            output_tokens=values[1],
            total_tokens=values[2],
            cached_input_tokens=values[3],
            reasoning_output_tokens=values[4],
        )
    except ValueError as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_usage_invalid") from error


def parse_deepseek_generation_v2_response(
    raw: bytes,
    generation_input: GenerationInput,
    trusted_evidence: tuple[EvidenceInput, ...],
) -> tuple[GenerationCandidateV2, str, GenerationUsage, str]:
    """Admit one complete output-only response and bind its candidate to exact evidence."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_size_invalid")
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_bom_forbidden")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _json_tree(document)
    except DeepSeekGenerationV2ContractError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_json_invalid") from error
    required = {
        "id",
        "object",
        "created_at",
        "status",
        "error",
        "incomplete_details",
        "model",
        "store",
        "previous_response_id",
        "output",
        "usage",
        "instructions",
        "reasoning",
        "text",
        "tools",
        "tool_choice",
        "max_output_tokens",
    }
    optional = {"background": False, "parallel_tool_calls": True, "truncation": "disabled"}
    if (
        type(document) is not dict
        or not required <= set(document)
        or set(document) - required - set(optional)
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_shape_invalid")
    if any(
        field in document
        and (type(document[field]) is not type(expected) or document[field] != expected)
        for field, expected in optional.items()
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_configuration_invalid")
    if (
        document["object"] != "response"
        or document["status"] != "completed"
        or document["error"] is not None
        or document["incomplete_details"] is not None
        or type(document["created_at"]) is not int
        or document["created_at"] < 0
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_incomplete")
    response_id, reported_model = document["id"], document["model"]
    if type(response_id) is not str or _RESPONSE_ID.fullmatch(response_id) is None:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_id_invalid")
    if reported_model != DEEPSEEK_GENERATION_V2_MODEL_ALIAS:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_model_mismatch")
    if (
        document["store"] is not False
        or document["previous_response_id"] is not None
        or document["instructions"] != GENERATION_V2_PROMPT_BYTES.decode("utf-8")
        or document["reasoning"] not in ({"effort": "none"}, {"effort": "none", "summary": None})
        or type(document["text"]) is not dict
        or canonical_json(document["text"])
        not in (
            canonical_json({"format": deepseek_generation_v2_response_format()}),
            canonical_json({"format": deepseek_generation_v2_response_format(), "verbosity": None}),
        )
        or document["tools"] != []
        or document["tool_choice"] != "none"
        or type(document["max_output_tokens"]) is not int
        or document["max_output_tokens"] != MAX_GENERATION_OUTPUT_TOKENS
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_response_configuration_invalid")
    output = document["output"]
    if type(output) is not list or len(output) != 1 or type(output[0]) is not dict:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_output_invalid")
    message = output[0]
    if set(message) - {"id", "type", "status", "role", "content", "phase"} or not {
        "id",
        "type",
        "status",
        "role",
        "content",
    } <= set(message):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_output_invalid")
    if (
        message["type"] != "message"
        or message["status"] != "completed"
        or message["role"] != "assistant"
        or message.get("phase", "final_answer") != "final_answer"
        or type(message["id"]) is not str
        or not 1 <= len(message["id"]) <= 128
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_tool_or_refusal")
    content = message["content"]
    if type(content) is not list or len(content) != 1 or type(content[0]) is not dict:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_output_invalid")
    part = content[0]
    if part.get("type") == "refusal":
        raise DeepSeekGenerationV2ContractError("deepseek_v2_refused")
    if (
        set(part) - {"type", "text", "annotations", "logprobs"}
        or not {"type", "text", "annotations"} <= set(part)
        or part["type"] != "output_text"
        or part["annotations"] != []
        or part.get("logprobs", []) != []
        or type(part["text"]) is not str
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_tool_or_refusal")
    try:
        candidate = validate_generation_v2_candidate(
            generation_input,
            parse_generation_v2_candidate(part["text"].encode("utf-8")),
            trusted_evidence=trusted_evidence,
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_candidate_invalid") from error
    return candidate, response_id, _usage(document["usage"]), reported_model


type DeepSeekGenerationV2ReceiptId = Annotated[
    str, StringConstraints(pattern=r"^generation-receipt:sha256:[0-9a-f]{64}$")
]


class DeepSeekProviderResultV2(DurableModel):
    candidate: GenerationCandidateV2
    provider: Literal["deepseek"] = "deepseek"
    requested_model_alias: Literal["deepseek-flash"] = "deepseek-flash"
    reported_model: Literal["deepseek-flash"] = "deepseek-flash"
    request_hash: Sha256Digest
    response_hash: Sha256Digest
    raw_response: Annotated[
        bytes, Field(min_length=1, max_length=MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES)
    ]
    provider_response_id: Annotated[str, StringConstraints(pattern=_RESPONSE_ID.pattern)]
    attempts: Annotated[int, Field(ge=1, le=3)]
    usage: GenerationUsage
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime

    @model_validator(mode="after")
    def exact_material(self) -> Self:
        if (
            type(self.candidate) is not GenerationCandidateV2
            or type(self.usage) is not GenerationUsage
        ):
            raise ValueError("DeepSeek V2 provider result has an unvalidated nested type")
        generation_v2_candidate_bytes(self.candidate)
        if self.response_hash != "sha256:" + hashlib.sha256(self.raw_response).hexdigest():
            raise ValueError("DeepSeek V2 response hash differs from raw bytes")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("DeepSeek V2 provider completion precedes start")
        return self


class DeepSeekGenerationReceiptV2(DurableModel):
    marker: Literal["M3_DEEPSEEK_GENERATION_RECEIPT_V2"] = "M3_DEEPSEEK_GENERATION_RECEIPT_V2"
    receipt_version: Literal["m3.generation.deepseek-receipt.v2"] = (
        "m3.generation.deepseek-receipt.v2"
    )
    receipt_id: DeepSeekGenerationV2ReceiptId
    receipt_content_hash: Sha256Digest
    run_id: RunId
    scope_id: ScopeId
    generation_input_hash: Sha256Digest
    trusted_evidence_hash: Sha256Digest
    generation_material_hash: Sha256Digest
    candidate_hash: Sha256Digest
    prompt_version: Literal["m3.generation.synthesis.v2"]
    prompt_hash: Sha256Digest
    candidate_configuration_version: Literal["m3.generation.deepseek-responses.v2"]
    candidate_configuration_hash: Sha256Digest
    provider_configuration_version: Literal["m3.generation.deepseek-flash-responses.v2"]
    provider_configuration_hash: Sha256Digest
    response_schema_version: Literal["m3.generation.candidate.v2"]
    response_schema_hash: Sha256Digest
    provider: Literal["deepseek"] = "deepseek"
    requested_model_alias: Literal["deepseek-flash"] = "deepseek-flash"
    reported_model: Literal["deepseek-flash"] = "deepseek-flash"
    reasoning_effort: Literal["none"] = "none"
    response_store_observed: Literal[False] = False
    response_continuation_observed: Literal[False] = False
    operational_retention_unknown: Literal[True] = True
    request_hash: Sha256Digest
    response_hash: Sha256Digest
    response_byte_count: Annotated[int, Field(ge=1, le=MAX_DEEPSEEK_GENERATION_V2_RESPONSE_BYTES)]
    provider_response_id: Annotated[str, StringConstraints(pattern=_RESPONSE_ID.pattern)]
    attempts: Annotated[int, Field(ge=1, le=3)]
    usage: GenerationUsage
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime

    @model_validator(mode="after")
    def exact_usage_and_time(self) -> Self:
        if type(self.usage) is not GenerationUsage or self.completed_at_utc < self.started_at_utc:
            raise ValueError("DeepSeek V2 receipt usage or timestamps are invalid")
        return self


class DeepSeekGenerationReceiptRefV2(DurableModel):
    receipt_id: DeepSeekGenerationV2ReceiptId
    receipt_content_hash: Sha256Digest
    run_id: RunId
    scope_id: ScopeId
    candidate_hash: Sha256Digest
    generation_material_hash: Sha256Digest
    provider: Literal["deepseek"] = "deepseek"
    receipt_version: Literal["m3.generation.deepseek-receipt.v2"] = (
        "m3.generation.deepseek-receipt.v2"
    )


def _receipt_payload(value: DeepSeekGenerationReceiptV2) -> dict[str, Any]:
    if type(value) is not DeepSeekGenerationReceiptV2:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_type_invalid")
    reconstructed = DeepSeekGenerationReceiptV2.model_validate(
        BaseModel.model_dump(value, mode="python")
    )
    if reconstructed != value:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_nested_type_invalid")
    return BaseModel.model_dump(reconstructed, mode="json")


def verify_deepseek_generation_v2_receipt(
    value: DeepSeekGenerationReceiptV2,
) -> DeepSeekGenerationReceiptV2:
    payload = _receipt_payload(value)
    if (
        payload["prompt_hash"] != GENERATION_V2_PROMPT_HASH
        or payload["response_schema_hash"] != GENERATION_V2_SCHEMA_HASH
        or payload["candidate_configuration_hash"] != GENERATION_V2_CONFIG_HASH
        or payload["provider_configuration_hash"] != DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_profile_mismatch")
    semantic = {
        key: item
        for key, item in payload.items()
        if key not in {"receipt_id", "receipt_content_hash", "started_at_utc", "completed_at_utc"}
    }
    expected_id = (
        "generation-receipt:sha256:"
        + hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
    )
    if payload["receipt_id"] != expected_id:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_identity_invalid")
    content = {key: item for key, item in payload.items() if key != "receipt_content_hash"}
    if (
        payload["receipt_content_hash"]
        != "sha256:" + hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_content_invalid")
    return value


def deepseek_generation_v2_receipt_bytes(value: DeepSeekGenerationReceiptV2) -> bytes:
    raw = canonical_json(_receipt_payload(verify_deepseek_generation_v2_receipt(value))).encode(
        "utf-8"
    )
    if len(raw) > MAX_DEEPSEEK_GENERATION_V2_RECEIPT_BYTES:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_too_large")
    return raw


def parse_deepseek_generation_v2_receipt(raw: bytes) -> DeepSeekGenerationReceiptV2:
    if type(raw) is not bytes or not raw or len(raw) > MAX_DEEPSEEK_GENERATION_V2_RECEIPT_BYTES:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_size_invalid")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _json_tree(document)
        value = DeepSeekGenerationReceiptV2.model_validate_json(raw)
        if canonical_json(_receipt_payload(value)).encode("utf-8") != raw:
            raise ValueError("receipt is not canonical")
        return verify_deepseek_generation_v2_receipt(value)
    except DeepSeekGenerationV2ContractError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_invalid") from error


def deepseek_generation_v2_receipt_ref(
    value: DeepSeekGenerationReceiptV2,
) -> DeepSeekGenerationReceiptRefV2:
    exact = verify_deepseek_generation_v2_receipt(value)
    return DeepSeekGenerationReceiptRefV2(
        receipt_id=exact.receipt_id,
        receipt_content_hash=exact.receipt_content_hash,
        run_id=exact.run_id,
        scope_id=exact.scope_id,
        candidate_hash=exact.candidate_hash,
        generation_material_hash=exact.generation_material_hash,
    )


def verify_deepseek_generation_v2_result(
    generation_input: GenerationInput,
    trusted_evidence: tuple[EvidenceInput, ...],
    result: DeepSeekProviderResultV2,
) -> DeepSeekProviderResultV2:
    if type(result) is not DeepSeekProviderResultV2:
        raise DeepSeekGenerationV2ContractError("deepseek_v2_result_type_invalid")
    exact = DeepSeekProviderResultV2.model_validate(BaseModel.model_dump(result, mode="python"))
    admitted_input, admitted_evidence = _admit_material(generation_input, trusted_evidence)
    candidate, response_id, usage, reported_model = parse_deepseek_generation_v2_response(
        exact.raw_response, admitted_input, admitted_evidence
    )
    request_hash = (
        "sha256:"
        + hashlib.sha256(
            deepseek_generation_v2_request_bytes(admitted_input, admitted_evidence)
        ).hexdigest()
    )
    if (
        exact.request_hash != request_hash
        or exact.candidate != candidate
        or exact.provider_response_id != response_id
        or exact.usage != usage
        or exact.reported_model != reported_model
    ):
        raise DeepSeekGenerationV2ContractError("deepseek_v2_result_binding_invalid")
    return exact


def build_deepseek_generation_v2_receipt(
    generation_input: GenerationInput,
    trusted_evidence: tuple[EvidenceInput, ...],
    result: DeepSeekProviderResultV2,
) -> DeepSeekGenerationReceiptV2:
    exact_input, exact_evidence = _admit_material(generation_input, trusted_evidence)
    exact = verify_deepseek_generation_v2_result(exact_input, exact_evidence, result)
    material = deepseek_generation_v2_input_bytes(exact_input, exact_evidence)
    common: dict[str, object] = {
        "run_id": exact_input.run_id,
        "scope_id": exact_input.scope_id,
        "generation_input_hash": generation_input_hash(exact_input),
        "trusted_evidence_hash": deepseek_generation_v2_trusted_evidence_hash(
            exact_input, exact_evidence
        ),
        "generation_material_hash": "sha256:" + hashlib.sha256(material).hexdigest(),
        "candidate_hash": "sha256:"
        + hashlib.sha256(generation_v2_candidate_bytes(exact.candidate)).hexdigest(),
        "prompt_version": "m3.generation.synthesis.v2",
        "prompt_hash": GENERATION_V2_PROMPT_HASH,
        "candidate_configuration_version": "m3.generation.deepseek-responses.v2",
        "candidate_configuration_hash": GENERATION_V2_CONFIG_HASH,
        "provider_configuration_version": "m3.generation.deepseek-flash-responses.v2",
        "provider_configuration_hash": DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH,
        "response_schema_version": "m3.generation.candidate.v2",
        "response_schema_hash": GENERATION_V2_SCHEMA_HASH,
        "provider": "deepseek",
        "requested_model_alias": DEEPSEEK_GENERATION_V2_MODEL_ALIAS,
        "reported_model": exact.reported_model,
        "reasoning_effort": "none",
        "response_store_observed": False,
        "response_continuation_observed": False,
        "operational_retention_unknown": True,
        "request_hash": exact.request_hash,
        "response_hash": exact.response_hash,
        "response_byte_count": len(exact.raw_response),
        "provider_response_id": exact.provider_response_id,
        "attempts": exact.attempts,
        "usage": BaseModel.model_dump(exact.usage, mode="json"),
        "started_at_utc": exact.started_at_utc,
        "completed_at_utc": exact.completed_at_utc,
    }
    semantic = {
        "marker": DEEPSEEK_GENERATION_V2_RECEIPT_MARKER,
        "receipt_version": DEEPSEEK_GENERATION_V2_RECEIPT_VERSION,
        **{
            key: item
            for key, item in common.items()
            if key not in {"started_at_utc", "completed_at_utc"}
        },
    }
    receipt_id = (
        "generation-receipt:sha256:"
        + hashlib.sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
    )
    content = {
        **semantic,
        "receipt_id": receipt_id,
        "started_at_utc": common["started_at_utc"],
        "completed_at_utc": common["completed_at_utc"],
    }
    provisional = DeepSeekGenerationReceiptV2.model_validate(
        {**content, "receipt_content_hash": "sha256:" + "0" * 64}
    )
    canonical_content = {
        key: item
        for key, item in BaseModel.model_dump(provisional, mode="json").items()
        if key != "receipt_content_hash"
    }
    return verify_deepseek_generation_v2_receipt(
        DeepSeekGenerationReceiptV2.model_validate(
            {
                **BaseModel.model_dump(provisional, mode="python"),
                "receipt_content_hash": "sha256:"
                + hashlib.sha256(canonical_json(canonical_content).encode("utf-8")).hexdigest(),
            }
        )
    )


class DeepSeekGenerationV2GatewayPort(Protocol):
    def generate(
        self,
        generation_input: GenerationInput,
        *,
        trusted_evidence: tuple[EvidenceInput, ...],
    ) -> DeepSeekProviderResultV2: ...


class DeepSeekGenerationV2ReceiptStorePort(Protocol):
    def save(
        self, receipt: DeepSeekGenerationReceiptV2, clean_raw_response: bytes
    ) -> DeepSeekGenerationReceiptRefV2: ...

    def load(
        self, reference: DeepSeekGenerationReceiptRefV2
    ) -> tuple[DeepSeekGenerationReceiptV2, bytes]: ...


class DeepSeekGenerationV2ServiceErrorCode(StrEnum):
    INPUT_INVALID = "deepseek_generation_v2_input_invalid"
    GATEWAY_INVALID = "deepseek_generation_v2_gateway_invalid"
    RECEIPT_INVALID = "deepseek_generation_v2_receipt_invalid"


class DeepSeekGenerationV2ServiceError(RuntimeError):
    def __init__(self, code: DeepSeekGenerationV2ServiceErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class DurableDeepSeekGenerationV2Result:
    candidate: GenerationCandidateV2
    receipt_ref: DeepSeekGenerationReceiptRefV2


@final
class DeepSeekGenerationV2Service:
    """Return a V2 candidate only after raw and receipt readback verification."""

    __slots__ = ("_gateway", "_store")
    _gateway: DeepSeekGenerationV2GatewayPort
    _store: DeepSeekGenerationV2ReceiptStorePort

    def __init__(
        self,
        *,
        gateway: DeepSeekGenerationV2GatewayPort,
        store: DeepSeekGenerationV2ReceiptStorePort,
    ) -> None:
        object.__setattr__(self, "_gateway", gateway)
        object.__setattr__(self, "_store", store)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek generation V2 service is frozen")

    def generate(
        self,
        generation_input: GenerationInput,
        *,
        trusted_evidence: tuple[EvidenceInput, ...],
    ) -> DurableDeepSeekGenerationV2Result:
        try:
            value, evidence = _admit_material(generation_input, trusted_evidence)
        except (TypeError, ValueError) as error:
            raise DeepSeekGenerationV2ServiceError(
                DeepSeekGenerationV2ServiceErrorCode.INPUT_INVALID
            ) from error
        try:
            result = self._gateway.generate(value, trusted_evidence=evidence)
        except GenerationGatewayError as error:
            code = object.__getattribute__(error, "code")
            if type(code) is str:
                raise GenerationGatewayError(code) from None
            raise DeepSeekGenerationV2ServiceError(
                DeepSeekGenerationV2ServiceErrorCode.GATEWAY_INVALID
            ) from None
        except Exception as error:
            raise DeepSeekGenerationV2ServiceError(
                DeepSeekGenerationV2ServiceErrorCode.GATEWAY_INVALID
            ) from error
        try:
            exact = verify_deepseek_generation_v2_result(value, evidence, result)
        except (TypeError, ValueError) as error:
            raise DeepSeekGenerationV2ServiceError(
                DeepSeekGenerationV2ServiceErrorCode.GATEWAY_INVALID
            ) from error
        try:
            receipt = build_deepseek_generation_v2_receipt(value, evidence, exact)
            reference = deepseek_generation_v2_receipt_ref(receipt)
            saved = self._store.save(receipt, exact.raw_response)
            if saved != reference:
                raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_reference_drift")
            loaded, raw = self._store.load(reference)
            if type(raw) is not bytes or raw != exact.raw_response or loaded != receipt:
                raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_readback_drift")
            if deepseek_generation_v2_receipt_ref(loaded) != reference:
                raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_identity_drift")
            verify_deepseek_generation_v2_result(
                value, evidence, exact.model_copy(update={"raw_response": raw})
            )
            expected = build_deepseek_generation_v2_receipt(value, evidence, exact)
            if loaded != expected:
                raise DeepSeekGenerationV2ContractError("deepseek_v2_receipt_binding_drift")
        except Exception as error:
            raise DeepSeekGenerationV2ServiceError(
                DeepSeekGenerationV2ServiceErrorCode.RECEIPT_INVALID
            ) from error
        return DurableDeepSeekGenerationV2Result(candidate=exact.candidate, receipt_ref=reference)
