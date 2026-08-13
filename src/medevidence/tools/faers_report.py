"""Build one closed M1B FAERS aggregate draft from trusted executions."""

from __future__ import annotations

from medevidence.domain import (
    DomainWarning,
    FaersAggregateSectionV1,
    FaersLocatorV1,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ReportId,
    RunId,
    SourceType,
    UtcDateTime,
)
from medevidence.domain.identifiers import LongText

from .contracts import FaersAggregateExecution


def build_faers_report(
    request: M1BResearchRequestV1,
    *,
    report_id: ReportId,
    run_id: RunId,
    executions: tuple[FaersAggregateExecution, ...],
    warnings: tuple[DomainWarning, ...] = (),
    limitations: tuple[LongText, ...] = (),
    retrieved_as_of: UtcDateTime,
) -> M1BResearchReportV1:
    """Construct a FAERS-only draft from exact narrative-free executions."""

    validated_request = M1BResearchRequestV1.model_validate(request.model_dump(mode="python"))
    if validated_request.requested_sources != (SourceType.FAERS,):
        raise ValueError("FAERS report tool requires FAERS as the sole requested source")
    validated_executions = tuple(
        FaersAggregateExecution.model_validate(execution.model_dump(mode="python"))
        for execution in executions
    )
    if validated_executions != executions:
        raise ValueError("FAERS report execution differs from closed validation")
    if tuple(execution.request for execution in executions) != request.faers_query_requests:
        raise ValueError("FAERS report executions must exactly echo the canonical request")
    if any(execution.acquisition_outcome_ref.run_id != run_id for execution in executions):
        raise ValueError("FAERS report executions must belong to the report run")

    sections = tuple(
        FaersAggregateSectionV1(
            report_id=report_id,
            run_id=run_id,
            ordinal=ordinal,
            request=execution.request,
            acquisition_outcome_refs=(execution.acquisition_outcome_ref,),
            result=execution.result,
            locators=tuple(
                FaersLocatorV1(
                    report_id=report_id,
                    run_id=run_id,
                    acquisition_id=execution.acquisition_outcome_ref.acquisition_id,
                    snapshot_id=execution.acquisition_outcome_ref.snapshot_id,
                    outcome_query_id=bucket.query_id,
                    query_id=bucket.query_id,
                    identity_stratum=bucket.identity_stratum,
                    reaction_pt=bucket.reaction_pt,
                    bucket_ordinal=bucket.bucket_ordinal,
                    report_count=bucket.report_count,
                    role_policy=bucket.role_policy,
                )
                for bucket in execution.result.buckets
            ),
            limitations=execution.result.limitations,
        )
        for ordinal, execution in enumerate(executions)
    )
    mandatory_limitations = tuple(
        limitation for execution in executions for limitation in execution.result.limitations
    )
    report = M1BResearchReportV1.create(
        report_id=report_id,
        run_id=run_id,
        request_id=validated_request.request_id,
        scope=validated_request.scope,
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.FAERS,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=tuple(execution.result.source_outcome for execution in executions),
        source_sections=sections,
        warnings=warnings,
        limitations=(*limitations, *mandatory_limitations),
        retrieved_as_of=retrieved_as_of,
    )
    report.validate_against(
        validated_request,
        trusted_acquisition_outcomes=tuple(
            (
                execution.request,
                execution.acquisition_outcome_ref,
                execution.result.source_outcome,
            )
            for execution in executions
        ),
        trusted_selection_decisions=(),
    )
    return M1BResearchReportV1.model_validate(report.model_dump(mode="python"))


__all__ = ["build_faers_report"]
