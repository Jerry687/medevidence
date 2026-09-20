"""Additive local V1 research routes over one injected application port."""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from typing import Any, Self, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, model_validator
from pydantic_core import PydanticSerializationError

from medevidence.domain import RunId
from medevidence.tools.research_application import (
    ResearchApplicationErrorCode,
    ResearchApplicationFailure,
    ResearchApplicationPort,
    ResearchExportArtifact,
    ResearchExportFormat,
    ResearchReportView,
    ResearchReviewCommand,
    ResearchReviewDecision,
    ResearchRunList,
    ResearchRunStatus,
    ResearchRunView,
    ResearchSubmission,
)

_MAX_BODY_BYTES = 65_536
_RUN_ID: TypeAdapter[str] = TypeAdapter(RunId)
_CANONICAL_INTEGER = re.compile(r"0|[1-9][0-9]{0,5}\Z")
_LOGGER = logging.getLogger(__name__)


class ResearchHttpErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    SCOPE_REJECTED = "scope_rejected"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    INVALID_APPLICATION_RESULT = "invalid_application_result"
    INTERNAL_ERROR = "internal_error"


_ERROR: dict[ResearchHttpErrorCode, tuple[int, str]] = {
    ResearchHttpErrorCode.INVALID_REQUEST: (422, "The request is invalid."),
    ResearchHttpErrorCode.SCOPE_REJECTED: (422, "The research scope was rejected."),
    ResearchHttpErrorCode.NOT_FOUND: (404, "The research run was not found."),
    ResearchHttpErrorCode.CONFLICT: (409, "The request conflicts with the current report state."),
    ResearchHttpErrorCode.UNAVAILABLE: (503, "The research application is unavailable."),
    ResearchHttpErrorCode.INVALID_APPLICATION_RESULT: (
        502,
        "The application returned an invalid result.",
    ),
    ResearchHttpErrorCode.INTERNAL_ERROR: (500, "An internal error occurred."),
}


class ResearchHttpErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ResearchHttpErrorCode
    message: str

    @model_validator(mode="after")
    def validate_fixed_message(self) -> Self:
        if self.message != _ERROR[self.code][1]:
            raise ValueError("HTTP error message differs from fixed contract")
        return self


class ResearchHttpErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    error: ResearchHttpErrorDetail


def _responses(*codes: ResearchHttpErrorCode) -> dict[int | str, dict[str, Any]]:
    return {
        _ERROR[code][0]: {
            "description": _ERROR[code][1],
            "model": ResearchHttpErrorResponse,
        }
        for code in codes
    }


def _operation_extra(
    *,
    body_model: str | None = None,
    run_id: bool = False,
    listing: bool = False,
    export: bool = False,
) -> dict[str, object]:
    """Document only the bounded parameters accepted by the manual parser."""

    result: dict[str, object] = {}
    if body_model is not None:
        result["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{body_model}"}}
            },
        }
    parameters: list[dict[str, object]] = []
    if run_id:
        parameters.append(
            {
                "name": "run_id",
                "in": "path",
                "required": True,
                "schema": _RUN_ID.json_schema(),
            }
        )
    if listing:
        parameters.extend(
            (
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                {
                    "name": "offset",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "minimum": 0, "maximum": 100_000, "default": 0},
                },
            )
        )
    if export:
        parameters.append(
            {
                "name": "format",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "enum": [item.value for item in ResearchExportFormat]},
            }
        )
    if parameters:
        result["parameters"] = parameters
    return result


def _error(code: ResearchHttpErrorCode) -> JSONResponse:
    status, message = _ERROR[code]
    body = ResearchHttpErrorResponse(error=ResearchHttpErrorDetail(code=code, message=message))
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
    )


def _application_error(error: ResearchApplicationFailure) -> JSONResponse:
    code = {
        ResearchApplicationErrorCode.SCOPE_REJECTED: ResearchHttpErrorCode.SCOPE_REJECTED,
        ResearchApplicationErrorCode.NOT_FOUND: ResearchHttpErrorCode.NOT_FOUND,
        ResearchApplicationErrorCode.CONFLICT: ResearchHttpErrorCode.CONFLICT,
        ResearchApplicationErrorCode.UNAVAILABLE: ResearchHttpErrorCode.UNAVAILABLE,
    }[error.code]
    return _error(code)


