"""Offline ASGI integration for the additive DailyMed report endpoint."""

from __future__ import annotations

import json
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.requests import Request
from tests.unit.tools.test_dailymed_report import trusted_case

from medevidence.api import ApiDependencies
from medevidence.api.routes import create_router
from medevidence.domain import M1BResearchReportV1, M1BResearchRequestV1, ResearchReport
from medevidence.tools import ResearchPubMedRequest, build_dailymed_report


def _unreachable_pubmed(_: ResearchPubMedRequest) -> ResearchReport:
    raise AssertionError("DailyMed integration must not invoke PubMed")


def _invoke(router: APIRouter, payload: dict[str, object]) -> object:
    route = next(route for route in router.routes if route.path == "/v1/research/dailymed")
    body = json.dumps(payload, separators=(",", ":")).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/research/dailymed",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    coroutine = cast(Coroutine[object, object, object], route.endpoint(request))
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("offline route unexpectedly suspended on external I/O")


def test_offline_dailymed_endpoint_preserves_exact_trusted_evidence() -> None:
    request, section, ref, outcome = trusted_case()
    observed: list[M1BResearchRequestV1] = []

    def dailymed_application(value: M1BResearchRequestV1) -> M1BResearchReportV1:
        observed.append(value)
        return build_dailymed_report(
            value,
            report_id=section.report_id,
            run_id=section.run_id,
            source_sections=(section,),
            retrieved_as_of=datetime(2026, 8, 12, 12, tzinfo=UTC),
            trusted_acquisition_outcomes=((section.request, ref, outcome),),
            trusted_selection_decisions=(),
        )

    router = create_router(
        ApiDependencies(
            application=_unreachable_pubmed,
            request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000010",
            run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000011",
            utc_now=lambda: datetime(2026, 8, 12, 12, tzinfo=UTC),
            code_revision="0" * 40,
            dailymed_application=dailymed_application,
        )
    )

    response = _invoke(router, request.model_dump(mode="json"))
    report = cast(M1BResearchReportV1, response)
    body = report.model_dump(mode="json")
    assert observed == [request]
    assert body["request_id"] == request.request_id
    assert body["source_outcomes"][0]["query_id"] == outcome.query_id
    assert body["source_sections"][0]["acquisition_outcome_refs"] == [ref.model_dump(mode="json")]
    assert body["status"] == "draft"
    assert body["exportable"] is False


def test_offline_dailymed_endpoint_fails_closed_on_unknown_field() -> None:
    request, _, _, _ = trusted_case()
    payload = request.model_dump(mode="json")
    payload["source_plan"] = []
    router = create_router(
        ApiDependencies(
            application=_unreachable_pubmed,
            request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000010",
            run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000011",
            utc_now=lambda: datetime(2026, 8, 12, 12, tzinfo=UTC),
            code_revision="0" * 40,
            dailymed_application=lambda _: (_ for _ in ()).throw(
                AssertionError("invalid request reached application")
            ),
        )
    )

    response = cast(JSONResponse, _invoke(router, payload))
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["error"]["code"] == "invalid_request"
