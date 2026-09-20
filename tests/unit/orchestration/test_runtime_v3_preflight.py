"""A wrong V3 provider identity cannot write a Stage-1 receipt or call HTTP."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.unit.orchestration.test_dynamic_registry import Stage1Store
from tests.unit.orchestration.test_workflow import Harness, _initial, _run_until_node

from medevidence.orchestration.contracts import WorkflowNode
from medevidence.orchestration.workflow import (
    ControlledOrchestrationWorkflow,
    WorkflowTransitionError,
)
from medevidence.tools.report_validation import (
    M3_SEMANTIC_EVALUATION_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3,
    M3_VALIDATION_CONFIGURATION_V3,
    EvaluatorIdentityInput,
    PlannedStage2SemanticInputV2,
    RuntimeSemanticProfileIdentityV3,
)
from medevidence.tools.report_validation_v3 import (
    M3_VALIDATION_CONFIGURATION_V4,
    provider_method_for_validation_configuration,
    validation_profile,
)


@pytest.mark.parametrize(
    "configuration", (M3_VALIDATION_CONFIGURATION_V3, M3_VALIDATION_CONFIGURATION_V4)
)
def test_wrong_v3_port_is_rejected_before_stage1_store_write(configuration: str) -> None:
    method = provider_method_for_validation_configuration(configuration)
    _, neutral_hash, provider_version, _ = validation_profile(configuration)
    harness = Harness()
    expectation = harness.registry.semantic_expectations[0]
    registry = replace(
        harness.registry,
        semantic_expectations=(
            PlannedStage2SemanticInputV2(
                expectation.citation_id,
                expectation.input_digest,
                method,
                M3_SEMANTIC_EVALUATION_V2,
            ),
        ),
        evaluator_identity=EvaluatorIdentityInput(method, M3_SEMANTIC_EVALUATION_V2),
        configuration_version=configuration,
    )
    harness.synthesis.registry = registry
    stage1 = Stage1Store()

    class WrongPort:
        profile_identity = RuntimeSemanticProfileIdentityV3(
            method,
            neutral_hash,
            provider_version,
            "sha256:" + "0" * 64,
        )

        def __init__(self) -> None:
            self.calls = 0

        def evaluate_v2(self, value):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise AssertionError("provider must not be called")

    wrong = WrongPort()
    assert wrong.profile_identity.provider_configuration_hash != (
        M3_STAGE2_SEMANTIC_PROVIDER_CONFIGURATION_HASH_V3
    )
    workflow = ControlledOrchestrationWorkflow(
        scope_safety=harness.scope_safety,
        source_planning=harness.planner,
        evidence_collection=harness.collector,
        synthesis=harness.synthesis,
        validation_registry=registry,
        semantic_result_provider=harness.semantic,
        semantic_result_provider_v2=wrong,
        validation_receipt_store=harness.receipts,
        stage1_receipt_store=stage1,
        draft_persistence=harness.persistence,
        export_approval=harness.approval,
        export=harness.export,
    )
    ready = _run_until_node(workflow, _initial(), WorkflowNode.VALIDATE_REPORT)
    with pytest.raises(WorkflowTransitionError, match="canonical report validation failed"):
        workflow.validate_report(ready)
    assert wrong.calls == 0
    assert stage1.saved == {}
