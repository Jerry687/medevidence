"""V2 Stage-1 receipt and semantic composition helpers."""

# ruff: noqa: E501, E701, I001, RUF021
# fmt: off
from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

from medevidence.domain import canonical_json, derive_identity, sha256_digest

from .report_validation import (
    CanonicalReportRequest, CanonicalValidationError, CitationInput, CitationRelationship,
    CitationTrace,
    ClaimInput,
    ComparisonInput, ConflictInput, ConflictOutcome, EvidenceInput,
    M3_SEMANTIC_EVALUATION_V2, M3_STAGE2_SEMANTIC_CONTRACT_HASH_V2,
    M3_STAGE2_SEMANTIC_CONTRACT_VERSION_V2,
    M3_STAGE2_SEMANTIC_RESULT_V2,
    M3_STAGE2_SEMANTIC_ROUTING_MATRIX_HASH_V2,
    M3_VALIDATION_CONFIGURATION_V2, M3_VALIDATION_CONFIGURATION_V3, M3_VALIDATION_CONFIGURATION_V4,
    _semantic_v2_validation_profile,
    PlannedStage2SemanticInputV2, ReviewRoutingDispositionInput,
    ResolutionAction, ResolutionInput, ResolutionInputV2,
    ResolutionSemanticBindingInput,
    SemanticEvaluationInput, SemanticSupport, Stage1ReceiptV2,
    Stage2SemanticInputV2, Stage2SemanticResultV2, ValidationCitationReceiptV2,
    ValidationClaimReceiptV2,
    ValidationReceiptV2,
    canonical_semantic_input_digest,
    _bounded_tuple, _copy_resolution_binding_v2, _digest, _exact, _primitive,
    _reason_tuple, _receipt_content_v2, _resolution_binding_from_stage2,
    _stage1_registry_v2_payload, _stage1_validation_input_hash_v2, _task_bindings, _text,
)
from .report_validation_v3 import provider_method_for_pair, provider_method_for_validation_configuration

if TYPE_CHECKING:
    from .semantic_evaluation import SemanticEvaluationRequest

def canonical_stage2_semantic_input_v2(value: Stage2SemanticResultV2, *, report_request: CanonicalReportRequest, current_input: SemanticEvaluationInput, stage1_result_id: str, stage1_claim_result_id: str, method: str) -> Stage2SemanticInputV2:
    """Reconstruct and project exact V2 semantic and routing authority for validation."""
    _exact(value, Stage2SemanticResultV2, "semantic_v2_result_wrapper_wrong_type")
    current = _exact(current_input, SemanticEvaluationInput, "semantic_input_wrong_type")
    report = _exact(report_request, CanonicalReportRequest, "request_wrong_type")
    if len(report.registry.comparisons) > 1 or len(report.registry.conflicts) > 1:
        raise CanonicalValidationError("semantic_v2_comparability_registry_ambiguous")
    stage1_result_id = _text(stage1_result_id, "semantic_v2_stage1_result_id_invalid")
    stage1_claim_result_id = _text(stage1_claim_result_id, "semantic_v2_stage1_claim_result_id_invalid")
    method = _text(method, "semantic_v2_method_invalid")
    try:
        from .semantic_evaluation import (
            REVIEW_ROUTING_POLICY_HASH,
            REVIEW_ROUTING_POLICY_VERSION,
            ReviewRoutingDispositionKind,
            SemanticEvaluationRequest,
            SemanticEvaluationResultV2,
            reconstruct_semantic_evaluation_result_v2,
        )
        request = _exact(value.semantic_request, SemanticEvaluationRequest, "semantic_v2_request_wrong_type")
        result = reconstruct_semantic_evaluation_result_v2(
            request,
            _exact(value.semantic_result, SemanticEvaluationResultV2, "semantic_v2_result_wrong_type"),
        )
        _, neutral_hash, provider_version, provider_hash = _semantic_v2_validation_profile(
            report.registry.configuration_version
        )
        if (
            result.configuration_hash,
            result.provider_configuration_version,
            result.provider_configuration_hash,
        ) != (neutral_hash, provider_version, provider_hash):
            raise CanonicalValidationError("semantic_v2_provider_profile_mismatch")
        admitted_input = request.stage1_admission.semantic_input
        if admitted_input != current or result.input_digest != canonical_semantic_input_digest(current.run_id, current.claim, current.citation, current.evidence):
            raise CanonicalValidationError("semantic_v2_request_binding_drift")
        admission = request.stage1_admission
        task = next((item for item in report.tasks if item.source is current.evidence.source), None)
        if task is None or (
            admission.run_id,
            admission.scope_id,
            admission.report_id,
            admission.validation_input_hash,
            admission.registry_binding_hash,
            admission.task_binding_hash,
            admission.source_task_id,
            admission.source_outcome_id,
            admission.source_outcome_binding_hash,
            admission.stage1_result_id,
            admission.stage1_claim_result_id,
            admission.report_content_hash,
        ) != (
            report.run_id,
            report.scope.scope_id,
            report.report_id,
            _stage1_validation_input_hash_v2(report),
            sha256_digest(canonical_json(_primitive(_stage1_registry_v2_payload(report.registry)))),
            sha256_digest(canonical_json(_primitive(_task_bindings(report.tasks)))),
            task.task_id,
            task.acquisition.source_outcome_id,
            sha256_digest(canonical_json(_primitive(task.outcome))),
            stage1_result_id,
            stage1_claim_result_id,
            report.synthesis.report_content_hash,
        ):
            raise CanonicalValidationError("semantic_v2_stage1_admission_binding_drift")
        metadata = request.comparability
        if not metadata.registry_empty and (metadata.comparison not in report.registry.comparisons or metadata.conflict not in report.registry.conflicts):
            raise CanonicalValidationError("semantic_v2_comparability_binding_drift")
        routing = result.routing_disposition
        if routing.routing_policy_version != REVIEW_ROUTING_POLICY_VERSION or routing.routing_policy_hash != REVIEW_ROUTING_POLICY_HASH:
            raise CanonicalValidationError("semantic_v2_routing_policy_drift")
        disposition = ReviewRoutingDispositionInput(routing.disposition.value)
        if routing.disposition is ReviewRoutingDispositionKind.FORMAL_CITATION_REJECTED and result.result is not SemanticSupport.UNSUPPORTED:
            raise CanonicalValidationError("semantic_v2_routing_binding_drift")
        if method != result.method:
            raise CanonicalValidationError("semantic_v2_provider_method_drift")
        comparison, conflict = metadata.comparison, metadata.conflict
        return _copy_stage2_v2(Stage2SemanticInputV2(citation_id=current.citation.citation_id, input_digest=result.input_digest, semantic_contract_version=result.semantic_contract_version, semantic_contract_hash=result.semantic_contract_hash, method=result.method, version=result.version, semantic_configuration_hash=result.configuration_hash, provider_configuration_version=result.provider_configuration_version, provider_configuration_hash=result.provider_configuration_hash, result=result.result, semantic_result_content_hash=result.semantic_result_content_hash, semantic_result_hash=result.content_hash, routing_policy_version=routing.routing_policy_version, routing_policy_hash=routing.routing_policy_hash, routing_matrix_hash=M3_STAGE2_SEMANTIC_ROUTING_MATRIX_HASH_V2, routing_disposition=disposition, human_review_required=routing.human_review_required, routing_disposition_content_hash=routing.content_hash, comparability_registry_empty=metadata.registry_empty, comparison_id=None if comparison is None else comparison.comparison_id, comparison_hash=None if comparison is None else comparison.artifact_hash, conflict_id=None if conflict is None else conflict.conflict_id, conflict_hash=None if conflict is None else conflict.artifact_hash, conflict_outcome=None if conflict is None else conflict.outcome))
    except CanonicalValidationError:
        raise
    except Exception as error:
        raise CanonicalValidationError("semantic_v2_result_reconstruction_failed") from error

