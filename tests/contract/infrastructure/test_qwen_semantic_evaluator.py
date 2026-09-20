"""Offline Qwen wire and provenance contracts for the selected fixed snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import httpx
import pytest
from tests.contract.infrastructure.test_openai_semantic_evaluator import _request

from medevidence.infrastructure.qwen_semantic_evaluator import (
    QWEN_MODEL,
    QwenChatSemanticEvaluatorV2,
    QwenSemanticError,
    finalize_qwen_observation,
    parse_qwen_completed_response,
    qwen_provider_request_semantic_v2_bytes,
    qwen_semantic_v2_provider_configuration_bytes,
    validated_qwen_endpoint,
)
from medevidence.tools.semantic_evaluation import (
    QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    QWEN_SEMANTIC_V2_PROVIDER_METHOD,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3,
    build_qwen_semantic_evaluation_result_v2,
    reconstruct_semantic_evaluation_result_v2,
    semantic_evaluation_input_bytes,
    semantic_evaluation_v2_response_schema,
)

KEY = "sk-" + "A" * 50
ENDPOINT = (
    "https://1234567890123456789.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
)


def _envelope(*, result: str = "supported", model: str = QWEN_MODEL) -> bytes:
    code = {
        "supported": "direct_support",
        "uncertain": "partial_or_ambiguous_support",
        "unsupported": "no_support",
    }[result]
    content = {
        "schema_version": "M3_STAGE2_SEMANTIC_RESULT_V2",
        "result": result,
        "rationale_codes": [code],
        "explanation": "Bounded source-grounded assessment.",
    }
    return json.dumps(
        {
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(content)},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
        separators=(",", ":"),
    ).encode()


def test_qwen_profile_and_request_only_adapt_unique_items() -> None:
    assert validated_qwen_endpoint(ENDPOINT) == ENDPOINT
    assert (
        "sha256:" + hashlib.sha256(qwen_semantic_v2_provider_configuration_bytes()).hexdigest()
        == QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH
    )
    request = _request()
    body = json.loads(qwen_provider_request_semantic_v2_bytes(request))
    assert body["messages"] == [
        {"role": "system", "content": SEMANTIC_EVALUATION_V2_PROMPT_BYTES_V3.decode()},
        {"role": "user", "content": semantic_evaluation_input_bytes(request).decode()},
    ]
    schema = semantic_evaluation_v2_response_schema()
    del schema["properties"]["rationale_codes"]["uniqueItems"]
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert body["model"] == QWEN_MODEL
    assert body["enable_thinking"] is False
    assert body["enable_search"] is False


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
        "https://evil.example/compatible-mode/v1/chat/completions",
        "https://123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions?x=1",
        "https://123.cn-beijing.maas.aliyuncs.com:443/compatible-mode/v1/chat/completions",
    ),
)
def test_endpoint_rejects_foreign_or_modified_hosts(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validated_qwen_endpoint(endpoint)


@pytest.mark.parametrize("result", ("supported", "uncertain", "unsupported"))
def test_qwen_result_uses_qwen_identity_and_replays(result: str) -> None:
    request = _request()
    candidate, _, _, _ = parse_qwen_completed_response(_envelope(result=result))
    bound = build_qwen_semantic_evaluation_result_v2(request, candidate)
    assert bound.method == QWEN_SEMANTIC_V2_PROVIDER_METHOD
    assert bound.provider_configuration_hash == QWEN_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH
    assert reconstruct_semantic_evaluation_result_v2(request, bound) == bound


def test_qwen_response_rejects_wrong_model_and_duplicate_json() -> None:
    with pytest.raises(QwenSemanticError):
        parse_qwen_completed_response(_envelope(model="qwen3.8-max"))
    raw = _envelope().replace(b'"object":', b'"object":"chat.completion","object":', 1)
    with pytest.raises(QwenSemanticError):
        parse_qwen_completed_response(raw)


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_transport_captures_safe_raw_before_finalization() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    request = _request()
    observed = evaluator.observe(request, absolute_deadline_monotonic=time.monotonic() + 95)
    assert len(calls) == 1
    assert calls[0].url.host == "1234567890123456789.cn-beijing.maas.aliyuncs.com"
    assert observed.raw_body == _envelope()
    assert observed.body_complete
    assert (
        finalize_qwen_observation(request, observed).result.method
        == QWEN_SEMANTIC_V2_PROVIDER_METHOD
    )
    evaluator.close()


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_transport_suppresses_credential_echo() -> None:
    raw = json.dumps({"error": {"message": KEY}}).encode()
    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY,
        endpoint=ENDPOINT,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(400, headers={"content-type": "application/json"}, content=raw)
        ),
    )
    observed = evaluator.observe(_request(), absolute_deadline_monotonic=time.monotonic() + 95)
    assert observed.raw_body is None
    assert observed.credential_echo
    evaluator.close()


@pytest.mark.allow_hosts(["127.0.0.1", "::1"])
def test_qwen_total_deadline_interrupts_slow_response() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    evaluator = QwenChatSemanticEvaluatorV2(
        api_key=KEY, endpoint=ENDPOINT, transport=httpx.MockTransport(handle)
    )
    try:
        observed = evaluator.observe(
            _request(), absolute_deadline_monotonic=time.monotonic() + 0.02
        )
        assert observed.raw_body is None
        assert observed.transport_error == "deadline_exceeded"
    finally:
        evaluator.close()
