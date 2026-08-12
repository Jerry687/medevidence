"""Explicit FastAPI application factory with no implicit live adapters."""

from __future__ import annotations

import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from fastapi import FastAPI
from pydantic import BaseModel

from medevidence.domain import M1BResearchReportV1, M1BResearchRequestV1, ResearchReport
from medevidence.tools import ResearchPubMedRequest

from .contracts import ApiInclusiveDateRange, ResearchPubMedApiRequest
from .errors import ApiErrorDetail, ApiErrorResponse
from .routes import create_router

_CODE_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_RESPONSE_COMPONENT_SUFFIX = "Response"


@dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Only the source-neutral application call and injected runtime values."""

    application: Callable[[ResearchPubMedRequest], ResearchReport]
    request_id_factory: Callable[[], str]
    run_id_factory: Callable[[], str]
    utc_now: Callable[[], datetime]
    code_revision: str
    dailymed_application: Callable[[M1BResearchRequestV1], M1BResearchReportV1] | None = None

    def __post_init__(self) -> None:
        if _CODE_REVISION_PATTERN.fullmatch(self.code_revision) is None:
            raise ValueError("code_revision must be an exact lowercase 40-character Git commit")


def create_app(dependencies: ApiDependencies) -> FastAPI:
    """Create the offline-safe M1A API from explicit injected dependencies."""

    dailymed_enabled = dependencies.dailymed_application is not None
    description = (
        "Versioned research-only transport for bounded PubMed and DailyMed evidence.\n"
        if dailymed_enabled
        else "Versioned research-only transport for the bounded M1A PubMed vertical slice.\n"
    ) + (
        "Responses are draft, non-exportable, and source-attributed. The API does not\n"
        "provide diagnosis, treatment, dosage, individualized medical advice, or a\n"
        "product-safety ranking."
    )
    app = FastAPI(
        title="MedEvidence API",
        summary="Traceable drug-safety evidence research API",
        description=description,
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
    _register_public_components(app, dailymed_enabled=dailymed_enabled)
    return app


def _register_public_components(app: FastAPI, *, dailymed_enabled: bool) -> None:
    original = app.openapi

    def openapi() -> dict[str, object]:
        schema = original()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        models: list[type[BaseModel]] = [
            ApiInclusiveDateRange,
            ResearchPubMedApiRequest,
            ApiErrorDetail,
            ApiErrorResponse,
        ]
        if dailymed_enabled:
            models.append(M1BResearchRequestV1)
        for model in models:
            components[model.__name__] = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
        required_fields = {
            "DailyMedLocatorV1": ("schema_version", "locator_kind", "source"),
            "DailyMedSelectionRequestV1": ("schema_version",),
            "M1BResearchRequestV1": ("schema_version",),
            "M1BSourcePlanEntryV1": ("schema_version",),
            "M1BSourceSection": ("schema_version", "section_kind", "source"),
        }
        report_component = components.get("M1BResearchReportV1")
        if isinstance(report_component, dict):
            properties = report_component.get("properties", {})
            if isinstance(properties, dict):
                required_fields["M1BResearchReportV1"] = tuple(properties)
        for component_name, discriminator_fields in required_fields.items():
            component = components.get(component_name)
            if isinstance(component, dict):
                required = set(component.get("required", ()))
                required.update(discriminator_fields)
                component["required"] = sorted(required)
        if dailymed_enabled:
            paths = schema.get("paths", {})
            if not isinstance(paths, dict):
                raise ValueError("OpenAPI paths must be a mapping")
            pubmed_path = paths.get("/v1/research/pubmed")
            if not isinstance(pubmed_path, dict):
                raise ValueError("PubMed OpenAPI path is missing")
            _require_dailymed_response_fields(components, pubmed_path=pubmed_path)
        return cast(dict[str, object], schema)

    app.openapi = openapi  # type: ignore[method-assign]


def _require_dailymed_response_fields(
    components: dict[str, object], *, pubmed_path: dict[str, object]
) -> None:
    """Mirror strict runtime presence without strengthening shared request schemas."""

    response_names = _reachable_components(components, "M1BResearchReportV1")
    request_names = _reachable_components(components, "M1BResearchRequestV1")
    pubmed_names = _component_refs(pubmed_path)
    pending = list(pubmed_names)
    while pending:
        name = pending.pop()
        component = components.get(name)
        if component is None:
            continue
        discovered = _component_refs(component) - pubmed_names
        pubmed_names.update(discovered)
        pending.extend(discovered)
    protected_names = request_names | pubmed_names
    replacements: dict[str, str] = {}
    for name in sorted(response_names & protected_names):
        component = components.get(name)
        if not isinstance(component, dict):
            continue
        properties = component.get("properties")
        if not isinstance(properties, dict):
            continue
        if set(cast(list[str], component.get("required", ()))) != set(properties):
            replacement = f"{name}{_RESPONSE_COMPONENT_SUFFIX}"
            if replacement in components:
                raise ValueError(f"OpenAPI response component collision: {replacement}")
            replacements[name] = replacement

    for name, replacement in replacements.items():
        cloned = deepcopy(cast(dict[str, object], components[name]))
        _rewrite_component_refs(cloned, replacements)
        properties = cast(dict[str, object], cloned["properties"])
        cloned["required"] = sorted(properties)
        components[replacement] = cloned

    for name in sorted(response_names - protected_names):
        component = components.get(name)
        if not isinstance(component, dict):
            continue
        _rewrite_component_refs(component, replacements)
        properties = component.get("properties")
        if isinstance(properties, dict) and set(
            cast(list[str], component.get("required", ()))
        ) != set(properties):
            component["required"] = sorted(properties)


def _reachable_components(components: dict[str, object], root: str) -> set[str]:
    reachable: set[str] = set()
    pending = [root]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        component = components.get(name)
        if component is not None:
            pending.extend(_component_refs(component) - reachable)
    return reachable


def _component_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                prefix = "#/components/schemas/"
                if child.startswith(prefix):
                    refs.add(child.removeprefix(prefix))
            else:
                refs.update(_component_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_component_refs(child))
    return refs


def _rewrite_component_refs(value: object, replacements: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                prefix = "#/components/schemas/"
                name = child.removeprefix(prefix) if child.startswith(prefix) else ""
                if name in replacements:
                    value[key] = f"{prefix}{replacements[name]}"
            else:
                _rewrite_component_refs(child, replacements)
    elif isinstance(value, list):
        for child in value:
            _rewrite_component_refs(child, replacements)


__all__ = ["ApiDependencies", "create_app"]
