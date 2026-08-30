"""DeepSeek-only Responses adapter for M3-008B semantic evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, final

import httpx
from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
    DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
    DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
    MAX_EVALUATION_ATTEMPTS,
    MAX_EVALUATION_OUTPUT_BYTES,
    MAX_EVALUATION_OUTPUT_TOKENS,
    MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    SEMANTIC_EVALUATION_BACKOFF_BASE_SECONDS,
    SEMANTIC_EVALUATION_CONNECT_TIMEOUT_SECONDS,
    SEMANTIC_EVALUATION_POOL_TIMEOUT_SECONDS,
    SEMANTIC_EVALUATION_PROMPT_BYTES,
    SEMANTIC_EVALUATION_READ_TIMEOUT_SECONDS,
    SEMANTIC_EVALUATION_RETRY_AFTER_CAP_SECONDS,
    SEMANTIC_EVALUATION_RETRYABLE_STATUSES,
    SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
    SEMANTIC_EVALUATION_WRITE_TIMEOUT_SECONDS,
    SemanticEvaluationCandidate,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluationUsage,
    build_deepseek_semantic_evaluation_result,
    parse_semantic_evaluation_candidate,
    semantic_evaluation_input_bytes,
    semantic_evaluation_response_schema,
)


class DeepSeekSemanticEvaluatorErrorCode(StrEnum):
    INVALID_CREDENTIAL = "invalid_credential"
    REQUEST_INTEGRITY = "request_integrity"
    AUTHENTICATION = "authentication_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_INVALID = "response_invalid"
    RESPONSE_INCOMPLETE = "response_incomplete"
    RESPONSE_REFUSED = "response_refused"
    RESPONSE_TOOL_OUTPUT = "response_tool_output"
    RESPONSE_MODEL_MISMATCH = "response_model_mismatch"
    CANDIDATE_INVALID = "candidate_invalid"


class DeepSeekSemanticEvaluatorError(RuntimeError):
    __slots__ = ("code", "status_code")

    def __init__(
        self,
        code: DeepSeekSemanticEvaluatorErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DeepSeekSemanticAssessment:
    result: SemanticEvaluationResult
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


def deepseek_response_format() -> dict[str, object]:
    """Return the exact DeepSeek JSON Schema format; application parsing is strict."""

    return {
        "type": "json_schema",
        "name": "medevidence_semantic_evaluation",
        "schema": semantic_evaluation_response_schema(),
    }


def deepseek_provider_request_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Return exact credential-free request bytes for the frozen DeepSeek profile."""

    if type(request) is not SemanticEvaluationRequest:
        raise SemanticEvaluationContractError("evaluation_request_invalid")
    content = semantic_evaluation_input_bytes(request).decode("utf-8", errors="strict")
    body = {
        "input": content,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning": {"effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT},
        "text": {"format": deepseek_response_format()},
        "tool_choice": "none",
        "tools": [],
    }
    raw = canonical_json(body).encode("utf-8")
    if len(raw) > MAX_EVALUATION_PROVIDER_REQUEST_BYTES:
        raise SemanticEvaluationContractError("evaluation_request_too_large")
    return raw