def _planned_semantic_request_v2(report: CanonicalReportRequest, receipt: Stage1ReceiptV2, claim: ClaimInput, current: SemanticEvaluationInput) -> SemanticEvaluationRequest:
    """Compose provider input exclusively from admitted application-owned evidence."""
    try:
        from .semantic_evaluation import (
            build_canonical_citation_stage1_binding,
            build_canonical_stage1_admission,
            build_comparability_metadata,
            build_empty_comparability_metadata,
            build_formal_claim_citation_topology,
            build_semantic_evaluation_request,
        )
        plans = {item.citation_id: item for item in report.registry.semantic_expectations if type(item) is PlannedStage2SemanticInputV2}
        claim_map = {item.claim_id: item for item in report.registry.claims}
        evidence_map = {item.evidence_id: item for item in report.registry.evidence}
        task_map = {item.source: item for item in report.tasks}
        claim_result_ids = dict(receipt.claim_result_ids)
        ordered_inputs = tuple(SemanticEvaluationInput(report.run_id, claim_map[citation.claim_id], citation, evidence_map[citation.evidence_id]) for citation in report.registry.citations if citation.claim_id == claim.claim_id)
        ordered_bindings = []
        for item in ordered_inputs:
            task = task_map[item.evidence.source]
            ordered_bindings.append(build_canonical_citation_stage1_binding(
                stage1_passed=True,
                validation_receipt_id=receipt.receipt_id,
                validation_receipt_content_hash=receipt.receipt_content_hash,
                registry_binding_hash=receipt.registry_binding_hash,
                source_task_id=task.task_id,
                task_binding_hash=receipt.task_binding_hash,
                source_outcome_id=task.acquisition.source_outcome_id,
                source_outcome_binding_hash=sha256_digest(canonical_json(_primitive(task.outcome))),
                stage1_result_id=receipt.stage1_result_id,
                stage1_claim_result_id=claim_result_ids[claim.claim_id],
            ))
        topology = build_formal_claim_citation_topology(run_id=report.run_id, claim=claim, ordered_semantic_inputs=ordered_inputs, ordered_stage1_bindings=tuple(ordered_bindings), current_citation_id=current.citation.citation_id)
        plan = plans[current.citation.citation_id]
        if (plan.comparison_id is None) != (plan.conflict_id is None):
            raise CanonicalValidationError("semantic_v2_plan_comparability_pair_incomplete")
        if plan.comparison_id is None:
            if report.registry.comparisons or report.registry.conflicts:
                raise CanonicalValidationError("semantic_v2_plan_comparability_omission_ambiguous")
            metadata = build_empty_comparability_metadata(run_id=report.run_id)
        else:
            comparisons = tuple(item for item in report.registry.comparisons if item.comparison_id == plan.comparison_id)
            conflicts = tuple(item for item in report.registry.conflicts if item.conflict_id == plan.conflict_id)
            if len(comparisons) != 1 or len(conflicts) != 1 or conflicts[0].comparison_id != comparisons[0].comparison_id:
                raise CanonicalValidationError("semantic_v2_plan_comparability_pair_invalid")
            comparison, conflict = comparisons[0], conflicts[0]
            metadata = build_comparability_metadata(run_id=report.run_id, comparison=comparison, conflict=conflict)
        task = task_map[current.evidence.source]
        admission = build_canonical_stage1_admission(
            stage1_passed=True,
            semantic_input=current,
            formal_citation_topology=topology,
            comparability=metadata,
            scope_id=report.scope.scope_id,
            report_id=report.report_id,
            validation_receipt_id=receipt.receipt_id,
            validation_receipt_content_hash=receipt.receipt_content_hash,
            validation_input_hash=receipt.validation_input_hash,
            registry_binding_hash=receipt.registry_binding_hash,
            task_binding_hash=receipt.task_binding_hash,
            source_outcome_id=task.acquisition.source_outcome_id,
            source_outcome_binding_hash=sha256_digest(canonical_json(_primitive(task.outcome))),
            stage1_result_id=receipt.stage1_result_id,
            stage1_claim_result_id=claim_result_ids[claim.claim_id],
            report_content_hash=receipt.report_content_hash,
        )
        return build_semantic_evaluation_request(admission, comparability=metadata)
    except CanonicalValidationError:
        raise
    except Exception as error:
        raise CanonicalValidationError("semantic_v2_request_composition_failed") from error

