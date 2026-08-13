"""In-process route inventory, success, and runtime-error tests."""

from __future__ import annotations

import json
import logging
import re
import warnings
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from medevidence.api import ApiDependencies, create_app
from medevidence.api.errors import (
    ApplicationFailure,
    ArtifactIntegrityFailure,
    DeadlineExceededFailure,
    PersistenceIntegrityFailure,
    PersistenceUnavailableFailure,
    StorageBusyFailure,
    StorageCapacityFailure,
    ToolContractFailure,
)
from medevidence.api.routes import REQUEST_EXAMPLE, _complete_no_match_example
from medevidence.domain import M1BResearchReportV1, M1BResearchRequestV1, ResearchReport
from medevidence.tools import ResearchPubMedRequest

pytestmark = pytest.mark.enable_socket

REQUEST_ID = "request:00000000-0000-4000-8000-000000000001"
RUN_ID = "run:00000000-0000-4000-8000-000000000002"
NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _client(
    application: Callable[[ResearchPubMedRequest], ResearchReport],
    *,
    request_id_factory: Callable[[], str] | None = None,
    dailymed_application: (Callable[[M1BResearchRequestV1], M1BResearchReportV1] | None) = None,
    faers_application: (Callable[[M1BResearchRequestV1], M1BResearchReportV1] | None) = None,
) -> TestClient:
    return TestClient(
        create_app(
            ApiDependencies(
                application=application,
                request_id_factory=request_id_factory or (lambda: REQUEST_ID),
                run_id_factory=lambda: RUN_ID,
                utc_now=lambda: NOW,
                code_revision="0" * 40,
                dailymed_application=dailymed_application,
                faers_application=faers_application,
            )
        )
    )


def _report(_: ResearchPubMedRequest) -> ResearchReport:
    return ResearchReport.model_validate_json(json.dumps(_complete_no_match_example()))


def test_route_inventory_has_one_application_operation_and_openapi() -> None:
    client = _client(_report)
    paths = client.app.openapi()["paths"]
    assert set(paths) == {"/v1/research/pubmed"}
    assert set(paths["/v1/research/pubmed"]) == {"post"}
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/").status_code == 404


def test_additive_dailymed_route_returns_closed_nonexportable_report() -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case

    request, section, ref, outcome = trusted_case()

    def dailymed_application(observed: M1BResearchRequestV1) -> M1BResearchReportV1:
        from medevidence.tools import build_dailymed_report

        assert observed == request
        return build_dailymed_report(
            observed,
            report_id=section.report_id,
            run_id=section.run_id,
            source_sections=(section,),
            retrieved_as_of=NOW,
            trusted_acquisition_outcomes=((section.request, ref, outcome),),
            trusted_selection_decisions=(),
        )

    client = _client(_report, dailymed_application=dailymed_application)
    response = client.post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert response.json()["schema_version"] == "m1b.report.v1"
    assert response.json()["status"] == "draft"
    assert response.json()["exportable"] is False
    assert response.json()["source_plan"] == [
        {
            "schema_version": "m1b.source-plan.v1",
            "source": "dailymed",
            "planning_status": "selected",
            "reason_code": None,
            "reason": None,
        }
    ]
    assert set(client.app.openapi()["paths"]) == {
        "/v1/research/pubmed",
        "/v1/research/dailymed",
    }


