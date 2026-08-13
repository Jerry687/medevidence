"""FAERS report-tool tests over exact offline narrative-free evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tests.unit.domain.test_reports import scope
from tests.unit.tools.test_faers import RUN_ID, _execution, _request

from medevidence.domain import (
    FAERS_MANDATORY_LIMITATIONS,
    DailyMedSelectionMode,
    M1BResearchRequestV1,
    SourceType,
)
from medevidence.tools import build_faers_report

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
REPORT_ID = f"report:sha256:{'7' * 64}"


def _report_request() -> M1BResearchRequestV1:
    faers_request = _request(drug_concept_id="drug:test")
    return M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000021",
        scope=scope(selected_sources=(SourceType.FAERS,)),
        requested_sources=(SourceType.FAERS,),
        faers_query_requests=(faers_request,),
    )


def test_report_tool_builds_exact_faers_draft_and_complete_locators() -> None:
    request = _report_request()
    execution = _execution(request.faers_query_requests[0])

    report = build_faers_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        executions=(execution,),
        retrieved_as_of=NOW,
    )

    assert report.schema_version == "m1b.report.v1"
    assert report.status == "draft"
    assert report.exportable is False
    assert report.source_plan[0].source is SourceType.FAERS
    assert report.source_outcomes == (execution.result.source_outcome,)
    assert report.limitations == tuple(sorted(FAERS_MANDATORY_LIMITATIONS))
    section = report.source_sections[0]
    assert section.result == execution.result
    assert section.limitations == FAERS_MANDATORY_LIMITATIONS
    assert len(section.locators) == len(execution.result.buckets)
    assert section.locators[0].report_count == execution.result.buckets[0].report_count
    assert section.locators[0].role_policy == "unfiltered_provider_roles"
    assert section.locators[0].endpoint_mode == "provider_count_occurrence"
    assert section.result.query.pt_values == ("DIARRHOEA", "NAUSEA", "VOMITING")


def test_report_tool_rejects_request_execution_or_run_drift() -> None:
    request = _report_request()
    execution = _execution(request.faers_query_requests[0])

    with pytest.raises(ValueError, match="exactly echo"):
        build_faers_report(
            request,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            executions=(),
            retrieved_as_of=NOW,
        )

    foreign_ref = execution.acquisition_outcome_ref.model_copy(
        update={"run_id": "run:00000000-0000-4000-8000-000000000099"}
    )
    foreign_execution = execution.model_copy(update={"acquisition_outcome_ref": foreign_ref})
    with pytest.raises((ValueError, ValidationError), match=r"report run|execution"):
        build_faers_report(
            request,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            executions=(foreign_execution,),
            retrieved_as_of=NOW,
        )


def test_report_tool_rejects_non_faers_route_scope() -> None:
    dailymed_request = M1BResearchRequestV1(
        request_id="request:00000000-0000-4000-8000-000000000022",
        scope=scope(selected_sources=(SourceType.DAILYMED,)),
        requested_sources=(SourceType.DAILYMED,),
        dailymed_selection_requests=(
            {
                "drug_concept_id": "drug:test",
                "requested_section_codes": ("34084-4",),
                "selection_mode": DailyMedSelectionMode.STRICT_IDENTITY,
            },
        ),
    )
    with pytest.raises(ValueError, match="sole requested source"):
        build_faers_report(
            dailymed_request,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            executions=(),
            retrieved_as_of=NOW,
        )


def test_report_tool_emits_no_individual_report_or_narrative_payload_fields() -> None:
    request = _report_request()
    report = build_faers_report(
        request,
        report_id=REPORT_ID,
        run_id=RUN_ID,
        executions=(_execution(request.faers_query_requests[0]),),
        retrieved_as_of=NOW,
    )
    serialized = report.model_dump_json()

    for forbidden in (
        '"patient"',
        '"narrative"',
        '"safetyreportid"',
        '"safetyreportversion"',
        '"drugcharacterization"',
        '"individual_reports"',
    ):
        assert forbidden not in serialized