@final
class DeepSeekResponsesSemanticEvaluator:
    """No-selector evaluator bound to one DeepSeek provider profile."""

    __slots__ = ("_api_key", "_transport")

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport) -> None:
        if not _valid_key(api_key):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.INVALID_CREDENTIAL
            )
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_transport", transport)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek semantic evaluator is frozen")

    def evaluate(self, request: SemanticEvaluationRequest) -> DeepSeekSemanticAssessment:
        """Evaluate one canonical Stage-1-admitted tuple and retain exact byte evidence."""

        try:
            evaluator_input = semantic_evaluation_input_bytes(request)
            request_bytes = deepseek_provider_request_bytes(request)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(),
            )
            raw_reply = DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).send(raw_request)
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None
        candidate, response_id, usage, output_bytes = parse_deepseek_completed_response(
            raw_reply.body
        )
        try:
            result = build_deepseek_semantic_evaluation_result(request, candidate)
        except (SemanticEvaluationContractError, TypeError, ValueError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
            ) from None
        return DeepSeekSemanticAssessment(
            result=result,
            evaluator_input_hash=_sha256(evaluator_input),
            provider_request_hash=raw_reply.request_hash,
            raw_provider_request_bytes=request_bytes,
            provider_response_id=response_id,
            provider_response_hash=raw_reply.response_hash,
            raw_response_envelope_bytes=raw_reply.body,
            structured_output_bytes=output_bytes,
            structured_output_hash=_sha256(output_bytes),
            attempts=raw_reply.attempts,
            usage=usage,
            started_at_utc=raw_reply.started_at_utc,
            completed_at_utc=raw_reply.completed_at_utc,
        )


