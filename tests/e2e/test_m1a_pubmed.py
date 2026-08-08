"""Fully offline M1A HTTP acceptance through the in-process ASGI adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from medevidence.api import ApiDependencies, create_app
from medevidence.api.routes import REQUEST_EXAMPLE, _complete_no_match_example
from medevidence.domain import ResearchReport
from medevidence.tools import ResearchPubMedRequest

pytestmark = pytest.mark.enable_socket


def test_complete_no_match_http_acceptance() -> None:
    def application(_: ResearchPubMedRequest) -> ResearchReport:
        return ResearchReport.model_validate_json(json.dumps(_complete_no_match_example()))

    app = create_app(
        ApiDependencies(
            application=application,
            request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000001",
            run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000002",
            utc_now=lambda: datetime(2026, 8, 8, 12, tzinfo=UTC),
            code_revision="0" * 40,
        )
    )
    response = TestClient(app).post("/v1/research/pubmed", json=REQUEST_EXAMPLE)
    assert response.status_code == 200
    body = response.json()
    assert body["source_outcomes"][0]["result_status"] == "no_match"
    assert body["publications"] == body["claims"] == body["citations"] == []
    assert body["status"] == "draft" and body["exportable"] is False