def _build_stage1_receipt_v2(request: CanonicalReportRequest, stage1: tuple[tuple[ClaimInput, tuple[tuple[CitationInput, EvidenceInput], ...], tuple[str, ...]], ...]) -> Stage1ReceiptV2:
    if any(reasons for _, _, reasons in stage1):
        raise CanonicalValidationError("stage1_receipt_requires_pass")
    policy_version = _semantic_v2_validation_profile(request.registry.configuration_version)[0]
    claim_results = tuple((claim.claim_id, derive_identity("validation-stage1-claim-result", _primitive((claim.claim_id, True, ())))) for claim, _, _ in stage1)
    stage1_result_id = derive_identity("validation-stage1-result", _primitive(tuple((claim.claim_id, True, ()) for claim, _, _ in stage1)))
    content = {
        "marker": "M3_STAGE1_VALIDATION_RECEIPT_V2",
        "stage1_passed": True,
        "run_id": request.run_id,
        "scope_id": request.scope.scope_id,
        "report_id": request.report_id,
        "report_content_hash": request.synthesis.report_content_hash,
        "validation_input_hash": _stage1_validation_input_hash_v2(request),
        "registry_binding_hash": sha256_digest(canonical_json(_primitive(_stage1_registry_v2_payload(request.registry)))),
        "task_binding_hash": sha256_digest(canonical_json(_primitive(_task_bindings(request.tasks)))),
        "stage1_result_id": stage1_result_id,
        "claim_result_ids": claim_results,
        "citation_ids": tuple(citation.citation_id for _, pairs, _ in stage1 for citation, _ in pairs),
        "policy_version": policy_version,
        "configuration_version": request.registry.configuration_version,
    }
    return Stage1ReceiptV2(
        marker="M3_STAGE1_VALIDATION_RECEIPT_V2",
        stage1_passed=True,
        receipt_id=derive_identity("validation-stage1-receipt-v2", content),
        receipt_content_hash=sha256_digest(canonical_json(content)),
        run_id=request.run_id,
        scope_id=request.scope.scope_id,
        report_id=request.report_id,
        report_content_hash=request.synthesis.report_content_hash,
        validation_input_hash=_stage1_validation_input_hash_v2(request),
        registry_binding_hash=sha256_digest(canonical_json(_primitive(_stage1_registry_v2_payload(request.registry)))),
        task_binding_hash=sha256_digest(canonical_json(_primitive(_task_bindings(request.tasks)))),
        stage1_result_id=stage1_result_id,
        claim_result_ids=claim_results,
        citation_ids=tuple(citation.citation_id for _, pairs, _ in stage1 for citation, _ in pairs),
        policy_version=policy_version,
        configuration_version=request.registry.configuration_version,
    )

def canonical_stage1_receipt_payload_v2(value: Stage1ReceiptV2) -> dict[str, object]:
    """Serialize one independently identifiable Stage-1 result for a typed store."""
    receipt = _exact(value, Stage1ReceiptV2, "stage1_receipt_wrong_type")
    if receipt.stage1_passed is not True:
        raise CanonicalValidationError("stage1_receipt_pass_drift")
    if receipt.policy_version != _semantic_v2_validation_profile(receipt.configuration_version)[0]:
        raise CanonicalValidationError("stage1_receipt_policy_drift")
    content = {item.name: _primitive(getattr(receipt, item.name)) for item in fields(receipt) if item.name not in {"receipt_id", "receipt_content_hash"}}
    if receipt.receipt_id != derive_identity("validation-stage1-receipt-v2", content) or receipt.receipt_content_hash != sha256_digest(canonical_json(content)):
        raise CanonicalValidationError("stage1_receipt_identity_drift")
    return {"receipt_id": receipt.receipt_id, "receipt_content_hash": receipt.receipt_content_hash, **content}