def test_additive_faers_route_is_conditional_and_returns_closed_report() -> None:
    from tests.unit.tools.test_faers import RUN_ID as FAERS_RUN_ID
    from tests.unit.tools.test_faers import _execution
    from tests.unit.tools.test_faers_report import NOW as FAERS_NOW
    from tests.unit.tools.test_faers_report import REPORT_ID, _report_request

    from medevidence.tools import build_faers_report

    request = _report_request()
    execution = _execution(request.faers_query_requests[0])

    def faers_application(observed: M1BResearchRequestV1) -> M1BResearchReportV1:
        assert observed == request
        return build_faers_report(
            observed,
            report_id=REPORT_ID,
            run_id=FAERS_RUN_ID,
            executions=(execution,),
            retrieved_as_of=FAERS_NOW,
        )

    client = _client(_report, faers_application=faers_application)
    response = client.post("/v1/research/faers", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "m1b.report.v1"
    assert body["status"] == "draft"
    assert body["exportable"] is False
    assert body["source_plan"] == [
        {
            "schema_version": "m1b.source-plan.v1",
            "source": "faers",
            "planning_status": "selected",
            "reason_code": None,
            "reason": None,
        }
    ]
    assert set(client.app.openapi()["paths"]) == {
        "/v1/research/pubmed",
        "/v1/research/faers",
    }


@pytest.mark.parametrize(
    "path,value",
    (
        (("scope", "query_bounds", "max_query_characters"), 512.0),
        (("faers_query_requests", 0, "effective_total_deadline_ms"), 30000.0),
        (("faers_query_requests", 0, "execution_bounds", "max_pages"), True),
        (("faers_query_requests", 0, "execution_bounds", "page_size"), "100"),
        (("faers_query_requests", 0, "execution_bounds", "max_buckets"), 100.5),
        (
            ("faers_query_requests", 0, "execution_bounds", "max_response_bytes"),
            10**100,
        ),
    ),
)
def test_faers_route_rejects_integer_type_drift_before_application_execution(
    path: tuple[str | int, ...], value: object
) -> None:
    from tests.unit.tools.test_faers_report import _report_request

    payload = _report_request().model_dump(mode="json")
    target: Any = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    executed = False

    def faers_application(_: M1BResearchRequestV1) -> M1BResearchReportV1:
        nonlocal executed
        executed = True
        raise AssertionError("invalid raw request must not execute the FAERS application")

    response = _client(_report, faers_application=faers_application).post(
        "/v1/research/faers",
        content=json.dumps(payload),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert executed is False


@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
def test_faers_route_rejects_missing_response_presence_and_request_drift(
    entrypoint: str,
) -> None:
    from tests.unit.tools.test_faers import RUN_ID as FAERS_RUN_ID
    from tests.unit.tools.test_faers import _execution
    from tests.unit.tools.test_faers_report import NOW as FAERS_NOW
    from tests.unit.tools.test_faers_report import REPORT_ID, _report_request

    from medevidence.tools import build_faers_report

    request = _report_request()
    valid = build_faers_report(
        request,
        report_id=REPORT_ID,
        run_id=FAERS_RUN_ID,
        executions=(_execution(request.faers_query_requests[0]),),
        retrieved_as_of=FAERS_NOW,
    )
    payload = deepcopy(valid.model_dump(mode="python"))
    del payload["source_sections"][0]["result"]["limitations"]
    returned: object = payload
    if entrypoint == "model_construct":
        returned = M1BResearchReportV1.model_construct(**payload)
    response = _client(
        _report,
        faers_application=lambda _: returned,  # type: ignore[arg-type,return-value]
    ).post("/v1/research/faers", json=request.model_dump(mode="json"))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"

    forged = valid.model_copy(update={"request_id": "request:00000000-0000-4000-8000-000000000099"})
    drift_response = _client(
        _report,
        faers_application=lambda _: forged,
    ).post("/v1/research/faers", json=request.model_dump(mode="json"))
    assert drift_response.status_code == 502
    assert drift_response.json()["error"]["code"] == "tool_contract_error"


def test_dailymed_route_rejects_response_request_drift() -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case

    request, section, ref, outcome = trusted_case()
    from medevidence.tools import build_dailymed_report

    valid = build_dailymed_report(
        request,
        report_id=section.report_id,
        run_id=section.run_id,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    )
    forged = valid.model_copy(update={"request_id": "request:00000000-0000-4000-8000-000000000099"})
    response = _client(
        _report,
        dailymed_application=lambda _: forged,
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"


@pytest.mark.parametrize(
    "path",
    (
        ("schema_version",),
        ("status",),
        ("exportable",),
        ("safety_notice",),
        ("source_plan", 0, "schema_version"),
        ("source_plan", 0, "reason_code"),
        ("source_plan", 0, "reason"),
        ("scope", "schema_version"),
        ("scope", "date_range"),
        ("scope", "language"),
        ("source_sections", 0, "schema_version"),
        ("source_sections", 0, "section_kind"),
        ("source_sections", 0, "source"),
        ("source_sections", 0, "request", "schema_version"),
        ("source_sections", 0, "request", "pinned_setid"),
        ("source_sections", 0, "request", "pinned_spl_version"),
        ("source_sections", 0, "label_version"),
        ("source_sections", 0, "retained_response"),
        ("source_sections", 0, "label_sections"),
        ("source_sections", 0, "locators"),
        ("source_sections", 0, "limitations"),
        ("source_outcomes", 0, "schema_version"),
        ("source_outcomes", 0, "failure_id"),
        ("source_outcomes", 0, "warning_codes"),
    ),
)
@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
def test_dailymed_route_rejects_missing_required_serialized_fields(
    path: tuple[str | int, ...], entrypoint: str
) -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case

    from medevidence.tools import build_dailymed_report

    request, section, ref, outcome = trusted_case()
    valid = build_dailymed_report(
        request,
        report_id=section.report_id,
        run_id=section.run_id,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    )
    payload = deepcopy(valid.model_dump(mode="python"))
    target: object = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    del target[path[-1]]  # type: ignore[index]
    returned: object = payload
    if entrypoint == "model_construct":
        returned = M1BResearchReportV1.model_construct(**payload)

    response = _client(
        _report,
        dailymed_application=lambda _: returned,  # type: ignore[arg-type,return-value]
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"


@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
@pytest.mark.parametrize(
    "path",
    (
        ("source_sections", 0, "label_version", "effective_date"),
        ("source_sections", 0, "retained_response", "body_complete"),
        ("source_sections", 0, "label_sections", 0, "parent_section_id"),
    ),
)
def test_dailymed_route_rejects_missing_stable_nested_response_fields(
    path: tuple[str | int, ...], entrypoint: str
) -> None:
    from tests.unit.tools.test_dailymed_report import _stable_report_case

    request, valid = _stable_report_case()
    payload = deepcopy(valid.model_dump(mode="python"))
    target: object = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    del target[path[-1]]  # type: ignore[index]
    returned: object = payload
    if entrypoint == "model_construct":
        returned = M1BResearchReportV1.model_construct(**payload)

    response = _client(
        _report,
        dailymed_application=lambda _: returned,  # type: ignore[arg-type,return-value]
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"


@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
def test_dailymed_route_rejects_missing_domain_warning_schema_version(entrypoint: str) -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case

    from medevidence.domain import DomainWarning
    from medevidence.tools import build_dailymed_report

    request, section, ref, outcome = trusted_case()
    valid = build_dailymed_report(
        request,
        report_id=section.report_id,
        run_id=section.run_id,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    ).model_copy(
        update={
            "warnings": (
                DomainWarning(code="source_coverage_incomplete", message="Coverage is partial."),
            )
        }
    )
    payload = deepcopy(valid.model_dump(mode="python"))
    del payload["warnings"][0]["schema_version"]
    returned: object = payload
    if entrypoint == "model_construct":
        returned = M1BResearchReportV1.model_construct(**payload)

    response = _client(
        _report,
        dailymed_application=lambda _: returned,  # type: ignore[arg-type,return-value]
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"


@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
def test_dailymed_route_rejects_missing_inclusive_date_precision(entrypoint: str) -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case

    from medevidence.domain import InclusiveDateRange, ResearchScope
    from medevidence.tools import build_dailymed_report

    request, section, ref, outcome = trusted_case()
    scope = ResearchScope.create(
        drugs=request.scope.drugs,
        adverse_reactions=request.scope.adverse_reactions,
        date_range=InclusiveDateRange(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)),
        selected_sources=request.scope.selected_sources,
        comparison_intent=request.scope.comparison_intent,
        query_bounds=request.scope.query_bounds,
        result_bounds=request.scope.result_bounds,
    )
    request = request.model_copy(update={"scope": scope})
    valid = build_dailymed_report(
        request,
        report_id=section.report_id,
        run_id=section.run_id,
        source_sections=(section,),
        retrieved_as_of=NOW,
        trusted_acquisition_outcomes=((section.request, ref, outcome),),
        trusted_selection_decisions=(),
    )
    payload = deepcopy(valid.model_dump(mode="python"))
    del payload["scope"]["date_range"]["precision"]
    returned: object = payload
    if entrypoint == "model_construct":
        returned = M1BResearchReportV1.model_construct(**payload)

    response = _client(
        _report,
        dailymed_application=lambda _: returned,  # type: ignore[arg-type,return-value]
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"


@pytest.mark.parametrize("entrypoint", ("mapping", "model_construct"))
def test_dailymed_route_rejects_every_missing_locator_field(entrypoint: str) -> None:
    from tests.unit.tools.test_dailymed_report import _stable_report_case

    request, valid = _stable_report_case()
    locator_fields = tuple(type(valid.source_sections[0].locators[0]).model_fields)
    assert len(locator_fields) == 44
    for field in locator_fields:
        payload = deepcopy(valid.model_dump(mode="python"))
        del payload["source_sections"][0]["locators"][0][field]
        returned: object = payload
        if entrypoint == "model_construct":
            returned = M1BResearchReportV1.model_construct(**payload)
        response = _client(
            _report,
            dailymed_application=lambda _, value=returned: value,  # type: ignore[arg-type,return-value]
        ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))
        assert response.status_code == 502, field
        assert response.json()["error"]["code"] == "tool_contract_error", field


@pytest.mark.parametrize("state", ("degraded", "failed_fetch", "stable"))
def test_dailymed_route_returns_representative_report_states(state: str) -> None:
    if state == "stable":
        from tests.unit.tools.test_dailymed_report import _stable_report_case

        request, report = _stable_report_case()
    else:
        from tests.unit.domain.test_reports import dailymed_report_for_acquisition_counts

        report, request, _, _ = dailymed_report_for_acquisition_counts(
            (1,) if state == "degraded" else (2,)
        )
        report = M1BResearchReportV1.model_validate(report.model_dump(mode="python"))

    response = _client(
        _report,
        dailymed_application=lambda observed: report if observed == request else None,  # type: ignore[return-value]
    ).post("/v1/research/dailymed", json=request.model_dump(mode="json"))

    assert response.status_code == 200
    assert (
        response.json()["source_sections"][0]["selection_status"]
        == {
            "degraded": None,
            "failed_fetch": "selected",
            "stable": "selected",
        }[state]
    )
    assert bool(response.json()["source_sections"][0]["locators"]) is (state == "stable")


def test_valid_report_is_http_200_and_runtime_values_are_server_owned() -> None:
    observed: list[ResearchPubMedRequest] = []

    def application(request: ResearchPubMedRequest) -> ResearchReport:
        observed.append(request)
        return _report(request)

    response = _client(application).post(
        "/v1/research/pubmed",
        content=json.dumps(REQUEST_EXAMPLE),
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["exportable"] is False
    assert observed[0].request_id == REQUEST_ID
    assert observed[0].run_id == RUN_ID
    assert observed[0].created_at_utc == NOW


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (StorageBusyFailure, 503, "storage_busy"),
        (StorageCapacityFailure, 503, "storage_capacity_unavailable"),
        (PersistenceUnavailableFailure, 503, "persistence_unavailable"),
        (PersistenceIntegrityFailure, 503, "persistence_integrity_failure"),
        (ToolContractFailure, 502, "tool_contract_error"),
        (ArtifactIntegrityFailure, 502, "artifact_integrity_failure"),
        (DeadlineExceededFailure, 504, "deadline_exceeded_before_outcome"),
    ],
)
def test_runtime_failures_are_fixed_and_redacted(
    failure: type[ApplicationFailure], status: int, code: str
) -> None:
    def application(_: ResearchPubMedRequest) -> ResearchReport:
        raise failure()

    response = _client(application).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == REQUEST_ID
    assert "traceback" not in response.text.casefold()


def test_unclassified_exception_is_redacted_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-db-url-and-path"

    def application(_: ResearchPubMedRequest) -> ResearchReport:
        raise RuntimeError(secret)

    with caplog.at_level(logging.INFO):
        response = _client(application).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret not in response.text
    assert secret not in caplog.text


def test_forged_report_serialization_is_warning_safe_and_redacted(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "SECRET_PATIENT_RAW_ABSTRACT_98765"
    valid = _report(
        ResearchPubMedRequest.model_construct(
            request_id=REQUEST_ID,
            run_id=RUN_ID,
            created_at_utc=NOW,
            code_revision="0" * 40,
            scope=None,
        )
    )
    payload = dict(valid.__dict__)
    payload["publications"] = secret
    forged = ResearchReport.model_construct(**payload)

    def application(_: ResearchPubMedRequest) -> ResearchReport:
        return forged

    with warnings.catch_warnings(record=True) as observed, caplog.at_level(logging.INFO):
        warnings.simplefilter("always")
        response = _client(application).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)

    captured = capsys.readouterr()
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tool_contract_error"
    assert observed == []
    assert secret not in response.text
    assert secret not in caplog.text
    assert secret not in captured.out
    assert secret not in captured.err


def test_request_id_factory_failures_receive_distinct_valid_redacted_correlations(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SECRET_REQUEST_ID_FACTORY_98765"
    generated = iter(
        (
            UUID("00000000-0000-4000-8000-000000000010"),
            UUID("00000000-0000-4000-8000-000000000011"),
        )
    )
    monkeypatch.setattr("medevidence.api.routes.uuid4", lambda: next(generated))

    def raising_factory() -> str:
        raise RuntimeError(secret)

    def invalid_factory() -> str:
        return secret

    responses = []
    with caplog.at_level(logging.INFO):
        for factory in (raising_factory, invalid_factory):
            responses.append(
                _client(_report, request_id_factory=factory).post(
                    "/v1/research/pubmed",
                    json=REQUEST_EXAMPLE,
                )
            )

    captured = capsys.readouterr()
    bodies = tuple(response.json() for response in responses)
    request_ids = tuple(body["error"]["request_id"] for body in bodies)
    assert all(response.status_code == 500 for response in responses)
    assert all(body["error"]["code"] == "internal_error" for body in bodies)
    assert request_ids == (
        "request:00000000-0000-4000-8000-000000000010",
        "request:00000000-0000-4000-8000-000000000011",
    )
    assert len(set(request_ids)) == len(request_ids)
    assert all(
        re.fullmatch(
            r"request:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            request_id,
        )
        for request_id in request_ids
    )
    assert all(secret not in response.text for response in responses)
    assert secret not in caplog.text
    assert secret not in captured.out
    assert secret not in captured.err
