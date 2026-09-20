from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import Counter
from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import evaluation.stage2_deepseek_calibration as calibration_module
import pytest
from evaluation.stage2_deepseek_calibration import (
    CASE_COUNT,
    HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_BYTES,
    HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_HASH,
    HISTORICAL_ATTEMPT005_CASE1_REQUEST_BYTES,
    HISTORICAL_ATTEMPT005_CASE1_REQUEST_HASH,
    HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_BYTES,
    HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_HASH,
    HISTORICAL_ATTEMPT005_PROJECTION_HASH,
    HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT005_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_BYTES,
    HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_HASH,
    HISTORICAL_ATTEMPT006_CLASSIFICATION,
    HISTORICAL_ATTEMPT006_CONFIGURATION_BINDING_HASH,
    HISTORICAL_ATTEMPT006_PROJECTION_HASH,
    HISTORICAL_ATTEMPT006_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT006_RUN_CONFIGURATION_FILE_HASH,
    HISTORICAL_ATTEMPT006_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT006_SUCCESS_CASE_FILE_HASHES,
    HISTORICAL_ATTEMPT007_CONFIGURATION_FILE_HASH,
    HISTORICAL_ATTEMPT007_MANIFEST_HASH,
    HISTORICAL_ATTEMPT007_PROJECTION_HASH,
    HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT007_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT007_SUCCESS_RAW_FACTS,
    HISTORICAL_ATTEMPT008_CONFIGURATION_FILE_HASH,
    HISTORICAL_ATTEMPT008_MANIFEST_HASH,
    HISTORICAL_ATTEMPT008_PROJECTION_HASH,
    HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT008_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT008_SUCCESS_RAW_FACTS,
    HISTORICAL_ATTEMPT009_CASE_FILE_HASHES,
    HISTORICAL_ATTEMPT009_CONFIGURATION_FILE_HASH,
    HISTORICAL_ATTEMPT009_MANIFEST_HASH,
    HISTORICAL_ATTEMPT009_PROJECTION_HASH,
    HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT009_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT009_SUCCESS_RAW_FACTS,
    HISTORICAL_ATTEMPT010_CASE_FILE_HASHES,
    HISTORICAL_ATTEMPT010_CONFIGURATION_FILE_HASH,
    HISTORICAL_ATTEMPT010_MANIFEST_HASH,
    HISTORICAL_ATTEMPT010_PROJECTION_HASH,
    HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
    HISTORICAL_ATTEMPT010_STATUS_BINDING_HASH,
    HISTORICAL_ATTEMPT010_SUCCESS_RAW_FACTS,
    OWNER_RESOLUTION_IDENTITY,
    CalibrationObservation,
    DeepSeekCalibrationError,
    FrozenCalibrationCase,
    acceptance_metrics,
    begin_pending_calibration_run,
    build_calibration_artifact,
    calibration_configuration,
    classify_historical_attempt006_application_binding,
    historical_attempt004_calibration_configuration,
    historical_attempt005_calibration_configuration,
    historical_attempt005_provider_event_projection,
    historical_attempt006_calibration_configuration,
    historical_attempt006_failure_classification,
    historical_attempt007_calibration_configuration,
    historical_attempt007_expected_run_status,
    historical_attempt007_provider_event_projection,
    historical_attempt008_calibration_configuration,
    historical_attempt009_calibration_configuration,
    historical_attempt010_calibration_configuration,
    historical_v1_calibration_configuration,
    historical_v1_provider_event_projection,
    persist_provider_event_projection,
    provider_attempt_run_id,
    provider_event_projection,
    publish_successful_calibration_run,
    reconcile_case_evidence,
    validate_authoritative_provider_events,
    validate_calibration_artifact,
    validate_historical_attempt005_provider_events,
    validate_historical_attempt007_provider_events,
    validate_provider_event_projection,
    verify_external_run,
    verify_historical_attempt007_external_run,
    verify_historical_attempt008_external_run,
    verify_historical_attempt009_external_run,
    verify_historical_attempt010_external_run,
    write_calibration_artifact,
)
from tests.unit.evaluation.test_stage2_calibration import _request

import medevidence.persistence.repositories as repository_module
from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
    DeepSeekSemanticAssessmentV2,
    deepseek_provider_request_semantic_v2_bytes,
    deepseek_provider_request_v2_bytes,
    deepseek_provider_request_v3_bytes,
    deepseek_response_format_v2,
    deepseek_semantic_v2_response_format,
)
from medevidence.persistence import ProviderAttemptEvent, make_provider_attempt_event
from medevidence.tools.provider_attempt_framing import (
    APPROVED_HEADER_NAMES_IDENTITY,
    FRAMING_CONTRACT_IDENTITY,
    PERSISTED_AUTHORITY_FIELDS,
    FramingObservation,
    Observation,
    build_framing_observation,
    build_unavailable_observation,
    classify_framing,
    generated_consumer_mutation_witness,
    generated_contract_cases,
    normalize_approved_headers,
)
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
    REVIEW_ROUTING_POLICY_HASH,
    SEMANTIC_EVALUATION_PROMPT_BYTES_V3,
    SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH,
    SEMANTIC_EVALUATION_V2_CONTRACT_HASH,
    SEMANTIC_EVALUATION_V2_CONTRACT_VERSION,
    SEMANTIC_EVALUATION_V2_PROMPT_BYTES,
    SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH,
    SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_ROW_COUNT,
    SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY,
    SemanticEvaluationCandidate,
    SemanticEvaluationCandidateV2,
    SemanticEvaluationContractError,
    SemanticEvaluationUsage,
    SemanticRationaleCode,
    build_semantic_evaluation_result_v2,
    deepseek_v4_candidate_wire_bytes,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
    semantic_evaluation_v2_candidate_wire_bytes,
    semantic_evaluation_v2_routing_matrix_bytes,
    validate_semantic_evaluation_v2_routing_matrix_bytes,
)

CODE_REVISION = "a" * 40
MANIFEST_HASH = "sha256:" + "b" * 64


@pytest.mark.parametrize(
    "raw",
    (
        b'{"value":' + (b"9" * 5_000) + b"}",
        b'{"value":"\\ud800"}',
        b'{"\\ud800":"value"}',
    ),
)
def test_external_json_admission_totalizes_digit_limit_and_surrogate_text(raw: bytes) -> None:
    with pytest.raises(DeepSeekCalibrationError, match="external evidence JSON is invalid"):
        calibration_module._admit_external_json_bytes(raw, label="external evidence")


def test_external_json_serialization_totalizes_lone_surrogate() -> None:
    with pytest.raises(DeepSeekCalibrationError, match="external evidence JSON is invalid"):
        calibration_module._canonical_external_json_bytes(
            {"value": "\ud800"}, label="external evidence"
        )


class _StaticLedger:
    def __init__(self, events: tuple[ProviderAttemptEvent, ...]) -> None:
        self.events = events

    def list_events(self, provider_run_id: str) -> tuple[ProviderAttemptEvent, ...]:
        return tuple(item for item in self.events if item.provider_run_id == provider_run_id)


class _StringSubclass(str):
    pass


class _HostileString(str):
    def __new__(cls, value: str) -> _HostileString:
        instance = cast("_HostileString", super().__new__(cls, value))
        instance.operations = []
        return instance

    def __hash__(self) -> int:
        self.operations.append("hash")
        raise AssertionError("hostile provider event string was hashed")

    def __eq__(self, other: object) -> bool:
        self.operations.append("equality")
        raise AssertionError("hostile provider event string was compared")

    def __str__(self) -> str:
        self.operations.append("string")
        raise AssertionError("hostile provider event string was stringified")


class _DictSubclass(dict[str, object]):
    pass


class _ListSubclass(list[object]):
    pass


class _IntSubclass(int):
    pass


def _rehash_v2_event(event: ProviderAttemptEvent) -> ProviderAttemptEvent:
    payload = {
        field.name: getattr(event, field.name)
        for field in fields(event)
        if field.name != "event_id"
    }
    return replace(
        event,
        event_id=repository_module.canonical_provider_attempt_event_id(payload),
    )


