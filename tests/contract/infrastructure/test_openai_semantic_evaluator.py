from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest

from medevidence.domain import CoverageStatus, ExecutionStatus, ResultStatus, SourceType
from medevidence.infrastructure.openai_semantic_evaluator import (
    OpenAIResponsesSemanticEvaluator,
    OpenAISemanticEvaluatorError,
    OpenAISemanticEvaluatorErrorCode,
    SemanticAssessment,
)
from medevidence.tools.report_validation import (
    CitationInput,
    CitationRelationship,
    ClaimClass,
    ClaimInclusion,
    ClaimInput,
    EvidenceInput,
    InferenceUse,
    QualitativeCode,
    SemanticEvaluationInput,
    SemanticSupport,
    canonical_citation_id,
    canonical_claim_id,
    canonical_evidence_id,
)
from medevidence.tools.semantic_evaluation import (
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    SEMANTIC_EVALUATION_MODEL,
    SEMANTIC_EVALUATION_PROMPT_BYTES,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    SemanticRationaleCode,
    build_canonical_citation_stage1_binding,
    build_canonical_stage1_admission,
    build_empty_comparability_metadata,
    build_formal_claim_citation_topology,
    build_semantic_evaluation_request,
    parse_semantic_evaluation_candidate,
    semantic_evaluation_input_bytes,
    semantic_evaluation_response_schema,
)

RUN_ID = "run:12345678-1234-4123-8123-123456789abc"
SCOPE_ID = "scope:sha256:" + "a" * 64
API_KEY = "test-provider-key-not-a-secret"


def _input(
    *,
    excerpt: str = "The study reports the bounded observation.",
    relationship: CitationRelationship = CitationRelationship.SUPPORTS,
) -> SemanticEvaluationInput:
    evidence = EvidenceInput(
        "evidence:sha256:" + "0" * 64,
        RUN_ID,
        SourceType.PUBMED,
        "record:one",
        "version:one",
        "snapshot:one",
        "sha256:" + "b" * 64,
        ("abstract:0-42",),
        frozenset({ClaimClass.DESCRIPTIVE}),
        frozenset({InferenceUse.DESCRIPTIVE}),
        excerpt,
        (),
    )
    evidence = replace(evidence, evidence_id=canonical_evidence_id(evidence))
    claim = ClaimInput(
        "claim:sha256:" + "0" * 64,
        SourceType.PUBMED,
        QualitativeCode.PUBMED_DESCRIPTIVE,
        "The bounded publication supplies descriptive evidence.",
        ClaimClass.DESCRIPTIVE,
        InferenceUse.DESCRIPTIVE,
        (),
        (),
        ClaimInclusion.FORMAL,
        None,
    )
    claim = replace(claim, claim_id=canonical_claim_id(claim))
    citation = CitationInput(
        "citation:sha256:" + "0" * 64,
        claim.claim_id,
        evidence.evidence_id,
        relationship,
        evidence.source_record_id,
        evidence.source_version,
        evidence.snapshot_id,
        evidence.content_hash,
        evidence.locators[0],
        ExecutionStatus.SUCCEEDED,
        CoverageStatus.COMPLETE,
        ResultStatus.MATCHES,
    )
    citation = replace(citation, citation_id=canonical_citation_id(citation))
    claim = replace(claim, citation_ids=(citation.citation_id,))
    return SemanticEvaluationInput(RUN_ID, claim, citation, evidence)


def _stage1_binding(value: SemanticEvaluationInput):  # type: ignore[no-untyped-def]
    return build_canonical_citation_stage1_binding(
        stage1_passed=True,
        validation_receipt_id="validation-receipt:sha256:" + "2" * 64,
        validation_receipt_content_hash="sha256:" + "3" * 64,
        registry_binding_hash="sha256:" + "5" * 64,
        source_task_id=(
            f"source-task:{value.run_id.removeprefix('run:')}:{value.evidence.source.value}"
        ),
        task_binding_hash="sha256:" + "6" * 64,
        source_outcome_id=f"source-outcome:{value.evidence.source.value}",
        source_outcome_binding_hash="sha256:" + "7" * 64,
        stage1_result_id="stage1-result:sha256:" + "8" * 64,
        stage1_claim_result_id="stage1-claim-result:sha256:" + "9" * 64,
    )


