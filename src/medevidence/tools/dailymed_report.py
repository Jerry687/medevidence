"""Build one closed M1B DailyMed draft from trusted existing evidence."""

from __future__ import annotations

from medevidence.domain import (
    DailyMedLabelSectionV1,
    DomainWarning,
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

from .contracts import (
    TrustedDailyMedAcquisitionOutcome,
    TrustedDailyMedFetchEvidence,
    TrustedDailyMedSelectionDecision,
)


def build_dailymed_report(
    request: M1BResearchRequestV1,
    *,
    report_id: ReportId,
    run_id: RunId,
    source_sections: tuple[DailyMedLabelSectionV1, ...],
    warnings: tuple[DomainWarning, ...] = (),
    limitations: tuple[LongText, ...] = (),
    retrieved_as_of: UtcDateTime,
    trusted_acquisition_outcomes: tuple[TrustedDailyMedAcquisitionOutcome, ...],
    trusted_selection_decisions: tuple[TrustedDailyMedSelectionDecision, ...],
    trusted_fetch_evidence: tuple[TrustedDailyMedFetchEvidence, ...] = (),
) -> M1BResearchReportV1:
    """Construct and fully compare a DailyMed-only report to trusted evidence."""

    validated_request = M1BResearchRequestV1.model_validate(request.model_dump(mode="python"))
    if validated_request.requested_sources != (SourceType.DAILYMED,):
        raise ValueError("DailyMed report tool requires DailyMed as the sole requested source")

    report = M1BResearchReportV1.create(
        report_id=report_id,
        run_id=run_id,
        request_id=validated_request.request_id,
        scope=validated_request.scope,
        source_plan=(
            M1BSourcePlanEntryV1(
                source=SourceType.DAILYMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=tuple(item[2] for item in trusted_acquisition_outcomes),
        source_sections=source_sections,
        warnings=warnings,
        limitations=limitations,
        retrieved_as_of=retrieved_as_of,
    )
    report.validate_against(
        validated_request,
        trusted_acquisition_outcomes=trusted_acquisition_outcomes,
        trusted_selection_decisions=trusted_selection_decisions,
        trusted_fetch_evidence=trusted_fetch_evidence,
    )
    return M1BResearchReportV1.model_validate(report.model_dump(mode="python"))


__all__ = ["build_dailymed_report"]
