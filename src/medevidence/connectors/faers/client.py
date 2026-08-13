"""Synchronous transport-injected connector for frozen FAERS count queries."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx

from medevidence.domain import FaersAggregateQueryV1

from .parsing import FaersCountPage, FaersParseError, parse_count_page
from .policy import (
    MAX_PAYLOAD_BYTES,
    REDIRECT_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    FaersConnectorConfig,
    FaersFailure,
    FaersFailureKind,
    FaersRequest,
    FaersRetryEvent,
    build_faers_request,
    parse_retry_after,
    retry_delay_seconds,
    validate_connector_config,
    validate_faers_request,
    validate_faers_url,
)

_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "content-encoding",
        "content-length",
        "content-type",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    }
)


def _canonical_content_length(value: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError("Content-Length must be a canonical ASCII decimal")
    length = int(value)
    if str(length) != value:
        raise ValueError("Content-Length must not contain signs, whitespace, or leading zeros")
    if length > MAX_PAYLOAD_BYTES:
        raise ValueError("Content-Length exceeds the frozen raw-body bound")
    return length


def _validated_response_headers(
    headers: httpx.Headers,
) -> tuple[tuple[tuple[str, str], ...], int | None]:
    raw_lengths = [value for name, value in headers.raw if name.lower() == b"content-length"]
    if len(raw_lengths) > 1:
        raise ValueError("Content-Length has duplicate raw occurrences")
    raw_transfer = [value for name, value in headers.raw if name.lower() == b"transfer-encoding"]
    if raw_lengths and raw_transfer:
        raise ValueError("Content-Length and Transfer-Encoding cannot coexist")

    declared_length: int | None = None
    canonical_length: str | None = None
    if raw_lengths:
        try:
            canonical_length = raw_lengths[0].decode("ascii", errors="strict")
        except UnicodeError as error:
            raise ValueError("Content-Length must be ASCII") from error
        declared_length = _canonical_content_length(canonical_length)

    raw_encodings = [value for name, value in headers.raw if name.lower() == b"content-encoding"]
    canonical_encoding: str | None = None
    if raw_encodings:
        if len(raw_encodings) != 1:
            raise ValueError("Content-Encoding has duplicate raw occurrences")
        try:
            raw_encoding = raw_encodings[0].decode("ascii", errors="strict")
        except UnicodeError as error:
            raise ValueError("Content-Encoding must be ASCII") from error
        canonical_encoding = raw_encoding.strip(" \t").casefold()
        if canonical_encoding != "identity" or "," in raw_encoding:
            raise ValueError("Content-Encoding must canonically equal identity")

    retained: dict[str, str] = {}
    for name, value in headers.multi_items():
        folded = name.casefold()
        if folded not in _SAFE_RESPONSE_HEADERS or folded in {
            "content-encoding",
            "content-length",
        }:
            continue
        if folded in retained:
            raise ValueError("duplicate retained response headers are forbidden")
        retained[folded] = value
    if canonical_encoding is not None:
        retained["content-encoding"] = canonical_encoding
    if canonical_length is not None:
        retained["content-length"] = canonical_length
    return tuple(sorted(retained.items())), declared_length


@dataclass(frozen=True, slots=True)
class RawFaersResponse:
    """Exact response bytes retained for immutable external snapshotting."""

    request_url: str
    final_url: str
    status_code: int
    body: bytes
    observed_at_utc: datetime
    body_complete: bool = True
    termination_reason: Literal[
        "complete_response",
        "payload_limit",
        "stream_error",
        "read_timeout",
        "clock_integrity_failure",
        "deadline_exceeded",
    ] = "complete_response"
    headers: tuple[tuple[str, str], ...] = ()
    page_number: int = 1
    attempt_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.body, bytes):
            raise TypeError("retained FAERS body must be exact bytes")
        if self.observed_at_utc.tzinfo is None or self.observed_at_utc.utcoffset() != timedelta(0):
            raise ValueError("observed_at_utc must be timezone-aware UTC")
        if self.body_complete != (self.termination_reason == "complete_response"):
            raise ValueError("body_complete must exactly match complete_response termination")
        if self.page_number < 1 or self.attempt_count < 1:
            raise ValueError("page and attempt counts must be positive")
        if not isinstance(self.headers, tuple) or self.headers != tuple(sorted(self.headers)):
            raise ValueError("retained FAERS headers must be a canonical sorted tuple")
        names: set[str] = set()
        for pair in self.headers:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise TypeError("retained FAERS header entries must be exact pairs")
            name, value = pair
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or name not in _SAFE_RESPONSE_HEADERS
                or name != name.casefold()
                or name in names
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError("retained FAERS headers violate the closed evidence profile")
            if name == "content-encoding" and value != "identity":
                raise ValueError("retained Content-Encoding must be canonical identity")
            names.add(name)
        declared = dict(self.headers).get("content-length")
        if declared is not None:
            length = _canonical_content_length(declared)
            if self.body_complete and len(self.body) != length:
                raise ValueError("complete body length differs from Content-Length")


@dataclass(frozen=True, slots=True)
class FaersConnectorResult:
    """Bounded count operation with raw response and retry evidence."""

    value: FaersCountPage | None
    failure: FaersFailure | None
    raw_responses: tuple[RawFaersResponse, ...]
    retry_events: tuple[FaersRetryEvent, ...]
    request_count: int
    pages_completed: int
    truncated: bool = False

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("connector result requires exactly one value or failure")
        if self.request_count < 0 or self.pages_completed < 0:
            raise ValueError("connector counters must be nonnegative")
        if self.pages_completed > 1:
            raise ValueError("the frozen three-PT count query completes in at most one page")
        if self.failure is not None and self.pages_completed:
            raise ValueError("failed count operation cannot claim a completed page")


@dataclass(slots=True)
class _Context:
    started_at: float
    last_monotonic: float
    raw_responses: list[RawFaersResponse] = field(default_factory=list)
    retry_events: list[FaersRetryEvent] = field(default_factory=list)
    cumulative_bytes: int = 0
    request_count: int = 0
    pages_completed: int = 0


@dataclass(frozen=True, slots=True)
class _Response:
    request_url: str
    final_url: str
    status_code: int
    body: bytes
    headers: tuple[tuple[str, str], ...]

    def header(self, name: str) -> str | None:
        folded = name.casefold()
        return next((value for key, value in self.headers if key == folded), None)


class FaersConnector:
    """FAERS adapter whose ordinary constructor requires an injected transport."""

    def __init__(
        self,
        transport: httpx.BaseTransport,
        config: FaersConnectorConfig | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must implement httpx.BaseTransport")
        self._config = validate_connector_config(config or FaersConnectorConfig())
        self._monotonic = monotonic
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0, self._config.jitter_seconds))
        self._client = httpx.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "medevidence/m1b-faers-002",
            },
        )
        self._closed = False

    @property
    def config(self) -> FaersConnectorConfig:
        return validate_connector_config(self._config)

    def close(self) -> None:
        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> FaersConnector:
        if self._closed:
            raise RuntimeError("connector is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def aggregate(self, query: FaersAggregateQueryV1) -> FaersConnectorResult:
        """Execute one exact bounded count request without cache or fallback."""

        try:
            request = build_faers_request(query)
        except (TypeError, ValueError):
            return self._input_failure()
        try:
            started_at = self._sample_monotonic()
        except (TypeError, ValueError):
            return self._integrity_failure_without_context(
                "Injected FAERS monotonic clock violated the deadline policy."
            )
        context = _Context(started_at, started_at)
        try:
            self._require_utc()
        except (TypeError, ValueError):
            return self._failed(
                context,
                FaersFailure(
                    FaersFailureKind.INTEGRITY_FAILURE,
                    "Injected FAERS clock violated the UTC evidence policy.",
                ),
            )
        response, failure = self._send_with_retries(context, request)
        if failure is not None:
            return self._failed(context, failure)
        assert response is not None
        try:
            page = parse_count_page(response.body, expected_page=1, expected_page_size=100)
        except FaersParseError:
            return self._failed(
                context,
                FaersFailure(
                    FaersFailureKind.MALFORMED_RESPONSE,
                    "FAERS response failed the frozen count-envelope parser.",
                ),
            )
        context.pages_completed = 1
        if page.next_page is not None:
            return self._failed(
                context,
                FaersFailure(
                    FaersFailureKind.MALFORMED_RESPONSE,
                    "FAERS count response omitted part of its bounded bucket collection.",
                ),
            )
        truncated = context.cumulative_bytes == self._config.max_cumulative_bytes
        return FaersConnectorResult(
            value=page,
            failure=None,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=context.pages_completed,
            truncated=truncated,
        )

    def query(self, query: FaersAggregateQueryV1) -> FaersConnectorResult:
        """Alias the structured aggregate operation without adding another mode."""

        return self.aggregate(query)

    def _send_with_retries(
        self, context: _Context, request: FaersRequest
    ) -> tuple[_Response | None, FaersFailure | None]:
        try:
            request = validate_faers_request(request)
        except (TypeError, ValueError):
            return None, FaersFailure(
                FaersFailureKind.INVALID_INPUT,
                "FAERS request violated the frozen typed design.",
            )
        for attempt in range(1, self._config.max_attempts + 1):
            response, failure = self._send_once(context, request, attempt)
            cause: FaersFailureKind
            if failure is not None:
                if failure.kind is not FaersFailureKind.TIMEOUT:
                    return None, failure
                cause = failure.kind
            else:
                assert response is not None
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return response, None
                cause = (
                    FaersFailureKind.RATE_LIMITED
                    if response.status_code == 429
                    else FaersFailureKind.UPSTREAM_UNAVAILABLE
                )
            status = response.status_code if response is not None else None
            if attempt == self._config.max_attempts:
                return None, FaersFailure(
                    FaersFailureKind.RETRY_EXHAUSTED,
                    "FAERS retry attempt budget was exhausted.",
                    status_code=status,
                    cause_kind=cause,
                )
            try:
                retry_after = (
                    parse_retry_after(
                        response.header("retry-after"),
                        now=self._require_utc(),
                        cap_seconds=self._config.max_retry_after_seconds,
                    )
                    if response is not None
                    else None
                )
                delay = (
                    retry_after
                    if retry_after is not None
                    else retry_delay_seconds(attempt, jitter=self._jitter())
                )
            except (TypeError, ValueError):
                return None, FaersFailure(
                    FaersFailureKind.INTEGRITY_FAILURE,
                    "Injected retry timing violated the frozen policy.",
                )
            try:
                remaining = self._remaining(context)
            except (TypeError, ValueError):
                return None, FaersFailure(
                    FaersFailureKind.INTEGRITY_FAILURE,
                    "Injected FAERS monotonic clock violated the deadline policy.",
                )
            if delay > remaining:
                return None, FaersFailure(
                    FaersFailureKind.RETRY_EXHAUSTED,
                    "Retry delay would exceed the FAERS acquisition deadline.",
                    status_code=status,
                    cause_kind=cause,
                )
            context.retry_events.append(
                FaersRetryEvent(attempt, delay, cause, status, retry_after is not None)
            )
            self._sleep(delay)
        raise RuntimeError("bounded retry loop terminated without a result")

    def _send_once(
        self, context: _Context, typed: FaersRequest, attempt: int
    ) -> tuple[_Response | None, FaersFailure | None]:
        try:
            remaining = self._remaining(context)
        except (TypeError, ValueError):
            return None, FaersFailure(
                FaersFailureKind.INTEGRITY_FAILURE,
                "Injected FAERS monotonic clock violated the deadline policy.",
            )
        if remaining <= 0:
            return None, FaersFailure(FaersFailureKind.TIMEOUT, "FAERS deadline expired.")
        timeout = httpx.Timeout(
            connect=min(self._config.connect_timeout_seconds, remaining),
            read=min(self._config.read_timeout_seconds, remaining),
            write=min(self._config.write_timeout_seconds, remaining),
            pool=min(self._config.pool_timeout_seconds, remaining),
        )
        try:
            canonical_url = validate_faers_url(typed.url, typed)
            request = self._client.build_request("GET", canonical_url, timeout=timeout)
            validate_faers_url(str(request.url), typed)
        except (TypeError, ValueError):
            return None, FaersFailure(
                FaersFailureKind.INVALID_INPUT,
                "FAERS URL violated the frozen request policy.",
            )
        context.request_count += 1
        try:
            response = self._client.send(request, stream=True, follow_redirects=False)
            try:
                try:
                    validate_faers_url(str(response.url), typed)
                except (TypeError, ValueError):
                    return None, FaersFailure(
                        FaersFailureKind.REDIRECT_REJECTED,
                        "FAERS final response URL violated the frozen request boundary.",
                    )
                try:
                    headers, declared_length = _validated_response_headers(response.headers)
                except ValueError:
                    return None, FaersFailure(
                        FaersFailureKind.INTEGRITY_FAILURE,
                        "FAERS response framing violated the exact-byte policy.",
                    )
                body, complete, termination = self._read_body(response, context)
                if complete and declared_length is not None and len(body) != declared_length:
                    return None, FaersFailure(
                        FaersFailureKind.INTEGRITY_FAILURE,
                        "FAERS complete raw body differs from Content-Length.",
                    )
                try:
                    observed_at = self._require_utc()
                except (TypeError, ValueError):
                    return None, FaersFailure(
                        FaersFailureKind.INTEGRITY_FAILURE,
                        "Injected FAERS clock violated the UTC evidence policy.",
                    )
                raw = RawFaersResponse(
                    request_url=str(request.url),
                    final_url=str(response.url),
                    status_code=response.status_code,
                    body=body,
                    observed_at_utc=observed_at,
                    body_complete=complete,
                    termination_reason=termination,
                    headers=headers,
                    page_number=typed.page_number,
                    attempt_count=attempt,
                )
                context.raw_responses.append(raw)
                if not complete:
                    kind = (
                        FaersFailureKind.PAYLOAD_LIMIT
                        if termination == "payload_limit"
                        else FaersFailureKind.TIMEOUT
                        if termination in {"deadline_exceeded", "read_timeout"}
                        else FaersFailureKind.INTEGRITY_FAILURE
                        if termination == "clock_integrity_failure"
                        else FaersFailureKind.TRANSPORT
                    )
                    return None, FaersFailure(
                        kind,
                        "FAERS response was not completely retained.",
                        retryable=termination == "read_timeout",
                    )
                result = _Response(
                    str(request.url), str(response.url), response.status_code, body, headers
                )
            finally:
                response.close()
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            return None, FaersFailure(
                FaersFailureKind.TIMEOUT, "FAERS transport timed out.", retryable=True
            )
        except httpx.TransportError:
            return None, FaersFailure(
                FaersFailureKind.TRANSPORT, "FAERS transport failed.", retryable=False
            )
        if result.status_code == 200:
            return result, None
        if result.status_code in REDIRECT_STATUS_CODES:
            return None, FaersFailure(
                FaersFailureKind.REDIRECT_REJECTED,
                "FAERS redirects are forbidden.",
                status_code=result.status_code,
            )
        if result.status_code in RETRYABLE_STATUS_CODES:
            return result, None
        if result.status_code in {401, 403}:
            return None, FaersFailure(
                FaersFailureKind.AUTHENTICATION_OR_AUTHORIZATION,
                "FAERS rejected authentication or authorization.",
                status_code=result.status_code,
            )
        if 400 <= result.status_code < 500:
            return None, FaersFailure(
                FaersFailureKind.CLIENT_ERROR,
                "FAERS returned a permanent client error.",
                status_code=result.status_code,
            )
        return None, FaersFailure(
            FaersFailureKind.UPSTREAM_UNAVAILABLE,
            "FAERS returned an unsupported upstream response.",
            status_code=result.status_code,
        )

    def _read_body(
        self, response: httpx.Response, context: _Context
    ) -> tuple[
        bytes,
        bool,
        Literal[
            "complete_response",
            "payload_limit",
            "stream_error",
            "read_timeout",
            "clock_integrity_failure",
            "deadline_exceeded",
        ],
    ]:
        chunks: list[bytes] = []
        response_bytes = 0
        try:
            raw_chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
            for chunk in raw_chunks:
                try:
                    remaining = self._remaining(context)
                except (TypeError, ValueError):
                    return b"".join(chunks), False, "clock_integrity_failure"
                if remaining <= 0:
                    return b"".join(chunks), False, "deadline_exceeded"
                response_remaining = self._config.max_response_bytes - response_bytes
                cumulative_remaining = self._config.max_cumulative_bytes - context.cumulative_bytes
                retained = min(response_remaining, cumulative_remaining)
                if len(chunk) > retained:
                    if retained > 0:
                        chunks.append(chunk[:retained])
                        response_bytes += retained
                        context.cumulative_bytes += retained
                    return b"".join(chunks), False, "payload_limit"
                chunks.append(chunk)
                response_bytes += len(chunk)
                context.cumulative_bytes += len(chunk)
        except httpx.ReadTimeout:
            return b"".join(chunks), False, "read_timeout"
        except httpx.TransportError:
            return b"".join(chunks), False, "stream_error"
        return b"".join(chunks), True, "complete_response"

    def _remaining(self, context: _Context) -> float:
        current = self._sample_monotonic()
        if current < context.last_monotonic:
            raise ValueError("monotonic clock must not rewind")
        context.last_monotonic = current
        elapsed = current - context.started_at
        return max(0.0, min(self._config.total_deadline_seconds, 30.0 - elapsed))

    def _sample_monotonic(self) -> float:
        try:
            value = self._monotonic()
        except Exception as error:
            raise ValueError("monotonic clock sampling failed") from error
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("monotonic clock must return a finite non-boolean number")
        return float(value)

    def _require_utc(self) -> datetime:
        value = self._utc_now()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() != timedelta(0)
        ):
            raise ValueError("injected clock must return timezone-aware UTC")
        return value

    @staticmethod
    def _input_failure() -> FaersConnectorResult:
        return FaersConnectorResult(
            value=None,
            failure=FaersFailure(FaersFailureKind.INVALID_INPUT, "FAERS input is invalid."),
            raw_responses=(),
            retry_events=(),
            request_count=0,
            pages_completed=0,
        )

    @staticmethod
    def _integrity_failure_without_context(message: str) -> FaersConnectorResult:
        return FaersConnectorResult(
            value=None,
            failure=FaersFailure(FaersFailureKind.INTEGRITY_FAILURE, message),
            raw_responses=(),
            retry_events=(),
            request_count=0,
            pages_completed=0,
        )

    @staticmethod
    def _failed(context: _Context, failure: FaersFailure) -> FaersConnectorResult:
        return FaersConnectorResult(
            value=None,
            failure=failure,
            raw_responses=tuple(context.raw_responses),
            retry_events=tuple(context.retry_events),
            request_count=context.request_count,
            pages_completed=0,
            truncated=failure.kind in {FaersFailureKind.PAYLOAD_LIMIT, FaersFailureKind.TIMEOUT},
        )


__all__ = ["FaersConnector", "FaersConnectorResult", "RawFaersResponse"]
