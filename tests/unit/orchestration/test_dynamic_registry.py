"""Dynamic registry is produced after synthesis and verified before Stage-2."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.orchestration.test_workflow import (
    Harness,
    _initial,
    _run_until_node,
    _run_until_terminal,
)
from tests.unit.tools.test_report_validation import _empty_request

from medevidence.infrastructure.validation_registry_store import SnapshotValidationRegistryStore
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import RuntimeContext, WorkflowNode
from medevidence.orchestration.workflow import (
    ControlledOrchestrationWorkflow,
    WorkflowTransitionError,
)
from medevidence.tools.report_validation import (
    M3_SEMANTIC_EVALUATION_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
    M3_VALIDATION_CONFIGURATION_V2,
    EvaluatorIdentityInput,
    PlannedStage2SemanticInputV2,
    SemanticSupport,
    canonical_stage1_receipt_payload_v2,
    stage1_receipt_from_payload_v2,
)
from medevidence.tools.semantic_evaluation import (
    SemanticEvaluationCandidateV2,
    SemanticRationaleCode,
    build_semantic_evaluation_result_v2,
)


class CountingRegistryStore:
    def __init__(self, delegate: SnapshotValidationRegistryStore) -> None:
        self.delegate = delegate
        self.loads = 0
        self.override = None

    def load_registry(self, reference):
        self.loads += 1
        return self.delegate.load_registry(reference) if self.override is None else self.override


class Stage1Store:
    def __init__(self) -> None:
        self.saved: dict[str, dict[str, object]] = {}

    def save_stage1_receipt(self, payload):
        receipt = stage1_receipt_from_payload_v2(dict(payload))
        canonical = canonical_stage1_receipt_payload_v2(receipt)
        self.saved[receipt.receipt_id] = canonical
        return canonical

    def load_stage1_receipt(self, receipt_id: str):
        return self.saved.get(receipt_id)


class V2Provider:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate_v2(self, value):
        self.calls += 1
        return build_semantic_evaluation_result_v2(
            value,
            SemanticEvaluationCandidateV2(
                result=SemanticSupport.SUPPORTED,
                rationale_codes=(SemanticRationaleCode.DIRECT_SUPPORT,),
                explanation="The bounded admitted source supports the material citation.",
            ),
        )


def _dynamic(tmp_path: Path):
    harness = Harness()
    expectation = harness.registry.semantic_expectations[0]
    registry = replace(
        harness.registry,
        semantic_expectations=(
            PlannedStage2SemanticInputV2(
                expectation.citation_id,
                expectation.input_digest,
                M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
                M3_SEMANTIC_EVALUATION_V2,
            ),
        ),
        evaluator_identity=EvaluatorIdentityInput(
            M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2, M3_SEMANTIC_EVALUATION_V2
        ),
        configuration_version=M3_VALIDATION_CONFIGURATION_V2,
    )
    harness.synthesis.registry = registry
    context = RuntimeContext(
        run_id=harness.registry.run_id,
        report_id=_initial().report_id,
        scope_id=harness.scope.scope_id,
    )
    snapshot = SnapshotStore(tmp_path / "registry", free_bytes=lambda _: 20_000_000_000)
    stored = SnapshotValidationRegistryStore(snapshot)
    reading = CountingRegistryStore(stored)

    class DynamicSynthesis:
        def synthesize(self, **kwargs):
            result = harness.synthesis.synthesize(**kwargs)
            reference = stored.publish_registry(
                context=context,
                report_content_hash=result.report_content_hash,
                registry=registry,
            )
            return result.model_copy(update={"validation_registry_ref": reference})

    provider = V2Provider()
    workflow = ControlledOrchestrationWorkflow(
        scope_safety=harness.scope_safety,
        source_planning=harness.planner,
        evidence_collection=harness.collector,
        synthesis=DynamicSynthesis(),
        semantic_result_provider=harness.semantic,
        semantic_result_provider_v2=provider,
        validation_receipt_store=harness.receipts,
        stage1_receipt_store=Stage1Store(),
        draft_persistence=harness.persistence,
        export_approval=harness.approval,
        export=harness.export,
        runtime_context=context,
        validation_registry_provider=reading,
    )
    return harness, workflow, stored, reading, provider, snapshot


def test_dynamic_run_loads_only_after_synthesis_and_passes_report_gate(tmp_path: Path) -> None:
    _, workflow, _, reading, provider, _ = _dynamic(tmp_path)
    state = _run_until_node(workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    assert reading.loads == 0 and provider.calls == 0
    synthesized = workflow.synthesize_claims(state)
    assert synthesized.synthesis is not None
    assert synthesized.synthesis.validation_registry_ref is not None
    assert reading.loads >= 1 and provider.calls == 0
    pending = _run_until_node(workflow, synthesized, WorkflowNode.SAVE_PENDING_DRAFT)
    assert pending.validation.passed
    assert provider.calls == 1
    completed = _run_until_terminal(workflow, pending)
    assert completed.disposition.value == "exported"
    assert provider.calls == 1


def test_missing_swapped_or_tampered_registry_blocks_before_provider(tmp_path: Path) -> None:
    _, workflow, stored, reading, provider, snapshot = _dynamic(tmp_path)
    state = _run_until_node(workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    synthesized = workflow.synthesize_claims(state)
    assert synthesized.synthesis is not None
    reference = synthesized.synthesis.validation_registry_ref
    assert reference is not None
    missing = synthesized.model_copy(
        update={
            "synthesis": synthesized.synthesis.model_copy(update={"validation_registry_ref": None})
        }
    )
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(missing)
    swapped = synthesized.model_copy(
        update={
            "synthesis": synthesized.synthesis.model_copy(
                update={
                    "validation_registry_ref": reference.model_copy(
                        update={"run_id": "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
                    )
                }
            )
        }
    )
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(swapped)
    empty = _empty_request()
    second_run = "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    second_context = RuntimeContext(
        run_id=second_run,
        report_id="report:sha256:" + "c" * 64,
        scope_id=empty.scope.scope_id,
    )
    second_registry = replace(
        empty.registry,
        run_id=second_run,
        evaluator_identity=EvaluatorIdentityInput(
            M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2, M3_SEMANTIC_EVALUATION_V2
        ),
        configuration_version=M3_VALIDATION_CONFIGURATION_V2,
        semantic_expectations=(),
    )
    second_ref = stored.publish_registry(
        context=second_context,
        report_content_hash=empty.synthesis.report_content_hash,
        registry=second_registry,
    )
    assert second_ref.registry_id != reference.registry_id
    actually_swapped = synthesized.model_copy(
        update={
            "synthesis": synthesized.synthesis.model_copy(
                update={"validation_registry_ref": second_ref}
            )
        }
    )
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(actually_swapped)
    original_registry = stored.load_registry(reference)
    stale_ref = stored.publish_registry(
        context=RuntimeContext(
            run_id=reference.run_id,
            report_id=reference.report_id,
            scope_id=reference.scope_id,
        ),
        report_content_hash="sha256:" + "0" * 64,
        registry=original_registry,
    )
    stale = synthesized.model_copy(
        update={
            "synthesis": synthesized.synthesis.model_copy(
                update={"validation_registry_ref": stale_ref}
            )
        }
    )
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(stale)
    digest = reference.registry_content_hash.removeprefix("sha256:")
    target = snapshot.root / "m3" / "validation-registry" / "sha256" / digest[:2] / f"{digest}.json"
    original = target.read_bytes()
    target.write_bytes(original.replace(b"pubmed", b"faersx", 1))
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(synthesized)
    assert provider.calls == 0 and reading.loads >= 1
    target.write_bytes(original)
    reading.override = replace(original_registry, semantic_expectations=())
    with pytest.raises(WorkflowTransitionError):
        workflow.validate_report(synthesized)
    assert provider.calls == 0


def test_dynamic_constructor_rejects_ambiguous_and_foreign_context(tmp_path: Path) -> None:
    harness, _, _, reading, _, _ = _dynamic(tmp_path)
    with pytest.raises(WorkflowTransitionError):
        ControlledOrchestrationWorkflow(
            scope_safety=harness.scope_safety,
            source_planning=harness.planner,
            evidence_collection=harness.collector,
            synthesis=harness.synthesis,
            validation_registry=harness.registry,
            semantic_result_provider=harness.semantic,
            validation_receipt_store=harness.receipts,
            draft_persistence=harness.persistence,
            export_approval=harness.approval,
            export=harness.export,
            runtime_context=RuntimeContext(
                run_id=harness.registry.run_id,
                report_id=_initial().report_id,
                scope_id=harness.scope.scope_id,
            ),
            validation_registry_provider=reading,
        )
    foreign = ControlledOrchestrationWorkflow(
        scope_safety=harness.scope_safety,
        source_planning=harness.planner,
        evidence_collection=harness.collector,
        synthesis=harness.synthesis,
        semantic_result_provider=harness.semantic,
        validation_receipt_store=harness.receipts,
        draft_persistence=harness.persistence,
        export_approval=harness.approval,
        export=harness.export,
        runtime_context=RuntimeContext(
            run_id="run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            report_id=_initial().report_id,
            scope_id=harness.scope.scope_id,
        ),
        validation_registry_provider=reading,
    )
    with pytest.raises(WorkflowTransitionError):
        foreign.scope_and_safety(_initial())
    assert harness.events == []