def _internal_error() -> JSONResponse:
    _LOGGER.error("research application operation failed")
    return _error(ResearchHttpErrorCode.INTERNAL_ERROR)


def _checked[T: BaseModel](value: object, expected: type[T]) -> T:
    if type(value) is not expected:
        raise ValueError("application result has wrong type")
    payload = value.model_dump(mode="python")
    if type(value) is ResearchReportView:
        payload["document"] = cast(ResearchReportView, value).document
    return expected.model_validate(payload, strict=True)


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON value")


def _path_run_id(request: Request) -> str:
    return _RUN_ID.validate_python(request.path_params["run_id"], strict=True)


def _query_integer(request: Request, name: str, default: int, maximum: int) -> int:
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise ValueError("query parameter is duplicated")
    if not values:
        return default
    raw = values[0]
    if _CANONICAL_INTEGER.fullmatch(raw) is None:
        raise ValueError("query parameter is not canonical")
    value = int(raw)
    if value < (1 if name == "limit" else 0) or value > maximum:
        raise ValueError("query parameter exceeds bound")
    return value


async def _parse_body[T: BaseModel](request: Request, expected: type[T]) -> T:
    content_type = request.headers.get("content-type", "")
    media, _, parameters = content_type.partition(";")
    if media.strip().casefold() != "application/json":
        raise ValueError("request content type is invalid")
    if parameters and parameters.strip().casefold() not in {"charset=utf-8", 'charset="utf-8"'}:
        raise ValueError("request charset is invalid")
    if request.headers.get("content-encoding", "identity").casefold() != "identity":
        raise ValueError("request encoding is invalid")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        body.extend(chunk)
    if not body:
        raise ValueError("request body is empty")
    text = body.decode("utf-8")
    if text.startswith("\ufeff"):
        raise ValueError("UTF-8 BOM is not permitted")
    raw = json.loads(text, object_pairs_hook=_unique_object_pairs, parse_constant=_reject_constant)
    if type(raw) is not dict:
        raise ValueError("request body must be an object")
    return expected.model_validate_json(body, strict=True)


