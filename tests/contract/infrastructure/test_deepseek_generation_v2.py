"""Socket-disabled DeepSeek Flash Generation V2 transport contracts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from tests.unit.tools.test_generation_v2_service import case, raw, response

from medevidence.infrastructure.deepseek_generation_v2 import (
    DeepSeekGenerationV2GatewayError,
    DeepSeekGenerationV2GatewayErrorCode,
    DeepSeekResponsesGenerationV2Gateway,
)
from medevidence.infrastructure.deepseek_responses_transport import (
    DeepSeekOneOperationObservation,
    DeepSeekTransportErrorCode,
)
from medevidence.tools.generation_v2_service import deepseek_generation_v2_request_bytes


def _http(status: int, body: bytes, *, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": content_type},
        content=body,
        extensions={"http_version": b"HTTP/2"},
    )


def test_mock_transport_posts_exact_v2_request_and_returns_clean_result() -> None:
    generation_input, evidence, candidate = case()
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return _http(200, raw())

    gateway = DeepSeekResponsesGenerationV2Gateway(
        api_key="synthetic-bounded-key", transport=httpx.MockTransport(handler)
    )
    result = gateway.generate(
        generation_input,
        trusted_evidence=evidence,  # type: ignore[arg-type]
    )
    assert result.candidate == candidate
    assert result.requested_model_alias == result.reported_model == "deepseek-flash"
    assert result.raw_response == raw() and result.attempts == 1
    assert len(sent) == 1
    assert sent[0].url == httpx.URL("https://api.deepseek.com/responses")
    assert sent[0].content == deepseek_generation_v2_request_bytes(
        generation_input,
        evidence,  # type: ignore[arg-type]
    )
    assert json.loads(sent[0].content)["reasoning"] == {"effort": "none"}


def test_invalid_trusted_evidence_makes_zero_transport_calls() -> None:
    generation_input, evidence, _ = case()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _http(200, raw())

    gateway = DeepSeekResponsesGenerationV2Gateway(
        api_key="synthetic-bounded-key", transport=httpx.MockTransport(handler)
    )
    changed = (replace(evidence[0], source_version="foreign"),)
    with pytest.raises(DeepSeekGenerationV2GatewayError) as captured:
        gateway.generate(
            generation_input,
            trusted_evidence=changed,  # type: ignore[arg-type]
        )
    assert captured.value.gateway_code is DeepSeekGenerationV2GatewayErrorCode.REQUEST_INVALID
    assert calls == 0


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("credential_echo", DeepSeekGenerationV2GatewayErrorCode.CREDENTIAL_ECHO),
        ("reasoning", DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID),
        ("refusal", DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID),
        ("extra_output", DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID),
        ("html", DeepSeekGenerationV2GatewayErrorCode.RESPONSE_INVALID),
        ("oversize", DeepSeekGenerationV2GatewayErrorCode.RESPONSE_TOO_LARGE),
        ("authentication", DeepSeekGenerationV2GatewayErrorCode.AUTHENTICATION_FAILED),
    ),
)
def test_transport_failures_are_redacted_and_nonretryable(
    kind: str, expected: DeepSeekGenerationV2GatewayErrorCode
) -> None:
    generation_input, evidence, _ = case()
    key = "synthetic-bounded-key"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "credential_echo":
            return _http(200, b'{"error":"' + key.encode() + b'"}')
        document = response()
        if kind == "reasoning":
            document["usage"]["output_tokens_details"]["reasoning_tokens"] = 1  # type: ignore[index]
            return _http(200, raw(document))
        if kind == "refusal":
            document["output"][0]["content"][0] = {"type": "refusal", "refusal": "no"}  # type: ignore[index]
            return _http(200, raw(document))
        if kind == "extra_output":
            document["output"].append(document["output"][0])  # type: ignore[union-attr,index]
            return _http(200, raw(document))
        if kind == "html":
            return _http(200, raw(), content_type="text/html")
        if kind == "oversize":
            return _http(200, b"x" * 131_073)
        return _http(401, b"{}")

    gateway = DeepSeekResponsesGenerationV2Gateway(
        api_key=key, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(DeepSeekGenerationV2GatewayError) as captured:
        gateway.generate(
            generation_input,
            trusted_evidence=evidence,  # type: ignore[arg-type]
        )
    assert captured.value.gateway_code is expected
    assert key not in str(captured.value)
    assert calls == 1


def test_retryable_transport_uses_at_most_three_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import medevidence.infrastructure.deepseek_generation_v2 as module

    generation_input, evidence, _ = case()
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
        instant = datetime(2026, 9, 15, tzinfo=UTC)
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
    gateway = DeepSeekResponsesGenerationV2Gateway(
        api_key="synthetic-bounded-key",
        transport=httpx.MockTransport(lambda _request: pytest.fail("transport patched")),
    )
    with pytest.raises(DeepSeekGenerationV2GatewayError) as captured:
        gateway.generate(
            generation_input,
            trusted_evidence=evidence,  # type: ignore[arg-type]
        )
    assert captured.value.gateway_code is DeepSeekGenerationV2GatewayErrorCode.PROVIDER_UNAVAILABLE
    assert calls == 3 and len(waits) == 2
    assert all(0 < value <= 2 for value in waits)
