"""Raw request and public request-contract tests."""

from __future__ import annotations

import json

import pytest

from medevidence.api.contracts import (
    MAX_REQUEST_BYTES,
    RequestContractFailure,
    validate_raw_dailymed_request,
    validate_raw_json_request,
)
from medevidence.api.errors import ApiErrorCode
from medevidence.domain import SourceType


def _body(**updates: object) -> bytes:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "catalog_version": "m1a-concepts-v1",
        "execution_profile_id": "M1A_CONSTRAINED_V1",
        "drug_concept_ids": ["m1a.drug.semaglutide"],
        "adverse_event_concept_ids": ["m1a.event.gastrointestinal"],
        "selected_sources": ["pubmed"],
        "comparison_intent": "summarize",
    }
    payload.update(updates)
    return json.dumps(payload, separators=(",", ":")).encode()


def _validate(
    raw: bytes,
    *,
    content_type: str = "application/json",
    content_encoding: str | None = None,
) -> object:
    return validate_raw_json_request(
        raw,
        content_type=content_type,
        content_encoding=content_encoding,
    )


def _failure(
    raw: bytes,
    *,
    content_type: str = "application/json",
    content_encoding: str | None = None,
) -> RequestContractFailure:
    with pytest.raises(RequestContractFailure) as captured:
        _validate(raw, content_type=content_type, content_encoding=content_encoding)
    return captured.value


def test_valid_request_maps_only_fixed_runtime_scope_values() -> None:
    request = _validate(_body())
    scope = request.to_scope()

    assert scope.selected_sources == (SourceType.PUBMED,)
    assert scope.query_bounds.model_dump() == {
        "max_query_characters": 512,
        "max_pages": 1,
        "max_total_seconds": 30,
    }
    assert scope.result_bounds.model_dump() == {
        "max_records": 100,
        "max_payload_bytes": 5_242_880,
    }


@pytest.mark.parametrize(
    "raw,content_type",
    [
        (b"", "application/json"),
        (b"\xef\xbb\xbf{}", "application/json"),
        (b"\xff", "application/json"),
        (b"{", "application/json"),
        (b"[]", "application/json"),
        (b'{"value":NaN}', "application/json"),
        (b'{"value":Infinity}', "application/json"),
        (b'{"value":-Infinity}', "application/json"),
        (_body(), "text/plain"),
        (_body(), "application/json; charset=latin-1"),
    ],
)
def test_raw_boundary_failures_are_invalid_request(raw: bytes, content_type: str) -> None:
    failure = _failure(raw, content_type=content_type)
    assert failure.code is ApiErrorCode.INVALID_REQUEST


def test_oversized_body_is_invalid_request() -> None:
    failure = _failure(b" " * (MAX_REQUEST_BYTES + 1))
    assert failure.code is ApiErrorCode.INVALID_REQUEST


def test_exact_maximum_raw_body_size_is_accepted() -> None:
    body = _body()
    exact = body + b" " * (MAX_REQUEST_BYTES - len(body))

    assert len(exact) == MAX_REQUEST_BYTES
    assert _validate(exact) is not None


def test_content_encoding_accepts_absent_or_identity_and_rejects_other_values() -> None:
    assert _validate(_body(), content_encoding=None) is not None
    assert _validate(_body(), content_encoding=" identity ") is not None
    assert _failure(_body(), content_encoding="gzip").code is ApiErrorCode.INVALID_REQUEST


def test_duplicate_keys_at_depth_report_json_pointer() -> None:
    raw = _body().replace(
        b'"comparison_intent":"summarize"',
        b'"comparison_intent":"summarize","nested":{"x":1,"x":2}',
    )
    failure = _failure(raw)
    assert failure.code is ApiErrorCode.INVALID_REQUEST
    assert failure.field_paths == ("/nested/x",)


def test_patient_key_precedes_unsupported_versions_without_values_in_error() -> None:
    failure = _failure(_body(schema_version="2.0", patient_name="redacted"))
    assert failure.code is ApiErrorCode.SUSPECTED_PATIENT_DATA
    assert failure.field_paths == ("/patient_name",)


@pytest.mark.parametrize(
    "updates,code",
    [
        (
            {"schema_version": "2.0", "catalog_version": "other"},
            ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION,
        ),
        (
            {"catalog_version": "other", "execution_profile_id": "other"},
            ApiErrorCode.UNSUPPORTED_CATALOG_VERSION,
        ),
        (
            {"execution_profile_id": "other", "drug_concept_ids": ["unknown"]},
            ApiErrorCode.UNSUPPORTED_EXECUTION_PROFILE,
        ),
        (
            {"drug_concept_ids": ["unknown"], "provider": "forbidden"},
            ApiErrorCode.UNKNOWN_CONCEPT_ID,
        ),
        (
            {"provider": "forbidden", "selected_sources": ["cadec"]},
            ApiErrorCode.INVALID_REQUEST,
        ),
    ],
)
def test_request_error_precedence_collisions(
    updates: dict[str, object],
    code: ApiErrorCode,
) -> None:
    assert _failure(_body(**updates)).code is code


