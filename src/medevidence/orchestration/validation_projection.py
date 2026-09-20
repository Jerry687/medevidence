"""Pure projection from trusted orchestration state into canonical report input."""

from __future__ import annotations

from medevidence.domain import M1BSourcePlanEntryV1, PlanningStatus, ResearchScope
from medevidence.tools.report_validation import (
    M3_VALIDATION_CONFIGURATION_V3,
    M3_VALIDATION_CONFIGURATION_V4,
    AcquisitionInput,
    ArtifactReferenceInput,
    CanonicalReportRequest,
    CitationReferenceInput,
    ClaimReferenceInput,
    EvidenceReferenceInput,
    ExecutionBoundsInput,
    ScopeInput,
    SourceOutcomeInput,
    StoredValidationInput,
    SynthesisInput,
    TerminalTaskInput,
    ValidationRegistryInput,
)
from medevidence.tools.report_validation_source_bindings_v3 import (
    EvidenceChildAcquisitionBindingV3,
    TerminalTaskInputV3,
)

from .contracts import (
    GateStatus,
    ReportValidationState,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
)
from .source_capabilities import source_plan_identity


class ValidationProjectionError(ValueError):
    """Trusted orchestration material cannot form a canonical validation request."""


def project_stored_validation(
    validation: ReportValidationState,
) -> StoredValidationInput:
    """Project an exact terminal gate summary for binding verification."""

    if type(validation) is not ReportValidationState:
        raise ValidationProjectionError("stored validation has a foreign type")
    statuses = (
        validation.structural_citation_gate,
        validation.semantic_support_gate,
        validation.safety_policy_gate,
    )
    if GateStatus.NOT_RUN in statuses:
        raise ValidationProjectionError("stored validation is not terminal")
    return StoredValidationInput(
        structural_passed=statuses[0] is GateStatus.PASSED,
        semantic_passed=statuses[1] is GateStatus.PASSED,
        safety_passed=statuses[2] is GateStatus.PASSED,
        reason_codes=validation.reason_codes,
    )