def _request(
    value: SemanticEvaluationInput | None = None,
    *,
    topology: object | None = None,
) -> SemanticEvaluationRequest:
    semantic_input = value or _input()
    comparability = build_empty_comparability_metadata(run_id=RUN_ID)
    admitted_topology = topology or build_formal_claim_citation_topology(
        run_id=RUN_ID,
        claim=semantic_input.claim,
        ordered_semantic_inputs=(semantic_input,),
        ordered_stage1_bindings=(_stage1_binding(semantic_input),),
        current_citation_id=semantic_input.citation.citation_id,
    )
    admission = build_canonical_stage1_admission(
        semantic_input=semantic_input,
        stage1_passed=True,
        formal_citation_topology=admitted_topology,  # type: ignore[arg-type]
        comparability=comparability,
        scope_id=SCOPE_ID,
        report_id="report:sha256:" + "1" * 64,
        validation_receipt_id="validation-receipt:sha256:" + "2" * 64,
        validation_receipt_content_hash="sha256:" + "3" * 64,
        validation_input_hash="sha256:" + "4" * 64,
        registry_binding_hash="sha256:" + "5" * 64,
        task_binding_hash="sha256:" + "6" * 64,
        source_outcome_id="source-outcome:pubmed",
        source_outcome_binding_hash="sha256:" + "7" * 64,
        stage1_result_id="stage1-result:sha256:" + "8" * 64,
        stage1_claim_result_id="stage1-claim-result:sha256:" + "9" * 64,
        report_content_hash="sha256:" + "a" * 64,
    )
    return build_semantic_evaluation_request(
        admission,
        comparability=comparability,
    )