def test_transport_failure_precedes_patient_key_detection() -> None:
    failure = _failure(_body(patient_name="secret"), content_type="text/plain")
    assert failure.code is ApiErrorCode.INVALID_REQUEST


@pytest.mark.parametrize(
    "updates,code,path",
    [
        ({"schema_version": "2.0"}, ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION, "/schema_version"),
        (
            {"catalog_version": "other"},
            ApiErrorCode.UNSUPPORTED_CATALOG_VERSION,
            "/catalog_version",
        ),
        (
            {"execution_profile_id": "other"},
            ApiErrorCode.UNSUPPORTED_EXECUTION_PROFILE,
            "/execution_profile_id",
        ),
        (
            {"drug_concept_ids": ["unknown"]},
            ApiErrorCode.UNKNOWN_CONCEPT_ID,
            "/drug_concept_ids/0",
        ),
        (
            {"selected_sources": ["cadec"]},
            ApiErrorCode.INVALID_SCOPE,
            "/selected_sources",
        ),
        (
            {"date_range": {"start_date": "2026-08-09", "end_date": "2026-08-08"}},
            ApiErrorCode.INVALID_SCOPE,
            "/date_range",
        ),
    ],
)
def test_request_error_precedence_classes(
    updates: dict[str, object], code: ApiErrorCode, path: str
) -> None:
    failure = _failure(_body(**updates))
    assert failure.code is code
    assert failure.field_paths == (path,)


def test_noncanonical_arrays_are_invalid_request() -> None:
    failure = _failure(
        _body(
            drug_concept_ids=[
                "m1a.drug.tirzepatide",
                "m1a.drug.semaglutide",
            ]
        )
    )
    assert failure.code is ApiErrorCode.INVALID_REQUEST
    assert failure.field_paths == ("/drug_concept_ids",)


def test_dailymed_boundary_uses_closed_domain_request_and_forbids_planning_fields() -> None:
    from tests.unit.tools.test_dailymed_report import dailymed_request

    payload = dailymed_request().model_dump(mode="json")
    validated = validate_raw_dailymed_request(
        json.dumps(payload, separators=(",", ":")).encode(),
        content_type="application/json",
        content_encoding=None,
    )
    assert validated == dailymed_request()

    for field in ("source_plan", "planning_status", "reason", "reason_code"):
        forged = dict(payload)
        forged[field] = [] if field == "source_plan" else "caller-controlled"
        with pytest.raises(RequestContractFailure) as captured:
            validate_raw_dailymed_request(
                json.dumps(forged, separators=(",", ":")).encode(),
                content_type="application/json",
                content_encoding=None,
            )
        assert captured.value.code is ApiErrorCode.INVALID_REQUEST


def test_dailymed_boundary_rejects_wrong_discriminator_and_source_set() -> None:
    from tests.unit.tools.test_dailymed_report import dailymed_request

    payload = dailymed_request().model_dump(mode="json")
    payload["schema_version"] = "1.0"
    with pytest.raises(RequestContractFailure) as captured:
        validate_raw_dailymed_request(
            json.dumps(payload).encode(),
            content_type="application/json",
            content_encoding=None,
        )
    assert captured.value.code is ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION

    payload = dailymed_request().model_dump(mode="json")
    del payload["schema_version"]
    with pytest.raises(RequestContractFailure) as captured:
        validate_raw_dailymed_request(
            json.dumps(payload).encode(),
            content_type="application/json",
            content_encoding=None,
        )
    assert captured.value.code is ApiErrorCode.INVALID_REQUEST
    assert captured.value.field_paths == ("/schema_version",)

    payload = dailymed_request().model_dump(mode="json")
    del payload["dailymed_selection_requests"][0]["schema_version"]
    with pytest.raises(RequestContractFailure) as captured:
        validate_raw_dailymed_request(
            json.dumps(payload).encode(),
            content_type="application/json",
            content_encoding=None,
        )
    assert captured.value.code is ApiErrorCode.INVALID_REQUEST
    assert captured.value.field_paths == ("/dailymed_selection_requests/0/schema_version",)

    payload = dailymed_request().model_dump(mode="json")
    payload["requested_sources"] = ["pubmed"]
    payload["scope"]["selected_sources"] = ["pubmed"]
    payload["dailymed_selection_requests"] = []
    with pytest.raises(RequestContractFailure) as captured:
        validate_raw_dailymed_request(
            json.dumps(payload).encode(),
            content_type="application/json",
            content_encoding=None,
        )
    assert captured.value.code is ApiErrorCode.INVALID_REQUEST
    assert captured.value.field_paths == ("/requested_sources",)
