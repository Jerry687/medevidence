"""Hardened synchronous transport for the exact DeepSeek Responses endpoint."""

from __future__ import annotations

import base64
import json
import math
import re
import time
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast, final
from urllib.parse import quote_from_bytes

import httpx

from medevidence.domain import Sha256Digest, sha256_digest

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
        "retry_after",
        "started_at_utc",
        "transport_error",
    )
    http_status: int | None
    approved_headers: dict[str, str]
    raw_body: bytes | None
    retry_after: str | None
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
    ) -> None:
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

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek one-operation observation is frozen")


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

    def execute_one(self, request: DeepSeekRawRequest) -> DeepSeekOneOperationObservation:
        """Perform exactly one bounded operation and detect credential echo before hashing."""

        if type(request) is not DeepSeekRawRequest:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        started_utc = datetime.now(UTC)
        started = time.monotonic()
        key = object.__getattribute__(request, "_api_key")
        representations = credential_representations(key)
        try:
            with httpx.Client(
                transport=_BorrowedTransport(object.__getattribute__(self, "_transport")),
                timeout=_attempt_timeout(started, request.profile),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                return _capture_one(
                    client,
                    request,
                    started,
                    started_utc,
                    representations,
                )
        except (httpx.TransportError, DeepSeekTransportError) as error:
            return DeepSeekOneOperationObservation(
                http_status=None,
                approved_headers={},
                raw_body=None,
                body_complete=False,
                observed_body_bytes_lower_bound=0,
                credential_echo=False,
                transport_error=(
                    error.code
                    if type(error) is DeepSeekTransportError
                    else DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
                ),
                started_at_utc=started_utc,
                completed_at_utc=datetime.now(UTC),
            )


def _capture_one(
    client: httpx.Client,
    request: DeepSeekRawRequest,
    started: float,
    started_utc: datetime,
    representations: tuple[bytes, ...],
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
        timeout=_attempt_timeout(started, profile),
    ) as response:
        sent = response.request
        if sent.method != "POST" or sent.content != request.request_bytes:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        approved_names = (
            "content-type",
            "content-length",
            "transfer-encoding",
            "content-encoding",
            "x-request-id",
        )
        header_values = {
            name: response.headers[name] for name in approved_names if name in response.headers
        }
        retry_after_value = response.headers.get("Retry-After")
        scanned_header_values = [*header_values.values()]
        if retry_after_value is not None:
            scanned_header_values.append(retry_after_value)
        if any(
            representation in value.encode("utf-8")
            for value in scanned_header_values
            for representation in representations
        ):
            header_values.clear()
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
        body = bytearray()
        maximum_representation = max(len(item) for item in representations)
        tail = b""
        observed = 0
        overflow = False
        chunks = (
            (response.content,)
            if response.is_stream_consumed
            else response.iter_raw(chunk_size=_CHUNK_BYTES)
        )
        try:
            for chunk in chunks:
                _deadline(started, profile)
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
                if len(body) < profile.max_response_bytes:
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
                transport_error=(
                    error.code
                    if type(error) is DeepSeekTransportError
                    else DeepSeekTransportErrorCode.RESPONSE_INVALID
                ),
                started_at_utc=started_utc,
                completed_at_utc=datetime.now(UTC),
            )
        return DeepSeekOneOperationObservation(
            http_status=response.status_code,
            approved_headers=header_values,
            raw_body=None if overflow else bytes(body),
            body_complete=not overflow,
            observed_body_bytes_lower_bound=(
                profile.max_response_bytes + 1 if overflow else len(body)
            ),
            credential_echo=False,
            transport_error=(DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE if overflow else None),
            started_at_utc=started_utc,
            completed_at_utc=datetime.now(UTC),
            retry_after=retry_after_value,
        )


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


def _deadline(started: float, profile: DeepSeekTransportProfile) -> None:
    if time.monotonic() - started >= profile.total_deadline_seconds:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)


def _attempt_timeout(started: float, profile: DeepSeekTransportProfile) -> httpx.Timeout:
    remaining = profile.total_deadline_seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)
    return httpx.Timeout(
        connect=min(profile.connect_timeout_seconds, remaining),
        read=min(profile.read_timeout_seconds, remaining),
        write=min(profile.write_timeout_seconds, remaining),
        pool=min(profile.pool_timeout_seconds, remaining),
    )


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
