"""Offline tests for the stable source-neutral DailyMed tool boundary."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    AcquisitionOutcomeRef,
    CoverageStatus,
    DailyMedSelectionMode,
    DailyMedSelectionRequestV1,
    ExecutionBounds,
    ExecutionStatus,
    LabelSelectionStatus,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.tools import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
    discover_dailymed_labels,
    fetch_dailymed_label,
)
from medevidence.tools.dailymed import (
    DailyMedDiscoveryExecutionProjection,
    DailyMedFetchExecutionProjection,
    DailyMedSectionEvidenceProjection,
)
from medevidence.tools.ports import DailyMedExecutionPort

SETID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "run:12345678-1234-4234-9234-123456789abc"


def _selection_request(*, pinned: bool = False) -> DailyMedSelectionRequestV1:
    return DailyMedSelectionRequestV1(
        drug_concept_id="drug:test",
        requested_section_codes=("34084-4",),
        selection_mode=(
            DailyMedSelectionMode.PINNED_VERSION
            if pinned
            else DailyMedSelectionMode.STRICT_IDENTITY
        ),
        pinned_setid=SETID if pinned else None,
        pinned_spl_version="3" if pinned else None,
    )


def _outcome(
    *,
    query_id: str,
    execution: ExecutionStatus = ExecutionStatus.SUCCEEDED,
    coverage: CoverageStatus = CoverageStatus.COMPLETE,
    result: ResultStatus = ResultStatus.MATCHES,
    count: int = 1,
) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.DAILYMED,
        query_id=query_id,
        execution_status=execution,
        coverage_status=coverage,
        result_status=result,
        configured_bounds=ExecutionBounds(
            max_query_characters=512,
            max_pages=5,
            max_records=100,
            max_payload_bytes=5_242_880,
            max_total_seconds=30,
        ),
        valid_result_count=count,
        pages_completed=1 if coverage is not CoverageStatus.UNAVAILABLE else 0,
        truncated=coverage is CoverageStatus.PARTIAL,
        warning_codes=("incomplete_coverage",) if coverage is not CoverageStatus.COMPLETE else (),
        failure_id="failure:test" if execution is ExecutionStatus.FAILED else None,
    )


def _discovery_response(request: DailyMedDiscoveryRequest) -> DailyMedDiscoveryResponse:
    return DailyMedDiscoveryResponse(
        selection_request=request.selection_request,
        query_id=request.query_id,
        source_outcome_id="source-outcome:discovery",
        source_outcome=_outcome(query_id=request.query_id),
        candidate_set_snapshot_id="snapshot:discovery",
        discovery_manifest_id="artifact:discovery-manifest",
        candidate_ids=("candidate:selected",),
        decision_id="decision:selected",
        selection_status=LabelSelectionStatus.SELECTED,
        selected_candidate_id="candidate:selected",
        selected_setid=SETID,
        selected_spl_version="3",
    )


def _fetch_request() -> DailyMedFetchRequest:
    return DailyMedFetchRequest(
        selection_request=_selection_request(),
        query_id="query:fetch",
        decision_id="decision:selected",
        selected_candidate_id="candidate:selected",
        selected_setid=SETID,
        selected_spl_version="3",
    )


def _fetch_response(request: DailyMedFetchRequest) -> DailyMedFetchResponse:
    return DailyMedFetchResponse(
        request=request,
        source_outcome_id="source-outcome:fetch",
        source_outcome=_outcome(query_id=request.query_id),
        fetch_snapshot_id="snapshot:fetch",
        fetch_manifest_id="artifact:fetch-manifest",
        retained_response_id="retained-response:test",
        label_version_id="label-version:test",
        section_ids=("section:adverse-reactions",),
    )


class _Execution:
    def __init__(self) -> None:
        self.foreign_discovery = False
        self.foreign_fetch = False

    def discover(
        self, request: DailyMedDiscoveryRequest
    ) -> tuple[DailyMedDiscoveryResponse, tuple[object, ...], None]:
        values = _discovery_response(request).model_dump(mode="python")
        values.update(
            candidate_ids=(),
            decision_id=None,
            selection_status=None,
            selected_candidate_id=None,
            selected_setid=None,
            selected_spl_version=None,
        )
        values["source_outcome"] = _outcome(
            query_id=request.query_id,
            coverage=CoverageStatus.PARTIAL,
            result=ResultStatus.INDETERMINATE,
            count=0,
        ).model_dump(mode="python")
        response = DailyMedDiscoveryResponse.model_validate(values)
        if not self.foreign_discovery:
            return response, (), None
        payload = response.model_dump(mode="python")
        payload["query_id"] = "query:foreign"
        payload["source_outcome"]["query_id"] = "query:foreign"
        return DailyMedDiscoveryResponse.model_validate(payload), (), None

    def fetch(self, request: DailyMedFetchRequest) -> DailyMedFetchResponse:
        response = _fetch_response(request)
        if not self.foreign_fetch:
            return response
        payload = response.model_dump(mode="python")
        payload["request"]["query_id"] = "query:foreign"
        payload["source_outcome"]["query_id"] = "query:foreign"
        return DailyMedFetchResponse.model_validate(payload)


def test_structured_tools_require_exact_request_echoes() -> None:
    execution = cast(DailyMedExecutionPort, _Execution())
    discovery_request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(), query_id="query:discovery"
    )
    assert discover_dailymed_labels(discovery_request, execution=execution).decision_id is None
    fetch_request = _fetch_request()
    assert (
        fetch_dailymed_label(fetch_request, execution=execution).label_version_id
        == "label-version:test"
    )

    concrete = cast(_Execution, execution)
    concrete.foreign_discovery = True
    with pytest.raises(ValueError, match="another query"):
        discover_dailymed_labels(discovery_request, execution=execution)
    concrete.foreign_discovery = False
    concrete.foreign_fetch = True
    with pytest.raises(ValueError, match="another exact request"):
        fetch_dailymed_label(fetch_request, execution=execution)


def test_discovery_tool_rejects_decision_without_authoritative_context() -> None:
    request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(), query_id="query:unbacked"
    )

    class _UnbackedExecution(_Execution):
        def discover(
            self, request: DailyMedDiscoveryRequest
        ) -> tuple[DailyMedDiscoveryResponse, tuple[object, ...], None]:
            return _discovery_response(request), (), None

    execution = cast(DailyMedExecutionPort, _UnbackedExecution())
    with pytest.raises(ValueError, match="authoritative context"):
        discover_dailymed_labels(request, execution=execution)


def test_partial_discovery_can_never_select() -> None:
    values = _discovery_response(
        DailyMedDiscoveryRequest(selection_request=_selection_request(), query_id="query:partial")
    ).model_dump(mode="python")
    values["source_outcome"] = _outcome(
        query_id="query:partial",
        coverage=CoverageStatus.PARTIAL,
    ).model_dump(mode="python")
    with pytest.raises(ValidationError, match="may never select"):
        DailyMedDiscoveryResponse.model_validate(values)


@pytest.mark.parametrize(
    ("coverage", "result", "count", "candidate_ids", "status", "message"),
    [
        (
            CoverageStatus.COMPLETE,
            ResultStatus.NO_MATCH,
            0,
            (),
            LabelSelectionStatus.REVIEW_REQUIRED,
            "maps only to no_candidate",
        ),
        (
            CoverageStatus.COMPLETE,
            ResultStatus.MATCHES,
            1,
            ("candidate:one",),
            LabelSelectionStatus.REVIEW_REQUIRED,
            "at least two unresolved candidates",
        ),
        (
            CoverageStatus.PARTIAL,
            ResultStatus.MATCHES,
            1,
            ("candidate:one",),
            LabelSelectionStatus.NO_CANDIDATE,
            "every partial match maps to review_required",
        ),
    ],
)
def test_discovery_response_rejects_non_exhaustive_decision_shapes(
    coverage: CoverageStatus,
    result: ResultStatus,
    count: int,
    candidate_ids: tuple[str, ...],
    status: LabelSelectionStatus,
    message: str,
) -> None:
    request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(), query_id="query:matrix"
    )
    values = _discovery_response(request).model_dump(mode="python")
    values.update(
        candidate_ids=candidate_ids,
        selection_status=status,
        selected_candidate_id=None,
        selected_setid=None,
        selected_spl_version=None,
    )
    values["source_outcome"] = _outcome(
        query_id=request.query_id,
        coverage=coverage,
        result=result,
        count=count,
    ).model_dump(mode="python")

    with pytest.raises(ValidationError, match=message):
        DailyMedDiscoveryResponse.model_validate(values)


def test_discovery_response_accepts_authoritative_review_and_no_candidate_shapes() -> None:
    request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(), query_id="query:matrix-positive"
    )
    values = _discovery_response(request).model_dump(mode="python")
    values.update(
        candidate_ids=("candidate:one", "candidate:two"),
        selection_status=LabelSelectionStatus.REVIEW_REQUIRED,
        selected_candidate_id=None,
        selected_setid=None,
        selected_spl_version=None,
    )
    values["source_outcome"] = _outcome(
        query_id=request.query_id,
        count=2,
    ).model_dump(mode="python")
    assert DailyMedDiscoveryResponse.model_validate(values).selection_status is (
        LabelSelectionStatus.REVIEW_REQUIRED
    )

    values.update(candidate_ids=(), selection_status=LabelSelectionStatus.NO_CANDIDATE)
    values["source_outcome"] = _outcome(
        query_id=request.query_id,
        result=ResultStatus.NO_MATCH,
        count=0,
    ).model_dump(mode="python")
    assert DailyMedDiscoveryResponse.model_validate(values).selection_status is (
        LabelSelectionStatus.NO_CANDIDATE
    )


def test_indeterminate_discovery_has_no_decision_row() -> None:
    values = _discovery_response(
        DailyMedDiscoveryRequest(
            selection_request=_selection_request(), query_id="query:indeterminate"
        )
    ).model_dump(mode="python")
    values.update(candidate_ids=(), selection_status=None, decision_id="decision:forged")
    values["selected_candidate_id"] = None
    values["selected_setid"] = None
    values["selected_spl_version"] = None
    values["source_outcome"] = _outcome(
        query_id="query:indeterminate",
        coverage=CoverageStatus.PARTIAL,
        result=ResultStatus.INDETERMINATE,
        count=0,
    ).model_dump(mode="python")
    with pytest.raises(ValidationError, match="no decision row"):
        DailyMedDiscoveryResponse.model_validate(values)


def test_pinned_selection_and_fetch_require_exact_identity() -> None:
    request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(pinned=True), query_id="query:pinned"
    )
    values = _discovery_response(request).model_dump(mode="python")
    values["selected_spl_version"] = "4"
    with pytest.raises(ValidationError, match="exact request pin"):
        DailyMedDiscoveryResponse.model_validate(values)

    with pytest.raises(ValidationError, match="exact request pin"):
        DailyMedFetchRequest(
            selection_request=_selection_request(pinned=True),
            query_id="query:fetch",
            decision_id="decision:selected",
            selected_candidate_id="candidate:selected",
            selected_setid=SETID,
            selected_spl_version="4",
        )


def test_unusable_fetch_cannot_expose_stable_evidence() -> None:
    values = _fetch_response(_fetch_request()).model_dump(mode="python")
    values["source_outcome"] = _outcome(
        query_id="query:fetch",
        execution=ExecutionStatus.FAILED,
        coverage=CoverageStatus.UNAVAILABLE,
        result=ResultStatus.INDETERMINATE,
        count=0,
    ).model_dump(mode="python")
    with pytest.raises(ValidationError, match="stable label identities require"):
        DailyMedFetchResponse.model_validate(values)


def test_dailymed_execution_projections_bind_exact_persisted_identities() -> None:
    discovery_request = DailyMedDiscoveryRequest(
        selection_request=_selection_request(), query_id="query:projection-discovery"
    )
    discovery_response = _discovery_response(discovery_request)
    discovery = DailyMedDiscoveryExecutionProjection(
        run_id=RUN_ID,
        scope_id="scope:test",
        task_id="source-task:test:dailymed",
        attempt_id="source-task-attempt:test",
        response=discovery_response,
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:projection-discovery",
            acquisition_intent_id="acquisition-intent:sha256:" + "a" * 64,
            acquisition_ordinal=0,
            operation="search",
            query_id=discovery_response.query_id,
            source_outcome_id=discovery_response.source_outcome_id,
            snapshot_id=discovery_response.candidate_set_snapshot_id,
        ),
    )
    assert discovery.response == discovery_response

    fetch_request = DailyMedFetchRequest(
        selection_request=discovery_response.selection_request,
        query_id=discovery_response.query_id,
        decision_id=discovery_response.decision_id,
        selected_candidate_id=discovery_response.selected_candidate_id,
        selected_setid=discovery_response.selected_setid,
        selected_spl_version=discovery_response.selected_spl_version,
    )
    fetch_response = _fetch_response(fetch_request)
    fetched = DailyMedFetchExecutionProjection(
        run_id=RUN_ID,
        scope_id="scope:test",
        task_id="source-task:test:dailymed",
        attempt_id="source-task-attempt:test",
        response=fetch_response,
        acquisition=AcquisitionOutcomeRef(
            run_id=RUN_ID,
            source=SourceType.DAILYMED,
            acquisition_id="acquisition:projection-fetch",
            acquisition_intent_id="acquisition-intent:sha256:" + "b" * 64,
            acquisition_ordinal=1,
            operation="fetch",
            query_id=fetch_response.request.query_id,
            source_outcome_id=fetch_response.source_outcome_id,
            snapshot_id=fetch_response.fetch_snapshot_id,
        ),
        section_evidence=(
            DailyMedSectionEvidenceProjection(
                section_id=fetch_response.section_ids[0],
                evidence_id="evidence:projection-section",
                content_hash="sha256:" + "c" * 64,
                locator_ref="locator:projection-section",
            ),
        ),
    )
    assert fetched.section_evidence[0].section_id == fetch_response.section_ids[0]

    stale = fetched.model_dump(mode="python")
    stale["section_evidence"][0]["section_id"] = "section:foreign"
    with pytest.raises(ValidationError, match="exact eligible section set"):
        DailyMedFetchExecutionProjection.model_validate(stale)
