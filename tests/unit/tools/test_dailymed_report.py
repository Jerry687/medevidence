"""DailyMed report-tool tests over exact offline trusted evidence."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from medevidence.domain import (
    AcquisitionOutcomeRef,
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DailyMedLabelSectionV1,
    DailyMedLocatorV1,
    DailyMedResolution,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    LabelSelectionDecision,
    LabelSelectionStatus,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    PlanningStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    RetainedSplResponse,
    SourceOutcome,
    SourceType,
)
from medevidence.tools import build_dailymed_report

REQUEST_ID = "request:00000000-0000-4000-8000-000000000001"
RUN_ID = "run:00000000-0000-4000-8000-000000000002"
REPORT_ID = f"report:sha256:{'1' * 64}"
NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
LIMITATION = "Discovery was indeterminate; no authoritative label was selected."


def dailymed_request() -> M1BResearchRequestV1:
    scope = ResearchScope.create(
        drugs=(DrugConcept(concept_id="drug:test", preferred_term="test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="event:test", preferred_term="test event"),
        ),
        date_range=None,
        selected_sources=(SourceType.DAILYMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=5,
            max_total_seconds=60,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    selection_request = DailyMedSelectionRequestV1(
        drug_concept_id="drug:test",
        requested_section_codes=("34084-4",),
        selection_mode=DailyMedSelectionMode.STRICT_IDENTITY,
    )
    return M1BResearchRequestV1(
        request_id=REQUEST_ID,
        scope=scope,
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(selection_request,),
    )


def trusted_case() -> tuple[
    M1BResearchRequestV1,
    DailyMedLabelSectionV1,
    AcquisitionOutcomeRef,
    SourceOutcome,
]:
    request = dailymed_request()
    ref = AcquisitionOutcomeRef(
        run_id=RUN_ID,
        source=SourceType.DAILYMED,
        acquisition_id="acquisition:dailymed-search",
        acquisition_intent_id=f"acquisition-intent:sha256:{'2' * 64}",
        acquisition_ordinal=0,
        operation="search",
        query_id="query:dailymed-search",
        source_outcome_id="source-outcome:dailymed-search",
        snapshot_id="snapshot:dailymed-search",
    )
    outcome = SourceOutcome(
        source=SourceType.DAILYMED,
        query_id=ref.query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=0,
        pages_completed=1,
        truncated=True,
        warning_codes=("source_coverage_incomplete",),
    )
    section = DailyMedLabelSectionV1(
        report_id=REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=request.dailymed_selection_requests[0],
        acquisition_outcome_refs=(ref,),
        limitations=(LIMITATION,),
    )
    return request, section, ref, outcome


def test_report_tool_builds_exact_selected_dailymed_draft() -> None:
    request, section, ref, outcome = trusted_case()

    report = build_dailymed_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    )

    assert report.schema_version == "m1b.report.v1"
    assert report.status == "draft"
    assert report.exportable is False
    assert report.source_plan[0].source is SourceType.DAILYMED
    assert report.source_plan[0].planning_status is PlanningStatus.SELECTED
    assert report.source_plan[0].reason is None
    assert report.source_plan[0].reason_code is None
    assert "individualized medical advice" in report.safety_notice
    assert "source_plan" not in inspect.signature(build_dailymed_report).parameters


def test_report_tool_rejects_forged_trusted_reference() -> None:
    request, section, ref, outcome = trusted_case()
    foreign_ref = ref.model_copy(update={"source_outcome_id": "source-outcome:foreign"})

    with pytest.raises(ValueError, match="trusted acquisition outcomes"):
        build_dailymed_report(
            request,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            source_sections=(section,),
            retrieved_as_of=NOW,
            trusted_acquisition_outcomes=((section.request, foreign_ref, outcome),),
            trusted_selection_decisions=(),
        )


def test_report_tool_rejects_non_dailymed_route_scope() -> None:
    request = dailymed_request()
    pubmed_scope = ResearchScope.create(
        drugs=request.scope.drugs,
        adverse_reactions=request.scope.adverse_reactions,
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=request.scope.comparison_intent,
        query_bounds=request.scope.query_bounds,
        result_bounds=request.scope.result_bounds,
    )
    pubmed_request = M1BResearchRequestV1(
        request_id=REQUEST_ID,
        scope=pubmed_scope,
        requested_sources=(SourceType.PUBMED,),
    )

    with pytest.raises(ValueError, match="sole requested source"):
        build_dailymed_report(
            pubmed_request,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            source_sections=(),
            retrieved_as_of=NOW,
            trusted_acquisition_outcomes=(),
            trusted_selection_decisions=(),
        )


@pytest.mark.parametrize(
    ("execution", "coverage"),
    (
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL),
        (ExecutionStatus.FAILED, CoverageStatus.PARTIAL),
        (ExecutionStatus.FAILED, CoverageStatus.UNAVAILABLE),
    ),
)
def test_report_tool_accepts_all_three_decisionless_indeterminate_triples(
    execution: ExecutionStatus,
    coverage: CoverageStatus,
) -> None:
    request, section, ref, _ = trusted_case()
    from tests.unit.domain.test_reports import dailymed_outcome

    outcome = dailymed_outcome(
        query_id=ref.query_id,
        execution=execution,
        coverage=coverage,
        result=ResultStatus.INDETERMINATE,
        count=0,
    )
    report = build_dailymed_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    )
    assert report.source_outcomes == (outcome,)
    assert report.source_sections[0].selection_status is None


@pytest.mark.parametrize("state", ("no_candidate", "complete_review", "partial_review"))
def test_report_tool_accepts_exact_nonselected_decision_states(state: str) -> None:
    from tests.unit.domain.test_reports import dailymed_candidate, dailymed_outcome

    request, base_section, ref, _ = trusted_case()
    if state == "no_candidate":
        outcome = dailymed_outcome(
            query_id=ref.query_id,
            result=ResultStatus.NO_MATCH,
            count=0,
        )
        decision = LabelSelectionDecision.no_candidate_from_discovery(
            run_id=RUN_ID,
            attempt_id="attempt:00000000-0000-4000-8000-000000000013",
            acquisition_id=ref.acquisition_id,
            acquisition_ordinal=ref.acquisition_ordinal,
            acquisition_intent_id=ref.acquisition_intent_id,
            candidate_set_snapshot_id=ref.snapshot_id,
            discovery_manifest_id="artifact:dailymed-discovery-manifest",
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            source_outcome_id=ref.source_outcome_id,
            outcome=outcome,
            decided_at_utc=NOW,
        )
        candidates = ()
    else:
        candidates = (dailymed_candidate(discovery_ref=ref, labeler="A labeler"),)
        coverage = CoverageStatus.COMPLETE if state == "complete_review" else CoverageStatus.PARTIAL
        if state == "complete_review":
            candidates = (
                *candidates,
                dailymed_candidate(
                    discovery_ref=ref,
                    setid="22222222-2222-2222-2222-222222222222",
                    ordinal=1,
                    labeler="B labeler",
                ),
            )
        outcome = dailymed_outcome(
            query_id=ref.query_id,
            coverage=coverage,
            count=len(candidates),
        )
        decision = LabelSelectionDecision.review_required_from_discovery(
            candidates=candidates,
            outcome=outcome,
            resolution=(
                DailyMedResolution.UNRESOLVED_NON_EQUIVALENT
                if state == "complete_review"
                else DailyMedResolution.RESOLVED_EQUIVALENT
            ),
            source_outcome_id=ref.source_outcome_id,
            discovery_manifest_content_hash=f"sha256:{'f' * 64}",
            decided_at_utc=NOW,
        )
    section = base_section.model_copy(
        update={
            "selection_decision_id": decision.decision_id,
            "selection_status": decision.status,
            "limitations": (f"{state} remains visible.",),
        }
    )
    report = build_dailymed_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(
            (section.request, decision, candidates, f"sha256:{'f' * 64}"),
        ),
    )
    assert report.source_sections[0].selection_status is decision.status


@pytest.mark.parametrize("fetch_attempted", (False, True))
def test_report_tool_accepts_selected_before_fetch_and_failed_fetch(
    fetch_attempted: bool,
) -> None:
    from tests.unit.domain.test_reports import dailymed_candidate, dailymed_outcome

    request, base_section, discovery_ref, _ = trusted_case()
    discovery = dailymed_outcome(query_id=discovery_ref.query_id)
    candidate = dailymed_candidate(discovery_ref=discovery_ref)
    decision = LabelSelectionDecision.selected_from_discovery(
        candidates=(candidate,),
        outcome=discovery,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id=discovery_ref.source_outcome_id,
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
    )
    refs = (discovery_ref,)
    outcomes = (discovery,)
    limitation: tuple[str, ...] = ()
    if fetch_attempted:
        fetch_ref = AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:dailymed-fetch",
            acquisition_intent_id=f"acquisition-intent:sha256:{'3' * 64}",
            acquisition_ordinal=1,
            operation="fetch",
            query_id="query:dailymed-fetch",
            source_outcome_id="source-outcome:dailymed-fetch",
            snapshot_id="snapshot:dailymed-fetch",
        )
        fetch = dailymed_outcome(
            query_id=fetch_ref.query_id,
            execution=ExecutionStatus.FAILED,
            coverage=CoverageStatus.PARTIAL,
            result=ResultStatus.INDETERMINATE,
            count=0,
        )
        refs = (*refs, fetch_ref)
        outcomes = (*outcomes, fetch)
        limitation = ("The selected label fetch did not produce usable evidence.",)
    section = base_section.model_copy(
        update={
            "selection_decision_id": decision.decision_id,
            "selection_status": LabelSelectionStatus.SELECTED,
            "acquisition_outcome_refs": refs,
            "limitations": limitation,
        }
    )
    trusted = tuple(
        (section.request, ref, outcome) for ref, outcome in zip(refs, outcomes, strict=True)
    )
    report = build_dailymed_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=trusted,
        trusted_selection_decisions=(
            (section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
        ),
    )
    assert len(report.source_outcomes) == len(refs)

    invalid_rows = [trusted[1:], (*trusted, trusted[-1])]
    if len(trusted) > 1:
        invalid_rows.append(tuple(reversed(trusted)))
    for invalid in invalid_rows:
        with pytest.raises(ValueError, match=r"trusted|report outcomes"):
            build_dailymed_report(
                request,
                report_id=REPORT_ID,
                run_id=RUN_ID,
                source_sections=(section,),
                retrieved_as_of=NOW,
                trusted_acquisition_outcomes=invalid,
                trusted_selection_decisions=(
                    (section.request, decision, (candidate,), f"sha256:{'f' * 64}"),
                ),
            )


def _stable_report_case() -> tuple[M1BResearchRequestV1, M1BResearchReportV1]:
    from tests.unit.domain.test_reports import (
        dailymed_candidate,
        dailymed_outcome,
        dailymed_version_and_section,
    )

    request, _, discovery_ref, _ = trusted_case()
    version, label_section = dailymed_version_and_section()
    discovery = dailymed_outcome(query_id=discovery_ref.query_id)
    fetch_ref = AcquisitionOutcomeRef(
        run_id=RUN_ID,
        source=SourceType.DAILYMED,
        acquisition_id="acquisition:dailymed-fetch",
        acquisition_intent_id=f"acquisition-intent:sha256:{'3' * 64}",
        acquisition_ordinal=1,
        operation="fetch",
        query_id="query:dailymed-fetch",
        source_outcome_id="source-outcome:dailymed-fetch",
        snapshot_id="snapshot:dailymed-fetch",
    )
    fetch = dailymed_outcome(query_id=fetch_ref.query_id)
    candidate = dailymed_candidate(discovery_ref=discovery_ref)
    decision = LabelSelectionDecision.selected_from_discovery(
        candidates=(candidate,),
        outcome=discovery,
        resolution=DailyMedResolution.RESOLVED_EQUIVALENT,
        source_outcome_id=discovery_ref.source_outcome_id,
        discovery_manifest_content_hash=f"sha256:{'f' * 64}",
        decided_at_utc=NOW,
    )
    fetch_attempt_id = "attempt:00000000-0000-4000-8000-000000000014"
    fetch_manifest_id = "artifact:dailymed-fetch-manifest"
    fetch_link_id = f"artifact-link:sha256:{'5' * 64}"
    retained = RetainedSplResponse.create(
        run_id=RUN_ID,
        acquisition_id=fetch_ref.acquisition_id,
        candidate_set_snapshot_id=discovery_ref.snapshot_id,
        selection_decision_id=decision.decision_id,
        source_outcome_query_id=fetch_ref.query_id,
        setid=version.setid,
        spl_version=version.spl_version,
        media_type="application/xml",
        byte_size=12,
        content_hash=version.content_hash,
        artifact_id=version.spl_artifact_id,
        manifest_id=fetch_manifest_id,
        retrieved_at=NOW,
        section_ids=(label_section.section_id,),
        fetch_attempt_id=fetch_attempt_id,
        fetch_acquisition_id=fetch_ref.acquisition_id,
        fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
        fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
        fetch_query_id=fetch_ref.query_id,
        fetch_snapshot_id=fetch_ref.snapshot_id,
        fetch_manifest_id=fetch_manifest_id,
        fetch_source_outcome_id=fetch_ref.source_outcome_id,
        fetch_member_ordinal=0,
        fetch_link_id=fetch_link_id,
        fetch_raw_artifact_id=version.spl_artifact_id,
        fetch_raw_content_hash=version.content_hash,
        selected_candidate_id=candidate.candidate_id,
        label_version_id=version.label_version_id,
    )
    locator = DailyMedLocatorV1(
        report_id=REPORT_ID,
        run_id=RUN_ID,
        acquisition_id=fetch_ref.acquisition_id,
        snapshot_id=fetch_ref.snapshot_id,
        outcome_query_id=fetch_ref.query_id,
        selection_decision_id=decision.decision_id,
        selected_candidate_id=candidate.candidate_id,
        discovery_attempt_id="attempt:00000000-0000-4000-8000-000000000013",
        discovery_acquisition_intent_id=discovery_ref.acquisition_intent_id,
        discovery_acquisition_ordinal=discovery_ref.acquisition_ordinal,
        discovery_query_id=discovery_ref.query_id,
        discovery_snapshot_id=discovery_ref.snapshot_id,
        discovery_manifest_id="artifact:dailymed-discovery-manifest",
        discovery_source_outcome_id=discovery_ref.source_outcome_id,
        fetch_attempt_id=fetch_attempt_id,
        setid=version.setid,
        label_version_id=version.label_version_id,
        spl_version=version.spl_version,
        fetch_acquisition_id=fetch_ref.acquisition_id,
        fetch_acquisition_intent_id=fetch_ref.acquisition_intent_id,
        fetch_acquisition_ordinal=fetch_ref.acquisition_ordinal,
        fetch_query_id=fetch_ref.query_id,
        fetch_snapshot_id=fetch_ref.snapshot_id,
        fetch_manifest_id=fetch_manifest_id,
        fetch_source_outcome_id=fetch_ref.source_outcome_id,
        fetch_member_ordinal=0,
        fetch_link_id=fetch_link_id,
        fetch_raw_artifact_id=version.spl_artifact_id,
        fetch_raw_content_hash=version.content_hash,
        stable_content_hash=version.content_hash,
        section_code=label_section.section_code,
        section_ordinal=label_section.section_ordinal,
        xml_path=label_section.xml_path,
        start_char=label_section.text_start,
        end_char=label_section.text_end,
        section_hash=label_section.text_hash,
        spl_artifact_id=version.spl_artifact_id,
    )
    section = DailyMedLabelSectionV1(
        report_id=REPORT_ID,
        run_id=RUN_ID,
        ordinal=0,
        request=request.dailymed_selection_requests[0],
        selection_decision_id=decision.decision_id,
        selection_status=LabelSelectionStatus.SELECTED,
        acquisition_outcome_refs=(discovery_ref, fetch_ref),
        label_version=version,
        retained_response=retained,
        label_sections=(label_section,),
        locators=(locator,),
    )
    acquisitions = (
        (section.request, discovery_ref, discovery),
        (section.request, fetch_ref, fetch),
    )
    decisions = ((section.request, decision, (candidate,), f"sha256:{'f' * 64}"),)
    trusted_fetch = (
        (
            section.request,
            fetch_ref,
            fetch_attempt_id,
            fetch_manifest_id,
            0,
            fetch_link_id,
            version.spl_artifact_id,
            version.content_hash,
        ),
    )
    report = build_dailymed_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=acquisitions,
        trusted_selection_decisions=decisions,
        trusted_fetch_evidence=trusted_fetch,
    )
    assert report.source_sections[0].locators == (locator,)

    for invalid_fetch in ((), (*trusted_fetch, trusted_fetch[0])):
        with pytest.raises(ValueError, match="trusted fetch evidence"):
            build_dailymed_report(
                request,
                report_id=REPORT_ID,
                run_id=RUN_ID,
                source_sections=(section,),
                retrieved_as_of=NOW,
                trusted_acquisition_outcomes=acquisitions,
                trusted_selection_decisions=decisions,
                trusted_fetch_evidence=invalid_fetch,
            )
    return request, report


def test_report_tool_forwards_exact_trusted_fetch_for_stable_locator() -> None:
    _, report = _stable_report_case()
    assert len(report.source_sections[0].locators) == 1
