from __future__ import annotations

import httpx
import pytest

from medevidence.infrastructure.deepseek_responses_transport import (
    DEEPSEEK_RESPONSES_ENDPOINT,
    DeepSeekRawRequest,
    DeepSeekRawTransport,
    DeepSeekTransportError,
    DeepSeekTransportErrorCode,
    DeepSeekTransportProfile,
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

    reply = DeepSeekRawTransport(transport=httpx.MockTransport(handler)).send(_request())
    assert calls == 1 and reply.body == b'{"ok":true}' and reply.attempts == 1


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
    assert transport.send(_request()).body == b"{}"
    assert transport.send(_request()).body == b"{}"
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
    ).send(_request(response_bytes=maximum))
    assert len(reply.body) == maximum

    invalid = b'"' + b"x" * (maximum - 1) + b'"'
    with pytest.raises(DeepSeekTransportError) as captured:
        DeepSeekRawTransport(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    content=invalid,
                )
            )
        ).send(_request(response_bytes=maximum))
    assert captured.value.code is DeepSeekTransportErrorCode.RESPONSE_TOO_LARGE


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

    with pytest.raises(DeepSeekTransportError) as captured:
        DeepSeekRawTransport(transport=httpx.MockTransport(retry)).send(_request())
    assert calls == 3
    assert captured.value.code is DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE

    with pytest.raises(DeepSeekTransportError) as redirected:
        DeepSeekRawTransport(
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
        ).send(_request())
    assert redirected.value.code is DeepSeekTransportErrorCode.RESPONSE_INVALID


def test_provider_error_body_and_credential_never_escape() -> None:
    secret = "credential-must-not-escape"
    request = DeepSeekRawRequest(
        api_key=secret,
        endpoint=DEEPSEEK_RESPONSES_ENDPOINT,
        request_bytes=b"{}",
        profile=_profile(),
    )
    with pytest.raises(DeepSeekTransportError) as captured:
        DeepSeekRawTransport(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    400,
                    headers={"Content-Type": "application/json"},
                    content=(f'{{"error":"{secret}"}}').encode(),
                )
            )
        ).send(request)
    assert captured.value.code is DeepSeekTransportErrorCode.PROVIDER_REJECTED
    assert secret not in str(captured.value)
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

    with pytest.raises(DeepSeekTransportError) as captured:
        DeepSeekRawTransport(transport=httpx.MockTransport(handler)).send(_request())
    assert captured.value.code is DeepSeekTransportErrorCode.RESPONSE_INVALID
    assert calls == 1
