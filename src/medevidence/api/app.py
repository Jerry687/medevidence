"""Explicit FastAPI application factory with no implicit live adapters."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from fastapi import FastAPI

from medevidence.domain import ResearchReport
from medevidence.tools import ResearchPubMedRequest

from .contracts import ApiInclusiveDateRange, ResearchPubMedApiRequest
from .errors import ApiErrorDetail, ApiErrorResponse
from .routes import create_router

_CODE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Only the source-neutral application call and injected runtime values."""

    application: Callable[[ResearchPubMedRequest], ResearchReport]
    request_id_factory: Callable[[], str]
    run_id_factory: Callable[[], str]
    utc_now: Callable[[], datetime]
    code_revision: str

    def __post_init__(self) -> None:
        if _CODE_REVISION_PATTERN.fullmatch(self.code_revision) is None:
            raise ValueError("code_revision must be an exact lowercase 40-character Git commit")


def create_app(dependencies: ApiDependencies) -> FastAPI:
    """Create the offline-safe M1A API from explicit injected dependencies."""

    app = FastAPI(
        title="MedEvidence API",
        summary="Traceable drug-safety evidence research API",
        description=(
            "Versioned research-only transport for the bounded M1A PubMed vertical slice.\n"
            "Responses are draft, non-exportable, and source-attributed. The API does not\n"
            "provide diagnosis, treatment, dosage, individualized medical advice, or a\n"
            "product-safety ranking."
        ),
        version="0.0.0",
        openapi_url="/openapi.json",
        docs_url=None,
        redoc_url=None,
        swagger_ui_oauth2_redirect_url=None,
        openapi_tags=[
            {
                "name": "research",
                "description": ("Bounded, traceable, draft-only public-source evidence research."),
            }
        ],
    )
    app.openapi_version = "3.1.0"
    app.include_router(create_router(dependencies))
    _register_public_components(app)
    return app


def _register_public_components(app: FastAPI) -> None:
    original = app.openapi

    def openapi() -> dict[str, object]:
        schema = original()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in (
            ApiInclusiveDateRange,
            ResearchPubMedApiRequest,
            ApiErrorDetail,
            ApiErrorResponse,
        ):
            components[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        return cast(dict[str, object], schema)

    app.openapi = openapi  # type: ignore[method-assign]


__all__ = ["ApiDependencies", "create_app"]
