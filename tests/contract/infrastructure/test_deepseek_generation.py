"""Socket-disabled DeepSeek generation transport and framing contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from tests.unit.tools.test_deepseek_generation import _raw, _response
from tests.unit.tools.test_generation import generation_input

from medevidence.infrastructure.deepseek_generation import (
    DeepSeekGenerationGatewayError,
    DeepSeekGenerationGatewayErrorCode,
    DeepSeekResponsesGenerationGateway,
)
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekTransportErrorCode,
)
from medevidence.tools.deepseek_generation import deepseek_generation_request_bytes


def _http(status: int, body: bytes, *, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": content_type},
        content=body,
        extensions={"http_version": b"HTTP/2"},
    )


def test_mock_transport_posts_exact_bounded_request_and_returns_clean_result() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _http(200, _raw())

    gateway = DeepSeekResponsesGenerationGateway(
        api_key="synthetic-bounded-key", transport=httpx.MockTransport(handler)
    )
    result = gateway.generate(generation_input())
    assert result.provider == "deepseek"
    assert result.requested_model_alias == result.reported_model == "deepseek-flash"
    assert result.raw_response == _raw()
    assert result.attempts == 1
    assert len(sent) == 1
    assert sent[0].url == httpx.URL("https://api.deepseek.com/responses")
    assert sent[0].content == deepseek_generation_request_bytes(generation_input())
    assert json.loads(sent[0].content)["tools"] == []


def test_retryable_status_uses_at_most_next_operation_without_real_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.infrastructure.deepseek_generation as module

    waits: list[float] = []
    monkeypatch.setattr(module.time, "sleep", waits.append)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _http(503, b"{}") if calls == 1 else _http(200, _raw())

    gateway = DeepSeekResponsesGenerationGateway(
        api_key="synthetic-bounded-key", transport=httpx.MockTransport(handler)
    )
    result = gateway.generate(generation_input())
    assert calls == 2 and result.attempts == 2
    assert len(waits) == 1 and 0.25 <= waits[0] <= 0.26


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("credential_echo", DeepSeekGenerationGatewayErrorCode.CREDENTIAL_ECHO),
        ("credential_header", DeepSeekGenerationGatewayErrorCode.CREDENTIAL_ECHO),
        ("refusal", DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID),
        ("nonjson", DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID),
        ("html", DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID),
        ("gzip", DeepSeekGenerationGatewayErrorCode.RESPONSE_INVALID),
        ("oversize", DeepSeekGenerationGatewayErrorCode.RESPONSE_TOO_LARGE),
        ("authentication", DeepSeekGenerationGatewayErrorCode.AUTHENTICATION_FAILED),
    ),
)
def test_mock_transport_failures_are_redacted_and_nonretryable(
    kind: str, expected: DeepSeekGenerationGatewayErrorCode
) -> None:
    key = "synthetic-bounded-key"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "credential_echo":
            return _http(200, b'{"error":"' + key.encode() + b'"}')
        if kind == "credential_header":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json", "X-Request-Id": key},
                content=_raw(),
                extensions={"http_version": b"HTTP/2"},
            )
        if kind == "refusal":
            document = _response()
            document["output"][0]["content"][0] = {"type": "refusal", "refusal": "no"}  # type: ignore[index]
            return _http(200, json.dumps(document).encode())
        if kind == "nonjson":
            return _http(200, b"not json")
        if kind == "html":
            return _http(200, _raw(), content_type="text/html")
        if kind == "gzip":
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
                content=_raw(),
                extensions={"http_version": b"HTTP/2"},
            )
        if kind == "oversize":
            return _http(200, b"x" * 131_073)
        return _http(401, b"{}")

    gateway = DeepSeekResponsesGenerationGateway(
        api_key=key, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(DeepSeekGenerationGatewayError) as captured:
        gateway.generate(generation_input())
    assert captured.value.gateway_code is expected
    assert key not in str(captured.value)
    assert calls == 1


def test_unavailable_transport_stops_after_three_attempts_under_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.infrastructure.deepseek_generation as module

    now = [100.0]
    waits: list[float] = []
    calls = 0
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    def unavailable(*_args: object, **_kwargs: object) -> DeepSeekOneOperationObservation:
        nonlocal calls
        calls += 1
        instant = datetime(2026, 9, 14, tzinfo=UTC)
        return DeepSeekOneOperationObservation(
            http_status=None,
            approved_headers={},
            raw_body=None,
            body_complete=False,
            observed_body_bytes_lower_bound=0,
            credential_echo=False,
            transport_error=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
            started_at_utc=instant,
            completed_at_utc=instant,
        )

    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(module.DeepSeekRawTransport, "execute_one", unavailable)
    gateway = DeepSeekResponsesGenerationGateway(
        api_key="synthetic-bounded-key",
        transport=httpx.MockTransport(lambda _request: pytest.fail("transport was patched")),
    )
    with pytest.raises(DeepSeekGenerationGatewayError) as captured:
        gateway.generate(generation_input())
    assert captured.value.gateway_code is DeepSeekGenerationGatewayErrorCode.PROVIDER_UNAVAILABLE
    assert calls == 3
    assert len(waits) == 2 and all(0 < value <= 2 for value in waits)


def test_shared_deadline_blocks_retry_after_incomplete_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.infrastructure.deepseek_generation as module

    now = [100.0]
    calls = 0
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def incomplete(*_args: object, **_kwargs: object) -> DeepSeekOneOperationObservation:
        nonlocal calls
        calls += 1
        now[0] = 145.0
        instant = datetime(2026, 9, 14, tzinfo=UTC)
        return DeepSeekOneOperationObservation(
            http_status=200,
            approved_headers={"content-type": "application/json"},
            raw_body=None,
            body_complete=False,
            observed_body_bytes_lower_bound=7,
            credential_echo=False,
            transport_error=DeepSeekTransportErrorCode.PROVIDER_UNAVAILABLE,
            started_at_utc=instant,
            completed_at_utc=instant,
            response_http_version="HTTP/2",
            response_header_items=(("content-type", "application/json"),),
            response_header_field_count=1,
        )

    monkeypatch.setattr(module.DeepSeekRawTransport, "execute_one", incomplete)
    gateway = DeepSeekResponsesGenerationGateway(
        api_key="synthetic-bounded-key",
        transport=httpx.MockTransport(lambda _request: pytest.fail("transport was patched")),
    )
    with pytest.raises(DeepSeekGenerationGatewayError) as captured:
        gateway.generate(generation_input())
    assert captured.value.gateway_code is DeepSeekGenerationGatewayErrorCode.DEADLINE_EXCEEDED
    assert calls == 1
