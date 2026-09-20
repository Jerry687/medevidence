"""Hardened synchronous transport for the exact DeepSeek Responses endpoint."""

from __future__ import annotations

import base64
import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast, final
from urllib.parse import quote_from_bytes

import httpx

from medevidence.domain import Sha256Digest, sha256_digest
from medevidence.tools.provider_attempt_framing import (
    APPROVED_HEADER_NAMES,
    normalize_approved_headers,
    raw_body_persistence_permitted,
)

DEEPSEEK_RESPONSES_ENDPOINT = "https://api.deepseek.com/responses"
_CHUNK_BYTES = 16_384
_RETRYABLE = (429, 500, 502, 503, 504)


class DeepSeekTransportErrorCode(StrEnum):
    INVALID_CREDENTIAL = "invalid_credential"
    REQUEST_INTEGRITY = "request_integrity"
    AUTHENTICATION = "authentication_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_INVALID = "response_invalid"


class DeepSeekTransportError(RuntimeError):
    """Fresh redacted transport failure without request, response, or credential data."""

    __slots__ = ("code", "status_code")

    def __init__(self, code: DeepSeekTransportErrorCode, *, status_code: int | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@final
class DeepSeekTransportProfile:
    __slots__ = (
        "backoff_base_seconds",
        "connect_timeout_seconds",
        "max_attempts",
        "max_request_bytes",
        "max_response_bytes",
        "pool_timeout_seconds",
        "read_timeout_seconds",
        "retry_after_cap_seconds",
        "retryable_statuses",
        "total_deadline_seconds",
        "write_timeout_seconds",
    )
    max_request_bytes: int
    max_response_bytes: int
    max_attempts: int
    retryable_statuses: tuple[int, ...]
    total_deadline_seconds: float
    connect_timeout_seconds: float
    read_timeout_seconds: float
    write_timeout_seconds: float
    pool_timeout_seconds: float
    backoff_base_seconds: float
    retry_after_cap_seconds: float

    def __init__(
        self,
        *,
        max_request_bytes: int,
        max_response_bytes: int,
        max_attempts: int,
        total_deadline_seconds: float,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        write_timeout_seconds: float,
        pool_timeout_seconds: float,
        backoff_base_seconds: float,
        retry_after_cap_seconds: float,
        retryable_statuses: tuple[int, ...] = _RETRYABLE,
    ) -> None:
        integers = (max_request_bytes, max_response_bytes, max_attempts)
        if any(type(value) is not int or value <= 0 for value in integers):
            raise TypeError("transport integer bounds must be positive exact integers")
        if max_attempts > 3 or max_request_bytes > 262_144 or max_response_bytes > 131_072:
            raise ValueError("transport bound exceeds the M3-008B profile")
        if retryable_statuses != _RETRYABLE:
            raise ValueError("retryable statuses drift")
        times = (
            total_deadline_seconds,
            connect_timeout_seconds,
            read_timeout_seconds,
            write_timeout_seconds,
            pool_timeout_seconds,
            backoff_base_seconds,
            retry_after_cap_seconds,
        )
        maxima = (45, 5, 30, 10, 5, 0.25, 2)
        if any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value <= 0
            or value > maximum
            for value, maximum in zip(times, maxima, strict=True)
        ):
            raise ValueError("transport time bound is invalid")
        object.__setattr__(self, "max_request_bytes", max_request_bytes)
        object.__setattr__(self, "max_response_bytes", max_response_bytes)
        object.__setattr__(self, "max_attempts", max_attempts)
        object.__setattr__(self, "retryable_statuses", retryable_statuses)
        object.__setattr__(self, "total_deadline_seconds", float(total_deadline_seconds))
        object.__setattr__(self, "connect_timeout_seconds", float(connect_timeout_seconds))
        object.__setattr__(self, "read_timeout_seconds", float(read_timeout_seconds))
        object.__setattr__(self, "write_timeout_seconds", float(write_timeout_seconds))
        object.__setattr__(self, "pool_timeout_seconds", float(pool_timeout_seconds))
        object.__setattr__(self, "backoff_base_seconds", float(backoff_base_seconds))
        object.__setattr__(self, "retry_after_cap_seconds", float(retry_after_cap_seconds))

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek transport profile is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("DeepSeekTransportProfile is sealed")


