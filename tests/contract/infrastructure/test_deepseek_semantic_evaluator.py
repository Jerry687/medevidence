from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
from tests.contract.infrastructure.test_openai_semantic_evaluator import (
    _candidate,
    _request,
)

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekResponsesSemanticEvaluator,
    DeepSeekSemanticEvaluatorError,
    DeepSeekSemanticEvaluatorErrorCode,
    deepseek_provider_request_bytes,
    deepseek_response_format,
    parse_deepseek_completed_response,
)
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    DEEPSEEK_SEMANTIC_EVALUATION_METHOD,
    SEMANTIC_EVALUATION_PROMPT_BYTES,
)

API_KEY = "deepseek-test-key-not-a-secret"
RESPONSE_ID = "123e4567-e89b-42d3-a456-426614174000"


def _response(*, candidate: str | None = None) -> dict[str, Any]:
    return {
        "id": RESPONSE_ID,
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "deepseek-v4-pro",
        "store": False,
        "previous_response_id": None,
        "parallel_tool_calls": True,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode(),
        "max_output_tokens": 4096,
        "reasoning": {"effort": "high"},
        "text": {"format": deepseek_response_format()},
        "tool_choice": "none",
        "tools": [],
        "output": [
            {
                "id": "reasoning-1",
                "type": "reasoning",
                "status": "completed",
                "content": [
                    {
                        "type": "reasoning_text",
                        "text": "provider-private reasoning retained only in raw bytes",
                    }
                ],
                "summary": [],
            },
            {
                "id": "message-1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": candidate or _candidate(),
                        "annotations": [],
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 2},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 2},
            "total_tokens": 15,
        },
    }


def _transport(document: dict[str, Any]) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=canonical_json(document).encode(),
        )
    )


def test_exact_request_is_deepseek_only_and_contains_no_labels_or_openai_state() -> None:
    request = _request()
    raw = deepseek_provider_request_bytes(request)
    body = json.loads(raw)
    assert set(body) == {
        "input",
        "instructions",
        "max_output_tokens",
        "model",
        "reasoning",
        "text",
        "tool_choice",
        "tools",
    }
    assert body["model"] == "deepseek-v4-pro"
    assert body["reasoning"] == {"effort": "high"}
    assert body["tools"] == [] and body["tool_choice"] == "none"
    assert set(body["text"]["format"]) == {"type", "name", "schema"}
    lowered = raw.lower()
    for forbidden in (
        b"store",
        b"background",
        b"parallel_tool_calls",
        b"truncation",
        b"previous_response_id",
        b"conversation",
        b"human_expected_state",
        b"human_resolution",
        b"answer_label",
    ):
        assert forbidden not in lowered


def test_evaluator_binds_deepseek_profile_and_keeps_reasoning_raw_only() -> None:
    request = _request()
    evaluator = DeepSeekResponsesSemanticEvaluator(
        api_key=API_KEY, transport=_transport(_response())
    )
    assessment = evaluator.evaluate(request)
    assert assessment.result.method == DEEPSEEK_SEMANTIC_EVALUATION_METHOD
    assert assessment.result.configuration_hash == DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH
    assert b"provider-private reasoning" in assessment.raw_response_envelope_bytes
    assert "provider-private reasoning" not in assessment.result.explanation
    assert assessment.provider_response_id == RESPONSE_ID


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda value: value.update(model="gpt-5.6-terra"), "response_model_mismatch"),
        (lambda value: value.update(status="incomplete"), "response_incomplete"),
        (lambda value: value.update(store=True), "response_invalid"),
        (lambda value: value.update(previous_response_id="foreign"), "response_invalid"),
        (lambda value: value.update(extra=True), "response_invalid"),
        (lambda value: value.update(parallel_tool_calls=False), "response_invalid"),
        (lambda value: value.pop("parallel_tool_calls"), "response_invalid"),
    ],
)
def test_response_identity_state_and_shape_fail_closed(mutator: object, code: str) -> None:
    value = deepcopy(_response())
    mutator(value)  # type: ignore[operator]
    with pytest.raises(DeepSeekSemanticEvaluatorError, match=code):
        parse_deepseek_completed_response(canonical_json(value).encode())


def test_duplicate_noncanonical_refusal_tool_and_usage_drift_fail_closed() -> None:
    raw = canonical_json(_response()).encode()
    duplicate = raw.replace(b'{"created_at":', b'{"created_at":1,"created_at":', 1)
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        parse_deepseek_completed_response(duplicate)

    noncanonical = deepcopy(_response())
    noncanonical["output"][1]["content"][0]["text"] = json.dumps(  # type: ignore[index]
        json.loads(_candidate()), indent=2
    )
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="candidate_invalid"):
        parse_deepseek_completed_response(canonical_json(noncanonical).encode())

    for part, code in (
        ({"type": "refusal", "refusal": "no"}, "response_refused"),
        ({"type": "web_search_call", "id": "x"}, "response_tool_output"),
    ):
        value = deepcopy(_response())
        value["output"][1]["content"] = [part]  # type: ignore[index]
        with pytest.raises(DeepSeekSemanticEvaluatorError, match=code):
            parse_deepseek_completed_response(canonical_json(value).encode())


@pytest.mark.parametrize("response_id", (RESPONSE_ID, "resp_123", "response-id.v4/pro"))
def test_documented_bounded_unique_string_response_ids_pass(response_id: str) -> None:
    value = _response()
    value["id"] = response_id
    assert parse_deepseek_completed_response(canonical_json(value).encode())[1] == response_id


@pytest.mark.parametrize(
    "response_id",
    ("", "contains space", "tab\tvalue", "snowman-☃", "x" * 513),
)
def test_invalid_response_ids_fail_closed(response_id: str) -> None:
    value = _response()
    value["id"] = response_id
    with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
        parse_deepseek_completed_response(canonical_json(value).encode())

    for usage in (
        {**_response()["usage"], "extra": 0},
        {**_response()["usage"], "input_tokens": True},
        {**_response()["usage"], "total_tokens": 99},
    ):
        value = deepcopy(_response())
        value["usage"] = usage
        with pytest.raises(DeepSeekSemanticEvaluatorError, match="response_invalid"):
            parse_deepseek_completed_response(canonical_json(value).encode())


def test_cross_provider_envelope_is_rejected() -> None:
    value = _response()
    value["id"] = "resp_123"
    value["model"] = "gpt-5.6-terra"
    value["background"] = False
    with pytest.raises(DeepSeekSemanticEvaluatorError):
        parse_deepseek_completed_response(canonical_json(value).encode())


def test_transport_errors_are_redacted() -> None:
    secret = "secret-value-that-must-not-escape"
    evaluator = DeepSeekResponsesSemanticEvaluator(
        api_key=secret,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                401,
                headers={"Content-Type": "application/json"},
                json={"error": secret},
            )
        ),
    )
    with pytest.raises(DeepSeekSemanticEvaluatorError) as captured:
        evaluator.evaluate(_request())
    assert captured.value.code is DeepSeekSemanticEvaluatorErrorCode.AUTHENTICATION
    assert secret not in str(captured.value)
