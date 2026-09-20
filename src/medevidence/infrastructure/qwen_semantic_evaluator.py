"""Fixed Qwen ChatCompletions semantic adapter for the V3 development rubric."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, cast
from urllib.parse import urlsplit

import httpx

from medevidence.domain import canonical_json
from medevidence.tools.semantic_evaluation import (
    MAX_EVALUATION_OUTPUT_TOKENS,
    MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
    QWEN_SEMANTIC_V2_PROVIDER_METHOD,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_HASH_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V3,
    SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V3,
    SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V3,
    SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
    SemanticEvaluationCandidateV2,
    SemanticEvaluationRequest,
    SemanticEvaluationResultV2,
    SemanticEvaluationUsage,
    build_qwen_semantic_evaluation_result_v2,
    parse_semantic_evaluation_v2_candidate,
    semantic_evaluation_input_bytes,
    semantic_evaluation_v2_candidate_wire_bytes,
    semantic_evaluation_v2_response_schema,
    validate_semantic_evaluation_candidate_v2_low_prompt_v3,
)

QWEN_MODEL: Final = "qwen3.8-max-0902"
QWEN_ENDPOINT_TEMPLATE: Final = (
    "https://<workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
)
QWEN_TOTAL_DEADLINE_SECONDS: Final = 95.0
QWEN_CONNECT_TIMEOUT_SECONDS: Final = 20.0
QWEN_READ_TIMEOUT_SECONDS: Final = 90.0


def qwen_semantic_v2_provider_configuration() -> dict[str, object]:
    """Return the fixed, credential-free provider profile."""

    return {
        "configuration_version": QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_VERSION,
        "endpoint_template": QWEN_ENDPOINT_TEMPLATE,
        "method": QWEN_SEMANTIC_V2_PROVIDER_METHOD,
        "model": QWEN_MODEL,
        "semantic_configuration_hash": SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
        "prompt_version": SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V3,
        "prompt_hash": SEMANTIC_EVALUATION_V2_PROMPT_HASH_V3,
        "rubric_version": SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V3,
        "rubric_hash": SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V3,
        "schema_version": "M3_STAGE2_SEMANTIC_RESULT_V2",
        "schema_hash": SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
        "wire_contract_identity": SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
        "wire_schema_delta": "remove rationale_codes.uniqueItems only",
        "enable_thinking": False,
        "enable_search": False,
        "temperature": 0,
        "stream": False,
        "max_completion_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "max_request_bytes": MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
        "max_response_bytes": MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        "connect_timeout_seconds": QWEN_CONNECT_TIMEOUT_SECONDS,
        "read_timeout_seconds": QWEN_READ_TIMEOUT_SECONDS,
        "total_deadline_seconds": QWEN_TOTAL_DEADLINE_SECONDS,
        "max_attempts": 3,
        "retryable_statuses": [429, 500, 502, 503, 504],
        "ambiguous_transport_retry": False,
        "backoff_base_seconds": 0.25,
        "retry_after_cap_seconds": 2,
        "jitter_max_seconds": 0.01,
    }


def qwen_semantic_v2_provider_configuration_bytes() -> bytes:
    return canonical_json(qwen_semantic_v2_provider_configuration()).encode("utf-8")


if (
    "sha256:" + hashlib.sha256(qwen_semantic_v2_provider_configuration_bytes()).hexdigest()
    != QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH
):
    raise RuntimeError("Qwen semantic provider profile identity drift")


def validated_qwen_endpoint(value: str) -> str:
    """Admit one Owner-configured Beijing workspace endpoint, without URL credentials."""

    if type(value) is not str or len(value) > 512:
        raise ValueError("Qwen endpoint invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/compatible-mode/v1/chat/completions"
        or parsed.hostname is None
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,62}\.cn-beijing\.maas\.aliyuncs\.com", parsed.hostname
        )
        or parsed.netloc != parsed.hostname
    ):
        raise ValueError("Qwen endpoint invalid")
    return value


def qwen_provider_request_semantic_v2_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Use exact V3 prompt and neutral input; adapt only vendor schema uniqueItems."""

    if type(request) is not SemanticEvaluationRequest:
        raise TypeError("Qwen semantic request type invalid")
    schema = semantic_evaluation_v2_response_schema()
    properties = cast(dict[str, dict[str, Any]], schema["properties"])
    del properties["rationale_codes"]["uniqueItems"]
    body = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3.decode("utf-8")},
            {"role": "user", "content": semantic_evaluation_input_bytes(request).decode("utf-8")},
        ],
        "enable_thinking": False,
        "enable_search": False,
        "temperature": 0,
        "stream": False,
        "max_completion_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "M3_STAGE2_SEMANTIC_RESULT_V2",
                "strict": True,
                "schema": schema,
            },
        },
    }
    raw = canonical_json(body).encode("utf-8")
    if len(raw) > MAX_EVALUATION_PROVIDER_REQUEST_BYTES:
        raise ValueError("Qwen semantic request too large")
    return raw