@final
class DeepSeekRawRequest:
    __slots__ = ("_api_key", "endpoint", "profile", "request_bytes", "request_hash")
    _api_key: str
    endpoint: str
    profile: DeepSeekTransportProfile
    request_bytes: bytes
    request_hash: Sha256Digest

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        request_bytes: bytes,
        profile: DeepSeekTransportProfile,
    ) -> None:
        if not _valid_key(api_key):
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.INVALID_CREDENTIAL)
        if type(endpoint) is not str or endpoint != DEEPSEEK_RESPONSES_ENDPOINT:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        try:
            url = httpx.URL(endpoint)
        except Exception:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY) from None
        if (
            url.scheme != "https"
            or url.host != "api.deepseek.com"
            or url.path != "/responses"
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        if type(profile) is not DeepSeekTransportProfile:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        if (
            type(request_bytes) is not bytes
            or not request_bytes
            or len(request_bytes) > profile.max_request_bytes
        ):
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        _validate_json(request_bytes)
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "request_bytes", request_bytes)
        object.__setattr__(self, "request_hash", sha256_digest(request_bytes))

    def __repr__(self) -> str:
        return "DeepSeekRawRequest(endpoint=<fixed>, request_bytes=<redacted>, profile=<bounded>)"

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek raw request is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("DeepSeekRawRequest is sealed")


@final
class DeepSeekRawReply:
    __slots__ = (
        "attempts",
        "body",
        "completed_at_utc",
        "request_hash",
        "response_hash",
        "started_at_utc",
        "status_code",
    )
    status_code: int
    body: bytes
    attempts: int
    request_hash: Sha256Digest
    response_hash: Sha256Digest
    started_at_utc: datetime
    completed_at_utc: datetime

    def __init__(
        self,
        *,
        body: bytes,
        attempts: int,
        request_hash: Sha256Digest,
        started_at_utc: datetime,
        completed_at_utc: datetime,
    ) -> None:
        if type(body) is not bytes or type(attempts) is not int or not 1 <= attempts <= 3:
            raise ValueError("DeepSeek raw reply fields are invalid")
        if completed_at_utc < started_at_utc:
            raise ValueError("DeepSeek raw reply timestamps are reversed")
        object.__setattr__(self, "status_code", 200)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "response_hash", sha256_digest(body))
        object.__setattr__(self, "started_at_utc", started_at_utc)
        object.__setattr__(self, "completed_at_utc", completed_at_utc)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek raw reply is frozen")


@final
class DeepSeekOneOperationObservation:
    """Bounded in-memory result of exactly one HTTP operation, before validation."""

    __slots__ = (
        "approved_headers",
        "body_complete",
        "completed_at_utc",
        "credential_echo",
        "http_status",
        "observed_body_bytes_lower_bound",
        "raw_body",
        "response_header_field_count",
        "response_header_items",
        "response_http_version",
        "retry_after",
        "started_at_utc",
        "transport_error",
    )
    http_status: int | None
    approved_headers: dict[str, str]
    raw_body: bytes | None
    retry_after: str | None
    response_http_version: str | None
    response_header_items: tuple[tuple[str, str], ...]
    response_header_field_count: int
    body_complete: bool
    observed_body_bytes_lower_bound: int
    credential_echo: bool
    transport_error: DeepSeekTransportErrorCode | None
    started_at_utc: datetime
    completed_at_utc: datetime

    def __init__(
        self,
        *,
        http_status: int | None,
        approved_headers: dict[str, str],
        raw_body: bytes | None,
        body_complete: bool,
        observed_body_bytes_lower_bound: int,
        credential_echo: bool,
        transport_error: DeepSeekTransportErrorCode | None,
        started_at_utc: datetime,
        completed_at_utc: datetime,
        retry_after: str | None = None,
        response_http_version: str | None = None,
        response_header_items: tuple[tuple[str, str], ...] = (),
        response_header_field_count: int = 0,
    ) -> None:
        _validate_deepseek_observation_values(
            http_status=http_status,
            approved_headers=approved_headers,
            raw_body=raw_body,
            body_complete=body_complete,
            observed_body_bytes_lower_bound=observed_body_bytes_lower_bound,
            credential_echo=credential_echo,
            transport_error=transport_error,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            retry_after=retry_after,
            response_http_version=response_http_version,
            response_header_items=response_header_items,
            response_header_field_count=response_header_field_count,
        )
        object.__setattr__(self, "http_status", http_status)
        object.__setattr__(self, "approved_headers", approved_headers)
        object.__setattr__(self, "raw_body", raw_body)
        object.__setattr__(self, "body_complete", body_complete)
        object.__setattr__(self, "observed_body_bytes_lower_bound", observed_body_bytes_lower_bound)
        object.__setattr__(self, "credential_echo", credential_echo)
        object.__setattr__(self, "transport_error", transport_error)
        object.__setattr__(self, "started_at_utc", started_at_utc)
        object.__setattr__(self, "completed_at_utc", completed_at_utc)
        object.__setattr__(self, "retry_after", retry_after)
        object.__setattr__(self, "response_http_version", response_http_version)
        object.__setattr__(self, "response_header_items", response_header_items)
        object.__setattr__(self, "response_header_field_count", response_header_field_count)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek one-operation observation is frozen")


