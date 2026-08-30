"""Offline contracts for the shared hardened raw Responses transport."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest

import medevidence.infrastructure.responses_transport as adapter
from medevidence.domain import sha256_digest
from medevidence.infrastructure.responses_transport import (
    MAX_RESPONSES_ATTEMPTS,
    MAX_RESPONSES_BACKOFF_BASE_SECONDS,
    MAX_RESPONSES_CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSES_POOL_TIMEOUT_SECONDS,
    MAX_RESPONSES_READ_TIMEOUT_SECONDS,
    MAX_RESPONSES_REQUEST_BYTES,
    MAX_RESPONSES_RESPONSE_BYTES,
    MAX_RESPONSES_RETRY_AFTER_SECONDS,
    MAX_RESPONSES_TOTAL_DEADLINE_SECONDS,
    MAX_RESPONSES_WRITE_TIMEOUT_SECONDS,
    RESPONSES_RETRYABLE_STATUSES,
    ResponsesRawReply,
    ResponsesRawRequest,
    ResponsesRawTransport,
    ResponsesTransportError,
    ResponsesTransportErrorCode,
    ResponsesTransportProfile,
)

ENDPOINT = "https://api.openai.com/v1/responses"
KEY = "raw-transport-test-key"
REQUEST_BYTES = b'{"input":"bounded"}'
RESPONSE_BYTES = b'{"id":"resp_test","ok":true}'


def _profile(**overrides: object) -> ResponsesTransportProfile:
    values: dict[str, object] = {
        "max_request_bytes": 4096,
        "max_response_bytes": 4096,
        "max_attempts": 3,
        "retryable_statuses": (429, 500, 502, 503, 504),
        "total_deadline_seconds": 30.0,
        "connect_timeout_seconds": 1.0,
        "read_timeout_seconds": 2.0,
        "write_timeout_seconds": 1.0,
        "pool_timeout_seconds": 1.0,
        "backoff_base_seconds": 0.01,
        "retry_after_cap_seconds": 0.1,
    }
    values.update(overrides)
    return ResponsesTransportProfile(**values)  # type: ignore[arg-type]


def _request(
    *,
    api_key: str = KEY,
    endpoint: str = ENDPOINT,
    request_bytes: bytes = REQUEST_BYTES,
    profile: ResponsesTransportProfile | None = None,
) -> ResponsesRawRequest:
    return ResponsesRawRequest(
        api_key=api_key,
        endpoint=endpoint,
        request_bytes=request_bytes,
        profile=profile or _profile(),
    )


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> ResponsesRawTransport:
    def bounded_handler(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if "Content-Type" not in response.headers:
            response.headers["Content-Type"] = "application/json"
        if response.is_stream_consumed:
            return httpx.Response(
                response.status_code,
                request=request,
                headers=response.headers,
                stream=httpx.ByteStream(response.content),
                extensions=response.extensions,
            )
        return response

    return ResponsesRawTransport(transport=httpx.MockTransport(bounded_handler))


def test_construction_has_no_io_and_composition_is_sealed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    request = _request()
    transport = _transport(handler)
    assert calls == 0
    assert not hasattr(request, "__dict__")
    assert not hasattr(transport, "__dict__")
    assert KEY not in repr(request)
    with pytest.raises(AttributeError, match="frozen"):
        request.endpoint = "https://example.invalid"  # type: ignore[misc]
    with pytest.raises(AttributeError, match="frozen"):
        transport._transport = object()  # type: ignore[misc]
    with pytest.raises(TypeError, match="BaseTransport"):
        ResponsesRawTransport(transport=object())  # type: ignore[arg-type]
    assert calls == 0


def test_exact_endpoint_headers_identity_body_and_closed_reply() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    result = _transport(handler).send(_request())
    assert len(observed) == 1
    sent = observed[0]
    assert sent.method == "POST"
    assert str(sent.url) == ENDPOINT
    assert sent.content == REQUEST_BYTES
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.headers["accept"] == "application/json"
    assert sent.headers["accept-encoding"] == "identity"
    assert sent.headers["content-type"] == "application/json"
    assert sent.headers["content-length"] == str(len(REQUEST_BYTES))
    assert result.status_code == 200
    assert result.body == RESPONSE_BYTES
    assert result.request_hash == sha256_digest(REQUEST_BYTES)
    assert result.response_hash == sha256_digest(RESPONSE_BYTES)
    assert result.attempts == 1
    assert result.completed_at_utc >= result.started_at_utc
    assert type(result) is ResponsesRawReply
    assert not hasattr(result, "__dict__")
    with pytest.raises(AttributeError, match="frozen"):
        result.body = b"replacement"  # type: ignore[misc]


def test_transport_cannot_substitute_authorization_or_identity_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        request.headers["Authorization"] = "Bearer substituted"
        request.headers["Accept-Encoding"] = "gzip"
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(_request())
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY


@pytest.mark.parametrize(
    "invalid",
    ("", " ", "contains space", "line\nbreak", "snow-雪"),
)
def test_invalid_credential_fails_before_capability_without_secret_chain(invalid: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    with pytest.raises(ResponsesTransportError) as caught:
        _request(api_key=invalid)
    error = caught.value
    assert error.code is ResponsesTransportErrorCode.INVALID_CREDENTIAL
    assert error.__cause__ is None
    assert error.__context__ is None
    if invalid:
        assert invalid not in repr(error)
    assert calls == 0


def test_credential_subclass_behavior_is_never_invoked() -> None:
    reads: list[str] = []

    class EvilKey(str):
        def __len__(self) -> int:
            reads.append("len")
            raise RuntimeError("credential-secret")

        def isascii(self) -> bool:
            reads.append("isascii")
            raise RuntimeError("credential-secret")

        def __iter__(self) -> Iterator[str]:
            reads.append("iter")
            raise RuntimeError("credential-secret")

    with pytest.raises(ResponsesTransportError) as caught:
        _request(api_key=EvilKey(KEY))
    assert caught.value.code is ResponsesTransportErrorCode.INVALID_CREDENTIAL
    assert reads == []


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://api.openai.com/v1/responses",
        "https://example.com/v1/responses",
        "https://api.openai.com/v1/responses?x=1",
        "https://user@api.openai.com/v1/responses",
        "https://api.openai.com/v1/responses/",
        "https://[invalid-secret/v1/responses",
    ),
)
def test_only_exact_responses_endpoint_is_admitted(endpoint: str) -> None:
    with pytest.raises(ResponsesTransportError) as caught:
        _request(endpoint=endpoint)
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "invalid-secret" not in repr(caught.value)


@pytest.mark.parametrize(
    "request_bytes",
    (
        b"not-json",
        b'\xef\xbb\xbf{"input":"x"}',
        b'{"input":"one","input":"two"}',
        b'{"input":"\xff"}',
        b'{"input":NaN}',
        b"[]",
        b"",
    ),
)
def test_request_is_strict_utf8_unique_key_json_before_capability(request_bytes: bytes) -> None:
    with pytest.raises(ResponsesTransportError) as caught:
        _request(request_bytes=request_bytes)
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_request_cap_and_mutated_identity_or_profile_fail_before_capability() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    with pytest.raises(ResponsesTransportError) as caught:
        _request(request_bytes=REQUEST_BYTES, profile=_profile(max_request_bytes=1))
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY

    request = _request()
    object.__setattr__(request, "request_bytes", b'{"input":"substituted"}')
    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(request)
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY

    request = _request()
    object.__setattr__(request.profile, "max_attempts", "3")
    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(request)
    assert caught.value.code is ResponsesTransportErrorCode.REQUEST_INTEGRITY
    assert calls == 0


@pytest.mark.parametrize(
    ("headers", "expected"),
    (
        ({"Content-Encoding": "gzip"}, ResponsesTransportErrorCode.RESPONSE_INVALID),
        ({"Transfer-Encoding": "chunked"}, ResponsesTransportErrorCode.RESPONSE_INVALID),
        ({"Content-Type": "text/plain"}, ResponsesTransportErrorCode.RESPONSE_INVALID),
        ({"Content-Length": "01"}, ResponsesTransportErrorCode.RESPONSE_INVALID),
        ({"Content-Length": "1, 1"}, ResponsesTransportErrorCode.RESPONSE_INVALID),
        ({"Content-Length": "99999"}, ResponsesTransportErrorCode.RESPONSE_TOO_LARGE),
    ),
)
def test_response_framing_compression_and_declared_cap_fail_closed(
    headers: dict[str, str],
    expected: ResponsesTransportErrorCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers=headers,
            stream=httpx.ByteStream(RESPONSE_BYTES),
        )

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(_request())
    assert caught.value.code is expected


def test_response_declared_length_mismatch_and_raw_stream_cap_fail_closed() -> None:
    class LargeStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b'{"padding":"'
            yield b"x" * 100
            yield b'"}'

    def mismatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"Content-Length": str(len(RESPONSE_BYTES) + 1)},
            content=RESPONSE_BYTES,
        )

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(mismatch).send(_request())
    assert caught.value.code is ResponsesTransportErrorCode.RESPONSE_INVALID

    def large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, stream=LargeStream())

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(large).send(_request(profile=_profile(max_response_bytes=32)))
    assert caught.value.code is ResponsesTransportErrorCode.RESPONSE_TOO_LARGE


@pytest.mark.parametrize(
    "raw",
    (
        b"not-json",
        b'\xef\xbb\xbf{"ok":true}',
        b'{"id":"one","id":"two"}',
        b'{"value":"\xff"}',
        b'{"value":Infinity}',
        b"[]",
    ),
)
def test_response_requires_strict_utf8_unique_key_json(raw: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, content=raw)

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(_request())
    assert caught.value.code is ResponsesTransportErrorCode.RESPONSE_INVALID


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (301, ResponsesTransportErrorCode.PROVIDER_REJECTED),
        (307, ResponsesTransportErrorCode.PROVIDER_REJECTED),
        (400, ResponsesTransportErrorCode.PROVIDER_REJECTED),
        (401, ResponsesTransportErrorCode.AUTHENTICATION),
        (403, ResponsesTransportErrorCode.AUTHENTICATION),
        (404, ResponsesTransportErrorCode.PROVIDER_REJECTED),
    ),
)
def test_nonretryable_status_is_single_attempt_without_redirect(
    status: int,
    expected: ResponsesTransportErrorCode,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, request=request, content=b"provider body")

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(_request())
    assert caught.value.code is expected
    assert caught.value.status_code == status
    assert calls == 1


@pytest.mark.parametrize("status", (429, 500, 502, 503, 504))
def test_retryable_statuses_use_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    calls = 0
    monkeypatch.setattr(adapter.time, "sleep", lambda _seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(status, request=request, headers={"Retry-After": "0"})
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    reply = _transport(handler).send(_request())
    assert reply.attempts == 3
    assert calls == 3


def test_prebody_failure_retries_but_postbody_failure_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter.time, "sleep", lambda _seconds: None)
    calls = 0

    def retry(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("redacted", request=request)
        return httpx.Response(200, request=request, content=RESPONSE_BYTES)

    assert _transport(retry).send(_request()).attempts == 3

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"{" * 16_384
            raise httpx.ReadError("post-body-secret")

    post_calls = 0

    def postbody(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        post_calls += 1
        return httpx.Response(200, request=request, stream=BrokenStream())

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(postbody).send(_request(profile=_profile(max_response_bytes=20_000)))
    assert caught.value.code is ResponsesTransportErrorCode.RESPONSE_INVALID
    assert post_calls == 1


def test_retry_after_and_total_deadline_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        adapter.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, request=request, headers={"Retry-After": "9999"})

    request = _request(profile=_profile(total_deadline_seconds=0.05, retry_after_cap_seconds=0.1))
    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(request)
    assert caught.value.code is ResponsesTransportErrorCode.DEADLINE_EXCEEDED
    assert calls == 1


def test_public_failure_chain_never_exposes_credential_or_request() -> None:
    secret_body = "request-secret-marker"
    request_bytes = ('{"input":"' + secret_body + '"}').encode()

    def handler(request: httpx.Request) -> httpx.Response:
        leaked = f"Bearer {KEY} {request.content.decode()}"
        raise httpx.ConnectError(leaked, request=request)

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(
            _request(request_bytes=request_bytes, profile=_profile(max_attempts=1))
        )
    error = caught.value
    assert error.code is ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = " ".join((str(error), repr(error), repr(error.args), repr(error.__dict__)))
    assert KEY not in rendered
    assert secret_body not in rendered
    assert "Authorization" not in rendered


def test_mutated_transport_error_is_reconstructed_to_safe_default() -> None:
    secret = "mutated-error-secret"
    poisoned = ResponsesTransportError(ResponsesTransportErrorCode.RESPONSE_INVALID)
    object.__setattr__(poisoned, "code", secret)
    object.__setattr__(poisoned, "status_code", 10_000)
    poisoned.args = (secret,)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise poisoned

    with pytest.raises(ResponsesTransportError) as caught:
        _transport(handler).send(_request())
    error = caught.value
    assert error.code is ResponsesTransportErrorCode.PROVIDER_UNAVAILABLE
    assert error.status_code is None
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in repr(error)


def test_profile_exact_types_order_and_positive_bounds_are_required() -> None:
    invalid = (
        {"max_attempts": True},
        {"max_response_bytes": 0},
        {"retryable_statuses": [429]},
        {"retryable_statuses": (500, 429)},
        {"retryable_statuses": (429, 429)},
        {"total_deadline_seconds": 0.0},
        {"total_deadline_seconds": float("nan")},
        {"read_timeout_seconds": float("inf")},
        {"max_request_bytes": MAX_RESPONSES_REQUEST_BYTES + 1},
        {"max_response_bytes": MAX_RESPONSES_RESPONSE_BYTES + 1},
        {"max_attempts": MAX_RESPONSES_ATTEMPTS + 1},
        {"retryable_statuses": (418,)},
        {"total_deadline_seconds": MAX_RESPONSES_TOTAL_DEADLINE_SECONDS + 0.1},
        {"connect_timeout_seconds": MAX_RESPONSES_CONNECT_TIMEOUT_SECONDS + 0.1},
        {"read_timeout_seconds": MAX_RESPONSES_READ_TIMEOUT_SECONDS + 0.1},
        {"write_timeout_seconds": MAX_RESPONSES_WRITE_TIMEOUT_SECONDS + 0.1},
        {"pool_timeout_seconds": MAX_RESPONSES_POOL_TIMEOUT_SECONDS + 0.1},
        {"backoff_base_seconds": MAX_RESPONSES_BACKOFF_BASE_SECONDS + 0.1},
        {"retry_after_cap_seconds": MAX_RESPONSES_RETRY_AFTER_SECONDS + 0.1},
    )
    for override in invalid:
        with pytest.raises((TypeError, ValueError)):
            _profile(**override)


def test_shared_profile_maxima_equal_the_existing_generation_transport_policy() -> None:
    assert MAX_RESPONSES_REQUEST_BYTES == 2_200_000
    assert MAX_RESPONSES_RESPONSE_BYTES == 1_048_576
    assert MAX_RESPONSES_ATTEMPTS == 3
    assert MAX_RESPONSES_TOTAL_DEADLINE_SECONDS == 45.0
    assert MAX_RESPONSES_CONNECT_TIMEOUT_SECONDS == 5.0
    assert MAX_RESPONSES_READ_TIMEOUT_SECONDS == 30.0
    assert MAX_RESPONSES_WRITE_TIMEOUT_SECONDS == 10.0
    assert MAX_RESPONSES_POOL_TIMEOUT_SECONDS == 5.0
    assert MAX_RESPONSES_BACKOFF_BASE_SECONDS == 0.25
    assert MAX_RESPONSES_RETRY_AFTER_SECONDS == 2.0
    assert RESPONSES_RETRYABLE_STATUSES == (429, 500, 502, 503, 504)
