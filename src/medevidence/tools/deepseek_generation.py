"""Exact DeepSeek generation contracts and durable application authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self, final

from pydantic import BaseModel, Field, StringConstraints, model_validator

from medevidence.domain import (
    RunId,
    ScopeId,
    Sha256Digest,
    UtcDateTime,
    canonical_json,
    derive_identity,
)
from medevidence.domain.identifiers import DurableModel
from medevidence.tools.generation import (
    GENERATION_PROMPT_BYTES,
    GENERATION_PROMPT_HASH,
    GENERATION_SCHEMA_HASH,
    MAX_GENERATION_OUTPUT_TOKENS,
    GenerationCandidate,
    GenerationGatewayError,
    GenerationInput,
    GenerationUsage,
    generation_candidate_hash,
    generation_content_bytes,
    generation_input_hash,
    generation_response_schema,
    parse_generation_candidate,
    reconstruct_generation_candidate,
    reconstruct_generation_input,
    validate_generation_candidate,
)

DEEPSEEK_GENERATION_ENDPOINT = "https://api.deepseek.com/responses"
DEEPSEEK_GENERATION_MODEL_ALIAS = "deepseek-flash"
DEEPSEEK_GENERATION_CONFIG_VERSION = "m3.generation.deepseek-responses.v1"
DEEPSEEK_GENERATION_RECEIPT_MARKER = "M3_DEEPSEEK_GENERATION_RECEIPT_V1"
DEEPSEEK_GENERATION_RECEIPT_VERSION = "m3.generation.deepseek-receipt.v1"
MAX_DEEPSEEK_REQUEST_BYTES = 262_144
MAX_DEEPSEEK_RESPONSE_BYTES = 131_072
MAX_DEEPSEEK_RECEIPT_BYTES = 65_536
_RESPONSE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_RECEIPT_ID = re.compile(r"^generation-receipt:sha256:[0-9a-f]{64}$")


class DeepSeekGenerationContractError(ValueError):
    """Stable redacted error for untrusted generation bytes or provenance."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DeepSeekGenerationConfiguration(DurableModel):
    configuration_version: Literal["m3.generation.deepseek-responses.v1"] = (
        "m3.generation.deepseek-responses.v1"
    )
    requested_model_alias: Literal["deepseek-flash"] = "deepseek-flash"
    reasoning_effort: Literal["none"] = "none"
    endpoint: Literal["https://api.deepseek.com/responses"] = "https://api.deepseek.com/responses"
    prompt_version: Literal["m3.generation.synthesis.v1"] = "m3.generation.synthesis.v1"
    prompt_hash: Sha256Digest = GENERATION_PROMPT_HASH
    response_schema_version: Literal["m3.generation.candidate.v1"] = "m3.generation.candidate.v1"
    response_schema_hash: Sha256Digest = GENERATION_SCHEMA_HASH
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
    def exact_retries(self) -> Self:
        if (
            self.retryable_statuses != (429, 500, 502, 503, 504)
            or type(self.backoff_base_seconds) is not float
            or self.backoff_base_seconds != 0.25
        ):
            raise ValueError("DeepSeek generation retry statuses drift")
        return self


DEEPSEEK_GENERATION_CONFIGURATION = DeepSeekGenerationConfiguration()
DEEPSEEK_GENERATION_CONFIGURATION_HASH: Sha256Digest = (
    "sha256:"
    + hashlib.sha256(
        canonical_json(
            BaseModel.model_dump(DEEPSEEK_GENERATION_CONFIGURATION, mode="json")
        ).encode()
    ).hexdigest()
)


def deepseek_generation_response_format() -> dict[str, object]:
    return {
        "name": "medevidence_generation_candidate",
        "schema": generation_response_schema(),
        "strict": True,
        "type": "json_schema",
    }


