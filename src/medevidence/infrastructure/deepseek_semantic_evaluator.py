"""DeepSeek-only Responses adapter for M3-008B semantic evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast, final

import httpx
from pydantic import BaseModel

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
    validate_deepseek_one_operation_observation,
)
from medevidence.tools.provider_attempt_framing import (
    APPROVED_HEADER_NAMES,
    FramingDecision,
    FramingStatus,
    Observation,
    build_framing_observation,
    build_unavailable_observation,
    canonical_fact_free_v2_event_projection,
    classify_framing,
    fact_free_v2_event_matches,
    normalize_approved_headers,
    projection_matches,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_RESPONSE_WIRE_REASONING_FIELDS_V2,
    DEEPSEEK_RESPONSE_WIRE_REASONING_SUMMARY_VALUE_V2,
    DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
    DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
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
    SEMANTIC_EVALUATION_PROMPT_BYTES_V2,
    SEMANTIC_EVALUATION_PROMPT_BYTES_V3,
    SEMANTIC_EVALUATION_READ_TIMEOUT_SECONDS,
    SEMANTIC_EVALUATION_RETRY_AFTER_CAP_SECONDS,
    SEMANTIC_EVALUATION_RETRYABLE_STATUSES,
    SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V2,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V2,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_HASH,
    SEMANTIC_EVALUATION_V2_PROMPT_HASH_V2,
    SEMANTIC_EVALUATION_V2_PROMPT_HASH_V3,
    SEMANTIC_EVALUATION_V2_PROMPT_VERSION,
    SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V2,
    SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V3,
    SEMANTIC_EVALUATION_V2_RUBRIC_HASH,
    SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V2,
    SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V3,
    SEMANTIC_EVALUATION_V2_RUBRIC_VERSION,
    SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V2,
    SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V3,
    SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
    SEMANTIC_EVALUATION_V2_SCHEMA_VERSION,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_VERSION,
    SEMANTIC_EVALUATION_WRITE_TIMEOUT_SECONDS,
    SemanticEvaluationCandidate,
    SemanticEvaluationCandidateV2,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    SemanticEvaluationResult,
    SemanticEvaluationResultV2,
    SemanticEvaluationUsage,
    build_deepseek_semantic_evaluation_result,
    build_deepseek_semantic_evaluation_result_v2,
    build_deepseek_semantic_evaluation_result_v3,
    build_deepseek_semantic_evaluation_result_v4,
    build_semantic_evaluation_result_v2,
    build_semantic_evaluation_result_v2_low,
    build_semantic_evaluation_result_v2_low_prompt_v2,
    build_semantic_evaluation_result_v2_low_prompt_v3,
    parse_deepseek_v2_candidate_wire_bytes,
    parse_deepseek_v2_json_integer,
    parse_deepseek_v3_candidate_wire_bytes,
    parse_deepseek_v4_candidate_wire_bytes,
    parse_semantic_evaluation_candidate,
    parse_semantic_evaluation_v2_candidate,
    semantic_evaluation_input_bytes,
    semantic_evaluation_response_schema,
    semantic_evaluation_response_schema_v2,
    semantic_evaluation_v2_response_schema,
    validate_semantic_evaluation_candidate_v2_low_prompt_v3,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW as APPLICATION_LOW_PROVIDER_HASH,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V2 as APP_LOW_V2_HASH,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V3 as APP_LOW_V3_HASH,
)

DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_V1 = "m3.semantic-evaluation.v2.deepseek-responses.v1"
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION = "m3.semantic-evaluation.v2.deepseek-responses.v2"
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW = (
    "m3.semantic-evaluation.v2.deepseek-responses.v3-low"
)
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW_PROMPT_V2 = (
    "m3.semantic-evaluation.v2.deepseek-responses.v4-low-prompt-v2"
)
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW_PROMPT_V3 = (
    "m3.semantic-evaluation.v2.deepseek-responses.v5-low-prompt-v3"
)
DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW = "low"


def _deepseek_semantic_v2_provider_configuration_common(
    *,
    configuration_version: str,
    reasoning_effort: str = DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
    semantic_configuration_hash: str = SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH,
    prompt_version: str = SEMANTIC_EVALUATION_V2_PROMPT_VERSION,
    prompt_hash: str = SEMANTIC_EVALUATION_V2_PROMPT_HASH,
    rubric_version: str = SEMANTIC_EVALUATION_V2_RUBRIC_VERSION,
    rubric_hash: str = SEMANTIC_EVALUATION_V2_RUBRIC_HASH,
) -> dict[str, object]:
    return {
        "configuration_version": configuration_version,
        "endpoint": DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
        "method": DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning_effort": reasoning_effort,
        "semantic_configuration_hash": semantic_configuration_hash,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "rubric_version": rubric_version,
        "rubric_hash": rubric_hash,
        "schema_version": SEMANTIC_EVALUATION_V2_SCHEMA_VERSION,
        "schema_hash": SEMANTIC_EVALUATION_V2_SCHEMA_HASH,
        "wire_contract_version": SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_VERSION,
        "wire_contract_identity": SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
        "tools": [],
        "tool_choice": "none",
        "web_search_enabled": False,
    }


def deepseek_semantic_v2_provider_configuration_v1() -> dict[str, object]:
    """Reconstruct immutable historical Attempt007 provider profile."""

    return _deepseek_semantic_v2_provider_configuration_common(
        configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_V1
    )


def deepseek_semantic_v2_provider_configuration() -> dict[str, object]:
    """Reconstruct the active Attempt009 provider profile with bounded retry semantics."""

    return {
        **_deepseek_semantic_v2_provider_configuration_common(
            configuration_version=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION
        ),
        "body_stream_transport_error_before_deadline": "provider_unavailable",
        "coordinator_deadline_authority": "absolute_monotonic",
        "max_attempts_per_case": 3,
        "retryable_dispositions": ["retryable_status", "transport_unavailable"],
    }


def deepseek_semantic_v2_provider_configuration_low() -> dict[str, object]:
    """Fixed Attempt013 provider profile, differing from V2 only in effort and identity."""

    configuration = deepseek_semantic_v2_provider_configuration()
    configuration["configuration_version"] = DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW
    configuration["reasoning_effort"] = DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW
    return configuration


def deepseek_semantic_v2_provider_configuration_low_prompt_v2() -> dict[str, object]:
    """Fixed Attempt014 LOW provider profile with Development prompt/rubric v2."""

    configuration = deepseek_semantic_v2_provider_configuration()
    configuration.update(
        {
            "configuration_version": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW_PROMPT_V2,
            "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
            "semantic_configuration_hash": SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V2,
            "prompt_version": SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V2,
            "prompt_hash": SEMANTIC_EVALUATION_V2_PROMPT_HASH_V2,
            "rubric_version": SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V2,
            "rubric_hash": SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V2,
        }
    )
    return configuration


def deepseek_semantic_v2_provider_configuration_low_prompt_v3() -> dict[str, object]:
    """Fixed Attempt015 LOW provider profile with final Development prompt/rubric v3."""

    configuration = deepseek_semantic_v2_provider_configuration()
    configuration.update(
        {
            "configuration_version": DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIG_VERSION_LOW_PROMPT_V3,
            "reasoning_effort": DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
            "semantic_configuration_hash": SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH_V3,
            "prompt_version": SEMANTIC_EVALUATION_V2_PROMPT_VERSION_V3,
            "prompt_hash": SEMANTIC_EVALUATION_V2_PROMPT_HASH_V3,
            "rubric_version": SEMANTIC_EVALUATION_V2_RUBRIC_VERSION_V3,
            "rubric_hash": SEMANTIC_EVALUATION_V2_RUBRIC_HASH_V3,
        }
    )
    return configuration


_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_V1_BYTES = canonical_json(
    deepseek_semantic_v2_provider_configuration_v1()
).encode("utf-8")
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1 = (
    "sha256:2798cf926eb197b746fd3c321d50047c28dea5061d2f4613adb5c81b30c80b35"
)
if (
    "sha256:" + hashlib.sha256(_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_V1_BYTES).hexdigest()
    != DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_V1
):
    raise RuntimeError("historical Attempt007 provider configuration identity drift")


_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_BYTES = canonical_json(
    deepseek_semantic_v2_provider_configuration()
).encode("utf-8")
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH = (
    "sha256:" + hashlib.sha256(_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_BYTES).hexdigest()
)
_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_BYTES = canonical_json(
    deepseek_semantic_v2_provider_configuration_low()
).encode("utf-8")
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW = (
    "sha256:" + hashlib.sha256(_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_BYTES).hexdigest()
)
if DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW != APPLICATION_LOW_PROVIDER_HASH:
    raise RuntimeError("Attempt013 LOW provider configuration identity drift")
_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V2_BYTES = canonical_json(
    deepseek_semantic_v2_provider_configuration_low_prompt_v2()
).encode("utf-8")
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V2 = (
    "sha256:"
    + hashlib.sha256(_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V2_BYTES).hexdigest()
)
if DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V2 != APP_LOW_V2_HASH:
    raise RuntimeError("Attempt014 LOW prompt-v2 provider configuration identity drift")
_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V3_BYTES = canonical_json(
    deepseek_semantic_v2_provider_configuration_low_prompt_v3()
).encode("utf-8")
DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V3 = (
    "sha256:"
    + hashlib.sha256(_DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V3_BYTES).hexdigest()
)
if DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH_LOW_PROMPT_V3 != APP_LOW_V3_HASH:
    raise RuntimeError("Attempt015 LOW prompt-v3 provider configuration identity drift")


def deepseek_semantic_v2_provider_configuration_bytes() -> bytes:
    """Return immutable exact canonical bytes for the active DeepSeek V2 profile."""

    return _DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_BYTES


def deepseek_semantic_v2_provider_configuration_low_bytes() -> bytes:
    return _DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_BYTES


def deepseek_semantic_v2_provider_configuration_low_prompt_v2_bytes() -> bytes:
    return _DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V2_BYTES


def deepseek_semantic_v2_provider_configuration_low_prompt_v3_bytes() -> bytes:
    return _DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_LOW_PROMPT_V3_BYTES


def deepseek_semantic_v2_provider_configuration_v1_bytes() -> bytes:
    """Return immutable canonical historical Attempt007 provider profile bytes."""

    return _DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_V1_BYTES


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
    CREDENTIAL_ECHO = "credential_echo"


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
class DeepSeekRawSemanticObservation:
    """Legacy durable raw observation type retained for offline artifact compatibility."""

    evaluator_input_hash: str
    provider_request_hash: str
    raw_provider_request_bytes: bytes
    provider_response_hash: str
    raw_response_envelope_bytes: bytes
    status_code: int
    attempts: int
    started_at_utc: datetime
    completed_at_utc: datetime


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


@dataclass(frozen=True, slots=True)
class DeepSeekSemanticAssessmentV2:
    """Attempt009 assessment bound to semantic-only provider output and derived routing."""

    result: SemanticEvaluationResultV2
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
    """Reconstruct the exact response format used by Attempts001-004."""

    return {
        "type": "json_schema",
        "name": "medevidence_semantic_evaluation",
        "schema": semantic_evaluation_response_schema(),
    }


def deepseek_response_format_v2() -> dict[str, object]:
    """Return the shared result.v2 JSON Schema format; application parsing is strict."""

    return {
        "type": "json_schema",
        "name": "medevidence_semantic_evaluation",
        "schema": semantic_evaluation_response_schema_v2(),
    }


def deepseek_semantic_v2_response_format() -> dict[str, object]:
    """Return the sole active four-field Attempt009 structured-output format."""

    return {
        "type": "json_schema",
        "name": "medevidence_semantic_evaluation_v2",
        "schema": semantic_evaluation_v2_response_schema(),
    }


def deepseek_provider_request_semantic_v2_bytes(
    request: SemanticEvaluationRequest,
) -> bytes:
    """Return unchanged exact credential-free bytes for the active Attempt009 profile."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
        response_format=deepseek_semantic_v2_response_format(),
    )