def _complete_provider_events(  # type: ignore[no-untyped-def]
    raw_root, observations, provider_run_id="provider-attempt-run:sha256:" + "a" * 64
):
    events = []
    for ordinal in range(1, 37):
        start = make_provider_attempt_event(
            provider_run_id=provider_run_id,
            case_id=f"M3-008B-CAL-{ordinal:03d}",
            case_ordinal=ordinal,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
            request_hash=observations[ordinal - 1].assessment.provider_request_hash,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        raw = observations[ordinal - 1].assessment.raw_response_envelope_bytes
        terminal = make_provider_attempt_event(
            provider_run_id=start.provider_run_id,
            case_id=start.case_id,
            case_ordinal=ordinal,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=start.configuration_hash,
            request_hash=start.request_hash,
            started_at_utc=start.started_at_utc,
            completed_at_utc=start.started_at_utc,
            http_status=200,
            disposition="success",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=build_framing_observation(
                disposition="success",
                http_status=200,
                http_version="HTTP/2",
                headers=normalize_approved_headers(
                    (("content-type", "application/json"),),
                    raw_header_field_count=1,
                ),
                raw_header_field_count=1,
                body_complete=True,
                actual_body_byte_count=len(raw),
                raw_body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
                raw_relative_path=f"raw/case-{ordinal:03d}.bin",
            ),
        )
        path = raw_root / f"raw/case-{ordinal:03d}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        events.extend((start, terminal))
    return tuple(events)


def _observation(index: int, human: SemanticSupport, predicted: SemanticSupport):
    request = _request(f"run:00000000-0000-4000-8000-{index:012d}")
    code = {
        SemanticSupport.SUPPORTED: SemanticRationaleCode.DIRECT_SUPPORT,
        SemanticSupport.UNCERTAIN: SemanticRationaleCode.PARTIAL_OR_AMBIGUOUS_SUPPORT,
        SemanticSupport.UNSUPPORTED: SemanticRationaleCode.NO_SUPPORT,
    }[predicted]
    candidate = SemanticEvaluationCandidateV2(
        schema_version="M3_STAGE2_SEMANTIC_RESULT_V2",
        result=predicted,
        rationale_codes=(code,),
        explanation="Bounded calibration output.",
    )
    result = build_semantic_evaluation_result_v2(request, candidate)
    structured = semantic_evaluation_v2_candidate_wire_bytes(candidate)
    response_document = {
        "id": f"00000000-0000-4000-8000-{index:012d}",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "deepseek-v4-pro",
        "store": False,
        "previous_response_id": None,
        "parallel_tool_calls": True,
        "instructions": SEMANTIC_EVALUATION_V2_PROMPT_BYTES.decode(),
        "max_output_tokens": 4096,
        "reasoning": {"effort": "high", "summary": None},
        "text": {"format": deepseek_semantic_v2_response_format()},
        "tool_choice": "none",
        "tools": [],
        "output": [
            {
                "id": f"message-{index}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": structured.decode(), "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    }
    raw_response = canonical_json(response_document).encode()
    provider_request = deepseek_provider_request_semantic_v2_bytes(request)
    request_bytes = semantic_evaluation_request_bytes(request)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    case = FrozenCalibrationCase(
        ordinal=index,
        case_id=f"M3-008B-CAL-{index:03d}",
        category=f"category-{(index - 1) % 6}",
        source="pubmed",
        citation_relationship="supports",
        semantic_request_hash="sha256:" + hashlib.sha256(request_bytes).hexdigest(),
        stage1_admission_identity=request.stage1_admission.admission_hash,
        request=request,
        human_expected_state=human,
        human_authority="project_owner",
        human_notes="Nonempty Owner rationale.",
        immutable_projection_hash="sha256:" + "2" * 64,
    )
    assessment = DeepSeekSemanticAssessmentV2(
        result=result,
        evaluator_input_hash="sha256:"
        + hashlib.sha256(semantic_evaluation_input_bytes(request)).hexdigest(),
        provider_request_hash="sha256:" + hashlib.sha256(provider_request).hexdigest(),
        raw_provider_request_bytes=provider_request,
        provider_response_id=response_document["id"],
        provider_response_hash="sha256:" + hashlib.sha256(raw_response).hexdigest(),
        raw_response_envelope_bytes=raw_response,
        structured_output_bytes=structured,
        structured_output_hash="sha256:" + hashlib.sha256(structured).hexdigest(),
        attempts=1,
        usage=SemanticEvaluationUsage(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            cached_input_tokens=0,
            reasoning_output_tokens=0,
        ),
        started_at_utc=now,
        completed_at_utc=now,
    )
    return CalibrationObservation(case, assessment)


def _cases(errors: int = 0, *, zero_tolerance: bool = False):
    states = (
        (SemanticSupport.SUPPORTED,) * 12
        + (SemanticSupport.UNCERTAIN,) * 12
        + (SemanticSupport.UNSUPPORTED,) * 12
    )
    predictions = list(states)
    safe_error_indexes = (0, 1, 12, 13, 24, 25)
    for index in safe_error_indexes[:errors]:
        predictions[index] = (
            SemanticSupport.UNCERTAIN if index < 12 else SemanticSupport.UNSUPPORTED
        )
        if index >= 24:
            predictions[index] = SemanticSupport.UNCERTAIN
    if zero_tolerance:
        predictions[24] = SemanticSupport.SUPPORTED
    return tuple(
        _observation(index, human, predicted)
        for index, (human, predicted) in enumerate(zip(states, predictions, strict=True), start=1)
    )


def _freeze_test_inventory(
    monkeypatch: pytest.MonkeyPatch, observations: tuple[CalibrationObservation, ...]
) -> None:
    inventory = [
        {
            "case_id": item.case.case_id,
            "category": item.case.category,
            "source": item.case.source,
            "citation_relationship": item.case.citation_relationship,
            "semantic_request_hash": item.case.semantic_request_hash,
            "stage1_admission_identity": item.case.stage1_admission_identity,
            "immutable_projection_hash": item.case.immutable_projection_hash,
            "human_expected_state": item.case.human_expected_state.value,
        }
        for item in observations
    ]
    identity = "sha256:" + hashlib.sha256(canonical_json(inventory).encode()).hexdigest()
    counts = tuple(sorted(Counter(item.case.category for item in observations).items()))
    monkeypatch.setattr(calibration_module, "FROZEN_CASE_INVENTORY_IDENTITY", identity)
    monkeypatch.setattr(calibration_module, "FROZEN_CATEGORY_COUNTS", counts)


def _rebind_artifact(artifact: dict[str, object]) -> None:
    semantic = dict(artifact)
    semantic.pop("artifact_semantic_identity")
    semantic.pop("completed_at_utc")
    artifact["artifact_semantic_identity"] = (
        "sha256:" + hashlib.sha256(canonical_json(semantic).encode()).hexdigest()
    )


def test_exact_acceptance_boundary_31_passes_and_30_fails() -> None:
    at_threshold = acceptance_metrics(_cases(errors=5))
    below_threshold = acceptance_metrics(_cases(errors=6))
    assert at_threshold["agreement_count"] == 31
    assert at_threshold["agreement_rate"] == pytest.approx(31 / CASE_COUNT)
    assert at_threshold["accepted"] is True
    assert below_threshold["agreement_count"] == 30
    assert below_threshold["accepted"] is False


def test_zero_tolerance_transition_fails_even_when_agreement_is_high() -> None:
    metrics = acceptance_metrics(_cases(zero_tolerance=True))
    assert metrics["agreement_count"] == 35
    assert metrics["zero_tolerance_passed"] is False
    assert metrics["accepted"] is False


def test_state_denominators_recalls_categories_and_order_are_recomputed() -> None:
    metrics = acceptance_metrics(_cases())
    assert metrics["accepted"] is True
    assert metrics["categories_exercised"] == [f"category-{index}" for index in range(6)]
    assert all(
        row["n"] == 12 and row["recall"] == 1.0 for row in metrics["human_state_metrics"].values()
    )
    reordered = list(_cases())
    reordered[0], reordered[1] = reordered[1], reordered[0]
    with pytest.raises(DeepSeekCalibrationError, match="order drift"):
        acceptance_metrics(reordered)


def test_configuration_separately_binds_deepseek_and_unchanged_owner_truth() -> None:
    configuration = calibration_configuration(
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    assert configuration["provider"] == "DeepSeek API"
    assert configuration["provider_calibration_attempt"] == "Attempt011"
    assert configuration["semantic_contract"] == "M3_STAGE2_SEMANTIC_RESULT_V2"
    assert configuration["semantic_contract_version"] == SEMANTIC_EVALUATION_V2_CONTRACT_VERSION
    assert configuration["semantic_contract_hash"] == SEMANTIC_EVALUATION_V2_CONTRACT_HASH
    assert configuration["semantic_contract_hash"] == (
        "sha256:9b97996233f6dc80091f196209b18c27b23e0eeb5c82c6e7e8c0f954df69a3bb"
    )
    assert configuration["semantic_configuration_hash"] == (
        SEMANTIC_EVALUATION_V2_CONFIGURATION_HASH
    )
    assert configuration["semantic_configuration_hash"] == (
        "sha256:fd3e9bda090c92b0c83244d521cb3163f4c3e43bda74b1132efaad7ffbb7f491"
    )
    assert configuration["configuration_hash"] == (
        "sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9"
    )
    assert (
        configuration["routing_policy_hash"]
        == REVIEW_ROUTING_POLICY_HASH
        == ("sha256:cfeaf63c84f4b2e207519b45a2181d40f97d98479391dd1b66af12d9be790dd1")
    )
    assert (
        configuration["routing_matrix_hash"]
        == SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH
        == ("sha256:4fdca5d8b856452f89fb07748f83521b3dee530e42613bddc859d29bd8160a77")
    )
    assert configuration["calibration_prompt_rubric_version"] == 1
    assert configuration["model"] == "deepseek-v4-pro"
    assert configuration["human_resolution_identity"] == OWNER_RESOLUTION_IDENTITY
    assert configuration["tools"] == []
    assert configuration["web_search_enabled"] is False
    assert configuration["code_revision"] == CODE_REVISION
    assert configuration["implementation_manifest_hash"] == MANIFEST_HASH
    assert configuration["case_inventory_identity"].startswith("sha256:")
    assert configuration["frozen_category_counts"]["applicable_contradiction"] == 8
    assert configuration["framing_contract_identity"] == FRAMING_CONTRACT_IDENTITY
    assert configuration["approved_header_names_identity"] == APPROVED_HEADER_NAMES_IDENTITY
    assert configuration["wire_contract_identity"] == SEMANTIC_EVALUATION_V2_WIRE_CONTRACT_IDENTITY


def test_attempt004_configuration_and_run_identity_reconstruct_exact_historical_bytes() -> None:
    configuration = historical_attempt004_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=(
            "sha256:7555f0211f49b1486efcc91b07329dbd8699ba53c340fb773e1397f0b58bb6e8"
        ),
    )
    assert configuration["provider_calibration_attempt"] == "Attempt004"
    assert configuration["calibration_prompt_rubric_version"] == 1
    assert configuration["configuration_hash"] == (
        "sha256:35b8411e401f32f974dd1d795770b4db73e622165ead9e83bc3356190b50b377"
    )
    assert provider_attempt_run_id(configuration) == (
        "provider-attempt-run:sha256:"
        "9f10f1f340227b01355f72bf2bae64ff1072fbeece5eb4af573cbfd92c2e81ca"
    )


def test_attempt005_configuration_and_run_identity_reconstruct_exact_historical_bytes() -> None:
    configuration = historical_attempt005_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=(
            "sha256:1459861819f7179ecea3bf01bafe62aa7e0df4f096d0e736a387879639b20e14"
        ),
    )
    assert configuration["provider_calibration_attempt"] == "Attempt005"
    assert configuration["calibration_prompt_rubric_version"] == 2
    assert configuration["configuration_hash"] == (
        "sha256:b625eacd4439ea08b141c79ab79de4ed348610b3a9ace4be80977e73a704e8ef"
    )
    assert provider_attempt_run_id(configuration) == (
        "provider-attempt-run:sha256:"
        "cf810656f57cd738b59abd8694b07855b4be9839b5e495a9dfe31548d35ede31"
    )
    assert provider_attempt_run_id(configuration) == HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID
    assert HISTORICAL_ATTEMPT005_CASE1_REQUEST_BYTES == 5_972
    assert HISTORICAL_ATTEMPT005_CASE1_REQUEST_HASH == (
        "sha256:6d8d309524aa47dc342bbb2226f5e31003578be915bfed6bafc57f8b39b4f9c8"
    )
    assert HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_BYTES == 8_977
    assert HISTORICAL_ATTEMPT005_CASE1_RAW_RESPONSE_HASH == (
        "sha256:9141329b33f96df06cf6d889fa5c164c87acee8a3f0a2ac43712c8f01bb76f18"
    )
    assert HISTORICAL_ATTEMPT005_PROJECTION_HASH == (
        "sha256:0dddbbb75c5d46822d1e01acfb03c6e13588d90fa4a2f2e0fe033ff881e892f6"
    )
    assert HISTORICAL_ATTEMPT005_STATUS_BINDING_HASH == (
        "sha256:596b133e9468f21712ba789f6f5c41c9627957cf7b7d97dc9eb02d42db7e3a99"
    )
    assert (
        HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_BYTES,
        HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_BYTES,
    ) == (421, 400)
    assert HISTORICAL_ATTEMPT005_STRUCTURED_OUTPUT_HASH == (
        "sha256:c3fc115886cdd303a33c2288dd16fac01630c914d9a9fb972b88d3444e8bb383"
    )
    assert HISTORICAL_ATTEMPT005_DIAGNOSTIC_CANONICAL_HASH == (
        "sha256:c3e9f566882dde1b5d3af93efe5318ee430e26a38a6cad2f653c93b4bfd7a7f5"
    )


def test_attempt006_configuration_and_failure_classification_are_immutable() -> None:
    configuration = historical_attempt006_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=(
            "sha256:3764ce9a44294a0d2df1c7d9864747c1869fc4f6a88aded89d0567f387b19faa"
        ),
    )
    assert provider_attempt_run_id(configuration) == HISTORICAL_ATTEMPT006_PROVIDER_RUN_ID
    assert provider_attempt_run_id(configuration).removeprefix("provider-attempt-run:") == (
        HISTORICAL_ATTEMPT006_CONFIGURATION_BINDING_HASH
    )
    assert HISTORICAL_ATTEMPT006_RUN_CONFIGURATION_FILE_HASH == (
        "sha256:a06b25d912f784b9e0f03a53fdfa97555cecfd262ba26855b19f357f25624d8e"
    )
    assert len(HISTORICAL_ATTEMPT006_SUCCESS_CASE_FILE_HASHES) == 5
    classification = historical_attempt006_failure_classification()
    assert classification == {
        "classification": HISTORICAL_ATTEMPT006_CLASSIFICATION,
        "attempted_case_count": 6,
        "successful_case_ids": [f"M3-008B-CAL-{index:03d}" for index in range(1, 6)],
        "failed_case_id": "M3-008B-CAL-006",
        "provider_output_valid": True,
        "application_policy_binding_failed": True,
        "application_error_code": "human_review_binding_invalid",
        "projection_hash": HISTORICAL_ATTEMPT006_PROJECTION_HASH,
        "status_binding_hash": HISTORICAL_ATTEMPT006_STATUS_BINDING_HASH,
    }


def test_attempt006_provider_output_valid_but_application_binding_failed() -> None:
    request = _cases()[0].case.request
    candidate = SemanticEvaluationCandidate(
        schema_version="m3.semantic-evaluation.result.v2",
        result=SemanticSupport.SUPPORTED,
        rationale_codes=(SemanticRationaleCode.DIRECT_SUPPORT,),
        explanation="The evidence directly supports the bounded claim.",
        human_review_required=True,
    )
    structured = deepseek_v4_candidate_wire_bytes(candidate)
    response = {
        "id": "00000000-0000-4000-8000-000000000006",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": "deepseek-v4-pro",
        "store": False,
        "previous_response_id": None,
        "parallel_tool_calls": True,
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES_V3.decode("utf-8"),
        "max_output_tokens": 4096,
        "reasoning": {"effort": "high", "summary": None},
        "text": {"format": deepseek_response_format_v2()},
        "tool_choice": "none",
        "tools": [],
        "output": [
            {
                "id": "message-6",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": structured.decode(), "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    }
    raw = canonical_json(response).encode("utf-8")
    assert classify_historical_attempt006_application_binding(request, raw) == (
        HISTORICAL_ATTEMPT006_CLASSIFICATION
    )


def test_attempt007_configuration_and_failed_run_facts_are_immutable() -> None:
    configuration = historical_attempt007_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT007_MANIFEST_HASH,
    )
    assert configuration["provider_calibration_attempt"] == "Attempt007"
    assert configuration["configuration_version"] == (
        "m3.semantic-evaluation.v2.deepseek-responses.v1"
    )
    assert configuration["configuration_hash"] == (
        "sha256:2798cf926eb197b746fd3c321d50047c28dea5061d2f4613adb5c81b30c80b35"
    )
    assert provider_attempt_run_id(configuration) == HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID
    assert HISTORICAL_ATTEMPT007_CONFIGURATION_FILE_HASH == (
        "sha256:bb051d2244b452df3668c62b2a1694ee59d9d64711d902ed615d702d31a20376"
    )
    assert HISTORICAL_ATTEMPT007_PROJECTION_HASH.endswith("d98206684")
    assert HISTORICAL_ATTEMPT007_STATUS_BINDING_HASH.endswith("5b7aa9c")
    assert HISTORICAL_ATTEMPT007_SUCCESS_RAW_FACTS == (
        (7202, "sha256:0fb737073cebee8b50191406fa302b8097b7d931483fb70698a5ced905168a91"),
        (7729, "sha256:7db1ff5114111c6074b92070fb4a334c962fa393bf12f29210f1f85a52fa2e49"),
        (10572, "sha256:23751854f3d9e00e496c290e6eab3f7d1541c53044ad988cb0a9a042d03f918f"),
        (13534, "sha256:711e5e8e9895cba88dfeac0cdfff00c56e435428ae3566ca8faad14237971b59"),
    )


def test_attempt008_configuration_and_failed_run_facts_are_immutable() -> None:
    configuration = historical_attempt008_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT008_MANIFEST_HASH,
    )
    assert configuration["provider_calibration_attempt"] == "Attempt008"
    assert configuration["configuration_version"] == (
        "m3.semantic-evaluation.v2.deepseek-responses.v2"
    )
    assert configuration["configuration_hash"] == (
        "sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9"
    )
    assert provider_attempt_run_id(configuration) == HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID
    assert HISTORICAL_ATTEMPT008_CONFIGURATION_FILE_HASH == (
        "sha256:ddfa7ad1aaba6a074b32f9cbee8335cf4a57a3d717e633363375f82536ced1ad"
    )
    assert HISTORICAL_ATTEMPT008_PROJECTION_HASH.endswith("b781ecbb5")
    assert HISTORICAL_ATTEMPT008_STATUS_BINDING_HASH.endswith("16448185")
    assert HISTORICAL_ATTEMPT008_SUCCESS_RAW_FACTS == (
        (8194, "sha256:46d6b2273db0f887680c1301ce2c0850b78342f52f380b88ad1d05763d7f4460"),
        (8575, "sha256:1efc8b9ec1b03df9b3531fe32a7c37055d63ad7ae70b33bcd74767c81a57343d"),
        (8601, "sha256:4bd3d95017a5257e09e32863c7617fbfcc65186eec1ec947ebc9e9bbcf9ed98e"),
        (11612, "sha256:4db3aef2fc0e584896ef558f794ed9723f3e78ed1150e2dffe5e377a780fad85"),
    )


@pytest.mark.parametrize(
    "historical_run_id",
    (
        HISTORICAL_ATTEMPT005_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT006_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
        HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
    ),
)
def test_active_event_authority_rejects_every_known_historical_run_before_events(
    historical_run_id: str,
) -> None:
    with pytest.raises(DeepSeekCalibrationError, match="historical provider run"):
        validate_authoritative_provider_events(
            (),
            frozen_cases=(),
            expected_provider_run_id=historical_run_id,
        )


def test_attempt010_is_immutable_and_attempt011_has_a_distinct_run_identity() -> None:
    prior = historical_attempt009_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT009_MANIFEST_HASH,
    )
    historical = historical_attempt010_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT010_MANIFEST_HASH,
    )
    active = calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT010_MANIFEST_HASH,
    )
    assert prior["provider_calibration_attempt"] == "Attempt009"
    assert historical["provider_calibration_attempt"] == "Attempt010"
    assert active["provider_calibration_attempt"] == "Attempt011"
    assert (
        prior["configuration_hash"]
        == historical["configuration_hash"]
        == active["configuration_hash"]
        == ("sha256:64890c63e275c5bbce00f18e31899b4326d16220e6e7865356a3618ef4e557e9")
    )
    assert provider_attempt_run_id(prior) == HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID
    assert provider_attempt_run_id(historical) == HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID
    assert provider_attempt_run_id(active) != HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID
    assert {
        key: value for key, value in active.items() if key != "provider_calibration_attempt"
    } == {key: value for key, value in historical.items() if key != "provider_calibration_attempt"}
    assert HISTORICAL_ATTEMPT010_CONFIGURATION_FILE_HASH == (
        "sha256:491f4455127037bb55477587d1093d2c75ae050260e8cb04f338f52751fd0203"
    )
    assert HISTORICAL_ATTEMPT010_PROJECTION_HASH == (
        "sha256:ecc271a70ab6c482b32576432e690afec2da4f62dd09f46710076065db616694"
    )
    assert HISTORICAL_ATTEMPT010_STATUS_BINDING_HASH == (
        "sha256:c65e2dc63e6d14cc7a10631d45b9c9af21468d2d941ee3b2af18a448b2e7ec6f"
    )
    assert len(HISTORICAL_ATTEMPT010_SUCCESS_RAW_FACTS) == 4
    assert len(HISTORICAL_ATTEMPT010_CASE_FILE_HASHES) == 4
    assert HISTORICAL_ATTEMPT009_CONFIGURATION_FILE_HASH == (
        "sha256:94b1174508ca157d92517352670dc96899099eef165656d8ad84a4410ae23f67"
    )
    assert HISTORICAL_ATTEMPT009_PROJECTION_HASH == (
        "sha256:c02f71b8e928ea4076af9997c4c07ebd4cb27e7c290f64ed44dadeb3c91a1b46"
    )
    assert HISTORICAL_ATTEMPT009_STATUS_BINDING_HASH == (
        "sha256:3d883dfd3dd8af63abf11b05f516477e1091179ab17b57085a12ddd18bee4b22"
    )
    assert HISTORICAL_ATTEMPT009_SUCCESS_RAW_FACTS == (
        (8338, "sha256:6b015c926ca88a2f06f5f32c4f9fe9b2947c97b996d67ab3a76a758ab564ea58"),
        (8619, "sha256:912fd7eac7230a81738d2faea5941759d327ca983d2ba378b24aabe8666bc18d"),
        (11157, "sha256:a20a3a4872fc7ce290352290c02cb597233b537e01d77ba69489475a7679ce74"),
        (8258, "sha256:a496453a81b6e296c36a3cae7698bbc2b73ac7c4f30b9e9caa1e618084344a2e"),
    )
    assert len(HISTORICAL_ATTEMPT009_CASE_FILE_HASHES) == 4
    with pytest.raises(DeepSeekCalibrationError, match="attempt is invalid"):
        calibration_module._semantic_v2_calibration_configuration(
            code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            implementation_manifest_hash=HISTORICAL_ATTEMPT009_MANIFEST_HASH,
            provider_calibration_attempt="Attempt012",
            provider_configuration_version=cast(str, active["configuration_version"]),
            provider_configuration_hash=cast(str, active["configuration_hash"]),
        )


