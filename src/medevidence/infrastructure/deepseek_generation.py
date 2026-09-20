"""Bounded synchronous DeepSeek Responses gateway for report generation."""

from __future__ import annotations

import hashlib
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Literal, cast, final

import httpx

from medevidence.infrastructure.deepseek_responses_transport import (
    DEEPSEEK_RESPONSES_ENDPOINT,
    DeepSeekOneOperationObservation,
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
    credential_representations,
    validate_deepseek_one_operation_observation,
)
from medevidence.tools.deepseek_generation import (
    DEEPSEEK_GENERATION_CONFIGURATION,
    MAX_DEEPSEEK_REQUEST_BYTES,
    MAX_DEEPSEEK_RESPONSE_BYTES,
    DeepSeekProviderResult,
    deepseek_generation_request_bytes,
    parse_deepseek_generation_response,
)
from medevidence.tools.generation import GenerationGatewayError, GenerationInput
from medevidence.tools.provider_attempt_framing import (
    ContentEncodingState,
    ContentLengthState,
    ContentTypeState,
    HeaderSurfaceState,
    HttpVersionState,
    TransferEncodingState,
    build_framing_observation,
    normalize_approved_headers,
)


class DeepSeekGenerationGatewayErrorCode(StrEnum):
    INVALID_CREDENTIAL = "invalid_credential"
    REQUEST_INVALID = "request_invalid"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_INVALID = "response_invalid"
    CREDENTIAL_ECHO = "credential_echo"


class DeepSeekGenerationGatewayError(GenerationGatewayError):
    """Stable credential-free gateway error."""

    def __init__(self, code: DeepSeekGenerationGatewayErrorCode) -> None:
        self.gateway_code = code
        super().__init__(code.value)


def _transport_profile() -> DeepSeekTransportProfile:
    return DeepSeekTransportProfile(
        max_request_bytes=MAX_DEEPSEEK_REQUEST_BYTES,
        max_response_bytes=MAX_DEEPSEEK_RESPONSE_BYTES,
        max_attempts=3,
        total_deadline_seconds=45,
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=10,
        pool_timeout_seconds=5,
        backoff_base_seconds=0.25,
        retry_after_cap_seconds=2,
    )


