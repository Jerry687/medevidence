"""Disposable PostgreSQL tests for explicit review and local report export."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from tests.unit.orchestration.test_workflow import Harness, _initial, _run_until_node
from tests.unit.tools import test_report_validation as validation_fixtures
from tests.unit.tools.test_report_document import _provenance

from medevidence.domain import SourceType
from medevidence.infrastructure.local_export_writer import (
    LocalExportIntegrityError,
    LocalExportWriter,
)
from medevidence.infrastructure.review_export_store import (
    ReviewDecisionRequired,
    ReviewExportStore,
    _export_texts,
)
from medevidence.infrastructure.v2_receipt_store import V2ReceiptStore
from medevidence.orchestration import ReviewDecision, ReviewRecord, WorkflowNode
from medevidence.orchestration.contracts import export_idempotency_key
from medevidence.persistence import (
    DATABASE_URL_ENV,
    PersistenceConflict,
    PersistenceIntegrityError,
    PersistenceSettings,
    models,
)
from medevidence.persistence.repositories import ReviewExportRepository
from medevidence.tools.report_document import (
    EvidenceProvenanceV1,
    report_document_to_json,
    report_document_to_markdown,
)
from medevidence.tools.report_validation import (
    CitationRelationship,
    SemanticSupport,
    StoredValidationInput,
    ValidationMode,
    canonical_validate_report,
    canonical_validation_receipt_payload,
)

GENERATED = datetime(2026, 2, 1, tzinfo=UTC)


class SyntheticVerifiedProvenance:
    """Synthetic test authority keyed by exact recorded source facts."""

    def __init__(self, rows: tuple[EvidenceProvenanceV1, ...]) -> None:
        self._rows = {row.evidence_id: row for row in rows}

    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None:
        row = self._rows.get(evidence_id)
        if row is None or (
            row.source,
            row.source_record_id,
            row.source_version,
            row.snapshot_id,
            row.content_hash,
        ) != (source, source_record_id, source_version, snapshot_id, content_hash):
            return None
        return row


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    instance = sa.create_engine(url, hide_parameters=True)
    yield instance
    instance.dispose()


@pytest.fixture(autouse=True)
def empty_review_store(engine: Engine) -> Iterator[None]:
    def clear() -> None:
        with engine.begin() as connection:
            for table in (
                models.m3_exports,
                models.m3_review_records,
                models.m3_report_documents,
                models.m3_pending_drafts,
                models.m3_validation_receipts,
            ):
                connection.execute(table.delete())

    clear()
    yield
    clear()


def _case(engine: Engine, root: Path) -> tuple[ReviewExportStore, object, object, object]:
    harness = Harness()
    state = _run_until_node(harness.workflow, _initial(), WorkflowNode.REQUEST_EXPORT_APPROVAL)
    request = harness.workflow._build_validation_request(state, include_stored=True)
    assert state.validation_receipt_ref is not None
    receipt = harness.receipts.load_receipt(state.validation_receipt_ref.receipt_id)
    assert receipt is not None
    repository = cast(
        ReviewExportRepository, ReviewExportRepository._from_engine_for_testing(engine)
    )
    repository.save_receipt(receipt)
    store = ReviewExportStore(
        repository,
        receipt_store=repository,
        provenance_store=SyntheticVerifiedProvenance(_provenance(request)),
        writer=LocalExportWriter._for_testing(root),
    )
    return store, state, request, receipt


def _approval(state: object, decision: ReviewDecision) -> ReviewRecord:
    assert hasattr(state, "pending_draft") and state.pending_draft is not None
    assert state.synthesis is not None
    return ReviewRecord(
        review_id="review:local-1",
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
        pending_draft_persistence_id=state.pending_draft.persistence_id,
        destination=state.destination,
        source_outcome_refs=tuple(task.terminal_outcome_ref for task in state.source_tasks),
        warning_codes=state.synthesis.warning_codes,
        decision=decision,
        reviewer_id="local-reviewer:offline-user",
        decided_at_utc=GENERATED,
    )


def test_explicit_approve_exports_exact_json_markdown_and_reopens(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, request, receipt = _case(engine, tmp_path)
    prepared = store.prepare_document(request, receipt, _provenance(request), GENERATED)
    assert prepared.document_id.startswith("report-document:sha256:")
    assert state.pending_draft is not None
    pending = store.save_pending(
        pending_draft_persistence_id=state.pending_draft.persistence_id,
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
    )
    assert store.load_pending(pending.persistence_id) == pending
    with pytest.raises(ReviewDecisionRequired):
        store.request_approval(
            report_id=state.report_id,
            report_content_hash=state.synthesis.report_content_hash,
            pending_draft_persistence_id=pending.persistence_id,
            destination=state.destination,
            source_tasks=state.source_tasks,
            warning_codes=state.synthesis.warning_codes,
        )
    approval = _approval(state, ReviewDecision.APPROVE)
    assert store.submit_review(approval, source_tasks=state.source_tasks) == approval
    assert (
        store.request_approval(
            report_id=state.report_id,
            report_content_hash=state.synthesis.report_content_hash,
            pending_draft_persistence_id=pending.persistence_id,
            destination=state.destination,
            source_tasks=state.source_tasks,
            warning_codes=state.synthesis.warning_codes,
        )
        == approval
    )
    key = export_idempotency_key(
        state.report_id, state.synthesis.report_content_hash, state.destination
    )
    record = store.finalize(
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
        destination=state.destination,
        idempotency_key=key,
        approval=approval,
    )
    names = LocalExportWriter.filenames(key)
    exported_json = (tmp_path / names[0]).read_text(encoding="utf-8")
    exported_markdown = (tmp_path / names[1]).read_text(encoding="utf-8")
    envelope = json.loads(exported_json)
    assert envelope["marker"] == "MEDEVIDENCE_APPROVED_EXPORT_V1"
    assert envelope["approval_and_export"]["approval_review_id"] == approval.review_id
    assert envelope["approval_and_export"]["export_id"] == record.export_id
    assert envelope["immutable_draft"] == json.loads(report_document_to_json(prepared.document))
    assert "# Approved research evidence export" in exported_markdown
    assert report_document_to_markdown(prepared.document) in exported_markdown
    assert store.read_export(
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
        destination=state.destination,
        idempotency_key=key,
        approval=approval,
        format="json",
    ) == (record, exported_json.encode("utf-8"))

    reopened_repository = ReviewExportRepository(PersistenceSettings.from_env())
    try:
        reopened = ReviewExportStore(
            reopened_repository,
            receipt_store=reopened_repository,
            provenance_store=store._provenance_store,
            writer=LocalExportWriter._for_testing(tmp_path),
        )
        assert (
            reopened.get_document(state.report_id, state.synthesis.report_content_hash) == prepared
        )
        assert (
            reopened.finalize(
                report_id=state.report_id,
                report_content_hash=state.synthesis.report_content_hash,
                destination=state.destination,
                idempotency_key=key,
                approval=approval,
            )
            == record
        )
    finally:
        reopened_repository.close()


@pytest.mark.parametrize("decision", (ReviewDecision.REJECT, ReviewDecision.EDIT))
def test_reject_and_edit_never_create_files(
    engine: Engine, tmp_path: Path, decision: ReviewDecision
) -> None:
    store, state, request, receipt = _case(engine, tmp_path)
    store.prepare_document(request, receipt, _provenance(request), GENERATED)
    assert state.pending_draft is not None
    store.save_pending(
        pending_draft_persistence_id=state.pending_draft.persistence_id,
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
    )
    review = _approval(state, decision)
    store.submit_review(review, source_tasks=state.source_tasks)
    key = export_idempotency_key(
        state.report_id, state.synthesis.report_content_hash, state.destination
    )
    with pytest.raises(ValueError, match="approve"):
        store.finalize(
            report_id=state.report_id,
            report_content_hash=state.synthesis.report_content_hash,
            destination=state.destination,
            idempotency_key=key,
            approval=review,
        )
    assert list(tmp_path.iterdir()) == []


def _approved_case(
    engine: Engine, root: Path
) -> tuple[ReviewExportStore, object, ReviewRecord, str]:
    store, state, request, receipt = _case(engine, root)
    store.prepare_document(request, receipt, _provenance(request), GENERATED)
    assert state.pending_draft is not None
    store.save_pending(
        pending_draft_persistence_id=state.pending_draft.persistence_id,
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
    )
    approval = _approval(state, ReviewDecision.APPROVE)
    store.submit_review(approval, source_tasks=state.source_tasks)
    key = export_idempotency_key(
        state.report_id, state.synthesis.report_content_hash, state.destination
    )
    return store, state, approval, key


def _finalize(store: ReviewExportStore, state: object, approval: ReviewRecord, key: str) -> object:
    return store.finalize(
        report_id=state.report_id,
        report_content_hash=state.synthesis.report_content_hash,
        destination=state.destination,
        idempotency_key=key,
        approval=approval,
    )


def test_duplicate_decision_conflicts_and_concurrent_export_converges(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, approval, key = _approved_case(engine, tmp_path)
    assert store.submit_review(approval, source_tasks=state.source_tasks) == approval
    opposite = approval.model_copy(
        update={"review_id": "review:local-2", "decision": ReviewDecision.REJECT}
    )
    with pytest.raises(PersistenceConflict):
        store.submit_review(opposite, source_tasks=state.source_tasks)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: _finalize(store, state, approval, key), range(2)))
    assert results[0] == results[1]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(models.m3_exports)) == 1


def test_prepared_export_resumes_after_failed_writer(engine: Engine, tmp_path: Path) -> None:
    store, state, approval, key = _approved_case(engine, tmp_path)

    class FailingWriter(LocalExportWriter):
        def write(self, *args: object) -> tuple[str, str]:
            raise RuntimeError("synthetic crash before file publication")

    failing = ReviewExportStore(
        store._repository,
        receipt_store=store._receipt_store,
        provenance_store=store._provenance_store,
        writer=FailingWriter._for_testing(tmp_path),
    )
    with pytest.raises(RuntimeError, match="synthetic crash"):
        _finalize(failing, state, approval, key)
    row = store._repository.load_export(key)
    assert row is not None and row["status"] == "prepared"
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(PersistenceIntegrityError, match="committed export differs"):
        store.read_export(
            report_id=state.report_id,
            report_content_hash=state.synthesis.report_content_hash,
            destination=state.destination,
            idempotency_key=key,
            approval=approval,
            format="json",
        )
    assert list(tmp_path.iterdir()) == []
    _finalize(store, state, approval, key)
    committed = store._repository.load_export(key)
    assert committed is not None and committed["status"] == "committed"


def test_prepared_partial_json_file_resumes_without_replacement(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, approval, key = _approved_case(engine, tmp_path)

    class FailingWriter(LocalExportWriter):
        def write(self, *args: object) -> tuple[str, str]:
            raise RuntimeError("synthetic stop after preparation")

    failing = ReviewExportStore(
        store._repository,
        receipt_store=store._receipt_store,
        provenance_store=store._provenance_store,
        writer=FailingWriter._for_testing(tmp_path),
    )
    with pytest.raises(RuntimeError, match="synthetic stop"):
        _finalize(failing, state, approval, key)
    document_row = store._repository.load_document(
        state.report_id, state.synthesis.report_content_hash
    )
    assert document_row is not None
    material = store._material_from_row(document_row)
    json_name, markdown_name = LocalExportWriter.filenames(key)
    prepared_row = store._repository.load_export(key)
    assert prepared_row is not None
    json_text, _ = _export_texts(material, approval, prepared_row["export_id"])
    json_bytes = json_text.encode("utf-8")
    (tmp_path / json_name).write_bytes(json_bytes)
    _finalize(store, state, approval, key)
    assert (tmp_path / json_name).read_bytes() == json_bytes
    assert (tmp_path / markdown_name).is_file()


def test_foreign_file_blocks_prepared_export_without_replacement(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, approval, key = _approved_case(engine, tmp_path)
    json_name, markdown_name = LocalExportWriter.filenames(key)
    (tmp_path / json_name).write_bytes(b"foreign")
    with pytest.raises(LocalExportIntegrityError, match="bytes differ"):
        _finalize(store, state, approval, key)
    assert (tmp_path / json_name).read_bytes() == b"foreign"
    assert not (tmp_path / markdown_name).exists()
    row = store._repository.load_export(key)
    assert row is not None and row["status"] == "prepared"


def test_corrupted_document_or_foreign_receipt_fails_before_review(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, request, receipt = _case(engine, tmp_path)
    with pytest.raises(ValueError):
        store.prepare_document(
            request,
            {**receipt, "report_id": "report:foreign"},
            _provenance(request),
            GENERATED,
        )
    prepared = store.prepare_document(request, receipt, _provenance(request), GENERATED)
    with engine.begin() as connection:
        connection.execute(
            models.m3_report_documents.update()
            .where(models.m3_report_documents.c.document_id == prepared.document_id)
            .values(document_payload={"marker": "tampered"})
        )
    with pytest.raises(PersistenceIntegrityError, match="differs from rebuilt"):
        store.get_document(state.report_id, state.synthesis.report_content_hash)


def test_forged_provenance_is_rejected_before_material_persistence(
    engine: Engine, tmp_path: Path
) -> None:
    store, state, request, receipt = _case(engine, tmp_path)
    original = _provenance(request)
    forged = (
        replace(
            original[0],
            source_url="https://attacker.example/forged",
            transformation_lineage=("forged",),
        ),
    )
    with pytest.raises(ValueError):
        store.prepare_document(request, receipt, forged, GENERATED)
    assert store.get_document(state.report_id, state.synthesis.report_content_hash) is None


def test_reopen_rechecks_verified_provenance_reader(engine: Engine, tmp_path: Path) -> None:
    store, state, request, receipt = _case(engine, tmp_path)
    store.prepare_document(request, receipt, _provenance(request), GENERATED)
    reader = cast(SyntheticVerifiedProvenance, store._provenance_store)
    row = _provenance(request)[0]
    reader._rows[row.evidence_id] = replace(row, source_url="https://attacker.example/changed")
    with pytest.raises(PersistenceIntegrityError, match="cannot be rebuilt"):
        store.get_document(state.report_id, state.synthesis.report_content_hash)


def test_v2_final_receipt_uses_real_readback_adapter(engine: Engine, tmp_path: Path) -> None:
    request, provider, _ = validation_fixtures._v2_request(
        (CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    audit = canonical_validate_report(
        request, mode=ValidationMode.ASSESS, semantic_result_provider=provider
    )
    assert audit.summary.passed and audit.receipt is not None
    stored = replace(request, stored_validation=StoredValidationInput(True, True, True, ()))
    receipt = canonical_validation_receipt_payload(audit.receipt)
    repository = cast(
        ReviewExportRepository, ReviewExportRepository._from_engine_for_testing(engine)
    )
    v2_receipts = V2ReceiptStore(repository)
    v2_receipts.save_receipt(receipt)
    store = ReviewExportStore(
        repository,
        receipt_store=v2_receipts,
        provenance_store=SyntheticVerifiedProvenance(_provenance(stored)),
        writer=LocalExportWriter._for_testing(tmp_path),
    )
    prepared = store.prepare_document(stored, receipt, _provenance(stored), GENERATED)
    assert store.get_document(stored.report_id, stored.synthesis.report_content_hash) == prepared
