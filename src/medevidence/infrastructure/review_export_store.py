"""Durable, explicit human review and resumable local report export."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from medevidence.domain import canonical_json, derive_identity, sha256_digest
from medevidence.orchestration.contracts import (
    ExportDestinationRef,
    ExportRecord,
    PendingDraftRef,
    ReviewDecision,
    ReviewRecord,
    SourceTaskState,
    export_idempotency_key,
    pending_draft_identity,
)
from medevidence.persistence.repositories import (
    PersistenceIntegrityError,
    ReviewExportRepository,
)
from medevidence.tools.report_document import (
    EvidenceProvenanceV1,
    ReceiptReadPort,
    ReportDocumentV1,
    VerifiedProvenanceReadPort,
    build_report_document,
    report_document_to_json,
    report_document_to_markdown,
)
from medevidence.tools.report_validation import (
    CanonicalReportRequest,
    ValidationReceipt,
    ValidationReceiptV2,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
)

from .local_export_writer import LocalExportWriter
from .report_material_codec import (
    decode_provenance,
    decode_report_request,
    encode_provenance,
    encode_report_request,
)


class ReviewDecisionRequired(RuntimeError):
    """No explicit human decision has been stored for the exact pending draft."""


_MAX_DOWNLOAD_BYTES = 2_097_152
_MAX_DRAFT_BYTES = _MAX_DOWNLOAD_BYTES - 4_096


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    document_id: str
    report_id: str
    report_content_hash: str
    validation_receipt_id: str
    render_document_hash: str
    json_byte_hash: str
    markdown_byte_hash: str
    document: ReportDocumentV1


@dataclass(frozen=True, slots=True)
class _Material:
    prepared: PreparedDocument
    request: CanonicalReportRequest
    json_text: str
    markdown_text: str


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("report material timestamp must be exact UTC")
    return value.astimezone(UTC)


def _receipt_payload(
    value: Mapping[str, object] | ValidationReceipt | ValidationReceiptV2,
) -> dict[str, object]:
    if type(value) is dict:
        receipt = validation_receipt_from_payload(value)
    elif type(value) in (ValidationReceipt, ValidationReceiptV2):
        receipt = cast(ValidationReceipt | ValidationReceiptV2, value)
    else:
        raise ValueError("final validation receipt is invalid")
    return canonical_validation_receipt_payload(receipt)


def _document_id(
    report_id: str,
    report_hash: str,
    receipt_id: str,
    render_hash: str,
    json_hash: str,
    markdown_hash: str,
) -> str:
    return derive_identity(
        "report-document",
        {
            "report_id": report_id,
            "report_content_hash": report_hash,
            "validation_receipt_id": receipt_id,
            "render_document_hash": render_hash,
            "json_byte_hash": json_hash,
            "markdown_byte_hash": markdown_hash,
        },
    )


def _export_texts(
    material: _Material,
    approval: ReviewRecord,
    export_id: str,
) -> tuple[str, str]:
    """Preserve the immutable draft under explicit approval/export bindings."""

    approved_at = approval.decided_at_utc.astimezone(UTC).isoformat(timespec="microseconds")
    approved_at = approved_at.replace("+00:00", "Z")
    bindings = {
        "export_id": export_id,
        "document_id": material.prepared.document_id,
        "destination_id": approval.destination.destination_id,
        "approval_review_id": approval.review_id,
        "approval_decision": approval.decision.value,
        "reviewer_id": approval.reviewer_id,
        "approved_at_utc": approved_at,
    }
    json_text = (
        canonical_json(
            {
                "marker": "MEDEVIDENCE_APPROVED_EXPORT_V1",
                "approval_and_export": bindings,
                "immutable_draft": json.loads(material.json_text),
            }
        )
        + "\n"
    )
    markdown_text = (
        "# Approved research evidence export\n\n"
        f"Approval review: {approval.review_id}  \n"
        f"Decision: {approval.decision.value}  \n"
        f"Reviewer: {approval.reviewer_id}  \n"
        f"Approved at: {approved_at}  \n"
        f"Export ID: {export_id}  \n"
        f"Destination: {approval.destination.destination_id}  \n"
        f"Document ID: {material.prepared.document_id}\n\n" + material.markdown_text
    )
    if (
        len(json_text.encode("utf-8")) > _MAX_DOWNLOAD_BYTES
        or len(markdown_text.encode("utf-8")) > _MAX_DOWNLOAD_BYTES
    ):
        raise ValueError("approved export exceeds the API download bound")
    return json_text, markdown_text


class ReviewExportStore:
    """Implement pending, review, and export ports with verified document material."""

    def __init__(
        self,
        repository: ReviewExportRepository,
        *,
        receipt_store: ReceiptReadPort,
        provenance_store: VerifiedProvenanceReadPort,
        writer: LocalExportWriter | None = None,
    ) -> None:
        self._repository = repository
        self._receipt_store = receipt_store
        self._provenance_store = provenance_store
        self._writer = LocalExportWriter() if writer is None else writer

    def _load_receipt(self, receipt_id: str) -> dict[str, object]:
        raw = self._receipt_store.load_receipt(receipt_id)
        durable = self._repository.load_receipt(receipt_id)
        if raw is None or durable is None:
            raise PersistenceIntegrityError("bound final validation receipt is missing")
        try:
            payload = _receipt_payload(raw)
        except ValueError as error:
            raise PersistenceIntegrityError("bound final validation receipt is invalid") from error
        if payload != raw or payload != durable or payload["receipt_id"] != receipt_id:
            raise PersistenceIntegrityError("bound final validation receipt drift")
        return payload

    def _material_from_row(self, row: Mapping[str, object]) -> _Material:
        try:
            request_raw = row["request_payload"]
            provenance_raw = row["provenance_payload"]
            document_raw = row["document_payload"]
            if (
                type(request_raw) is not dict
                or type(provenance_raw) is not list
                or type(document_raw) is not dict
            ):
                raise ValueError("stored report material JSON types are invalid")
            request = decode_report_request(canonical_json(request_raw))
            provenance = decode_provenance(canonical_json(provenance_raw))
            receipt_id = cast(str, row["validation_receipt_id"])
            receipt = self._load_receipt(receipt_id)
            generated_at = _utc(cast(datetime, row["generated_at_utc"]))
            document = build_report_document(
                request,
                receipt,
                source_provenance=provenance,
                generated_at=generated_at,
                receipt_store=self._receipt_store,
                provenance_store=self._provenance_store,
            )
            json_text = report_document_to_json(document)
            markdown_text = report_document_to_markdown(document)
            if (
                len(json_text.encode("utf-8")) > _MAX_DRAFT_BYTES
                or len(markdown_text.encode("utf-8")) > _MAX_DRAFT_BYTES
            ):
                raise ValueError("draft report exceeds the export download bound")
            json_hash = sha256_digest(json_text.encode("utf-8"))
            markdown_hash = sha256_digest(markdown_text.encode("utf-8"))
            document_id = _document_id(
                request.report_id,
                request.synthesis.report_content_hash,
                receipt_id,
                document.render_document_hash,
                json_hash,
                markdown_hash,
            )
            expected = {
                "document_id": document_id,
                "report_id": request.report_id,
                "report_content_hash": request.synthesis.report_content_hash,
                "validation_receipt_id": receipt_id,
                "validation_receipt_hash": receipt["receipt_content_hash"],
                "render_document_hash": document.render_document_hash,
                "request_payload": json.loads(encode_report_request(request)),
                "provenance_payload": json.loads(encode_provenance(provenance)),
                "document_payload": json.loads(json_text),
                "json_byte_hash": json_hash,
                "markdown_byte_hash": markdown_hash,
                "generated_at_utc": generated_at,
            }
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored report document cannot be rebuilt") from error
        if any(row.get(name) != value for name, value in expected.items()):
            raise PersistenceIntegrityError("stored report document differs from rebuilt material")
        return _Material(
            PreparedDocument(
                document_id,
                request.report_id,
                request.synthesis.report_content_hash,
                receipt_id,
                document.render_document_hash,
                json_hash,
                markdown_hash,
                document,
            ),
            request,
            json_text,
            markdown_text,
        )

    def prepare_document(
        self,
        request: CanonicalReportRequest,
        stored_receipt: Mapping[str, object] | ValidationReceipt | ValidationReceiptV2,
        provenance: tuple[EvidenceProvenanceV1, ...],
        generated_at: datetime,
    ) -> PreparedDocument:
        """Persist exact rebuildable material after verifying a saved final receipt."""

        if type(request) is not CanonicalReportRequest:
            raise ValueError("report document request must be exact canonical type")
        receipt = _receipt_payload(stored_receipt)
        if self._load_receipt(cast(str, receipt["receipt_id"])) != receipt:
            raise PersistenceIntegrityError("supplied final receipt differs from durable receipt")
        generated = _utc(generated_at)
        document = build_report_document(
            request,
            receipt,
            source_provenance=provenance,
            generated_at=generated,
            receipt_store=self._receipt_store,
            provenance_store=self._provenance_store,
        )
        request_payload = json.loads(encode_report_request(request))
        provenance_payload = json.loads(encode_provenance(provenance))
        json_text = report_document_to_json(document)
        markdown_text = report_document_to_markdown(document)
        if (
            len(json_text.encode("utf-8")) > _MAX_DRAFT_BYTES
            or len(markdown_text.encode("utf-8")) > _MAX_DRAFT_BYTES
        ):
            raise ValueError("draft report exceeds the export download bound")
        json_hash = sha256_digest(json_text.encode("utf-8"))
        markdown_hash = sha256_digest(markdown_text.encode("utf-8"))
        document_id = _document_id(
            request.report_id,
            request.synthesis.report_content_hash,
            cast(str, receipt["receipt_id"]),
            document.render_document_hash,
            json_hash,
            markdown_hash,
        )
        row = self._repository.save_document(
            {
                "document_id": document_id,
                "report_id": request.report_id,
                "report_content_hash": request.synthesis.report_content_hash,
                "validation_receipt_id": receipt["receipt_id"],
                "validation_receipt_hash": receipt["receipt_content_hash"],
                "render_document_hash": document.render_document_hash,
                "request_payload": request_payload,
                "provenance_payload": provenance_payload,
                "document_payload": json.loads(json_text),
                "json_byte_hash": json_hash,
                "markdown_byte_hash": markdown_hash,
                "generated_at_utc": generated,
            }
        )
        material = self._material_from_row(row)
        if material.prepared.document_id != document_id:
            raise PersistenceIntegrityError("saved report document identity drift")
        return material.prepared

    def get_document(self, report_id: str, report_content_hash: str) -> PreparedDocument | None:
        row = self._repository.load_document(report_id, report_content_hash)
        return None if row is None else self._material_from_row(row).prepared

    def save_pending(
        self,
        *,
        pending_draft_persistence_id: str,
        report_id: str,
        report_content_hash: str,
    ) -> PendingDraftRef:
        expected = pending_draft_identity(report_id, report_content_hash)
        if pending_draft_persistence_id != expected:
            raise ValueError("pending draft identity differs from report binding")
        pending = PendingDraftRef(
            persistence_id=expected,
            report_id=report_id,
            report_content_hash=report_content_hash,
        )
        row = self._repository.save_pending_draft(
            {
                "persistence_id": expected,
                "report_id": report_id,
                "report_content_hash": report_content_hash,
            }
        )
        if any(
            row.get(name) != value
            for name, value in (
                ("persistence_id", expected),
                ("report_id", report_id),
                ("report_content_hash", report_content_hash),
            )
        ):
            raise PersistenceIntegrityError("saved pending draft binding drift")
        return pending

    def load_pending(self, persistence_id: str) -> PendingDraftRef | None:
        row = self._repository.load_pending_draft(persistence_id)
        if row is None:
            return None
        try:
            pending = PendingDraftRef(
                persistence_id=cast(str, row["persistence_id"]),
                report_id=cast(str, row["report_id"]),
                report_content_hash=cast(str, row["report_content_hash"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored pending draft is invalid") from error
        if (
            pending.persistence_id != persistence_id
            or pending.persistence_id
            != pending_draft_identity(pending.report_id, pending.report_content_hash)
        ):
            raise PersistenceIntegrityError("stored pending draft identity drift")
        return pending

    def _bound_material(self, pending_id: str, report_id: str, report_hash: str) -> _Material:
        pending = self.load_pending(pending_id)
        if pending is None or (pending.report_id, pending.report_content_hash) != (
            report_id,
            report_hash,
        ):
            raise PersistenceIntegrityError("exact pending draft is unavailable")
        row = self._repository.load_document(report_id, report_hash)
        if row is None:
            raise PersistenceIntegrityError("validated report material is unavailable")
        return self._material_from_row(row)

    @staticmethod
    def _match_sources(
        material: _Material,
        review: ReviewRecord,
        source_tasks: tuple[SourceTaskState, ...] | None,
    ) -> None:
        request_tasks = material.request.tasks
        refs = review.source_outcome_refs
        if len(refs) != len(request_tasks):
            raise ValueError("review source outcome coverage differs from document")
        if source_tasks is not None:
            if type(source_tasks) is not tuple or len(source_tasks) != len(request_tasks):
                raise ValueError("review source tasks differ from document")
            expected = tuple(task.terminal_outcome_ref for task in source_tasks)
            if None in expected or refs != expected:
                raise ValueError("review source outcome references differ from terminal tasks")
        for task, ref in zip(request_tasks, refs, strict=True):
            outcome = ref.outcome
            acquisition = ref.acquisition
            if (
                not task.terminal
                or task.source != outcome.source
                or task.acquisition.run_id != acquisition.run_id
                or task.acquisition.source != acquisition.source
                or task.acquisition.source_outcome_id != ref.terminal_outcome_id
                or task.acquisition.acquisition_id != acquisition.acquisition_id
                or task.acquisition.acquisition_intent_id != acquisition.acquisition_intent_id
                or task.acquisition.acquisition_ordinal != acquisition.acquisition_ordinal
                or task.acquisition.operation != acquisition.operation
                or task.acquisition.snapshot_id != acquisition.snapshot_id
                or task.acquisition.query_id != outcome.query_id
                or task.outcome.source != outcome.source
                or task.outcome.query_id != outcome.query_id
                or task.outcome.execution_status != outcome.execution_status
                or task.outcome.coverage_status != outcome.coverage_status
                or task.outcome.result_status != outcome.result_status
                or task.outcome.configured_bounds.max_query_characters
                != outcome.configured_bounds.max_query_characters
                or task.outcome.configured_bounds.max_pages != outcome.configured_bounds.max_pages
                or task.outcome.configured_bounds.max_records
                != outcome.configured_bounds.max_records
                or task.outcome.configured_bounds.max_payload_bytes
                != outcome.configured_bounds.max_payload_bytes
                or task.outcome.configured_bounds.max_total_seconds
                != outcome.configured_bounds.max_total_seconds
                or task.outcome.valid_result_count != outcome.valid_result_count
                or task.outcome.pages_completed != outcome.pages_completed
                or task.outcome.truncated != outcome.truncated
                or task.outcome.warning_codes != outcome.warning_codes
                or task.outcome.failure_id != outcome.failure_id
            ):
                raise ValueError("review source outcome differs from validated document")

    def _review_from_row(self, row: Mapping[str, object], material: _Material) -> ReviewRecord:
        try:
            payload = row["review_payload"]
            if type(payload) is not dict:
                raise ValueError("review payload must be an object")
            review = ReviewRecord.model_validate_json(canonical_json(payload))
            if payload != review.model_dump(mode="json"):
                raise ValueError("review payload is noncanonical")
            expected = {
                "review_id": review.review_id,
                "pending_draft_persistence_id": review.pending_draft_persistence_id,
                "document_id": material.prepared.document_id,
                "destination_id": review.destination.destination_id,
                "decision": review.decision.value,
                "review_payload": payload,
            }
            if any(row.get(name) != value for name, value in expected.items()):
                raise ValueError("review projections differ from payload")
            if (
                review.report_id != material.prepared.report_id
                or review.report_content_hash != material.prepared.report_content_hash
                or not review.reviewer_id.startswith("local-reviewer:")
                or review.warning_codes != material.request.synthesis.warning_codes
            ):
                raise ValueError("review does not bind the document")
            self._match_sources(material, review, None)
        except (KeyError, TypeError, ValueError) as error:
            raise PersistenceIntegrityError("stored review decision is invalid") from error
        return review

    def submit_review(
        self,
        review: ReviewRecord,
        *,
        source_tasks: tuple[SourceTaskState, ...],
    ) -> ReviewRecord:
        """Store only an explicit local human decision with exact document bindings."""

        if type(review) is not ReviewRecord:
            raise ValueError("review decision must use exact typed record")
        review = ReviewRecord.model_validate(review.model_dump(mode="python"))
        material = self._bound_material(
            review.pending_draft_persistence_id,
            review.report_id,
            review.report_content_hash,
        )
        if (
            not review.reviewer_id.startswith("local-reviewer:")
            or review.warning_codes != material.request.synthesis.warning_codes
        ):
            raise ValueError("reviewer or warnings differ from local document binding")
        self._match_sources(material, review, source_tasks)
        payload = review.model_dump(mode="json")
        row = self._repository.save_review(
            {
                "review_id": review.review_id,
                "pending_draft_persistence_id": review.pending_draft_persistence_id,
                "document_id": material.prepared.document_id,
                "destination_id": review.destination.destination_id,
                "decision": review.decision.value,
                "review_payload": payload,
            }
        )
        loaded = self._review_from_row(row, material)
        if loaded != review:
            raise PersistenceIntegrityError("saved review differs from explicit decision")
        return loaded

    def request_approval(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        pending_draft_persistence_id: str,
        destination: ExportDestinationRef,
        source_tasks: tuple[SourceTaskState, ...],
        warning_codes: tuple[str, ...],
    ) -> ReviewRecord:
        material = self._bound_material(
            pending_draft_persistence_id, report_id, report_content_hash
        )
        if warning_codes != material.request.synthesis.warning_codes:
            raise ValueError("review warning codes differ from validated report")
        row = self._repository.load_review(pending_draft_persistence_id, destination.destination_id)
        if row is None:
            raise ReviewDecisionRequired("explicit local review decision is required")
        review = self._review_from_row(row, material)
        if review.destination != destination:
            raise PersistenceIntegrityError("review destination differs from request")
        self._match_sources(material, review, source_tasks)
        return review

    def get_review(
        self,
        *,
        pending_draft_persistence_id: str,
        report_id: str,
        report_content_hash: str,
        destination: ExportDestinationRef,
    ) -> ReviewRecord | None:
        """Read one explicit decision without interrupting or writing."""

        material = self._bound_material(
            pending_draft_persistence_id, report_id, report_content_hash
        )
        row = self._repository.load_review(pending_draft_persistence_id, destination.destination_id)
        return None if row is None else self._review_from_row(row, material)

    def finalize(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        destination: ExportDestinationRef,
        idempotency_key: str,
        approval: ReviewRecord,
    ) -> ExportRecord:
        """Resume or commit the one approved JSON/Markdown export."""

        if type(approval) is not ReviewRecord or approval.decision is not ReviewDecision.APPROVE:
            raise ValueError("formal export requires an explicit approve decision")
        if idempotency_key != export_idempotency_key(report_id, report_content_hash, destination):
            raise ValueError("export idempotency key differs from report binding")
        material = self._bound_material(
            approval.pending_draft_persistence_id, report_id, report_content_hash
        )
        row = self._repository.load_review(
            approval.pending_draft_persistence_id, destination.destination_id
        )
        if row is None or self._review_from_row(row, material) != approval:
            raise PersistenceIntegrityError("exact approved review is unavailable")
        names = self._writer.filenames(idempotency_key)
        export_id = derive_identity(
            "export",
            {
                "idempotency_key": idempotency_key,
                "review_id": approval.review_id,
                "document_id": material.prepared.document_id,
            },
        )
        export_json, export_markdown = _export_texts(material, approval, export_id)
        export_json_hash = sha256_digest(export_json.encode("utf-8"))
        export_markdown_hash = sha256_digest(export_markdown.encode("utf-8"))
        immutable = {
            "export_id": export_id,
            "idempotency_key": idempotency_key,
            "review_id": approval.review_id,
            "document_id": material.prepared.document_id,
            "report_id": report_id,
            "report_content_hash": report_content_hash,
            "destination_id": destination.destination_id,
            "json_filename": names[0],
            "markdown_filename": names[1],
            "json_byte_hash": export_json_hash,
            "markdown_byte_hash": export_markdown_hash,
        }
        prepared = self._repository.prepare_export(immutable)
        if any(prepared.get(name) != value for name, value in immutable.items()):
            raise PersistenceIntegrityError("prepared export differs from approved material")
        self._writer.write(
            idempotency_key,
            export_json,
            export_markdown,
            export_json_hash,
            export_markdown_hash,
        )
        committed = self._repository.commit_export(idempotency_key, immutable)
        self._writer.verify(
            idempotency_key,
            export_json_hash,
            export_markdown_hash,
        )
        exported_at = _utc(cast(datetime, committed["exported_at_utc"]))
        if committed["status"] != "committed":
            raise PersistenceIntegrityError("export did not reach committed status")
        return ExportRecord(
            export_id=export_id,
            report_id=report_id,
            report_content_hash=report_content_hash,
            destination=destination,
            idempotency_key=idempotency_key,
            approval_review_id=approval.review_id,
            exported_at_utc=exported_at,
        )

    def read_export(
        self,
        *,
        report_id: str,
        report_content_hash: str,
        destination: ExportDestinationRef,
        idempotency_key: str,
        approval: ReviewRecord,
        format: str,
    ) -> tuple[ExportRecord, bytes]:
        """Read a committed approved artifact without creating or repairing files."""

        if format not in ("json", "markdown"):
            raise ValueError("export download format is invalid")
        if type(approval) is not ReviewRecord or approval.decision is not ReviewDecision.APPROVE:
            raise ValueError("committed export requires exact approved review")
        if idempotency_key != export_idempotency_key(report_id, report_content_hash, destination):
            raise ValueError("export download key differs from report binding")
        material = self._bound_material(
            approval.pending_draft_persistence_id, report_id, report_content_hash
        )
        review_row = self._repository.load_review(
            approval.pending_draft_persistence_id, destination.destination_id
        )
        if review_row is None or self._review_from_row(review_row, material) != approval:
            raise PersistenceIntegrityError("committed approval is unavailable")
        export_id = derive_identity(
            "export",
            {
                "idempotency_key": idempotency_key,
                "review_id": approval.review_id,
                "document_id": material.prepared.document_id,
            },
        )
        export_json, export_markdown = _export_texts(material, approval, export_id)
        hashes = (
            sha256_digest(export_json.encode("utf-8")),
            sha256_digest(export_markdown.encode("utf-8")),
        )
        names = self._writer.filenames(idempotency_key)
        row = self._repository.load_export(idempotency_key)
        if row is None:
            raise PersistenceIntegrityError("committed export record is missing")
        expected = {
            "export_id": export_id,
            "idempotency_key": idempotency_key,
            "review_id": approval.review_id,
            "document_id": material.prepared.document_id,
            "report_id": report_id,
            "report_content_hash": report_content_hash,
            "destination_id": destination.destination_id,
            "json_filename": names[0],
            "markdown_filename": names[1],
            "json_byte_hash": hashes[0],
            "markdown_byte_hash": hashes[1],
            "status": "committed",
        }
        if any(row.get(name) != value for name, value in expected.items()):
            raise PersistenceIntegrityError("committed export differs from approved material")
        exported_at = _utc(cast(datetime, row["exported_at_utc"]))
        content = self._writer.read_verified(
            idempotency_key,
            format,
            hashes[0] if format == "json" else hashes[1],
        )
        record = ExportRecord(
            export_id=export_id,
            report_id=report_id,
            report_content_hash=report_content_hash,
            destination=destination,
            idempotency_key=idempotency_key,
            approval_review_id=approval.review_id,
            exported_at_utc=exported_at,
        )
        return record, content
