"""Offline HTTP contract for the injected V1 research application boundary."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from tests.unit.tools.test_research_application import _document_view

from medevidence.api import ApiDependencies, create_app
from medevidence.domain import (
    AdverseEventConcept,
    ComparisonIntent,
    DrugConcept,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)
from medevidence.tools.research_application import (
    ResearchApplicationErrorCode,
    ResearchApplicationFailure,
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

pytestmark = pytest.mark.enable_socket


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="rxnorm:1", preferred_term="Test drug"),),
        adverse_reactions=(
            AdverseEventConcept(concept_id="meddra:1", preferred_term="Test event"),
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=128, max_pages=2, max_total_seconds=30),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=100_000),
    )


class FakeResearchApplication:
    def __init__(self) -> None:
        self.report = _document_view()
        self.calls: list[str] = []
        self.failure: ResearchApplicationErrorCode | None = None
        self.export_override: ResearchExportArtifact | None = None

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self.failure is not None:
            raise ResearchApplicationFailure(self.failure)

    def submit(self, request: ResearchSubmission) -> ResearchRunView:
        self._record("submit")
        assert request.scope.scope_id == self.report.run.scope_id
        return self.report.run

    def list_runs(self, *, limit: int, offset: int) -> ResearchRunList:
        self._record("list")
        assert 1 <= limit <= 50 and 0 <= offset <= 100_000
        return ResearchRunList(items=(self.report.run,))

    def get_run(self, run_id: str) -> ResearchRunView:
        self._record("get")
        assert run_id == self.report.run.run_id
        return self.report.run

    def get_report(self, run_id: str) -> ResearchReportView:
        self._record("report")
        assert run_id == self.report.run.run_id
        return self.report

    def review(self, command: ResearchReviewCommand) -> ResearchRunView:
        self._record("review")
        assert command.report_id == self.report.run.report_id
        return self.report.run.model_copy(update={"status": ResearchRunStatus.APPROVED})

    def download_export(self, run_id: str, format: ResearchExportFormat) -> ResearchExportArtifact:
        self._record("export")
        if self.export_override is not None:
            return self.export_override
        content = b'{"exported":true}\n'
        return ResearchExportArtifact(
            run_id=run_id,
            report_id=self.report.run.report_id,
            report_content_hash=self.report.document.report_content_hash,
            render_document_hash=self.report.document.render_document_hash,
            export_id="export:test",
            approval_review_id="review:test",
            format=format,
            content=content,
            content_hash="sha256:" + sha256(content).hexdigest(),
        )


def _client(application: FakeResearchApplication | None) -> TestClient:
    dependencies = ApiDependencies(
        application=lambda _: (_ for _ in ()).throw(AssertionError("M1A route called")),
        request_id_factory=lambda: "request:00000000-0000-4000-8000-000000000001",
        run_id_factory=lambda: "run:00000000-0000-4000-8000-000000000002",
        utc_now=lambda: __import__("datetime").datetime.now(__import__("datetime").UTC),
        code_revision="0" * 40,
    )
    return TestClient(create_app(dependencies, research_application=application))


def test_unconfigured_routes_are_503_and_creation_discovery_do_not_call_port() -> None:
    client = _client(None)
    assert client.post("/v1/research/runs", json={}).status_code == 503
    assert client.get("/v1/research/runs").status_code == 503
    assert client.get("/v1/research/runs/invalid/report").status_code == 503
    assert client.get("/v1/research/runs/invalid/export?format=json").status_code == 503
    assert client.get("/openapi.json").status_code == 200
    fake = FakeResearchApplication()
    configured = _client(fake)
    configured.get("/openapi.json")
    assert fake.calls == []


def test_submit_list_report_review_and_download_are_bound_to_port() -> None:
    fake = FakeResearchApplication()
    client = _client(fake)
    submission = ResearchSubmission(scope=_scope(), idempotency_key="sha256:" + "a" * 64)
    submitted = client.post("/v1/research/runs", json=submission.model_dump(mode="json"))
    assert submitted.status_code == 202
    assert submitted.json()["scope_id"] == submission.scope.scope_id
    run_id = fake.report.run.run_id
    listed = client.get("/v1/research/runs?limit=1&offset=0")
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    assert client.get(f"/v1/research/runs/{run_id}").status_code == 200
    report = client.get(f"/v1/research/runs/{run_id}/report")
    assert report.status_code == 200
    assert (
        report.json()["document"]["render_document_hash"]
        == fake.report.document.render_document_hash
    )
    assert report.json()["document"]["evidence_provenance"]
    review = ResearchReviewCommand(
        run_id=run_id,
        report_id=fake.report.run.report_id,
        report_content_hash=fake.report.document.report_content_hash,
        render_document_hash=fake.report.document.render_document_hash,
        pending_draft_id="pending:test",
        destination_id="destination:test",
        reviewer_id="local-reviewer:researcher_1",
        decision=ResearchReviewDecision.APPROVE,
        idempotency_key="sha256:" + "b" * 64,
    )
    approved = client.post(
        f"/v1/research/runs/{run_id}/review", json=review.model_dump(mode="json")
    )
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    blocked_download = client.get(f"/v1/research/runs/{run_id}/export?format=json")
    assert blocked_download.status_code == 409
    fake.report = ResearchReportView(
        run=fake.report.run.model_copy(update={"status": ResearchRunStatus.EXPORTED}),
        document=fake.report.document,
    )
    exported = client.get(f"/v1/research/runs/{run_id}/export?format=json")
    assert exported.status_code == 200 and exported.content == b'{"exported":true}\n'
    assert exported.headers["content-disposition"].startswith('attachment; filename="medevidence-')
    assert fake.calls == ["submit", "list", "get", "report", "review", "get", "get", "export"]


def test_invalid_requests_never_reach_port_and_errors_are_fixed() -> None:
    fake = FakeResearchApplication()
    client = _client(fake)
    assert (
        client.post(
            "/v1/research/runs",
            content='{"scope":{},"scope":{}}',
            headers={"content-type": "application/json"},
        ).status_code
        == 422
    )
    assert client.post("/v1/research/runs", json={"patient_id": "x"}).status_code == 422
    assert (
        client.post(
            "/v1/research/runs", content=b"x" * 65_537, headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert client.get("/v1/research/runs?limit=51").status_code == 422
    assert client.get("/v1/research/runs?limit=1&limit=2").status_code == 422
    assert client.get("/v1/research/runs/invalid").status_code == 422
    assert client.get("/v1/research/runs/invalid/export?format=pdf").status_code == 422
    assert fake.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    (
        (ResearchApplicationErrorCode.NOT_FOUND, 404),
        (ResearchApplicationErrorCode.CONFLICT, 409),
        (ResearchApplicationErrorCode.UNAVAILABLE, 503),
    ),
)
def test_typed_application_failures_have_safe_http_status(
    code: ResearchApplicationErrorCode, status: int
) -> None:
    fake = FakeResearchApplication()
    fake.failure = code
    response = _client(fake).get(f"/v1/research/runs/{fake.report.run.run_id}")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code.value


def test_scope_safety_rejection_is_fixed_redacted_422() -> None:
    fake = FakeResearchApplication()
    fake.failure = ResearchApplicationErrorCode.SCOPE_REJECTED
    submission = ResearchSubmission(scope=_scope(), idempotency_key="sha256:" + "a" * 64)
    response = _client(fake).post("/v1/research/runs", json=submission.model_dump(mode="json"))
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "scope_rejected", "message": "The research scope was rejected."}
    }
    assert fake.calls == ["submit"]


@pytest.mark.parametrize(
    ("field", "foreign"),
    (
        ("run_id", "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("report_content_hash", "sha256:" + "0" * 64),
        ("render_document_hash", "sha256:" + "0" * 64),
    ),
)
def test_foreign_export_response_fails_closed_without_bytes(field: str, foreign: str) -> None:
    fake = FakeResearchApplication()
    client = _client(fake)
    run_id = fake.report.run.run_id
    fake.report = ResearchReportView(
        run=fake.report.run.model_copy(update={"status": ResearchRunStatus.EXPORTED}),
        document=fake.report.document,
    )
    fake.export_override = fake.download_export(run_id, ResearchExportFormat.JSON).model_copy(
        update={field: foreign}
    )
    fake.calls.clear()
    response = client.get(f"/v1/research/runs/{run_id}/export?format=json")
    assert response.status_code == 502
    assert response.content != b'{"exported":true}\n'
    assert fake.calls == ["get", "export"]


def test_tampered_report_document_is_not_returned() -> None:
    fake = FakeResearchApplication()
    fake.report = ResearchReportView.model_construct(
        run=fake.report.run,
        document=replace(fake.report.document, render_document_hash="sha256:" + "0" * 64),
    )
    response = _client(fake).get(f"/v1/research/runs/{fake.report.run.run_id}/report")
    assert response.status_code == 502
    assert "evidence_provenance" not in response.text


def test_review_path_mismatch_is_conflict_before_application_call() -> None:
    fake = FakeResearchApplication()
    command = ResearchReviewCommand(
        run_id="run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        report_id=fake.report.run.report_id,
        report_content_hash=fake.report.document.report_content_hash,
        render_document_hash=fake.report.document.render_document_hash,
        pending_draft_id="pending:test",
        destination_id="destination:test",
        reviewer_id="local-reviewer:researcher_1",
        decision=ResearchReviewDecision.REJECT,
        idempotency_key="sha256:" + "c" * 64,
    )
    response = _client(fake).post(
        f"/v1/research/runs/{fake.report.run.run_id}/review",
        json=command.model_dump(mode="json"),
    )
    assert response.status_code == 409
    assert fake.calls == []


def test_unexpected_application_error_is_redacted() -> None:
    fake = FakeResearchApplication()

    def broken(_: str) -> ResearchRunView:
        raise RuntimeError("sensitive provider diagnostic")

    fake.get_run = broken  # type: ignore[method-assign]
    response = _client(fake).get(f"/v1/research/runs/{fake.report.run.run_id}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive provider diagnostic" not in response.text
