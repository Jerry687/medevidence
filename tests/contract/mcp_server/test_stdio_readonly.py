"""Real MCP protocol checks for the bounded read-only adapter."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime

import pytest_socket
from mcp import Client, StdioServerParameters
from tests.unit.tools import test_report_validation as fixtures
from tests.unit.tools.test_report_document import FakeProvenanceStore, FakeReceiptStore

from medevidence.mcp_server import create_mcp_server
from medevidence.tools.report_document import EvidenceProvenanceV1, build_report_document
from medevidence.tools.report_validation import (
    StoredValidationInput,
    ValidationMode,
    canonical_validate_report,
    canonical_validation_receipt_payload,
)
from medevidence.tools.research_application import (
    ResearchApplicationErrorCode,
    ResearchApplicationFailure,
    ResearchReportView,
    ResearchRunList,
    ResearchRunStatus,
    ResearchRunView,
)


def _run_with_disabled_network[T](coroutine: Coroutine[object, object, T]) -> T:
    """Windows asyncio needs a local self-pipe socket only while creating its loop."""

    pytest_socket.enable_socket()
    try:
        loop = asyncio.new_event_loop()
    finally:
        pytest_socket.disable_socket()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


def _ready_report() -> tuple[ResearchRunView, ResearchReportView]:
    request = fixtures._material_request()
    audit = canonical_validate_report(
        request, mode=ValidationMode.ASSESS, semantic_result_provider=fixtures.Provider()
    )
    assert audit.summary.passed and audit.receipt is not None
    stored = replace(request, stored_validation=StoredValidationInput(True, True, True, ()))
    evidence = stored.registry.evidence[0]
    provenance = EvidenceProvenanceV1(
        evidence.evidence_id,
        evidence.source,
        evidence.source_record_id,
        evidence.source_version,
        evidence.snapshot_id,
        evidence.content_hash,
        "https://example.org/public-record",
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
        ("verified snapshot",),
    )
    receipt_payload = canonical_validation_receipt_payload(audit.receipt)
    document = build_report_document(
        stored,
        receipt_payload,
        source_provenance=(provenance,),
        generated_at=datetime(2026, 2, 1, tzinfo=UTC),
        receipt_store=FakeReceiptStore(receipt_payload),
        provenance_store=FakeProvenanceStore(stored.run_id, (provenance,)),
    )
    run = ResearchRunView(
        run_id=request.run_id,
        report_id=request.report_id,
        scope_id=request.scope.scope_id,
        checkpoint_id="checkpoint:local-test",
        status=ResearchRunStatus.PENDING_REVIEW,
        report_content_hash=document.report_content_hash,
        render_document_hash=document.render_document_hash,
        pending_draft_id="draft:local-test",
        destination_id="destination:local-test",
    )
    return run, ResearchReportView(run=run, document=document)


class ReadOnlyApplication:
    def __init__(self) -> None:
        self.run, self.report = _ready_report()
        self.calls: list[tuple[object, ...]] = []

    def list_runs(self, *, limit: int, offset: int) -> ResearchRunList:
        self.calls.append(("list", limit, offset))
        return ResearchRunList(items=(self.run,), next_offset=None)

    def get_run(self, run_id: str) -> ResearchRunView:
        self.calls.append(("get_run", run_id))
        return self.run

    def get_report(self, run_id: str) -> ResearchReportView:
        self.calls.append(("get_report", run_id))
        return self.report

    def submit(self, _request: object) -> None:
        raise AssertionError("MCP must not submit")

    def review(self, _command: object) -> None:
        raise AssertionError("MCP must not review")

    def download_export(self, _run_id: str, _format: object) -> None:
        raise AssertionError("MCP must not export")


def test_in_process_initialize_discovery_and_read_calls() -> None:
    async def exercise() -> None:
        app = ReadOnlyApplication()
        async with Client(create_mcp_server(app)) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                "list_research_runs",
                "get_research_run",
                "get_research_report",
            ]
            for tool in listed.tools:
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.destructive_hint is False
            listed_result = await client.call_tool("list_research_runs", {"limit": 1, "offset": 0})
            assert listed_result.is_error is False
            assert listed_result.structured_content["items"][0]["run_id"] == app.run.run_id
            run_result = await client.call_tool("get_research_run", {"run_id": app.run.run_id})
            assert run_result.is_error is False
            assert run_result.structured_content["status"] == "pending_review"
            report_result = await client.call_tool(
                "get_research_report", {"run_id": app.run.run_id}
            )
            assert report_result.is_error is False
            assert (
                report_result.structured_content["document"]["render_document_hash"]
                == app.report.document.render_document_hash
            )
        assert app.calls == [
            ("list", 1, 0),
            ("get_run", app.run.run_id),
            ("get_report", app.run.run_id),
        ]

    _run_with_disabled_network(exercise())


def test_invalid_arguments_and_unknown_tool_never_enter_application() -> None:
    async def exercise() -> None:
        app = ReadOnlyApplication()
        async with Client(create_mcp_server(app)) as client:
            invalid = (
                ("get_research_run", {"run_id": "../../etc/passwd"}),
                ("get_research_run", {"run_id": app.run.run_id, "path": "x"}),
                ("list_research_runs", {"limit": True}),
                ("list_research_runs", {"limit": 51}),
                ("list_research_runs", {"offset": -1}),
                ("get_research_run", {"run_id": "x" * 4096}),
            )
            for name, args in invalid:
                result = await client.call_tool(name, args)
                assert result.is_error is True
                assert json.loads(result.content[0].text) == {"error": "invalid_arguments"}
            unknown = await client.call_tool("review_research_run", {"run_id": app.run.run_id})
            assert unknown.is_error is True
            assert json.loads(unknown.content[0].text) == {"error": "unknown_tool"}
        assert app.calls == []

    _run_with_disabled_network(exercise())


def test_unconfigured_stdio_initialize_and_discovery() -> None:
    async def exercise() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "medevidence.mcp_server"],
        )
        async with Client(params) as client:
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == [
                "list_research_runs",
                "get_research_run",
                "get_research_report",
            ]
            result = await client.call_tool("list_research_runs", {})
            assert result.is_error is True
            assert json.loads(result.content[0].text) == {"error": "unavailable"}

    _run_with_disabled_network(exercise())


def test_application_unavailable_is_redacted() -> None:
    class Unavailable(ReadOnlyApplication):
        def get_run(self, run_id: str) -> ResearchRunView:
            raise ResearchApplicationFailure(ResearchApplicationErrorCode.UNAVAILABLE)

    async def exercise() -> None:
        app = Unavailable()
        async with Client(create_mcp_server(app)) as client:
            result = await client.call_tool("get_research_run", {"run_id": app.run.run_id})
            assert result.is_error is True
            assert json.loads(result.content[0].text) == {"error": "unavailable"}

    _run_with_disabled_network(exercise())