def _validate_deepseek_observation_values(
    *,
    http_status: object,
    approved_headers: object,
    raw_body: object,
    body_complete: object,
    observed_body_bytes_lower_bound: object,
    credential_echo: object,
    transport_error: object,
    started_at_utc: object,
    completed_at_utc: object,
    retry_after: object,
    response_http_version: object,
    response_header_items: object,
    response_header_field_count: object,
) -> None:
    if (
        (http_status is not None and type(http_status) is not int)
        or type(approved_headers) is not dict
        or any(
            type(name) is not str or type(value) is not str
            for name, value in approved_headers.items()
        )
        or (raw_body is not None and type(raw_body) is not bytes)
        or type(body_complete) is not bool
        or type(observed_body_bytes_lower_bound) is not int
        or type(credential_echo) is not bool
        or (transport_error is not None and type(transport_error) is not DeepSeekTransportErrorCode)
        or type(started_at_utc) is not datetime
        or type(completed_at_utc) is not datetime
        or (retry_after is not None and type(retry_after) is not str)
        or (response_http_version is not None and type(response_http_version) is not str)
        or type(response_header_items) is not tuple
        or any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            for item in response_header_items
        )
        or type(response_header_field_count) is not int
    ):
        raise TypeError("DeepSeek one-operation observation primitives must be exact")


def validate_deepseek_one_operation_observation(
    observation: DeepSeekOneOperationObservation,
) -> None:
    """Reject non-exact transport primitives before any downstream derivation."""

    if type(observation) is not DeepSeekOneOperationObservation:
        raise TypeError("DeepSeek one-operation observation type must be exact")
    _validate_deepseek_observation_values(
        http_status=observation.http_status,
        approved_headers=observation.approved_headers,
        raw_body=observation.raw_body,
        body_complete=observation.body_complete,
        observed_body_bytes_lower_bound=observation.observed_body_bytes_lower_bound,
        credential_echo=observation.credential_echo,
        transport_error=observation.transport_error,
        started_at_utc=observation.started_at_utc,
        completed_at_utc=observation.completed_at_utc,
        retry_after=observation.retry_after,
        response_http_version=observation.response_http_version,
        response_header_items=observation.response_header_items,
        response_header_field_count=observation.response_header_field_count,
    )


def credential_representations(api_key: str) -> tuple[bytes, ...]:
    """Return the finite Owner-frozen credential representation set in memory only."""

    if not _valid_key(api_key):
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.INVALID_CREDENTIAL)
    literal = api_key.encode("ascii")
    std = base64.b64encode(literal)
    url = base64.urlsafe_b64encode(literal)
    escaped = json.dumps(api_key, ensure_ascii=True)[1:-1].encode("ascii")
    full_percent_upper = "".join(f"%{byte:02X}" for byte in literal).encode("ascii")
    full_percent_lower = full_percent_upper.lower()
    quoted_upper_text = quote_from_bytes(literal, safe="")
    quoted_lower_text = re.sub(
        r"%[0-9A-F]{2}", lambda match: match.group(0).lower(), quoted_upper_text
    )
    values = {
        literal,
        std,
        std.rstrip(b"="),
        url,
        url.rstrip(b"="),
        literal.hex().encode("ascii"),
        literal.hex().upper().encode("ascii"),
        full_percent_upper,
        full_percent_lower,
        quoted_upper_text.encode("ascii"),
        quoted_lower_text.encode("ascii"),
    }
    if escaped != literal:
        values.add(escaped)
    return tuple(sorted(values))