def deepseek_provider_request_semantic_v2_low_bytes(
    request: SemanticEvaluationRequest,
) -> bytes:
    """Exact Attempt013 LOW request, with the historical prompt and schema."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
        response_format=deepseek_semantic_v2_response_format(),
        reasoning_effort=DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
    )


def deepseek_provider_request_semantic_v2_low_prompt_v2_bytes(
    request: SemanticEvaluationRequest,
) -> bytes:
    """Exact Attempt014 LOW request with Development prompt/rubric v2."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V2,
        response_format=deepseek_semantic_v2_response_format(),
        reasoning_effort=DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
    )


def deepseek_provider_request_semantic_v2_low_prompt_v3_bytes(
    request: SemanticEvaluationRequest,
) -> bytes:
    """Exact Attempt015 LOW request with final Development prompt/rubric v3."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3,
        response_format=deepseek_semantic_v2_response_format(),
        reasoning_effort=DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
    )


def deepseek_provider_request_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Reconstruct exact credential-free request bytes for immutable historical Attempt006."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES_V3,
        response_format=deepseek_response_format_v2(),
    )


def deepseek_provider_request_v3_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Reconstruct exact credential-free Attempt005 request bytes."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES_V2,
        response_format=deepseek_response_format_v2(),
    )


def deepseek_provider_request_v2_bytes(request: SemanticEvaluationRequest) -> bytes:
    """Reconstruct exact credential-free Attempt004 request bytes."""

    return _deepseek_provider_request_bytes(
        request,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES,
        response_format=deepseek_response_format(),
    )


def _deepseek_provider_request_bytes(
    request: SemanticEvaluationRequest,
    *,
    prompt_bytes: bytes,
    response_format: dict[str, object],
    reasoning_effort: str = DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
) -> bytes:

    if type(request) is not SemanticEvaluationRequest:
        raise SemanticEvaluationContractError("evaluation_request_invalid")
    content = semantic_evaluation_input_bytes(request).decode("utf-8", errors="strict")
    body = {
        "input": content,
        "instructions": prompt_bytes.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "model": DEEPSEEK_SEMANTIC_EVALUATION_MODEL,
        "reasoning": {"effort": reasoning_effort},
        "text": {"format": response_format},
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

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        total_deadline_seconds: float = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        """Perform one provider operation without response validation or hashing."""

        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started_at_utc = datetime.now(UTC)
        try:
            started_monotonic = _monotonic_value(clock)
            if absolute_deadline_monotonic is None:
                deadline_at = started_monotonic + total_deadline_seconds
            elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
                absolute_deadline_monotonic
            ):
                raise ValueError("absolute deadline is invalid")
            else:
                deadline_at = float(absolute_deadline_monotonic)
            if started_monotonic >= deadline_at:
                return _deadline_observation(started_at_utc)
            request_bytes = deepseek_provider_request_bytes(request)
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(total_deadline_seconds),
            )
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            return DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).execute_one(
                raw_request,
                absolute_deadline_monotonic=deadline_at,
                monotonic_clock=clock,
            )
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None


@final
class DeepSeekResponsesSemanticEvaluatorV2:
    """No-selector evaluator bound only to the Attempt009 semantic-family V2 profile."""

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
        raise AttributeError("DeepSeek semantic evaluator V2 is frozen")

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        total_deadline_seconds: float = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        """Perform one Attempt009 operation under the coordinator deadline."""

        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started_at_utc = datetime.now(UTC)
        try:
            started_monotonic = _monotonic_value(clock)
            if absolute_deadline_monotonic is None:
                deadline_at = started_monotonic + total_deadline_seconds
            elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
                absolute_deadline_monotonic
            ):
                raise ValueError("absolute deadline is invalid")
            else:
                deadline_at = float(absolute_deadline_monotonic)
            if started_monotonic >= deadline_at:
                return _deadline_observation(started_at_utc)
            request_bytes = deepseek_provider_request_semantic_v2_bytes(request)
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(total_deadline_seconds),
            )
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            return DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).execute_one(
                raw_request,
                absolute_deadline_monotonic=deadline_at,
                monotonic_clock=clock,
            )
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None


@final
class DeepSeekResponsesSemanticEvaluatorV2Low:
    """Fixed Attempt013 LOW evaluator with explicit transport and no profile selector."""

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
        raise AttributeError("DeepSeek semantic evaluator LOW is frozen")

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        total_deadline_seconds: float = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started_at_utc = datetime.now(UTC)
        try:
            started_monotonic = _monotonic_value(clock)
            if absolute_deadline_monotonic is None:
                deadline_at = started_monotonic + total_deadline_seconds
            elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
                absolute_deadline_monotonic
            ):
                raise ValueError("absolute deadline is invalid")
            else:
                deadline_at = float(absolute_deadline_monotonic)
            if started_monotonic >= deadline_at:
                return _deadline_observation(started_at_utc)
            request_bytes = deepseek_provider_request_semantic_v2_low_bytes(request)
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(total_deadline_seconds),
            )
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            return DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).execute_one(
                raw_request,
                absolute_deadline_monotonic=deadline_at,
                monotonic_clock=clock,
            )
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None


@final
class DeepSeekResponsesSemanticEvaluatorV2LowPromptV2:
    """Fixed Attempt014 LOW prompt-v2 evaluator with explicit transport and no profile selector."""

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
        raise AttributeError("DeepSeek semantic evaluator LOW is frozen")

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        total_deadline_seconds: float = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started_at_utc = datetime.now(UTC)
        try:
            started_monotonic = _monotonic_value(clock)
            if absolute_deadline_monotonic is None:
                deadline_at = started_monotonic + total_deadline_seconds
            elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
                absolute_deadline_monotonic
            ):
                raise ValueError("absolute deadline is invalid")
            else:
                deadline_at = float(absolute_deadline_monotonic)
            if started_monotonic >= deadline_at:
                return _deadline_observation(started_at_utc)
            request_bytes = deepseek_provider_request_semantic_v2_low_prompt_v2_bytes(request)
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(total_deadline_seconds),
            )
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            return DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).execute_one(
                raw_request,
                absolute_deadline_monotonic=deadline_at,
                monotonic_clock=clock,
            )
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None


@final
class DeepSeekResponsesSemanticEvaluatorV2LowPromptV3:
    """Fixed Attempt015 LOW prompt-v2 evaluator with explicit transport and no profile selector."""

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
        raise AttributeError("DeepSeek semantic evaluator LOW is frozen")

    def observe(
        self,
        request: SemanticEvaluationRequest,
        *,
        total_deadline_seconds: float = SEMANTIC_EVALUATION_TOTAL_DEADLINE_SECONDS,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started_at_utc = datetime.now(UTC)
        try:
            started_monotonic = _monotonic_value(clock)
            if absolute_deadline_monotonic is None:
                deadline_at = started_monotonic + total_deadline_seconds
            elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
                absolute_deadline_monotonic
            ):
                raise ValueError("absolute deadline is invalid")
            else:
                deadline_at = float(absolute_deadline_monotonic)
            if started_monotonic >= deadline_at:
                return _deadline_observation(started_at_utc)
            request_bytes = deepseek_provider_request_semantic_v2_low_prompt_v3_bytes(request)
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            raw_request = DeepSeekRawRequest(
                api_key=object.__getattribute__(self, "_api_key"),
                endpoint=DEEPSEEK_SEMANTIC_EVALUATION_ENDPOINT,
                request_bytes=request_bytes,
                profile=_profile(total_deadline_seconds),
            )
            if _monotonic_value(clock) >= deadline_at:
                return _deadline_observation(started_at_utc)
            return DeepSeekRawTransport(
                transport=object.__getattribute__(self, "_transport")
            ).execute_one(
                raw_request,
                absolute_deadline_monotonic=deadline_at,
                monotonic_clock=clock,
            )
        except DeepSeekTransportError as error:
            raise _transport_error(error) from None
        except (SemanticEvaluationContractError, TypeError, ValueError, UnicodeError):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.REQUEST_INTEGRITY
            ) from None


def _monotonic_value(monotonic_clock: Callable[[], float]) -> float:
    value = monotonic_clock()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("monotonic clock value is invalid")
    return float(value)


def _deadline_observation(started_at_utc: datetime) -> DeepSeekOneOperationObservation:
    return DeepSeekOneOperationObservation(
        http_status=None,
        approved_headers={},
        raw_body=None,
        body_complete=False,
        observed_body_bytes_lower_bound=0,
        credential_echo=False,
        transport_error=DeepSeekTransportErrorCode.DEADLINE_EXCEEDED,
        started_at_utc=started_at_utc,
        completed_at_utc=datetime.now(UTC),
    )


def finalize_deepseek_one_operation(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
) -> DeepSeekSemanticAssessment:
    """Apply unchanged transport/envelope/result validation after safe raw persistence."""

    if type(observation) is not DeepSeekOneOperationObservation:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if observation.credential_echo:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.CREDENTIAL_ECHO)
    if observation.transport_error is not None:
        mapping = {
            DeepSeekTransportErrorCode.DEADLINE_EXCEEDED: (
                DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED
            ),
            DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE: (
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE
            ),
            DeepSeekTransportErrorCode.RESPONSE_INVALID: (
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            ),
            DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE: (
                DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE
            ),
        }
        raise DeepSeekSemanticEvaluatorError(
            mapping.get(
                observation.transport_error,
                DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE,
            ),
            status_code=observation.http_status,
        )
    status = observation.http_status
    if status in {401, 403}:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.AUTHENTICATION, status_code=status
        )
    if status != 200:
        code = (
            DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE
            if status in {429, 500, 502, 503, 504}
            else DeepSeekSemanticEvaluatorErrorCode.PROVIDER_REJECTED
        )
        raise DeepSeekSemanticEvaluatorError(code, status_code=status)
    headers = observation.approved_headers
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if "transfer-encoding" in headers or headers.get("content-type") not in {
        "application/json",
        "application/json; charset=utf-8",
    }:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    raw = observation.raw_body
    if type(raw) is not bytes or not observation.body_complete:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    declared = headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) != len(raw):
                raise ValueError
        except ValueError:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            ) from None
    candidate, response_id, usage, output_bytes = parse_deepseek_completed_response(raw)
    try:
        result = build_deepseek_semantic_evaluation_result(request, candidate)
    except (SemanticEvaluationContractError, TypeError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    request_bytes = deepseek_provider_request_v2_bytes(request)
    return DeepSeekSemanticAssessment(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=output_bytes,
        structured_output_hash=_sha256(output_bytes),
        attempts=1,
        usage=usage,
        started_at_utc=observation.started_at_utc,
        completed_at_utc=observation.completed_at_utc,
    )


def _require_exact_v2_transport_observation(
    observation: DeepSeekOneOperationObservation,
) -> None:
    try:
        validate_deepseek_one_operation_observation(observation)
    except TypeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None


def build_deepseek_v2_framing_observation(
    observation: DeepSeekOneOperationObservation,
    *,
    disposition: str,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
) -> Observation:
    """Reconstruct canonical V2 framing input only from captured response facts."""

    _require_exact_v2_transport_observation(observation)
    classified_response_dispositions = {
        "authentication_failed",
        "candidate_invalid",
        "deadline_exceeded",
        "provider_rejected",
        "response_invalid",
        "response_too_large",
        "retryable_status",
        "success",
        "transport_unavailable",
        "validation_internal_failure",
    }
    if (
        observation.credential_echo
        or type(disposition) is not str
        or disposition not in classified_response_dispositions
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if observation.http_status is None:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    status = observation.http_status
    retryable_statuses = {429, 500, 502, 503, 504}
    if (
        (disposition in {"success", "candidate_invalid"} and status != 200)
        or (disposition == "retryable_status" and status not in retryable_statuses)
        or (disposition == "authentication_failed" and status not in {401, 403})
        or (
            disposition == "provider_rejected"
            and (status == 200 or status in retryable_statuses or status in {401, 403})
        )
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    items = observation.response_header_items
    if type(items) is not tuple or any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        or item[0] not in APPROVED_HEADER_NAMES
        or type(item[1]) is not str
        for item in items
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    raw = observation.raw_body
    if raw is not None and type(raw) is not bytes:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if raw_body_hash is not None and (raw is None or raw_body_hash != _sha256(raw)):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if (raw_body_hash is None) is not (raw_relative_path is None):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        return build_framing_observation(
            disposition=disposition,
            http_status=observation.http_status,
            http_version=observation.response_http_version,
            headers=normalize_approved_headers(
                items,
                raw_header_field_count=observation.response_header_field_count,
            ),
            raw_header_field_count=observation.response_header_field_count,
            body_complete=observation.body_complete,
            actual_body_byte_count=(
                len(raw) if observation.body_complete and raw is not None else None
            ),
            observed_body_bytes_lower_bound=observation.observed_body_bytes_lower_bound,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
    except (TypeError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None


def derive_deepseek_v2_disposition(
    observation: DeepSeekOneOperationObservation,
) -> str:
    """Derive the only truthful ledger disposition from captured operation facts."""

    _require_exact_v2_transport_observation(observation)
    if observation.credential_echo:
        if (
            observation.http_status is None
            or type(observation.approved_headers) is not dict
            or observation.approved_headers
            or observation.retry_after is not None
            or observation.raw_body is not None
            or observation.body_complete is not False
            or observation.response_http_version is not None
            or observation.response_header_field_count != 0
            or observation.response_header_items
        ):
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        return "credential_echo"
    error_dispositions = {
        DeepSeekTransportErrorCode.AUTHENTICATION: "authentication_failed",
        DeepSeekTransportErrorCode.PROVIDER_REJECTED: "provider_rejected",
        DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE: "transport_unavailable",
        DeepSeekTransportErrorCode.DEADLINE_EXCEEDED: "deadline_exceeded",
        DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE: "response_too_large",
        DeepSeekTransportErrorCode.RESPONSE_INVALID: "response_invalid",
    }
    if observation.transport_error is not None:
        disposition = error_dispositions.get(observation.transport_error)
        if disposition is None:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
    else:
        status = observation.http_status
        if status is None:
            disposition = "transport_unavailable"
        elif status in {401, 403}:
            disposition = "authentication_failed"
        elif status in {429, 500, 502, 503, 504}:
            disposition = "retryable_status"
        elif status != 200:
            disposition = "provider_rejected"
        else:
            disposition = "success"
    if observation.http_status is None:
        _validate_fact_free_v2_terminal(
            observation,
            disposition,
            raw_body_hash=None,
            raw_relative_path=None,
        )
    return disposition


def _validate_fact_free_v2_terminal(
    observation: DeepSeekOneOperationObservation,
    disposition: str,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
) -> None:
    if (
        raw_body_hash is not None
        or raw_relative_path is not None
        or type(observation.approved_headers) is not dict
        or observation.approved_headers
        or observation.retry_after is not None
        or observation.raw_body is not None
        or observation.body_complete is not False
        or type(observation.observed_body_bytes_lower_bound) is not int
        or observation.observed_body_bytes_lower_bound != 0
        or observation.response_http_version is not None
        or observation.response_header_field_count != 0
        or type(observation.response_header_items) is not tuple
        or observation.response_header_items
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        projection = canonical_fact_free_v2_event_projection(
            event_kind="TERMINAL", disposition=disposition
        )
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if not fact_free_v2_event_matches(projection):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)


def _credential_echo_v2_observation(
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
) -> Observation:
    if (
        observation.http_status is None
        or type(observation.approved_headers) is not dict
        or observation.approved_headers
        or observation.retry_after is not None
        or raw_body_hash is not None
        or raw_relative_path is not None
        or observation.raw_body is not None
        or observation.body_complete is not False
        or observation.response_http_version is not None
        or observation.response_header_field_count != 0
        or observation.response_header_items
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        return build_unavailable_observation(
            disposition="credential_echo", http_status=observation.http_status
        )
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None


def _raise_v2_terminal(disposition: str, status: int | None) -> None:
    mapping = {
        "authentication_failed": DeepSeekSemanticEvaluatorErrorCode.AUTHENTICATION,
        "candidate_invalid": DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID,
        "credential_echo": DeepSeekSemanticEvaluatorErrorCode.CREDENTIAL_ECHO,
        "deadline_exceeded": DeepSeekSemanticEvaluatorErrorCode.DEADLINE_EXCEEDED,
        "provider_rejected": DeepSeekSemanticEvaluatorErrorCode.PROVIDER_REJECTED,
        "response_invalid": DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID,
        "response_too_large": DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE,
        "retryable_status": DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE,
        "transport_unavailable": DeepSeekSemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE,
    }
    code = mapping.get(disposition)
    if code is None:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    raise DeepSeekSemanticEvaluatorError(code, status_code=status)


def finalize_deepseek_one_operation_v2(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessment:
    """Recompute framing and preserve exact Attempt004 V2 response authority."""

    return _finalize_deepseek_one_operation_with_authority(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_v2,
        result_builder=build_deepseek_semantic_evaluation_result_v2,
        request_bytes_builder=deepseek_provider_request_v2_bytes,
    )


def finalize_deepseek_one_operation_v3(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessment:
    """Recompute framing and apply exact Attempt005 V3 response authority."""

    return _finalize_deepseek_one_operation_with_authority(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_v3,
        result_builder=build_deepseek_semantic_evaluation_result_v3,
        request_bytes_builder=deepseek_provider_request_v3_bytes,
    )


def finalize_deepseek_one_operation_v4(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessment:
    """Recompute framing and apply exact Attempt006 V4 response authority."""

    return _finalize_deepseek_one_operation_with_authority(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_v4,
        result_builder=build_deepseek_semantic_evaluation_result_v4,
        request_bytes_builder=deepseek_provider_request_bytes,
    )


def finalize_deepseek_one_operation_semantic_v2(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessmentV2:
    """Recompute framing, parse four semantic fields, then derive application routing."""

    return _finalize_deepseek_one_operation_semantic_v2_for_profile(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_semantic_v2,
        result_builder=build_semantic_evaluation_result_v2,
        request_builder=deepseek_provider_request_semantic_v2_bytes,
    )


def finalize_deepseek_one_operation_semantic_v2_low(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessmentV2:
    """Finalize Attempt013 under fixed LOW request, echo and result provenance."""

    return _finalize_deepseek_one_operation_semantic_v2_for_profile(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_semantic_v2_low,
        result_builder=build_semantic_evaluation_result_v2_low,
        request_builder=deepseek_provider_request_semantic_v2_low_bytes,
    )


def finalize_deepseek_one_operation_semantic_v2_low_prompt_v2(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessmentV2:
    """Finalize Attempt014 under fixed LOW Development prompt/rubric v2 authority."""

    return _finalize_deepseek_one_operation_semantic_v2_for_profile(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_semantic_v2_low_prompt_v2,
        result_builder=build_semantic_evaluation_result_v2_low_prompt_v2,
        request_builder=deepseek_provider_request_semantic_v2_low_prompt_v2_bytes,
    )


def finalize_deepseek_one_operation_semantic_v2_low_prompt_v3(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None = None,
) -> DeepSeekSemanticAssessmentV2:
    """Finalize Attempt015 under fixed LOW Development prompt/rubric v3 authority."""

    return _finalize_deepseek_one_operation_semantic_v2_for_profile(
        request,
        observation,
        raw_body_hash=raw_body_hash,
        raw_relative_path=raw_relative_path,
        projected_decision=projected_decision,
        response_parser=parse_deepseek_completed_response_semantic_v2_low_prompt_v3,
        result_builder=build_semantic_evaluation_result_v2_low_prompt_v3,
        request_builder=deepseek_provider_request_semantic_v2_low_prompt_v3_bytes,
    )


def _finalize_deepseek_one_operation_semantic_v2_for_profile(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None,
    response_parser: Callable[
        [bytes], tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]
    ],
    result_builder: Callable[
        [SemanticEvaluationRequest, SemanticEvaluationCandidateV2], SemanticEvaluationResultV2
    ],
    request_builder: Callable[[SemanticEvaluationRequest], bytes],
) -> DeepSeekSemanticAssessmentV2:

    _require_exact_v2_transport_observation(observation)
    disposition = derive_deepseek_v2_disposition(observation)
    if observation.http_status is None:
        if projected_decision is not None:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        _validate_fact_free_v2_terminal(
            observation,
            disposition,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
        _raise_v2_terminal(disposition, None)
    canonical = (
        _credential_echo_v2_observation(
            observation,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
        if disposition == "credential_echo"
        else build_deepseek_v2_framing_observation(
            observation,
            disposition=disposition,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
    )
    decision = classify_framing(canonical)
    if projected_decision is not None and (
        type(projected_decision) is not FramingDecision
        or type(projected_decision.status) is not FramingStatus
        or type(projected_decision.rule_key) is not str
        or projected_decision.rule_key != decision.rule_key
        or not projection_matches(
            canonical,
            framing_status=projected_decision.status.value,
            accepted_framing_class=projected_decision.accepted_class,
            framing_rejection_code=projected_decision.rejection_code,
            framing_input_identity=projected_decision.input_identity,
        )
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if disposition != "success":
        _raise_v2_terminal(disposition, observation.http_status)
    if decision.status is not FramingStatus.ACCEPTED:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    raw = observation.raw_body
    if type(raw) is not bytes:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    candidate, response_id, usage, output_bytes = response_parser(raw)
    try:
        result = result_builder(request, candidate)
    except (SemanticEvaluationContractError, TypeError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    request_bytes = request_builder(request)
    return DeepSeekSemanticAssessmentV2(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=output_bytes,
        structured_output_hash=_sha256(output_bytes),
        attempts=1,
        usage=usage,
        started_at_utc=observation.started_at_utc,
        completed_at_utc=observation.completed_at_utc,
    )


def _finalize_deepseek_one_operation_with_authority(
    request: SemanticEvaluationRequest,
    observation: DeepSeekOneOperationObservation,
    *,
    raw_body_hash: str | None,
    raw_relative_path: str | None,
    projected_decision: FramingDecision | None,
    response_parser: Callable[
        [bytes], tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]
    ],
    result_builder: Callable[
        [SemanticEvaluationRequest, SemanticEvaluationCandidate], SemanticEvaluationResult
    ],
    request_bytes_builder: Callable[[SemanticEvaluationRequest], bytes],
) -> DeepSeekSemanticAssessment:

    _require_exact_v2_transport_observation(observation)
    disposition = derive_deepseek_v2_disposition(observation)
    if observation.http_status is None:
        if projected_decision is not None:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        _validate_fact_free_v2_terminal(
            observation,
            disposition,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
        _raise_v2_terminal(disposition, None)
    canonical = (
        _credential_echo_v2_observation(
            observation,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
        if disposition == "credential_echo"
        else build_deepseek_v2_framing_observation(
            observation,
            disposition=disposition,
            raw_body_hash=raw_body_hash,
            raw_relative_path=raw_relative_path,
        )
    )
    decision = classify_framing(canonical)
    if projected_decision is not None and (
        type(projected_decision) is not FramingDecision
        or type(projected_decision.status) is not FramingStatus
        or type(projected_decision.rule_key) is not str
        or projected_decision.rule_key != decision.rule_key
        or not projection_matches(
            canonical,
            framing_status=projected_decision.status.value,
            accepted_framing_class=projected_decision.accepted_class,
            framing_rejection_code=projected_decision.rejection_code,
            framing_input_identity=projected_decision.input_identity,
        )
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    if disposition != "success":
        _raise_v2_terminal(disposition, observation.http_status)
    if decision.status is not FramingStatus.ACCEPTED:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    raw = observation.raw_body
    if type(raw) is not bytes:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    candidate, response_id, usage, output_bytes = response_parser(raw)
    try:
        result = result_builder(request, candidate)
    except (SemanticEvaluationContractError, TypeError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    request_bytes = request_bytes_builder(request)
    return DeepSeekSemanticAssessment(
        result=result,
        evaluator_input_hash=_sha256(semantic_evaluation_input_bytes(request)),
        provider_request_hash=_sha256(request_bytes),
        raw_provider_request_bytes=request_bytes,
        provider_response_id=response_id,
        provider_response_hash=_sha256(raw),
        raw_response_envelope_bytes=raw,
        structured_output_bytes=output_bytes,
        structured_output_hash=_sha256(output_bytes),
        attempts=1,
        usage=usage,
        started_at_utc=observation.started_at_utc,
        completed_at_utc=observation.completed_at_utc,
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
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _require_valid_json_text(document)
    _validate_envelope(document)
    output_text = _one_output_text(document["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
    except UnicodeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    _validate_output_json_text_boundary(output_bytes)
    try:
        candidate = parse_semantic_evaluation_candidate(output_bytes)
    except (SemanticEvaluationContractError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    try:
        canonical = canonical_json(BaseModel.model_dump(candidate, mode="json")).encode("utf-8")
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if output_bytes != canonical:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    response_id = _response_id(document["id"])
    return candidate, response_id, _usage(document["usage"]), output_bytes


def parse_deepseek_completed_response_v2(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse the exact Attempt004 DeepSeek response envelope."""

    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE)
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _require_valid_json_text(document)
    legacy = _normalize_v2_envelope(document)
    _validate_envelope(
        legacy,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES,
        response_format=deepseek_response_format(),
    )
    output_text = _one_output_text(legacy["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
    except UnicodeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    _validate_output_json_text_boundary(output_bytes)
    try:
        candidate = parse_deepseek_v2_candidate_wire_bytes(output_bytes)
    except (SemanticEvaluationContractError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    return candidate, _response_id(legacy["id"]), _usage(legacy["usage"]), output_bytes


def parse_deepseek_completed_response_v3(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse the exact Attempt005 DeepSeek response envelope."""

    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE)
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _require_valid_json_text(document)
    legacy = _normalize_v2_envelope(document)
    _validate_envelope(
        legacy,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES_V2,
        response_format=deepseek_response_format_v2(),
    )
    output_text = _one_output_text(legacy["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
    except UnicodeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    _validate_output_json_text_boundary(output_bytes)
    try:
        candidate = parse_deepseek_v3_candidate_wire_bytes(output_bytes)
    except (SemanticEvaluationContractError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    return candidate, _response_id(legacy["id"]), _usage(legacy["usage"]), output_bytes


def parse_deepseek_completed_response_v4(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidate, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse the exact Attempt006 DeepSeek response envelope."""

    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE)
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _require_valid_json_text(document)
    legacy = _normalize_v2_envelope(document)
    _validate_envelope(
        legacy,
        prompt_bytes=SEMANTIC_EVALUATION_PROMPT_BYTES_V3,
        response_format=deepseek_response_format_v2(),
    )
    output_text = _one_output_text(legacy["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
    except UnicodeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    _validate_output_json_text_boundary(output_bytes)
    try:
        candidate = parse_deepseek_v4_candidate_wire_bytes(output_bytes)
    except (SemanticEvaluationContractError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    return candidate, _response_id(legacy["id"]), _usage(legacy["usage"]), output_bytes


def parse_deepseek_completed_response_semantic_v2(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse the active Attempt009 four-field DeepSeek response envelope."""

    return _parse_deepseek_completed_response_semantic_v2_with_effort(
        raw, DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT
    )


def parse_deepseek_completed_response_semantic_v2_low(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse the Attempt013 LOW envelope and reject HIGH echoes."""

    return _parse_deepseek_completed_response_semantic_v2_with_effort(
        raw,
        DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
    )


def parse_deepseek_completed_response_semantic_v2_low_prompt_v2(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse Attempt014 LOW while rejecting Development-v1 prompt echoes."""

    return _parse_deepseek_completed_response_semantic_v2_with_effort(
        raw,
        DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
        prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V2,
    )


def parse_deepseek_completed_response_semantic_v2_low_prompt_v3(
    raw: bytes,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:
    """Strictly parse Attempt015 LOW and reject all historical prompt echoes."""

    candidate, response_id, usage, structured = (
        _parse_deepseek_completed_response_semantic_v2_with_effort(
            raw,
            DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT_LOW,
            prompt_bytes=SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3,
        )
    )
    try:
        validated = validate_semantic_evaluation_candidate_v2_low_prompt_v3(candidate)
    except SemanticEvaluationContractError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    return validated, response_id, usage, structured


def _parse_deepseek_completed_response_semantic_v2_with_effort(
    raw: bytes,
    reasoning_effort: str,
    *,
    prompt_bytes: bytes = SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
) -> tuple[SemanticEvaluationCandidateV2, str, SemanticEvaluationUsage, bytes]:

    if type(raw) is not bytes or len(raw) > MAX_EVALUATION_PROVIDER_RESPONSE_BYTES:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE)
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    if type(document) is not dict:
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    _require_valid_json_text(document)
    normalized = _normalize_v2_envelope(document)
    _validate_envelope(
        normalized,
        prompt_bytes=prompt_bytes,
        response_format=deepseek_semantic_v2_response_format(),
        reasoning_effort=reasoning_effort,
    )
    output_text = _one_output_text(normalized["output"])
    try:
        output_bytes = output_text.encode("utf-8")
        if len(output_bytes) > MAX_EVALUATION_OUTPUT_BYTES:
            raise ValueError
    except UnicodeError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    except ValueError:
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    _validate_output_json_text_boundary(output_bytes)
    try:
        candidate = parse_semantic_evaluation_v2_candidate(output_bytes)
    except (SemanticEvaluationContractError, ValueError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.CANDIDATE_INVALID
        ) from None
    return candidate, _response_id(normalized["id"]), _usage(normalized["usage"]), output_bytes


def _normalize_v2_envelope(document: dict[str, Any]) -> dict[str, Any]:
    exact_optional: dict[str, object] = {
        "background": False,
        "completed_at": None,
        "content_filters": None,
        "frequency_penalty": 0.0,
        "max_tool_calls": None,
        "metadata": {},
        "moderation": None,
        "presence_penalty": 0.0,
        "prompt_cache_key": None,
        "prompt_cache_retention": None,
        "safety_identifier": None,
        "service_tier": "default",
        "temperature": 1.0,
        "top_logprobs": 0,
        "top_p": 1.0,
        "truncation": "disabled",
        "user": None,
    }
    legacy_fields = {
        "created_at",
        "error",
        "id",
        "incomplete_details",
        "instructions",
        "max_output_tokens",
        "model",
        "object",
        "output",
        "parallel_tool_calls",
        "previous_response_id",
        "reasoning",
        "status",
        "store",
        "text",
        "tool_choice",
        "tools",
        "usage",
    }
    if set(document) - legacy_fields - set(exact_optional):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    for field, expected in exact_optional.items():
        if field not in document:
            continue
        value = document[field]
        if field == "completed_at":
            valid = type(value) is int and value >= 0
        elif field in {"frequency_penalty", "presence_penalty", "temperature", "top_p"}:
            valid = type(value) is float and math.isfinite(value) and value == expected
        elif field == "top_logprobs":
            valid = type(value) is int and value == 0
        else:
            valid = type(value) is type(expected) and value == expected
        if not valid:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
    legacy = {key: value for key, value in document.items() if key in legacy_fields}
    reasoning = legacy.get("reasoning")
    if (
        type(reasoning) is not dict
        or set(reasoning) != set(DEEPSEEK_RESPONSE_WIRE_REASONING_FIELDS_V2)
        or reasoning[DEEPSEEK_RESPONSE_WIRE_REASONING_FIELDS_V2[1]]
        is not DEEPSEEK_RESPONSE_WIRE_REASONING_SUMMARY_VALUE_V2
    ):
        raise DeepSeekSemanticEvaluatorError(DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID)
    legacy["reasoning"] = {"effort": reasoning["effort"]}
    output = legacy.get("output")
    if type(output) is list:
        normalized_output: list[object] = []
        for source_item in output:
            if type(source_item) is not dict:
                normalized_output.append(source_item)
                continue
            item = dict(source_item)
            if (
                item.get("type") == "reasoning"
                and "encrypted_content" in item
                and type(item.pop("encrypted_content")) is not str
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            if (
                item.get("type") == "message"
                and "phase" in item
                and item.pop("phase") != "final_answer"
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            content = item.get("content")
            if type(content) is list:
                normalized_content: list[object] = []
                for source_part in content:
                    if (
                        type(source_part) is dict
                        and source_part.get("type") == "output_text"
                        and "logprobs" in source_part
                    ):
                        part = dict(source_part)
                        if part.pop("logprobs") != []:
                            raise DeepSeekSemanticEvaluatorError(
                                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                            )
                        normalized_content.append(part)
                    else:
                        normalized_content.append(source_part)
                item["content"] = normalized_content
            normalized_output.append(item)
        legacy["output"] = normalized_output
    if "text" in legacy:
        text_value = legacy["text"]
        if type(text_value) is not dict or set(text_value) - {"format", "verbosity"}:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        normalized_text = dict(text_value)
        if normalized_text.pop("verbosity", None) is not None:
            raise DeepSeekSemanticEvaluatorError(
                DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
            )
        format_value = normalized_text.get("format")
        if type(format_value) is dict:
            normalized_format = dict(format_value)
            if (
                normalized_format.pop("description", None) is not None
                or normalized_format.pop("strict", None) is not None
            ):
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                )
            normalized_text["format"] = normalized_format
        legacy["text"] = normalized_text
    return legacy


def _validate_envelope(
    document: dict[str, Any],
    *,
    prompt_bytes: bytes = SEMANTIC_EVALUATION_PROMPT_BYTES,
    response_format: dict[str, object] | None = None,
    reasoning_effort: str = DEEPSEEK_SEMANTIC_EVALUATION_REASONING_EFFORT,
) -> None:
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
        "instructions": prompt_bytes.decode("utf-8"),
        "max_output_tokens": MAX_EVALUATION_OUTPUT_TOKENS,
        "reasoning": {"effort": reasoning_effort},
        "text": {
            "format": (deepseek_response_format() if response_format is None else response_format)
        },
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


def _profile(total_deadline_seconds: float) -> DeepSeekTransportProfile:
    return DeepSeekTransportProfile(
        max_request_bytes=MAX_EVALUATION_PROVIDER_REQUEST_BYTES,
        max_response_bytes=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        max_attempts=MAX_EVALUATION_ATTEMPTS,
        total_deadline_seconds=total_deadline_seconds,
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


def _require_valid_json_text(value: object) -> None:
    """Reject decoded JSON containing text that cannot be represented as UTF-8."""

    pending = [value]
    while pending:
        item = pending.pop()
        item_type = type(item)
        if item_type is str:
            try:
                cast(str, item).encode("utf-8", errors="strict")
            except UnicodeError:
                raise DeepSeekSemanticEvaluatorError(
                    DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
                ) from None
        elif item_type is list:
            pending.extend(cast(list[object], item))
        elif item_type is dict:
            for key, child in cast(dict[object, object], item).items():
                pending.extend((key, child))


def _validate_output_json_text_boundary(raw: bytes) -> None:
    """Totalize decoder/runtime text failures before semantic candidate admission."""

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_int=parse_deepseek_v2_json_integer,
        )
    except (_DuplicateKeyError, json.JSONDecodeError):
        return
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise DeepSeekSemanticEvaluatorError(
            DeepSeekSemanticEvaluatorErrorCode.RESPONSE_INVALID
        ) from None
    _require_valid_json_text(value)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result