def stage1_receipt_from_payload_v2(value: object) -> Stage1ReceiptV2:
    """Reparse an untrusted Stage-1 store response with exact keys and identity."""
    if type(value) is not dict or set(value) != {item.name for item in fields(Stage1ReceiptV2)}:
        raise CanonicalValidationError("stage1_receipt_payload_keys_invalid")
    raw = value
    claim_rows_raw, citation_rows_raw = raw["claim_result_ids"], raw["citation_ids"]
    if type(claim_rows_raw) not in (tuple, list) or type(citation_rows_raw) not in (tuple, list):
        raise CanonicalValidationError("stage1_receipt_collection_wrong_type")
    claim_rows, citation_rows = tuple(claim_rows_raw), tuple(citation_rows_raw)
    _bounded_tuple(claim_rows, 200, "stage1_receipt_claim_cardinality_exceeded")
    _bounded_tuple(citation_rows, 400, "stage1_receipt_citation_cardinality_exceeded")
    claims_list: list[tuple[str, str]] = []
    for item in claim_rows:
        if type(item) not in (tuple, list) or len(item) != 2:
            raise CanonicalValidationError("stage1_receipt_claim_invalid")
        claims_list.append((_text(item[0], "stage1_receipt_claim_invalid"), _text(item[1], "stage1_receipt_claim_result_invalid")))
    claims = tuple(claims_list)
    receipt = Stage1ReceiptV2(
        marker=_text(raw["marker"], "stage1_receipt_marker_invalid"),
        stage1_passed=_exact(raw["stage1_passed"], bool, "stage1_receipt_pass_invalid"),
        receipt_id=_text(raw["receipt_id"], "stage1_receipt_id_invalid"),
        receipt_content_hash=_digest(raw["receipt_content_hash"], "stage1_receipt_content_hash_invalid"),
        run_id=_text(raw["run_id"], "stage1_receipt_run_invalid"),
        scope_id=_text(raw["scope_id"], "stage1_receipt_scope_invalid"),
        report_id=_text(raw["report_id"], "stage1_receipt_report_invalid"),
        report_content_hash=_digest(raw["report_content_hash"], "stage1_receipt_report_hash_invalid"),
        validation_input_hash=_digest(raw["validation_input_hash"], "stage1_receipt_input_hash_invalid"),
        registry_binding_hash=_digest(raw["registry_binding_hash"], "stage1_receipt_registry_hash_invalid"),
        task_binding_hash=_digest(raw["task_binding_hash"], "stage1_receipt_task_hash_invalid"),
        stage1_result_id=_text(raw["stage1_result_id"], "stage1_receipt_stage1_id_invalid"),
        claim_result_ids=claims,
        citation_ids=tuple(_text(item, "stage1_receipt_citation_invalid") for item in citation_rows),
        policy_version=_text(raw["policy_version"], "stage1_receipt_policy_invalid"),
        configuration_version=_text(raw["configuration_version"], "stage1_receipt_configuration_invalid"),
    )
    if receipt.marker != "M3_STAGE1_VALIDATION_RECEIPT_V2" or receipt.stage1_passed is not True or receipt.policy_version != _semantic_v2_validation_profile(receipt.configuration_version)[0]:
        raise CanonicalValidationError("stage1_receipt_policy_drift")
    canonical_stage1_receipt_payload_v2(receipt)
    return receipt
def stage2_projections_from_receipt_v2(value: ValidationReceiptV2) -> tuple[Stage2SemanticInputV2, ...]:
    """Reconstruct completed V2 projections from a canonical saved receipt."""
    receipt = _copy_validation_receipt_v2(value, value)
    rows: list[Stage2SemanticInputV2] = []
    for claim in receipt.claim_results:
        for citation in claim.citation_results:
            rows.append(_copy_stage2_v2(Stage2SemanticInputV2(
                citation_id=citation.citation_id,
                input_digest=citation.input_digest,
                semantic_contract_version=citation.semantic_contract_version,
                semantic_contract_hash=citation.semantic_contract_hash,
                method=citation.method,
                version=citation.version,
                semantic_configuration_hash=citation.semantic_configuration_hash,
                provider_configuration_version=citation.provider_configuration_version,
                provider_configuration_hash=citation.provider_configuration_hash,
                result=citation.result,
                semantic_result_content_hash=citation.semantic_result_content_hash,
                semantic_result_hash=citation.semantic_result_hash,
                routing_policy_version=citation.routing_policy_version,
                routing_policy_hash=citation.routing_policy_hash,
                routing_matrix_hash=citation.routing_matrix_hash,
                routing_disposition=citation.routing_disposition,
                human_review_required=citation.human_review_required,
                routing_disposition_content_hash=citation.routing_disposition_content_hash,
                comparability_registry_empty=citation.comparability_registry_empty,
                comparison_id=citation.comparison_id,
                comparison_hash=citation.comparison_hash,
                conflict_id=citation.conflict_id,
                conflict_hash=citation.conflict_hash,
                conflict_outcome=citation.conflict_outcome,
            )))
    if len({item.citation_id for item in rows}) != len(rows):
        raise CanonicalValidationError("semantic_v2_receipt_projection_duplicate")
    return tuple(rows)


