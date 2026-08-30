from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from evaluation import stage2_calibration as calibration

from medevidence.domain import CoverageStatus, ExecutionStatus, ResultStatus, SourceType
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
    MAX_EVALUATION_INPUT_TOKENS,
    MAX_EVALUATION_OUTPUT_TOKENS,
    MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
    MAX_EVALUATION_TOTAL_TOKENS,
    SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    SEMANTIC_EVALUATION_METHOD,
    SEMANTIC_EVALUATION_MODEL,
    SEMANTIC_EVALUATION_PROMPT_BYTES,
    SEMANTIC_EVALUATION_PROMPT_HASH,
    SEMANTIC_EVALUATION_RUBRIC_HASH,
    SEMANTIC_EVALUATION_SCHEMA_HASH,
    SEMANTIC_EVALUATION_VERSION,
    SemanticEvaluationContractError,
    SemanticEvaluationRequest,
    build_canonical_citation_stage1_binding,
    build_canonical_stage1_admission,
    build_empty_comparability_metadata,
    build_formal_claim_citation_topology,
    build_semantic_evaluation_request,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
    semantic_evaluation_response_schema,
    validate_semantic_evaluation_response_id,
)

RUN_ID = "run:12345678-1234-4123-8123-123456789abc"
SCOPE_ID = "scope:sha256:" + "a" * 64
PACKET = "sha256:" + "b" * 64
DATASET = "sha256:" + "c" * 64


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _request(run_id: str = RUN_ID) -> SemanticEvaluationRequest:
    evidence = EvidenceInput(
        "evidence:sha256:" + "0" * 64,
        run_id,
        SourceType.PUBMED,
        "record:synthetic",
        "version:synthetic",
        "snapshot:synthetic",
        _digest("synthetic evidence"),
        ("abstract:0-20",),
        frozenset({ClaimClass.DESCRIPTIVE}),
        frozenset({InferenceUse.DESCRIPTIVE}),
        "Synthetic nonmedical evidence reports the bounded observation.",
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
        CitationRelationship.SUPPORTS,
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
    semantic_input = SemanticEvaluationInput(run_id, claim, citation, evidence)
    comparability = build_empty_comparability_metadata(run_id=run_id)
    citation_binding = build_canonical_citation_stage1_binding(
        stage1_passed=True,
        validation_receipt_id="validation-receipt:sha256:" + "2" * 64,
        validation_receipt_content_hash="sha256:" + "3" * 64,
        registry_binding_hash="sha256:" + "5" * 64,
        source_task_id=f"source-task:{run_id.removeprefix('run:')}:pubmed",
        task_binding_hash="sha256:" + "6" * 64,
        source_outcome_id="source-outcome:pubmed",
        source_outcome_binding_hash="sha256:" + "7" * 64,
        stage1_result_id="validation-stage1-result:sha256:" + "8" * 64,
        stage1_claim_result_id="validation-claim-result:sha256:" + "9" * 64,
    )
    topology = build_formal_claim_citation_topology(
        run_id=run_id,
        claim=claim,
        ordered_semantic_inputs=(semantic_input,),
        ordered_stage1_bindings=(citation_binding,),
        current_citation_id=citation.citation_id,
    )
    admission = build_canonical_stage1_admission(
        stage1_passed=True,
        semantic_input=semantic_input,
        formal_citation_topology=topology,
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
        stage1_result_id="validation-stage1-result:sha256:" + "8" * 64,
        stage1_claim_result_id="validation-claim-result:sha256:" + "9" * 64,
        report_content_hash="sha256:" + "a" * 64,
    )
    return build_semantic_evaluation_request(
        admission,
        comparability=comparability,
    )


def _contradiction_request() -> SemanticEvaluationRequest:
    base = _request()
    support = base.citation
    contradiction = replace(support, relationship=CitationRelationship.CONTRADICTS)
    contradiction = replace(contradiction, citation_id=canonical_citation_id(contradiction))
    claim = replace(base.claim, citation_ids=(support.citation_id, contradiction.citation_id))
    support_input = SemanticEvaluationInput(RUN_ID, claim, support, base.evidence)
    contradiction_input = SemanticEvaluationInput(RUN_ID, claim, contradiction, base.evidence)
    binding = base.stage1_admission.formal_citation_topology.ordered_citations[0].stage1_binding
    topology = build_formal_claim_citation_topology(
        run_id=RUN_ID,
        claim=claim,
        ordered_semantic_inputs=(support_input, contradiction_input),
        ordered_stage1_bindings=(binding, binding),
        current_citation_id=contradiction.citation_id,
    )
    admitted = base.stage1_admission
    admission = build_canonical_stage1_admission(
        stage1_passed=True,
        semantic_input=contradiction_input,
        formal_citation_topology=topology,
        comparability=base.comparability,
        scope_id=admitted.scope_id,
        report_id=admitted.report_id,
        validation_receipt_id=admitted.validation_receipt_id,
        validation_receipt_content_hash=admitted.validation_receipt_content_hash,
        validation_input_hash=admitted.validation_input_hash,
        registry_binding_hash=admitted.registry_binding_hash,
        task_binding_hash=admitted.task_binding_hash,
        source_outcome_id=admitted.source_outcome_id,
        source_outcome_binding_hash=admitted.source_outcome_binding_hash,
        stage1_result_id=admitted.stage1_result_id,
        stage1_claim_result_id=admitted.stage1_claim_result_id,
        report_content_hash=admitted.report_content_hash,
    )
    return build_semantic_evaluation_request(admission, comparability=base.comparability)


def _candidate(state: SemanticSupport) -> str:
    code = {
        SemanticSupport.SUPPORTED: "direct_support",
        SemanticSupport.UNCERTAIN: "partial_or_ambiguous_support",
        SemanticSupport.UNSUPPORTED: "no_support",
    }[state]
    return json.dumps(
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": state.value,
            "rationale_codes": [code],
            "explanation": f"Synthetic advisory result: {state.value}.",
            "human_review_required": state is SemanticSupport.UNCERTAIN,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _response(state: SemanticSupport) -> bytes:
    document = {
        "id": f"resp_{state.value}",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": SEMANTIC_EVALUATION_MODEL,
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
        "output": [
            {"id": "rs_1", "type": "reasoning", "summary": [], "status": "completed"},
            {
                "id": "msg_1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": _candidate(state),
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
    }
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


def _assessment(
    state: SemanticSupport, request: SemanticEvaluationRequest | None = None
) -> calibration.GatewayObservation:
    selected_request = request or _request()
    response = _response(state)
    structured = _candidate(state).encode()
    provider_request = calibration.canonical_provider_request_bytes(selected_request)
    return calibration.GatewayObservation(
        evaluator_input_hash=_digest(semantic_evaluation_input_bytes(selected_request)),
        provider_request_hash=_digest(provider_request),
        raw_provider_request_bytes=provider_request,
        provider_response_id=f"resp_{state.value}",
        provider_response_hash=_digest(response),
        raw_response_envelope_bytes=response,
        structured_output_bytes=structured,
        structured_output_hash=_digest(structured),
        attempts=1,
        usage=calibration.SemanticEvaluationUsage(
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cached_input_tokens=0,
            reasoning_output_tokens=2,
        ),
        started_at_utc=datetime(2026, 8, 30, 1, tzinfo=UTC),
        completed_at_utc=datetime(2026, 8, 30, 1, 0, 1, tzinfo=UTC),
    )


def _provenance() -> tuple[calibration.ProvenanceRef, ...]:
    return (
        calibration.ProvenanceRef(
            calibration.ProvenanceKind.CASE_SOURCE,
            "synthetic-source",
            DATASET,
            "synthetic://source",
        ),
        calibration.ProvenanceRef(
            calibration.ProvenanceKind.HUMAN_RESOLUTION_PACKET,
            "synthetic-human-packet",
            PACKET,
            "synthetic://human-packet",
        ),
    )


def _case(
    case_id: str,
    predicted: SemanticSupport,
    expected: SemanticSupport,
    *,
    split: calibration.CalibrationSplit = calibration.CalibrationSplit.SYNTHETIC,
    request: SemanticEvaluationRequest | None = None,
) -> calibration.CalibrationCase:
    selected_request = request or _request()
    return calibration.make_calibration_case(
        case_id=case_id,
        category="semantic-support",
        split=split,
        request=selected_request,
        assessment=_assessment(predicted, selected_request),
        human_resolution=expected,
        human_expected_state=expected,
        human_authority="synthetic human adjudicator",
        human_notes="Synthetic nonmedical calibration note.",
        human_resolution_packet_identity=PACKET,
        provenance=_provenance(),
    )


def _configuration() -> calibration.CalibrationConfiguration:
    return calibration.calibration_configuration(
        code_revision="1" * 40,
        implementation_manifest_hash=_digest("implementation manifest"),
        calibration_dataset_identity=DATASET,
        human_resolution_packet_identity=PACKET,
    )


def _artifact() -> dict[str, object]:
    return calibration.build_calibration_artifact(
        calibration_set_name="synthetic-framework",
        configuration=_configuration(),
        cases=[
            _case("supported", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
            _case("uncertain", SemanticSupport.UNCERTAIN, SemanticSupport.UNCERTAIN),
            _case("disagree", SemanticSupport.SUPPORTED, SemanticSupport.UNSUPPORTED),
        ],
        operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _rebind(artifact: dict[str, object]) -> None:
    artifact["calibration_set"]["identity"] = calibration._sha256(
        calibration._canonical_bytes(artifact["cases"])
    )
    semantic = dict(artifact)
    semantic.pop("artifact_semantic_id")
    semantic.pop("operational_timestamp_utc")
    artifact["artifact_semantic_id"] = calibration._sha256(calibration._canonical_bytes(semantic))


def _canonical_hash(value: object) -> str:
    return _digest(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _foreign_support_request_bytes() -> bytes:
    current = json.loads(semantic_evaluation_request_bytes(_contradiction_request()))
    foreign = json.loads(
        semantic_evaluation_request_bytes(_request("run:12345678-1234-4123-8123-123456789abd"))
    )
    admission = current["stage1_admission"]
    topology = admission["formal_citation_topology"]
    foreign_entry = foreign["stage1_admission"]["formal_citation_topology"]["ordered_citations"][0]
    topology["ordered_citations"][0] = foreign_entry
    ordered = [
        [entry["citation_id"], entry["relationship"]] for entry in topology["ordered_citations"]
    ]
    topology["ordered_citations_hash"] = _canonical_hash(ordered)
    topology_common = {
        "run_id": topology["run_id"],
        "claim_id": topology["claim_id"],
        "ordered_citations": ordered,
        "ordered_entry_hashes": [entry["entry_hash"] for entry in topology["ordered_citations"]],
        "ordered_citations_hash": topology["ordered_citations_hash"],
        "current_citation_id": topology["current_citation_id"],
        "current_relationship": topology["current_relationship"],
        "supporting_citation_count": topology["supporting_citation_count"],
    }
    topology["topology_hash"] = _canonical_hash(topology_common)
    admission_common = dict(admission)
    admission_common.pop("admission_hash")
    admission["admission_hash"] = _canonical_hash(admission_common)
    semantic = admission["semantic_input"]
    request_common = {
        "schema_version": current["schema_version"],
        "run_id": admission["run_id"],
        "scope_id": admission["scope_id"],
        "input_digest": current["input_digest"],
        "stage1_admission_hash": admission["admission_hash"],
        "source": semantic["claim"]["source"],
        "source_classification": current["source_classification"],
        "claim": semantic["claim"],
        "citation": semantic["citation"],
        "evidence": semantic["evidence"],
        "comparability": current["comparability"],
    }
    current["request_content_hash"] = _canonical_hash(request_common)
    return json.dumps(current, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def test_all_current_contradiction_with_support_is_valid_calibration_input() -> None:
    request = _contradiction_request()
    topology = request.stage1_admission.formal_citation_topology
    assert topology.run_id == RUN_ID
    assert topology.current_relationship is CitationRelationship.CONTRADICTS
    assert topology.supporting_citation_count == 1
    case = _case(
        "current-contradiction",
        SemanticSupport.UNCERTAIN,
        SemanticSupport.UNCERTAIN,
        request=request,
    )
    artifact = calibration.build_calibration_artifact(
        calibration_set_name="all-current-contradiction",
        configuration=_configuration(),
        cases=[case],
        operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
    )
    assert artifact["metrics"]["agreement"]["agreement_count"] == 1


def test_rehashed_foreign_support_request_and_artifact_reject_before_metrics() -> None:
    foreign_run = "run:12345678-1234-4123-8123-123456789abd"
    foreign_request = _request(foreign_run)
    foreign_bytes = semantic_evaluation_request_bytes(foreign_request)
    assert calibration.validate_semantic_request_bytes(foreign_bytes).run_id == foreign_run
    mixed = _foreign_support_request_bytes()
    with pytest.raises(calibration.Stage2CalibrationError, match="request parser"):
        calibration.validate_semantic_request_bytes(mixed)
    request = _contradiction_request()
    case = _case(
        "foreign-support",
        SemanticSupport.UNCERTAIN,
        SemanticSupport.UNCERTAIN,
        request=request,
    )
    artifact = calibration.build_calibration_artifact(
        calibration_set_name="foreign-support-control",
        configuration=_configuration(),
        cases=[case],
        operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
    )
    changed = copy.deepcopy(artifact)
    changed_case = changed["cases"][0]
    changed_case["semantic_request_bytes_hex"] = mixed.hex()
    changed_case["semantic_request_bytes"] = len(mixed)
    changed_case["semantic_request_hash"] = _digest(mixed)
    changed["metrics"] = {"must_not_be_reached": True}
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="request parser"):
        calibration.validate_calibration_artifact(changed)


def test_configuration_binds_current_authority_code_and_calibration_inputs() -> None:
    config = _configuration()
    assert (config.evaluator_method, config.evaluator_version) == (
        SEMANTIC_EVALUATION_METHOD,
        SEMANTIC_EVALUATION_VERSION,
    )
    assert (
        config.prompt_hash,
        config.rubric_hash,
        config.schema_hash,
        config.configuration_hash,
    ) == (
        SEMANTIC_EVALUATION_PROMPT_HASH,
        SEMANTIC_EVALUATION_RUBRIC_HASH,
        SEMANTIC_EVALUATION_SCHEMA_HASH,
        SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    )
    with pytest.raises(calibration.Stage2CalibrationError, match="authority drift"):
        calibration.build_calibration_artifact(
            calibration_set_name="drift",
            configuration=replace(config, evaluator_version="foreign"),
            cases=[_case("case", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)],
            operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
        )
    with pytest.raises(calibration.Stage2CalibrationError, match="40-hex"):
        calibration.calibration_configuration(
            code_revision="not-a-commit",
            implementation_manifest_hash=_digest("manifest"),
            calibration_dataset_identity=_digest("dataset"),
            human_resolution_packet_identity=PACKET,
        )
    with pytest.raises(calibration.Stage2CalibrationError, match="dataset provenance"):
        calibration.build_calibration_artifact(
            calibration_set_name="dataset-drift",
            configuration=replace(config, calibration_dataset_identity=_digest("foreign dataset")),
            cases=[_case("case", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)],
            operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_actual_gateway_observation_is_preserved_without_hash_substitution() -> None:
    assessment = _assessment(SemanticSupport.SUPPORTED)
    case = _case("actual", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    assert case.evaluator_input_hash == assessment.evaluator_input_hash
    assert case.provider_request_hash == assessment.provider_request_hash
    assert case.provider_request_hash != case.evaluator_input_hash
    assert bytes.fromhex(case.raw_provider_request_hex) == assessment.raw_provider_request_bytes
    assert bytes.fromhex(case.raw_response_envelope_hex) == assessment.raw_response_envelope_bytes
    assert bytes.fromhex(case.structured_output_hex) == assessment.structured_output_bytes
    assert case.provider_response_id == "resp_supported"
    assert case.usage.reasoning_output_tokens == 2


def test_shared_response_byte_id_and_usage_exact_maxima() -> None:
    exact = b"x" * MAX_EVALUATION_PROVIDER_RESPONSE_BYTES
    assert (
        calibration._bytes_from_hex(
            exact.hex(),
            len(exact),
            "response envelope",
            maximum=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        )
        == exact
    )
    response_id = "resp_" + "a" * 507
    assert len(response_id) == 512
    assert validate_semantic_evaluation_response_id(response_id) == response_id
    usage = calibration.SemanticEvaluationUsage(
        input_tokens=MAX_EVALUATION_INPUT_TOKENS,
        output_tokens=MAX_EVALUATION_OUTPUT_TOKENS,
        total_tokens=MAX_EVALUATION_TOTAL_TOKENS,
        cached_input_tokens=MAX_EVALUATION_INPUT_TOKENS,
        reasoning_output_tokens=MAX_EVALUATION_OUTPUT_TOKENS,
    )
    assert usage.total_tokens == 69_632


def test_review_oversized_response_and_unbounded_id_repros_fail_before_parse() -> None:
    oversized = b"x" * 143_367
    with pytest.raises(calibration.Stage2CalibrationError, match="shared byte bound"):
        calibration._bytes_from_hex(
            oversized.hex(),
            len(oversized),
            "response envelope",
            maximum=MAX_EVALUATION_PROVIDER_RESPONSE_BYTES,
        )
    response_id = "resp_" + "a" * 140_000
    assert len(response_id) == 140_005
    with pytest.raises(SemanticEvaluationContractError, match="response_id_invalid"):
        validate_semantic_evaluation_response_id(response_id)


@pytest.mark.parametrize(
    ("cached", "reasoning", "total"),
    [
        (11, 2, 15),
        (0, 6, 15),
        (0, 2, 14),
    ],
)
def test_shared_usage_rejects_cached_reasoning_and_total_repros(
    cached: int, reasoning: int, total: int
) -> None:
    artifact = _artifact()
    changed = copy.deepcopy(artifact)
    case = changed["cases"][0]
    case["usage"] = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": total,
        "cached_input_tokens": cached,
        "reasoning_output_tokens": reasoning,
    }
    envelope = json.loads(bytes.fromhex(case["raw_response_envelope_hex"]))
    envelope["usage"] = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": total,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens_details": {"reasoning_tokens": reasoning},
    }
    raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    case["raw_response_envelope_hex"] = raw.hex()
    case["raw_response_envelope_bytes"] = len(raw)
    case["provider_response_hash"] = _digest(raw)
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="shared semantic authority"):
        calibration.validate_calibration_artifact(changed)


def test_provider_request_bytes_hash_and_exact_profile_fail_closed() -> None:
    artifact = _artifact()
    mutations = [
        ("model", "foreign-model"),
        ("reasoning", {"effort": "high"}),
        ("store", True),
        ("background", True),
        ("tools", [{"type": "function"}]),
        ("instructions", "foreign instructions"),
        ("input", "foreign input"),
        ("text", {"format": {"type": "json_object"}}),
    ]
    for field, value in mutations:
        changed = copy.deepcopy(artifact)
        case = changed["cases"][0]
        provider = json.loads(bytes.fromhex(case["raw_provider_request_hex"]))
        provider[field] = value
        raw = json.dumps(provider, separators=(",", ":"), sort_keys=True).encode()
        case["raw_provider_request_hex"] = raw.hex()
        case["raw_provider_request_bytes"] = len(raw)
        case["provider_request_hash"] = _digest(raw)
        _rebind(changed)
        with pytest.raises(calibration.Stage2CalibrationError, match="canonical evaluator profile"):
            calibration.validate_calibration_artifact(changed)
    changed = copy.deepcopy(artifact)
    changed["cases"][0]["provider_request_hash"] = _digest("substituted")
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="provider request hash"):
        calibration.validate_calibration_artifact(changed)


def test_full_request_round_trips_through_public_parser() -> None:
    raw = semantic_evaluation_request_bytes(_request())
    rebuilt = calibration.validate_semantic_request_bytes(raw)
    assert semantic_evaluation_request_bytes(rebuilt) == raw
    case = _case("roundtrip", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    assert bytes.fromhex(case.semantic_request_bytes_hex) == raw
    assert case.semantic_request_hash == _digest(raw)


@pytest.mark.parametrize(
    "key",
    [
        "retrieval_score",
        "retrievalScores",
        "score-of-retrieval",
        "generator_reasoning",
        "reasoningFromGenerator",
        "adjudicated_support_state",
        "ExpectedAnswer",
        "qReLs",
        "HOLDOUT 20",
    ],
)
def test_request_parser_rejects_all_answer_side_and_open_shape_repros(key: str) -> None:
    document = json.loads(semantic_evaluation_request_bytes(_request()))
    document["stage1_admission"]["semantic_input"]["claim"][key] = "forbidden"
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(calibration.Stage2CalibrationError, match="request parser"):
        calibration.validate_semantic_request_bytes(raw)


def test_mutated_claim_fails_after_all_outer_hashes_are_rebound() -> None:
    artifact = _artifact()
    changed = copy.deepcopy(artifact)
    case = changed["cases"][0]
    request = json.loads(bytes.fromhex(case["semantic_request_bytes_hex"]))
    request["stage1_admission"]["semantic_input"]["claim"]["statement"] = (
        "Fabricated noncanonical claim."
    )
    raw = json.dumps(request, separators=(",", ":"), sort_keys=True).encode()
    case["semantic_request_bytes_hex"] = raw.hex()
    case["semantic_request_bytes"] = len(raw)
    case["semantic_request_hash"] = _digest(raw)
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="request parser"):
        calibration.validate_calibration_artifact(changed)


def test_response_envelope_and_inner_output_bindings_fail_closed() -> None:
    artifact = _artifact()
    changed = copy.deepcopy(artifact)
    changed["cases"][0]["parsed_state"] = "unsupported"
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="public semantic parser"):
        calibration.validate_calibration_artifact(changed)
    changed = copy.deepcopy(artifact)
    case = changed["cases"][0]
    envelope = json.loads(bytes.fromhex(case["raw_response_envelope_hex"]))
    envelope["id"] = "resp_foreign"
    raw = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    case["raw_response_envelope_hex"] = raw.hex()
    case["raw_response_envelope_bytes"] = len(raw)
    case["provider_response_hash"] = _digest(raw)
    _rebind(changed)
    with pytest.raises(calibration.Stage2CalibrationError, match="response identity"):
        calibration.validate_calibration_artifact(changed)


def test_response_envelope_rejects_tool_unknown_refusal_multiple_and_config_repros() -> None:
    base = json.loads(_response(SemanticSupport.SUPPORTED))
    mutations: list[dict[str, object]] = []
    value = copy.deepcopy(base)
    value["web_search_call"] = {}
    mutations.append(value)
    value = copy.deepcopy(base)
    value["output"].append({"id": "call_1", "type": "function_call"})
    mutations.append(value)
    value = copy.deepcopy(base)
    value["output"][1]["unknown"] = True
    mutations.append(value)
    value = copy.deepcopy(base)
    value["output"][1]["content"] = [{"type": "refusal", "refusal": "no"}]
    mutations.append(value)
    value = copy.deepcopy(base)
    value["output"][1]["content"].append(copy.deepcopy(value["output"][1]["content"][0]))
    mutations.append(value)
    value = copy.deepcopy(base)
    value["output"][0]["summary"] = [{"text": "hidden"}]
    mutations.append(value)
    value = copy.deepcopy(base)
    value["reasoning"] = {"effort": "high", "summary": None}
    mutations.append(value)
    for document in mutations:
        raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        with pytest.raises(calibration.Stage2CalibrationError):
            calibration._extract_output_text(calibration._response_document(raw))


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": "uncertain",
            "rationale_codes": ["partial_or_ambiguous_support"],
            "explanation": "Uncertain requires review.",
            "human_review_required": False,
        },
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": "supported",
            "rationale_codes": ["no_support"],
            "explanation": "Invalid rationale matrix.",
            "human_review_required": False,
        },
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": "supported",
            "rationale_codes": ["partial_or_ambiguous_support"],
            "explanation": "Supported matrix drift.",
            "human_review_required": False,
        },
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": "uncertain",
            "rationale_codes": ["direct_support"],
            "explanation": "Uncertain matrix drift.",
            "human_review_required": True,
        },
        {
            "schema_version": "m3.semantic-evaluation.result.v1",
            "result": "unsupported",
            "rationale_codes": ["direct_support"],
            "explanation": "Unsupported matrix drift.",
            "human_review_required": False,
        },
    ],
)
def test_candidate_must_pass_canonical_result_authority(payload: dict[str, object]) -> None:
    structured = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    envelope = json.loads(_response(SemanticSupport.SUPPORTED))
    envelope["output"][1]["content"][0]["text"] = structured.decode()
    raw_envelope = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    base = _assessment(SemanticSupport.SUPPORTED)
    observation = replace(
        base,
        provider_response_hash=_digest(raw_envelope),
        raw_response_envelope_bytes=raw_envelope,
        structured_output_bytes=structured,
        structured_output_hash=_digest(structured),
    )
    with pytest.raises(calibration.Stage2CalibrationError, match="canonical semantic result"):
        calibration.make_calibration_case(
            case_id="invalid-candidate",
            category="semantic-support",
            split=calibration.CalibrationSplit.SYNTHETIC,
            request=_request(),
            assessment=observation,
            human_resolution=SemanticSupport.UNSUPPORTED,
            human_expected_state=SemanticSupport.UNSUPPORTED,
            human_authority="synthetic authority",
            human_notes="Synthetic invalid-candidate control.",
            human_resolution_packet_identity=PACKET,
            provenance=_provenance(),
        )


