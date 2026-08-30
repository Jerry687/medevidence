"""Bounded OpenAI Responses gateway for independent semantic evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, final

import httpx

from medevidence.domain import canonical_json
from medevidence.infrastructure.responses_transport import (
    ResponsesRawRequest,
    ResponsesRawTransport,
    ResponsesTransportError,
    ResponsesTransportErrorCode,
    ResponsesTransportProfile,
)
from medevidence.tools.semantic_evaluation import (
    MAX_EVALUATION_ATTEMPTS,
    MAX_EVALUATION_OUTPUT_BYTES,
    MAX_EVALUATION_OUTPUT_TOKENS,
    MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    SEMANTIC_EVALUATION_BACKOFF_BASE_SECONDS,
    SEMANTIC_EVALUATION_CONFIGURATION,
    SEMANTIC_EVALUATION_CONNECT_TIMEOUT_SECONDS,
    SEMANTIC_EVALUATION_ENDPOINT,
    SEMANTIC_EVALUATION_MODEL,
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
    build_semantic_evaluation_result,
    parse_semantic_evaluation_candidate,
    reconstruct_semantic_evaluation_usage,
    semantic_evaluation_input_bytes,
    semantic_evaluation_response_schema,
    validate_semantic_evaluation_response_id,
)


class OpenAISemanticEvaluatorErrorCode(StrEnum):
    """Stable redacted errors exposed by the evaluator boundary."""

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


class OpenAISemanticEvaluatorError(RuntimeError):
    """Fresh redacted evaluator error without provider or evidence material."""

    __slots__ = ("code", "status_code")

    def __init__(
        self,
        code: OpenAISemanticEvaluatorErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@final
@dataclass(frozen=True, slots=True, repr=False)
class SemanticAssessment:
    """Provider-neutral result plus bounded transport provenance."""

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

    def __repr__(self) -> str:
        return "SemanticAssessment(<bounded caller-held observation>)"

    def __post_init__(self) -> None:
        if type(self.result) is not SemanticEvaluationResult:
            raise TypeError("semantic assessment result has wrong type")
        for digest in (
            self.evaluator_input_hash,
            self.provider_request_hash,
            self.provider_response_hash,
            self.structured_output_hash,
        ):
            if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError("semantic assessment digest invalid")
        if (
            type(self.raw_provider_request_bytes) is not bytes
            or not self.raw_provider_request_bytes
            or len(self.raw_provider_request_bytes) > MAX_EVALUATION_PROVIDER_REQUEST_BYTES
        ):
            raise ValueError("semantic assessment raw provider request bytes invalid")
        if self.provider_request_hash != _sha256(self.raw_provider_request_bytes):
            raise ValueError("semantic assessment provider request hash drift")
        try:
            request_document = json.loads(
                self.raw_provider_request_bytes.decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
            raise ValueError("semantic assessment provider request bytes invalid") from None
        if not isinstance(request_document, dict) or type(request_document.get("input")) is not str:
            raise ValueError("semantic assessment provider request body invalid")
        evaluator_input_bytes = request_document["input"].encode("utf-8")
        if self.evaluator_input_hash != _sha256(evaluator_input_bytes):
            raise ValueError("semantic assessment evaluator input hash drift")
        expected_request_bytes = canonical_json(_request_body(request_document["input"])).encode(
            "utf-8"
        )
        if self.raw_provider_request_bytes != expected_request_bytes:
            raise ValueError("semantic assessment provider request configuration drift")
        if (
            type(self.raw_response_envelope_bytes) is not bytes
            or not self.raw_response_envelope_bytes
            or len(self.raw_response_envelope_bytes) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES
        ):
            raise ValueError("semantic assessment raw envelope bytes invalid")
        if (
            type(self.structured_output_bytes) is not bytes
            or not self.structured_output_bytes
            or len(self.structured_output_bytes) > MAX_EVALUATION_OUTPUT_BYTES
        ):
            raise ValueError("semantic assessment structured output bytes invalid")
        if self.provider_response_hash != _sha256(self.raw_response_envelope_bytes):
            raise ValueError("semantic assessment response hash drift")
        if self.structured_output_hash != _sha256(self.structured_output_bytes):
            raise ValueError("semantic assessment structured output hash drift")
        if type(self.attempts) is not int or not 1 <= self.attempts <= MAX_EVALUATION_ATTEMPTS:
            raise ValueError("semantic assessment attempt count invalid")
        try:
            response_identity = validate_semantic_evaluation_response_id(self.provider_response_id)
            exact_usage = reconstruct_semantic_evaluation_usage(self.usage)
        except SemanticEvaluationContractError:
            raise ValueError("semantic assessment shared observation invalid") from None
        if response_identity != self.provider_response_id or exact_usage != self.usage:
            raise ValueError("semantic assessment shared observation drift")
        if (
            not isinstance(self.started_at_utc, datetime)
            or self.started_at_utc.tzinfo is None
            or not isinstance(self.completed_at_utc, datetime)
            or self.completed_at_utc.tzinfo is None
            or self.completed_at_utc < self.started_at_utc
        ):
            raise ValueError("semantic assessment timestamps invalid")
        started_offset = self.started_at_utc.utcoffset()
        completed_offset = self.completed_at_utc.utcoffset()
        if (
            started_offset is None
            or started_offset.total_seconds() != 0
            or completed_offset is None
            or completed_offset.total_seconds() != 0
        ):
            raise ValueError("semantic assessment timestamps must be UTC")
        candidate, response_id, usage, output_bytes = _parse_completed_response(
            self.raw_response_envelope_bytes
        )
        if (
            response_id != self.provider_response_id
            or usage != self.usage
            or output_bytes != self.structured_output_bytes
            or candidate.result is not self.result.result
            or candidate.rationale_codes != self.result.rationale_codes
            or candidate.explanation != self.result.explanation
            or candidate.human_review_required is not self.result.human_review_required
        ):
            raise ValueError("semantic assessment parsed observation drift")


@final
class OpenAIResponsesSemanticEvaluator:
    """Sealed tool-free evaluator for one fully admitted Stage-2 request."""

    __slots__ = ("_api_key", "_transport")

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("OpenAI semantic evaluator composition is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("OpenAIResponsesSemanticEvaluator is sealed")

    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.BaseTransport,
    ) -> None:
        if not _valid_api_key(api_key):
            raise OpenAISemanticEvaluatorError(
                OpenAISemanticEvaluatorErrorCode.INVALID_CREDENTIAL
            ) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_transport", transport)

    def assess(self, value: SemanticEvaluationRequest) -> SemanticAssessment:
        """Return one fully bound assessment or a fresh redacted failure."""

        try:
            return OpenAIResponsesSemanticEvaluator._assess(self, value)
        except OpenAISemanticEvaluatorError as error:
            code, status = _sanitize_public_error(error)
        except Exception:
            code = OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE
            status = None
        raise OpenAISemanticEvaluatorError(code, status_code=status) from None

    def _assess(self, value: SemanticEvaluationRequest) -> SemanticAssessment:
        try:
            if type(value) is not SemanticEvaluationRequest:
                raise SemanticEvaluationContractError("evaluation_request_wrong_type")
            request = value
            evaluator_input_bytes = semantic_evaluation_input_bytes(request)
            content = evaluator_input_bytes.decode("utf-8")
            request_bytes = canonical_json(_request_body(content)).encode("utf-8")
            if len(request_bytes) > MAX_EVALUATION_PROVIDER_REQUEST_BYTES:
                raise SemanticEvaluationContractError("evaluation_request_too_large")
        except (SemanticEvaluationContractError, UnicodeDecodeError, ValueError, TypeError):
            raise OpenAISemanticEvaluatorError(
                OpenAISemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None

        try:
            raw_request = ResponsesRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_evaluation_transport_profile(),
            )
            transport = object.__getattribute__(self, "_transport")
            raw_reply = ResponsesRawTransport(transport=transport).send(raw_request)
        except ResponsesTransportError as error:
            raise _transport_error(error) from None

        candidate, response_id, usage, output_bytes = _parse_completed_response(raw_reply.body)
        try:
            result = build_semantic_evaluation_result(request, candidate)
            return SemanticAssessment(
                result=result,
                evaluator_input_hash=_sha256(evaluator_input_bytes),
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
        except (SemanticEvaluationContractError, TypeError, ValueError):
            raise OpenAISemanticEvaluatorError(
                OpenAISemanticEvaluatorErrorCode.CANDIDATE_INVALID
            ) from None


def _request_body(content: str) -> dict[str, object]:
    return {
        "background": False,
        "input": content,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "model": SEMANTIC_EVALUATION_MODEL,
        "parallel_tool_calls": False,
        "reasoning": {"effort": "medium"},
        "store": False,
        "text": {"format": _response_format()},
        "tool_choice": "none",
        "tools": [],
        "truncation": "disabled",
    }


def _response_format() -> dict[str, object]:
    return {
        "name": "medevidence_semantic_evaluation",
        "schema": semantic_evaluation_response_schema(),
        "strict": True,
        "type": "json_schema",
    }


def _parse_completed_response(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]:
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_unique_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError):
        raise OpenAISemanticEvaluatorError(
            OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if not isinstance(document, dict):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _validate_envelope(document)
    if document.get("object") != "response" or document.get("status") != "completed":
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE)
    if document.get("error") is not None or document.get("incomplete_details") is not None:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE)
    _validate_configuration_echo(document)
    output_text = _one_output_text(document.get("output"))
    try:
        output_bytes = output_text.encode("utf-8")
        candidate = parse_semantic_evaluation_candidate(output_bytes)
    except (SemanticEvaluationContractError, UnicodeEncodeError, ValueError):
        raise OpenAISemanticEvaluatorError(
            OpenAISemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    try:
        response_id = validate_semantic_evaluation_response_id(document.get("id"))
    except SemanticEvaluationContractError:
        raise OpenAISemanticEvaluatorError(
            OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    return candidate, response_id, _usage(document.get("usage")), output_bytes


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _validate_envelope(document: dict[str, Any]) -> None:
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
    if set(document) & tool_fields:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT)
    if set(document) - allowed:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    created_at = document.get("created_at")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at < 0:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)


def _validate_configuration_echo(document: dict[str, Any]) -> None:
    if document.get("model") != SEMANTIC_EVALUATION_MODEL:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_MODEL_MISMATCH)
    if document.get("instructions") != SEMANTIC_EVALUATION_PROMPT_BYTES.decode("utf-8"):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    reasoning = document.get("reasoning")
    if (
        not isinstance(reasoning, dict)
        or set(reasoning) - {"effort", "summary"}
        or reasoning.get("effort") != SEMANTIC_EVALUATION_CONFIGURATION.reasoning_effort
        or reasoning.get("summary") is not None
    ):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    text = document.get("text")
    if (
        not isinstance(text, dict)
        or set(text) - {"format", "verbosity"}
        or text.get("format") != _response_format()
        or text.get("verbosity") not in (None, "medium")
    ):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if (
        document.get("background") is not False
        or document.get("store") is not False
        or document.get("tools") != []
        or document.get("tool_choice") != "none"
        or document.get("parallel_tool_calls") is not False
        or document.get("max_output_tokens") != MAX_EVALUATION_OUTPUT_TOKENS
        or document.get("truncation") != "disabled"
        or document.get("service_tier") not in (None, "default")
    ):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if document.get("prompt_cache_retention") not in (None, "in_memory"):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if document.get("prompt_cache_options") not in (None, {}):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
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
    if any(document.get(field) is not None for field in unrequested):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)


def _one_output_text(output: object) -> str:
    if not isinstance(output, list):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    texts: list[str] = []
    messages = 0
    for item in output:
        if not isinstance(item, dict):
            raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
        item_type = item.get("type")
        if item_type == "reasoning":
            _validate_reasoning_item(item)
            continue
        if item_type != "message":
            raise OpenAISemanticEvaluatorError(
                OpenAISemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT
            )
        messages += 1
        if set(item) != {"id", "type", "status", "role", "content"}:
            raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
        if item.get("role") != "assistant" or item.get("status") != "completed":
            raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INCOMPLETE)
        if not isinstance(item.get("id"), str) or not item["id"].startswith("msg_"):
            raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
        content = item.get("content")
        if not isinstance(content, list):
            raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
        for part in content:
            if not isinstance(part, dict):
                raise OpenAISemanticEvaluatorError(
                    OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            if part.get("type") == "refusal":
                raise OpenAISemanticEvaluatorError(
                    OpenAISemanticEvaluatorErrorCode.RESPONSE_REFUSED
                )
            if set(part) != {"type", "text", "annotations", "logprobs"}:
                raise OpenAISemanticEvaluatorError(
                    OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            if part.get("type") != "output_text" or part.get("annotations") != []:
                raise OpenAISemanticEvaluatorError(
                    OpenAISemanticEvaluatorErrorCode.RESPONSE_TOOL_OUTPUT
                )
            if part.get("logprobs") != [] or not isinstance(part.get("text"), str):
                raise OpenAISemanticEvaluatorError(
                    OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            texts.append(part["text"])
    if messages != 1 or len(texts) != 1:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    return texts[0]


def _validate_reasoning_item(item: dict[str, Any]) -> None:
    if set(item) - {"id", "type", "summary", "status"}:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if not isinstance(item.get("id"), str) or not item["id"].startswith("rs_"):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if item.get("status") not in (None, "completed") or item.get("summary") != []:
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)


def _usage(value: object) -> SemanticEvaluationUsage:
    if not isinstance(value, dict):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    input_tokens = _exact_int(value.get("input_tokens"))
    output_tokens = _exact_int(value.get("output_tokens"))
    total_tokens = _exact_int(value.get("total_tokens"))
    cached = _optional_detail(value.get("input_tokens_details"), "cached_tokens")
    reasoning = _optional_detail(value.get("output_tokens_details"), "reasoning_tokens")
    try:
        return SemanticEvaluationUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached,
            reasoning_output_tokens=reasoning,
        )
    except ValueError:
        raise OpenAISemanticEvaluatorError(
            OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None


def _exact_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    return value


def _optional_detail(value: object, key: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, dict):
        raise OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID)
    return _exact_int(value.get(key, 0))


def _evaluation_transport_profile() -> ResponsesTransportProfile:
    return ResponsesTransportProfile(
        max_request_bytes=MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
        max_response_bytes=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        max_attempts=MAX_EVALUATION_ATTEMPTS,
        retryable_statuses=tuple(sorted(SEMANTIC_EVALUATION_RETRYABLE_STATUSES)),
        total_deadline_seconds=SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        connect_timeout_seconds=SEMANTIC_EVALUATION_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=SEMANTIC_EVALUATION_READ_TIMEOUT_SECONDS,
        write_timeout_seconds=SEMANTIC_EVALUATION_WRITE_TIMEOUT_SECONDS,
        pool_timeout_seconds=SEMANTIC_EVALUATION_POOL_TIMEOUT_SECONDS,
        backoff_base_seconds=SEMANTIC_EVALUATION_BACKOFF_BASE_SECONDS,
        retry_after_cap_seconds=SEMANTIC_EVALUATION_RETRY_AFTER_CAP_SECONDS,
    )


def _transport_error(error: ResponsesTransportError) -> OpenAISemanticEvaluatorError:
    mapping = {
        ResponsesTransportErrorCode.INVALID_CREDENTIAL: (
            OpenAISemanticEvaluatorErrorCode.INVALID_CREDENTIAL
        ),
        ResponsesTransportErrorCode.REQUEST_INTEGRITY: (
            OpenAISemanticEvaluatorErrorCode.REQUEST_INTEGRITY
        ),
        ResponsesTransportErrorCode.AUTHENTICATION: OpenAISemanticEvaluatorErrorCode.AUTHENTICATION,
        ResponsesTransportErrorCode.PROVIDER_REJECTED: (
            OpenAISemanticEvaluatorErrorCode.PROVIDER_REJECTED
        ),
        ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE: (
            OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE
        ),
        ResponsesTransportErrorCode.DEADLINE_EXCEEDED: (
            OpenAISemanticEvaluatorErrorCode.DEADLINE_EXCEEDED
        ),
        ResponsesTransportErrorCode.RESPONSE_TOO_LARGE: (
            OpenAISemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE
        ),
        ResponsesTransportErrorCode.RESPONSE_INVALID: (
            OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID
        ),
    }
    if type(error) is not ResponsesTransportError:
        return OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE)
    try:
        code = object.__getattribute__(error, "code")
        status = object.__getattribute__(error, "status_code")
    except Exception:
        return OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE)
    mapped = mapping.get(code)
    if mapped is None or (
        status is not None and (type(status) is not int or not 100 <= status <= 599)
    ):
        return OpenAISemanticEvaluatorError(OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE)
    return OpenAISemanticEvaluatorError(mapped, status_code=status)


def _sanitize_public_error(
    error: OpenAISemanticEvaluatorError,
) -> tuple[OpenAISemanticEvaluatorErrorCode, int | None]:
    if type(error) is not OpenAISemanticEvaluatorError:
        return OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE, None
    try:
        code = object.__getattribute__(error, "code")
        status = object.__getattribute__(error, "status_code")
    except Exception:
        return OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE, None
    if type(code) is not OpenAISemanticEvaluatorErrorCode:
        return OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE, None
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        return OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE, None
    return code, status


def _valid_api_key(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 512
        and value.isascii()
        and all(33 <= ord(char) <= 126 for char in value)
    )


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result
