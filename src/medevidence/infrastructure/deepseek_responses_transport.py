"""Hardened synchronous transport for the exact DeepSeek Responses endpoint."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import cast, final

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
class DeepSeekRawTransport:
    __slots__ = ("_transport",)

    def __init__(self, *, transport: httpx.BaseTransport) -> None:
        if not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an explicit synchronous httpx.BaseTransport")
        object.__setattr__(self, "_transport", transport)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("DeepSeek transport composition is frozen")

    def send(self, request: DeepSeekRawRequest) -> DeepSeekRawReply:
        """Execute only the reconstructed exact request with bounded retries."""

        try:
            if type(request) is not DeepSeekRawRequest:
                raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
            profile = object.__getattribute__(request, "profile")
            if type(profile) is not DeepSeekTransportProfile:
                raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
            started_utc = datetime.now(UTC)
            started = time.monotonic()
            attempts = 0
            with httpx.Client(
                transport=_BorrowedTransport(object.__getattribute__(self, "_transport")),
                timeout=httpx.Timeout(
                    connect=profile.connect_timeout_seconds,
                    read=profile.read_timeout_seconds,
                    write=profile.write_timeout_seconds,
                    pool=profile.pool_timeout_seconds,
                ),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                while attempts < profile.max_attempts:
                    _deadline(started, profile)
                    attempts += 1
                    try:
                        response, body = _send_once(client, request, started)
                    except httpx.TransportError:
                        if attempts >= profile.max_attempts:
                            raise DeepSeekTransportError(
                                DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE
                            ) from None
                        _sleep(request.request_hash, attempts, started, profile, None)
                        continue
                    status = response.status_code
                    if status in profile.retryable_statuses:
                        if attempts >= profile.max_attempts:
                            raise DeepSeekTransportError(
                                DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
                                status_code=status,
                            )
                        _sleep(
                            request.request_hash,
                            attempts,
                            started,
                            profile,
                            response.headers.get("Retry-After"),
                        )
                        continue
                    if status in {401, 403}:
                        raise DeepSeekTransportError(
                            DeepSeekTransportErrorCode.AUTHENTICATION,
                            status_code=status,
                        )
                    if status != 200:
                        raise DeepSeekTransportError(
                            DeepSeekTransportErrorCode.PROVIDER_REJECTED,
                            status_code=status,
                        )
                    _validate_json(body)
                    return DeepSeekRawReply(
                        body=body,
                        attempts=attempts,
                        request_hash=request.request_hash,
                        started_at_utc=started_utc,
                        completed_at_utc=datetime.now(UTC),
                    )
        except DeepSeekTransportError:
            raise
        except Exception:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE) from None
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE)


def _send_once(
    client: httpx.Client, request: DeepSeekRawRequest, started: float
) -> tuple[httpx.Response, bytes]:
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
        if (
            sent.method != "POST"
            or str(sent.url) != DEEPSEEK_RESPONSES_ENDPOINT
            or sent.headers.get("host") != "api.deepseek.com"
            or sent.content != request.request_bytes
            or hashlib.sha256(sent.content).digest()
            != hashlib.sha256(request.request_bytes).digest()
        ):
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.REQUEST_INTEGRITY)
        if response.is_redirect:
            raise DeepSeekTransportError(
                DeepSeekTransportErrorCode.RESPONSE_INVALID,
                status_code=response.status_code,
            )
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID)
        if response.headers.get("Transfer-Encoding") is not None:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID)
        if response.headers.get("Content-Type") not in {
            "application/json",
            "application/json; charset=utf-8",
        }:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID)
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID) from None
            if length < 0 or length > profile.max_response_bytes:
                raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE)
        body = bytearray()
        chunks = (
            (response.content,)
            if response.is_stream_consumed
            else response.iter_raw(chunk_size=_CHUNK_BYTES)
        )
        try:
            for chunk in chunks:
                _deadline(started, profile)
                if len(body) + len(chunk) > profile.max_response_bytes:
                    raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE)
                body.extend(chunk)
        except DeepSeekTransportError:
            raise
        except httpx.TransportError:
            raise DeepSeekTransportError(DeepSeekTransportErrorCode.RESPONSE_INVALID) from None
        return response, bytes(body)


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


def _sleep(
    request_hash: str,
    attempt: int,
    started: float,
    profile: DeepSeekTransportProfile,
    retry_after: str | None,
) -> None:
    delay = min(
        profile.retry_after_cap_seconds,
        _retry_after(retry_after)
        if retry_after is not None
        else profile.backoff_base_seconds * (2 ** (attempt - 1)),
    )
    jitter = int(hashlib.sha256(f"{request_hash}:{attempt}".encode()).hexdigest()[:4], 16)
    delay = min(profile.retry_after_cap_seconds, delay + (jitter / 65535) * 0.01)
    if time.monotonic() - started + delay >= profile.total_deadline_seconds:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)
    time.sleep(delay)


def _retry_after(value: str) -> float:
    try:
        number = float(value)
        if math.isfinite(number) and number >= 0:
            return number
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return 0.0


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
