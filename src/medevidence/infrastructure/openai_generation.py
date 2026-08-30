"""Bounded synchronous OpenAI Responses transport for report generation."""

from __future__ import annotations

import json
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
from medevidence.tools.generation import (
    GENERATION_BACKOFF_BASE_SECONDS,
    GENERATION_CONFIGURATION,
    GENERATION_CONNECT_TIMEOUT_SECONDS,
    GENERATION_ENDPOINT,
    GENERATION_EXTENDED_PROMPT_CACHE,
    GENERATION_MODEL,
    GENERATION_PARALLEL_TOOL_CALLS,
    GENERATION_POOL_TIMEOUT_SECONDS,
    GENERATION_PROMPT_BYTES,
    GENERATION_READ_TIMEOUT_SECONDS,
    GENERATION_RETRY_AFTER_CAP_SECONDS,
    GENERATION_RETRYABLE_STATUSES,
    GENERATION_TOOL_CHOICE,
    GENERATION_TOTAL_DEADLINE_SECONDS,
    GENERATION_TRUNCATION,
    GENERATION_WRITE_TIMEOUT_SECONDS,
    MAX_GENERATION_ATTEMPTS,
    MAX_GENERATION_OUTPUT_TOKENS,
    MAX_PROVIDER_REQUEST_BYTES,
    MAX_PROVIDER_RESPONSE_BYTES,
    GenerationCandidate,
    GenerationContractError,
    GenerationGatewayError,
    GenerationGatewayPort,
    GenerationInput,
    GenerationProviderResult,
    GenerationUsage,
    generation_content_bytes,
    generation_response_schema,
    parse_generation_candidate,
    reconstruct_generation_input,
    reconstruct_generation_provider_result,
    validate_generation_candidate,
)


class OpenAIGenerationErrorCode(StrEnum):
    """Stable redacted failure classes for the provider boundary."""

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


class OpenAIGenerationError(GenerationGatewayError):
    """Redacted provider error that never includes request or response material."""

    __slots__ = ("status_code",)

    def __init__(
        self,
        code: OpenAIGenerationErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@final
class OpenAIResponsesGenerationGateway(GenerationGatewayPort):
    """Call one exact tool-free OpenAI Responses endpoint with bounded retries."""

    __slots__ = ("_api_key", "_transport")
    _api_key: str
    _transport: httpx.BaseTransport

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("OpenAI generation composition fields are frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("OpenAIResponsesGenerationGateway is sealed")

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport) -> None:
        if type(api_key) is not str:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.INVALID_CREDENTIAL) from None
        valid_key = (
            1 <= len(api_key) <= 512
            and api_key.isascii()
            and all(33 <= ord(char) <= 126 for char in api_key)
        )
        if not valid_key:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.INVALID_CREDENTIAL) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_transport", transport)

    def generate(self, generation_input: GenerationInput) -> GenerationProviderResult:
        """Generate one candidate while exposing only a fresh redacted failure."""

        try:
            return self._generate(generation_input)
        except OpenAIGenerationError as error:
            failure_code, failure_status = _sanitize_public_error(error)
        except Exception:
            failure_code = OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE
            failure_status = None
        raise OpenAIGenerationError(failure_code, status_code=failure_status) from None

    def _generate(self, generation_input: GenerationInput) -> GenerationProviderResult:
        """Perform the internal provider operation behind the redaction boundary."""

        try:
            exact_input = reconstruct_generation_input(generation_input)
            content = generation_content_bytes(exact_input).decode("utf-8")
            request_body = _request_body(content)
            request_bytes = canonical_json(request_body).encode("utf-8")
            if len(request_bytes) > MAX_PROVIDER_REQUEST_BYTES:
                raise GenerationContractError("generation_request_byte_limit_exceeded")
        except (GenerationContractError, UnicodeDecodeError, ValueError) as error:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.REQUEST_INTEGRITY) from error

        try:
            raw_request = ResponsesRawRequest(
                api_key=self._api_key,
                endpoint=GENERATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_generation_transport_profile(),
            )
            raw_reply = ResponsesRawTransport(transport=self._transport).send(raw_request)
        except ResponsesTransportError as error:
            raise _generation_transport_error(error) from None

        candidate, response_id, usage = _parse_completed_response(raw_reply.body, exact_input)
        try:
            return reconstruct_generation_provider_result(
                GenerationProviderResult(
                    candidate=candidate,
                    request_hash=raw_reply.request_hash,
                    response_hash=raw_reply.response_hash,
                    provider_response_id=response_id,
                    attempts=raw_reply.attempts,
                    usage=usage,
                    started_at_utc=raw_reply.started_at_utc,
                    completed_at_utc=raw_reply.completed_at_utc,
                )
            )
        except ValueError as error:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID) from error