def _copy_validation_receipt_v2(value: ValidationReceiptV2, expected: ValidationReceiptV2) -> ValidationReceiptV2:
    _exact(value, ValidationReceiptV2, "validation_receipt_v2_wrong_type")
    if value.configuration_version != expected.configuration_version:
        raise CanonicalValidationError("validation_receipt_v2_configuration_mismatch")
    policy_version, neutral_hash, provider_version, provider_hash = (
        _semantic_v2_validation_profile(value.configuration_version)
    )
    if value.policy_version != policy_version or expected.policy_version != policy_version:
        raise CanonicalValidationError("validation_receipt_policy_drift")
    if type(value.reason_codes) is not tuple or len(value.reason_codes) != len(expected.reason_codes):
        raise CanonicalValidationError("validation_receipt_summary_reason_cardinality_mismatch")
    if type(value.claim_results) is not tuple or len(value.claim_results) != len(expected.claim_results):
        raise CanonicalValidationError("validation_receipt_claim_cardinality_mismatch")
    claims: list[ValidationClaimReceiptV2] = []
    for raw_claim, expected_claim in zip(value.claim_results, expected.claim_results, strict=True):
        claim = _exact(raw_claim, ValidationClaimReceiptV2, "validation_receipt_v2_claim_wrong_type")
        if type(claim.stage1_reason_codes) is not tuple or len(claim.stage1_reason_codes) != len(expected_claim.stage1_reason_codes):
            raise CanonicalValidationError("validation_receipt_reason_cardinality_mismatch")
        if type(claim.citation_results) is not tuple or len(claim.citation_results) != len(expected_claim.citation_results):
            raise CanonicalValidationError("validation_receipt_citation_cardinality_mismatch")
        citations: list[ValidationCitationReceiptV2] = []
        for raw_citation in claim.citation_results:
            item = _exact(raw_citation, ValidationCitationReceiptV2, "validation_receipt_v2_citation_wrong_type")
            copied = ValidationCitationReceiptV2(
                _text(item.citation_result_id, "validation_receipt_citation_identity_invalid"),
                _text(item.citation_id, "validation_receipt_citation_id_invalid"),
                _digest(item.input_digest, "validation_receipt_input_digest_invalid"),
                _text(item.method, "validation_receipt_method_invalid"),
                _text(item.version, "validation_receipt_version_invalid"),
                _text(item.semantic_contract_version, "validation_receipt_v2_contract_version_invalid"),
                _digest(item.semantic_contract_hash, "validation_receipt_v2_contract_hash_invalid"),
                _digest(item.semantic_configuration_hash, "validation_receipt_v2_configuration_hash_invalid"),
                _text(item.provider_configuration_version, "validation_receipt_v2_provider_configuration_version_invalid"),
                _digest(item.provider_configuration_hash, "validation_receipt_v2_provider_configuration_hash_invalid"),
                _exact(item.result, SemanticSupport, "validation_receipt_result_invalid"),
                _exact(item.relationship, CitationRelationship, "validation_receipt_relationship_invalid"),
                _digest(item.semantic_result_content_hash, "validation_receipt_v2_result_content_hash_invalid"),
                _digest(item.semantic_result_hash, "validation_receipt_v2_result_hash_invalid"),
                _text(item.routing_policy_version, "validation_receipt_v2_routing_policy_version_invalid"),
                _digest(item.routing_policy_hash, "validation_receipt_v2_routing_policy_hash_invalid"),
                _digest(item.routing_matrix_hash, "validation_receipt_v2_routing_matrix_hash_invalid"),
                _exact(item.routing_disposition, ReviewRoutingDispositionInput, "validation_receipt_v2_routing_disposition_invalid"),
                _exact(item.human_review_required, bool, "validation_receipt_v2_human_review_invalid"),
                _digest(item.routing_disposition_content_hash, "validation_receipt_v2_disposition_hash_invalid"),
                _exact(item.comparability_registry_empty, bool, "validation_receipt_v2_comparability_empty_wrong_type"),
                None if item.comparison_id is None else _text(item.comparison_id, "validation_receipt_v2_comparison_id_invalid"),
                None if item.comparison_hash is None else _digest(item.comparison_hash, "validation_receipt_v2_comparison_hash_invalid"),
                None if item.conflict_id is None else _text(item.conflict_id, "validation_receipt_v2_conflict_id_invalid"),
                None if item.conflict_hash is None else _digest(item.conflict_hash, "validation_receipt_v2_conflict_hash_invalid"),
                None if item.conflict_outcome is None else _exact(item.conflict_outcome, ConflictOutcome, "validation_receipt_v2_conflict_outcome_wrong_type"),
            )
            if copied.human_review_required is not (copied.routing_disposition is ReviewRoutingDispositionInput.HUMAN_REVIEW_REQUIRED):
                raise CanonicalValidationError("validation_receipt_v2_routing_boolean_drift")
            _validate_routing_disposition_v2(copied)
            if (
                copied.semantic_contract_version,
                copied.semantic_contract_hash,
                copied.method,
                copied.semantic_configuration_hash,
                copied.provider_configuration_version,
                copied.provider_configuration_hash,
                copied.routing_matrix_hash,
            ) != (
                M3_STAGE2_SEMANTIC_CONTRACT_VERSION_V2,
                M3_STAGE2_SEMANTIC_CONTRACT_HASH_V2,
                provider_method_for_validation_configuration(value.configuration_version),
                neutral_hash,
                provider_version,
                provider_hash,
                M3_STAGE2_SEMANTIC_ROUTING_MATRIX_HASH_V2,
            ):
                raise CanonicalValidationError("validation_receipt_v2_provenance_drift")
            participation = (copied.comparison_id, copied.comparison_hash, copied.conflict_id, copied.conflict_hash, copied.conflict_outcome)
            if copied.comparability_registry_empty != all(value is None for value in participation) or not copied.comparability_registry_empty and any(value is None for value in participation): raise CanonicalValidationError("validation_receipt_v2_comparability_participation_invalid")
            payload: dict[str, object] = {field.name: getattr(copied, field.name) for field in fields(ValidationCitationReceiptV2) if field.name != "citation_result_id"}
            if copied.citation_result_id != derive_identity("validation-citation-result-v2", _primitive(payload)):
                raise CanonicalValidationError("validation_receipt_citation_identity_drift")
            citations.append(copied)
        raw_bindings = claim.resolution_semantic_bindings
        _bounded_tuple(raw_bindings, 400, "validation_receipt_v2_resolution_binding_cardinality_exceeded", type_code="validation_receipt_v2_resolution_bindings_wrong_type")
        bindings = tuple(_copy_resolution_binding_v2(item) for item in raw_bindings)
        if any((item.semantic_configuration_hash, item.provider_configuration_version, item.provider_configuration_hash) != (neutral_hash, provider_version, provider_hash) for item in bindings):
            raise CanonicalValidationError("validation_receipt_v2_resolution_profile_mismatch")
        resolution = None if claim.resolution_action is None else _exact(claim.resolution_action, ResolutionAction, "validation_receipt_resolution_invalid")
        resolution_values = (claim.resolution_record_id, claim.resolution_method, claim.resolution_version)
        if resolution is None and (any(item is not None for item in resolution_values) or bindings) or resolution is not None and any(item is None for item in resolution_values):
            raise CanonicalValidationError("validation_receipt_resolution_binding_invalid")
        copied_resolution = tuple(None if item is None else _text(item, "validation_receipt_resolution_text_invalid") for item in resolution_values)
        if resolution is ResolutionAction.ADJUDICATED_TO_SUPPORTED and (copied_resolution[1] != "human_review" or not bindings):
            raise CanonicalValidationError("validation_receipt_v2_resolution_binding_invalid")
        if resolution is ResolutionAction.REMOVED and bindings:
            raise CanonicalValidationError("validation_receipt_v2_removed_binding_forbidden")
        governed_values = (claim.comparison_id, claim.conflict_id)
        copied_governed = tuple(None if item is None else _text(item, "validation_receipt_governed_id_invalid") for item in governed_values)
        if any(item is not None for item in copied_governed):
            raise CanonicalValidationError("validation_receipt_v2_legacy_comparability_forbidden")
        aggregate = None if claim.aggregate_result is None else _exact(claim.aggregate_result, SemanticSupport, "validation_receipt_aggregate_invalid")
        copied_claim = ValidationClaimReceiptV2(_text(claim.claim_result_id, "validation_receipt_claim_identity_invalid"), _text(claim.claim_id, "validation_receipt_claim_id_invalid"), _exact(claim.stage1_passed, bool, "validation_receipt_stage1_invalid"), _reason_tuple(claim.stage1_reason_codes, "validation_receipt_reason_invalid"), tuple(citations), aggregate, resolution, copied_resolution[0], copied_resolution[1], copied_resolution[2], bindings, copied_governed[0], copied_governed[1], _exact(claim.formal_claim_accepted, bool, "validation_receipt_acceptance_invalid"))
        payload = {field.name: getattr(copied_claim, field.name) for field in fields(ValidationClaimReceiptV2) if field.name != "claim_result_id"}
        if copied_claim.claim_result_id != derive_identity("validation-claim-result-v2", _primitive(payload)):
            raise CanonicalValidationError("validation_receipt_claim_identity_drift")
        claims.append(copied_claim)
    copied_receipt_v2 = ValidationReceiptV2(
        _text(value.marker, "validation_receipt_marker_invalid"),
        _text(value.receipt_id, "validation_receipt_identity_invalid"),
        _digest(value.receipt_content_hash, "validation_receipt_content_hash_invalid"),
        _text(value.run_id, "validation_receipt_run_invalid"),
        _text(value.report_id, "validation_receipt_report_invalid"),
        _digest(value.report_content_hash, "validation_receipt_report_hash_invalid"),
        _digest(value.validation_input_hash, "validation_receipt_input_hash_invalid"),
        _digest(value.task_binding_hash, "validation_receipt_task_hash_invalid"),
        _text(value.stage1_result_id, "validation_receipt_stage1_identity_invalid"),
        _text(value.evaluator_method, "validation_receipt_method_invalid"),
        _text(value.evaluator_version, "validation_receipt_version_invalid"),
        tuple(claims),
        _exact(value.structural_passed, bool, "validation_receipt_summary_invalid"),
        _exact(value.semantic_passed, bool, "validation_receipt_summary_invalid"),
        _exact(value.safety_passed, bool, "validation_receipt_summary_invalid"),
        _reason_tuple(value.reason_codes, "validation_receipt_summary_reason_invalid"),
        _text(value.policy_version, "validation_receipt_policy_invalid"),
        _text(value.configuration_version, "validation_receipt_configuration_invalid"),
        _text(value.semantic_contract, "validation_receipt_v2_semantic_contract_invalid"),
        _text(value.semantic_contract_version, "validation_receipt_v2_contract_version_invalid"),
        _digest(value.semantic_contract_hash, "validation_receipt_v2_contract_hash_invalid"),
        _digest(value.semantic_configuration_hash, "validation_receipt_v2_configuration_hash_invalid"),
        _text(value.provider_configuration_version, "validation_receipt_v2_provider_configuration_version_invalid"),
        _digest(value.provider_configuration_hash, "validation_receipt_v2_provider_configuration_hash_invalid"),
        _text(value.routing_policy_version, "validation_receipt_v2_routing_policy_version_invalid"),
        _digest(value.routing_policy_hash, "validation_receipt_v2_routing_policy_hash_invalid"),
        _digest(value.routing_matrix_hash, "validation_receipt_v2_routing_matrix_hash_invalid"),
    )
    from .semantic_evaluation import REVIEW_ROUTING_POLICY_HASH, REVIEW_ROUTING_POLICY_VERSION
    if (
        copied_receipt_v2.semantic_contract,
        copied_receipt_v2.semantic_contract_version,
        copied_receipt_v2.semantic_contract_hash,
        copied_receipt_v2.evaluator_method,
        copied_receipt_v2.semantic_configuration_hash,
        copied_receipt_v2.provider_configuration_version,
        copied_receipt_v2.provider_configuration_hash,
        copied_receipt_v2.routing_matrix_hash,
    ) != (
        M3_STAGE2_SEMANTIC_RESULT_V2,
        M3_STAGE2_SEMANTIC_CONTRACT_VERSION_V2,
        M3_STAGE2_SEMANTIC_CONTRACT_HASH_V2,
        provider_method_for_validation_configuration(value.configuration_version),
        neutral_hash,
        provider_version,
        provider_hash,
        M3_STAGE2_SEMANTIC_ROUTING_MATRIX_HASH_V2,
    ):
        raise CanonicalValidationError("validation_receipt_v2_provenance_drift")
    if copied_receipt_v2.routing_policy_version != REVIEW_ROUTING_POLICY_VERSION or copied_receipt_v2.routing_policy_hash != REVIEW_ROUTING_POLICY_HASH: raise CanonicalValidationError("validation_receipt_v2_routing_policy_drift")
    content = _receipt_content_v2(copied_receipt_v2)
    if copied_receipt_v2.receipt_content_hash != sha256_digest(canonical_json(content)):
        raise CanonicalValidationError("validation_receipt_content_hash_drift")
    if copied_receipt_v2.receipt_id != derive_identity("validation-receipt-v2", content):
        raise CanonicalValidationError("validation_receipt_identity_drift")
    return copied_receipt_v2

