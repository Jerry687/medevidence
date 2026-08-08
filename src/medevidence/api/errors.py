"""Closed, redacted M1A application-error taxonomy."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

RequestId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^request:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
    ),
]
JsonPointer = Annotated[str, StringConstraints(max_length=512)]


class ApiErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    UNSUPPORTED_CATALOG_VERSION = "unsupported_catalog_version"
    UNSUPPORTED_EXECUTION_PROFILE = "unsupported_execution_profile"
    SUSPECTED_PATIENT_DATA = "suspected_patient_data"
    UNKNOWN_CONCEPT_ID = "unknown_concept_id"
    INVALID_SCOPE = "invalid_scope"
    STORAGE_BUSY = "storage_busy"
    STORAGE_CAPACITY_UNAVAILABLE = "storage_capacity_unavailable"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
    PERSISTENCE_INTEGRITY_FAILURE = "persistence_integrity_failure"
    TOOL_CONTRACT_ERROR = "tool_contract_error"
    ARTIFACT_INTEGRITY_FAILURE = "artifact_integrity_failure"
    DEADLINE_EXCEEDED_BEFORE_OUTCOME = "deadline_exceeded_before_outcome"
    INTERNAL_ERROR = "internal_error"


ERROR_SPECS: Final[dict[ApiErrorCode, tuple[int, bool, str]]] = {
    ApiErrorCode.INVALID_REQUEST: (422, False, "The request is invalid."),
    ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION: (
        422,
        False,
        "The request schema version is not supported.",
    ),
    ApiErrorCode.UNSUPPORTED_CATALOG_VERSION: (
        422,
        False,
        "The catalog version is not supported.",
    ),
    ApiErrorCode.UNSUPPORTED_EXECUTION_PROFILE: (
        422,
        False,
        "The execution profile is not supported.",
    ),
    ApiErrorCode.SUSPECTED_PATIENT_DATA: (
        422,
        False,
        "The request contains fields that are not permitted for this research API.",
    ),
    ApiErrorCode.UNKNOWN_CONCEPT_ID: (
        422,
        False,
        "One or more concept identifiers are not present in the approved catalog.",
    ),
    ApiErrorCode.INVALID_SCOPE: (
        422,
        False,
        "The research scope is invalid for the M1A PubMed workflow.",
    ),
    ApiErrorCode.STORAGE_BUSY: (503, True, "Snapshot storage is busy. Retry later."),
    ApiErrorCode.STORAGE_CAPACITY_UNAVAILABLE: (
        503,
        True,
        "Snapshot storage capacity is unavailable. Retry later.",
    ),
    ApiErrorCode.PERSISTENCE_UNAVAILABLE: (
        503,
        True,
        "Persistence is temporarily unavailable. Retry later.",
    ),
    ApiErrorCode.PERSISTENCE_INTEGRITY_FAILURE: (
        503,
        False,
        "Persistence integrity validation failed.",
    ),
    ApiErrorCode.TOOL_CONTRACT_ERROR: (
        502,
        False,
        "The application tool returned an invalid result.",
    ),
    ApiErrorCode.ARTIFACT_INTEGRITY_FAILURE: (
        502,
        False,
        "Evidence artifact integrity validation failed.",
    ),
    ApiErrorCode.DEADLINE_EXCEEDED_BEFORE_OUTCOME: (
        504,
        True,
        "The operation deadline was exceeded before a valid persisted outcome was available.",
    ),
    ApiErrorCode.INTERNAL_ERROR: (500, False, "An internal error occurred."),
}


class ApiErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ApiErrorCode
    message: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    request_id: RequestId
    retryable: bool
    field_paths: tuple[JsonPointer, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_fixed_contract(self) -> Self:
        _, retryable, message = ERROR_SPECS[self.code]
        if self.retryable is not retryable or self.message != message:
            raise ValueError("API error detail differs from the fixed error contract")
        if self.field_paths != tuple(sorted(set(self.field_paths))):
            raise ValueError("field paths must be sorted and unique")
        return self


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"] = "1.0"
    error: ApiErrorDetail


class ApplicationFailure(Exception):
    """Typed application-boundary failure with no adapter diagnostics."""

    code: ApiErrorCode = ApiErrorCode.INTERNAL_ERROR

    def __init__(self, field_paths: tuple[str, ...] = ()) -> None:
        self.field_paths = tuple(sorted(set(field_paths)))
        super().__init__(self.code.value)


class StorageBusyFailure(ApplicationFailure):
    code = ApiErrorCode.STORAGE_BUSY


class StorageCapacityFailure(ApplicationFailure):
    code = ApiErrorCode.STORAGE_CAPACITY_UNAVAILABLE


class PersistenceUnavailableFailure(ApplicationFailure):
    code = ApiErrorCode.PERSISTENCE_UNAVAILABLE


class PersistenceIntegrityFailure(ApplicationFailure):
    code = ApiErrorCode.PERSISTENCE_INTEGRITY_FAILURE


class ToolContractFailure(ApplicationFailure):
    code = ApiErrorCode.TOOL_CONTRACT_ERROR


class ArtifactIntegrityFailure(ApplicationFailure):
    code = ApiErrorCode.ARTIFACT_INTEGRITY_FAILURE


class DeadlineExceededFailure(ApplicationFailure):
    code = ApiErrorCode.DEADLINE_EXCEEDED_BEFORE_OUTCOME


def error_response(
    code: ApiErrorCode,
    request_id: str,
    field_paths: tuple[str, ...] = (),
) -> ApiErrorResponse:
    """Construct one exact fixed-message error response."""

    _, retryable, message = ERROR_SPECS[code]
    return ApiErrorResponse.model_validate(
        {
            "schema_version": "1.0",
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "retryable": retryable,
                "field_paths": tuple(sorted(set(field_paths))),
            },
        },
        strict=True,
    )


__all__ = [
    "ERROR_SPECS",
    "ApiErrorCode",
    "ApiErrorDetail",
    "ApiErrorResponse",
    "ApplicationFailure",
    "ArtifactIntegrityFailure",
    "DeadlineExceededFailure",
    "PersistenceIntegrityFailure",
    "PersistenceUnavailableFailure",
    "StorageBusyFailure",
    "StorageCapacityFailure",
    "ToolContractFailure",
    "error_response",
]
