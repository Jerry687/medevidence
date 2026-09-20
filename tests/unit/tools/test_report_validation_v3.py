"""Closed V3 source budgets, semantic profile, and receipt replay boundaries."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.unit.tools.test_report_validation import (
    _rebind,
    _v2_candidate,
    _v2_request,
    _v2_resolution_binding,
)

from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    DrugConcept,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)
from medevidence.infrastructure.validation_registry_store import SnapshotValidationRegistryStore
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import RuntimeContext
from medevidence.tools.report_validation import (
    M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V2,
    M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3,
    M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3,
    M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V3,
    M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
    M3_VALIDATION_CONFIGURATION_V2,
    M3_VALIDATION_CONFIGURATION_V3,
    M3_VALIDATION_POLICY_V3,
    CanonicalValidationError,
    CitationRelationship,
    ExecutionBoundsInput,
    PlannedStage2SemanticInputV2,
    RuntimeSemanticProfileIdentityV3,
    ScopeInput,
    SemanticSupport,
    ValidationMode,
    ValidationReceiptV2,
    canonical_stage1_receipt_payload_v2,
    canonical_validate_report,
    canonical_validation_receipt_payload,
    stage1_receipt_from_payload_v2,
    validation_receipt_from_payload,
    verify_validation_receipt,
)
from medevidence.tools.runtime_source_bounds import expected_runtime_source_bounds_v3
from medevidence.tools.semantic_evaluation import (
    build_semantic_evaluation_result_v2,
    build_semantic_evaluation_result_v2_low_prompt_v3,
)


def _v3_request():  # type: ignore[no-untyped-def]
    source, _, projections = _v2_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTEXT_ONLY),
        (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
    )
    model = ResearchScope.create(
        drugs=tuple(
            DrugConcept(concept_id=item[0], preferred_term=item[1]) for item in source.scope.drugs
        ),
        adverse_reactions=tuple(
            AdverseEventConcept(concept_id=item[0], preferred_term=item[1])
            for item in source.scope.adverse_reactions
        ),
        date_range=None,
        selected_sources=source.scope.selected_sources,
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    scope = ScopeInput(
        scope_id=model.scope_id,
        drugs=source.scope.drugs,
        adverse_reactions=source.scope.adverse_reactions,
        date_range=None,
        selected_sources=model.selected_sources,
        comparison_intent=model.comparison_intent,
        max_query_characters=512,
        max_pages=5,
        max_total_seconds=60,
        max_records=100,
        max_payload_bytes=5_242_880,
    )
    plans = tuple(
        PlannedStage2SemanticInputV2(item.citation_id, item.input_digest, item.method, item.version)
        for item in projections
    )
    task = source.tasks[0]
    task = replace(
        task,
        outcome=replace(
            task.outcome,
            configured_bounds=ExecutionBoundsInput(512, 1, 100, 5_242_880, 30),
        ),
    )
    return _rebind(
        replace(
            source,
            scope=scope,
            tasks=(task,),
            registry=replace(
                source.registry,
                scope_id=scope.scope_id,
                semantic_expectations=plans,
                configuration_version=M3_VALIDATION_CONFIGURATION_V3,
            ),
        )
    )


class _LowV3Port:
    profile_identity = RuntimeSemanticProfileIdentityV3(
        M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
        M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3,
        M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V3,
        M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3,
    )

    def __init__(self) -> None:
        self.calls = 0

    def evaluate_v2(self, request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return build_semantic_evaluation_result_v2_low_prompt_v3(
            request, _v2_candidate(SemanticSupport.SUPPORTED)
        )


def test_v3_source_profiles_are_exact_and_within_master() -> None:
    master = (512, 5, 100, 5_242_880, 60)
    assert expected_runtime_source_bounds_v3(SourceType.PUBMED, master) == (
        512,
        1,
        100,
        5_242_880,
        30,
    )
    for source in (SourceType.DAILYMED, SourceType.FAERS):
        assert expected_runtime_source_bounds_v3(source, master) == (512, 5, 100, 5_242_880, 30)
    assert expected_runtime_source_bounds_v3(SourceType.CADEC, master) == master
    with pytest.raises(ValueError, match="exceed"):
        expected_runtime_source_bounds_v3(SourceType.PUBMED, (128, 5, 100, 100_000, 60))


def test_v3_preflight_receipt_and_completed_receipt_bind_fixed_low_profile() -> None:
    request = _v3_request()
    preflight = canonical_validate_report(request, mode=ValidationMode.PREPARE_STAGE1)
    stage1 = preflight.stage1_receipt
    assert stage1 is not None
    assert (stage1.configuration_version, stage1.policy_version) == (
        M3_VALIDATION_CONFIGURATION_V3,
        M3_VALIDATION_POLICY_V3,
    )
    assert stage1_receipt_from_payload_v2(canonical_stage1_receipt_payload_v2(stage1)) == stage1
    port = _LowV3Port()
    audit = canonical_validate_report(
        request,
        mode=ValidationMode.ASSESS,
        semantic_result_provider_v2=port,
        stage1_receipt=stage1,
    )
    assert port.calls == 2
    assert audit.summary.passed
    receipt = audit.receipt
    assert type(receipt) is ValidationReceiptV2
    assert receipt.configuration_version == M3_VALIDATION_CONFIGURATION_V3
    assert receipt.policy_version == M3_VALIDATION_POLICY_V3
    assert receipt.semantic_configuration_hash == M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V3
    assert receipt.provider_configuration_hash == M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3
    assert validation_receipt_from_payload(canonical_validation_receipt_payload(receipt)) == receipt
    assert audit.resolved_request is not None
    assert (
        verify_validation_receipt(receipt, request=audit.resolved_request, audit=audit) == receipt
    )
    stage2 = audit.claims[0].citation_traces[0].stage2_v2
    assert stage2 is not None
    mixed_binding = replace(
        _v2_resolution_binding(stage2),
        semantic_configuration_hash=M3_STAGE2_SEMANTIC_CONFIGURATION_HASH_V2,
        provider_configuration_version=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_VERSION_V2,
        provider_configuration_hash=M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V2,
    )
    mixed_claim = replace(receipt.claim_results[0], resolution_semantic_bindings=(mixed_binding,))
    with pytest.raises(CanonicalValidationError, match="resolution_profile_mismatch"):
        canonical_validation_receipt_payload(
            replace(receipt, claim_results=(mixed_claim, *receipt.claim_results[1:]))
        )
    with pytest.raises(CanonicalValidationError):
        canonical_validation_receipt_payload(
            replace(receipt, provider_configuration_hash="sha256:" + "0" * 64)
        )
    with pytest.raises(CanonicalValidationError):
        canonical_validation_receipt_payload(
            replace(receipt, configuration_version=M3_VALIDATION_CONFIGURATION_V2)
        )
    with pytest.raises(CanonicalValidationError):
        canonical_stage1_receipt_payload_v2(
            replace(stage1, configuration_version=M3_VALIDATION_CONFIGURATION_V2)
        )


def test_v3_registry_store_roundtrip_binds_configuration(tmp_path) -> None:  # type: ignore[no-untyped-def]
    request = _v3_request()
    context = RuntimeContext(
        run_id=request.run_id,
        report_id=request.report_id,
        scope_id=request.scope.scope_id,
    )
    store = SnapshotValidationRegistryStore(
        SnapshotStore(tmp_path / "registry", free_bytes=lambda _: 20_000_000_000)
    )
    reference = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=request.registry,
    )
    assert store.load_registry(reference) == request.registry
    old = replace(request.registry, configuration_version=M3_VALIDATION_CONFIGURATION_V2)
    old_reference = store.publish_registry(
        context=context,
        report_content_hash=request.synthesis.report_content_hash,
        registry=old,
    )
    assert old_reference.registry_content_hash != reference.registry_content_hash


def test_v3_wrong_port_or_high_result_fails_before_or_at_boundary() -> None:
    request = _v3_request()
    stage1 = canonical_validate_report(request, mode=ValidationMode.PREPARE_STAGE1).stage1_receipt
    assert stage1 is not None
    wrong = _LowV3Port()
    wrong.profile_identity = replace(
        wrong.profile_identity, provider_configuration_hash="sha256:" + "0" * 64
    )
    with pytest.raises(CanonicalValidationError, match="identity_mismatch"):
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider_v2=wrong,
            stage1_receipt=stage1,
        )
    assert wrong.calls == 0

    class _HighResultPort(_LowV3Port):
        def evaluate_v2(self, value):  # type: ignore[no-untyped-def]
            self.calls += 1
            return build_semantic_evaluation_result_v2(
                value, _v2_candidate(SemanticSupport.SUPPORTED)
            )

    high = _HighResultPort()
    with pytest.raises(CanonicalValidationError):
        canonical_validate_report(
            request,
            mode=ValidationMode.ASSESS,
            semantic_result_provider_v2=high,
            stage1_receipt=stage1,
        )
    assert high.calls == 1


def test_legacy_v2_registry_rejects_declared_v3_port_before_provider() -> None:
    v3 = _v3_request()
    legacy = _rebind(
        replace(
            v3,
            tasks=(
                replace(
                    v3.tasks[0],
                    outcome=replace(
                        v3.tasks[0].outcome,
                        configured_bounds=ExecutionBoundsInput(512, 5, 100, 5_242_880, 60),
                    ),
                ),
            ),
            registry=replace(v3.registry, configuration_version=M3_VALIDATION_CONFIGURATION_V2),
        )
    )
    stage1 = canonical_validate_report(legacy, mode=ValidationMode.PREPARE_STAGE1).stage1_receipt
    assert stage1 is not None
    port = _LowV3Port()
    with pytest.raises(CanonicalValidationError, match="provider_identity_mismatch"):
        canonical_validate_report(
            legacy,
            mode=ValidationMode.ASSESS,
            semantic_result_provider_v2=port,
            stage1_receipt=stage1,
        )
    assert port.calls == 0


def test_v3_actual_source_bounds_are_not_rewritten_to_master() -> None:
    request = _v3_request()
    drifted = _rebind(
        replace(
            request,
            tasks=(
                replace(
                    request.tasks[0],
                    outcome=replace(
                        request.tasks[0].outcome,
                        configured_bounds=ExecutionBoundsInput(512, 5, 100, 5_242_880, 60),
                    ),
                ),
            ),
        )
    )
    audit = canonical_validate_report(drifted, mode=ValidationMode.PREPARE_STAGE1)
    assert not audit.summary.structural_passed
    assert "source_bounds_policy_mismatch" in audit.summary.reason_codes
    assert audit.stage1_receipt is None
