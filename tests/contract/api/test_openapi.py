"""Exact normalized OpenAPI 3.1 contract."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from medevidence.api import ApiDependencies, create_app
from medevidence.api.errors import ApiErrorCode
from medevidence.domain import (
    FaersAggregateRequestV1,
    FaersExecutionBoundsV1,
    FaersInclusiveDateRangeV1,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    ResearchReport,
)
from medevidence.tools import ResearchPubMedRequest

FIXTURE = Path("tests/fixtures/api/openapi-v1.json")


def _application(_: ResearchPubMedRequest) -> ResearchReport:
    raise AssertionError("OpenAPI generation must not execute the application")


def _dailymed_application(_: M1BResearchRequestV1) -> M1BResearchReportV1:
    raise AssertionError("OpenAPI generation must not execute the DailyMed application")


def _faers_application(_: M1BResearchRequestV1) -> M1BResearchReportV1:
    raise AssertionError("OpenAPI generation must not execute the FAERS application")


def _schema(*, dailymed_enabled: bool = True, faers_enabled: bool = True) -> dict[str, object]:
    app = create_app(
        ApiDependencies(
            application=_application,
            request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000001",
            run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000002",
            utc_now=lambda: datetime(2026, 8, 8, 12, tzinfo=UTC),
            code_revision="0" * 40,
            dailymed_application=_dailymed_application if dailymed_enabled else None,
            faers_application=_faers_application if faers_enabled else None,
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


def _schema_accepts(document: dict[str, object], root: dict[str, object], value: object) -> bool:
    """Evaluate the structural JSON Schema keywords used by route parity tests."""

    components = cast(dict[str, object], cast(dict[str, object], document["components"])["schemas"])

    def accepts(schema: object, candidate: object) -> bool:
        if not isinstance(schema, dict):
            return True
        reference = schema.get("$ref")
        if isinstance(reference, str):
            prefix = "#/components/schemas/"
            if not reference.startswith(prefix) or not accepts(
                components[reference.removeprefix(prefix)], candidate
            ):
                return False
        if "const" in schema and candidate != schema["const"]:
            return False
        if "enum" in schema and candidate not in cast(list[object], schema["enum"]):
            return False
        choices = schema.get("allOf")
        if isinstance(choices, list) and not all(accepts(choice, candidate) for choice in choices):
            return False
        choices = schema.get("anyOf")
        if isinstance(choices, list) and not any(accepts(choice, candidate) for choice in choices):
            return False
        choices = schema.get("oneOf")
        if isinstance(choices, list) and sum(accepts(choice, candidate) for choice in choices) != 1:
            return False
        expected_type = schema.get("type")
        if expected_type == "object":
            if not isinstance(candidate, dict):
                return False
            required = schema.get("required", ())
            if any(name not in candidate for name in cast(list[str], required)):
                return False
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                if schema.get("additionalProperties") is False and set(candidate) - set(properties):
                    return False
                if any(
                    name in candidate and not accepts(child, candidate[name])
                    for name, child in properties.items()
                ):
                    return False
        elif expected_type == "array":
            if not isinstance(candidate, list):
                return False
            if len(candidate) < cast(int, schema.get("minItems", 0)):
                return False
            maximum = schema.get("maxItems")
            if isinstance(maximum, int) and len(candidate) > maximum:
                return False
            items = schema.get("items")
            if items is not None and any(not accepts(items, item) for item in candidate):
                return False
        elif expected_type == "string":
            if not isinstance(candidate, str):
                return False
            if len(candidate) < cast(int, schema.get("minLength", 0)):
                return False
            maximum = schema.get("maxLength")
            if isinstance(maximum, int) and len(candidate) > maximum:
                return False
            pattern = schema.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, candidate) is None:
                return False
        elif (
            (expected_type == "integer" and type(candidate) is not int)
            or (expected_type == "number" and type(candidate) not in {int, float})
            or (expected_type == "boolean" and type(candidate) is not bool)
            or (expected_type == "null" and candidate is not None)
        ):
            return False
        if type(candidate) in {int, float}:
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and candidate < minimum:
                return False
            if isinstance(maximum, (int, float)) and candidate > maximum:
                return False
        return True

    return accepts(root, value)


def _faers_route_schemas(
    schema: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    paths = cast(dict[str, object], schema["paths"])
    operation = cast(
        dict[str, object], cast(dict[str, object], paths["/v1/research/faers"])["post"]
    )
    request_body = cast(dict[str, object], operation["requestBody"])
    request_content = cast(dict[str, object], request_body["content"])
    request_schema = cast(
        dict[str, object], cast(dict[str, object], request_content["application/json"])["schema"]
    )
    responses = cast(dict[str, object], operation["responses"])
    response = cast(dict[str, object], responses["200"])
    response_content = cast(dict[str, object], response["content"])
    response_schema = cast(
        dict[str, object], cast(dict[str, object], response_content["application/json"])["schema"]
    )
    return request_schema, response_schema


def test_openapi_exact_route_metadata_models_and_examples() -> None:
    schema = _schema()
    assert schema["openapi"] == "3.1.0"
    info = cast(dict[str, object], schema["info"])
    assert info == {
        "title": "MedEvidence API",
        "summary": "Traceable drug-safety evidence research API",
        "description": (
            "Versioned research-only transport for bounded PubMed, DailyMed, and FAERS evidence.\n"
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
    assert set(paths) == {
        "/v1/research/pubmed",
        "/v1/research/dailymed",
        "/v1/research/faers",
    }
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
    for component_name, discriminators in {
        "DailyMedLocatorV1": {"schema_version", "locator_kind", "source"},
        "DailyMedSelectionRequestV1": {"schema_version"},
        "M1BResearchReportV1": {"schema_version"},
        "M1BResearchRequestV1": {"schema_version"},
        "M1BSourcePlanEntryV1": {"schema_version"},
    }.items():
        component = cast(dict[str, object], schemas[component_name])
        assert discriminators <= set(cast(list[str], component["required"]))

    section_union = cast(dict[str, object], schemas["M1BSourceSection"])
    assert section_union["discriminator"] == {
        "propertyName": "section_kind",
        "mapping": {
            "dailymed_label": "#/components/schemas/DailyMedLabelSectionV1",
            "faers_aggregate": "#/components/schemas/FaersAggregateSectionV1",
        },
    }
    assert section_union["oneOf"] == [
        {"$ref": "#/components/schemas/DailyMedLabelSectionV1"},
        {"$ref": "#/components/schemas/FaersAggregateSectionV1"},
    ]

    dailymed = cast(dict[str, object], paths["/v1/research/dailymed"])
    dailymed_post = cast(dict[str, object], dailymed["post"])
    assert dailymed_post["operationId"] == "research_dailymed_v1"
    assert dailymed_post["summary"] == "Research DailyMed label evidence"
    dailymed_body = cast(dict[str, object], dailymed_post["requestBody"])
    dailymed_content = cast(dict[str, object], dailymed_body["content"])
    assert cast(dict[str, object], dailymed_content["application/json"])["schema"] == {
        "$ref": "#/components/schemas/M1BResearchRequestV1"
    }
    dailymed_responses = cast(dict[str, object], dailymed_post["responses"])
    documented_dailymed_codes = {
        code
        for response in dailymed_responses.values()
        if isinstance(response, dict)
        for content in [response.get("content")]
        if isinstance(content, dict)
        for media in [content.get("application/json")]
        if isinstance(media, dict)
        for code in cast(dict[str, object], media.get("examples", {}))
    }
    assert documented_dailymed_codes == {
        "invalid_request",
        "unsupported_schema_version",
        "suspected_patient_data",
        "internal_error",
        "tool_contract_error",
        "artifact_integrity_failure",
        "storage_busy",
        "storage_capacity_unavailable",
        "persistence_unavailable",
        "persistence_integrity_failure",
        "deadline_exceeded_before_outcome",
    }
    dailymed_200 = cast(dict[str, object], dailymed_responses["200"])
    assert cast(
        dict[str, object],
        cast(dict[str, object], dailymed_200["content"])["application/json"],
    )["schema"] == {"$ref": "#/components/schemas/M1BResearchReportV1"}
    report_schema = cast(dict[str, object], schemas["M1BResearchReportV1"])
    assert set(cast(dict[str, object], report_schema["properties"])) == set(
        cast(list[str], report_schema["required"])
    )

    faers = cast(dict[str, object], paths["/v1/research/faers"])
    faers_post = cast(dict[str, object], faers["post"])
    assert faers_post["operationId"] == "research_faers_v1"
    assert faers_post["summary"] == "Research FAERS aggregate evidence"
    assert faers_post["description"] == (
        "Build an additive M1B FAERS report from exact trusted aggregate evidence.\n"
        "The response remains research-only, draft, and non-exportable."
    )
    faers_body = cast(dict[str, object], faers_post["requestBody"])
    faers_content = cast(dict[str, object], faers_body["content"])
    assert cast(dict[str, object], faers_content["application/json"])["schema"] == {
        "$ref": "#/components/schemas/M1BResearchRequestV1FaersRoute"
    }
    faers_responses = cast(dict[str, object], faers_post["responses"])
    faers_200 = cast(dict[str, object], faers_responses["200"])
    assert faers_200["description"] == "Validated draft FAERS research report."
    assert cast(
        dict[str, object],
        cast(dict[str, object], faers_200["content"])["application/json"],
    )["schema"] == {"$ref": "#/components/schemas/M1BResearchReportV1FaersRoute"}


def test_m1a_pubmed_route_and_transitive_components_are_byte_compatible() -> None:
    disabled = _schema(dailymed_enabled=False, faers_enabled=False)
    enabled = _schema()

    def pubmed_contract(schema: dict[str, object]) -> tuple[object, dict[str, object]]:
        path = cast(dict[str, object], schema["paths"])["/v1/research/pubmed"]
        schemas = cast(dict[str, object], cast(dict[str, object], schema["components"])["schemas"])
        names: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "$ref" and isinstance(child, str):
                        prefix = "#/components/schemas/"
                        if child.startswith(prefix):
                            name = child.removeprefix(prefix)
                            if name not in names:
                                names.add(name)
                                collect(schemas[name])
                        continue
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(path)
        return path, {name: schemas[name] for name in sorted(names)}

    path, components = pubmed_contract(disabled)
    enabled_path, enabled_components = pubmed_contract(enabled)

    def digest(value: object) -> str:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    assert digest(path) == "c83daba0f7805277444bf08732ced1228bb09de9cc47ae29bf6c22f0a4a60bae"
    assert len(components) == 76
    assert digest(components) == "985edba15e6f6dda1aa5339a81b7de79144dd13d39328e1b6c4dc331e0e8994e"
    assert enabled_path == path
    assert enabled_components == components


def test_default_m1a_openapi_is_byte_identical_and_has_no_m1b_advertisement() -> None:
    raw = _normalized(_schema(dailymed_enabled=False, faers_enabled=False))
    assert hashlib.sha256(raw).hexdigest() == (
        "0d735acbbb1503dcc3235a37193b9d383cae08b8dc4fdb3b0e42616982ff028a"
    )
    assert b"M1B" not in raw
    assert b"DailyMed" not in raw


def test_dailymed_only_openapi_remains_byte_identical() -> None:
    raw = _normalized(_schema(faers_enabled=False))
    assert hashlib.sha256(raw).hexdigest() == (
        "b2fb6da8c1bc14daf30dc3003da54f22fbb98fbb70efb61828accf8a44ca6b36"
    )
    assert b'"/v1/research/faers"' not in raw


def test_all_local_schema_refs_resolve_in_default_and_enabled_configs() -> None:
    for schema in (
        _schema(dailymed_enabled=False, faers_enabled=False),
        _schema(faers_enabled=False),
        _schema(),
    ):
        components = cast(
            dict[str, object], cast(dict[str, object], schema["components"])["schemas"]
        )

        def visit(value: object, schemas: dict[str, object] = components) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "$ref":
                        assert isinstance(child, str)
                        prefix = "#/components/schemas/"
                        assert child.startswith(prefix)
                        assert child.removeprefix(prefix) in schemas
                    else:
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(schema)


def test_enabled_response_requiredness_matches_strict_recursive_presence() -> None:
    schema = _schema()
    paths = cast(dict[str, object], schema["paths"])
    dailymed = cast(dict[str, object], paths["/v1/research/dailymed"])
    operation = cast(dict[str, object], dailymed["post"])
    responses = cast(dict[str, object], operation["responses"])
    response = cast(dict[str, object], responses["200"])
    content = cast(dict[str, object], response["content"])
    media = cast(dict[str, object], content["application/json"])
    components = cast(dict[str, object], cast(dict[str, object], schema["components"])["schemas"])
    reachable: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "$ref" and isinstance(child, str):
                    name = child.removeprefix("#/components/schemas/")
                    if name not in reachable:
                        reachable.add(name)
                        visit(components[name])
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(media["schema"])
    expected_models = {
        "DailyMedLabelVersion": 10,
        "DailyMedLocatorV1": 44,
        "DailyMedSelectionRequestV1Response": 6,
        "DomainWarningResponse": 3,
        "InclusiveDateRangeResponse": 3,
        "LabelSection": 15,
        "M1BSourcePlanEntryV1": 5,
        "DailyMedLabelSectionV1": 15,
        "FaersAggregateSectionV1": 11,
        "ResearchScopeResponse": 10,
        "RetainedSplResponse": 33,
        "SourceOutcomeResponse": 12,
    }
    assert set(expected_models) <= reachable
    for name in reachable:
        component = cast(dict[str, object], components[name])
        properties = component.get("properties")
        if isinstance(properties, dict):
            assert set(cast(list[str], component["required"])) == set(properties)
    for name, field_count in expected_models.items():
        component = cast(dict[str, object], components[name])
        assert len(cast(dict[str, object], component["properties"])) == field_count


def test_enabled_input_optionality_and_response_nullability_are_distinct() -> None:
    schema = _schema()
    components = cast(dict[str, object], cast(dict[str, object], schema["components"])["schemas"])
    assert set(
        cast(
            list[str], cast(dict[str, object], components["DailyMedSelectionRequestV1"])["required"]
        )
    ) == {"schema_version", "drug_concept_id", "requested_section_codes", "selection_mode"}
    assert set(
        cast(list[str], cast(dict[str, object], components["ResearchScope"])["required"])
    ) == {
        "scope_id",
        "drugs",
        "adverse_reactions",
        "selected_sources",
        "comparison_intent",
        "query_bounds",
        "result_bounds",
    }
    assert set(
        cast(list[str], cast(dict[str, object], components["InclusiveDateRange"])["required"])
    ) == {"start_date", "end_date"}
    assert set(
        cast(
            list[str],
            cast(dict[str, object], components["FaersAggregateRequestV1"])["required"],
        )
    ) == {
        "drug_concept_id",
        "execution_bounds",
        "identity_exact_value",
        "identity_strategy",
        "inclusive_date_range",
        "pt_values",
        "statistical_unit",
    }

    request_schema = cast(dict[str, object], components["M1BResearchRequestV1"])
    request_properties = cast(dict[str, object], request_schema["properties"])
    request_items = cast(
        dict[str, object],
        cast(dict[str, object], request_properties["dailymed_selection_requests"])["items"],
    )
    assert request_items["$ref"] == "#/components/schemas/DailyMedSelectionRequestV1"
    faers_request_items = cast(
        dict[str, object],
        cast(dict[str, object], request_properties["faers_query_requests"])["items"],
    )
    assert faers_request_items["$ref"] == "#/components/schemas/FaersAggregateRequestV1"

    for response_name, input_name in {
        "DailyMedSelectionRequestV1Response": "DailyMedSelectionRequestV1",
        "DomainWarningResponse": "DomainWarning",
        "InclusiveDateRangeResponse": "InclusiveDateRange",
        "ResearchScopeResponse": "ResearchScope",
        "SourceOutcomeResponse": "SourceOutcome",
    }.items():
        response_component = cast(dict[str, object], components[response_name])
        input_component = cast(dict[str, object], components[input_name])
        response_properties = json.loads(json.dumps(response_component["properties"]))

        def normalize_response_refs(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "$ref" and isinstance(child, str) and child.endswith("Response"):
                        value[key] = child.removesuffix("Response")
                    else:
                        normalize_response_refs(child)
            elif isinstance(value, list):
                for child in value:
                    normalize_response_refs(child)

        normalize_response_refs(response_properties)
        assert response_properties == input_component["properties"]

    def allows_null(value: object) -> bool:
        if isinstance(value, dict):
            return value.get("type") == "null" or any(
                allows_null(child) for child in value.values()
            )
        if isinstance(value, list):
            return any(allows_null(child) for child in value)
        return False

    nullable_fields = {
        "DailyMedLabelVersion": ("effective_date", "published_date"),
        "DailyMedSelectionRequestV1Response": ("pinned_setid", "pinned_spl_version"),
        "LabelSection": ("parent_section_id",),
        "M1BSourcePlanEntryV1": ("reason", "reason_code"),
        "DailyMedLabelSectionV1": (
            "label_version",
            "retained_response",
            "selection_decision_id",
            "selection_status",
        ),
        "FaersAggregateResult": ("provider_as_of_utc",),
        "ResearchScopeResponse": ("date_range",),
        "SourceOutcomeResponse": ("failure_id",),
    }
    for component_name, fields in nullable_fields.items():
        component = cast(dict[str, object], components[component_name])
        properties = cast(dict[str, object], component["properties"])
        required = set(cast(list[str], component["required"]))
        for field in fields:
            assert field in required
            assert allows_null(properties[field])


def test_enabled_faers_input_requiredness_matches_runtime_presence() -> None:
    components = cast(
        dict[str, object], cast(dict[str, object], _schema()["components"])["schemas"]
    )
    models = {
        "FaersAggregateRequestV1": FaersAggregateRequestV1,
        "FaersExecutionBoundsV1": FaersExecutionBoundsV1,
        "FaersInclusiveDateRangeV1": FaersInclusiveDateRangeV1,
    }
    explicit_runtime_presence = {
        "FaersAggregateRequestV1": {"pt_values", "statistical_unit"},
    }
    for component_name, model in models.items():
        runtime_required = {
            name for name, field in model.model_fields.items() if field.is_required()
        } | explicit_runtime_presence.get(component_name, set())
        component = cast(dict[str, object], components[component_name])
        openapi_required = set(cast(list[str], component.get("required", ())))
        assert openapi_required == runtime_required

    request_component = cast(dict[str, object], components["M1BResearchRequestV1"])
    request_properties = cast(dict[str, object], request_component["properties"])
    faers_items = cast(
        dict[str, object],
        cast(dict[str, object], request_properties["faers_query_requests"])["items"],
    )
    assert faers_items == {"$ref": "#/components/schemas/FaersAggregateRequestV1"}
    assert "faers_query_requests" not in set(cast(list[str], request_component["required"]))


def test_faers_route_request_schema_accepts_only_exact_faers_shape() -> None:
    from tests.unit.tools.test_dailymed_report import dailymed_request
    from tests.unit.tools.test_faers_report import _report_request

    schema = _schema()
    request_schema, _ = _faers_route_schemas(schema)
    valid = _report_request().model_dump(mode="json")
    assert _schema_accepts(schema, request_schema, valid)
    omitted_optional_empty_arrays = deepcopy(valid)
    del omitted_optional_empty_arrays["dailymed_selection_requests"]
    del omitted_optional_empty_arrays["cadec_query_requests"]
    assert _schema_accepts(schema, request_schema, omitted_optional_empty_arrays)

    dailymed_only = dailymed_request().model_dump(mode="json")
    assert not _schema_accepts(schema, request_schema, dailymed_only)

    mixed = deepcopy(valid)
    mixed["requested_sources"] = ["dailymed", "faers"]
    mixed["scope"]["selected_sources"] = ["dailymed", "faers"]
    mixed["dailymed_selection_requests"] = dailymed_only["dailymed_selection_requests"]
    assert not _schema_accepts(schema, request_schema, mixed)

    missing_request = deepcopy(valid)
    del missing_request["faers_query_requests"]
    assert not _schema_accepts(schema, request_schema, missing_request)


def test_faers_route_response_schema_rejects_foreign_plan_and_section() -> None:
    from tests.unit.tools.test_dailymed_report import trusted_case
    from tests.unit.tools.test_faers import RUN_ID as FAERS_RUN_ID
    from tests.unit.tools.test_faers import _execution
    from tests.unit.tools.test_faers_report import NOW, REPORT_ID, _report_request

    from medevidence.tools import build_faers_report

    schema = _schema()
    _, response_schema = _faers_route_schemas(schema)
    request = _report_request()
    valid = build_faers_report(
        request,
        report_id=REPORT_ID,
        run_id=FAERS_RUN_ID,
        executions=(_execution(request.faers_query_requests[0]),),
        retrieved_as_of=NOW,
    ).model_dump(mode="json")
    assert _schema_accepts(schema, response_schema, valid)

    foreign_plan = deepcopy(valid)
    foreign_plan["source_plan"][0]["source"] = "dailymed"
    assert not _schema_accepts(schema, response_schema, foreign_plan)

    _, dailymed_section, _, _ = trusted_case()
    foreign_section = deepcopy(valid)
    foreign_section["source_sections"] = [dailymed_section.model_dump(mode="json")]
    assert not _schema_accepts(schema, response_schema, foreign_section)


def test_normalized_openapi_fixture_is_byte_exact() -> None:
    raw = FIXTURE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw == _normalized(_schema())