def _request_body(content: str) -> dict[str, object]:
    if GENERATION_EXTENDED_PROMPT_CACHE:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.REQUEST_INTEGRITY)
    return {
        "background": GENERATION_CONFIGURATION.background,
        "input": content,
        "instructions": GENERATION_PROMPT_BYTES.decode("utf-8"),
        "max_output_tokens": MAX_GENERATION_OUTPUT_TOKENS,
        "model": GENERATION_MODEL,
        "parallel_tool_calls": GENERATION_PARALLEL_TOOL_CALLS,
        "reasoning": {"effort": "medium"},
        "store": GENERATION_CONFIGURATION.store,
        "text": {"format": _response_format()},
        "tool_choice": GENERATION_TOOL_CHOICE,
        "tools": [],
        "truncation": GENERATION_TRUNCATION,
    }


def _parse_completed_response(
    raw: bytes,
    generation_input: GenerationInput,
) -> tuple[GenerationCandidate, str, GenerationUsage]:
    forbidden_boms = (
        b"\xef\xbb\xbf",
        b"\xff\xfe\x00\x00",
        b"\x00\x00\xfe\xff",
        b"\xff\xfe",
        b"\xfe\xff",
    )
    if raw.startswith(forbidden_boms):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(text, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateKeyError) as error:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID) from error
    if not isinstance(document, dict):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    _validate_response_envelope(document)
    if document.get("object") != "response" or document.get("status") != "completed":
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INCOMPLETE)
    if document.get("error") is not None or document.get("incomplete_details") is not None:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INCOMPLETE)
    _validate_response_configuration(document)
    output_text = _one_output_text(document.get("output"))
    try:
        candidate = parse_generation_candidate(output_text.encode("utf-8"))
        candidate = validate_generation_candidate(generation_input, candidate)
    except (GenerationContractError, UnicodeEncodeError, ValueError) as error:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.CANDIDATE_INVALID) from error
    response_id = document.get("id")
    if not isinstance(response_id, str):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    usage = _usage(document.get("usage"))
    return candidate, response_id, usage


def _sanitize_public_error(
    error: OpenAIGenerationError,
) -> tuple[OpenAIGenerationErrorCode, int | None]:
    if type(error) is not OpenAIGenerationError:
        return OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE, None
    try:
        code = object.__getattribute__(error, "code")
        status_code = object.__getattribute__(error, "status_code")
    except Exception:
        return OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE, None
    valid_status = status_code is None or (type(status_code) is int and 100 <= status_code <= 599)
    if type(code) is not OpenAIGenerationErrorCode or not valid_status:
        return OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE, None
    return code, status_code


