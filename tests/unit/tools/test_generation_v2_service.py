"""DeepSeek Flash/none Generation V2 request, response, receipt, and service."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tests.unit.tools.test_generation_v2 import (
    _candidate,
    _input,
    _qualitative_claim,
    _trusted,
)

from medevidence.domain import canonical_json
from medevidence.tools.generation import GenerationGatewayError, GenerationUsage
from medevidence.tools.generation_v2 import (
    GENERATION_V2_CONFIG_HASH,
    GENERATION_V2_PROMPT_BYTES,
    GENERATION_V2_PROMPT_HASH,
    GENERATION_V2_SCHEMA_HASH,
    CandidateCitationV2,
    CandidateClaimV2,
    GenerationCandidateV2,
    canonical_numerical_text,
    generation_v2_candidate_bytes,
)
from medevidence.tools.generation_v2_service import (
    DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH,
    DeepSeekGenerationReceiptRefV2,
    DeepSeekGenerationV2ContractError,
    DeepSeekGenerationV2Service,
    DeepSeekGenerationV2ServiceError,
    DeepSeekGenerationV2ServiceErrorCode,
    DeepSeekProviderResultV2,
    build_deepseek_generation_v2_receipt,
    deepseek_generation_v2_input_bytes,
    deepseek_generation_v2_receipt_bytes,
    deepseek_generation_v2_receipt_ref,
    deepseek_generation_v2_request_bytes,
    parse_deepseek_generation_v2_receipt,
    parse_deepseek_generation_v2_response,
)
from medevidence.tools.report_validation import (
    ClaimClass,
    EvidenceInput,
    InferenceUse,
    NumericalContextInput,
    canonical_evidence_id,
)


def case() -> tuple[object, tuple[EvidenceInput, ...], GenerationCandidateV2]:
    evidence = _trusted()
    generation_input = _input(evidence)
    return generation_input, (evidence,), _candidate(generation_input, _qualitative_claim(evidence))


def response(
    candidate: GenerationCandidateV2 | None = None,
) -> dict[str, object]:
    generation_input, evidence, default = case()
    del generation_input, evidence
    selected = default if candidate is None else candidate
    from medevidence.tools.generation_v2_service import (
        deepseek_generation_v2_response_format,
    )

    return {
        "id": "12345678-1234-4234-9234-123456789abc",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "deepseek-flash",
        "store": False,
        "previous_response_id": None,
        "instructions": GENERATION_V2_PROMPT_BYTES.decode(),
        "reasoning": {"effort": "none", "summary": None},
        "text": {"format": deepseek_generation_v2_response_format()},
        "tools": [],
        "tool_choice": "none",
        "max_output_tokens": 8192,
        "parallel_tool_calls": True,
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": generation_v2_candidate_bytes(selected).decode(),
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def raw(document: dict[str, object] | None = None) -> bytes:
    return canonical_json(response() if document is None else document).encode()


def result(
    generation_input: object | None = None,
    evidence: tuple[EvidenceInput, ...] | None = None,
    body: bytes | None = None,
) -> DeepSeekProviderResultV2:
    default_input, default_evidence, _ = case()
    selected_input = default_input if generation_input is None else generation_input
    selected_evidence = default_evidence if evidence is None else evidence
    selected_raw = raw() if body is None else body
    candidate, response_id, usage, reported_model = parse_deepseek_generation_v2_response(
        selected_raw,
        selected_input,
        selected_evidence,  # type: ignore[arg-type]
    )
    now = datetime(2026, 9, 15, tzinfo=UTC)
    request_hash = (
        "sha256:"
        + hashlib.sha256(
            deepseek_generation_v2_request_bytes(
                selected_input,
                selected_evidence,  # type: ignore[arg-type]
            )
        ).hexdigest()
    )
    return DeepSeekProviderResultV2(
        candidate=candidate,
        reported_model=reported_model,
        request_hash=request_hash,
        response_hash="sha256:" + hashlib.sha256(selected_raw).hexdigest(),
        raw_response=selected_raw,
        provider_response_id=response_id,
        attempts=1,
        usage=usage,
        started_at_utc=now,
        completed_at_utc=now,
    )


def test_request_binds_full_numeric_evidence_and_none_profile() -> None:
    context = NumericalContextInput(
        "7", "count", "population", "none", "window", "bounded population"
    )
    evidence = _trusted(context=context)
    generation_input = _input(evidence)
    claim = CandidateClaimV2(
        ordinal=1,
        source=evidence.source,
        statement=canonical_numerical_text(context),
        claim_class=ClaimClass.DESCRIPTIVE,
        inference_use=InferenceUse.DESCRIPTIVE,
        qualitative_code=None,
        numerical_context=context,
        citations=(
            CandidateCitationV2(
                evidence_id=evidence.evidence_id,
                locator_ref=evidence.locators[0],
                relationship="supports",
            ),
        ),
        presented_limitation_ids=(),
        conflict_ids=(),
    )
    request = json.loads(deepseek_generation_v2_request_bytes(generation_input, (evidence,)))
    assert set(request) == {
        "input",
        "instructions",
        "max_output_tokens",
        "model",
        "reasoning",
        "text",
        "tool_choice",
        "tools",
    }
    assert request["model"] == "deepseek-flash"
    assert request["reasoning"] == {"effort": "none"}
    assert request["tools"] == [] and request["tool_choice"] == "none"
    material = deepseek_generation_v2_input_bytes(generation_input, (evidence,)).decode()
    payload = json.loads(material.split("\n", maxsplit=1)[1].rsplit("\n", maxsplit=1)[0])
    fact = payload["trusted_evidence"][0]["numerical_facts"][0]
    assert fact["exact_text"] == canonical_numerical_text(context)
    assert tuple(fact[name] for name in context.__dataclass_fields__) == tuple(
        getattr(context, name) for name in context.__dataclass_fields__
    )
    assert _candidate(generation_input, claim).claims[0].statement == fact["exact_text"]
    assert DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH not in {
        GENERATION_V2_CONFIG_HASH,
        GENERATION_V2_PROMPT_HASH,
        GENERATION_V2_SCHEMA_HASH,
    }
    assert DEEPSEEK_GENERATION_V2_CONFIGURATION_HASH == (
        "sha256:f515d045a1800efcfcec3bbf351ad45011e973df5824d92b7ae1751e995bd896"
    )


def test_complete_response_and_v2_receipt_round_trip() -> None:
    generation_input, evidence, candidate = case()
    parsed, response_id, usage, reported = parse_deepseek_generation_v2_response(
        raw(),
        generation_input,
        evidence,  # type: ignore[arg-type]
    )
    assert parsed == candidate
    assert response_id == response()["id"] and reported == "deepseek-flash"
    assert usage == GenerationUsage(
        input_tokens=100,
        output_tokens=40,
        total_tokens=140,
        cached_input_tokens=0,
        reasoning_output_tokens=0,
    )
    receipt = build_deepseek_generation_v2_receipt(
        generation_input,
        evidence,
        result(),  # type: ignore[arg-type]
    )
    assert receipt.marker == "M3_DEEPSEEK_GENERATION_RECEIPT_V2"
    assert receipt.prompt_version == "m3.generation.synthesis.v2"
    assert receipt.response_schema_version == "m3.generation.candidate.v2"
    assert receipt.provider_configuration_version.endswith(".v2")
    assert receipt.trusted_evidence_hash.startswith("sha256:")
    assert receipt.generation_material_hash.startswith("sha256:")
    assert (
        parse_deepseek_generation_v2_receipt(deepseek_generation_v2_receipt_bytes(receipt))
        == receipt
    )
    assert deepseek_generation_v2_receipt_ref(receipt).receipt_version.endswith(".v2")


@pytest.mark.parametrize(
    "change",
    (
        "store",
        "continuation",
        "reasoning",
        "reasoning_tokens",
        "usage_total",
        "refusal",
        "tool",
        "extra_output",
        "annotations",
        "prompt",
        "schema",
        "candidate",
        "duplicate",
        "bom",
    ),
)
def test_untrusted_response_fails_closed(change: str) -> None:
    generation_input, evidence, _ = case()
    document = deepcopy(response())
    if change == "store":
        document["store"] = True
    elif change == "continuation":
        document["previous_response_id"] = "foreign"
    elif change == "reasoning":
        document["reasoning"] = {"effort": "high"}
    elif change == "reasoning_tokens":
        document["usage"]["output_tokens_details"]["reasoning_tokens"] = 1  # type: ignore[index]
    elif change == "usage_total":
        document["usage"]["total_tokens"] = 139  # type: ignore[index]
    elif change == "refusal":
        document["output"][0]["content"][0] = {"type": "refusal", "refusal": "no"}  # type: ignore[index]
    elif change == "tool":
        document["output"][0]["type"] = "function_call"  # type: ignore[index]
    elif change == "extra_output":
        document["output"].append(deepcopy(document["output"][0]))  # type: ignore[union-attr,index]
    elif change == "annotations":
        document["output"][0]["content"][0]["annotations"] = [{"url": "https://invalid"}]  # type: ignore[index]
    elif change == "prompt":
        document["instructions"] = "different"
    elif change == "schema":
        document["text"]["format"]["strict"] = False  # type: ignore[index]
    elif change == "candidate":
        document["output"][0]["content"][0]["text"] = "{}"  # type: ignore[index]
    changed_raw = raw(document)
    if change == "duplicate":
        changed_raw = changed_raw[:-1] + b',"status":"completed"}'
    elif change == "bom":
        changed_raw = b"\xef\xbb\xbf" + changed_raw
    with pytest.raises(DeepSeekGenerationV2ContractError):
        parse_deepseek_generation_v2_response(
            changed_raw,
            generation_input,
            evidence,  # type: ignore[arg-type]
        )


def test_request_rejects_trusted_evidence_drift_before_gateway() -> None:
    generation_input, evidence, _ = case()
    changed = (replace(evidence[0], source_version="other"),)
    with pytest.raises(DeepSeekGenerationV2ContractError, match="trusted_evidence"):
        deepseek_generation_v2_request_bytes(
            generation_input,
            changed,  # type: ignore[arg-type]
        )


def test_request_rejects_combined_material_above_provider_bound() -> None:
    evidence_rows = []
    for index in range(40):
        evidence = replace(
            _trusted(index=index),
            normalized_excerpt=f"{index:03d}" + "x" * 4_093,
        )
        evidence_rows.append(replace(evidence, evidence_id=canonical_evidence_id(evidence)))
    trusted = tuple(evidence_rows)
    generation_input = _input(*trusted)
    assert len(deepseek_generation_v2_input_bytes(generation_input, trusted)) < 1_048_576
    with pytest.raises(DeepSeekGenerationV2ContractError, match="request_too_large"):
        deepseek_generation_v2_request_bytes(generation_input, trusted)


def test_service_persists_and_reparses_before_return() -> None:
    generation_input, evidence, candidate = case()
    provider_result = result()
    events: list[str] = []

    class Gateway:
        def generate(
            self, _value: object, *, trusted_evidence: tuple[EvidenceInput, ...]
        ) -> DeepSeekProviderResultV2:
            assert trusted_evidence == evidence
            events.append("gateway")
            return provider_result

    class Store:
        stored: tuple[object, bytes] | None = None

        def save(self, receipt: object, clean_raw_response: bytes) -> object:
            events.append("save")
            self.stored = (receipt, clean_raw_response)
            return deepseek_generation_v2_receipt_ref(receipt)  # type: ignore[arg-type]

        def load(self, reference: object) -> tuple[object, bytes]:
            events.append("load")
            assert self.stored is not None
            receipt, saved_raw = self.stored
            assert deepseek_generation_v2_receipt_ref(receipt) == reference  # type: ignore[arg-type]
            return receipt, saved_raw

    durable = DeepSeekGenerationV2Service(
        gateway=Gateway(),
        store=Store(),  # type: ignore[arg-type]
    ).generate(generation_input, trusted_evidence=evidence)  # type: ignore[arg-type]
    assert durable.candidate == candidate
    assert events == ["gateway", "save", "load"]


def test_service_rejects_gateway_and_receipt_drift() -> None:
    generation_input, evidence, _ = case()

    class FailingGateway:
        def generate(self, _value: object, **_kwargs: object) -> DeepSeekProviderResultV2:
            raise GenerationGatewayError("provider_unavailable")

    class UnusedStore:
        def save(self, *_args: object) -> DeepSeekGenerationReceiptRefV2:
            pytest.fail("store must not be called")

        def load(self, *_args: object) -> tuple[object, bytes]:
            pytest.fail("store must not be called")

    service = DeepSeekGenerationV2Service(
        gateway=FailingGateway(),
        store=UnusedStore(),  # type: ignore[arg-type]
    )
    with pytest.raises(GenerationGatewayError, match="provider_unavailable"):
        service.generate(generation_input, trusted_evidence=evidence)  # type: ignore[arg-type]

    provider_result = result()

    class Gateway:
        def generate(self, _value: object, **_kwargs: object) -> DeepSeekProviderResultV2:
            return provider_result

    class BadStore:
        def save(self, receipt: object, _raw: bytes) -> DeepSeekGenerationReceiptRefV2:
            return deepseek_generation_v2_receipt_ref(receipt).model_copy(  # type: ignore[arg-type]
                update={"candidate_hash": "sha256:" + "f" * 64}
            )

        def load(self, *_args: object) -> tuple[object, bytes]:
            pytest.fail("load must not be called")

    with pytest.raises(DeepSeekGenerationV2ServiceError) as captured:
        DeepSeekGenerationV2Service(
            gateway=Gateway(),
            store=BadStore(),  # type: ignore[arg-type]
        ).generate(generation_input, trusted_evidence=evidence)  # type: ignore[arg-type]
    assert captured.value.code is DeepSeekGenerationV2ServiceErrorCode.RECEIPT_INVALID
