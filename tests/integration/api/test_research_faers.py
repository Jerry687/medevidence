"""Offline ASGI integration for the conditional FAERS report endpoint."""

from __future__ import annotations

import json
from collections.abc import Coroutine
from pathlib import Path
from typing import cast

from fastapi import APIRouter
from starlette.requests import Request
from tests.unit.tools.test_faers import RUN_ID, _execution
from tests.unit.tools.test_faers_report import NOW, REPORT_ID, _report_request

from medevidence.api.routes import create_router
from medevidence.composition import create_api_dependencies
from medevidence.domain import M1BResearchReportV1, M1BResearchRequestV1
from medevidence.persistence import PersistenceSettings
from medevidence.tools import build_faers_report


def _invoke(router: APIRouter, payload: dict[str, object]) -> object:
    route = next(route for route in router.routes if route.path == "/v1/research/faers")
    body = json.dumps(payload, separators=(",", ":")).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/research/faers",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    coroutine = cast(Coroutine[object, object, object], route.endpoint(request))
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("offline FAERS route unexpectedly suspended on external I/O")


def test_offline_faers_endpoint_preserves_exact_aggregate_evidence(tmp_path: Path) -> None:
    request = _report_request()
    execution = _execution(request.faers_query_requests[0])
    observed: list[M1BResearchRequestV1] = []

    def faers_application(value: M1BResearchRequestV1) -> M1BResearchReportV1:
        observed.append(value)
        return build_faers_report(
            value,
            report_id=REPORT_ID,
            run_id=RUN_ID,
            executions=(execution,),
            retrieved_as_of=NOW,
        )

    transport_calls = 0

    def transport_factory() -> object:
        nonlocal transport_calls
        transport_calls += 1
        raise AssertionError("FAERS composition must not construct the PubMed transport")

    dependencies = create_api_dependencies(
        snapshot_root=tmp_path / "snapshots",
        persistence_settings=PersistenceSettings(
            database_url="postgresql+psycopg://test:test@127.0.0.1:1/never-contact"
        ),
        code_revision="0" * 40,
        request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000010",
        run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000011",
        attempt_id_factory=lambda: "attempt:00000000-0000-4000-8000-000000000012",
        utc_now=lambda: NOW,
        transport_factory=transport_factory,  # type: ignore[arg-type]
        faers_application=faers_application,
    )
    router = create_router(dependencies)

    report = cast(
        M1BResearchReportV1,
        _invoke(router, request.model_dump(mode="json")),
    )
    body = report.model_dump(mode="json")
    assert observed == [request]
    assert transport_calls == 0
    assert body["request_id"] == request.request_id
    assert body["source_sections"][0]["result"] == execution.result.model_dump(mode="json")
    assert body["source_sections"][0]["acquisition_outcome_refs"] == [
        execution.acquisition_outcome_ref.model_dump(mode="json")
    ]
    assert body["status"] == "draft"
    assert body["exportable"] is False
    keys: set[str] = set()

    def collect_keys(value: object) -> None:
        if isinstance(value, dict):
            keys.update(str(key).casefold() for key in value)
            for child in value.values():
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)

    collect_keys(body)
    assert keys.isdisjoint(
        {"patient", "narrative", "safetyreportid", "individual_reports", "provider_payload"}
    )