def test_every_case_requires_exact_human_resolution_authority_notes_and_packet() -> None:
    case = _case("human", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    foreign_packet = _digest("foreign")
    mutations = [
        (replace(case, human_resolution=SemanticSupport.UNSUPPORTED), "expected state"),
        (replace(case, human_authority=""), "authority"),
        (replace(case, human_notes=""), "notes"),
        (
            replace(
                case,
                human_resolution_packet_identity=foreign_packet,
                human_resolution_hash=calibration._human_hash(
                    case.case_id,
                    case.human_resolution,
                    case.human_expected_state,
                    case.human_authority,
                    case.human_notes,
                    foreign_packet,
                ),
            ),
            "packet provenance",
        ),
    ]
    for changed, reason in mutations:
        with pytest.raises(calibration.Stage2CalibrationError, match=reason):
            calibration.build_calibration_artifact(
                calibration_set_name="human-drift",
                configuration=_configuration(),
                cases=[changed],
                operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
            )
    with pytest.raises(calibration.Stage2CalibrationError, match="human resolution"):
        calibration.make_calibration_case(
            case_id="unresolved",
            category="semantic-support",
            split=calibration.CalibrationSplit.DEVELOPMENT,
            request=_request(),
            assessment=_assessment(SemanticSupport.SUPPORTED),
            human_resolution=None,  # type: ignore[arg-type]
            human_expected_state=SemanticSupport.SUPPORTED,
            human_authority="authority",
            human_notes="notes",
            human_resolution_packet_identity=PACKET,
            provenance=_provenance(),
        )


def test_only_adjudicated_development_or_synthetic_splits_are_admitted() -> None:
    synthetic = _case("synthetic", SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED)
    development = _case(
        "development",
        SemanticSupport.SUPPORTED,
        SemanticSupport.SUPPORTED,
        split=calibration.CalibrationSplit.DEVELOPMENT,
    )
    assert synthetic.synthetic_only is True and development.synthetic_only is False
    with pytest.raises(calibration.Stage2CalibrationError, match="split"):
        calibration.build_calibration_artifact(
            calibration_set_name="bad-split",
            configuration=_configuration(),
            cases=[replace(synthetic, split="holdout")],  # type: ignore[arg-type]
            operational_timestamp_utc=datetime(2026, 8, 30, tzinfo=UTC),
        )


def test_metrics_use_reparsed_inner_output_and_exact_human_expected_state() -> None:
    metrics = _artifact()["metrics"]
    assert metrics["agreement"] == {
        "agreement_count": 2,
        "denominator": 3,
        "agreement_rate": 2 / 3,
        "unresolved_or_excluded": 0,
    }
    assert metrics["confusion_matrix"]["unsupported"]["supported"] == 1
    assert metrics["error_analysis"] == {
        "disagreement_pairs": {"unsupported->supported": 1},
        "disagreement_case_ids": ["disagree"],
    }


def test_framework_status_is_honest() -> None:
    assert calibration.framework_status() == {
        "status": "AWAITING_APPROVED_CALIBRATION_PACKET",
        "approved_calibration_packet_present": False,
        "calibration_claimed": False,
        "holdout_accessed": False,
    }


def test_atomic_append_only_writer_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "run"
    result = calibration.write_calibration_artifact(_artifact(), output)
    assert result["artifact"]["sha256"] == _digest(
        (output / "stage2-calibration.json").read_bytes()
    )
    with pytest.raises(calibration.Stage2CalibrationError, match="overwrite"):
        calibration.write_calibration_artifact(_artifact(), output)
    failed = tmp_path / "failed"

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(calibration.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="synthetic fsync failure"):
        calibration.write_calibration_artifact(_artifact(), failed)
    assert not failed.exists() and not (tmp_path / ".failed.pending").exists()