def _copy_stage2_v2(value: Stage2SemanticInputV2) -> Stage2SemanticInputV2:
    _exact(value, Stage2SemanticInputV2, "semantic_v2_input_wrong_type")
    copied = Stage2SemanticInputV2(
        citation_id=_text(value.citation_id, "semantic_v2_citation_invalid"), input_digest=_digest(value.input_digest, "semantic_v2_input_digest_invalid"), semantic_contract_version=_text(value.semantic_contract_version, "semantic_v2_contract_version_invalid"), semantic_contract_hash=_digest(value.semantic_contract_hash, "semantic_v2_contract_hash_invalid"), method=_text(value.method, "semantic_v2_method_invalid"), version=_text(value.version, "semantic_v2_version_invalid"), semantic_configuration_hash=_digest(value.semantic_configuration_hash, "semantic_v2_configuration_hash_invalid"), provider_configuration_version=_text(value.provider_configuration_version, "semantic_v2_provider_configuration_version_invalid"), provider_configuration_hash=_digest(value.provider_configuration_hash, "semantic_v2_provider_configuration_hash_invalid"), result=_exact(value.result, SemanticSupport, "semantic_v2_result_wrong_type"), semantic_result_content_hash=_digest(value.semantic_result_content_hash, "semantic_v2_result_content_hash_invalid"), semantic_result_hash=_digest(value.semantic_result_hash, "semantic_v2_result_hash_invalid"), routing_policy_version=_text(value.routing_policy_version, "semantic_v2_routing_policy_version_invalid"), routing_policy_hash=_digest(value.routing_policy_hash, "semantic_v2_routing_policy_hash_invalid"), routing_matrix_hash=_digest(value.routing_matrix_hash, "semantic_v2_routing_matrix_hash_invalid"), routing_disposition=_exact(value.routing_disposition, ReviewRoutingDispositionInput, "semantic_v2_routing_disposition_wrong_type"), human_review_required=_exact(value.human_review_required, bool, "semantic_v2_human_review_wrong_type"), routing_disposition_content_hash=_digest(value.routing_disposition_content_hash, "semantic_v2_routing_disposition_hash_invalid"), comparability_registry_empty=_exact(value.comparability_registry_empty, bool, "semantic_v2_comparability_empty_wrong_type"), comparison_id=None if value.comparison_id is None else _text(value.comparison_id, "semantic_v2_comparison_id_invalid"), comparison_hash=None if value.comparison_hash is None else _digest(value.comparison_hash, "semantic_v2_comparison_hash_invalid"), conflict_id=None if value.conflict_id is None else _text(value.conflict_id, "semantic_v2_conflict_id_invalid"), conflict_hash=None if value.conflict_hash is None else _digest(value.conflict_hash, "semantic_v2_conflict_hash_invalid"), conflict_outcome=None if value.conflict_outcome is None else _exact(value.conflict_outcome, ConflictOutcome, "semantic_v2_conflict_outcome_wrong_type"),
    )
    common = (
        copied.semantic_contract_version,
        copied.semantic_contract_hash,
        copied.method,
        copied.version,
        copied.routing_matrix_hash,
    )
    if common != (
        M3_STAGE2_SEMANTIC_CONTRACT_VERSION_V2,
        M3_STAGE2_SEMANTIC_CONTRACT_HASH_V2,
        provider_method_for_pair(copied.provider_configuration_version, copied.provider_configuration_hash),
        M3_SEMANTIC_EVALUATION_V2,
        M3_STAGE2_SEMANTIC_ROUTING_MATRIX_HASH_V2,
    ) or (
        copied.semantic_configuration_hash,
        copied.provider_configuration_version,
        copied.provider_configuration_hash,
    ) not in {
        _semantic_v2_validation_profile(version)[1:]
        for version in (M3_VALIDATION_CONFIGURATION_V2, M3_VALIDATION_CONFIGURATION_V3, M3_VALIDATION_CONFIGURATION_V4)
    }:
        raise CanonicalValidationError("semantic_v2_provenance_invalid")
    participation = (copied.comparison_id, copied.comparison_hash, copied.conflict_id, copied.conflict_hash, copied.conflict_outcome)
    if copied.comparability_registry_empty != all(item is None for item in participation) or not copied.comparability_registry_empty and any(item is None for item in participation): raise CanonicalValidationError("semantic_v2_comparability_participation_invalid")
    if copied.human_review_required is not (copied.routing_disposition is ReviewRoutingDispositionInput.HUMAN_REVIEW_REQUIRED):
        raise CanonicalValidationError("semantic_v2_routing_boolean_drift")
    _validate_routing_disposition_v2(copied)
    return copied


