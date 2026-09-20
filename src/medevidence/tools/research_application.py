"""Source-neutral application boundary for local V1 research review and export."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import ReportId, ResearchScope, RunId, ScopeId, Sha256Digest
from medevidence.domain.identifiers import DurableModel

from .report_document import ReportDocumentV1, report_document_to_json

StableId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*:[A-Za-z0-9:_-]{1,160}$")]
LocalReviewerId = Annotated[
    str, StringConstraints(pattern=r"^local-reviewer:[a-z0-9][a-z0-9_-]{0,63}$")
]


class ResearchRunStatus(StrEnum):
    SUBMITTED = "submitted"
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class ResearchReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ResearchExportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"


class ResearchApplicationErrorCode(StrEnum):
    SCOPE_REJECTED = "scope_rejected"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


class ResearchApplicationFailure(Exception):
    """Redacted, fixed-category application failure for HTTP mapping."""

    def __init__(self, code: ResearchApplicationErrorCode) -> None:
        if type(code) is not ResearchApplicationErrorCode:
            raise TypeError("application failure code must be exact")
        self.code = code
        super().__init__(code.value)


class ResearchSubmission(DurableModel):
    schema_version: Literal["m3.research-submission.v1"] = "m3.research-submission.v1"
    scope: ResearchScope
    idempotency_key: Sha256Digest


class ResearchRunView(DurableModel):
    schema_version: Literal["m3.research-run-view.v1"] = "m3.research-run-view.v1"
    run_id: RunId
    report_id: ReportId
    scope_id: ScopeId
    checkpoint_id: StableId
    status: ResearchRunStatus
    report_content_hash: Sha256Digest | None = None
    render_document_hash: Sha256Digest | None = None
    pending_draft_id: StableId | None = None
    destination_id: StableId
    warning_codes: tuple[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,127}$")], ...
    ] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_ready_bindings(self) -> Self:
        if self.status in {
            ResearchRunStatus.PENDING_REVIEW,
            ResearchRunStatus.APPROVED,
            ResearchRunStatus.REJECTED,
            ResearchRunStatus.EXPORTED,
        } and (
            self.report_content_hash is None
            or self.render_document_hash is None
            or self.pending_draft_id is None
        ):
            raise ValueError("review state lacks exact report, document or pending binding")
        if len(set(self.warning_codes)) != len(self.warning_codes):
            raise ValueError("warning codes must be unique")
        return self


class ResearchRunList(DurableModel):
    schema_version: Literal["m3.research-run-list.v1"] = "m3.research-run-list.v1"
    items: tuple[ResearchRunView, ...] = Field(max_length=50)
    next_offset: int | None = Field(default=None, ge=0, le=100_000)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> Self:
        if len({item.run_id for item in self.items}) != len(self.items):
            raise ValueError("run list contains duplicate identities")
        return self


class ResearchReportView(DurableModel):
    schema_version: Literal["m3.research-report-view.v1"] = "m3.research-report-view.v1"
    run: ResearchRunView
    document: ReportDocumentV1

    @model_validator(mode="after")
    def validate_document_binding(self) -> Self:
        if (
            self.document.run_id != self.run.run_id
            or self.document.report_id != self.run.report_id
            or self.document.scope_id != self.run.scope_id
            or self.document.report_content_hash != self.run.report_content_hash
            or self.document.render_document_hash != self.run.render_document_hash
        ):
            raise ValueError("report document differs from run binding")
        report_document_to_json(self.document)
        return self


class ResearchReviewCommand(DurableModel):
    schema_version: Literal["m3.research-review-command.v1"] = "m3.research-review-command.v1"
    run_id: RunId
    report_id: ReportId
    report_content_hash: Sha256Digest
    render_document_hash: Sha256Digest
    pending_draft_id: StableId
    destination_id: StableId
    reviewer_id: LocalReviewerId
    decision: ResearchReviewDecision
    idempotency_key: Sha256Digest


class ResearchExportArtifact(DurableModel):
    schema_version: Literal["m3.research-export-artifact.v1"] = "m3.research-export-artifact.v1"
    run_id: RunId
    report_id: ReportId
    report_content_hash: Sha256Digest
    render_document_hash: Sha256Digest
    export_id: StableId
    approval_review_id: StableId
    format: ResearchExportFormat
    content: bytes = Field(min_length=1, max_length=2_097_152)
    content_hash: Sha256Digest

    @model_validator(mode="after")
    def validate_exact_content(self) -> Self:
        if self.content_hash != "sha256:" + sha256(self.content).hexdigest():
            raise ValueError("export bytes differ from content hash")
        self.content.decode("utf-8")
        return self


class ResearchApplicationPort(Protocol):
    """Only application operations exposed to API, UI and read-only MCP adapters."""

    def submit(self, request: ResearchSubmission) -> ResearchRunView: ...

    def list_runs(self, *, limit: int, offset: int) -> ResearchRunList: ...

    def get_run(self, run_id: str) -> ResearchRunView: ...

    def get_report(self, run_id: str) -> ResearchReportView: ...

    def review(self, command: ResearchReviewCommand) -> ResearchRunView: ...

    def download_export(
        self, run_id: str, format: ResearchExportFormat
    ) -> ResearchExportArtifact: ...