def parse_deepseek_completed_response(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse one completed DeepSeek Responses envelope."""

    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE)
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _validate_envelope(document)
    output_text = _one_output_text(document["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
        candidate = parse_semantic_evaluation_candidate(output_bytes)
        canonical = canonical_json(BaseModel.model_dump(candidate, mode="json")).encode("utf-8")
        if output_bytes != canonical:
            raise ValueError
    except (SemanticEvaluationContractError, UnicodeEncodeError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    response_id = _response_id(document["id"])
    return candidate, response_id, _usage(document["usage"]), output_bytes


def _validate_envelope(document: dict[str, Any]) -> None:
    required = {
        "created_at",
        "error",
        "id",
        "incomplete_details",
        "model",
        "object",
        "output",
        "parallel_tool_calls",
        "previous_response_id",
        "status",
        "store",
        "usage",
    }
    allowed = required | {
        "instructions",
        "max_output_tokens",
        "reasoning",
        "text",
        "tool_choice",
        "tools",
    }
    if set(document) - allowed or not required <= set(document):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if document["object"] != "response" or document["status"] != "completed":
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE)
    if document["error"] is not None or document["incomplete_details"] is not None:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE)
    if (
        type(document["created_at"]) is not int
        or document["created_at"] < 0
        or document["model"] != DEEPSEEK_SEMANTIC_EVALUATION_MODEL
    ):
        code = (
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_MODEL_MISMATCH
            if document.get("model") != DEEPSEEK_SEMANTIC_EVALUATION_MODEL
            else DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        )
        raise DeepSeekSemanticEvaluatorError(code)
    if document["store"] is not False or document["previous_response_id"] is not None:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if document["parallel_tool_calls"] is not True:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    echoes = {
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "reasoning": {"effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT},
        "text": {"format": deepseek_response_format()},
        "tool_choice": "none",
        "tools": [],
    }
    if any(field in document and document[field] != value for field, value in echoes.items()):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)


def _one_output_text(output: object) -> str:
    if type(output) is not list:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    messages = 0
    texts: list[str] = []
    for item in output:
        if type(item) is not dict:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        if item.get("type") == "reasoning":
            if set(item) != {"id", "type", "status", "content", "summary"}:
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            if (
                type(item["id"]) is not str
                or item["status"] != "completed"
                or item["summary"] != []
                or type(item["content"]) is not list
                or len(item["content"]) != 1
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            reasoning = item["content"][0]
            if (
                type(reasoning) is not dict
                or set(reasoning) != {"type", "text"}
                or reasoning["type"] != "reasoning_text"
                or type(reasoning["text"]) is not str
                or len(reasoning["text"].encode("utf-8")) > MAX_EVALUATION_OUTPUT_BYTES
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            continue
        if item.get("type") != "message":
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT
            )
        if set(item) != {"id", "type", "status", "role", "content"}:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        if item["status"] != "completed" or item["role"] != "assistant":
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE
            )
        if type(item["id"]) is not str or type(item["content"]) is not list:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        messages += 1
        for part in item["content"]:
            if type(part) is not dict:
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            if part.get("type") == "refusal":
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_REFUSED
                )
            if (
                set(part) != {"type", "text", "annotations"}
                or part["type"] != "output_text"
                or part["annotations"] != []
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT
                )
            if type(part["text"]) is not str:
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            texts.append(part["text"])
    if messages != 1 or len(texts) != 1:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    return texts[0]


def _usage(value: object) -> SemanticEvaluationUsage:
    if type(value) is not dict or set(value) != {
        "input_tokens",
        "input_tokens_details",
        "output_tokens",
        "output_tokens_details",
        "total_tokens",
    }:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    input_details = value["input_tokens_details"]
    output_details = value["output_tokens_details"]
    if type(input_details) is not dict or set(input_details) != {"cached_tokens"}:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if type(output_details) is not dict or set(output_details) != {"reasoning_tokens"}:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    fields = (
        value["input_tokens"],
        value["output_tokens"],
        value["total_tokens"],
        input_details["cached_tokens"],
        output_details["reasoning_tokens"],
    )
    if any(type(item) is not int for item in fields):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        return SemanticEvaluationUsage(
            input_tokens=fields[0],
            output_tokens=fields[1],
            total_tokens=fields[2],
            cached_input_tokens=fields[3],
            reasoning_output_tokens=fields[4],
        )
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None


def _response_id(value: object) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 512
        or not value.isascii()
        or any(not 33 <= ord(character) <= 126 for character in value)
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    return value


def _profile() -> DeepSeekTransportProfile:
    return DeepSeekTransportProfile(
        max_request_bytes=MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
        max_response_bytes=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        max_attempts=MAX_EVALUATION_ATTEMPTS,
        total_deadline_seconds=SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        connect_timeout_seconds=SEMANTIC_EVALUATION_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=SEMANTIC_EVALUATION_READ_TIMEOUT_SECONDS,
        write_timeout_seconds=SEMANTIC_EVALUATION_WRITE_TIMEOUT_SECONDS,
        pool_timeout_seconds=SEMANTIC_EVALUATION_POOL_TIMEOUT_SECONDS,
        backoff_base_seconds=SEMANTIC_EVALUATION_BACKOFF_BASE_SECONDS,
        retry_after_cap_seconds=SEMANTIC_EVALUATION_RETRY_AFTER_CAP_SECONDS,
        retryable_statuses=tuple(SEMANTIC_EVALUATION_RETRYABLE_STATUSES),
    )


def _transport_error(error: DeepSeekTransportError) -> DeepSeekSemanticEvaluatorError:
    mapping = {
        DeepSeekTransportErrorCode.INVALID_CREDENTIAL: (
            DeepSeekSemanticEvaluatorErrorCode.INVALID_CREDENTIAL
        ),
        DeepSeekTransportErrorCode.REQUEST_INTEGRITY: (
            DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
        ),
        DeepSeekTransportErrorCode.AUTHENTICATION: (
            DeepSeekSemanticEvaluatorErrorCode.AUTHENTICATION
        ),
        DeepSeekTransportErrorCode.PROVIDER_REJECTED: (
            DeepSeekSemanticEvaluatorErrorCode.PROVIDER_REJECTED
        ),
        DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE: (
            DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE
        ),
        DeepSeekTransportErrorCode.DEADLINE_EXCEEDED: (
            DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED
        ),
        DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE: (
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE
        ),
        DeepSeekTransportErrorCode.RESPONSE_INVALID: (
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ),
    }
    return DeepSeekSemanticEvaluatorError(
        mapping.get(error.code, DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE),
        status_code=error.status_code,
    )


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _valid_key(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 512
        and value.isascii()
        and all(33 <= ord(character) <= 126 for character in value)
    )


class _DuplicateKeyError(ValueError):
    pass


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result