def _one_output_text(output: object) -> str:
    if not isinstance(output, list):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    texts: list[str] = []
    message_count = 0
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
        item_type = item["type"]
        if item_type == "reasoning":
            _validate_reasoning_item(item)
            continue
        if item_type != "message":
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
        message_count += 1
        if set(item) != {"id", "type", "status", "role", "content"}:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
        message_id = item.get("id")
        if not isinstance(message_id, str) or not message_id.startswith("msg_"):
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
        if item.get("role") != "assistant" or item.get("status") != "completed":
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INCOMPLETE)
        content = item.get("content")
        if not isinstance(content, list):
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
        for part in content:
            if not isinstance(part, dict):
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
            part_type = part.get("type")
            if part_type == "refusal":
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_REFUSED)
            if part_type != "output_text":
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
            if set(part) != {"type", "text", "annotations", "logprobs"}:
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
            if part.get("annotations") != [] or part.get("logprobs") != []:
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
            text = part.get("text")
            if not isinstance(text, str):
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
            texts.append(text)
    if message_count != 1 or len(texts) != 1:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    return texts[0]


def _validate_reasoning_item(item: dict[str, Any]) -> None:
    if set(item) - {"id", "type", "summary", "status"}:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    reasoning_id = item.get("id")
    if not isinstance(reasoning_id, str) or not reasoning_id.startswith("rs_"):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    if item.get("status") not in (None, "completed"):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INCOMPLETE)
    summary = item.get("summary")
    if not isinstance(summary, list):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    for part in summary:
        if (
            not isinstance(part, dict)
            or set(part) != {"type", "text"}
            or part.get("type") != "summary_text"
            or not isinstance(part.get("text"), str)
        ):
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)


def _validate_prompt_cache_echo(document: dict[str, Any]) -> None:
    if "prompt_cache_retention" in document:
        retention = document["prompt_cache_retention"]
        if retention != "in_memory":
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    if "prompt_cache_options" in document:
        options = document["prompt_cache_options"]
        if options not in (None, {}):
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)


def _validate_response_envelope(document: dict[str, Any]) -> None:
    allowed_fields = {
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
        "computer_calls",
        "file_search_call",
        "file_search_calls",
        "function_call",
        "function_calls",
        "mcp_call",
        "mcp_calls",
        "tool_calls",
        "web_search_call",
        "web_search_calls",
    }
    if set(document) & tool_fields:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_TOOL_OUTPUT)
    if set(document) - allowed_fields:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    created_at = document.get("created_at")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at < 0:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)


def _validate_response_configuration(document: dict[str, Any]) -> None:
    if document.get("model") != GENERATION_MODEL:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_MODEL_MISMATCH)
    if document.get("instructions") != GENERATION_PROMPT_BYTES.decode("utf-8"):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    _validate_prompt_cache_echo(document)

    reasoning = document.get("reasoning")
    if (
        not isinstance(reasoning, dict)
        or set(reasoning) - {"effort", "summary"}
        or reasoning.get("effort") != GENERATION_CONFIGURATION.reasoning_effort
        or reasoning.get("summary") is not None
    ):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)

    text = document.get("text")
    if (
        not isinstance(text, dict)
        or set(text) - {"format", "verbosity"}
        or text.get("format") != _response_format()
        or text.get("verbosity") not in (None, "medium")
    ):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)

    if (
        document.get("background") is not GENERATION_CONFIGURATION.background
        or document.get("store") is not GENERATION_CONFIGURATION.store
        or document.get("tools") != []
        or document.get("tool_choice") != GENERATION_TOOL_CHOICE
        or document.get("parallel_tool_calls") is not GENERATION_PARALLEL_TOOL_CALLS
        or document.get("max_output_tokens") != MAX_GENERATION_OUTPUT_TOKENS
        or document.get("truncation") != GENERATION_TRUNCATION
        or document.get("service_tier") not in (None, "default")
    ):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)

    unrequested_fields = {
        "audio",
        "conversation",
        "frequency_penalty",
        "include",
        "logprobs",
        "max_tool_calls",
        "metadata",
        "modalities",
        "presence_penalty",
        "previous_response_id",
        "prompt",
        "prompt_cache_key",
        "response_format",
        "safety_identifier",
        "seed",
        "stream",
        "stream_options",
        "temperature",
        "tool_resources",
        "top_logprobs",
        "top_p",
        "user",
        "web_search_options",
    }
    if any(document.get(field) is not None for field in unrequested_fields):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)