def _validate_routing_disposition_v2(value: Stage2SemanticInputV2 | ValidationCitationReceiptV2) -> None:
    try:
        from .semantic_evaluation import ReviewRoutingDisposition, ReviewRoutingDispositionKind
        ReviewRoutingDisposition(routing_policy_version="m3.semantic-review-routing.policy.v1", routing_policy_hash=value.routing_policy_hash, input_digest=value.input_digest, semantic_result_content_hash=value.semantic_result_content_hash, disposition=ReviewRoutingDispositionKind(value.routing_disposition.value), human_review_required=value.human_review_required, content_hash=value.routing_disposition_content_hash)
    except Exception as error:
        raise CanonicalValidationError("semantic_v2_routing_binding_drift") from error
    if value.result is SemanticSupport.UNSUPPORTED and value.routing_disposition is not ReviewRoutingDispositionInput.FORMAL_CITATION_REJECTED:
        raise CanonicalValidationError("semantic_v2_unsupported_routing_drift")
    if value.result is SemanticSupport.UNCERTAIN and value.routing_disposition is not ReviewRoutingDispositionInput.HUMAN_REVIEW_REQUIRED:
        raise CanonicalValidationError("semantic_v2_uncertain_routing_drift")
    if value.result is SemanticSupport.SUPPORTED and value.routing_disposition is ReviewRoutingDispositionInput.FORMAL_CITATION_REJECTED:
        raise CanonicalValidationError("semantic_v2_supported_routing_drift")