def build_validation_request_projection(
    *,
    run_id: str,
    report_id: str,
    scope: ResearchScope,
    source_plan: tuple[M1BSourcePlanEntryV1, ...],
    source_tasks: tuple[SourceTaskState, ...],
    synthesis: SynthesisState,
    registry: ValidationRegistryInput,
    stored_validation: StoredValidationInput | None = None,
) -> CanonicalReportRequest:
    """Build the exact store-free request used for provisional and final report hashes."""

    scope_input = ScopeInput(
        scope_id=scope.scope_id,
        drugs=tuple((item.concept_id, item.preferred_term) for item in scope.drugs),
        adverse_reactions=tuple(
            (item.concept_id, item.preferred_term) for item in scope.adverse_reactions
        ),
        date_range=(
            None
            if scope.date_range is None
            else (
                scope.date_range.start_date.isoformat(),
                scope.date_range.end_date.isoformat(),
            )
        ),
        selected_sources=scope.selected_sources,
        comparison_intent=scope.comparison_intent,
        max_query_characters=scope.query_bounds.max_query_characters,
        max_pages=scope.query_bounds.max_pages,
        max_total_seconds=scope.query_bounds.max_total_seconds,
        max_records=scope.result_bounds.max_records,
        max_payload_bytes=scope.result_bounds.max_payload_bytes,
    )
    selected_task_sources = tuple(
        row.source for row in source_plan if row.planning_status is PlanningStatus.SELECTED
    )
    task_inputs: list[TerminalTaskInput] = []
    for task in source_tasks:
        terminal = task.terminal_outcome_ref
        if terminal is None:
            raise ValidationProjectionError("canonical validation requires terminal tasks")
        acquisition = terminal.acquisition
        outcome = terminal.outcome
        bounds = outcome.configured_bounds
        projected_task = TerminalTaskInput(
            task_id=task.task_id,
            source=task.source,
            terminal=task.status is SourceTaskStatus.TERMINAL,
            acquisition=AcquisitionInput(
                run_id=acquisition.run_id,
                source=acquisition.source,
                acquisition_id=acquisition.acquisition_id,
                acquisition_intent_id=acquisition.acquisition_intent_id,
                acquisition_ordinal=acquisition.acquisition_ordinal,
                operation=acquisition.operation,
                query_id=outcome.query_id,
                source_outcome_id=terminal.terminal_outcome_id,
                snapshot_id=acquisition.snapshot_id,
            ),
            outcome=SourceOutcomeInput(
                source=outcome.source,
                query_id=outcome.query_id,
                execution_status=outcome.execution_status,
                coverage_status=outcome.coverage_status,
                result_status=outcome.result_status,
                configured_bounds=ExecutionBoundsInput(
                    max_query_characters=bounds.max_query_characters,
                    max_pages=bounds.max_pages,
                    max_records=bounds.max_records,
                    max_payload_bytes=bounds.max_payload_bytes,
                    max_total_seconds=bounds.max_total_seconds,
                ),
                valid_result_count=outcome.valid_result_count,
                pages_completed=outcome.pages_completed,
                truncated=outcome.truncated,
                warning_codes=outcome.warning_codes,
                failure_id=outcome.failure_id,
            ),
            evidence_refs=tuple(
                EvidenceReferenceInput(
                    evidence_id=item.evidence_id,
                    source=item.source,
                    snapshot_id=item.snapshot_id,
                    content_hash=item.content_hash,
                    locator_ref=item.locator_ref,
                )
                for item in task.evidence_refs
            ),
        )
        if registry.configuration_version in (
            M3_VALIDATION_CONFIGURATION_V3,
            M3_VALIDATION_CONFIGURATION_V4,
        ):
            child_bindings = tuple(
                EvidenceChildAcquisitionBindingV3(
                    run_id=result.acquisition.run_id,
                    task_id=result.acquisition.task_id,
                    attempt_id=result.acquisition.attempt_id,
                    source=result.acquisition.source,
                    kind=result.acquisition.kind.value,
                    ordinal=result.acquisition.ordinal,
                    query_id=result.acquisition.query_id,
                    operation_id=result.acquisition.operation_id,
                    acquisition_id=result.acquisition.acquisition_id,
                    acquisition_intent_id=result.acquisition.acquisition_intent_id,
                    source_outcome_id=result.acquisition.source_outcome_id,
                    snapshot_id=result.acquisition.snapshot_id,
                    evidence_id=observation.evidence_id,
                    content_hash=observation.content_hash,
                    locator_ref=observation.locator_ref,
                )
                for result in task.operation_results
                for observation in result.observations
            )
            projected_task = TerminalTaskInputV3(
                task_id=projected_task.task_id,
                source=projected_task.source,
                terminal=projected_task.terminal,
                acquisition=projected_task.acquisition,
                outcome=projected_task.outcome,
                evidence_refs=projected_task.evidence_refs,
                operation_acquisition_ids=terminal.operation_acquisition_ids,
                evidence_child_bindings=child_bindings,
            )
        task_inputs.append(projected_task)
    synthesis_input = SynthesisInput(
        report_content_hash=synthesis.report_content_hash,
        claims=tuple(ClaimReferenceInput(item.claim_id) for item in synthesis.claims),
        citations=tuple(
            CitationReferenceInput(item.citation_id, item.claim_id, item.evidence_id)
            for item in synthesis.citations
        ),
        comparison_refs=tuple(
            ArtifactReferenceInput(item.comparability_id, item.artifact_hash)
            for item in synthesis.comparability_refs
        ),
        conflict_refs=tuple(
            ArtifactReferenceInput(item.conflict_id, item.artifact_hash)
            for item in synthesis.conflict_refs
        ),
        warning_codes=synthesis.warning_codes,
    )
    return CanonicalReportRequest(
        run_id=run_id,
        report_id=report_id,
        scope=scope_input,
        source_plan_id=source_plan_identity(source_plan),
        selected_task_sources=selected_task_sources,
        tasks=tuple(task_inputs),
        synthesis=synthesis_input,
        registry=registry,
        stored_validation=stored_validation,
    )
