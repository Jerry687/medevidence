"""Streamlit UI flows against test-only loopback API responses."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest
from tests.contract.mcp_server.test_stdio_readonly import _ready_report

from medevidence.tools.research_application import ResearchRunStatus, ResearchSubmission

APP = Path(__file__).resolve().parents[3] / "frontend" / "app.py"
RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
REPORT_ID = "report:sha256:" + "b" * 64


class FakeApi:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.submissions: list[ResearchSubmission] = []
        self.reviews: list[dict[str, object]] = []
        self.run, self.report = _ready_report()
        self.mode = "empty"
        self.export_bytes = b'{"approved":true}\n'
        self.bad_hash = False
        self.report_override: dict[str, object] | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if self.mode == "unavailable":
            return httpx.Response(503, json={"error": {"code": "unavailable"}})
        if request.method == "POST" and path == "/v1/research/runs":
            submission = ResearchSubmission.model_validate_json(request.content, strict=True)
            self.submissions.append(submission)
            body = {
                "schema_version": "m3.research-run-view.v1",
                "run_id": RUN_ID,
                "report_id": REPORT_ID,
                "scope_id": submission.scope.scope_id,
                "checkpoint_id": "checkpoint:test",
                "status": "active",
                "destination_id": "destination:test",
                "warning_codes": [],
            }
            return httpx.Response(202, json=body)
        if request.method == "GET" and path == "/v1/research/runs":
            items = [] if self.mode == "empty" else [self.run.model_dump(mode="json")]
            return httpx.Response(
                200, json={"schema_version": "m3.research-run-list.v1", "items": items}
            )
        if request.method == "GET" and path == f"/v1/research/runs/{RUN_ID}":
            return httpx.Response(200, json=self.run.model_dump(mode="json"))
        if request.method == "GET" and path == f"/v1/research/runs/{RUN_ID}/report":
            if self.mode == "missing_report":
                return httpx.Response(409, json={"error": {"code": "conflict"}})
            return httpx.Response(
                200,
                json=self.report_override or self.report.model_dump(mode="json"),
            )
        if request.method == "POST" and path == f"/v1/research/runs/{RUN_ID}/review":
            command = json.loads(request.content)
            self.reviews.append(command)
            body = self.run.model_dump(mode="json") | {"status": "approved"}
            return httpx.Response(200, json=body)
        if request.method == "GET" and path == f"/v1/research/runs/{RUN_ID}/export":
            return httpx.Response(
                200,
                content=self.export_bytes,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Content-SHA256": (
                        "sha256:" + "0" * 64
                        if self.bad_hash
                        else "sha256:" + hashlib.sha256(self.export_bytes).hexdigest()
                    ),
                },
            )
        return httpx.Response(404, json={"error": {"code": "not_found"}})


def _app(monkeypatch, fake: FakeApi) -> AppTest:
    actual_client = httpx.Client

    def mocked_client(*args, **kwargs):
        assert kwargs.get("trust_env") is False
        assert kwargs.get("follow_redirects") is False
        kwargs["transport"] = httpx.MockTransport(fake.handle)
        return actual_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mocked_client)
    return AppTest.from_file(APP).run()


def _text(at: AppTest) -> str:
    return "\n".join(
        str(item.value)
        for item in [
            *at.title,
            *at.subheader,
            *at.text,
            *at.info,
            *at.warning,
            *at.error,
            *at.success,
        ]
    )


def test_initial_form_and_unavailable_state(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "unavailable"
    at = _app(monkeypatch, fake)
    assert not at.exception
    assert "MedEvidence" in _text(at)
    assert "Research assistance only" in _text(at)
    assert at.text_area(key="drugs").value == "Semaglutide\nTirzepatide"
    assert at.text_area(key="reactions").value == "Nausea\nVomiting\nDiarrhoea"
    assert "unavailable" in _text(at).lower()
    assert fake.submissions == []


def test_non_loopback_base_rejected_before_http(monkeypatch) -> None:
    fake = FakeApi()
    monkeypatch.setenv("MEDEVIDENCE_API_BASE", "http://example.com:8000")
    at = _app(monkeypatch, fake)
    assert not at.exception
    assert "loopback HTTP address" in _text(at)
    assert fake.requests == []


def test_submission_uses_exact_backend_scope_and_reuses_key_after_timeout(monkeypatch) -> None:
    fake = FakeApi()
    at = _app(monkeypatch, fake)
    at.button(key="submit_research").click().run()
    assert not at.exception
    assert len(fake.submissions) == 1
    first = fake.submissions[0]
    assert first.scope.scope_id.startswith("scope:sha256:")
    assert {item.preferred_term for item in first.scope.drugs} == {"Semaglutide", "Tirzepatide"}
    assert first.scope.selected_sources == tuple(sorted(first.scope.selected_sources, key=str))
    assert len(first.scope.adverse_reactions) == 3
    at.button(key="submit_research").click().run()
    assert fake.submissions[1].idempotency_key == first.idempotency_key
    at.text_area(key="drugs").set_value("Semaglutide").run()
    at.button(key="submit_research").click().run()
    assert fake.submissions[2].idempotency_key != first.idempotency_key


def test_pending_review_exact_binding_and_escaped_evidence(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "pending"
    document = fake.report.document
    claim = document.claims[0]
    fake.report = fake.report.model_copy(
        update={
            "document": replace(
                document,
                claims=(
                    replace(claim, statement="<script>alert(1)</script> [unsafe](javascript:1)"),
                ),
            ),
        }
    )
    # The mock bypasses server hash validation to exercise inert UI rendering.
    at = _app(monkeypatch, fake)
    assert not at.exception
    assert "Human export review" in _text(at)
    assert fake.run.report_id in _text(at)
    assert fake.run.render_document_hash in _text(at)
    assert "<script>alert(1)</script>" in _text(at)
    assert not at.get("html")
    at.button(key="approve_export").click().run()
    assert not fake.reviews
    assert "Confirm that you reviewed" in _text(at)
    at.checkbox(key="review_ack").check().run()
    at.button(key="approve_export").click().run()
    assert len(fake.reviews) == 1
    command = fake.reviews[0]
    assert command["decision"] == "approve"
    for field in (
        "run_id",
        "report_id",
        "report_content_hash",
        "render_document_hash",
        "pending_draft_id",
        "destination_id",
    ):
        assert command[field] == getattr(fake.run, field)


def test_reject_is_explicit_and_bound(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "pending"
    at = _app(monkeypatch, fake)
    at.button(key="reject_report").click().run()
    assert len(fake.reviews) == 1
    assert fake.reviews[0]["decision"] == "reject"
    assert fake.reviews[0]["render_document_hash"] == fake.run.render_document_hash


def test_coverage_distinguishes_complete_no_match_from_degraded_zero(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "pending"
    payload = fake.report.model_dump(mode="json")
    document = payload["document"]
    document["coverage"] = [
        {
            "source": "pubmed",
            "selected_for_execution": True,
            "query_id": "query:complete",
            "execution_status": "succeeded",
            "coverage_status": "complete",
            "result_status": "no_match",
            "valid_result_count": 0,
            "retrieval_as_of": None,
            "warning_codes": [],
        },
        {
            "source": "faers",
            "selected_for_execution": True,
            "query_id": "query:partial",
            "execution_status": "failed",
            "coverage_status": "partial",
            "result_status": "indeterminate",
            "valid_result_count": 0,
            "retrieval_as_of": None,
            "warning_codes": ["source_degraded"],
        },
    ]
    fake.report_override = payload
    at = _app(monkeypatch, fake)
    assert not at.exception
    visible = _text(at)
    assert "Complete bounded search: no match" in visible
    assert "zero retained results do not prove absence" in visible
    assert "source_degraded" in visible
    at.button(key="refresh_runs").click().run()
    assert fake.requests.count(("GET", "/v1/research/runs")) >= 2


def test_missing_report_is_not_presented_as_no_evidence(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "missing_report"
    at = _app(monkeypatch, fake)
    assert "Refresh it before trying again" in _text(at)
    assert "No formal claims were accepted" not in _text(at)


def test_export_only_after_state_and_hash_check(monkeypatch) -> None:
    fake = FakeApi()
    fake.mode = "exported"
    fake.run = fake.run.model_copy(update={"status": ResearchRunStatus.EXPORTED})
    fake.report = fake.report.model_copy(update={"run": fake.run})
    at = _app(monkeypatch, fake)
    assert not at.exception
    assert not at.get("download_button")
    at.button(key="prepare_download").click().run()
    assert at.get("download_button")
    fake.bad_hash = True
    at.button(key="prepare_download").click().run()
    assert not at.exception
    assert not at.get("download_button")
    assert "content or format check" in _text(at)