def deepseek_generation_request_bytes(generation_input: GenerationInput) -> bytes:
    """Return one exact tool-free bounded DeepSeek request from admitted research input."""

    try:
        content = generation_content_bytes(reconstruct_generation_input(generation_input)).decode()
        raw = canonical_json(
            {
                "input": content,
                "instructions": GENERATION_PROMPT_BYTES.decode(),
                "max_output_tokens": MAX_GENERATION_OUTPUT_TOKENS,
                "model": DEEPSEEK_GENERATION_MODEL_ALIAS,
                "reasoning": {"effort": "none"},
                "text": {"format": deepseek_generation_response_format()},
                "tool_choice": "none",
                "tools": [],
            }
        ).encode()
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeepSeekGenerationContractError("deepseek_request_invalid") from error
    if len(raw) > MAX_DEEPSEEK_REQUEST_BYTES:
        raise DeepSeekGenerationContractError("deepseek_request_too_large")
    return raw


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DeepSeekGenerationContractError("deepseek_response_duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise DeepSeekGenerationContractError("deepseek_response_nonfinite")


def _json_tree(value: object, *, depth: int = 0) -> None:
    if depth > 64:
        raise DeepSeekGenerationContractError("deepseek_response_nesting_invalid")
    if type(value) is str:
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise DeepSeekGenerationContractError("deepseek_response_text_invalid")
    elif type(value) is list:
        for item in value:
            _json_tree(item, depth=depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            _json_tree(key, depth=depth + 1)
            _json_tree(item, depth=depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise DeepSeekGenerationContractError("deepseek_response_nonfinite")
    elif type(value) not in (int, bool, type(None)):
        raise DeepSeekGenerationContractError("deepseek_response_type_invalid")


def _usage(value: object) -> GenerationUsage:
    if type(value) is not dict or set(value) != {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_tokens_details",
        "output_tokens_details",
    }:
        raise DeepSeekGenerationContractError("deepseek_response_usage_invalid")
    details_in = value["input_tokens_details"]
    details_out = value["output_tokens_details"]
    if (
        type(details_in) is not dict
        or set(details_in) != {"cached_tokens"}
        or type(details_out) is not dict
        or set(details_out) != {"reasoning_tokens"}
    ):
        raise DeepSeekGenerationContractError("deepseek_response_usage_invalid")
    values = (
        value["input_tokens"],
        value["output_tokens"],
        value["total_tokens"],
        details_in["cached_tokens"],
        details_out["reasoning_tokens"],
    )
    if any(type(item) is not int for item in values):
        raise DeepSeekGenerationContractError("deepseek_response_usage_invalid")
    if values[4] != 0:
        raise DeepSeekGenerationContractError("deepseek_response_reasoning_profile_mismatch")
    try:
        return GenerationUsage(
            input_tokens=values[0],
            output_tokens=values[1],
            total_tokens=values[2],
            cached_input_tokens=values[3],
            reasoning_output_tokens=values[4],
        )
    except ValueError as error:
        raise DeepSeekGenerationContractError("deepseek_response_usage_invalid") from error


def parse_deepseek_generation_response(
    raw: bytes, generation_input: GenerationInput
) -> tuple[GenerationCandidate, str, GenerationUsage, str]:
    """Admit one complete text-only response; never interpret provider reasoning/tools."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_DEEPSEEK_RESPONSE_BYTES:
        raise DeepSeekGenerationContractError("deepseek_response_size_invalid")
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekGenerationContractError("deepseek_response_bom_forbidden")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _json_tree(document)
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise DeepSeekGenerationContractError("deepseek_response_json_invalid") from error
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
        raise DeepSeekGenerationContractError("deepseek_response_shape_invalid")
    if any(
        field in document
        and (type(document[field]) is not type(expected) or document[field] != expected)
        for field, expected in optional.items()
    ):
        raise DeepSeekGenerationContractError("deepseek_response_configuration_invalid")
    if (
        document["object"] != "response"
        or document["status"] != "completed"
        or document["error"] is not None
        or document["incomplete_details"] is not None
    ):
        raise DeepSeekGenerationContractError("deepseek_response_incomplete")
    if type(document["created_at"]) is not int or document["created_at"] < 0:
        raise DeepSeekGenerationContractError("deepseek_response_shape_invalid")
    response_id = document["id"]
    if type(response_id) is not str or _RESPONSE_ID.fullmatch(response_id) is None:
        raise DeepSeekGenerationContractError("deepseek_response_id_invalid")
    reported_model = document["model"]
    if type(reported_model) is not str or reported_model != DEEPSEEK_GENERATION_MODEL_ALIAS:
        raise DeepSeekGenerationContractError("deepseek_response_model_mismatch")
    if (
        document["store"] is not False
        or document["previous_response_id"] is not None
        or document["instructions"] != GENERATION_PROMPT_BYTES.decode()
        or document["reasoning"] not in ({"effort": "none"}, {"effort": "none", "summary": None})
        or type(document["text"]) is not dict
        or canonical_json(document["text"])
        not in (
            canonical_json({"format": deepseek_generation_response_format()}),
            canonical_json({"format": deepseek_generation_response_format(), "verbosity": None}),
        )
        or document["tools"] != []
        or document["tool_choice"] != "none"
        or type(document["max_output_tokens"]) is not int
        or document["max_output_tokens"] != MAX_GENERATION_OUTPUT_TOKENS
    ):
        raise DeepSeekGenerationContractError("deepseek_response_configuration_invalid")
    # DeepSeek echoes parallel_tool_calls=true even when no tool was requested.
    output = document["output"]
    if type(output) is not list or len(output) != 1 or type(output[0]) is not dict:
        raise DeepSeekGenerationContractError("deepseek_response_output_invalid")
    message = output[0]
    if set(message) - {"id", "type", "status", "role", "content", "phase"} or not {
        "id",
        "type",
        "status",
        "role",
        "content",
    } <= set(message):
        raise DeepSeekGenerationContractError("deepseek_response_output_invalid")
    if (
        message["type"] != "message"
        or message["status"] != "completed"
        or message["role"] != "assistant"
        or message.get("phase", "final_answer") != "final_answer"
    ):
        raise DeepSeekGenerationContractError("deepseek_response_tool_or_refusal")
    if type(message["id"]) is not str or not 1 <= len(message["id"]) <= 128:
        raise DeepSeekGenerationContractError("deepseek_response_output_invalid")
    content = message["content"]
    if type(content) is not list or len(content) != 1 or type(content[0]) is not dict:
        raise DeepSeekGenerationContractError("deepseek_response_output_invalid")
    part = content[0]
    if part.get("type") == "refusal":
        raise DeepSeekGenerationContractError("deepseek_response_refused")
    if (
        set(part) - {"type", "text", "annotations", "logprobs"}
        or not {"type", "text", "annotations"} <= set(part)
        or part["type"] != "output_text"
        or part["annotations"] != []
        or part.get("logprobs", []) != []
        or type(part["text"]) is not str
    ):
        raise DeepSeekGenerationContractError("deepseek_response_tool_or_refusal")
    try:
        candidate = validate_generation_candidate(
            generation_input, parse_generation_candidate(part["text"].encode("utf-8"))
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise DeepSeekGenerationContractError("deepseek_candidate_invalid") from error
    return candidate, response_id, _usage(document["usage"]), reported_model


type DeepSeekReceiptId = Annotated[
    str, StringConstraints(pattern=r"^generation-receipt:sha256:[0-9a-f]{64}$")
]


class DeepSeekProviderResult(DurableModel):
    candidate: GenerationCandidate
    provider: Literal["deepseek"] = "deepseek"
    requested_model_alias: Literal["deepseek-flash"] = "deepseek-flash"
    reported_model: Literal["deepseek-flash"] = "deepseek-flash"
    request_hash: Sha256Digest
    response_hash: Sha256Digest
    raw_response: Annotated[bytes, Field(min_length=1, max_length=MAX_DEEPSEEK_RESPONSE_BYTES)]
    provider_response_id: Annotated[str, StringConstraints(pattern=_RESPONSE_ID.pattern)]
    attempts: Annotated[int, Field(ge=1, le=3)]
    usage: GenerationUsage
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime

    @model_validator(mode="after")
    def exact_material(self) -> Self:
        if (
            type(self.candidate) is not GenerationCandidate
            or type(self.usage) is not GenerationUsage
        ):
            raise ValueError("DeepSeek provider result has an unvalidated nested type")
        reconstruct_generation_candidate(self.candidate)
        if self.response_hash != "sha256:" + hashlib.sha256(self.raw_response).hexdigest():
            raise ValueError("DeepSeek provider response hash differs from raw bytes")
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("DeepSeek provider completion precedes start")
        return self


class DeepSeekGenerationReceipt(DurableModel):
    marker: Literal["M3_DEEPSEEK_GENERATION_RECEIPT_V1"] = "M3_DEEPSEEK_GENERATION_RECEIPT_V1"
    receipt_version: Literal["m3.generation.deepseek-receipt.v1"] = (
        "m3.generation.deepseek-receipt.v1"
    )
    receipt_id: DeepSeekReceiptId
    receipt_content_hash: Sha256Digest
    run_id: RunId
    scope_id: ScopeId
    generation_input_hash: Sha256Digest
    candidate_hash: Sha256Digest
    prompt_hash: Sha256Digest
    configuration_hash: Sha256Digest
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
    response_byte_count: Annotated[int, Field(ge=1, le=MAX_DEEPSEEK_RESPONSE_BYTES)]
    provider_response_id: Annotated[str, StringConstraints(pattern=_RESPONSE_ID.pattern)]
    attempts: Annotated[int, Field(ge=1, le=3)]
    usage: GenerationUsage
    started_at_utc: UtcDateTime
    completed_at_utc: UtcDateTime

    @model_validator(mode="after")
    def exact_usage_and_time(self) -> Self:
        if type(self.usage) is not GenerationUsage or self.completed_at_utc < self.started_at_utc:
            raise ValueError("DeepSeek receipt usage or timestamps are invalid")
        return self


class DeepSeekGenerationReceiptRef(DurableModel):
    receipt_id: DeepSeekReceiptId
    receipt_content_hash: Sha256Digest
    run_id: RunId
    scope_id: ScopeId
    candidate_hash: Sha256Digest
    provider: Literal["deepseek"] = "deepseek"


def _receipt_payload(value: DeepSeekGenerationReceipt) -> dict[str, Any]:
    if type(value) is not DeepSeekGenerationReceipt:
        raise DeepSeekGenerationContractError("deepseek_receipt_type_invalid")
    reconstructed = DeepSeekGenerationReceipt.model_validate(
        BaseModel.model_dump(value, mode="python")
    )
    if reconstructed != value:
        raise DeepSeekGenerationContractError("deepseek_receipt_nested_type_invalid")
    return BaseModel.model_dump(reconstructed, mode="json")


def verify_deepseek_receipt(value: DeepSeekGenerationReceipt) -> DeepSeekGenerationReceipt:
    payload = _receipt_payload(value)
    if (
        payload["prompt_hash"] != GENERATION_PROMPT_HASH
        or payload["response_schema_hash"] != GENERATION_SCHEMA_HASH
        or payload["configuration_hash"] != DEEPSEEK_GENERATION_CONFIGURATION_HASH
    ):
        raise DeepSeekGenerationContractError("deepseek_receipt_profile_mismatch")
    semantic = {
        key: item
        for key, item in payload.items()
        if key not in {"receipt_id", "receipt_content_hash", "started_at_utc", "completed_at_utc"}
    }
    if payload["receipt_id"] != derive_identity("generation-receipt", semantic):
        raise DeepSeekGenerationContractError("deepseek_receipt_identity_invalid")
    content = {key: item for key, item in payload.items() if key != "receipt_content_hash"}
    if (
        payload["receipt_content_hash"]
        != "sha256:" + hashlib.sha256(canonical_json(content).encode()).hexdigest()
    ):
        raise DeepSeekGenerationContractError("deepseek_receipt_content_invalid")
    return value


def deepseek_receipt_bytes(value: DeepSeekGenerationReceipt) -> bytes:
    raw = canonical_json(_receipt_payload(verify_deepseek_receipt(value))).encode()
    if len(raw) > MAX_DEEPSEEK_RECEIPT_BYTES:
        raise DeepSeekGenerationContractError("deepseek_receipt_too_large")
    return raw


def parse_deepseek_receipt(raw: bytes) -> DeepSeekGenerationReceipt:
    if type(raw) is not bytes or not raw or len(raw) > MAX_DEEPSEEK_RECEIPT_BYTES:
        raise DeepSeekGenerationContractError("deepseek_receipt_size_invalid")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        _json_tree(document)
        value = DeepSeekGenerationReceipt.model_validate_json(raw)
        if canonical_json(_receipt_payload(value)).encode() != raw:
            raise ValueError("receipt is not canonical")
        return verify_deepseek_receipt(value)
    except (UnicodeError, ValueError, OverflowError, RecursionError) as error:
        raise DeepSeekGenerationContractError("deepseek_receipt_invalid") from error


def deepseek_receipt_ref(value: DeepSeekGenerationReceipt) -> DeepSeekGenerationReceiptRef:
    verified = verify_deepseek_receipt(value)
    return DeepSeekGenerationReceiptRef(
        receipt_id=verified.receipt_id,
        receipt_content_hash=verified.receipt_content_hash,
        run_id=verified.run_id,
        scope_id=verified.scope_id,
        candidate_hash=verified.candidate_hash,
    )


def build_deepseek_receipt(
    generation_input: GenerationInput, result: DeepSeekProviderResult
) -> DeepSeekGenerationReceipt:
    value = reconstruct_generation_input(generation_input)
    exact = verify_deepseek_result(value, result)
    common: dict[str, object] = {
        "run_id": value.run_id,
        "scope_id": value.scope_id,
        "generation_input_hash": generation_input_hash(value),
        "candidate_hash": generation_candidate_hash(exact.candidate),
        "prompt_hash": GENERATION_PROMPT_HASH,
        "configuration_hash": DEEPSEEK_GENERATION_CONFIGURATION_HASH,
        "response_schema_hash": GENERATION_SCHEMA_HASH,
        "provider": "deepseek",
        "requested_model_alias": DEEPSEEK_GENERATION_MODEL_ALIAS,
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
        "marker": DEEPSEEK_GENERATION_RECEIPT_MARKER,
        "receipt_version": DEEPSEEK_GENERATION_RECEIPT_VERSION,
        **{
            key: item
            for key, item in common.items()
            if key not in {"started_at_utc", "completed_at_utc"}
        },
    }
    receipt_id = derive_identity("generation-receipt", semantic)
    content = {
        **semantic,
        "receipt_id": receipt_id,
        "started_at_utc": common["started_at_utc"],
        "completed_at_utc": common["completed_at_utc"],
    }
    provisional = DeepSeekGenerationReceipt.model_validate(
        {**content, "receipt_content_hash": "sha256:" + "0" * 64}
    )
    canonical_content = {
        key: item
        for key, item in BaseModel.model_dump(provisional, mode="json").items()
        if key != "receipt_content_hash"
    }
    return verify_deepseek_receipt(
        DeepSeekGenerationReceipt.model_validate(
            {
                **BaseModel.model_dump(provisional, mode="python"),
                "receipt_content_hash": "sha256:"
                + hashlib.sha256(canonical_json(canonical_content).encode()).hexdigest(),
            }
        )
    )


def verify_deepseek_result(
    generation_input: GenerationInput, result: DeepSeekProviderResult
) -> DeepSeekProviderResult:
    if type(result) is not DeepSeekProviderResult:
        raise DeepSeekGenerationContractError("deepseek_result_type_invalid")
    exact = DeepSeekProviderResult.model_validate(BaseModel.model_dump(result, mode="python"))
    value = reconstruct_generation_input(generation_input)
    candidate, response_id, usage, reported_model = parse_deepseek_generation_response(
        exact.raw_response, value
    )
    if (
        exact.request_hash
        != "sha256:" + hashlib.sha256(deepseek_generation_request_bytes(value)).hexdigest()
        or exact.candidate != candidate
        or exact.provider_response_id != response_id
        or exact.usage != usage
        or exact.reported_model != reported_model
    ):
        raise DeepSeekGenerationContractError("deepseek_result_binding_invalid")
    return exact


class DeepSeekGenerationGatewayPort(Protocol):
    def generate(self, generation_input: GenerationInput) -> DeepSeekProviderResult: ...


class DeepSeekGenerationReceiptStorePort(Protocol):
    def save(
        self, receipt: DeepSeekGenerationReceipt, clean_raw_response: bytes
    ) -> DeepSeekGenerationReceiptRef: ...

    def load(
        self, reference: DeepSeekGenerationReceiptRef
    ) -> tuple[DeepSeekGenerationReceipt, bytes]: ...


class DeepSeekGenerationServiceErrorCode(StrEnum):
    INPUT_INVALID = "deepseek_generation_input_invalid"
    GATEWAY_INVALID = "deepseek_generation_gateway_invalid"
    RECEIPT_INVALID = "deepseek_generation_receipt_invalid"


class DeepSeekGenerationServiceError(RuntimeError):
    def __init__(self, code: DeepSeekGenerationServiceErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class DurableDeepSeekGenerationResult:
    candidate: GenerationCandidate
    receipt_ref: DeepSeekGenerationReceiptRef


@final
class DeepSeekGenerationService:
    """Return a candidate only after exact raw response and receipt readback."""

    __slots__ = ("_gateway", "_store")
    _gateway: DeepSeekGenerationGatewayPort
    _store: DeepSeekGenerationReceiptStorePort

    def __init__(
        self, *, gateway: DeepSeekGenerationGatewayPort, store: DeepSeekGenerationReceiptStorePort
    ) -> None:
        object.__setattr__(self, "_gateway", gateway)
        object.__setattr__(self, "_store", store)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek generation service is frozen")

    def generate(self, generation_input: GenerationInput) -> DurableDeepSeekGenerationResult:
        try:
            value = reconstruct_generation_input(generation_input)
        except (TypeError, ValueError) as error:
            raise DeepSeekGenerationServiceError(
                DeepSeekGenerationServiceErrorCode.INPUT_INVALID
            ) from error
        try:
            result = self._gateway.generate(value)
        except GenerationGatewayError as error:
            try:
                code = object.__getattribute__(error, "code")
                if type(code) is str:
                    raise GenerationGatewayError(code) from None
            except (AttributeError, TypeError, ValueError):
                pass
            raise DeepSeekGenerationServiceError(
                DeepSeekGenerationServiceErrorCode.GATEWAY_INVALID
            ) from None
        except Exception as error:
            raise DeepSeekGenerationServiceError(
                DeepSeekGenerationServiceErrorCode.GATEWAY_INVALID
            ) from error
        try:
            exact = verify_deepseek_result(value, result)
        except (TypeError, ValueError) as error:
            raise DeepSeekGenerationServiceError(
                DeepSeekGenerationServiceErrorCode.GATEWAY_INVALID
            ) from error
        try:
            receipt = build_deepseek_receipt(value, exact)
            reference = deepseek_receipt_ref(receipt)
            saved = self._store.save(receipt, exact.raw_response)
            if saved != reference:
                raise DeepSeekGenerationContractError("deepseek_receipt_reference_drift")
            loaded, raw = self._store.load(reference)
            if type(raw) is not bytes or raw != exact.raw_response or loaded != receipt:
                raise DeepSeekGenerationContractError("deepseek_receipt_readback_drift")
            if deepseek_receipt_ref(loaded) != reference:
                raise DeepSeekGenerationContractError("deepseek_receipt_identity_drift")
            verify_deepseek_result(value, exact.model_copy(update={"raw_response": raw}))
        except Exception as error:
            raise DeepSeekGenerationServiceError(
                DeepSeekGenerationServiceErrorCode.RECEIPT_INVALID
            ) from error
        return DurableDeepSeekGenerationResult(candidate=exact.candidate, receipt_ref=reference)
