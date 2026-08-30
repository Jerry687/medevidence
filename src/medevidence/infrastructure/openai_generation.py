"""Bounded synchronous OpenAI Responses transport for report generation."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, final

import httpx

from medevidence.domain import Sha256Digest, canonical_json, sha256_digest
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

_SUM_PHASE_TIMEOUT_SECONDS = (
    GENERATION_CONNECT_TIMEOUT_SECONDS
    + GENERATION_READ_TIMEOUT_SECONDS
    + GENERATION_WRITE_TIMEOUT_SECONDS
    + GENERATION_POOL_TIMEOUT_SECONDS
)
_RAW_RESPONSE_CHUNK_BYTES = 16_384


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

        request_hash = sha256_digest(request_bytes)
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        attempts = 0

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                transport=_BorrowedTransport(self._transport),
                timeout=_attempt_timeout(started_monotonic),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                while attempts < MAX_GENERATION_ATTEMPTS:
                    _require_remaining_deadline(started_monotonic)
                    attempts += 1
                    try:
                        response, response_bytes = _send_bounded(
                            client,
                            request_bytes=request_bytes,
                            headers=headers,
                            started_monotonic=started_monotonic,
                        )
                    except _PreBodyTransportFailure as error:
                        if attempts >= MAX_GENERATION_ATTEMPTS:
                            raise OpenAIGenerationError(
                                OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE
                            ) from error
                        _sleep_before_retry(
                            request_hash=request_hash,
                            attempt=attempts,
                            started_monotonic=started_monotonic,
                            retry_after=None,
                        )
                        continue
                    except _PostBodyTransportFailure as error:
                        raise OpenAIGenerationError(
                            OpenAIGenerationErrorCode.RESPONSE_INVALID
                        ) from error

                    status_code = response.status_code
                    if status_code in GENERATION_RETRYABLE_STATUSES:
                        if attempts >= MAX_GENERATION_ATTEMPTS:
                            raise OpenAIGenerationError(
                                OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE,
                                status_code=status_code,
                            )
                        _sleep_before_retry(
                            request_hash=request_hash,
                            attempt=attempts,
                            started_monotonic=started_monotonic,
                            retry_after=response.headers.get("Retry-After"),
                        )
                        continue
                    if status_code in {401, 403}:
                        raise OpenAIGenerationError(
                            OpenAIGenerationErrorCode.AUTHENTICATION,
                            status_code=status_code,
                        )
                    if status_code != 200:
                        raise OpenAIGenerationError(
                            OpenAIGenerationErrorCode.PROVIDER_REJECTED,
                            status_code=status_code,
                        )

                    candidate, response_id, usage = _parse_completed_response(
                        response_bytes,
                        exact_input,
                    )
                    try:
                        return reconstruct_generation_provider_result(
                            GenerationProviderResult(
                                candidate=candidate,
                                request_hash=request_hash,
                                response_hash=sha256_digest(response_bytes),
                                provider_response_id=response_id,
                                attempts=attempts,
                                usage=usage,
                                started_at_utc=started_at,
                                completed_at_utc=datetime.now(UTC),
                            )
                        )
                    except ValueError as error:
                        raise OpenAIGenerationError(
                            OpenAIGenerationErrorCode.RESPONSE_INVALID
                        ) from error
        except OpenAIGenerationError:
            raise
        except httpx.TransportError as error:
            raise OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE) from error
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.PROVIDER_UNAVAILABLE)


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


def _send_bounded(
    client: httpx.Client,
    *,
    request_bytes: bytes,
    headers: dict[str, str],
    started_monotonic: float,
) -> tuple[httpx.Response, bytes]:
    received = False
    try:
        with client.stream(
            "POST",
            GENERATION_ENDPOINT,
            content=request_bytes,
            headers=headers,
            timeout=_attempt_timeout(started_monotonic),
        ) as response:
            request = response.request
            if request.method != "POST" or request.url != httpx.URL(GENERATION_ENDPOINT):
                raise OpenAIGenerationError(OpenAIGenerationErrorCode.REQUEST_INTEGRITY)
            body = bytearray()
            if response.headers.get("Transfer-Encoding") is not None:
                raise OpenAIGenerationError(
                    OpenAIGenerationErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            encoding = response.headers.get("Content-Encoding")
            if encoding is not None and encoding.strip().lower() != "identity":
                raise OpenAIGenerationError(
                    OpenAIGenerationErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            content_type = response.headers.get("Content-Type")
            if content_type not in {
                "application/json",
                "application/json; charset=utf-8",
            }:
                raise OpenAIGenerationError(
                    OpenAIGenerationErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            content_length = response.headers.get("Content-Length")
            declared_length: int | None = None
            if content_length is not None:
                canonical_length = content_length == "0" or (
                    content_length.isascii()
                    and content_length[:1] in "123456789"
                    and (len(content_length) == 1 or content_length[1:].isdigit())
                )
                if not canonical_length:
                    raise OpenAIGenerationError(
                        OpenAIGenerationErrorCode.RESPONSE_INVALID,
                        status_code=response.status_code,
                    )
                declared_length = int(content_length)
                if declared_length > MAX_PROVIDER_RESPONSE_BYTES:
                    raise OpenAIGenerationError(
                        OpenAIGenerationErrorCode.RESPONSE_TOO_LARGE,
                        status_code=response.status_code,
                    )
            for chunk in response.iter_raw(chunk_size=_RAW_RESPONSE_CHUNK_BYTES):
                _require_remaining_deadline(started_monotonic)
                if chunk:
                    received = True
                    if len(body) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                        raise OpenAIGenerationError(
                            OpenAIGenerationErrorCode.RESPONSE_TOO_LARGE,
                            status_code=response.status_code,
                        )
                    body.extend(chunk)
            _require_remaining_deadline(started_monotonic)
            if declared_length is not None and declared_length != len(body):
                raise OpenAIGenerationError(
                    OpenAIGenerationErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            return response, bytes(body)
    except OpenAIGenerationError:
        raise
    except httpx.TransportError as error:
        if received:
            raise _PostBodyTransportFailure from error
        raise _PreBodyTransportFailure from error


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


def _sleep_before_retry(
    *,
    request_hash: Sha256Digest,
    attempt: int,
    started_monotonic: float,
    retry_after: str | None,
) -> None:
    delay = _retry_after_seconds(retry_after)
    if delay is None:
        base = GENERATION_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
        jitter_byte = hashlib.sha256(f"{request_hash}:{attempt}".encode()).digest()[0]
        delay = base + (base * 0.1 * jitter_byte / 255.0)
    elapsed = time.monotonic() - started_monotonic
    if elapsed + delay >= GENERATION_TOTAL_DEADLINE_SECONDS:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.DEADLINE_EXCEEDED)
    time.sleep(delay)
    _require_remaining_deadline(started_monotonic)


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if seconds < 0:
            return None
    except ValueError:
        try:
            instant = parsedate_to_datetime(value)
            if instant.tzinfo is None:
                return None
            seconds = max(0.0, (instant - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return min(seconds, GENERATION_RETRY_AFTER_CAP_SECONDS)


def _require_remaining_deadline(started_monotonic: float) -> None:
    if time.monotonic() - started_monotonic >= GENERATION_TOTAL_DEADLINE_SECONDS:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.DEADLINE_EXCEEDED)


def _attempt_timeout(started_monotonic: float) -> httpx.Timeout:
    remaining = GENERATION_TOTAL_DEADLINE_SECONDS - (time.monotonic() - started_monotonic)
    if remaining <= 0:
        raise OpenAIGenerationError(OpenAIGenerationErrorCode.DEADLINE_EXCEEDED)
    scale = min(1.0, remaining / _SUM_PHASE_TIMEOUT_SECONDS)
    return httpx.Timeout(
        connect=max(0.001, GENERATION_CONNECT_TIMEOUT_SECONDS * scale),
        read=max(0.001, GENERATION_READ_TIMEOUT_SECONDS * scale),
        write=max(0.001, GENERATION_WRITE_TIMEOUT_SECONDS * scale),
        pool=max(0.001, GENERATION_POOL_TIMEOUT_SECONDS * scale),
    )


class _DuplicateKeyError(ValueError):
    pass


class _PreBodyTransportFailure(RuntimeError):
    pass


class _PostBodyTransportFailure(RuntimeError):
    pass


class _BorrowedTransport(httpx.BaseTransport):
    """Let the composition root, not a per-call client, own transport lifetime."""

    def __init__(self, transport: httpx.BaseTransport) -> None:
        self._transport = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._transport.handle_request(request)

    def close(self) -> None:
        return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result
