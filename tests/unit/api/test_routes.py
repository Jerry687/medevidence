"""In-process route inventory, success, and runtime-error tests."""

from __future__ import annotations

import json
import logging
import re
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
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
from medevidence.domain import ResearchReport
from medevidence.tools import ResearchPubMedRequest

pytestmark = pytest.mark.enable_socket

REQUEST_ID = "request:00000000-0000-4000-8000-000000000001"
RUN_ID = "run:00000000-0000-4000-8000-000000000002"
NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _client(
    application: Callable[[ResearchPubMedRequest], ResearchReport],
    *,
    request_id_factory: Callable[[], str] | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            ApiDependencies(
                application=application,
                request_id_factory=request_id_factory or (lambda: REQUEST_ID),
                run_id_factory=lambda: RUN_ID,
                utc_now=lambda: NOW,
                code_revision="0" * 40,
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