def test_attempt007_event_projection_and_status_are_isolated_from_attempt008(
    tmp_path: Path,
) -> None:
    source = _cases()[0]
    configuration = historical_attempt007_calibration_configuration(
        code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        implementation_manifest_hash=HISTORICAL_ATTEMPT007_MANIFEST_HASH,
    )
    start = make_provider_attempt_event(
        provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        case_id=source.case.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=cast(str, configuration["configuration_hash"]),
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 9, 3, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    assert validate_historical_attempt007_provider_events(
        (start,),
        frozen_cases=(source.case,),
        expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
    ) == (start,)
    projection = historical_attempt007_provider_event_projection(
        (start,),
        frozen_cases=(source.case,),
        expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
    )
    status = historical_attempt007_expected_run_status(
        configuration=configuration,
        events=(start,),
        frozen_cases=(source.case,),
        expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        raw_root=tmp_path,
    )
    assert projection["status"] == "NONFINAL"
    assert status["status"] == "INTERRUPTED"
    with pytest.raises(DeepSeekCalibrationError, match="historical provider run"):
        validate_authoritative_provider_events(
            (start,),
            frozen_cases=(source.case,),
            expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        )


def test_attempt007_exact_external_replay_when_immutable_evidence_is_present() -> None:
    root = Path(
        "D:/Projects/medevidence/.local/evidence/external-evidence/"
        "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION/deepseek-calibration-v2-attempt-007"
    )
    machine = (
        root.parent / "owner-adjudication-packet-v1" / "m3-008b-owner-adjudication-machine.json"
    )
    resolution = (
        root.parent / "owner-adjudication-resolution-v1" / "m3-008b-owner-resolution-packet.json"
    )
    if not root.is_dir() or not machine.is_file() or not resolution.is_file():
        pytest.skip("immutable local Attempt007 evidence is not installed")
    cases = calibration_module.load_frozen_calibration_cases(machine, resolution)
    projection = json.loads((root / "provider-attempt-projection.json").read_text("utf-8"))
    events: list[ProviderAttemptEvent] = []
    for row in projection["events"]:
        values = dict(row)
        for name, value in tuple(values.items()):
            if name in {"started_at_utc", "completed_at_utc"} and value is not None:
                values[name] = datetime.fromisoformat(value)
            elif type(value) is list:
                values[name] = tuple(value)
        events.append(ProviderAttemptEvent(**values))  # type: ignore[arg-type]
    verified = verify_historical_attempt007_external_run(
        _StaticLedger(tuple(events)),  # type: ignore[arg-type]
        root,
        expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
        expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        expected_implementation_manifest_hash=HISTORICAL_ATTEMPT007_MANIFEST_HASH,
        frozen_cases=cases,
    )
    assert verified["projection_hash"] == HISTORICAL_ATTEMPT007_PROJECTION_HASH

    changed = list(events)
    changed[-1] = replace(changed[-1], disposition="response_too_large")
    with pytest.raises(DeepSeekCalibrationError):
        verify_historical_attempt007_external_run(
            _StaticLedger(tuple(changed)),  # type: ignore[arg-type]
            root,
            expected_provider_run_id=HISTORICAL_ATTEMPT007_PROVIDER_RUN_ID,
            expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            expected_implementation_manifest_hash=HISTORICAL_ATTEMPT007_MANIFEST_HASH,
            frozen_cases=cases,
        )


def test_attempt008_exact_external_replay_when_immutable_evidence_is_present() -> None:
    root = Path(
        "D:/Projects/medevidence/.local/evidence/external-evidence/"
        "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION/deepseek-calibration-v2-attempt-008"
    )
    machine = (
        root.parent / "owner-adjudication-packet-v1" / "m3-008b-owner-adjudication-machine.json"
    )
    resolution = (
        root.parent / "owner-adjudication-resolution-v1" / "m3-008b-owner-resolution-packet.json"
    )
    if not root.is_dir() or not machine.is_file() or not resolution.is_file():
        pytest.skip("immutable local Attempt008 evidence is not installed")
    cases = calibration_module.load_frozen_calibration_cases(machine, resolution)
    projection = json.loads((root / "provider-attempt-projection.json").read_text("utf-8"))
    events: list[ProviderAttemptEvent] = []
    for row in projection["events"]:
        values = dict(row)
        for name, value in tuple(values.items()):
            if name in {"started_at_utc", "completed_at_utc"} and value is not None:
                values[name] = datetime.fromisoformat(value)
            elif type(value) is list:
                values[name] = tuple(value)
        events.append(ProviderAttemptEvent(**values))  # type: ignore[arg-type]
    verified = verify_historical_attempt008_external_run(
        _StaticLedger(tuple(events)),  # type: ignore[arg-type]
        root,
        expected_provider_run_id=HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID,
        expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        expected_implementation_manifest_hash=HISTORICAL_ATTEMPT008_MANIFEST_HASH,
        frozen_cases=cases,
    )
    assert verified["projection_hash"] == HISTORICAL_ATTEMPT008_PROJECTION_HASH

    changed = list(events)
    changed[-1] = replace(changed[-1], disposition="response_invalid")
    with pytest.raises(DeepSeekCalibrationError):
        verify_historical_attempt008_external_run(
            _StaticLedger(tuple(changed)),  # type: ignore[arg-type]
            root,
            expected_provider_run_id=HISTORICAL_ATTEMPT008_PROVIDER_RUN_ID,
            expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            expected_implementation_manifest_hash=HISTORICAL_ATTEMPT008_MANIFEST_HASH,
            frozen_cases=cases,
        )


@pytest.mark.parametrize(
    "mutated_surface",
    ("configuration", "projection", "status", "case", "raw"),
)
def test_attempt009_exact_external_replay_and_mutations_fail_closed(
    tmp_path: Path, mutated_surface: str
) -> None:
    root = Path(
        "D:/Projects/medevidence/.local/evidence/external-evidence/"
        "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION/deepseek-calibration-v2-attempt-009"
    )
    machine = (
        root.parent / "owner-adjudication-packet-v1" / "m3-008b-owner-adjudication-machine.json"
    )
    resolution = (
        root.parent / "owner-adjudication-resolution-v1" / "m3-008b-owner-resolution-packet.json"
    )
    raw_source = (
        root.parent
        / "provider-attempt-raw"
        / HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID.removeprefix("provider-attempt-run:sha256:")
    )
    if (
        not root.is_dir()
        or not machine.is_file()
        or not resolution.is_file()
        or not raw_source.is_dir()
    ):
        pytest.skip("immutable local Attempt009 evidence is not installed")
    cases = calibration_module.load_frozen_calibration_cases(machine, resolution)
    projection = json.loads((root / "provider-attempt-projection.json").read_text("utf-8"))
    events: list[ProviderAttemptEvent] = []
    for row in projection["events"]:
        values = dict(row)
        for name, value in tuple(values.items()):
            if name in {"started_at_utc", "completed_at_utc"} and value is not None:
                values[name] = datetime.fromisoformat(value)
            elif type(value) is list:
                values[name] = tuple(value)
        events.append(ProviderAttemptEvent(**values))  # type: ignore[arg-type]
    ledger = _StaticLedger(tuple(events))
    verified = verify_historical_attempt009_external_run(
        ledger,  # type: ignore[arg-type]
        root,
        expected_provider_run_id=HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
        expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        expected_implementation_manifest_hash=HISTORICAL_ATTEMPT009_MANIFEST_HASH,
        frozen_cases=cases,
    )
    assert verified["projection_hash"] == HISTORICAL_ATTEMPT009_PROJECTION_HASH
    with pytest.raises(DeepSeekCalibrationError, match="historical provider run"):
        validate_authoritative_provider_events(
            tuple(events),
            frozen_cases=cases,
            expected_provider_run_id=HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
        )

    copied_root = tmp_path / root.name
    copied_raw = (
        tmp_path
        / "provider-attempt-raw"
        / HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID.removeprefix("provider-attempt-run:sha256:")
    )
    shutil.copytree(root, copied_root)
    shutil.copytree(raw_source, copied_raw)
    targets = {
        "configuration": copied_root / "run-configuration.json",
        "projection": copied_root / "provider-attempt-projection.json",
        "status": copied_root / "run-status.json",
        "case": copied_root / "case-001-evidence.json",
        "raw": copied_raw / "case-001-attempt-001-raw.bin",
    }
    target = targets[mutated_surface]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(DeepSeekCalibrationError):
        verify_historical_attempt009_external_run(
            ledger,  # type: ignore[arg-type]
            copied_root,
            expected_provider_run_id=HISTORICAL_ATTEMPT009_PROVIDER_RUN_ID,
            expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            expected_implementation_manifest_hash=HISTORICAL_ATTEMPT009_MANIFEST_HASH,
            frozen_cases=cases,
        )


@pytest.mark.parametrize(
    "mutated_surface",
    ("configuration", "projection", "status", "case", "raw"),
)
def test_attempt010_exact_external_replay_and_mutations_fail_closed(
    tmp_path: Path, mutated_surface: str
) -> None:
    root = Path(
        "D:/Projects/medevidence/.local/evidence/external-evidence/"
        "M3-008B-STAGE2-DEVELOPMENT-CALIBRATION/deepseek-calibration-v2-attempt-010"
    )
    machine = (
        root.parent / "owner-adjudication-packet-v1" / "m3-008b-owner-adjudication-machine.json"
    )
    resolution = (
        root.parent / "owner-adjudication-resolution-v1" / "m3-008b-owner-resolution-packet.json"
    )
    raw_source = (
        root.parent
        / "provider-attempt-raw"
        / HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID.removeprefix("provider-attempt-run:sha256:")
    )
    if (
        not root.is_dir()
        or not machine.is_file()
        or not resolution.is_file()
        or not raw_source.is_dir()
    ):
        pytest.skip("immutable local Attempt010 evidence is not installed")
    cases = calibration_module.load_frozen_calibration_cases(machine, resolution)
    projection = json.loads((root / "provider-attempt-projection.json").read_text("utf-8"))
    events: list[ProviderAttemptEvent] = []
    for row in projection["events"]:
        values = dict(row)
        for name, value in tuple(values.items()):
            if name in {"started_at_utc", "completed_at_utc"} and value is not None:
                values[name] = datetime.fromisoformat(value)
            elif type(value) is list:
                values[name] = tuple(value)
        events.append(ProviderAttemptEvent(**values))  # type: ignore[arg-type]
    ledger = _StaticLedger(tuple(events))
    verified = verify_historical_attempt010_external_run(
        ledger,  # type: ignore[arg-type]
        root,
        expected_provider_run_id=HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
        expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
        expected_implementation_manifest_hash=HISTORICAL_ATTEMPT010_MANIFEST_HASH,
        frozen_cases=cases,
    )
    assert verified["projection_hash"] == HISTORICAL_ATTEMPT010_PROJECTION_HASH
    with pytest.raises(DeepSeekCalibrationError, match="historical provider run"):
        validate_authoritative_provider_events(
            tuple(events),
            frozen_cases=cases,
            expected_provider_run_id=HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
        )
    with pytest.raises(DeepSeekCalibrationError, match="expected provider run identity drift"):
        verify_external_run(
            ledger,  # type: ignore[arg-type]
            root,
            expected_provider_run_id=HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
            expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            expected_implementation_manifest_hash=HISTORICAL_ATTEMPT010_MANIFEST_HASH,
            frozen_cases=cases,
        )

    copied_root = tmp_path / root.name
    copied_raw = (
        tmp_path
        / "provider-attempt-raw"
        / HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID.removeprefix("provider-attempt-run:sha256:")
    )
    shutil.copytree(root, copied_root)
    shutil.copytree(raw_source, copied_raw)
    targets = {
        "configuration": copied_root / "run-configuration.json",
        "projection": copied_root / "provider-attempt-projection.json",
        "status": copied_root / "run-status.json",
        "case": copied_root / "case-001-evidence.json",
        "raw": copied_raw / "case-001-attempt-001-raw.bin",
    }
    target = targets[mutated_surface]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(DeepSeekCalibrationError):
        verify_historical_attempt010_external_run(
            ledger,  # type: ignore[arg-type]
            copied_root,
            expected_provider_run_id=HISTORICAL_ATTEMPT010_PROVIDER_RUN_ID,
            expected_code_revision="26c67108bf5b8de8b05bddf7e7ec5bac61261425",
            expected_implementation_manifest_hash=HISTORICAL_ATTEMPT010_MANIFEST_HASH,
            frozen_cases=cases,
        )


def test_routing_matrix_is_exhaustive_recomputed_and_tamper_evident() -> None:
    raw = semantic_evaluation_v2_routing_matrix_bytes()
    document = json.loads(raw)
    assert len(document["rows"]) == SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_ROW_COUNT == 702
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == (
        SEMANTIC_EVALUATION_V2_ROUTING_MATRIX_HASH
    )
    validate_semantic_evaluation_v2_routing_matrix_bytes(raw)
    document["rows"][0]["human_review_required"] = not document["rows"][0]["human_review_required"]
    with pytest.raises(SemanticEvaluationContractError, match="routing_matrix"):
        validate_semantic_evaluation_v2_routing_matrix_bytes(
            canonical_json(document).encode("utf-8")
        )


def test_acceptance_metrics_compare_semantic_state_not_routing() -> None:
    observations = list(_cases())
    first = observations[0]
    assert isinstance(first.assessment, DeepSeekSemanticAssessmentV2)
    semantically_identical = first.assessment.result.model_copy(
        update={"routing_disposition": object()}
    )
    observations[0] = CalibrationObservation(
        first.case,
        replace(first.assessment, result=semantically_identical),
    )
    assert acceptance_metrics(observations) == acceptance_metrics(_cases())


def test_attempt005_ledger_authority_is_historical_only_and_v4_cannot_replay_it() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "5" * 64
    request = deepseek_provider_request_v3_bytes(source.case.request)
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
        request_hash="sha256:" + hashlib.sha256(request).hexdigest(),
        started_at_utc=datetime(2026, 9, 2, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    assert validate_historical_attempt005_provider_events(
        (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
    ) == (start,)
    assert (
        historical_attempt005_provider_event_projection(
            (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
        )["status"]
        == "NONFINAL"
    )
    with pytest.raises(DeepSeekCalibrationError, match="frozen authority"):
        validate_authoritative_provider_events(
            (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
        )


def test_v2_ledger_projection_rejects_foreign_decision_and_header_authority(
    tmp_path,
) -> None:
    observations = _cases()
    events = list(_complete_provider_events(tmp_path, observations))
    terminal_index = next(
        index for index, event in enumerate(events) if event.event_kind == "TERMINAL"
    )
    terminal = events[terminal_index]

    events[terminal_index] = replace(
        terminal,
        framing_status="rejected",
        accepted_framing_class=None,
        framing_rejection_code="invalid_content_type",
    )
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            tuple(events),
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=terminal.provider_run_id,
            raw_root=tmp_path,
        )

    events[terminal_index] = replace(terminal, credential_echo=True)
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            tuple(events),
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=terminal.provider_run_id,
            raw_root=tmp_path,
        )

    events[terminal_index] = replace(terminal, error_code="foreign_error")
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            tuple(events),
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=terminal.provider_run_id,
            raw_root=tmp_path,
        )

    events[terminal_index] = replace(
        terminal,
        approved_header_names_identity="m3-approved-header-names:sha256:" + "0" * 64,
    )
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            tuple(events),
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=terminal.provider_run_id,
            raw_root=tmp_path,
        )


def test_v1_start_identity_and_absent_v2_facts_remain_immutable() -> None:
    source = _cases()[0]
    event = make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash="sha256:"
        + hashlib.sha256(deepseek_provider_request_v2_bytes(source.case.request)).hexdigest(),
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert event.schema_version == "M3_PROVIDER_ATTEMPT_EVENT_V1"
    assert event.event_id == (
        "provider-attempt-event:sha256:"
        "2b55a126da571bbac2cb4979cd89daef1c8ccbded7f9e17a506a7a7e35432043"
    )
    assert event.framing_contract_identity is None
    assert event.framing_input_identity is None
    assert event.framing_status is None
    historical_configuration = historical_v1_calibration_configuration(
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    assert historical_configuration["configuration_hash"] == (
        "sha256:8fb92f9658ca76c690d1182e3904095089771957f0e69f793f345b34006061b2"
    )
    assert "provider_calibration_attempt" not in historical_configuration
    assert "framing_contract_identity" not in historical_configuration
    projection = historical_v1_provider_event_projection(
        (event,),
        frozen_cases=(source.case,),
        expected_provider_run_id=event.provider_run_id,
    )
    v1_fields = (
        "event_id",
        "schema_version",
        "provider_run_id",
        "case_id",
        "case_ordinal",
        "attempt_ordinal",
        "event_kind",
        "event_slot",
        "start_event_id",
        "start_event_kind",
        "provider",
        "endpoint",
        "model",
        "configuration_hash",
        "request_hash",
        "started_at_utc",
        "completed_at_utc",
        "http_status",
        "disposition",
        "error_code",
        "credential_echo",
        "body_complete",
        "body_byte_count",
        "body_hash",
        "body_relative_path",
        "observed_body_bytes_lower_bound",
        "approved_header_names",
    )
    expected_start_row = {
        "event_id": (
            "provider-attempt-event:sha256:"
            "2b55a126da571bbac2cb4979cd89daef1c8ccbded7f9e17a506a7a7e35432043"
        ),
        "schema_version": "M3_PROVIDER_ATTEMPT_EVENT_V1",
        "provider_run_id": "provider-attempt-run:sha256:" + "a" * 64,
        "case_id": "M3-008B-CAL-001",
        "case_ordinal": 1,
        "attempt_ordinal": 1,
        "event_kind": "START",
        "event_slot": 0,
        "start_event_id": None,
        "start_event_kind": None,
        "provider": "DeepSeek API",
        "endpoint": "https://api.deepseek.com/responses",
        "model": "deepseek-v4-pro",
        "configuration_hash": (
            "sha256:8fb92f9658ca76c690d1182e3904095089771957f0e69f793f345b34006061b2"
        ),
        "request_hash": ("sha256:3c973297a54ecfc3cd4f3c6fe3409a50707fbadd4a63303f3e4a941c9625cf54"),
        "started_at_utc": "2026-08-31T00:00:00+00:00",
        "completed_at_utc": None,
        "http_status": None,
        "disposition": "started",
        "error_code": None,
        "credential_echo": False,
        "body_complete": None,
        "body_byte_count": None,
        "body_hash": None,
        "body_relative_path": None,
        "observed_body_bytes_lower_bound": None,
        "approved_header_names": [],
    }
    assert projection["schema_version"] == "m3.provider-attempt-projection.v1"
    assert projection["status"] == "NONFINAL"
    assert tuple(cast(list[dict[str, object]], projection["events"])[0]) == v1_fields
    assert tuple(calibration_module._PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA) == (
        "M3_PROVIDER_ATTEMPT_EVENT_V1",
        "M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    assert (
        calibration_module._PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA["M3_PROVIDER_ATTEMPT_EVENT_V1"]
        == v1_fields
    )
    expected_semantic = {
        "schema_version": "m3.provider-attempt-projection.v1",
        "event_count": 1,
        "attempt_count": 1,
        "status": "NONFINAL",
        "events": [expected_start_row],
    }
    expected_projection = {
        **expected_semantic,
        "projection_hash": (
            "sha256:f500205641b945dd4781cc69064800c7770dc1b374589dfa0d3209599d4d52f7"
        ),
    }
    projection_bytes = canonical_json(projection).encode("utf-8")
    assert projection_bytes == canonical_json(expected_projection).encode("utf-8")
    assert hashlib.sha256(projection_bytes).hexdigest() == (
        "fb5c50c1f85298535905b88a9b19ae97982ca7584b808dcab79d7ee4ec4ac678"
    )
    validate_provider_event_projection(
        projection,
        (event,),
        frozen_cases=(source.case,),
        expected_provider_run_id=event.provider_run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
    )
    falsely_reversioned = deepcopy(projection)
    falsely_reversioned["schema_version"] = "m3.provider-attempt-projection.v2"
    falsely_reversioned_semantic = dict(falsely_reversioned)
    falsely_reversioned_semantic.pop("projection_hash")
    falsely_reversioned["projection_hash"] = (
        "sha256:"
        + hashlib.sha256(canonical_json(falsely_reversioned_semantic).encode("utf-8")).hexdigest()
    )
    with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
        validate_provider_event_projection(
            falsely_reversioned,
            (event,),
            frozen_cases=(source.case,),
            expected_provider_run_id=event.provider_run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
        )

    recovery = make_provider_attempt_event(
        provider_run_id=event.provider_run_id,
        case_id=event.case_id,
        case_ordinal=event.case_ordinal,
        attempt_ordinal=event.attempt_ordinal,
        event_kind="RECOVERY",
        start_event=event,
        configuration_hash=event.configuration_hash,
        request_hash=event.request_hash,
        started_at_utc=event.started_at_utc,
        completed_at_utc=datetime(2026, 8, 31, 0, 1, tzinfo=UTC),
        disposition="interrupted_unknown_after_start",
        error_code="interrupted_unknown_after_start",
    )
    recovery_projection = historical_v1_provider_event_projection(
        (event, recovery),
        frozen_cases=(source.case,),
        expected_provider_run_id=event.provider_run_id,
    )
    expected_recovery_row = {
        **expected_start_row,
        "event_id": (
            "provider-attempt-event:sha256:"
            "4a36657de760dac122b62bb7eb26af02201f078293decfec420209639c287abe"
        ),
        "event_kind": "RECOVERY",
        "event_slot": 1,
        "start_event_id": expected_start_row["event_id"],
        "start_event_kind": "START",
        "completed_at_utc": "2026-08-31T00:01:00+00:00",
        "disposition": "interrupted_unknown_after_start",
        "error_code": "interrupted_unknown_after_start",
    }
    expected_recovery_semantic = {
        "schema_version": "m3.provider-attempt-projection.v1",
        "event_count": 2,
        "attempt_count": 1,
        "status": "INTERRUPTED",
        "events": [expected_start_row, expected_recovery_row],
    }
    expected_recovery_projection = {
        **expected_recovery_semantic,
        "projection_hash": (
            "sha256:fabc5df5c603e3012186c9bb2f238b3014acf4ae1133be4cc453dddc0fce61ac"
        ),
    }
    recovery_bytes = canonical_json(recovery_projection).encode("utf-8")
    assert recovery_bytes == canonical_json(expected_recovery_projection).encode("utf-8")
    assert hashlib.sha256(recovery_bytes).hexdigest() == (
        "7b4f92c2253236599c805f173bf8a34888832b15233467ae6c4af50800e5dd42"
    )
    validate_provider_event_projection(
        recovery_projection,
        (event, recovery),
        frozen_cases=(source.case,),
        expected_provider_run_id=event.provider_run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
    )

    v2_start = make_provider_attempt_event(
        provider_run_id=event.provider_run_id,
        case_id=event.case_id,
        case_ordinal=event.case_ordinal,
        attempt_ordinal=event.attempt_ordinal,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash="sha256:"
        + hashlib.sha256(
            deepseek_provider_request_semantic_v2_bytes(source.case.request)
        ).hexdigest(),
        started_at_utc=event.started_at_utc,
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    v2_projection = provider_event_projection(
        (v2_start,),
        frozen_cases=(source.case,),
        expected_provider_run_id=v2_start.provider_run_id,
    )
    v2_row = cast(list[dict[str, object]], v2_projection["events"])[0]
    assert tuple(v2_row) == tuple(field.name for field in fields(ProviderAttemptEvent))
    assert (
        tuple(v2_row)
        == calibration_module._PROVIDER_EVENT_ROW_FIELDS_BY_SCHEMA["M3_PROVIDER_ATTEMPT_EVENT_V2"]
    )
    assert v2_projection["schema_version"] == "m3.provider-attempt-projection.v2"


def test_empty_projection_requires_exact_event_schema_authority() -> None:
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    v1_projection = historical_v1_provider_event_projection(
        (), frozen_cases=(), expected_provider_run_id=run_id
    )
    v2_projection = provider_event_projection((), frozen_cases=(), expected_provider_run_id=run_id)
    v1_bytes = canonical_json(v1_projection).encode("utf-8")
    v2_bytes = canonical_json(v2_projection).encode("utf-8")
    assert v1_bytes == (
        b'{"attempt_count":0,"event_count":0,"events":[],"projection_hash":'
        b'"sha256:b13292bf35e4d168981d7ee996cc7810b332aa34dd68ae22034149d496e5d17c",'
        b'"schema_version":"m3.provider-attempt-projection.v1","status":"EMPTY"}'
    )
    assert hashlib.sha256(v1_bytes).hexdigest() == (
        "925cda3e3c19f922960fe5d3022089aced71b678bfea7370505dd62c7e3cc117"
    )
    assert v2_bytes == (
        b'{"attempt_count":0,"event_count":0,"events":[],"projection_hash":'
        b'"sha256:c493515df40ab618f9370d0070568ee134eb3e75ea04cf5ce76c136b467b0191",'
        b'"schema_version":"m3.provider-attempt-projection.v2","status":"EMPTY"}'
    )
    assert hashlib.sha256(v2_bytes).hexdigest() == (
        "38c6ac7196d79122ef1c6488512d100235f1554a0dba3a80f20b1f1da917a92a"
    )

    validate_provider_event_projection(
        v1_projection,
        (),
        frozen_cases=(),
        expected_provider_run_id=run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V1",
    )
    validate_provider_event_projection(
        v2_projection,
        (),
        frozen_cases=(),
        expected_provider_run_id=run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    with pytest.raises(DeepSeekCalibrationError, match="requires expected event schema"):
        validate_provider_event_projection(
            v2_projection,
            (),
            frozen_cases=(),
            expected_provider_run_id=run_id,
        )
    with pytest.raises(DeepSeekCalibrationError, match="schema authority is invalid"):
        validate_provider_event_projection(
            v2_projection,
            (),
            frozen_cases=(),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V3",
        )
    for projection, expected_event_schema_version in (
        (v1_projection, "M3_PROVIDER_ATTEMPT_EVENT_V2"),
        (v2_projection, "M3_PROVIDER_ATTEMPT_EVENT_V1"),
    ):
        with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
            validate_provider_event_projection(
                projection,
                (),
                frozen_cases=(),
                expected_provider_run_id=run_id,
                expected_event_schema_version=expected_event_schema_version,
            )

    source = _cases()[0]
    v1_start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash="sha256:"
        + hashlib.sha256(deepseek_provider_request_v2_bytes(source.case.request)).hexdigest(),
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
    )
    nonempty_v1_projection = historical_v1_provider_event_projection(
        (v1_start,),
        frozen_cases=(source.case,),
        expected_provider_run_id=run_id,
    )
    with pytest.raises(DeepSeekCalibrationError, match="schema authority mismatch"):
        validate_provider_event_projection(
            nonempty_v1_projection,
            (v1_start,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )


def test_artifact_reparses_every_byte_surface_and_rejects_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    observations = _cases()
    events = _complete_provider_events(tmp_path, observations)
    frozen_cases = tuple(item.case for item in observations)
    expected_provider_run_id = events[0].provider_run_id
    _freeze_test_inventory(monkeypatch, observations)
    artifact = build_calibration_artifact(
        observations,
        completed_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
        provider_attempt_events=events,
        provider_raw_root=tmp_path,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    validate_calibration_artifact(
        artifact,
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
        provider_attempt_events=events,
        provider_raw_root=tmp_path,
        frozen_cases=frozen_cases,
        expected_provider_run_id=expected_provider_run_id,
    )
    for field, value, match in (
        ("evaluator_input_hash", "sha256:" + "0" * 64, "provider request drift"),
        ("structured_output_hex", "00", "provider response drift"),
        ("semantic_contract_version", "m3.stage2-semantic-result.contract.v3", "response drift"),
        ("semantic_contract_hash", "sha256:" + "0" * 64, "response drift"),
        ("application_provenance_method", "foreign.method", "response drift"),
        ("provider_configuration_version", "foreign.profile", "response drift"),
        ("provider_configuration_hash", "sha256:" + "0" * 64, "response drift"),
        ("category", "mutated_category", "ordered case inventory drift"),
    ):
        changed = deepcopy(artifact)
        changed["cases"][0][field] = value
        _rebind_artifact(changed)
        with pytest.raises(DeepSeekCalibrationError, match=match):
            validate_calibration_artifact(
                changed,
                code_revision=CODE_REVISION,
                implementation_manifest_hash=MANIFEST_HASH,
                provider_attempt_events=events,
                provider_raw_root=tmp_path,
                frozen_cases=frozen_cases,
                expected_provider_run_id=expected_provider_run_id,
            )

    changed_code = deepcopy(artifact)
    changed_code["configuration"]["code_revision"] = "c" * 40
    _rebind_artifact(changed_code)
    with pytest.raises(DeepSeekCalibrationError, match="boundary drift"):
        validate_calibration_artifact(
            changed_code,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=events,
            provider_raw_root=tmp_path,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )

    changed_manifest = deepcopy(artifact)
    changed_manifest["configuration"]["implementation_manifest_hash"] = "sha256:" + "c" * 64
    _rebind_artifact(changed_manifest)
    with pytest.raises(DeepSeekCalibrationError, match="boundary drift"):
        validate_calibration_artifact(
            changed_manifest,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=events,
            provider_raw_root=tmp_path,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )

    missing_category = deepcopy(artifact)
    for case in missing_category["cases"]:
        if case["category"] == "category-5":
            case["category"] = "category-4"
    _rebind_artifact(missing_category)
    with pytest.raises(DeepSeekCalibrationError, match="ordered case inventory drift"):
        validate_calibration_artifact(
            missing_category,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=events,
            provider_raw_root=tmp_path,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )

    duplicate_response = deepcopy(artifact)
    first_id = duplicate_response["cases"][0]["provider_response_id"]
    second = duplicate_response["cases"][1]
    second_response = json.loads(bytes.fromhex(second["raw_provider_response_hex"]))
    second_response["id"] = first_id
    second_raw = canonical_json(second_response).encode()
    second["provider_response_id"] = first_id
    second["provider_response_hash"] = "sha256:" + hashlib.sha256(second_raw).hexdigest()
    second["raw_provider_response_hex"] = second_raw.hex()
    _rebind_artifact(duplicate_response)
    with pytest.raises(DeepSeekCalibrationError, match="response differs from ledger"):
        validate_calibration_artifact(
            duplicate_response,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=events,
            provider_raw_root=tmp_path,
            frozen_cases=frozen_cases,
            expected_provider_run_id=expected_provider_run_id,
        )


@pytest.mark.parametrize(
    ("code_revision", "manifest"),
    (
        ("A" * 40, MANIFEST_HASH),
        ("a" * 39, MANIFEST_HASH),
        ("z" * 40, MANIFEST_HASH),
        (CODE_REVISION, "b" * 64),
        (CODE_REVISION, "sha256:" + "B" * 64),
    ),
)
def test_code_and_manifest_identity_are_exact(code_revision: str, manifest: str) -> None:
    with pytest.raises(DeepSeekCalibrationError):
        calibration_configuration(
            code_revision=code_revision,
            implementation_manifest_hash=manifest,
        )


def test_atomic_writer_cleans_pending_directory_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    output = tmp_path / "external-result"
    monkeypatch.setattr(
        "evaluation.stage2_deepseek_calibration.validate_calibration_artifact",
        lambda _value, **_kwargs: None,
    )
    monkeypatch.setattr(
        "evaluation.stage2_deepseek_calibration.os.fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("simulated flush failure")),
    )
    with pytest.raises(OSError, match="simulated"):
        write_calibration_artifact(
            {"bounded": True},
            output,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=(),
            provider_raw_root=tmp_path,
            frozen_cases=(),
            expected_provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        )
    assert not output.exists()
    assert not (tmp_path / ".external-result.pending").exists()


def test_external_projection_cannot_override_authoritative_ledger_truth() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    projection = provider_event_projection(
        (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
    )
    assert projection["attempt_count"] == 1
    assert projection["status"] == "NONFINAL"
    changed = dict(projection)
    changed["status"] = "COMPLETE"
    semantic = dict(changed)
    semantic.pop("projection_hash")
    changed["projection_hash"] = (
        "sha256:" + hashlib.sha256(canonical_json(semantic).encode()).hexdigest()
    )
    with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
        validate_provider_event_projection(
            changed,
            (start,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )

    missing = deepcopy(projection)
    missing.pop("status")
    extra = deepcopy(projection)
    extra["foreign"] = None
    for drifted in (missing, extra):
        with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
            validate_provider_event_projection(
                drifted,
                (start,),
                frozen_cases=(source.case,),
                expected_provider_run_id=run_id,
                expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            )


def _bind_generated_observation_to_external_raw(
    observation: Observation,
    *,
    raw_root: Path,
    variant_ordinal: int,
) -> Observation:
    if type(observation) is not FramingObservation or observation.raw_relative_path is None:
        return observation
    assert observation.actual_body_byte_count is not None
    raw = bytes((variant_ordinal % 251 + 1,)) * observation.actual_body_byte_count
    relative_path = f"raw/external-matrix-{variant_ordinal:03d}.bin"
    path = raw_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return build_framing_observation(
        disposition=observation.disposition,
        http_status=observation.http_status,
        http_version=observation.observed_http_version,
        headers=observation.headers,
        raw_header_field_count=observation.raw_header_field_count,
        body_complete=observation.body_complete,
        actual_body_byte_count=observation.actual_body_byte_count,
        observed_body_bytes_lower_bound=observation.observed_body_bytes_lower_bound,
        raw_body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        raw_relative_path=relative_path,
    )


def test_external_projection_consumes_every_generated_mutation_at_its_exact_event_path(
    tmp_path: Path,
) -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    generated = generated_contract_cases()
    pairs = [
        (case, variant)
        for case in generated
        for variant in case.noncanonical_variants
        if "external" in variant.consumers
    ]
    primitive = [variant for _, variant in pairs if variant.case_id.startswith("primitive:")]
    consumer_counts = Counter(
        consumer
        for case in generated
        for variant in case.noncanonical_variants
        for consumer in variant.consumers
    )

    assert len(pairs) == consumer_counts["external"]
    assert len(primitive) == sum(
        variant.case_id.startswith("primitive:") for _case, variant in pairs
    )
    assert {variant.target_authority_field for variant in primitive} == set(
        PERSISTED_AUTHORITY_FIELDS
    )

    for variant_ordinal, (case, variant) in enumerate(pairs, start=1):
        observation = _bind_generated_observation_to_external_raw(
            case.observation,
            raw_root=tmp_path,
            variant_ordinal=variant_ordinal,
        )
        decision = classify_framing(observation)
        assert (
            decision.rule_key,
            decision.status,
            decision.accepted_class,
            decision.rejection_code,
        ) == (
            variant.expected_first_match_rule,
            variant.expected_status,
            variant.expected_class,
            variant.expected_code,
        )
        start = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=source.case.case_id,
            case_ordinal=source.case.ordinal,
            attempt_ordinal=1,
            event_kind="START",
            configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
            request_hash=source.assessment.provider_request_hash,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )
        disposition = observation.disposition
        terminal = make_provider_attempt_event(
            provider_run_id=run_id,
            case_id=source.case.case_id,
            case_ordinal=source.case.ordinal,
            attempt_ordinal=1,
            event_kind="TERMINAL",
            start_event=start,
            configuration_hash=start.configuration_hash,
            request_hash=start.request_hash,
            started_at_utc=start.started_at_utc,
            completed_at_utc=start.started_at_utc,
            http_status=observation.http_status,
            disposition=disposition,
            error_code=None if disposition == "success" else disposition,
            credential_echo=disposition == "credential_echo",
            schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            framing_observation=observation,
        )
        projection = provider_event_projection(
            (start, terminal),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            raw_root=tmp_path,
        )
        changed = deepcopy(projection)
        event_rows = cast(list[object], changed["events"])
        terminal_row = cast(dict[str, object], event_rows[1])
        assert set(PERSISTED_AUTHORITY_FIELDS) <= set(terminal_row)
        external_target = next(
            target for target in variant.consumer_targets if target.consumer == "external"
        )
        consumer_witnesses = generated_consumer_mutation_witness(
            variant,
            "external",
            terminal_row,
        )
        assert external_target.authority_fields == tuple(
            witness.field for witness in consumer_witnesses
        )
        assert external_target.direct_target_paths == tuple(
            witness.direct_target_path for witness in consumer_witnesses
        )

        for witness in consumer_witnesses:
            assert witness.case_id == variant.case_id
            assert witness.consumer == "external"
            assert witness.target_authority_field == variant.target_authority_field
            assert witness.direct_target_path == (
                f"provider-attempt-projection.events[*].{witness.field}"
            )
            assert witness.field in terminal_row
            original = terminal_row[witness.field]
            assert type(original) is type(witness.canonical_value)
            assert original == witness.canonical_value
            if witness.operation == "remove":
                del terminal_row[witness.field]
                assert witness.field not in terminal_row
            else:
                terminal_row[witness.field] = witness.mutated_value
                assert terminal_row[witness.field] is witness.mutated_value
                assert (
                    type(original) is not type(witness.mutated_value)
                    or original != witness.mutated_value
                )

        with pytest.raises(DeepSeekCalibrationError):
            validate_provider_event_projection(
                changed,
                (start, terminal),
                frozen_cases=(source.case,),
                expected_provider_run_id=run_id,
                expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
                raw_root=tmp_path,
            )


def test_external_projection_rejects_recursive_builtin_subclasses() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    projection = provider_event_projection(
        (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
    )
    root_subclass = _DictSubclass(projection)
    list_subclass = deepcopy(projection)
    list_subclass["events"] = _ListSubclass(cast(list[object], list_subclass["events"]))
    string_subclass = deepcopy(projection)
    string_subclass["status"] = _StringSubclass(cast(str, string_subclass["status"]))
    integer_subclass = deepcopy(projection)
    integer_subclass["attempt_count"] = _IntSubclass(cast(int, integer_subclass["attempt_count"]))

    for drifted in (root_subclass, list_subclass, string_subclass, integer_subclass):
        with pytest.raises(DeepSeekCalibrationError, match="value type is invalid"):
            validate_provider_event_projection(
                drifted,
                (start,),
                frozen_cases=(source.case,),
                expected_provider_run_id=run_id,
                expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            )


def test_external_projection_rejects_boolean_as_integer_type_drift() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    projection = provider_event_projection(
        (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
    )
    changed = json.loads(canonical_json(projection))
    changed["events"][0]["credential_echo"] = 0

    with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
        validate_provider_event_projection(
            changed,
            (start,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )

    changed = json.loads(canonical_json(projection))
    changed["attempt_count"] = True
    with pytest.raises(DeepSeekCalibrationError, match="differs from ledger"):
        validate_provider_event_projection(
            changed,
            (start,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )


@pytest.mark.parametrize("field_name", ("case_ordinal", "attempt_ordinal", "event_slot"))
def test_external_projection_rejects_boolean_start_and_failure_topology(
    field_name: str,
) -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    terminal = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=start.case_id,
        case_ordinal=start.case_ordinal,
        attempt_ordinal=start.attempt_ordinal,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        http_status=200,
        disposition="evidence_persistence_failure",
        error_code="evidence_persistence_failure",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=build_unavailable_observation(
            disposition="evidence_persistence_failure",
            http_status=200,
        ),
    )
    start_value = field_name != "event_slot"
    bad_start = _rehash_v2_event(replace(start, **{field_name: start_value}))
    bad_terminal = _rehash_v2_event(
        replace(
            terminal,
            **{field_name: True},
            start_event_id=bad_start.event_id,
        )
    )

    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            (bad_start, bad_terminal),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("case_id", _StringSubclass("M3-008B-CAL-001")),
        ("event_kind", _StringSubclass("START")),
        ("provider_run_id", _StringSubclass("provider-attempt-run:sha256:" + "a" * 64)),
    ),
)
def test_external_projection_rejects_string_subclass_before_frozen_lookup(
    field_name: str,
    replacement: str,
) -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    changed = _rehash_v2_event(replace(start, **{field_name: replacement}))

    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            (changed,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
        )


def test_external_projection_validates_all_event_primitives_before_schema_inference() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    projection = provider_event_projection(
        (start,), frozen_cases=(source.case,), expected_provider_run_id=run_id
    )
    hostile_values = {
        "schema_version": _HostileString("M3_PROVIDER_ATTEMPT_EVENT_V2"),
        "provider_run_id": _HostileString(run_id),
        "case_id": _HostileString(source.case.case_id),
        "event_kind": _HostileString("START"),
    }
    hostile_event = replace(start, **hostile_values)

    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        validate_provider_event_projection(
            projection,
            (hostile_event,),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        )

    assert all(value.operations == [] for value in hostile_values.values())


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("body_byte_count", True),
        ("actual_body_byte_count", True),
        ("body_hash", _StringSubclass("sha256:" + "1" * 64)),
        ("raw_body_hash", _StringSubclass("sha256:" + "1" * 64)),
    ),
)
def test_external_projection_rejects_canonically_rehashed_body_type_drift(
    field_name: str,
    replacement: object,
) -> None:
    source = _cases()[0]
    raw = b"bounded-provider-body"
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    terminal = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=start.case_id,
        case_ordinal=start.case_ordinal,
        attempt_ordinal=start.attempt_ordinal,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        http_status=200,
        disposition="response_invalid",
        error_code="response_invalid",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=build_framing_observation(
            disposition="response_invalid",
            http_status=200,
            http_version="HTTP/2",
            headers=normalize_approved_headers(
                (("content-type", "application/json"),),
                raw_header_field_count=1,
            ),
            raw_header_field_count=1,
            body_complete=True,
            actual_body_byte_count=len(raw),
            raw_body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
            raw_relative_path="raw/case-001.bin",
        ),
    )
    changed = _rehash_v2_event(replace(terminal, **{field_name: replacement}))

    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        provider_event_projection(
            (start, changed),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
        )


def test_projection_verifies_exact_ledger_bound_raw_file(tmp_path) -> None:
    source = _cases()[0]
    raw = b'{"safe":"raw-before-parse"}'
    relative = "provider-attempt-raw/a/case-001-attempt-001-raw.bin"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    start = make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    terminal = make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        http_status=200,
        disposition="response_invalid",
        error_code="response_invalid",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=build_framing_observation(
            disposition="response_invalid",
            http_status=200,
            http_version="HTTP/2",
            headers=normalize_approved_headers(
                (("content-type", "application/json"),),
                raw_header_field_count=1,
            ),
            raw_header_field_count=1,
            body_complete=True,
            actual_body_byte_count=len(raw),
            raw_body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
            raw_relative_path=relative,
        ),
    )
    projection = provider_event_projection(
        (start, terminal),
        frozen_cases=(source.case,),
        expected_provider_run_id=start.provider_run_id,
        raw_root=tmp_path,
    )
    validate_provider_event_projection(
        projection,
        (start, terminal),
        frozen_cases=(source.case,),
        expected_provider_run_id=start.provider_run_id,
        expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        raw_root=tmp_path,
    )
    path.write_bytes(b"tampered")
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body differs"):
        validate_provider_event_projection(
            projection,
            (start, terminal),
            frozen_cases=(source.case,),
            expected_provider_run_id=start.provider_run_id,
            expected_event_schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
            raw_root=tmp_path,
        )


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unsupported")
@pytest.mark.parametrize("consumer", ("projection", "case_evidence", "artifact"))
def test_every_raw_consumer_rejects_final_symlink_before_opening_outside_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    consumer: str,
) -> None:
    observations = _cases()
    _freeze_test_inventory(monkeypatch, observations)
    events = _complete_provider_events(tmp_path, observations)
    source = observations[0]
    artifact = (
        build_calibration_artifact(
            observations,
            completed_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
            provider_attempt_events=events,
            provider_raw_root=tmp_path,
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=events[0].provider_run_id,
        )
        if consumer == "artifact"
        else None
    )
    raw_path = tmp_path / "raw/case-001.bin"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-final.bin"
    outside.write_bytes(source.assessment.raw_response_envelope_bytes)
    raw_path.unlink()
    try:
        raw_path.symlink_to(outside)
    except OSError:
        outside.unlink(missing_ok=True)
        pytest.skip("symlink creation is unavailable to this test process")
    opened: list[Path] = []
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(DeepSeekCalibrationError, match=r"raw provider body|raw response path"):
        if consumer == "projection":
            provider_event_projection(
                events,
                frozen_cases=tuple(item.case for item in observations),
                expected_provider_run_id=events[0].provider_run_id,
                raw_root=tmp_path,
            )
        elif consumer == "case_evidence":
            calibration_module.canonical_case_evidence_document(
                source.case,
                events,
                tmp_path,
                frozen_cases=tuple(item.case for item in observations),
                expected_provider_run_id=events[0].provider_run_id,
            )
        else:
            assert artifact is not None
            validate_calibration_artifact(
                artifact,
                code_revision=CODE_REVISION,
                implementation_manifest_hash=MANIFEST_HASH,
                provider_attempt_events=events,
                provider_raw_root=tmp_path,
                frozen_cases=tuple(item.case for item in observations),
                expected_provider_run_id=events[0].provider_run_id,
            )
    assert opened == []
    raw_path.unlink(missing_ok=True)
    outside.unlink(missing_ok=True)


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unsupported")
def test_raw_consumer_rejects_symlinked_ancestor_before_opening_outside_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations = _cases()
    events = _complete_provider_events(tmp_path, observations)
    raw_directory = tmp_path / "raw"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-directory"
    outside.mkdir()
    for child in raw_directory.iterdir():
        child.unlink()
    raw_directory.rmdir()
    try:
        raw_directory.symlink_to(outside, target_is_directory=True)
    except OSError:
        outside.rmdir()
        pytest.skip("directory symlink creation is unavailable to this test process")
    (outside / "case-001.bin").write_bytes(observations[0].assessment.raw_response_envelope_bytes)
    opened: list[Path] = []
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body"):
        provider_event_projection(
            events,
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=events[0].provider_run_id,
            raw_root=tmp_path,
        )
    assert opened == []
    raw_directory.unlink(missing_ok=True)
    (outside / "case-001.bin").unlink(missing_ok=True)
    outside.rmdir()


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unsupported")
def test_raw_consumer_rejects_symlinked_ancestor_above_approved_root_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations = _cases()
    real_parent = tmp_path / "real"
    approved_root = real_parent / "approved"
    approved_root.mkdir(parents=True)
    events = _complete_provider_events(approved_root, observations)
    alias_parent = tmp_path / "link"
    try:
        alias_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink creation is unavailable to this test process")
    opened: list[Path] = []
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body"):
        provider_event_projection(
            events,
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=events[0].provider_run_id,
            raw_root=alias_parent / "approved",
        )
    assert opened == []


def test_raw_consumer_rejects_case_alias_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations = _cases()
    events = _complete_provider_events(tmp_path, observations)
    start = events[0]
    prior = events[1]
    raw = observations[0].assessment.raw_response_envelope_bytes
    alias_terminal = make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=start.case_ordinal,
        attempt_ordinal=start.attempt_ordinal,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=prior.completed_at_utc,
        http_status=200,
        disposition="success",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
        framing_observation=build_framing_observation(
            disposition="success",
            http_status=200,
            http_version="HTTP/2",
            headers=normalize_approved_headers(
                (("content-type", "application/json"),), raw_header_field_count=1
            ),
            raw_header_field_count=1,
            body_complete=True,
            actual_body_byte_count=len(raw),
            raw_body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
            raw_relative_path="RAW/CASE-001.BIN",
        ),
    )
    alias_events = (start, alias_terminal, *events[2:])
    opened: list[Path] = []
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body"):
        provider_event_projection(
            alias_events,
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=start.provider_run_id,
            raw_root=tmp_path,
        )
    assert opened == []


def test_raw_consumer_rejects_reparse_ancestor_before_opening_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations = _cases()
    events = _complete_provider_events(tmp_path, observations)
    marked = tmp_path.parent
    original_lstat = os.lstat
    reparse_flag = 0x400
    monkeypatch.setattr(
        calibration_module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", reparse_flag, raising=False
    )

    class ReparseStat:
        def __init__(self, value: os.stat_result) -> None:
            self._value = value
            self.st_mode = value.st_mode
            self.st_file_attributes = reparse_flag

        def __getattr__(self, name: str) -> object:
            return getattr(self._value, name)

    def marked_lstat(path: os.PathLike[str] | str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        value = original_lstat(path, *args, **kwargs)
        return ReparseStat(value) if Path(path) == marked else value

    monkeypatch.setattr(calibration_module.os, "lstat", marked_lstat)
    opened: list[Path] = []
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body"):
        provider_event_projection(
            events,
            frozen_cases=tuple(item.case for item in observations),
            expected_provider_run_id=events[0].provider_run_id,
            raw_root=tmp_path,
        )
    assert opened == []


def test_projection_rejects_terminal_only_and_dual_closure() -> None:
    source = _cases()[0]
    start = make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    terminal = make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        disposition="provider_rejected",
        error_code="provider_rejected",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    recovery = make_provider_attempt_event(
        provider_run_id=start.provider_run_id,
        case_id=start.case_id,
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="RECOVERY",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        disposition="interrupted_unknown_after_start",
        error_code="interrupted_unknown_after_start",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    with pytest.raises(DeepSeekCalibrationError, match="START authority"):
        provider_event_projection(
            (terminal,),
            frozen_cases=(source.case,),
            expected_provider_run_id=start.provider_run_id,
        )
    with pytest.raises(DeepSeekCalibrationError, match="closure topology drift"):
        provider_event_projection(
            (start, terminal, recovery),
            frozen_cases=(source.case,),
            expected_provider_run_id=start.provider_run_id,
        )


@pytest.mark.parametrize("closure_kind", ("TERMINAL", "RECOVERY"))
def test_authoritative_events_reject_failed_or_recovered_wrong_request(
    closure_kind: str,
) -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_V2_PROVIDER_CONFIGURATION_HASH,
        request_hash="sha256:" + "0" * 64,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    closure = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=start.case_id,
        case_ordinal=start.case_ordinal,
        attempt_ordinal=1,
        event_kind=closure_kind,
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        disposition=(
            "provider_rejected" if closure_kind == "TERMINAL" else "interrupted_unknown_after_start"
        ),
        error_code=(
            "provider_rejected" if closure_kind == "TERMINAL" else "interrupted_unknown_after_start"
        ),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    with pytest.raises(DeepSeekCalibrationError, match="request differs"):
        validate_authoritative_provider_events(
            (start, closure),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
        )


def test_authoritative_events_reject_configuration_mismatch_on_any_event() -> None:
    source = _cases()[0]
    run_id = "provider-attempt-run:sha256:" + "a" * 64
    start = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=source.case.case_id,
        case_ordinal=source.case.ordinal,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH_V3,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    terminal = make_provider_attempt_event(
        provider_run_id=run_id,
        case_id=start.case_id,
        case_ordinal=start.case_ordinal,
        attempt_ordinal=1,
        event_kind="TERMINAL",
        start_event=start,
        configuration_hash=start.configuration_hash,
        request_hash=start.request_hash,
        started_at_utc=start.started_at_utc,
        completed_at_utc=start.started_at_utc,
        disposition="provider_rejected",
        error_code="provider_rejected",
        schema_version="M3_PROVIDER_ATTEMPT_EVENT_V2",
    )
    foreign_terminal = replace(terminal, configuration_hash="sha256:" + "0" * 64)
    with pytest.raises(DeepSeekCalibrationError, match="canonical validation failed"):
        validate_authoritative_provider_events(
            (start, foreign_terminal),
            frozen_cases=(source.case,),
            expected_provider_run_id=run_id,
        )


def test_external_run_verifier_reconstructs_and_rejects_rebound_file_mutations(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    observations = _cases()
    frozen_cases = tuple(item.case for item in observations)
    _freeze_test_inventory(monkeypatch, observations)
    configuration = calibration_configuration(
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    run_id = provider_attempt_run_id(configuration)
    events = _complete_provider_events(tmp_path, observations, run_id)
    output = tmp_path / "verified-run"
    pending = begin_pending_calibration_run(
        output,
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    reconcile_case_evidence(
        pending,
        frozen_cases,
        events,
        tmp_path,
        expected_provider_run_id=run_id,
    )
    persist_provider_event_projection(
        pending,
        events,
        frozen_cases=frozen_cases,
        expected_provider_run_id=run_id,
    )
    artifact = build_calibration_artifact(
        observations,
        completed_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
        provider_attempt_events=events,
        provider_raw_root=tmp_path,
        frozen_cases=frozen_cases,
        expected_provider_run_id=run_id,
    )
    publish_successful_calibration_run(
        pending,
        artifact,
        provider_attempt_events=events,
        provider_raw_root=tmp_path,
        frozen_cases=frozen_cases,
        expected_provider_run_id=run_id,
    )
    repository = _StaticLedger(events)
    verify_kwargs = {
        "expected_provider_run_id": run_id,
        "expected_code_revision": CODE_REVISION,
        "expected_implementation_manifest_hash": MANIFEST_HASH,
        "frozen_cases": frozen_cases,
    }
    verified = verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    assert verified["status"] == "COMPLETE"

    canonical_json_paths = (
        output / "provider-attempt-projection.json",
        output / "run-configuration.json",
        output / "run-status.json",
        output / "case-001-evidence.json",
        output / "m3-008b-deepseek-calibration.json",
    )
    for path in canonical_json_paths:
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        with pytest.raises(DeepSeekCalibrationError, match="bytes are not canonical"):
            verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
        path.write_bytes(original)

    projection_path = output / "provider-attempt-projection.json"
    original_projection = projection_path.read_bytes()
    projection_value = json.loads(original_projection)
    projection_path.write_bytes(
        json.dumps(projection_value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    with pytest.raises(DeepSeekCalibrationError, match="bytes are not canonical"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    projection_path.write_bytes(original_projection)

    configuration_path = output / "run-configuration.json"
    original_configuration = configuration_path.read_bytes()
    configuration_value = json.loads(original_configuration)
    reversed_configuration = dict(reversed(tuple(configuration_value.items())))
    configuration_path.write_bytes(
        json.dumps(reversed_configuration, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    with pytest.raises(DeepSeekCalibrationError, match="bytes are not canonical"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    configuration_path.write_bytes(original_configuration)

    configuration_path.write_bytes(b'{"schema_version":"duplicate",' + original_configuration[1:])
    with pytest.raises(DeepSeekCalibrationError, match="JSON is invalid"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    configuration_path.write_bytes(original_configuration)

    configuration_path.write_bytes(b'{"invalid":"\xff"}')
    with pytest.raises(DeepSeekCalibrationError, match="JSON is invalid"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    configuration_path.write_bytes(original_configuration)

    changed_configuration = json.loads(original_configuration)
    changed_configuration["configuration"]["code_revision"] = "c" * 40
    changed_configuration["configuration_binding_hash"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json(changed_configuration["configuration"]).encode()
        ).hexdigest()
    )
    configuration_path.write_bytes(canonical_json(changed_configuration).encode())
    with pytest.raises(DeepSeekCalibrationError, match="run configuration differs"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    configuration_path.write_bytes(original_configuration)

    status_path = output / "run-status.json"
    original_status = status_path.read_bytes()
    changed_status = json.loads(original_status)
    changed_status["status"] = "FAILED"
    status_semantic = dict(changed_status)
    status_semantic.pop("status_binding_hash")
    changed_status["status_binding_hash"] = (
        "sha256:" + hashlib.sha256(canonical_json(status_semantic).encode()).hexdigest()
    )
    status_path.write_bytes(canonical_json(changed_status).encode())
    with pytest.raises(DeepSeekCalibrationError, match="run status differs"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    status_path.write_bytes(original_status)

    case_path = output / "case-001-evidence.json"
    original_case = case_path.read_bytes()
    changed_case = json.loads(original_case)
    changed_case["evidence"]["human_notes"] = "rebound mutation"
    changed_case["evidence_binding_hash"] = (
        "sha256:" + hashlib.sha256(canonical_json(changed_case["evidence"]).encode()).hexdigest()
    )
    case_path.write_bytes(canonical_json(changed_case).encode())
    with pytest.raises(DeepSeekCalibrationError, match="case evidence differs"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    case_path.write_bytes(original_case)

    artifact_path = output / "m3-008b-deepseek-calibration.json"
    sidecar_path = output / "m3-008b-deepseek-calibration.json.sha256"
    original_artifact = artifact_path.read_bytes()
    original_sidecar = sidecar_path.read_bytes()
    changed_artifact = json.loads(original_artifact)
    changed_artifact["holdout_accessed"] = True
    _rebind_artifact(changed_artifact)
    changed_artifact_raw = canonical_json(changed_artifact).encode()
    artifact_path.write_bytes(changed_artifact_raw)
    sidecar_path.write_text(
        f"{hashlib.sha256(changed_artifact_raw).hexdigest()}  {artifact_path.name}\n",
        encoding="ascii",
    )
    with pytest.raises(DeepSeekCalibrationError, match="artifact boundary drift"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
    artifact_path.write_bytes(original_artifact)
    sidecar_path.write_bytes(original_sidecar)

    sidecar_path.write_text("0" * 64 + f"  {artifact_path.name}\n", encoding="ascii")
    with pytest.raises(DeepSeekCalibrationError, match="artifact/status binding drift"):
        verify_external_run(repository, output, **verify_kwargs)  # type: ignore[arg-type]
