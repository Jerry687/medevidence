"""Strict request and response contracts for PubMed tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    CoverageStatus,
    DrugConcept,
    ExecutionBounds,
    ExecutionStatus,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    ResultStatus,
    SourceOutcome,
    SourceType,
)
from medevidence.tools import ResearchPubMedRequest, SearchPubMedRequest, SearchPubMedResponse
from medevidence.tools.contracts import AcquisitionIntentInput
from medevidence.tools.ports import (
    FaersReportApplicationPort,
    PersistedAcquisition,
    PersistedPublicationBinding,
    PersistedPublicationLineageEdge,
    PubMedSearchExecution,
    ResponseObservation,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_faers_report_application_port_has_stable_typed_boundary() -> None:
    hints = get_type_hints(FaersReportApplicationPort.__call__)

    assert hints["request"].__name__ == "M1BResearchRequestV1"
    assert hints["return"].__name__ == "M1BResearchReportV1"


def _scope(*, term: str = "semaglutide") -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="m1a.drug.semaglutide", preferred_term=term),),
        adverse_reactions=(
            AdverseEventConcept(
                concept_id="m1a.event.gastrointestinal",
                preferred_term="gastrointestinal",
            ),
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=1,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _outcome(pmids: int) -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES if pmids else ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=pmids,
        pages_completed=1,
        truncated=False,
    )


def test_requests_are_strict_frozen_and_forbid_unknown_fields() -> None:
    request = SearchPubMedRequest(scope=_scope())
    with pytest.raises(ValidationError):
        request.scope = _scope(term="changed")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SearchPubMedRequest.model_validate({"scope": _scope(), "url": "https://example.test"})


def test_acquisition_intent_identity_matches_merged_adr010_vector() -> None:
    intent = AcquisitionIntentInput.create(
        attempt_id="attempt:00000000-0000-4000-8000-000000000003",
        run_id="run:00000000-0000-4000-8000-000000000002",
        run_intent_id=(
            "run-intent:sha256:9cea22d71d57ae4edfa4d4a4b3587b72b974defcd9e8421831e732ee84f032d3"
        ),
        created_at_utc=datetime(2026, 8, 6, 12, 0, 1, tzinfo=UTC),
        acquisition_ordinal=0,
        operation="search",
        query=('("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])'),
    )
    assert intent.acquisition_intent_id == (
        "acquisition-intent:sha256:fe9f621ba82c3a783382764171022c641e399453f6b80650380bb54a1df9cd3d"
    )

    with pytest.raises(ValidationError, match="merged journal intent"):
        AcquisitionIntentInput.model_validate(
            {
                **intent.model_dump(mode="python"),
                "acquisition_intent_id": f"acquisition-intent:sha256:{'f' * 64}",
            }
        )


def test_research_request_requires_exact_runtime_ids_and_code_revision() -> None:
    request = ResearchPubMedRequest(
        request_id="request:00000000-0000-4000-8000-000000000001",
        run_id="run:00000000-0000-4000-8000-000000000002",
        created_at_utc=NOW,
        code_revision="a" * 40,
        scope=_scope(),
    )

    assert request.schema_version == "1.0"
    with pytest.raises(ValidationError):
        ResearchPubMedRequest(
            request_id=request.request_id,
            run_id=request.run_id,
            created_at_utc=NOW,
            code_revision="not-a-commit",
            scope=request.scope,
        )


def test_scope_must_match_exact_constrained_profile() -> None:
    broad = ResearchScope.create(
        drugs=_scope().drugs,
        adverse_reactions=_scope().adverse_reactions,
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(
            max_query_characters=512,
            max_pages=2,
            max_total_seconds=30,
        ),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )
    with pytest.raises(ValidationError, match="M1A_CONSTRAINED_V1"):
        SearchPubMedRequest(scope=broad)


def test_search_response_requires_numeric_unique_sorted_pmids_and_exact_count() -> None:
    valid = SearchPubMedResponse(
        query='("semaglutide"[Title/Abstract]) AND ("gastrointestinal"[Title/Abstract])',
        query_id="query:test",
        pmids=("2", "10"),
        total_available=2,
        source_outcome=_outcome(2),
    )
    assert valid.pmids == ("2", "10")

    with pytest.raises(ValidationError, match="numerically sorted"):
        SearchPubMedResponse(
            query=valid.query,
            query_id=valid.query_id,
            pmids=("10", "2"),
            total_available=2,
            source_outcome=_outcome(2),
        )
    with pytest.raises(ValidationError, match="count"):
        SearchPubMedResponse(
            query=valid.query,
            query_id=valid.query_id,
            pmids=("2",),
            total_available=2,
            source_outcome=_outcome(2),
        )


def test_search_response_rejects_complete_untruncated_excess_total() -> None:
    pmids = tuple(str(value) for value in range(1, 101))
    complete = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=100,
        pages_completed=1,
        truncated=False,
    )
    with pytest.raises(ValidationError, match="partial truncated"):
        SearchPubMedResponse(
            query="fixture",
            query_id="query:test",
            pmids=pmids,
            total_available=101,
            source_outcome=complete,
        )

    partial = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=100,
        pages_completed=1,
        truncated=True,
        warning_codes=("source_coverage_incomplete",),
    )
    response = SearchPubMedResponse(
        query="fixture",
        query_id="query:test",
        pmids=pmids,
        total_available=101,
        source_outcome=partial,
    )
    assert response.source_outcome.coverage_status is CoverageStatus.PARTIAL


def _observation(**changes: object) -> ResponseObservation:
    values: dict[str, object] = {
        "body": b"fixture",
        "observed_at_utc": NOW + timedelta(seconds=1),
        "headers": (("content-type", "application/xml"),),
        "http_status": 200,
        "body_complete": True,
        "termination_reason": "complete_response",
    }
    values.update(changes)
    return ResponseObservation.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"observed_at_utc": NOW.replace(tzinfo=None)}, "timezone-aware UTC"),
        ({"http_status": 999}, "less than or equal to 599"),
        ({"body": b"x" * 5_242_881}, "at most 5242880"),
        ({"headers": (("authorization", "secret"),)}, "forbidden evidence header"),
        ({"headers": (("x-unknown", "value"),)}, "forbidden evidence header"),
        (
            {
                "headers": (
                    ("content-type", "application/xml"),
                    ("content-length", "7"),
                )
            },
            "sorted and unique",
        ),
        (
            {
                "headers": (
                    ("content-type", "application/xml"),
                    ("content-type", "text/xml"),
                )
            },
            "sorted and unique",
        ),
        ({"headers": (("content-type", "x" * 513),)}, "at most 512"),
        ({"headers": (("content-type", "application/xml\r\nsecret"),)}, "control-free"),
        (
            {"body_complete": False, "termination_reason": "complete_response"},
            "must match termination_reason",
        ),
        (
            {"body": b"", "body_complete": False, "termination_reason": "stream_error"},
            "retained nonempty prefix",
        ),
    ],
)
def test_response_observation_rejects_untrusted_adapter_output(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _observation(**changes)


def _search_execution(**changes: object) -> PubMedSearchExecution:
    values: dict[str, object] = {
        "response": SearchPubMedResponse(
            query="fixture",
            query_id="query:test",
            pmids=("1",),
            total_available=1,
            source_outcome=_outcome(1),
        ),
        "started_at_utc": NOW,
        "completed_at_utc": NOW + timedelta(seconds=2),
        "attempts_used": 1,
        "observations": (_observation(),),
    }
    values.update(changes)
    return PubMedSearchExecution.model_validate(values)


@pytest.mark.parametrize("attempts", [0, 3])
def test_execution_rejects_attempts_outside_frozen_bound(attempts: int) -> None:
    with pytest.raises(ValidationError):
        _search_execution(attempts_used=attempts)


def test_execution_rejects_five_observations_and_invalid_time_order() -> None:
    with pytest.raises(ValidationError, match="at most 4"):
        _search_execution(observations=tuple(_observation() for _ in range(5)))
    with pytest.raises(ValidationError, match="completion precedes start"):
        _search_execution(completed_at_utc=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        _search_execution(started_at_utc=NOW.replace(tzinfo=None))


def test_execution_failure_fields_must_match_terminal_outcome() -> None:
    with pytest.raises(ValidationError, match="required exactly"):
        _search_execution(failure_code="timeout", redacted_detail="unexpected")

    failed = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
        warning_codes=("source_coverage_incomplete",),
        failure_id="failure:test",
    )
    response = SearchPubMedResponse(
        query="fixture",
        query_id="query:test",
        pmids=("1",),
        total_available=1,
        source_outcome=failed,
    )
    with pytest.raises(ValidationError, match="required exactly"):
        _search_execution(response=response)


def test_execution_enforces_manifest_evidence_semantics() -> None:
    with pytest.raises(ValidationError, match="zero observations"):
        _search_execution(observations=())
    with pytest.raises(ValidationError, match="final nonempty complete HTTP 2xx"):
        _search_execution(observations=(_observation(body=b""),))
    with pytest.raises(ValidationError, match="final nonempty complete HTTP 2xx"):
        _search_execution(
            observations=(_observation(body_complete=False, termination_reason="stream_error"),)
        )
    with pytest.raises(ValidationError, match="final nonempty complete HTTP 2xx"):
        _search_execution(observations=(_observation(http_status=503),))
    with pytest.raises(ValidationError, match="exceed 5,242,880"):
        _search_execution(
            observations=(
                _observation(body=b"a" * 3_000_000),
                _observation(
                    body=b"b" * 3_000_000,
                    observed_at_utc=NOW + timedelta(seconds=2),
                ),
            )
        )

    partial_matches = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.PARTIAL,
        result_status=ResultStatus.MATCHES,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
        warning_codes=("source_coverage_incomplete",),
    )
    response = SearchPubMedResponse(
        query="fixture",
        query_id="query:test",
        pmids=("1",),
        total_available=1,
        source_outcome=partial_matches,
    )
    with pytest.raises(ValidationError, match="retained nonempty HTTP 2xx"):
        _search_execution(
            response=response,
            observations=(
                _observation(
                    http_status=503,
                    body_complete=False,
                    termination_reason="stream_error",
                ),
            ),
        )


def test_failed_unavailable_execution_is_the_only_zero_observation_case() -> None:
    unavailable = SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:test",
        execution_status=ExecutionStatus.FAILED,
        coverage_status=CoverageStatus.UNAVAILABLE,
        result_status=ResultStatus.INDETERMINATE,
        configured_bounds=ExecutionBounds.from_scope(_scope()),
        valid_result_count=0,
        pages_completed=0,
        truncated=False,
        warning_codes=("source_unavailable",),
        failure_id="failure:unavailable",
    )
    execution = _search_execution(
        response=SearchPubMedResponse(
            query="fixture",
            query_id="query:test",
            pmids=(),
            total_available=0,
            source_outcome=unavailable,
        ),
        observations=(),
        failure_code="timeout",
        redacted_detail="synthetic timeout",
    )
    assert execution.observations == ()


def _publication_binding(**changes: object) -> PersistedPublicationBinding:
    publication_artifact_id = f"sha256:{'a' * 64}"
    manifest_id = f"sha256:{'1' * 64}"
    values: dict[str, object] = {
        "pmid": "10",
        "publication_version_id": f"pubmed:10:sha256:{'a' * 64}",
        "publication_artifact_id": publication_artifact_id,
        "snapshot_id": manifest_id,
        "manifest_id": manifest_id,
        "artifact_ids": tuple(sorted((publication_artifact_id, manifest_id))),
        "lineage_edges": (
            {
                "parent_artifact_id": publication_artifact_id,
                "child_artifact_id": manifest_id,
            },
        ),
    }
    values.update(changes)
    return PersistedPublicationBinding.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"publication_version_id": f"pubmed:11:sha256:{'a' * 64}"}, "PMID"),
        ({"publication_artifact_id": f"sha256:{'b' * 64}"}, "content identity"),
        ({"manifest_id": f"sha256:{'9' * 64}"}, "snapshot"),
        (
            {"artifact_ids": tuple(sorted((f"sha256:{'1' * 64}", f"sha256:{'2' * 64}")))},
            "include publication and manifest",
        ),
        (
            {"artifact_ids": tuple(sorted((f"sha256:{'a' * 64}", f"sha256:{'2' * 64}")))},
            "include publication and manifest",
        ),
        ({"artifact_ids": (f"sha256:{'a' * 64}", f"sha256:{'1' * 64}")}, "sorted"),
        (
            {"artifact_ids": (f"sha256:{'1' * 64}", f"sha256:{'1' * 64}")},
            "sorted and unique",
        ),
        (
            {"artifact_ids": tuple(f"sha256:{value:064x}" for value in range(1, 10))},
            "at most 8",
        ),
        ({"lineage_edges": ()}, "at least 1"),
        (
            {
                "lineage_edges": (
                    {
                        "parent_artifact_id": f"sha256:{'2' * 64}",
                        "child_artifact_id": f"sha256:{'1' * 64}",
                    },
                )
            },
            "exact publication and manifest",
        ),
        (
            {
                "lineage_edges": (
                    {
                        "parent_artifact_id": f"sha256:{'a' * 64}",
                        "child_artifact_id": f"sha256:{'2' * 64}",
                    },
                )
            },
            "exact publication and manifest",
        ),
    ],
)
def test_persisted_publication_binding_rejects_identity_or_lineage_drift(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _publication_binding(**changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": "2.0"}, "Input should be '1.0'"),
        ({"lineage_type": "manifest_to_publication"}, "publication_to_manifest"),
        ({"lineage_ordinal": 1}, "Input should be 0"),
        ({"parent_artifact_id": f"sha256:{'1' * 64}"}, "distinct"),
        ({"provider_row_id": "forbidden"}, "extra_forbidden"),
    ],
)
def test_publication_lineage_edge_rejects_wrong_relationship(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "parent_artifact_id": f"sha256:{'a' * 64}",
        "child_artifact_id": f"sha256:{'1' * 64}",
    }
    values.update(changes)
    with pytest.raises(ValidationError, match=message):
        PersistedPublicationLineageEdge.model_validate(values)


def test_persisted_acquisition_rejects_extra_or_unrelated_publication_binding() -> None:
    binding = _publication_binding()
    values = {
        "acquisition_intent_id": f"acquisition-intent:sha256:{'7' * 64}",
        "snapshot_id": f"sha256:{'1' * 64}",
        "manifest_id": f"sha256:{'1' * 64}",
        "registration_envelope_id": (f"registration-envelope:acquisition:sha256:{'4' * 64}"),
    }
    with pytest.raises(ValidationError, match="at most 1"):
        PersistedAcquisition(
            **values,
            publication_bindings=(binding, binding),
        )
    with pytest.raises(ValidationError, match="belong to its acquisition"):
        PersistedAcquisition(
            **values,
            publication_bindings=(
                _publication_binding(
                    snapshot_id=f"sha256:{'5' * 64}",
                    manifest_id=f"sha256:{'5' * 64}",
                    artifact_ids=tuple(sorted((f"sha256:{'a' * 64}", f"sha256:{'5' * 64}"))),
                    lineage_edges=(
                        {
                            "parent_artifact_id": f"sha256:{'a' * 64}",
                            "child_artifact_id": f"sha256:{'5' * 64}",
                        },
                    ),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="snapshot identity"):
        PersistedAcquisition(
            **{**values, "manifest_id": f"sha256:{'6' * 64}"},
            publication_bindings=(),
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PersistedPublicationBinding.model_validate(
            {**binding.model_dump(mode="python"), "source_url": "forbidden"}
        )


def _failed_unavailable_response() -> SearchPubMedResponse:
    return SearchPubMedResponse(
        query="fixture",
        query_id="query:test",
        pmids=(),
        total_available=0,
        source_outcome=SourceOutcome(
            source=SourceType.PUBMED,
            query_id="query:test",
            execution_status=ExecutionStatus.FAILED,
            coverage_status=CoverageStatus.UNAVAILABLE,
            result_status=ResultStatus.INDETERMINATE,
            configured_bounds=ExecutionBounds.from_scope(_scope()),
            valid_result_count=0,
            pages_completed=0,
            truncated=False,
            warning_codes=("source_unavailable",),
            failure_id="failure:unavailable",
        ),
    )


@pytest.mark.parametrize(
    "detail",
    [
        "Authorization: Bearer synthetic-secret\nCookie: session=synthetic",
        "authorization: value",
        "PROXY-AUTHORIZATION=value",
        "cookie: value",
        "set-cookie: value",
        "bearer value",
        "password=value",
        "passwd=value",
        "synthetic secret",
        "api-key=value",
        "api_key=value",
        "access-token=value",
        "access_token=value",
        "refresh-token=value",
        "refresh_token=value",
        "session=value",
        " leading whitespace",
        "trailing whitespace ",
        "tab\tvalue",
        "line\rvalue",
        "line\nvalue",
    ],
)
def test_redacted_detail_rejects_credentials_controls_and_untrimmed_text(
    detail: str,
) -> None:
    with pytest.raises(ValidationError, match="redacted detail"):
        _search_execution(
            response=_failed_unavailable_response(),
            observations=(),
            failure_code="timeout",
            redacted_detail=detail,
        )


@pytest.mark.parametrize(
    "detail",
    ["transport timeout after bounded retries", "upstream status 503", "x" * 512],
)
def test_redacted_detail_accepts_safe_bounded_single_line_messages(detail: str) -> None:
    execution = _search_execution(
        response=_failed_unavailable_response(),
        observations=(),
        failure_code="timeout",
        redacted_detail=detail,
    )
    assert execution.redacted_detail == detail


@pytest.mark.parametrize("detail", ["", " ", "x" * 513])
def test_redacted_detail_rejects_blank_or_oversize_messages(detail: str) -> None:
    with pytest.raises(ValidationError):
        _search_execution(
            response=_failed_unavailable_response(),
            observations=(),
            failure_code="timeout",
            redacted_detail=detail,
        )