def _candidate(
    result: str = "supported",
    *,
    review: bool = False,
    rationale_code: str | None = None,
) -> str:
    explanation = f"Bounded advisory result: {result}."
    code = (
        {
            "supported": SemanticRationaleCode.DIRECT_SUPPORT.value,
            "uncertain": SemanticRationaleCode.PARTIAL_OR_AMBIGUOUS_SUPPORT.value,
            "unsupported": SemanticRationaleCode.NO_SUPPORT.value,
        }[result]
        if rationale_code is None
        else rationale_code
    )
    payload = {
        "schema_version": "m3.semantic-evaluation.result.v1",
        "result": result,
        "rationale_codes": [code],
        "explanation": explanation,
        "human_review_required": review,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _response(
    *,
    candidate: str | None = None,
    status: str = "completed",
    model: str = SEMANTIC_EVALUATION_MODEL,
    output: object | None = None,
) -> dict[str, object]:
    actual_output = output
    if actual_output is None:
        actual_output = [
            {"id": "rs_123", "type": "reasoning", "summary": [], "status": "completed"},
            {
                "id": "msg_123",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": candidate or _candidate(),
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            },
        ]
    return {
        "id": "resp_123",
        "object": "response",
        "created_at": 1,
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": model,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode(),
        "reasoning": {"effort": "medium", "summary": None},
        "text": {
            "format": {
                "name": "medevidence_semantic_evaluation",
                "schema": semantic_evaluation_response_schema(),
                "strict": True,
                "type": "json_schema",
            },
            "verbosity": "medium",
        },
        "background": False,
        "store": False,
        "tools": [],
        "tool_choice": "none",
        "parallel_tool_calls": False,
        "max_output_tokens": 4096,
        "truncation": "disabled",
        "service_tier": "default",
        "output": actual_output,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }


def _json_response(request: httpx.Request, body: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        stream=httpx.ByteStream(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()),
        request=request,
    )


@pytest.mark.parametrize(
    ("state", "review"),
    [("supported", False), ("uncertain", True), ("unsupported", False)],
)
def test_exact_request_and_all_three_states_bind_transport_provenance(
    state: str, review: bool
) -> None:
    seen: list[httpx.Request] = []
    response_body = _response(candidate=_candidate(state, review=review))
    response_bytes = json.dumps(response_body, separators=(",", ":"), sort_keys=True).encode()
    structured_output_bytes = _candidate(state, review=review).encode()
    evaluator_request = _request()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert body["model"] == "gpt-5.6-terra"
        assert body["reasoning"] == {"effort": "medium"}
        assert body["store"] is False and body["background"] is False
        assert body["tools"] == [] and body["tool_choice"] == "none"
        assert body["parallel_tool_calls"] is False
        assert body["truncation"] == "disabled"
        assert body["text"]["format"]["schema"] == semantic_evaluation_response_schema()
        assert "rationale_codes_hash" not in body["text"]["format"]["schema"]["properties"]
        assert "explanation_hash" not in body["text"]["format"]["schema"]["properties"]
        assert "expected_result" not in body["input"]
        assert "answer_label" not in body["input"]
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(response_bytes),
            request=request,
        )

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    assessment = evaluator.assess(evaluator_request)

    assert isinstance(assessment, SemanticAssessment)
    assert assessment.result.result is SemanticSupport(state)
    assert assessment.result.human_review_required is review
    assert (
        assessment.result.rationale_codes_hash
        == "sha256:"
        + hashlib.sha256(
            json.dumps([assessment.result.rationale_codes[0].value], separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert (
        assessment.result.explanation_hash
        == "sha256:" + hashlib.sha256(assessment.result.explanation.encode()).hexdigest()
    )
    assert (
        assessment.evaluator_input_hash
        == "sha256:"
        + hashlib.sha256(semantic_evaluation_input_bytes(evaluator_request)).hexdigest()
    )
    assert (
        assessment.provider_request_hash == "sha256:" + hashlib.sha256(seen[0].content).hexdigest()
    )
    assert assessment.raw_provider_request_bytes == seen[0].content
    assert API_KEY.encode() not in assessment.raw_provider_request_bytes
    assert b"Authorization" not in assessment.raw_provider_request_bytes
    assert (
        assessment.provider_response_hash == "sha256:" + hashlib.sha256(response_bytes).hexdigest()
    )
    assert assessment.raw_response_envelope_bytes == response_bytes
    assert assessment.structured_output_bytes == structured_output_bytes
    assert (
        assessment.structured_output_hash
        == "sha256:" + hashlib.sha256(structured_output_bytes).hexdigest()
    )
    reparsed = parse_semantic_evaluation_candidate(assessment.structured_output_bytes)
    assert reparsed.result is assessment.result.result
    assert tuple(code.value for code in reparsed.rationale_codes) == tuple(
        code.value for code in assessment.result.rationale_codes
    )
    assert assessment.provider_response_id == "resp_123"
    assert "Bounded advisory" not in repr(assessment)
    assert assessment.attempts == 1
    assert assessment.usage.total_tokens == 15
    assert not hasattr(evaluator, "evaluate")
    assert len(seen) == 1
    if state == "supported":
        with pytest.raises(ValueError, match="provider request hash drift"):
            replace(assessment, raw_provider_request_bytes=b"{}")
        substituted_request = b'{"input":"substituted"}'
        with pytest.raises(
            ValueError,
            match=r"evaluator input hash drift|provider request body invalid|configuration drift",
        ):
            replace(
                assessment,
                raw_provider_request_bytes=substituted_request,
                provider_request_hash="sha256:" + hashlib.sha256(substituted_request).hexdigest(),
            )
        with pytest.raises(ValueError, match="provider request hash drift"):
            replace(assessment, provider_request_hash="sha256:" + "f" * 64)
        with pytest.raises(ValueError, match="structured output hash drift"):
            replace(assessment, structured_output_bytes=b"{}")
        with pytest.raises(ValueError, match="response hash drift"):
            replace(assessment, raw_response_envelope_bytes=response_bytes + b" ")


def test_bare_absent_forged_admission_and_comparability_have_zero_transport_calls() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("transport must not be invoked")

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    forged_admission = _request()
    object.__setattr__(
        forged_admission.stage1_admission,
        "validation_input_hash",
        "sha256:" + "f" * 64,
    )
    absent_admission = _request()
    object.__setattr__(absent_admission, "stage1_admission", None)
    absent_comparability = _request()
    object.__setattr__(absent_comparability, "comparability", None)
    forged_comparability = _request()
    object.__setattr__(
        forged_comparability.comparability,
        "registry_hash",
        "sha256:" + "e" * 64,
    )
    invalid_nested = _request()
    object.__setattr__(invalid_nested.evidence, "normalized_excerpt", "substituted")

    for invalid in (
        _input(),
        forged_admission,
        absent_admission,
        absent_comparability,
        forged_comparability,
        invalid_nested,
    ):
        with pytest.raises(OpenAISemanticEvaluatorError) as raised:
            evaluator.assess(invalid)  # type: ignore[arg-type]
        assert raised.value.code is OpenAISemanticEvaluatorErrorCode.REQUEST_INTEGRITY
        assert raised.value.__cause__ is None
        assert calls == 0

    with pytest.raises((SemanticEvaluationContractError, ValueError)):
        _request(_input(relationship=CitationRelationship.CONTRADICTS))
    assert calls == 0

    current = _input(relationship=CitationRelationship.CONTRADICTS)
    ghost_evidence = replace(
        current.evidence,
        evidence_id="evidence:sha256:" + "0" * 64,
        source_record_id="record:ghost",
        source_version="version:ghost",
        snapshot_id="snapshot:ghost",
        content_hash="sha256:" + "d" * 64,
        locators=("ghost:0-1",),
    )
    ghost_evidence = replace(
        ghost_evidence,
        evidence_id=canonical_evidence_id(ghost_evidence),
    )
    ghost_support = replace(
        current.citation,
        citation_id="citation:sha256:" + "0" * 64,
        evidence_id=ghost_evidence.evidence_id,
        relationship=CitationRelationship.SUPPORTS,
        source_record_id=ghost_evidence.source_record_id,
        source_version=ghost_evidence.source_version,
        snapshot_id=ghost_evidence.snapshot_id,
        content_hash=ghost_evidence.content_hash,
        locator_ref=ghost_evidence.locators[0],
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
    )
    ghost_support = replace(
        ghost_support,
        citation_id=canonical_citation_id(ghost_support),
    )
    full_claim = replace(
        current.claim,
        citation_ids=(ghost_support.citation_id, current.citation.citation_id),
    )
    current_tuple = SemanticEvaluationInput(
        RUN_ID,
        full_claim,
        current.citation,
        current.evidence,
    )
    ghost_tuple = SemanticEvaluationInput(
        RUN_ID,
        full_claim,
        ghost_support,
        ghost_evidence,
    )
    valid_binding = (
        _request().stage1_admission.formal_citation_topology.ordered_citations[0].stage1_binding
    )
    with pytest.raises((SemanticEvaluationContractError, ValueError)):
        build_formal_claim_citation_topology(
            run_id=RUN_ID,
            claim=full_claim,
            ordered_semantic_inputs=(ghost_tuple, current_tuple),
            ordered_stage1_bindings=(valid_binding, valid_binding),
            current_citation_id=current.citation.citation_id,
        )
    assert calls == 0

    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(evaluator, "assess", lambda _value: None)
    assert calls == 0


@pytest.mark.parametrize("key", ["", "bad\nkey", "x" * 513])
def test_missing_or_invalid_key_fails_at_construction_without_io(key: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError

    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        OpenAIResponsesSemanticEvaluator(
            api_key=key,
            transport=httpx.MockTransport(handler),
        )
    assert raised.value.code is OpenAISemanticEvaluatorErrorCode.INVALID_CREDENTIAL
    assert raised.value.__cause__ is None
    assert API_KEY not in str(raised.value)
    assert calls == 0


def test_run_wide_topology_rejects_foreign_support_and_admits_current_support() -> None:
    calls = 0
    current = _input(relationship=CitationRelationship.CONTRADICTS)
    supporting = replace(current.citation, relationship=CitationRelationship.SUPPORTS)
    supporting = replace(supporting, citation_id=canonical_citation_id(supporting))
    full_claim = replace(
        current.claim,
        citation_ids=(supporting.citation_id, current.citation.citation_id),
    )
    current_tuple = SemanticEvaluationInput(
        RUN_ID,
        full_claim,
        current.citation,
        current.evidence,
    )
    supporting_tuple = SemanticEvaluationInput(
        RUN_ID,
        full_claim,
        supporting,
        current.evidence,
    )
    topology = build_formal_claim_citation_topology(
        run_id=RUN_ID,
        claim=full_claim,
        ordered_semantic_inputs=(supporting_tuple, current_tuple),
        ordered_stage1_bindings=(
            _stage1_binding(supporting_tuple),
            _stage1_binding(current_tuple),
        ),
        current_citation_id=current.citation.citation_id,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response(
            request,
            _response(candidate=_candidate("supported", review=True)),
        )

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    assessment = evaluator.assess(_request(current_tuple, topology=topology))
    assert assessment.result.result is SemanticSupport.SUPPORTED
    assert assessment.result.human_review_required is True
    assert calls == 1
    calls = 0

    foreign_run = "run:12345678-1234-4123-8123-123456789abd"
    foreign_evidence = replace(
        current.evidence,
        evidence_id="evidence:sha256:" + "0" * 64,
        authorized_run_id=foreign_run,
        source_record_id="record:foreign-support",
        snapshot_id="snapshot:foreign-support",
    )
    foreign_evidence = replace(
        foreign_evidence,
        evidence_id=canonical_evidence_id(foreign_evidence),
    )
    foreign_support = replace(
        supporting,
        citation_id="citation:sha256:" + "0" * 64,
        evidence_id=foreign_evidence.evidence_id,
        source_record_id=foreign_evidence.source_record_id,
        source_version=foreign_evidence.source_version,
        snapshot_id=foreign_evidence.snapshot_id,
        content_hash=foreign_evidence.content_hash,
        locator_ref=foreign_evidence.locators[0],
    )
    foreign_support = replace(
        foreign_support,
        citation_id=canonical_citation_id(foreign_support),
    )
    foreign_claim = replace(
        current.claim,
        citation_ids=(foreign_support.citation_id, current.citation.citation_id),
    )
    foreign_tuple = SemanticEvaluationInput(
        foreign_run,
        foreign_claim,
        foreign_support,
        foreign_evidence,
    )
    current_with_foreign_claim = SemanticEvaluationInput(
        RUN_ID,
        foreign_claim,
        current.citation,
        current.evidence,
    )
    with pytest.raises(SemanticEvaluationContractError, match="run_drift"):
        build_formal_claim_citation_topology(
            run_id=RUN_ID,
            claim=foreign_claim,
            ordered_semantic_inputs=(foreign_tuple, current_with_foreign_claim),
            ordered_stage1_bindings=(
                _stage1_binding(foreign_tuple),
                _stage1_binding(current_with_foreign_claim),
            ),
            current_citation_id=current.citation.citation_id,
        )
    assert calls == 0


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, OpenAISemanticEvaluatorErrorCode.AUTHENTICATION),
        (403, OpenAISemanticEvaluatorErrorCode.AUTHENTICATION),
        (400, OpenAISemanticEvaluatorErrorCode.PROVIDER_REJECTED),
        (429, OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE),
        (500, OpenAISemanticEvaluatorErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_shared_transport_errors_are_redacted(status: int, expected: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(b'{"secret":"provider-body"}'),
            request=request,
        )

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        evaluator.assess(_request())
    assert raised.value.code is expected
    assert raised.value.__cause__ is None
    assert API_KEY not in str(raised.value)
    assert "provider-body" not in str(raised.value)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda body: {**body, "model": "gpt-5.6-sol"}, "response_model_mismatch"),
        (lambda body: {**body, "store": True}, "response_invalid"),
        (lambda body: {**body, "tools": [{"type": "web_search"}]}, "response_invalid"),
        (lambda body: {**body, "status": "incomplete"}, "response_incomplete"),
        (lambda body: {**body, "id": "resp_" + "x" * 508}, "response_invalid"),
        (
            lambda body: {
                **body,
                "usage": {**body["usage"], "total_tokens": 16},
            },
            "response_invalid",
        ),
        (
            lambda body: {
                **body,
                "usage": {
                    **body["usage"],
                    "input_tokens_details": {"cached_tokens": 11},
                },
            },
            "response_invalid",
        ),
        (
            lambda body: {
                **body,
                "usage": {
                    **body["usage"],
                    "output_tokens_details": {"reasoning_tokens": 6},
                },
            },
            "response_invalid",
        ),
        (
            lambda body: {
                **body,
                "output": [
                    {
                        "id": "msg_1",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ],
            },
            "response_refused",
        ),
    ],
)
def test_response_envelope_and_configuration_drift_fail_closed(mutator: Any, expected: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, mutator(_response()))

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError, match=expected) as raised:
        evaluator.assess(_request())
    assert raised.value.__cause__ is None


def test_human_review_gate_drift_is_rejected_after_strict_parse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, _response(candidate=_candidate("uncertain", review=False)))

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        evaluator.assess(_request())
    assert raised.value.code is OpenAISemanticEvaluatorErrorCode.CANDIDATE_INVALID
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("semantic_input", "candidate"),
    [
        (
            _input(),
            _candidate(
                "supported",
                review=True,
                rationale_code=SemanticRationaleCode.DIRECT_CONTRADICTION.value,
            ),
        ),
    ],
)
def test_direct_contradiction_relationship_and_rationale_mismatch_are_rejected(
    semantic_input: SemanticEvaluationInput,
    candidate: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(request, _response(candidate=candidate))

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        evaluator.assess(_request(semantic_input))
    assert raised.value.code is OpenAISemanticEvaluatorErrorCode.CANDIDATE_INVALID
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "content",
    [b"\xef\xbb\xbf{}", b'{"id":"resp_1","id":"resp_2"}'],
)
def test_bom_and_duplicate_provider_responses_fail_closed(content: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(content),
            request=request,
        )

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        evaluator.assess(_request())
    assert raised.value.code in {
        OpenAISemanticEvaluatorErrorCode.RESPONSE_INVALID,
        OpenAISemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE,
    }
    assert raised.value.__cause__ is None


def test_oversize_provider_response_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=httpx.ByteStream(b"x" * (MAX_EVALUATION_PROVIDER_RESPONSE_BYTES + 1)),
            request=request,
        )

    evaluator = OpenAIResponsesSemanticEvaluator(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(OpenAISemanticEvaluatorError) as raised:
        evaluator.assess(_request())
    assert raised.value.code is OpenAISemanticEvaluatorErrorCode.RESPONSE_TOO_LARGE
    assert raised.value.__cause__ is None