def _delay(request_hash: str, attempt: int, retry_after: str | None) -> float:
    base = 0.25 * (2 ** (attempt - 1))
    if retry_after is not None:
        try:
            parsed = float(retry_after)
            if not math.isfinite(parsed) or parsed < 0:
                raise ValueError
            base = parsed
        except ValueError:
            try:
                value = parsedate_to_datetime(retry_after)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                base = max(0.0, (value - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                base = 0.25 * (2 ** (attempt - 1))
    jitter = (
        int.from_bytes(hashlib.sha256(f"{request_hash}:{attempt}".encode()).digest()[:2], "big")
        / 65535
        * 0.01
    )
    return float(min(2.0, min(base, 2.0) + jitter))


def _clean_complete_body(observation: DeepSeekOneOperationObservation, api_key: str) -> bytes:
    validate_deepseek_one_operation_observation(observation)
    if observation.credential_echo:
        raise DeepSeekGenerationGatewayError(DeepSeekGenerationGatewayErrorCode.CREDENTIAL_ECHO)
    raw = observation.raw_body
    if (
        observation.http_status != 200
        or observation.transport_error is not None
        or observation.body_complete is not True
        or type(raw) is not bytes
        or not raw
        or len(raw) > MAX_DEEPSEEK_RESPONSE_BYTES
        or observation.observed_body_bytes_lower_bound != len(raw)
    ):
        raise DeepSeekGenerationGatewayError(DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID)
    if any(representation in raw for representation in credential_representations(api_key)):
        raise DeepSeekGenerationGatewayError(DeepSeekGenerationGatewayErrorCode.CREDENTIAL_ECHO)
    try:
        headers = normalize_approved_headers(
            observation.response_header_items,
            raw_header_field_count=observation.response_header_field_count,
        )
        framing = build_framing_observation(
            disposition="success",
            http_status=200,
            http_version=observation.response_http_version,
            headers=headers,
            raw_header_field_count=observation.response_header_field_count,
            body_complete=True,
            actual_body_byte_count=len(raw),
            raw_body_hash=None,
            raw_relative_path=None,
        )
    except (TypeError, ValueError) as error:
        raise DeepSeekGenerationGatewayError(
            DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
        ) from error
    if (
        headers.surface_state is not HeaderSurfaceState.VALID
        or framing.http_version_state not in {HttpVersionState.HTTP_1_1, HttpVersionState.HTTP_2}
        or framing.content_type_state is not ContentTypeState.APPROVED
        or framing.content_encoding_state
        not in {ContentEncodingState.ABSENT, ContentEncodingState.IDENTITY}
        or framing.transfer_encoding_state
        not in {TransferEncodingState.ABSENT, TransferEncodingState.CHUNKED}
        or framing.content_length_state not in {ContentLengthState.ABSENT, ContentLengthState.VALID}
        or (
            framing.content_length_state is ContentLengthState.VALID
            and framing.content_length_value != len(raw)
        )
        or (
            framing.content_length_state is ContentLengthState.VALID
            and framing.transfer_encoding_state is TransferEncodingState.CHUNKED
        )
    ):
        raise DeepSeekGenerationGatewayError(DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID)
    return raw


def _terminal_error(observation: DeepSeekOneOperationObservation) -> DeepSeekGenerationGatewayError:
    if observation.credential_echo:
        return DeepSeekGenerationGatewayError(DeepSeekGenerationGatewayErrorCode.CREDENTIAL_ECHO)
    mapping = {
        DeepSeekTransportErrorCode.AUTHENTICATION: (
            DeepSeekGenerationGatewayErrorCode.AUTHENTICATION_FAILED
        ),
        DeepSeekTransportErrorCode.PROVIDER_REJECTED: (
            DeepSeekGenerationGatewayErrorCode.PROVIDER_REJECTED
        ),
        DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE: (
            DeepSeekGenerationGatewayErrorCode.PROVIDER_UNAVAILABLE
        ),
        DeepSeekTransportErrorCode.DEADLINE_EXCEEDED: (
            DeepSeekGenerationGatewayErrorCode.DEADLINE_EXCEEDED
        ),
        DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE: (
            DeepSeekGenerationGatewayErrorCode.RESPONSE_TOO_LARGE
        ),
        DeepSeekTransportErrorCode.RESPONSE_INVALID: (
            DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
        ),
    }
    if observation.transport_error is not None:
        return DeepSeekGenerationGatewayError(
            mapping.get(
                observation.transport_error, DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
            )
        )
    if observation.http_status in (401, 403):
        code = DeepSeekGenerationGatewayErrorCode.AUTHENTICATION_FAILED
    elif observation.http_status in (429, 500, 502, 503, 504):
        code = DeepSeekGenerationGatewayErrorCode.PROVIDER_UNAVAILABLE
    elif observation.http_status != 200:
        code = DeepSeekGenerationGatewayErrorCode.PROVIDER_REJECTED
    else:
        code = DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
    return DeepSeekGenerationGatewayError(code)


@final
class DeepSeekResponsesGenerationGateway:
    """One approved Responses alias with finite transport retries and no import-time I/O."""

    __slots__ = ("_api_key", "_transport")
    _api_key: str
    _transport: httpx.BaseTransport

    def __init__(self, *, api_key: str, transport: httpx.BaseTransport) -> None:
        if (
            type(api_key) is not str
            or not 1 <= len(api_key) <= 512
            or not api_key.isascii()
            or any(not 33 <= ord(char) <= 126 for char in api_key)
        ):
            raise DeepSeekGenerationGatewayError(
                DeepSeekGenerationGatewayErrorCode.INVALID_CREDENTIAL
            )
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("DeepSeek generation requires explicit synchronous transport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_transport", transport)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek generation gateway is frozen")

    def generate(self, generation_input: GenerationInput) -> DeepSeekProviderResult:
        try:
            return self._generate(generation_input)
        except DeepSeekGenerationGatewayError as error:
            if type(error) is DeepSeekGenerationGatewayError:
                raise DeepSeekGenerationGatewayError(error.gateway_code) from None
        except Exception:
            pass
        raise DeepSeekGenerationGatewayError(
            DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
        ) from None

    def _generate(self, generation_input: GenerationInput) -> DeepSeekProviderResult:
        try:
            request_bytes = deepseek_generation_request_bytes(generation_input)
            request = DeepSeekRawRequest(
                api_key=self._api_key,
                endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
                request_bytes=request_bytes,
                profile=_transport_profile(),
            )
        except (TypeError, ValueError, DeepSeekTransportError) as error:
            raise DeepSeekGenerationGatewayError(
                DeepSeekGenerationGatewayErrorCode.REQUEST_INVALID
            ) from error
        clock = time.monotonic
        deadline = clock() + DEEPSEEK_GENERATION_CONFIGURATION.total_deadline_seconds
        for attempt in range(1, 4):
            if clock() >= deadline:
                raise DeepSeekGenerationGatewayError(
                    DeepSeekGenerationGatewayErrorCode.DEADLINE_EXCEEDED
                )
            observed = DeepSeekRawTransport(transport=self._transport).execute_one(
                request, absolute_deadline_monotonic=deadline, monotonic_clock=clock
            )
            validate_deepseek_one_operation_observation(observed)
            if (
                observed.http_status == 200
                and observed.transport_error is None
                and not observed.credential_echo
            ):
                raw = _clean_complete_body(observed, self._api_key)
                try:
                    candidate, response_id, usage, reported_model = (
                        parse_deepseek_generation_response(raw, generation_input)
                    )
                    return DeepSeekProviderResult(
                        candidate=candidate,
                        requested_model_alias=DEEPSEEK_GENERATION_CONFIGURATION.requested_model_alias,
                        reported_model=cast(Literal["deepseek-flash"], reported_model),
                        request_hash=request.request_hash,
                        response_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
                        raw_response=raw,
                        provider_response_id=response_id,
                        attempts=attempt,
                        usage=usage,
                        started_at_utc=observed.started_at_utc,
                        completed_at_utc=observed.completed_at_utc,
                    )
                except (TypeError, ValueError) as error:
                    raise DeepSeekGenerationGatewayError(
                        DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID
                    ) from error
            retryable = (
                observed.transport_error is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
                or (
                    observed.transport_error is None
                    and observed.http_status in (429, 500, 502, 503, 504)
                )
            )
            if retryable and attempt < 3:
                delay = _delay(request.request_hash, attempt, observed.retry_after)
                if clock() + delay >= deadline:
                    raise DeepSeekGenerationGatewayError(
                        DeepSeekGenerationGatewayErrorCode.DEADLINE_EXCEEDED
                    )
                time.sleep(delay)
                continue
            raise _terminal_error(observed)
        raise DeepSeekGenerationGatewayError(
            DeepSeekGenerationGatewayErrorCode.PROVIDER_UNAVAILABLE
        )