class QwenSemanticErrorCode(StrEnum):
    REQUEST_INVALID = "request_invalid"
    RESPONSE_INVALID = "response_invalid"
    CANDIDATE_INVALID = "candidate_invalid"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    CREDENTIAL_ECHO = "credential_echo"
    RESPONSE_TOO_LARGE = "response_too_large"


class QwenSemanticError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: QwenSemanticErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class QwenObservation:
    http_status: int | None
    raw_body: bytes | None = field(repr=False)
    body_complete: bool
    observed_body_bytes_lower_bound: int
    credential_echo: bool
    transport_error: str | None
    started_at_utc: datetime
    completed_at_utc: datetime
    retry_after: str | None


@dataclass(frozen=True, slots=True)
class QwenSemanticAssessment:
    result: SemanticEvaluationResultV2
    provider_request_hash: str
    provider_response_id: str
    provider_response_hash: str
    structured_output_bytes: bytes = field(repr=False)
    structured_output_hash: str
    usage: SemanticEvaluationUsage


def _strict_json(raw: bytes) -> Any:
    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    def invalid(_: str) -> None:
        raise ValueError("nonfinite JSON value")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 24 or count > 8192:
                raise ValueError("JSON structure bound")
            if isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID) from None


def _body_safety(raw: bytes, credential: str) -> str:
    if len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        return "response_too_large"
    text = raw.decode("utf-8", errors="replace")
    if credential in text or re.search(r"sk-[A-Za-z0-9._-]{20,250}", text):
        return "credential_echo"
    try:
        value = _strict_json(raw)
    except QwenSemanticError:
        return "response_invalid"
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and (
            credential in item or re.search(r"sk-[A-Za-z0-9._-]{20,250}", item)
        ):
            return "credential_echo"
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return "safe"


def parse_qwen_completed_response(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:
    """Reject wrong model, incomplete answers, tools, thinking and malformed usage."""

    envelope = _strict_json(raw)
    if type(envelope) is not dict or envelope.get("model") != QWEN_MODEL:
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    response_id = envelope.get("id")
    choices = envelope.get("choices")
    if (
        envelope.get("object") != "chat.completion"
        or type(response_id) is not str
        or not 1 <= len(response_id) <= 256
        or type(choices) is not list
        or len(choices) != 1
        or type(choices[0]) is not dict
        or choices[0].get("finish_reason") != "stop"
    ):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    message = choices[0].get("message")
    if (
        type(message) is not dict
        or message.get("role") != "assistant"
        or message.get("tool_calls")
        or message.get("function_call")
        or message.get("refusal")
        or message.get("reasoning_content") not in (None, "")
        or type(message.get("content")) is not str
    ):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    candidate_value = _strict_json(message["content"].encode("utf-8"))
    if type(candidate_value) is not dict or set(candidate_value) != {
        "schema_version",
        "result",
        "rationale_codes",
        "explanation",
    }:
        raise QwenSemanticError(QwenSemanticErrorCode.CANDIDATE_INVALID)
    try:
        candidate = SemanticEvaluationCandidateV2.model_validate_json(
            canonical_json(candidate_value).encode("utf-8"), strict=True
        )
        structured = semantic_evaluation_v2_candidate_wire_bytes(candidate)
        checked = validate_semantic_evaluation_candidate_v2_low_prompt_v3(
            parse_semantic_evaluation_v2_candidate(structured)
        )
    except (TypeError, ValueError):
        raise QwenSemanticError(QwenSemanticErrorCode.CANDIDATE_INVALID) from None
    usage = envelope.get("usage")
    if type(usage) is not dict:
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in fields):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    details = usage.get("completion_tokens_details") or {}
    if (
        usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
        or usage["completion_tokens"] > MAX_EVALUATION_OUTPUT_TOKENS
        or type(details) is not dict
        or details.get("reasoning_tokens", 0) != 0
    ):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    try:
        parsed_usage = SemanticEvaluationUsage(
            input_tokens=usage["prompt_tokens"],
            output_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            cached_input_tokens=0,
            reasoning_output_tokens=0,
        )
    except ValueError:
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID) from None
    return checked, response_id, parsed_usage, structured


def finalize_qwen_observation(
    request: SemanticEvaluationRequest, observation: QwenObservation
) -> QwenSemanticAssessment:
    """Build a genuine Qwen result only from a complete, safe 200 response."""

    if type(observation) is not QwenObservation:
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    if observation.credential_echo:
        raise QwenSemanticError(QwenSemanticErrorCode.CREDENTIAL_ECHO)
    if (
        observation.http_status != 200
        or observation.body_complete is not True
        or type(observation.raw_body) is not bytes
    ):
        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
    candidate, response_id, usage, structured = parse_qwen_completed_response(observation.raw_body)
    try:
        result = build_qwen_semantic_evaluation_result_v2(request, candidate)
    except (TypeError, ValueError):
        raise QwenSemanticError(QwenSemanticErrorCode.CANDIDATE_INVALID) from None
    request_bytes = qwen_provider_request_semantic_v2_bytes(request)
    return QwenSemanticAssessment(
        result=result,
        provider_request_hash="sha256:" + hashlib.sha256(request_bytes).hexdigest(),
        provider_response_id=response_id,
        provider_response_hash="sha256:" + hashlib.sha256(observation.raw_body).hexdigest(),
        structured_output_bytes=structured,
        structured_output_hash="sha256:" + hashlib.sha256(structured).hexdigest(),
        usage=usage,
    )