def create_research_router(application: ResearchApplicationPort | None) -> APIRouter:
    """Expose only typed application calls; an absent runtime returns 503."""

    router = APIRouter(tags=["research-v1"])

    @router.post(
        "/v1/research/runs",
        response_model=ResearchRunView,
        status_code=202,
        openapi_extra=_operation_extra(body_model="ResearchSubmission"),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.SCOPE_REJECTED,
            ResearchHttpErrorCode.CONFLICT,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    async def submit(request: Request) -> ResearchRunView | JSONResponse:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            command = await _parse_body(request, ResearchSubmission)
        except (ValueError, UnicodeDecodeError, ValidationError, json.JSONDecodeError):
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        try:
            result = _checked(application.submit(command), ResearchRunView)
            if result.scope_id != command.scope.scope_id:
                raise ValueError("submitted scope identity drift")
            return result
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()

    @router.get(
        "/v1/research/runs",
        response_model=ResearchRunList,
        openapi_extra=_operation_extra(listing=True),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    def list_runs(request: Request) -> ResearchRunList | JSONResponse:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            if set(request.query_params) - {"limit", "offset"}:
                raise ValueError("unknown query parameter")
            limit = _query_integer(request, "limit", 20, 50)
            offset = _query_integer(request, "offset", 0, 100_000)
        except ValueError:
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        try:
            result = _checked(application.list_runs(limit=limit, offset=offset), ResearchRunList)
            if len(result.items) > limit:
                raise ValueError("application returned more than the requested limit")
            return result
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()

    @router.get(
        "/v1/research/runs/{run_id}",
        response_model=ResearchRunView,
        openapi_extra=_operation_extra(run_id=True),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.NOT_FOUND,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    def get_run(request: Request) -> ResearchRunView | JSONResponse:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            run_id = _path_run_id(request)
        except ValidationError:
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        try:
            result = _checked(application.get_run(run_id), ResearchRunView)
            if result.run_id != run_id:
                raise ValueError("run identity drift")
            return result
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()

    @router.get(
        "/v1/research/runs/{run_id}/report",
        response_model=ResearchReportView,
        openapi_extra=_operation_extra(run_id=True),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.NOT_FOUND,
            ResearchHttpErrorCode.CONFLICT,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    def get_report(request: Request) -> ResearchReportView | JSONResponse:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            run_id = _path_run_id(request)
        except ValidationError:
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        try:
            result = _checked(application.get_report(run_id), ResearchReportView)
            if result.run.run_id != run_id:
                raise ValueError("report run identity drift")
            return result
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()

    @router.post(
        "/v1/research/runs/{run_id}/review",
        response_model=ResearchRunView,
        openapi_extra=_operation_extra(run_id=True, body_model="ResearchReviewCommand"),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.NOT_FOUND,
            ResearchHttpErrorCode.CONFLICT,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    async def review(request: Request) -> ResearchRunView | JSONResponse:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            run_id = _path_run_id(request)
            command = await _parse_body(request, ResearchReviewCommand)
        except (ValueError, UnicodeDecodeError, ValidationError, json.JSONDecodeError):
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        if command.run_id != run_id:
            return _error(ResearchHttpErrorCode.CONFLICT)
        try:
            result = _checked(application.review(command), ResearchRunView)
            if (
                result.run_id != run_id
                or result.report_id != command.report_id
                or result.destination_id != command.destination_id
            ):
                raise ValueError("review result identity drift")
            if command.decision is not ResearchReviewDecision.EDIT and (
                result.report_content_hash != command.report_content_hash
                or result.render_document_hash != command.render_document_hash
                or result.pending_draft_id != command.pending_draft_id
            ):
                raise ValueError("review result report binding drift")
            return result
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()

    @router.get(
        "/v1/research/runs/{run_id}/export",
        response_class=Response,
        openapi_extra=_operation_extra(run_id=True, export=True),
        responses=_responses(
            ResearchHttpErrorCode.INVALID_REQUEST,
            ResearchHttpErrorCode.NOT_FOUND,
            ResearchHttpErrorCode.CONFLICT,
            ResearchHttpErrorCode.UNAVAILABLE,
            ResearchHttpErrorCode.INVALID_APPLICATION_RESULT,
            ResearchHttpErrorCode.INTERNAL_ERROR,
        ),
    )
    def download_export(request: Request) -> Response:
        if application is None:
            return _error(ResearchHttpErrorCode.UNAVAILABLE)
        try:
            run_id = _path_run_id(request)
            if (
                set(request.query_params) != {"format"}
                or len(request.query_params.getlist("format")) != 1
            ):
                raise ValueError("export format query is invalid")
            format = ResearchExportFormat(request.query_params["format"])
        except (ValueError, ValidationError):
            return _error(ResearchHttpErrorCode.INVALID_REQUEST)
        try:
            current = _checked(application.get_run(run_id), ResearchRunView)
            if current.run_id != run_id:
                raise ValueError("export run identity drift")
            if current.status is not ResearchRunStatus.EXPORTED:
                return _error(ResearchHttpErrorCode.CONFLICT)
            artifact = _checked(application.download_export(run_id, format), ResearchExportArtifact)
            if (
                artifact.run_id != run_id
                or artifact.format is not format
                or artifact.report_id != current.report_id
                or artifact.report_content_hash != current.report_content_hash
                or artifact.render_document_hash != current.render_document_hash
            ):
                raise ValueError("export result identity drift")
        except ResearchApplicationFailure as error:
            return _application_error(error)
        except (ValueError, ValidationError, PydanticSerializationError, TypeError):
            return _error(ResearchHttpErrorCode.INVALID_APPLICATION_RESULT)
        except Exception:
            return _internal_error()
        suffix = artifact.report_id.removeprefix("report:sha256:")
        extension = "json" if format is ResearchExportFormat.JSON else "md"
        content_type = (
            "application/json" if format is ResearchExportFormat.JSON else "text/markdown"
        )
        return Response(
            content=artifact.content,
            media_type=f"{content_type}; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="medevidence-{suffix}.{extension}"',
                "X-Content-SHA256": artifact.content_hash,
            },
        )

    return router