def _recompute_stage2_v2_routing(value: Stage2SemanticInputV2, *, claim: ClaimInput, citation: CitationInput, comparisons: tuple[ComparisonInput, ...], conflicts: tuple[ConflictInput, ...]) -> None:
    if len(comparisons) > 1 or len(conflicts) > 1:
        raise CanonicalValidationError("semantic_v2_comparability_registry_ambiguous")
    participating_outcomes: tuple[ConflictOutcome, ...] = ()
    if not value.comparability_registry_empty:
        comparison = next((item for item in comparisons if item.comparison_id == value.comparison_id and item.artifact_hash == value.comparison_hash), None)
        conflict = next((item for item in conflicts if item.conflict_id == value.conflict_id and item.artifact_hash == value.conflict_hash), None)
        if comparison is None or conflict is None or conflict.comparison_id != comparison.comparison_id or conflict.outcome is not value.conflict_outcome: raise CanonicalValidationError("semantic_v2_comparability_participation_drift")
        participating_outcomes = (conflict.outcome,)
    try:
        from .semantic_evaluation import derive_review_routing_disposition
        expected = derive_review_routing_disposition(input_digest=value.input_digest, semantic_result_content_hash=value.semantic_result_content_hash, semantic_result=value.result, relationship=citation.relationship, inference_use=claim.inference_use, conflict_outcomes=participating_outcomes)
    except Exception as error:
        raise CanonicalValidationError("semantic_v2_routing_reconstruction_failed") from error
    observed = (value.routing_policy_version, value.routing_policy_hash, value.routing_disposition.value, value.human_review_required, value.routing_disposition_content_hash)
    authoritative = (expected.routing_policy_version, expected.routing_policy_hash, expected.disposition.value, expected.human_review_required, expected.content_hash)
    if observed != authoritative:
        raise CanonicalValidationError("semantic_v2_routing_binding_drift")

def _v2_required_resolution_bindings(traces: tuple[CitationTrace, ...]) -> tuple[ResolutionSemanticBindingInput, ...]:
    return tuple(
        _resolution_binding_from_stage2(item.stage2_v2)
        for item in traces
        if item.stage2_v2 is not None and item.stage2_v2.routing_disposition is ReviewRoutingDispositionInput.HUMAN_REVIEW_REQUIRED
    )

def _v2_resolution_is_exact(value: ResolutionInput | ResolutionInputV2 | None, traces: tuple[CitationTrace, ...]) -> bool:
    if type(value) is not ResolutionInputV2:
        return False
    required = _v2_required_resolution_bindings(traces)
    return (
        value.action is ResolutionAction.ADJUDICATED_TO_SUPPORTED
        and value.method == "human_review"
        and value.semantic_bindings == required
    )