@final
class DeepSeekRawTransport:
    __slots__ = ("_transport",)

    def __init__(self, *, transport: httpx.BaseTransport) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_transport", transport)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek transport composition is frozen")

    def execute_one(
        self,
        request: DeepSeekRawRequest,
        *,
        absolute_deadline_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> DeepSeekOneOperationObservation:
        """Perform exactly one bounded operation and detect credential echo before hashing."""

        if type(request) is not DeepSeekRawRequest:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        clock = monotonic_clock if monotonic_clock is not None else time.monotonic
        started = _monotonic_now(clock)
        if absolute_deadline_monotonic is None:
            deadline_at = started + request.profile.total_deadline_seconds
        elif type(absolute_deadline_monotonic) not in (int, float) or not math.isfinite(
            absolute_deadline_monotonic
        ):
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        else:
            deadline_at = float(absolute_deadline_monotonic)
        started_utc = datetime.now(UTC)
        key = object.__getattribute__(request, "_api_key")
        representations = credential_representations(key)
        try:
            with httpx.Client(
                transport=_BorrowedTransport(object.__getattribute__(self, "_transport")),
                timeout=_attempt_timeout(deadline_at, request.profile, clock),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                return _capture_one(
                    client,
                    request,
                    deadline_at,
                    started_utc,
                    representations,
                    clock,
                )
        except (httpx.TransportError, DeepSeekTransportError) as error:
            return DeepSeekOneOperationObservation(
                http_status=None,
                approved_headers={},
                raw_body=None,
                body_complete=False,
                observed_body_bytes_lower_bound=0,
                credential_echo=False,
                transport_error=_error_code_after_exception(
                    error,
                    deadline_at=deadline_at,
                    fallback=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
                    monotonic_clock=clock,
                ),
                started_at_utc=started_utc,
                completed_at_utc=datetime.now(UTC),
            )


def _capture_one(
    client: httpx.Client,
    request: DeepSeekRawRequest,
    deadline_at: float,
    started_utc: datetime,
    representations: tuple[bytes, ...],
    monotonic_clock: Callable[[], float],
) -> DeepSeekOneOperationObservation:
    profile = request.profile
    with client.stream(
        "POST",
        request.endpoint,
        content=request.request_bytes,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {object.__getattribute__(request, '_api_key')}",
            "Content-Type": "application/json",
        },
        timeout=_attempt_timeout(deadline_at, profile, monotonic_clock),
    ) as response:
        response_http_version = _response_http_version(response)
        sent = response.request
        if sent.method != "POST" or sent.content != request.request_bytes:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        raw_header_items = tuple(response.headers.raw)
        response_header_field_count = len(raw_header_items)
        if any(
            representation in raw_value or representation in raw_name
            for raw_name, raw_value in raw_header_items
            for representation in representations
        ):
            return DeepSeekOneOperationObservation(
                http_status=response.status_code,
                approved_headers={},
                raw_body=None,
                body_complete=False,
                observed_body_bytes_lower_bound=0,
                credential_echo=True,
                transport_error=None,
                started_at_utc=started_utc,
                completed_at_utc=datetime.now(UTC),
            )
        response_header_items = _approved_header_items(raw_header_items)
        header_values = _legacy_header_projection(response_header_items)
        retry_after_value = _single_header_value(raw_header_items, "retry-after")
        try:
            normalized_headers = normalize_approved_headers(
                response_header_items,
                raw_header_field_count=response_header_field_count,
            )
            persist_raw_body = raw_body_persistence_permitted(normalized_headers)
        except (TypeError, ValueError):
            persist_raw_body = False
        body = bytearray()
        maximum_representation = max(len(item) for item in representations)
        tail = b""
        observed = 0
        overflow = False
        chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
        try:
            iterator = iter(chunks)
            while True:
                _deadline(deadline_at, monotonic_clock)
                try:
                    chunk = next(iterator)
                except StopIteration:
                    _deadline(deadline_at, monotonic_clock)
                    break
                _deadline(deadline_at, monotonic_clock)
                observed += len(chunk)
                scanned = tail + chunk
                if any(item in scanned for item in representations):
                    body.clear()
                    header_values.clear()
                    return DeepSeekOneOperationObservation(
                        http_status=response.status_code,
                        approved_headers={},
                        raw_body=None,
                        body_complete=False,
                        observed_body_bytes_lower_bound=observed,
                        credential_echo=True,
                        transport_error=None,
                        started_at_utc=started_utc,
                        completed_at_utc=datetime.now(UTC),
                    )
                tail = scanned[-(maximum_representation - 1) :]
                if persist_raw_body and len(body) < profile.max_response_bytes:
                    remaining = profile.max_response_bytes - len(body)
                    body.extend(chunk[:remaining])
                if observed > profile.max_response_bytes:
                    overflow = True
        except (httpx.TransportError, DeepSeekTransportError) as error:
            body.clear()
            return DeepSeekOneOperationObservation(
                http_status=response.status_code,
                approved_headers=header_values,
                raw_body=None,
                body_complete=False,
                observed_body_bytes_lower_bound=observed,
                credential_echo=False,
                transport_error=_error_code_after_exception(
                    error,
                    deadline_at=deadline_at,
                    fallback=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
                    monotonic_clock=monotonic_clock,
                ),
                started_at_utc=started_utc,
                completed_at_utc=datetime.now(UTC),
                response_http_version=response_http_version,
                response_header_items=response_header_items,
                response_header_field_count=response_header_field_count,
            )
        return DeepSeekOneOperationObservation(
            http_status=response.status_code,
            approved_headers=header_values,
            raw_body=(bytes(body) if persist_raw_body and not overflow else None),
            body_complete=persist_raw_body and not overflow,
            observed_body_bytes_lower_bound=(
                profile.max_response_bytes + 1 if overflow else observed
            ),
            credential_echo=False,
            transport_error=(DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE if overflow else None),
            started_at_utc=started_utc,
            completed_at_utc=datetime.now(UTC),
            retry_after=retry_after_value,
            response_http_version=response_http_version,
            response_header_items=response_header_items,
            response_header_field_count=response_header_field_count,
        )


def _response_http_version(response: httpx.Response) -> str | None:
    raw = response.extensions.get("http_version")
    if type(raw) is not bytes:
        return None
    try:
        value = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return None
    if not 1 <= len(value) <= 16 or any(not 33 <= ord(character) <= 126 for character in value):
        return None
    return value


def _approved_header_items(
    raw_header_items: tuple[tuple[bytes, bytes], ...],
) -> tuple[tuple[str, str], ...]:
    approved: list[tuple[str, str]] = []
    for raw_name, raw_value in raw_header_items:
        try:
            name = raw_name.decode("ascii", errors="strict").lower()
        except UnicodeDecodeError:
            continue
        if name in APPROVED_HEADER_NAMES:
            approved.append((name, raw_value.decode("latin-1")))
    return tuple(approved)


def _legacy_header_projection(
    items: tuple[tuple[str, str], ...],
) -> dict[str, str]:
    projected: dict[str, list[str]] = {}
    for name, value in items:
        projected.setdefault(name, []).append(value)
    return {name: ", ".join(values) for name, values in projected.items()}


def _single_header_value(
    raw_header_items: tuple[tuple[bytes, bytes], ...], name: str
) -> str | None:
    values = [
        value.decode("latin-1")
        for raw_name, value in raw_header_items
        if raw_name.lower() == name.encode("ascii")
    ]
    return values[0] if len(values) == 1 else None


@final
class _BorrowedTransport(httpx.BaseTransport):
    """Delegate requests without allowing per-call clients to close shared transport."""

    __slots__ = ("_transport",)

    def __init__(self, transport: httpx.BaseTransport) -> None:
        object.__setattr__(self, "_transport", transport)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        transport = cast(httpx.BaseTransport, object.__getattribute__(self, "_transport"))
        return transport.handle_request(request)

    def close(self) -> None:
        return None


def _monotonic_now(monotonic_clock: Callable[[], float]) -> float:
    value = monotonic_clock()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
    return float(value)


def _deadline(
    deadline_at: float,
    monotonic_clock: Callable[[], float] | None = None,
) -> None:
    clock = monotonic_clock if monotonic_clock is not None else time.monotonic
    if _monotonic_now(clock) >= deadline_at:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)


