"""Versioned M1A PubMed and additive M1B DailyMed application routes."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from medevidence.catalog import CATALOG_CONTENT_HASH, load_production_catalog
from medevidence.domain import (
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    M1BResearchReportV1,
    M1BResearchRequestV1,
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ResearchReport,
    ResultStatus,
    SourceOutcome,
    SourcePlanEntry,
    SourceType,
    derive_identity,
    sha256_digest,
)
from medevidence.tools import ResearchPubMedRequest
from medevidence.tools.pubmed import build_pubmed_query, query_identity

from .contracts import (
    MAX_REQUEST_BYTES,
    RequestContractFailure,
    ResearchPubMedApiRequest,
    validate_raw_dailymed_request,
    validate_raw_json_request,
)
from .errors import (
    ERROR_SPECS,
    ApiErrorCode,
    ApiErrorResponse,
    ApplicationFailure,
    ToolContractFailure,
    error_response,
)

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(
    r"request:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
REQUEST_EXAMPLE = {
    "schema_version": "1.0",
    "catalog_version": "m1a-concepts-v1",
    "execution_profile_id": "M1A_CONSTRAINED_V1",
    "drug_concept_ids": ["m1a.drug.semaglutide"],
    "adverse_event_concept_ids": ["m1a.event.gastrointestinal"],
    "selected_sources": ["pubmed"],
    "comparison_intent": "summarize",
}


class _Dependencies(Protocol):
    @property
    def application(self) -> Callable[[ResearchPubMedRequest], ResearchReport]: ...

    @property
    def dailymed_application(
        self,
    ) -> Callable[[M1BResearchRequestV1], M1BResearchReportV1] | None: ...

    @property
    def request_id_factory(self) -> Callable[[], str]: ...

    @property
    def run_id_factory(self) -> Callable[[], str]: ...

    @property
    def utc_now(self) -> Callable[[], datetime]: ...

    @property
    def code_revision(self) -> str: ...


def create_router(dependencies: _Dependencies) -> APIRouter:
    """Bind enabled research routes to explicit, side-effect-free dependencies."""

    router = APIRouter()

    @router.post(
        "/v1/research/pubmed",
        operation_id="research_pubmed_v1",
        tags=["research"],
        summary="Research PubMed evidence",
        description=(
            "Execute the bounded M1A PubMed workflow and return the persisted,\n"
            "source-attributed, draft ResearchReport. Valid degraded reports remain HTTP\n"
            "200 and carry their typed limitations."
        ),
        response_description="Persisted draft research report.",
        response_model=ResearchReport,
        responses=_documented_responses(),
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ResearchPubMedApiRequest"},
                        "examples": {
                            "summarize_semaglutide_gastrointestinal": {"value": REQUEST_EXAMPLE}
                        },
                    }
                },
            }
        },
    )
    async def research_pubmed(request: Request) -> ResearchReport | JSONResponse:
        try:
            request_id = dependencies.request_id_factory()
            if _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
                raise ValueError("request ID factory returned an invalid identity")
        except Exception:
            fallback_request_id = f"request:{uuid4()}"
            return _error_json(ApiErrorCode.INTERNAL_ERROR, fallback_request_id, ())
        try:
            raw = await _bounded_body(request)
            api_request = validate_raw_json_request(
                raw,
                content_type=request.headers.get("content-type"),
                content_encoding=request.headers.get("content-encoding"),
            )
        except RequestContractFailure as error:
            return _error_json(error.code, request_id, error.field_paths)

        try:
            tool_request = ResearchPubMedRequest(
                request_id=request_id,
                run_id=dependencies.run_id_factory(),
                created_at_utc=dependencies.utc_now(),
                code_revision=dependencies.code_revision,
                scope=api_request.to_scope(),
            )
            returned = dependencies.application(tool_request)
            report = ResearchReport.model_validate(
                returned.model_dump(mode="python", warnings="error")
                if isinstance(returned, ResearchReport)
                else returned,
                strict=True,
            )
        except ApplicationFailure as error:
            return _error_json(error.code, request_id, error.field_paths)
        except (ValidationError, PydanticSerializationError):
            tool_error = ToolContractFailure()
            return _error_json(tool_error.code, request_id, tool_error.field_paths)
        except Exception:
            return _error_json(ApiErrorCode.INTERNAL_ERROR, request_id, ())
        return report

    if dependencies.dailymed_application is None:
        return router

    @router.post(
        "/v1/research/dailymed",
        operation_id="research_dailymed_v1",
        tags=["research"],
        summary="Research DailyMed label evidence",
        description=(
            "Build an additive M1B DailyMed report from exact trusted evidence.\n"
            "The response remains research-only, draft, and non-exportable."
        ),
        response_description="Validated draft DailyMed research report.",
        response_model=M1BResearchReportV1,
        responses=_dailymed_documented_responses(),
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/M1BResearchRequestV1"}
                    }
                },
            }
        },
    )
    async def research_dailymed(request: Request) -> M1BResearchReportV1 | JSONResponse:
        try:
            request_id = dependencies.request_id_factory()
            if _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
                raise ValueError("request ID factory returned an invalid identity")
        except Exception:
            request_id = f"request:{uuid4()}"
        try:
            raw = await _bounded_body(request)
            api_request = validate_raw_dailymed_request(
                raw,
                content_type=request.headers.get("content-type"),
                content_encoding=request.headers.get("content-encoding"),
            )
            request_id = api_request.request_id
        except RequestContractFailure as error:
            return _error_json(error.code, request_id, error.field_paths)

        try:
            if dependencies.dailymed_application is None:
                raise ToolContractFailure()
            returned = dependencies.dailymed_application(api_request)
            raw_report = (
                returned.model_dump(
                    mode="python",
                    warnings="error",
                    exclude_unset=True,
                )
                if isinstance(returned, M1BResearchReportV1)
                else returned
            )
            report = M1BResearchReportV1.model_validate(
                raw_report,
                strict=True,
            )
            _require_serialized_presence(raw_report, report)
            _validate_dailymed_response(report, api_request)
        except ApplicationFailure as error:
            return _error_json(error.code, request_id, error.field_paths)
        except (ValidationError, PydanticSerializationError):
            tool_error = ToolContractFailure()
            return _error_json(tool_error.code, request_id, tool_error.field_paths)
        except Exception:
            return _error_json(ApiErrorCode.INTERNAL_ERROR, request_id, ())
        return report

    return router


async def _bounded_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REQUEST_BYTES:
            raise RequestContractFailure(ApiErrorCode.INVALID_REQUEST, ("",))
        body.extend(chunk)
    return bytes(body)


def _error_json(
    code: ApiErrorCode,
    request_id: str,
    field_paths: tuple[str, ...],
) -> JSONResponse:
    status, _, _ = ERROR_SPECS[code]
    logger.info(
        "versioned API request failed",
        extra={"api_error_code": code.value, "request_id": request_id},
    )
    response = error_response(code, request_id, field_paths)
    return JSONResponse(status_code=status, content=response.model_dump(mode="json"))


def _documented_responses() -> dict[int | str, dict[str, object]]:
    grouped: dict[int, dict[str, object]] = {}
    for code, (status, _, _) in ERROR_SPECS.items():
        example = error_response(
            code,
            "request:00000000-0000-4000-8000-000000000001",
            _example_field_paths(code),
        ).model_dump(mode="json")
        grouped.setdefault(status, {})[code.value] = {"value": example}
    responses: dict[int | str, dict[str, object]] = {
        200: {
            "description": "Persisted draft research report.",
            "content": {
                "application/json": {
                    "examples": {"complete_no_match": {"value": _complete_no_match_example()}}
                }
            },
        }
    }
    for status, examples in grouped.items():
        responses[status] = {
            "model": ApiErrorResponse,
            "description": "Versioned application error.",
            "content": {"application/json": {"examples": examples}},
        }
    return responses


def _dailymed_documented_responses() -> dict[int | str, dict[str, object]]:
    documented_codes = {
        ApiErrorCode.INVALID_REQUEST,
        ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION,
        ApiErrorCode.SUSPECTED_PATIENT_DATA,
        ApiErrorCode.INTERNAL_ERROR,
        ApiErrorCode.TOOL_CONTRACT_ERROR,
        ApiErrorCode.ARTIFACT_INTEGRITY_FAILURE,
        ApiErrorCode.STORAGE_BUSY,
        ApiErrorCode.STORAGE_CAPACITY_UNAVAILABLE,
        ApiErrorCode.PERSISTENCE_UNAVAILABLE,
        ApiErrorCode.PERSISTENCE_INTEGRITY_FAILURE,
        ApiErrorCode.DEADLINE_EXCEEDED_BEFORE_OUTCOME,
    }
    grouped: dict[int, dict[str, object]] = {}
    for code in documented_codes:
        status, _, _ = ERROR_SPECS[code]
        example = error_response(
            code,
            "request:00000000-0000-4000-8000-000000000001",
            {
                ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION: ("/schema_version",),
                ApiErrorCode.SUSPECTED_PATIENT_DATA: ("/patient",),
            }.get(code, ()),
        ).model_dump(mode="json")
        grouped.setdefault(status, {})[code.value] = {"value": example}
    responses: dict[int | str, dict[str, object]] = {
        200: {
            "description": "Validated draft DailyMed research report.",
        }
    }
    for status, examples in grouped.items():
        responses[status] = {
            "model": ApiErrorResponse,
            "description": "Versioned application error.",
            "content": {"application/json": {"examples": examples}},
        }
    return responses


def _require_serialized_presence(raw: object, parsed: object) -> None:
    """Reject any omitted field before defaults can complete a returned contract."""

    if isinstance(parsed, BaseModel):
        if not isinstance(raw, dict) or set(type(parsed).model_fields) - set(raw):
            raise ToolContractFailure()
        for name in type(parsed).model_fields:
            _require_serialized_presence(raw[name], getattr(parsed, name))
        return
    if isinstance(parsed, (tuple, list)):
        if not isinstance(raw, (tuple, list)) or len(raw) != len(parsed):
            raise ToolContractFailure()
        for raw_item, parsed_item in zip(raw, parsed, strict=True):
            _require_serialized_presence(raw_item, parsed_item)


def _validate_dailymed_response(
    report: M1BResearchReportV1,
    request: M1BResearchRequestV1,
) -> None:
    expected_plan = (
        M1BSourcePlanEntryV1(
            source=SourceType.DAILYMED,
            planning_status=PlanningStatus.SELECTED,
        ),
    )
    if (
        report.request_id != request.request_id
        or report.scope != request.scope
        or report.source_plan != expected_plan
        or tuple(section.request for section in report.source_sections)
        != request.dailymed_selection_requests
    ):
        raise ToolContractFailure()


def _example_field_paths(code: ApiErrorCode) -> tuple[str, ...]:
    return {
        ApiErrorCode.INVALID_REQUEST: ("",),
        ApiErrorCode.UNSUPPORTED_SCHEMA_VERSION: ("/schema_version",),
        ApiErrorCode.UNSUPPORTED_CATALOG_VERSION: ("/catalog_version",),
        ApiErrorCode.UNSUPPORTED_EXECUTION_PROFILE: ("/execution_profile_id",),
        ApiErrorCode.SUSPECTED_PATIENT_DATA: ("/patient",),
        ApiErrorCode.UNKNOWN_CONCEPT_ID: ("/drug_concept_ids/0",),
        ApiErrorCode.INVALID_SCOPE: ("/selected_sources",),
    }.get(code, ())


def _complete_no_match_example() -> dict[str, object]:
    request = ResearchPubMedApiRequest.model_validate_json(
        json.dumps(REQUEST_EXAMPLE, separators=(",", ":")),
        strict=True,
    )
    scope = request.to_scope(load_production_catalog())
    catalog = load_production_catalog().resolve_scope(scope)
    query = build_pubmed_query(scope, catalog)
    query_id = query_identity(scope, query)
    outcome = SourceOutcome(
        source=SourceType.PUBMED,
        query_id=query_id,
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.NO_MATCH,
        configured_bounds=ExecutionBounds.from_scope(scope),
        valid_result_count=0,
        pages_completed=1,
        truncated=False,
    )
    snapshot_id = sha256_digest(b"<eSearchResult><Count>0</Count></eSearchResult>")
    report = ResearchReport.create(
        run_id="run:00000000-0000-4000-8000-000000000002",
        catalog_content_hash=CATALOG_CONTENT_HASH,
        run_intent_id=derive_identity(
            "run-intent",
            {
                "request_id": "request:00000000-0000-4000-8000-000000000001",
                "run_id": "run:00000000-0000-4000-8000-000000000002",
                "created_at_utc": "2026-08-08T12:00:00.000000Z",
                "code_revision": "0" * 40,
                "scope_id": scope.scope_id,
                "query": query,
            },
        ),
        acquisition_snapshot_ids=(snapshot_id,),
        acquisition_manifest_ids=(snapshot_id,),
        acquisition_registration_envelope_ids=(
            derive_identity(
                "registration-envelope:acquisition",
                {
                    "attempt_id": "attempt:00000000-0000-4000-8000-000000000003",
                    "snapshot_id": snapshot_id,
                },
            ),
        ),
        scope=scope,
        source_plan=(
            SourcePlanEntry(
                source=SourceType.PUBMED,
                planning_status=PlanningStatus.SELECTED,
            ),
        ),
        source_outcomes=(outcome,),
        publications=(),
        claims=(),
        citations=(),
        source_status_warnings=(),
        claim_status_warnings=(),
        coverage_limitations=(),
        retrieval_as_of=datetime(2026, 8, 8, 12, 0, 2, tzinfo=UTC),
    )
    validated = ResearchReport.model_validate(report.model_dump(mode="python"), strict=True)
    return cast(dict[str, object], validated.model_dump(mode="json"))


__all__ = ["REQUEST_EXAMPLE", "create_router"]
