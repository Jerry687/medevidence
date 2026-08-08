"""Exact normalized OpenAPI 3.1 contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from medevidence.api import ApiDependencies, create_app
from medevidence.api.errors import ApiErrorCode
from medevidence.domain import ResearchReport
from medevidence.tools import ResearchPubMedRequest

FIXTURE = Path("tests/fixtures/api/openapi-v1.json")


def _application(_: ResearchPubMedRequest) -> ResearchReport:
    raise AssertionError("OpenAPI generation must not execute the application")


def _schema() -> dict[str, object]:
    app = create_app(
        ApiDependencies(
            application=_application,
            request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000001",
            run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000002",
            utc_now=lambda: datetime(2026, 8, 8, 12, tzinfo=UTC),
            code_revision="0" * 40,
        )
    )
    return cast(dict[str, object], app.openapi())


def _normalized(schema: dict[str, object]) -> bytes:
    return (
        json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def test_openapi_exact_route_metadata_models_and_examples() -> None:
    schema = _schema()
    assert schema["openapi"] == "3.1.0"
    info = cast(dict[str, object], schema["info"])
    assert info == {
        "title": "MedEvidence API",
        "summary": "Traceable drug-safety evidence research API",
        "description": (
            "Versioned research-only transport for the bounded M1A PubMed vertical slice.\n"
            "Responses are draft, non-exportable, and source-attributed. The API does not\n"
            "provide diagnosis, treatment, dosage, individualized medical advice, or a\n"
            "product-safety ranking."
        ),
        "version": "0.0.0",
    }
    assert schema["tags"] == [
        {
            "name": "research",
            "description": "Bounded, traceable, draft-only public-source evidence research.",
        }
    ]
    paths = cast(dict[str, object], schema["paths"])
    assert set(paths) == {"/v1/research/pubmed"}
    path = cast(dict[str, object], paths["/v1/research/pubmed"])
    assert set(path) == {"post"}
    operation = cast(dict[str, object], path["post"])
    assert operation["operationId"] == "research_pubmed_v1"
    assert operation["tags"] == ["research"]
    assert operation["summary"] == "Research PubMed evidence"
    assert operation["description"] == (
        "Execute the bounded M1A PubMed workflow and return the persisted,\n"
        "source-attributed, draft ResearchReport. Valid degraded reports remain HTTP\n"
        "200 and carry their typed limitations."
    )
    request_body = cast(dict[str, object], operation["requestBody"])
    request_content = cast(dict[str, object], request_body["content"])
    request_json = cast(dict[str, object], request_content["application/json"])
    assert request_json["schema"] == {"$ref": "#/components/schemas/ResearchPubMedApiRequest"}
    assert set(cast(dict[str, object], request_json["examples"])) == {
        "summarize_semaglutide_gastrointestinal"
    }
    responses = cast(dict[str, object], operation["responses"])
    assert set(responses) == {"200", "422", "500", "502", "503", "504"}
    response_200 = cast(dict[str, object], responses["200"])
    assert response_200["description"] == "Persisted draft research report."
    content_200 = cast(dict[str, object], response_200["content"])
    json_200 = cast(dict[str, object], content_200["application/json"])
    assert json_200["schema"] == {"$ref": "#/components/schemas/ResearchReport"}
    assert set(cast(dict[str, object], json_200["examples"])) == {"complete_no_match"}

    observed_codes: set[str] = set()
    for status in ("422", "500", "502", "503", "504"):
        response = cast(dict[str, object], responses[status])
        content = cast(dict[str, object], response["content"])
        media = cast(dict[str, object], content["application/json"])
        assert media["schema"] == {"$ref": "#/components/schemas/ApiErrorResponse"}
        observed_codes.update(cast(dict[str, object], media["examples"]))
    assert observed_codes == {code.value for code in ApiErrorCode}

    components = cast(dict[str, object], schema["components"])
    schemas = cast(dict[str, object], components["schemas"])
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_normalized_openapi_fixture_is_byte_exact() -> None:
    raw = FIXTURE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw == _normalized(_schema())
