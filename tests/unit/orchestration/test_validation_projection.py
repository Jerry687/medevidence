"""Differential identity checks for the public canonical validation projection."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.orchestration.test_dynamic_registry import _dynamic
from tests.unit.orchestration.test_workflow import Harness, _initial, _run_until_node

from medevidence.orchestration.contracts import (
    GateStatus,
    ReportValidationState,
    WorkflowNode,
)
from medevidence.orchestration.validation_projection import (
    ValidationProjectionError,
    build_validation_request_projection,
    project_stored_validation,
)
from medevidence.tools.report_validation import canonical_report_content_hash


def _direct(state, registry, *, stored=None):
    assert state.interpreted_scope is not None and state.synthesis is not None
    return build_validation_request_projection(
        run_id=state.run_id,
        report_id=state.report_id,
        scope=state.interpreted_scope,
        source_plan=state.source_plan,
        source_tasks=state.source_tasks,
        synthesis=state.synthesis,
        registry=registry,
        stored_validation=stored,
    )


def test_fixed_workflow_request_is_byte_equivalent_before_and_after_validation() -> None:
    harness = Harness()
    state = _run_until_node(harness.workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    synthesized = harness.workflow.synthesize_claims(state)
    assert harness.workflow._build_validation_request(synthesized, include_stored=False) == _direct(
        synthesized, harness.registry
    )
    validated = harness.workflow.validate_report(synthesized)
    stored = project_stored_validation(validated.validation)
    assert harness.workflow._build_validation_request(validated, include_stored=True) == _direct(
        validated, harness.registry, stored=stored
    )


def test_dynamic_workflow_uses_the_exact_loaded_registry_projection(tmp_path: Path) -> None:
    _harness, workflow, stored, _reading, _provider, _snapshot = _dynamic(tmp_path)
    state = _run_until_node(workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    synthesized = workflow.synthesize_claims(state)
    assert synthesized.synthesis is not None
    reference = synthesized.synthesis.validation_registry_ref
    assert reference is not None
    registry = stored.load_registry(reference)
    assert workflow._build_validation_request(synthesized, include_stored=False) == _direct(
        synthesized, registry
    )


def test_provisional_hash_then_final_projection_has_the_same_canonical_identity() -> None:
    harness = Harness()
    state = _run_until_node(harness.workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    synthesized = harness.workflow.synthesize_claims(state)
    assert synthesized.synthesis is not None
    provisional = synthesized.model_copy(
        update={
            "synthesis": synthesized.synthesis.model_copy(
                update={"report_content_hash": "sha256:" + "0" * 64}
            )
        }
    )
    expected_hash = canonical_report_content_hash(_direct(provisional, harness.registry))
    assert expected_hash == synthesized.synthesis.report_content_hash
    assert canonical_report_content_hash(_direct(synthesized, harness.registry)) == expected_hash


def test_nonterminal_stored_validation_and_nonterminal_task_fail_closed() -> None:
    with pytest.raises(ValidationProjectionError, match="not terminal"):
        project_stored_validation(ReportValidationState())
    terminal = project_stored_validation(
        ReportValidationState(
            structural_citation_gate=GateStatus.PASSED,
            semantic_support_gate=GateStatus.PASSED,
            safety_policy_gate=GateStatus.PASSED,
        )
    )
    assert terminal.structural_passed and terminal.semantic_passed and terminal.safety_passed
    harness = Harness()
    collecting = _run_until_node(harness.workflow, _initial(), WorkflowNode.COLLECT_EVIDENCE)
    ready = _run_until_node(harness.workflow, _initial(), WorkflowNode.SYNTHESIZE_CLAIMS)
    synthesized = harness.workflow.synthesize_claims(ready)
    assert ready.interpreted_scope is not None and synthesized.synthesis is not None
    with pytest.raises(ValidationProjectionError, match="terminal tasks"):
        build_validation_request_projection(
            run_id=ready.run_id,
            report_id=ready.report_id,
            scope=ready.interpreted_scope,
            source_plan=ready.source_plan,
            source_tasks=collecting.source_tasks,
            synthesis=synthesized.synthesis,
            registry=harness.registry,
            stored_validation=terminal,
        )