def _attempt_timeout(
    deadline_at: float,
    profile: DeepSeekTransportProfile,
    monotonic_clock: Callable[[], float] | None = None,
) -> httpx.Timeout:
    clock = monotonic_clock if monotonic_clock is not None else time.monotonic
    remaining = deadline_at - _monotonic_now(clock)
    if remaining <= 0:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)
    return httpx.Timeout(
        connect=min(profile.connect_timeout_seconds, remaining),
        read=min(profile.read_timeout_seconds, remaining),
        write=min(profile.write_timeout_seconds, remaining),
        pool=min(profile.pool_timeout_seconds, remaining),
    )


def _error_code_after_exception(
    error: httpx.TransportError | DeepSeekTransportError,
    *,
    deadline_at: float,
    fallback: DeepSeekTransportErrorCode,
    monotonic_clock: Callable[[], float] | None = None,
) -> DeepSeekTransportErrorCode:
    clock = monotonic_clock if monotonic_clock is not None else time.monotonic
    if _monotonic_now(clock) >= deadline_at:
        return DeepSeekTransportErrorCode.DEADLINE_EXCEEDED
    if type(error) is DeepSeekTransportError:
        return error.code
    return fallback


def _validate_json(raw: bytes) -> None:
    if raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID)
    try:
        json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID) from None


def _valid_key(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 512
        and value.isascii()
        and all(33 <= ord(character) <= 126 for character in value)
    )
