from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
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
    begin_pending_calibration_run,
    build_calibration_artifact,
    calibration_configuration,
    persist_provider_event_projection,
    provider_attempt_run_id,
    provider_event_projection,
    publish_successful_calibration_run,
    reconcile_case_evidence,
    validate_authoritative_provider_events,
    validate_calibration_artifact,
    validate_provider_event_projection,
    verify_external_run,
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
from medevidence.persistence import ProviderAttemptEvent, make_provider_attempt_event
from medevidence.tools.report_validation import SemanticSupport
from medevidence.tools.semantic_evaluation import (
    DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
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


class _StaticLedger:
    def __init__(self, events: tuple[ProviderAttemptEvent, ...]) -> None:
        self.events = events

    def list_events(self, provider_run_id: str) -> tuple[ProviderAttemptEvent, ...]:
        return tuple(item for item in self.events if item.provider_run_id == provider_run_id)


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
            configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
            request_hash=observations[ordinal - 1].assessment.provider_request_hash,
            started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
            body_complete=True,
            body_byte_count=len(raw),
            body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
            body_relative_path=f"raw/case-{ordinal:03d}.bin",
            observed_body_bytes_lower_bound=len(raw),
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
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
        body_complete=True,
        body_byte_count=len(raw),
        body_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        body_relative_path=relative,
        observed_body_bytes_lower_bound=len(raw),
        approved_header_names=("content-type",),
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
        raw_root=tmp_path,
    )
    path.write_bytes(b"tampered")
    with pytest.raises(DeepSeekCalibrationError, match="raw provider body differs"):
        validate_provider_event_projection(
            projection,
            (start, terminal),
            frozen_cases=(source.case,),
            expected_provider_run_id=start.provider_run_id,
            raw_root=tmp_path,
        )


def test_projection_rejects_terminal_only_and_dual_closure() -> None:
    source = _cases()[0]
    start = make_provider_attempt_event(
        provider_run_id="provider-attempt-run:sha256:" + "a" * 64,
        case_id="M3-008B-CAL-001",
        case_ordinal=1,
        attempt_ordinal=1,
        event_kind="START",
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash="sha256:" + "0" * 64,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
        configuration_hash=DEEPSEEK_SEMANTIC_EVALUATION_CONFIGURATION_HASH,
        request_hash=source.assessment.provider_request_hash,
        started_at_utc=datetime(2026, 8, 31, tzinfo=UTC),
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
    )
    foreign_terminal = replace(terminal, configuration_hash="sha256:" + "0" * 64)
    with pytest.raises(DeepSeekCalibrationError, match="frozen authority"):
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

    configuration_path = output / "run-configuration.json"
    original_configuration = configuration_path.read_bytes()
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
