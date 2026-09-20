"""Closed application DTO tests without a production runtime or network."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.unit.tools.test_report_document import (
    GENERATED,
    FakeProvenanceStore,
    FakeReceiptStore,
    _passed,
    _provenance,
)

from medevidence.tools.report_document import build_report_document
from medevidence.tools.research_application import (
    ResearchExportArtifact,
    ResearchExportFormat,
    ResearchReportView,
    ResearchReviewCommand,
    ResearchReviewDecision,
    ResearchRunStatus,
    ResearchRunView,
)


def _document_view() -> ResearchReportView:
    request, receipt = _passed()
    provenance = _provenance(request)
    document = build_report_document(
        request,
        receipt,
        source_provenance=provenance,
        generated_at=GENERATED,
        receipt_store=FakeReceiptStore(receipt),
        provenance_store=FakeProvenanceStore(request.run_id, provenance),
    )
    run = ResearchRunView(
        run_id=document.run_id,
        report_id=document.report_id,
        scope_id=document.scope_id,
        checkpoint_id="checkpoint:test",
        status=ResearchRunStatus.PENDING_REVIEW,
        report_content_hash=document.report_content_hash,
        render_document_hash=document.render_document_hash,
        pending_draft_id="pending:test",
        destination_id="destination:test",
    )
    return ResearchReportView(run=run, document=document)


def test_report_view_carries_exact_verified_document() -> None:
    view = _document_view()
    assert view.document.render_document_hash == view.run.render_document_hash
    assert view.document.evidence_provenance
    with pytest.raises(ValidationError):
        ResearchReportView(
            run=view.run,
            document=replace(view.document, render_document_hash="sha256:" + "0" * 64),
        )


def test_review_command_requires_exact_closed_identities_and_local_actor_label() -> None:
    view = _document_view()
    valid = ResearchReviewCommand(
        run_id=view.run.run_id,
        report_id=view.run.report_id,
        report_content_hash=view.document.report_content_hash,
        render_document_hash=view.document.render_document_hash,
        pending_draft_id="pending:test",
        destination_id="destination:test",
        reviewer_id="local-reviewer:researcher_1",
        decision=ResearchReviewDecision.APPROVE,
        idempotency_key="sha256:" + "a" * 64,
    )
    assert valid.reviewer_id.startswith("local-reviewer:")
    with pytest.raises(ValidationError):
        ResearchReviewCommand.model_validate(
            {**valid.model_dump(mode="python"), "patient_id": "untrusted"}, strict=True
        )
    with pytest.raises(ValidationError):
        ResearchReviewCommand.model_validate(
            {**valid.model_dump(mode="python"), "reviewer_id": "clinician:unverified"},
            strict=True,
        )


def test_export_artifact_binds_bytes_and_fixed_format() -> None:
    view = _document_view()
    content = b'{"verified":true}\n'
    artifact = ResearchExportArtifact(
        run_id=view.run.run_id,
        report_id=view.run.report_id,
        report_content_hash=view.document.report_content_hash,
        render_document_hash=view.document.render_document_hash,
        export_id="export:test",
        approval_review_id="review:test",
        format=ResearchExportFormat.JSON,
        content=content,
        content_hash="sha256:" + sha256(content).hexdigest(),
    )
    assert artifact.content == content
    with pytest.raises(ValidationError):
        ResearchExportArtifact.model_validate(
            {**artifact.model_dump(mode="python"), "content": b"tampered"}, strict=True
        )