class QwenChatSemanticEvaluatorV2:
    """One-operation, bounded HTTP evaluator; journal controls retries and replay."""

    __slots__ = ("_api_key", "_client", "_closed", "_endpoint", "_loop", "_thread")
    _api_key: str
    _client: httpx.AsyncClient
    _closed: bool
    _endpoint: str
    _loop: asyncio.AbstractEventLoop
    _thread: threading.Thread

    def __init__(self, *, api_key: str, endpoint: str, transport: httpx.AsyncBaseTransport) -> None:
        if type(api_key) is not str or not re.fullmatch(r"sk-[A-Za-z0-9._-]{20,250}", api_key):
            raise QwenSemanticError(QwenSemanticErrorCode.REQUEST_INVALID)
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_endpoint", validated_qwen_endpoint(endpoint))
        object.__setattr__(
            self,
            "_client",
            httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(connect=20, read=90, write=10, pool=5),
            ),
        )
        object.__setattr__(self, "_loop", asyncio.new_event_loop())
        object.__setattr__(self, "_closed", False)
        object.__setattr__(
            self, "_thread", threading.Thread(target=self._loop.run_forever, daemon=True)
        )
        self._thread.start()

    @property
    def endpoint_identity(self) -> str:
        """Bind actual workspace host to cache operations without storing its value."""

        return "sha256:" + hashlib.sha256(self._endpoint.encode("utf-8")).hexdigest()

    def raw_response_is_safe(self, raw: bytes) -> bool:
        """Recheck cached raw before any replay-derived semantic result."""

        return _body_safety(raw, self._api_key) == "safe"

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Qwen semantic evaluator authority is frozen")

    def close(self) -> None:
        """Close the private pooled client and its event loop."""

        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        try:
            asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result(timeout=5)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            if not self._thread.is_alive():
                self._loop.close()

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        absolute_deadline_monotonic: float,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> QwenObservation:
        started = datetime.now(UTC)
        remaining = absolute_deadline_monotonic - monotonic_clock()
        if not math.isfinite(remaining) or remaining <= 0:
            raise QwenSemanticError(QwenSemanticErrorCode.DEADLINE_EXCEEDED)
        if self._closed:
            raise QwenSemanticError(QwenSemanticErrorCode.TRANSPORT_UNAVAILABLE)
        body = qwen_provider_request_semantic_v2_bytes(request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        task = asyncio.run_coroutine_threadsafe(
            self._observe_async(body, headers, started, remaining), self._loop
        )
        try:
            return task.result(timeout=remaining + 1)
        except concurrent.futures.TimeoutError:
            task.cancel()
            raise QwenSemanticError(QwenSemanticErrorCode.DEADLINE_EXCEEDED) from None

    async def _observe_async(
        self,
        body: bytes,
        headers: dict[str, str],
        started: datetime,
        remaining: float,
    ) -> QwenObservation:
        status: int | None = None
        chunks: list[bytes] = []
        size = 0
        retry_after: str | None = None
        try:
            async with asyncio.timeout(remaining):
                async with self._client.stream(
                    "POST",
                    self._endpoint,
                    content=body,
                    headers=headers,
                    timeout=httpx.Timeout(
                        connect=min(20, remaining),
                        read=min(90, remaining),
                        write=min(10, remaining),
                        pool=min(5, remaining),
                    ),
                ) as response:
                    status = response.status_code
                    retry_after = response.headers.get("retry-after")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_INVALID)
                    stream = (
                        (response.content,)
                        if response.is_stream_consumed
                        else response.aiter_raw(chunk_size=16384)
                    )
                    if isinstance(stream, tuple):
                        for chunk in stream:
                            size += len(chunk)
                            if size > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
                                raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_TOO_LARGE)
                            chunks.append(chunk)
                    else:
                        async for chunk in stream:
                            size += len(chunk)
                            if size > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
                                raise QwenSemanticError(QwenSemanticErrorCode.RESPONSE_TOO_LARGE)
                            chunks.append(chunk)
            raw = b"".join(chunks)
            safety = _body_safety(raw, self._api_key)
            return QwenObservation(
                status,
                raw if safety == "safe" else None,
                True,
                size,
                safety == "credential_echo",
                None if safety in ("safe", "credential_echo") else safety,
                started,
                datetime.now(UTC),
                retry_after,
            )
        except (httpx.TransportError, TimeoutError) as error:
            return QwenObservation(
                status,
                None,
                False,
                size,
                False,
                (
                    "deadline_exceeded"
                    if isinstance(error, TimeoutError)
                    else "transport_unavailable"
                ),
                started,
                datetime.now(UTC),
                retry_after,
            )
        except QwenSemanticError as error:
            return QwenObservation(
                status,
                None,
                False,
                size,
                False,
                error.code.value,
                started,
                datetime.now(UTC),
                retry_after,
            )
