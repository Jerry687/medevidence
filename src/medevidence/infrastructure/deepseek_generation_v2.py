"""Bounded synchronous DeepSeek Flash gateway for Generation V2."""

from __future__ import annotations

import hashlib
import time
from enum import StrEnum
from typing import Literal, cast, final

import httpx

from medevidence.infrastructure.deepseek_generation import (
    DeepSeekGenerationGatewayError,
    _clean_complete_body,
    _delay,
    _terminal_error,
)
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
    validate_deepseek_one_operation_observation,
)
from medevidence.tools.generation import GenerationGatewayError, GenerationInput
from medevidence.tools.generation_v2_service import (
    DEEPSEEK_GENERATION_V2_CONFIGURATION,
    DEEPSEEK_GENERATION_V2_ENDPOINT,
    DeepSeekGenerationV2ContractError,
    DeepSeekProviderResultV2,
    deepseek_generation_v2_request_bytes,
    parse_deepseek_generation_v2_response,
)
from medevidence.tools.report_validation import EvidenceInput


class DeepSeekGenerationV2GatewayErrorCode(StrEnum):
    INVALID_CREDENTIAL = "invalid_credential"
    REQUEST_INVALID = "request_invalid"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_INVALID = "response_invalid"
    CREDENTIAL_ECHO = "credential_echo"


class DeepSeekGenerationV2GatewayError(GenerationGatewayError):
    """Stable credential-free V2 gateway error."""

    def __init__(self, code: DeepSeekGenerationV2GatewayErrorCode) -> None:
        self.gateway_code = code
        super().__init__(code.value)


def _translate(error: DeepSeekGenerationGatewayError) -> DeepSeekGenerationV2GatewayError:
    try:
        code = DeepSeekGenerationV2GatewayErrorCode(error.code)
    except ValueError:
        code = DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID
    return DeepSeekGenerationV2GatewayError(code)


def _transport_profile() -> DeepSeekTransportProfile:
    config = DEEPSEEK_GENERATION_V2_CONFIGURATION
    return DeepSeekTransportProfile(
        max_request_bytes=config.max_request_bytes,
        max_response_bytes=config.max_response_bytes,
        max_attempts=config.max_attempts,
        total_deadline_seconds=config.total_deadline_seconds,
        connect_timeout_seconds=config.connect_timeout_seconds,
        read_timeout_seconds=config.read_timeout_seconds,
        write_timeout_seconds=config.write_timeout_seconds,
        pool_timeout_seconds=config.pool_timeout_seconds,
        backoff_base_seconds=config.backoff_base_seconds,
        retry_after_cap_seconds=config.retry_after_cap_seconds,
    )


@final
class DeepSeekResponsesGenerationV2Gateway:
    """One explicit Flash/none V2 gateway with no construction-time I/O."""

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
            raise DeepSeekGenerationV2GatewayError(
                DeepSeekGenerationV2GatewayErrorCode.INVALID_CREDENTIAL
            )
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("DeepSeek generation V2 requires explicit synchronous transport")
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "_transport", transport)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek generation V2 gateway is frozen")

    def generate(
        self,
        generation_input: GenerationInput,
        *,
        trusted_evidence: tuple[EvidenceInput, ...],
    ) -> DeepSeekProviderResultV2:
        try:
            return self._generate(generation_input, trusted_evidence=trusted_evidence)
        except DeepSeekGenerationV2GatewayError as error:
            raise DeepSeekGenerationV2GatewayError(error.gateway_code) from None
        except DeepSeekGenerationGatewayError as error:
            raise _translate(error) from None
        except Exception:
            raise DeepSeekGenerationV2GatewayError(
                DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID
            ) from None

    def _generate(
        self,
        generation_input: GenerationInput,
        *,
        trusted_evidence: tuple[EvidenceInput, ...],
    ) -> DeepSeekProviderResultV2:
        try:
            request_bytes = deepseek_generation_v2_request_bytes(generation_input, trusted_evidence)
            request = DeepSeekRawRequest(
                api_key=self._api_key,
                endpoint=DEEPSEEK_GENERATION_V2_ENDPOINT,
                request_bytes=request_bytes,
                profile=_transport_profile(),
            )
        except (TypeError, ValueError, DeepSeekTransportError) as error:
            raise DeepSeekGenerationV2GatewayError(
                DeepSeekGenerationV2GatewayErrorCode.REQUEST_INVALID
            ) from error
        clock = time.monotonic
        deadline = clock() + DEEPSEEK_GENERATION_V2_CONFIGURATION.total_deadline_seconds
        for attempt in range(1, 4):
            if clock() >= deadline:
                raise DeepSeekGenerationV2GatewayError(
                    DeepSeekGenerationV2GatewayErrorCode.DEADLINE_EXCEEDED
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
                        parse_deepseek_generation_v2_response(
                            raw, generation_input, trusted_evidence
                        )
                    )
                    return DeepSeekProviderResultV2(
                        candidate=candidate,
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
                except (TypeError, ValueError, DeepSeekGenerationV2ContractError) as error:
                    raise DeepSeekGenerationV2GatewayError(
                        DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID
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
                    raise DeepSeekGenerationV2GatewayError(
                        DeepSeekGenerationV2GatewayErrorCode.DEADLINE_EXCEEDED
                    )
                time.sleep(delay)
                continue
            raise _translate(_terminal_error(observed))
        raise DeepSeekGenerationV2GatewayError(
            DeepSeekGenerationV2GatewayErrorCode.PROVIDER_UNAVAILABLE
        )
