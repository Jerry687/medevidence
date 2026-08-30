from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime

import evaluation.stage2_deepseek_calibration as calibration_module
import pytest
from evaluation.stage2_deepseek_calibration import (
    CASE_COUNT,
    OWNER_RESOLUTION_IDENTITY,
    CalibrationObservation,
    DeepSeekCalibrationError,
    FrozenCalibrationCase,
    acceptance_metrics,
    build_calibration_artifact,
    calibration_configuration,
    validate_calibration_artifact,
    write_calibration_artifact,
)
from pydantic import BaseModel
from tests.unit.evaluation.test_stage2_calibration import _request

from medevidence.domain import canonical_json
from medevidence.infrastructure.deepseek_semantic_evaluator import (
    DeepSeekSemanticAssessment,
    deepseek_provider_request_bytes,
    deepseek_response_format,
)
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    SEMANTIC_EVALUATION_PROMPT_BYTES,
    SemanticEvaluationCandidate,
    SemanticEvaluationUsage,
    SemanticRationaleCode,
    build_deepseek_semantic_evaluation_result,
    semantic_evaluation_input_bytes,
    semantic_evaluation_request_bytes,
)

CODE_REVISION = "a" * 40
MANIFEST_HASH = "sha256:" + "b" * 64


def _observation(index: int, human: SemanticSupport, predicted: SemanticSupport):
    request = _request(f"run:00000000-0000-4000-8000-{index:012d}")
    code = {
        SemanticSupport.SUPPORTED: SemanticRationaleCode.DIRECT_SUPPORT,
        SemanticSupport.UNCERTAIN: SemanticRationaleCode.PARTIAL_OR_AMBIGUOUS_SUPPORT,
        SemanticSupport.UNSUPPORTED: SemanticRationaleCode.NO_SUPPORT,
    }[predicted]
    candidate = SemanticEvaluationCandidate(
        schema_version="m3.semantic-evaluation.result.v1",
        result=predicted,
        rationale_codes=(code,),
        explanation="Bounded calibration output.",
        human_review_required=predicted is SemanticSupport.UNCERTAIN,
    )
    result = build_deepseek_semantic_evaluation_result(request, candidate)
    structured = canonical_json(BaseModel.model_dump(candidate, mode="json")).encode()
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
        "instructions": SEMANTIC_EVALUATION_PROMPT_BYTES.decode(),
        "max_output_tokens": 4096,
        "reasoning": {"effort": "high"},
        "text": {"format": deepseek_response_format()},
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
    provider_request = deepseek_provider_request_bytes(request)
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
    assessment = DeepSeekSemanticAssessment(
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
    assert configuration["model"] == "deepseek-v4-pro"
    assert configuration["human_resolution_identity"] == OWNER_RESOLUTION_IDENTITY
    assert configuration["tools"] == []
    assert configuration["web_search_enabled"] is False
    assert configuration["code_revision"] == CODE_REVISION
    assert configuration["implementation_manifest_hash"] == MANIFEST_HASH
    assert configuration["case_inventory_identity"].startswith("sha256:")
    assert configuration["frozen_category_counts"]["applicable_contradiction"] == 8


def test_artifact_reparses_every_byte_surface_and_rejects_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _cases()
    _freeze_test_inventory(monkeypatch, observations)
    artifact = build_calibration_artifact(
        observations,
        completed_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    validate_calibration_artifact(
        artifact,
        code_revision=CODE_REVISION,
        implementation_manifest_hash=MANIFEST_HASH,
    )
    for field, value, match in (
        ("evaluator_input_hash", "sha256:" + "0" * 64, "provider request drift"),
        ("structured_output_hex", "00", "provider response drift"),
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
            )

    changed_code = deepcopy(artifact)
    changed_code["configuration"]["code_revision"] = "c" * 40
    _rebind_artifact(changed_code)
    with pytest.raises(DeepSeekCalibrationError, match="boundary drift"):
        validate_calibration_artifact(
            changed_code,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
        )

    changed_manifest = deepcopy(artifact)
    changed_manifest["configuration"]["implementation_manifest_hash"] = "sha256:" + "c" * 64
    _rebind_artifact(changed_manifest)
    with pytest.raises(DeepSeekCalibrationError, match="boundary drift"):
        validate_calibration_artifact(
            changed_manifest,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
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
    with pytest.raises(DeepSeekCalibrationError, match="duplicate provider response"):
        validate_calibration_artifact(
            duplicate_response,
            code_revision=CODE_REVISION,
            implementation_manifest_hash=MANIFEST_HASH,
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
        )
    assert not output.exists()
    assert not (tmp_path / ".external-result.pending").exists()
