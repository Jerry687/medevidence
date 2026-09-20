"""Bounded stdio-compatible MCP tools for already-created research runs."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)
from pydantic import ValidationError

from medevidence.domain import RunId
from medevidence.tools.research_application import (
    ResearchApplicationFailure,
    ResearchApplicationPort,
    ResearchReportView,
    ResearchRunList,
    ResearchRunView,
)

_MAX_ARGUMENT_BYTES = 4096
_MAX_RESULT_BYTES = 2_097_152
_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_RUN_ID_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "maxLength": 40,
            "pattern": (
                "^run:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
            ),
        }
    },
    "required": ["run_id"],
    "additionalProperties": False,
}
_TOOLS = [
    Tool(
        name="list_research_runs",
        description="List already-created local research runs and their review status.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
            },
            "additionalProperties": False,
        },
        annotations=_READ_ONLY,
    ),
    Tool(
        name="get_research_run",
        description="Read one already-created run's exact status and report identities.",
        input_schema=_RUN_ID_SCHEMA,
        annotations=_READ_ONLY,
    ),
    Tool(
        name="get_research_report",
        description="Read an existing report draft without changing review or export state.",
        input_schema=_RUN_ID_SCHEMA,
        annotations=_READ_ONLY,
    ),
]


def _failure(code: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": code}))],
        is_error=True,
    )


def _validated_args(value: object) -> dict[str, Any] | None:
    if type(value) is not dict or not all(type(key) is str for key in value):
        return None
    try:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > _MAX_ARGUMENT_BYTES:
            return None
    except (TypeError, ValueError):
        return None
    return value


def _run_id(value: object) -> str | None:
    if type(value) is not str or len(value) > 40:
        return None
    from pydantic import TypeAdapter

    try:
        return TypeAdapter(RunId).validate_python(value, strict=True)
    except ValidationError:
        return None


def _result(value: ResearchRunList | ResearchRunView | ResearchReportView) -> CallToolResult:
    payload = value.model_dump(mode="json")
    text = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    if len(text.encode("utf-8")) > _MAX_RESULT_BYTES:
        return _failure("result_too_large")
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )


def create_mcp_server(application: ResearchApplicationPort | None = None) -> Server[None]:
    """Create a discoverable MCP server; unconfigured calls fail explicitly."""

    async def list_tools(
        _context: ServerRequestContext[None], _params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=_TOOLS)

    async def call_tool(
        _context: ServerRequestContext[None], params: CallToolRequestParams
    ) -> CallToolResult:
        name = params.name
        if name not in {tool.name for tool in _TOOLS}:
            return _failure("unknown_tool")
        args = _validated_args(params.arguments or {})
        if args is None:
            return _failure("invalid_arguments")
        run_id: str | None = None
        if name == "list_research_runs":
            if set(args) - {"limit", "offset"}:
                return _failure("invalid_arguments")
            limit, offset = args.get("limit", 20), args.get("offset", 0)
            if (
                type(limit) is not int
                or not 1 <= limit <= 50
                or type(offset) is not int
                or not 0 <= offset <= 100000
            ):
                return _failure("invalid_arguments")
        else:
            if set(args) != {"run_id"}:
                return _failure("invalid_arguments")
            run_id = _run_id(args["run_id"])
            if run_id is None:
                return _failure("invalid_arguments")
        if application is None:
            return _failure("unavailable")
        try:
            if name == "list_research_runs":
                raw_list = application.list_runs(limit=limit, offset=offset)
                return _result(
                    ResearchRunList.model_validate(raw_list.model_dump(mode="python"), strict=True)
                )
            assert run_id is not None
            if name == "get_research_run":
                raw_run = application.get_run(run_id)
                return _result(
                    ResearchRunView.model_validate(raw_run.model_dump(mode="python"), strict=True)
                )
            raw_report = application.get_report(run_id)
            return _result(
                ResearchReportView.model_validate(
                    {
                        "run": raw_report.run.model_dump(mode="python"),
                        "document": raw_report.document,
                    },
                    strict=True,
                )
            )
        except ResearchApplicationFailure as error:
            return _failure(error.code.value)

    return Server(
        "MedEvidence Research",
        version="1.0.0",
        description="Read-only access to existing local research runs and report drafts.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
