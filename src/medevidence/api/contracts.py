"""Strict public request contracts and raw JSON boundary validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from medevidence.catalog import ProductionCatalog, load_production_catalog
from medevidence.domain import (
    ComparisonIntent,
    InclusiveDateRange,
    M1BResearchRequestV1,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)

from .errors import ApiErrorCode

MAX_REQUEST_BYTES: Final = 65_536
DRUG_CONCEPT_IDS: Final = frozenset(
    {
        "m1a.drug.semaglutide",
        "m1a.drug.tirzepatide",
        "synthetic.drug.alpha",
    }
)
ADVERSE_EVENT_CONCEPT_IDS: Final = frozenset({"m1a.event.gastrointestinal", "synthetic.event.beta"})
PATIENT_KEYS: Final = frozenset(
    {
        "patient",
        "patient_id",
        "patient_name",
        "first_name",
        "last_name",
        "full_name",
        "dob",
        "date_of_birth",
        "mrn",
        "medical_record_number",
        "clinical_note",
        "note",
        "symptom",
        "symptoms",
        "email",
        "phone",
        "telephone",
        "address",
        "ssn",
        "social_security_number",
    }
)


class ApiInclusiveDateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    start_date: date
    end_date: date


class ResearchPubMedApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"]
    catalog_version: Literal["m1a-concepts-v1"]
    execution_profile_id: Literal["M1A_CONSTRAINED_V1"]
    drug_concept_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    adverse_event_concept_ids: tuple[str, ...] = Field(min_length=1, max_length=4)
    selected_sources: tuple[SourceType, ...] = Field(min_length=1, max_length=4)
    comparison_intent: ComparisonIntent
    date_range: ApiInclusiveDateRange | None = None

    @field_validator(
        "drug_concept_ids",
        "adverse_event_concept_ids",
        "selected_sources",
    )
    @classmethod
    def validate_canonical_array(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if value != tuple(sorted(set(value), key=str)):
            raise ValueError("array must be sorted and unique")
        return value

    def to_scope(self, catalog: ProductionCatalog | None = None) -> ResearchScope:
        """Map exact public concept IDs to the fixed source-neutral domain scope."""

        active_catalog = catalog or load_production_catalog()
        drugs = tuple(active_catalog.drugs[concept_id] for concept_id in self.drug_concept_ids)
        events = tuple(
            active_catalog.adverse_events[concept_id]
            for concept_id in self.adverse_event_concept_ids
        )
        date_range = (
            None
            if self.date_range is None
            else InclusiveDateRange(
                start_date=self.date_range.start_date,
                end_date=self.date_range.end_date,
                precision="day",
            )
        )
        return ResearchScope.create(
            drugs=drugs,
            adverse_reactions=events,
            date_range=date_range,
            selected_sources=self.selected_sources,
            comparison_intent=self.comparison_intent,
            query_bounds=QueryBounds(
                max_query_characters=512,
                max_pages=1,
                max_total_seconds=30,
            ),
            result_bounds=ResultBounds(
                max_records=100,
                max_payload_bytes=5_242_880,
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestContractFailure(Exception):
    """One precedence-selected, payload-free request rejection."""

    code: ApiErrorCode
    field_paths: tuple[str, ...]


class _JSONObject(list[tuple[str, object]]):
    pass


def validate_raw_json_request(
    raw: bytes,
    *,
    content_type: str | None,
    content_encoding: str | None,
) -> ResearchPubMedApiRequest:
    """Apply the exact raw, JSON, safety, version, catalog, and scope precedence."""

    _validate_transport_headers_and_size(raw, content_type, content_encoding)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",)) from error
    if text.startswith("\ufeff"):
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    try:
        loaded = json.loads(
            text,
            object_pairs_hook=_JSONObject,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",)) from error
    if not isinstance(loaded, _JSONObject):
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    materialized, duplicate_paths = _materialize_object(loaded, "")
    if duplicate_paths:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, duplicate_paths)
    data = cast(dict[str, object], materialized)

    patient_paths = _patient_key_paths(data, "")
    if patient_paths:
        raise RequestContractFailure(ApiErrorCode.SUSPECTED_PATIENT_DATA, patient_paths)
    for field, expected, code in (
        ("schema_version", "1.0", ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION),
        ("catalog_version", "m1a-concepts-v1", ApiErrorCode.UNSUPPORTED_CATALOG_VERSION),
        (
            "execution_profile_id",
            "M1A_CONSTRAINED_V1",
            ApiErrorCode.UNSUPPORTED_EXECUTION_PROFILE,
        ),
    ):
        if field in data and data[field] != expected:
            raise RequestContractFailure(code, (f"/{field}",))

    unknown_paths = _unknown_concept_paths(data)
    if unknown_paths:
        raise RequestContractFailure(ApiErrorCode.UNKNOWN_CONCEPT_ID, unknown_paths)

    try:
        normalized = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        request = ResearchPubMedApiRequest.model_validate_json(normalized, strict=True)
    except (ValidationError, ValueError) as error:
        paths = _validation_paths(error)
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, paths) from error

    invalid_scope_paths: set[str] = set()
    if SourceType.PUBMED not in request.selected_sources:
        invalid_scope_paths.add("/selected_sources")
    if request.date_range is not None and (
        request.date_range.start_date > request.date_range.end_date
    ):
        invalid_scope_paths.add("/date_range")
    if invalid_scope_paths:
        raise RequestContractFailure(
            ApiErrorCode.INVALID_SCOPE,
            tuple(sorted(invalid_scope_paths)),
        )
    try:
        request.to_scope()
    except (KeyError, ValueError) as error:
        raise RequestContractFailure(ApiErrorCode.INVALID_SCOPE, ("",)) from error
    return request


def validate_raw_dailymed_request(
    raw: bytes,
    *,
    content_type: str | None,
    content_encoding: str | None,
) -> M1BResearchRequestV1:
    """Validate the additive closed DailyMed request without caller planning state."""

    _validate_transport_headers_and_size(raw, content_type, content_encoding)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",)) from error
    if text.startswith("\ufeff"):
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    try:
        loaded = json.loads(
            text,
            object_pairs_hook=_JSONObject,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",)) from error
    if not isinstance(loaded, _JSONObject):
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    materialized, duplicate_paths = _materialize_object(loaded, "")
    if duplicate_paths:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, duplicate_paths)
    data = cast(dict[str, object], materialized)

    patient_paths = _patient_key_paths(data, "")
    if patient_paths:
        raise RequestContractFailure(ApiErrorCode.SUSPECTED_PATIENT_DATA, patient_paths)
    if "schema_version" not in data:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("/schema_version",))
    if data["schema_version"] != "m1b.request.v1":
        raise RequestContractFailure(
            ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION,
            ("/schema_version",),
        )
    if data.get("requested_sources") != [SourceType.DAILYMED.value]:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("/requested_sources",))
    selection_requests = data.get("dailymed_selection_requests")
    if isinstance(selection_requests, list):
        missing_discriminators = tuple(
            f"/dailymed_selection_requests/{index}/schema_version"
            for index, item in enumerate(selection_requests)
            if isinstance(item, dict) and "schema_version" not in item
        )
        if missing_discriminators:
            raise RequestContractFailure(
                ApiErrorCode.INVALID_REQUEST,
                missing_discriminators,
            )
    try:
        normalized = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        request = M1BResearchRequestV1.model_validate_json(normalized, strict=True)
    except (ValidationError, ValueError) as error:
        raise RequestContractFailure(
            ApiErrorCode.INVALID_REQUEST,
            _validation_paths(error),
        ) from error
    if request.requested_sources != (SourceType.DAILYMED,):
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("/requested_sources",))
    return request


def _validate_transport_headers_and_size(
    raw: bytes,
    content_type: str | None,
    content_encoding: str | None,
) -> None:
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    if content_encoding is not None and content_encoding.casefold().strip() != "identity":
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    if content_type is None:
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    parts = tuple(part.strip() for part in content_type.split(";"))
    if not parts or parts[0].casefold() != "application/json":
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
    parameters: dict[str, str] = {}
    for parameter in parts[1:]:
        if "=" not in parameter:
            raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
        name, value = (item.strip() for item in parameter.split("=", 1))
        normalized_value = value.strip('"').casefold()
        if name.casefold() in parameters or name.casefold() != "charset":
            raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
        parameters[name.casefold()] = normalized_value
    if parameters.get("charset", "utf-8") != "utf-8":
        raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is forbidden")


def _materialize_object(value: object, path: str) -> tuple[object, tuple[str, ...]]:
    duplicates: set[str] = set()
    if isinstance(value, _JSONObject):
        result: dict[str, object] = {}
        for key, child in value:
            pointer = f"{path}/{_escape_pointer(key)}"
            materialized, child_duplicates = _materialize_object(child, pointer)
            duplicates.update(child_duplicates)
            if key in result:
                duplicates.add(pointer)
            result[key] = materialized
        return result, tuple(sorted(duplicates))
    if isinstance(value, list):
        result_list: list[object] = []
        for index, child in enumerate(value):
            materialized, child_duplicates = _materialize_object(child, f"{path}/{index}")
            result_list.append(materialized)
            duplicates.update(child_duplicates)
        return result_list, tuple(sorted(duplicates))
    return value, ()


def _patient_key_paths(value: object, path: str) -> tuple[str, ...]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            pointer = f"{path}/{_escape_pointer(key)}"
            normalized = key.casefold().replace("-", "_").replace(" ", "_")
            if normalized in PATIENT_KEYS:
                paths.add(pointer)
            paths.update(_patient_key_paths(child, pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.update(_patient_key_paths(child, f"{path}/{index}"))
    return tuple(sorted(paths))


def _unknown_concept_paths(data: dict[str, object]) -> tuple[str, ...]:
    paths: set[str] = set()
    for field, known in (
        ("drug_concept_ids", DRUG_CONCEPT_IDS),
        ("adverse_event_concept_ids", ADVERSE_EVENT_CONCEPT_IDS),
    ):
        values = data.get(field)
        if isinstance(values, list):
            paths.update(
                f"/{field}/{index}"
                for index, value in enumerate(values)
                if isinstance(value, str) and value not in known
            )
    return tuple(sorted(paths))


def _validation_paths(error: Exception) -> tuple[str, ...]:
    if not isinstance(error, ValidationError):
        return ("",)
    paths: set[str] = set()
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        loc = item["loc"]
        paths.add("".join(f"/{_escape_pointer(str(part))}" for part in loc))
    return tuple(sorted(paths or {""}))


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


__all__ = [
    "ADVERSE_EVENT_CONCEPT_IDS",
    "DRUG_CONCEPT_IDS",
    "MAX_REQUEST_BYTES",
    "ApiInclusiveDateRange",
    "RequestContractFailure",
    "ResearchPubMedApiRequest",
    "validate_raw_dailymed_request",
    "validate_raw_json_request",
]
