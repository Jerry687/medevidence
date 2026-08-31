from __future__ import annotations

import httpx
import pytest

import medevidence.infrastructure.deepseek_responses_transport as transport_module
from medevidence.infrastructure.deepseek_responses_transport import (
    DEEPSEEK_RESPONSES_ENDPOINT,
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
    credential_representations,
)


def _profile(*, response_bytes: int = 128) -> DeepSeekTransportProfile:
    return DeepSeekTransportProfile(
        max_request_bytes=128,
        max_response_bytes=response_bytes,
        max_attempts=3,
        total_deadline_seconds=45,
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=10,
        pool_timeout_seconds=5,
        backoff_base_seconds=0.25,
        retry_after_cap_seconds=2,
    )


def _request(*, response_bytes: int = 128) -> DeepSeekRawRequest:
    return DeepSeekRawRequest(
        api_key="bounded-test-key",
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b'{"input":"bounded"}',
        profile=_profile(response_bytes=response_bytes),
    )


def test_exact_endpoint_host_headers_and_bytes() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == DEEPSEEK_RESPONSES_ENDPOINT
        assert request.headers["host"] == "api.deepseek.com"
        assert request.headers["authorization"] == "Bearer bounded-test-key"
        assert request.content == b'{"input":"bounded"}'
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b'{"ok":true}',
        )

    reply = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(_request())
    assert calls == 1 and reply.raw_body == b'{"ok":true}'


def test_shared_transport_survives_multiple_sequential_requests() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )

    transport = DeepSeekRawTransport(transport=httpx.MockTransport(handler))
    assert transport.execute_one(_request()).raw_body == b"{}"
    assert transport.execute_one(_request()).raw_body == b"{}"
    assert calls == 2


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://api.deepseek.com/responses",
        "https://api.deepseek.com/v1/responses",
        "https://api.openai.com/v1/responses",
        "https://api.deepseek.com/responses?x=1",
    ),
)
def test_endpoint_substitution_rejects_before_effect(endpoint: str) -> None:
    with pytest.raises(DeepSeekTransportError, match="request_integrity"):
        DeepSeekRawRequest(
            api_key="key",
            endpoint=endpoint,
            request_bytes=b"{}",
            profile=_profile(),
        )


def test_exact_max_response_passes_and_max_plus_one_fails() -> None:
    maximum = 32
    valid = b'"' + b"x" * (maximum - 2) + b'"'
    reply = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=valid,
            )
        )
    ).execute_one(_request(response_bytes=maximum))
    assert reply.raw_body is not None and len(reply.raw_body) == maximum

    invalid = b'"' + b"x" * (maximum - 1) + b'"'
    captured = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=invalid,
            )
        )
    ).execute_one(_request(response_bytes=maximum))
    assert captured.transport_error is DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE
    assert captured.raw_body is None


def test_retry_is_bounded_and_redirect_is_never_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _value: None)
    calls = 0

    def retry(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"Content-Type": "application/json", "Retry-After": "0"},
            content=b"{}",
        )

    captured = DeepSeekRawTransport(transport=httpx.MockTransport(retry)).execute_one(_request())
    assert calls == 1
    assert captured.http_status == 503

    redirected = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                307,
                headers={
                    "Content-Type": "application/json",
                    "Location": "https://evil.example/steal",
                },
                content=b"{}",
            )
        )
    ).execute_one(_request())
    assert redirected.http_status == 307


def test_provider_error_body_and_credential_never_escape() -> None:
    secret = "credential-must-not-escape"
    request = DeepSeekRawRequest(
        api_key=secret,
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    captured = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                400,
                headers={"Content-Type": "application/json"},
                content=(f'{{"error":"{secret}"}}').encode(),
            )
        )
    ).execute_one(request)
    assert captured.credential_echo is True
    assert captured.raw_body is None
    assert secret not in repr(request)


def test_post_body_transport_failure_is_not_retried() -> None:
    calls = 0

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"{"
            raise httpx.ReadError("simulated post-body failure")

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=BrokenStream(),
        )

    captured = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).execute_one(_request())
    assert captured.transport_error is DeepSeekTransportErrorCode.RESPONSE_INVALID
    assert calls == 1


@pytest.mark.parametrize(
    "representation",
    credential_representations("bounded-test-key"),
)
def test_every_frozen_credential_representation_drops_body(
    representation: bytes,
) -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"prefix-" + representation + b"-suffix",
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_credential_detection_crosses_stream_chunk_boundary() -> None:
    marker = b"bounded-test-key"

    class SplitStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"prefix-" + marker[:5]
            yield marker[5:] + b"-suffix"

    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=SplitStream(),
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_reserved_percent_credential_crosses_chunk_boundary() -> None:
    key = "a/b?c=d&e"
    marker = b"a%2Fb%3Fc%3Dd%26e"

    class SplitPercentStream(httpx.SyncByteStream):
        def __iter__(self):  # type: ignore[no-untyped-def]
            yield b"prefix-" + marker[:7]
            yield marker[7:] + b"-suffix"

    request = DeepSeekRawRequest(
        api_key=key,
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=SplitPercentStream(),
            )
        )
    ).execute_one(request)
    assert observation.credential_echo is True
    assert observation.raw_body is None


def test_allowed_header_credential_echo_drops_header_values_and_body() -> None:
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": "bounded-test-key",
                },
                content=b"{}",
            )
        )
    ).execute_one(_request())
    assert observation.credential_echo is True
    assert observation.approved_headers == {}
    assert observation.raw_body is None


def test_retry_after_credential_echo_is_detected_before_use() -> None:
    request = DeepSeekRawRequest(
        api_key="99",
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                503,
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": "99",
                },
                content=b"{}",
            )
        )
    ).execute_one(request)
    assert observation.credential_echo is True
    assert observation.retry_after is None
    assert observation.raw_body is None


def test_finite_representation_set_includes_json_and_percent_forms() -> None:
    values = credential_representations('a/b?c=d&e"\\')
    assert b'a/b?c=d&e\\"\\\\' in values
    assert b"a%2Fb%3Fc%3Dd%26e%22%5C" in values
    assert b"a%2fb%3fc%3dd%26e%22%5c" in values
    assert b"%61%2F%62%3F%63%3D%64%26%65%22%5C" in values
    assert b"%61%2f%62%3f%63%3d%64%26%65%22%5c" in values


def test_streaming_deadline_returns_bounded_terminal_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deadline(*_args: object) -> None:
        raise DeepSeekTransportError(DeepSeekTransportErrorCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(transport_module, "_deadline", deadline)
    observation = DeepSeekRawTransport(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                stream=httpx.ByteStream(b"{}"),
            )
        )
    ).execute_one(_request())
    assert observation.transport_error is DeepSeekTransportErrorCode.DEADLINE_EXCEEDED
    assert observation.raw_body is None
