"""Hardened raw synchronous transport for one bounded Responses API request."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, final

import httpx

from medevidence.domain import Sha256Digest, sha256_digest

_RAW_RESPONSE_CHUNK_BYTES = 16_384
_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
MAX_RESPONSES_REQUEST_BYTES = 2_200_000
MAX_RESPONSES_RESPONSE_BYTES = 1_048_576
MAX_RESPONSES_ATTEMPTS = 3
MAX_RESPONSES_TOTAL_DEADLINE_SECONDS = 45.0
MAX_RESPONSES_CONNECT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSES_READ_TIMEOUT_SECONDS = 30.0
MAX_RESPONSES_WRITE_TIMEOUT_SECONDS = 10.0
MAX_RESPONSES_POOL_TIMEOUT_SECONDS = 5.0
MAX_RESPONSES_BACKOFF_BASE_SECONDS = 0.25
MAX_RESPONSES_RETRY_AFTER_SECONDS = 2.0
RESPONSES_RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
_FORBIDDEN_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff",
)


class ResponsesTransportErrorCode(StrEnum):
    """Stable redacted failure classes for the raw provider boundary."""

    INVALID_CREDENTIAL = "invalid_credential"
    REQUEST_INTEGRITY = "request_integrity"
    AUTHENTICATION = "authentication_failed"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    RESPONSE_TOO_LARGE = "response_too_large"
    RESPONSE_INVALID = "response_invalid"


class ResponsesTransportError(RuntimeError):
    """Fresh redacted raw-transport error without provider material."""

    __slots__ = ("code", "status_code")

    def __init__(
        self,
        code: ResponsesTransportErrorCode,
        *,
        status_code: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status_code = status_code


@final
class ResponsesTransportProfile:
    """Exact immutable safety bounds admitted by the raw transport."""

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

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Responses transport profile is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("ResponsesTransportProfile is sealed")

    def __init__(
        self,
        *,
        max_request_bytes: int,
        max_response_bytes: int,
        max_attempts: int,
        retryable_statuses: tuple[int, ...],
        total_deadline_seconds: float,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        write_timeout_seconds: float,
        pool_timeout_seconds: float,
        backoff_base_seconds: float,
        retry_after_cap_seconds: float,
    ) -> None:
        integer_values = (max_request_bytes, max_response_bytes, max_attempts)
        if any(type(value) is not int or value <= 0 for value in integer_values):
            raise TypeError("transport integer bounds must be positive exact integers")
        if (
            max_request_bytes > MAX_RESPONSES_REQUEST_BYTES
            or max_response_bytes > MAX_RESPONSES_RESPONSE_BYTES
            or max_attempts > MAX_RESPONSES_ATTEMPTS
        ):
            raise ValueError("transport integer bounds exceed the shared safety maximum")
        if type(retryable_statuses) is not tuple or not retryable_statuses:
            raise TypeError("retryable_statuses must be a nonempty exact tuple")
        if any(type(value) is not int or not 100 <= value <= 599 for value in retryable_statuses):
            raise TypeError("retryable statuses must be exact HTTP status integers")
        if retryable_statuses != tuple(sorted(set(retryable_statuses))):
            raise ValueError("retryable statuses must be sorted and unique")
        if any(value not in RESPONSES_RETRYABLE_STATUSES for value in retryable_statuses):
            raise ValueError("retryable status is outside the shared safety profile")
        float_values = (
            total_deadline_seconds,
            connect_timeout_seconds,
            read_timeout_seconds,
            write_timeout_seconds,
            pool_timeout_seconds,
            backoff_base_seconds,
            retry_after_cap_seconds,
        )
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in float_values
        ):
            raise TypeError("transport time bounds must be positive exact numbers")
        time_maxima = (
            MAX_RESPONSES_TOTAL_DEADLINE_SECONDS,
            MAX_RESPONSES_CONNECT_TIMEOUT_SECONDS,
            MAX_RESPONSES_READ_TIMEOUT_SECONDS,
            MAX_RESPONSES_WRITE_TIMEOUT_SECONDS,
            MAX_RESPONSES_POOL_TIMEOUT_SECONDS,
            MAX_RESPONSES_BACKOFF_BASE_SECONDS,
            MAX_RESPONSES_RETRY_AFTER_SECONDS,
        )
        if any(value > maximum for value, maximum in zip(float_values, time_maxima, strict=True)):
            raise ValueError("transport time bound exceeds the shared safety maximum")
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


@final
class ResponsesRawRequest:
    """Closed immutable request admitted by the raw transport."""

    __slots__ = ("_api_key", "endpoint", "profile", "request_bytes", "request_hash")
    _api_key: str
    endpoint: str
    profile: ResponsesTransportProfile
    request_bytes: bytes
    request_hash: Sha256Digest

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Responses raw request is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("ResponsesRawRequest is sealed")

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        request_bytes: bytes,
        profile: ResponsesTransportProfile,
    ) -> None:
        if not _valid_api_key(api_key):
            raise ResponsesTransportError(ResponsesTransportErrorCode.INVALID_CREDENTIAL) from None
        if type(endpoint) is not str:
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        invalid_url = False
        try:
            url = httpx.URL(endpoint)
        except Exception:
            invalid_url = True
            url = httpx.URL(_RESPONSES_ENDPOINT)
        if invalid_url:
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        if (
            endpoint != _RESPONSES_ENDPOINT
            or url.scheme != "https"
            or url.host != "api.openai.com"
            or url.username != ""
            or url.password != ""
            or url.query
            or url.fragment
        ):
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        if type(request_bytes) is not bytes or not request_bytes:
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        if type(profile) is not ResponsesTransportProfile:
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        if len(request_bytes) > profile.max_request_bytes:
            raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
        _validate_json_bytes(request_bytes, request=True)
        object.__setattr__(self, "_api_key", api_key)
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "request_bytes", request_bytes)
        object.__setattr__(self, "request_hash", sha256_digest(request_bytes))
        object.__setattr__(self, "profile", profile)

    def __repr__(self) -> str:
        return (
            "ResponsesRawRequest(endpoint=<redacted>, request_bytes=<redacted>, profile=<bounded>)"
        )


@final
class ResponsesRawReply:
    """Closed immutable metadata and exact raw body returned after validation."""

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

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Responses raw reply is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("ResponsesRawReply is sealed")

    def __init__(
        self,
        *,
        status_code: int,
        body: bytes,
        attempts: int,
        request_hash: Sha256Digest,
        started_at_utc: datetime,
        completed_at_utc: datetime,
    ) -> None:
        if type(status_code) is not int or status_code != 200:
            raise ValueError("raw reply requires exact successful HTTP status")
        if type(body) is not bytes:
            raise TypeError("raw reply body must be exact bytes")
        if type(attempts) is not int or attempts <= 0:
            raise ValueError("raw reply attempts must be positive")
        if type(request_hash) is not str or not request_hash.startswith("sha256:"):
            raise ValueError("raw reply request hash is invalid")
        if (
            not isinstance(started_at_utc, datetime)
            or started_at_utc.tzinfo is None
            or not isinstance(completed_at_utc, datetime)
            or completed_at_utc.tzinfo is None
            or completed_at_utc < started_at_utc
        ):
            raise ValueError("raw reply timestamps are invalid")
        object.__setattr__(self, "status_code", status_code)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "request_hash", request_hash)
        object.__setattr__(self, "response_hash", sha256_digest(body))
        object.__setattr__(self, "started_at_utc", started_at_utc)
        object.__setattr__(self, "completed_at_utc", completed_at_utc)


@final
class ResponsesRawTransport:
    """Execute a closed raw Responses request with no caller parser authority."""

    __slots__ = ("_transport",)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Responses raw transport composition is frozen")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("ResponsesRawTransport is sealed")

    def __init__(self, *, transport: httpx.BaseTransport) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_transport", transport)

    def send(self, request: ResponsesRawRequest) -> ResponsesRawReply:
        """Return one bounded raw reply or a fresh redacted failure."""

        try:
            if type(request) is not ResponsesRawRequest:
                raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY)
            exact_request = _reconstruct_request(request)
            transport = object.__getattribute__(self, "_transport")
            if not isinstance(transport, httpx.BaseTransport):
                raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY)
            return ResponsesRawTransport._send(self, exact_request)
        except ResponsesTransportError as error:
            code, status = _sanitize_public_error(error)
        except Exception:
            code = ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE
            status = None
        raise ResponsesTransportError(code, status_code=status) from None

    def _send(self, request: ResponsesRawRequest) -> ResponsesRawReply:
        profile = request.profile
        started_at = datetime.now(UTC)
        started_monotonic = time.monotonic()
        attempts = 0
        try:
            with httpx.Client(
                transport=_BorrowedTransport(object.__getattribute__(self, "_transport")),
                timeout=_attempt_timeout(started_monotonic, profile),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                while attempts < profile.max_attempts:
                    _require_remaining_deadline(started_monotonic, profile)
                    attempts += 1
                    try:
                        response, body = _send_bounded(
                            client,
                            request=request,
                            started_monotonic=started_monotonic,
                        )
                    except _PreBodyTransportFailure as error:
                        if attempts >= profile.max_attempts:
                            raise ResponsesTransportError(
                                ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE
                            ) from error
                        _sleep_before_retry(
                            request_hash=request.request_hash,
                            attempt=attempts,
                            started_monotonic=started_monotonic,
                            retry_after=None,
                            profile=profile,
                        )
                        continue
                    except _PostBodyTransportFailure as error:
                        raise ResponsesTransportError(
                            ResponsesTransportErrorCode.RESPONSE_INVALID
                        ) from error

                    status_code = response.status_code
                    if status_code in profile.retryable_statuses:
                        if attempts >= profile.max_attempts:
                            raise ResponsesTransportError(
                                ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE,
                                status_code=status_code,
                            )
                        _sleep_before_retry(
                            request_hash=request.request_hash,
                            attempt=attempts,
                            started_monotonic=started_monotonic,
                            retry_after=response.headers.get("Retry-After"),
                            profile=profile,
                        )
                        continue
                    if status_code in {401, 403}:
                        raise ResponsesTransportError(
                            ResponsesTransportErrorCode.AUTHENTICATION,
                            status_code=status_code,
                        )
                    if status_code != 200:
                        raise ResponsesTransportError(
                            ResponsesTransportErrorCode.PROVIDER_REJECTED,
                            status_code=status_code,
                        )
                    _validate_json_bytes(body, request=False)
                    return ResponsesRawReply(
                        status_code=status_code,
                        body=body,
                        attempts=attempts,
                        request_hash=request.request_hash,
                        started_at_utc=started_at,
                        completed_at_utc=datetime.now(UTC),
                    )
        except ResponsesTransportError:
            raise
        except httpx.TransportError as error:
            raise ResponsesTransportError(
                ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE
            ) from error
        raise ResponsesTransportError(ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE)


def _send_bounded(
    client: httpx.Client,
    *,
    request: ResponsesRawRequest,
    started_monotonic: float,
) -> tuple[httpx.Response, bytes]:
    profile = request.profile
    received = False
    try:
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
            timeout=_attempt_timeout(started_monotonic, profile),
        ) as response:
            sent = response.request
            _validate_sent_request(sent, request)
            body = bytearray()
            if response.headers.get("Transfer-Encoding") is not None:
                raise ResponsesTransportError(
                    ResponsesTransportErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            encoding = response.headers.get("Content-Encoding")
            if encoding is not None and encoding.strip().lower() != "identity":
                raise ResponsesTransportError(
                    ResponsesTransportErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            content_type = response.headers.get("Content-Type")
            if content_type not in {"application/json", "application/json; charset=utf-8"}:
                raise ResponsesTransportError(
                    ResponsesTransportErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            declared_length = _declared_length(response)
            if declared_length is not None and declared_length > profile.max_response_bytes:
                raise ResponsesTransportError(
                    ResponsesTransportErrorCode.RESPONSE_TOO_LARGE,
                    status_code=response.status_code,
                )
            for chunk in response.iter_raw(chunk_size=_RAW_RESPONSE_CHUNK_BYTES):
                _require_remaining_deadline(started_monotonic, profile)
                if chunk:
                    received = True
                    if len(body) + len(chunk) > profile.max_response_bytes:
                        raise ResponsesTransportError(
                            ResponsesTransportErrorCode.RESPONSE_TOO_LARGE,
                            status_code=response.status_code,
                        )
                    body.extend(chunk)
            _require_remaining_deadline(started_monotonic, profile)
            if declared_length is not None and declared_length != len(body):
                raise ResponsesTransportError(
                    ResponsesTransportErrorCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            return response, bytes(body)
    except ResponsesTransportError:
        raise
    except httpx.TransportError as error:
        if received:
            raise _PostBodyTransportFailure from error
        raise _PreBodyTransportFailure from error


def _declared_length(response: httpx.Response) -> int | None:
    content_length = response.headers.get("Content-Length")
    if content_length is None:
        return None
    canonical = content_length == "0" or (
        content_length.isascii()
        and content_length[:1] in "123456789"
        and (len(content_length) == 1 or content_length[1:].isdigit())
    )
    if not canonical:
        raise ResponsesTransportError(
            ResponsesTransportErrorCode.RESPONSE_INVALID,
            status_code=response.status_code,
        )
    return int(content_length)


def _validate_sent_request(sent: httpx.Request, request: ResponsesRawRequest) -> None:
    exact_headers = {
        "accept": "application/json",
        "accept-encoding": "identity",
        "authorization": f"Bearer {object.__getattribute__(request, '_api_key')}",
        "content-type": "application/json",
        "content-length": str(len(request.request_bytes)),
    }
    if (
        sent.method != "POST"
        or sent.url != httpx.URL(request.endpoint)
        or sent.content != request.request_bytes
        or sent.headers.get("transfer-encoding") is not None
        or any(sent.headers.get(name) != value for name, value in exact_headers.items())
    ):
        raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY)


def _reconstruct_request(request: ResponsesRawRequest) -> ResponsesRawRequest:
    try:
        api_key = object.__getattribute__(request, "_api_key")
        endpoint = object.__getattribute__(request, "endpoint")
        request_bytes = object.__getattribute__(request, "request_bytes")
        request_hash = object.__getattribute__(request, "request_hash")
        profile = _reconstruct_profile(object.__getattribute__(request, "profile"))
    except Exception:
        raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None
    reconstructed = ResponsesRawRequest(
        api_key=api_key,
        endpoint=endpoint,
        request_bytes=request_bytes,
        profile=profile,
    )
    if request_hash != reconstructed.request_hash:
        raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY)
    return reconstructed


def _reconstruct_profile(profile: ResponsesTransportProfile) -> ResponsesTransportProfile:
    if type(profile) is not ResponsesTransportProfile:
        raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY)
    try:
        return ResponsesTransportProfile(
            max_request_bytes=object.__getattribute__(profile, "max_request_bytes"),
            max_response_bytes=object.__getattribute__(profile, "max_response_bytes"),
            max_attempts=object.__getattribute__(profile, "max_attempts"),
            retryable_statuses=object.__getattribute__(profile, "retryable_statuses"),
            total_deadline_seconds=object.__getattribute__(profile, "total_deadline_seconds"),
            connect_timeout_seconds=object.__getattribute__(profile, "connect_timeout_seconds"),
            read_timeout_seconds=object.__getattribute__(profile, "read_timeout_seconds"),
            write_timeout_seconds=object.__getattribute__(profile, "write_timeout_seconds"),
            pool_timeout_seconds=object.__getattribute__(profile, "pool_timeout_seconds"),
            backoff_base_seconds=object.__getattribute__(profile, "backoff_base_seconds"),
            retry_after_cap_seconds=object.__getattribute__(profile, "retry_after_cap_seconds"),
        )
    except ResponsesTransportError:
        raise
    except Exception:
        raise ResponsesTransportError(ResponsesTransportErrorCode.REQUEST_INTEGRITY) from None


def _validate_json_bytes(raw: bytes, *, request: bool) -> None:
    code = (
        ResponsesTransportErrorCode.REQUEST_INTEGRITY
        if request
        else ResponsesTransportErrorCode.RESPONSE_INVALID
    )
    if raw.startswith(_FORBIDDEN_BOMS):
        raise ResponsesTransportError(code)
    invalid = False
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(document, dict):
            raise ValueError("Responses JSON must be an object")
    except (UnicodeDecodeError, ValueError, RecursionError):
        invalid = True
    if invalid:
        raise ResponsesTransportError(code) from None


def _valid_api_key(api_key: object) -> bool:
    return (
        type(api_key) is str
        and 1 <= len(api_key) <= 512
        and api_key.isascii()
        and all(33 <= ord(char) <= 126 for char in api_key)
    )


def _sanitize_public_error(
    error: ResponsesTransportError,
) -> tuple[ResponsesTransportErrorCode, int | None]:
    if type(error) is not ResponsesTransportError:
        return ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE, None
    try:
        code = object.__getattribute__(error, "code")
        status_code = object.__getattribute__(error, "status_code")
    except Exception:
        return ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE, None
    valid_status = status_code is None or (type(status_code) is int and 100 <= status_code <= 599)
    if type(code) is not ResponsesTransportErrorCode or not valid_status:
        return ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE, None
    return code, status_code


def _sleep_before_retry(
    *,
    request_hash: Sha256Digest,
    attempt: int,
    started_monotonic: float,
    retry_after: str | None,
    profile: ResponsesTransportProfile,
) -> None:
    delay = _retry_after_seconds(retry_after, profile)
    if delay is None:
        base = profile.backoff_base_seconds * (2 ** (attempt - 1))
        jitter_byte = hashlib.sha256(f"{request_hash}:{attempt}".encode()).digest()[0]
        delay = base + (base * 0.1 * jitter_byte / 255.0)
    elapsed = time.monotonic() - started_monotonic
    if elapsed + delay >= profile.total_deadline_seconds:
        raise ResponsesTransportError(ResponsesTransportErrorCode.DEADLINE_EXCEEDED)
    time.sleep(delay)
    _require_remaining_deadline(started_monotonic, profile)


def _retry_after_seconds(value: str | None, profile: ResponsesTransportProfile) -> float | None:
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
    return min(seconds, profile.retry_after_cap_seconds)


def _require_remaining_deadline(
    started_monotonic: float,
    profile: ResponsesTransportProfile,
) -> None:
    if time.monotonic() - started_monotonic >= profile.total_deadline_seconds:
        raise ResponsesTransportError(ResponsesTransportErrorCode.DEADLINE_EXCEEDED)


def _attempt_timeout(
    started_monotonic: float,
    profile: ResponsesTransportProfile,
) -> httpx.Timeout:
    remaining = profile.total_deadline_seconds - (time.monotonic() - started_monotonic)
    if remaining <= 0:
        raise ResponsesTransportError(ResponsesTransportErrorCode.DEADLINE_EXCEEDED)
    total_phase_seconds = (
        profile.connect_timeout_seconds
        + profile.read_timeout_seconds
        + profile.write_timeout_seconds
        + profile.pool_timeout_seconds
    )
    scale = min(1.0, remaining / total_phase_seconds)
    return httpx.Timeout(
        connect=max(0.001, profile.connect_timeout_seconds * scale),
        read=max(0.001, profile.read_timeout_seconds * scale),
        write=max(0.001, profile.write_timeout_seconds * scale),
        pool=max(0.001, profile.pool_timeout_seconds * scale),
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


def _reject_constant(value: str) -> None:
    del value
    raise ValueError("non-finite JSON number")