def _response_format() -> dict[str, object]:
    return {
        "name": "medevidence_generation_candidate",
        "schema": generation_response_schema(),
        "strict": True,
        "type": "json_schema",
    }


def _usage(value: object) -> GenerationUsage:
    if not isinstance(value, dict):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    input_tokens = _nonnegative_int(value.get("input_tokens"))
    output_tokens = _nonnegative_int(value.get("output_tokens"))
    total_tokens = _nonnegative_int(value.get("total_tokens"))
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    cached = _optional_detail(input_details, "cached_tokens")
    reasoning = _optional_detail(output_details, "reasoning_tokens")
    try:
        return GenerationUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_input_tokens=cached,
            reasoning_output_tokens=reasoning,
        )
    except ValueError as error:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID) from error


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    return value


def _optional_detail(value: object, key: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, dict):
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.RESPONSE_INVALID)
    return _nonnegative_int(value.get(key, 0))


def _generation_transport_profile() -> ResponsesTransportProfile:
    """Reconstruct the exact generation transport profile at the authority boundary."""

    return ResponsesTransportProfile(
        max_request_bytes=MAX_PROVIDER_REQUEST_BYTES,
        max_response_bytes=MAX_PROVIDER_RESPONSE_BYTES,
        max_attempts=MAX_GENERATION_ATTEMPTS,
        retryable_statuses=tuple(sorted(GENERATION_RETRYABLE_STATUSES)),
        total_deadline_seconds=GENERATION_TOTAL_DEADLINE_SECONDS,
        connect_timeout_seconds=GENERATION_CONNECT_TIMEOUT_SECONDS,
        read_timeout_seconds=GENERATION_READ_TIMEOUT_SECONDS,
        write_timeout_seconds=GENERATION_WRITE_TIMEOUT_SECONDS,
        pool_timeout_seconds=GENERATION_POOL_TIMEOUT_SECONDS,
        backoff_base_seconds=GENERATION_BACKOFF_BASE_SECONDS,
        retry_after_cap_seconds=GENERATION_RETRY_AFTER_CAP_SECONDS,
    )


def _generation_transport_error(error: ResponsesTransportError) -> OpenAIGenerationError:
    mapping = {
        ResponsesTransportErrorCode.INVALID_CREDENTIAL: (
            OpenAIGenerationErrorCode.INVALID_CREDENTIAL
        ),
        ResponsesTransportErrorCode.REQUEST_INTEGRITY: OpenAIGenerationErrorCode.REQUEST_INTEGRITY,
        ResponsesTransportErrorCode.AUTHENTICATION: OpenAIGenerationErrorCode.AUTHENTICATION,
        ResponsesTransportErrorCode.PROVIDER_REJECTED: OpenAIGenerationErrorCode.PROVIDER_REJECTED,
        ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE: (
            OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE
        ),
        ResponsesTransportErrorCode.DEADLINE_EXCEEDED: OpenAIGenerationErrorCode.DEADLINE_EXCEEDED,
        ResponsesTransportErrorCode.RESPONSE_TOO_LARGE: (
            OpenAIGenerationErrorCode.RESPONSE_TOO_LARGE
        ),
        ResponsesTransportErrorCode.RESPONSE_INVALID: OpenAIGenerationErrorCode.RESPONSE_INVALID,
    }
    if type(error) is not ResponsesTransportError:
        return OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE)
    try:
        code = object.__getattribute__(error, "code")
        status_code = object.__getattribute__(error, "status_code")
    except Exception:
        return OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE)
    mapped = mapping.get(code)
    if mapped is None:
        return OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE)
    valid_status = status_code is None or (type(status_code) is int and 100 <= status_code <= 599)
    if not valid_status:
        return OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE)
    return OpenAIGenerationError(mapped, status_code=status_code)


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result
