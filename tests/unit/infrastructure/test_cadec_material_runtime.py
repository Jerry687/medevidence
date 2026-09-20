"""Exact CADEC auxiliary material stays payload-free and replayable."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import medevidence.infrastructure.cadec_local_search as adapter_module
import medevidence.infrastructure.cadec_material_runtime as material_module
from medevidence.connectors.cadec.loader import (
    CadecLoadResult,
    CadecVerificationSummary,
    _CadecAdmittedDocumentText,
    _CadecTextLoadResult,
    _member_artifact_id,
)
from medevidence.domain import (
    AdverseEventConcept,
    CadecCorpusDocumentV1,
    CadecProvenanceContextV1,
    CadecReleaseManifestV1,
    CadecSplit,
    ComparisonIntent,
    DrugConcept,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
    canonical_json,
)
from medevidence.infrastructure.cadec_local_search import CanonicalCadecEvidenceCollection
from medevidence.infrastructure.cadec_material_runtime import (
    CadecMaterialError,
    CadecMaterialRuntime,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    SourceTaskState,
    source_task_attempt,
    source_task_id,
)
from medevidence.orchestration.source_capabilities import (
    SourceCapabilities,
    planned_running_source_task,
    terminal_source_task,
)
from medevidence.tools.cadec_runtime import _EXACT_CADEC_VERIFICATION
from medevidence.tools.report_validation import canonical_evidence_id

ARCHIVE = Path("C:/approved/CADEC.v2.zip")
MANIFEST = Path("C:/approved/manifest.json")
RUN_ID = "run:12345678-1234-4234-9234-123456789abc"
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="drug-a", preferred_term="match"),),
        adverse_reactions=(AdverseEventConcept(concept_id="event-a", preferred_term="Nausea"),),
        date_range=None,
        selected_sources=(SourceType.CADEC,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=1, max_total_seconds=30),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _document(document_id: str, text: str) -> _CadecAdmittedDocumentText:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    member_path = f"cadec/text/{document_id}.txt"
    artifact_id = _member_artifact_id(member_path, digest)
    provenance = CadecProvenanceContextV1.create(
        split=CadecSplit.TRAIN,
        artifact_id=artifact_id,
        artifact_sha256=f"sha256:{digest}",
        lineage_artifact_ids=(),
    )
    document = CadecCorpusDocumentV1.create(
        split=CadecSplit.TRAIN,
        artifact_id=artifact_id,
        artifact_sha256=f"sha256:{digest}",
        document_id=document_id,
        member_path=member_path,
        text_length=len(text),
        text_sha256=f"sha256:{digest}",
        provenance=provenance,
    )
    return _CadecAdmittedDocumentText(document=document, text=text)


def _install(
    monkeypatch: pytest.MonkeyPatch, admitted: tuple[_CadecAdmittedDocumentText, ...]
) -> None:
    documents = list(admitted)
    for index in range(2 - sum(not item.text for item in documents)):
        documents.append(_document(f"EMPTY.{index + 100}", ""))
    for index in range(1_248 - len(documents)):
        documents.append(_document(f"PAD.{index + 1}", "unrelated"))
    complete = tuple(documents)
    loaded = _CadecTextLoadResult(
        admitted=CadecLoadResult(
            release_manifest=CadecReleaseManifestV1.create(),
            documents=tuple(item.document for item in complete),
            annotations=(),
            locators=(),
            verification=CadecVerificationSummary(**dict(_EXACT_CADEC_VERIFICATION)),
        ),
        document_texts=complete,
    )
    monkeypatch.setattr(adapter_module, "_load_cadec_archive_with_text", lambda *_args: loaded)
    monkeypatch.setattr(
        adapter_module.CadecLocalSearchAdapter, "_verify_asset_identity", lambda _self: None
    )


def _runtime(tmp_path: Path, now: datetime = NOW) -> CadecMaterialRuntime:
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _path: 20_000_000_000)
    delegate = CanonicalCadecEvidenceCollection(
        archive_path=ARCHIVE,
        manifest_path=MANIFEST,
        delegate=object.__new__(SourceCapabilities),
    )
    return CadecMaterialRuntime(
        delegate=delegate,
        snapshots=snapshots,
        archive_path=ARCHIVE,
        manifest_path=MANIFEST,
        utc_now=lambda: now,
    )


def _collected(runtime: CadecMaterialRuntime) -> tuple[SourceTaskState, CollectedEvidenceResult]:
    scope = _scope()
    pending = SourceTaskState(
        task_id=source_task_id(RUN_ID, SourceType.CADEC), source=SourceType.CADEC
    )
    attempt = source_task_attempt(pending.task_id, 1)
    running = planned_running_source_task(runtime, pending, scope, attempt, RUN_ID)
    result = runtime.collect(running, scope, attempt)
    assert type(result) is CollectedEvidenceResult
    return running, result


def test_cadec_material_receipt_maps_canonical_ids_without_persisting_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, (_document("DOC.1", "match PRIVATE-FIXTURE-NEVER-PERSIST"),))
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    scope = _scope()
    terminal = terminal_source_task(running, result, RUN_ID)
    runtime.validate_terminal_task(terminal, scope)
    materials = runtime.read_material(RUN_ID, scope, terminal, terminal.operation_results[1])

    assert len(materials) == len(result.evidence_refs) == 1
    material = materials[0]
    assert material.evidence.evidence_id == canonical_evidence_id(material.evidence)
    assert material.evidence.evidence_id == result.evidence_refs[0].evidence_id
    assert material.evidence.permitted_claim_classes == frozenset()
    assert material.evidence.permitted_inference_uses == frozenset()
    assert material.evidence.numerical_facts == ()
    assert material.provenance.retrieved_at == NOW
    assert material.provenance.lookup_key == "cadec/text/DOC.1.txt"
    evidence = material.evidence
    assert (
        runtime.load_verified_provenance(
            run_id=RUN_ID,
            evidence_id=evidence.evidence_id,
            source=SourceType.CADEC,
            source_record_id=evidence.source_record_id,
            source_version=evidence.source_version,
            snapshot_id=evidence.snapshot_id,
            content_hash=evidence.content_hash,
        )
        == material.provenance
    )
    assert (
        runtime.load_verified_provenance(
            run_id=RUN_ID,
            evidence_id=evidence.evidence_id,
            source=SourceType.CADEC,
            source_record_id="foreign",
            source_version=evidence.source_version,
            snapshot_id=evidence.snapshot_id,
            content_hash=evidence.content_hash,
        )
        is None
    )
    receipt_files = tuple((tmp_path / "snapshots" / "cadec" / "material").rglob("*.json"))
    assert len(receipt_files) == 1
    assert b"PRIVATE-FIXTURE-NEVER-PERSIST" not in receipt_files[0].read_bytes()
    index_files = tuple((tmp_path / "snapshots" / "cadec" / "material-index").rglob("*.json"))
    assert len(index_files) == 1
    assert b"PRIVATE-FIXTURE-NEVER-PERSIST" not in index_files[0].read_bytes()


def test_twenty_reference_receipt_fits_new_finite_cap_and_old_cap_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch, tuple(_document(f"DOC.{number}", "match synthetic") for number in range(1, 21))
    )
    runtime = _runtime(tmp_path / "accepted")
    accepted_running, collected = _collected(runtime)
    assert len(collected.evidence_refs) == 20
    receipt = next((tmp_path / "accepted" / "snapshots" / "cadec" / "material").rglob("*.json"))
    assert 65_536 < receipt.stat().st_size <= material_module._MAX_RECEIPT_BYTES
    assert b"match synthetic" not in receipt.read_bytes()
    receipt.write_bytes(
        receipt.read_bytes()
        + b" " * (material_module._MAX_RECEIPT_BYTES + 1 - receipt.stat().st_size)
    )
    with pytest.raises(CadecMaterialError, match="receipt unavailable or invalid") as rejected:
        runtime._read_receipt(
            RUN_ID, _scope(), accepted_running, accepted_running.active_attempt.attempt_id
        )
    assert isinstance(rejected.value.__cause__, CadecMaterialError)
    assert "byte size is invalid" in str(rejected.value.__cause__)

    monkeypatch.setattr(material_module, "_MAX_RECEIPT_BYTES", 65_536)
    lower_runtime = _runtime(tmp_path / "rejected")
    scope = _scope()
    pending = SourceTaskState(
        task_id=source_task_id(RUN_ID, SourceType.CADEC), source=SourceType.CADEC
    )
    attempt = source_task_attempt(pending.task_id, 1)
    running = planned_running_source_task(lower_runtime, pending, scope, attempt, RUN_ID)
    with pytest.raises(CadecMaterialError, match="byte cap"):
        lower_runtime.collect(running, scope, attempt)
    assert not tuple((tmp_path / "rejected" / "snapshots" / "cadec" / "material").rglob("*.json"))


def test_same_attempt_reuses_receipt_timestamp_and_repairs_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, (_document("DOC.1", "match PRIVATE-FIXTURE-NEVER-PERSIST"),))
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    index = next((tmp_path / "snapshots" / "cadec" / "material-index").rglob("*.json"))
    index.unlink()
    restarted = _runtime(tmp_path, NOW + timedelta(days=1))
    repeated = restarted.collect(running, _scope(), running.active_attempt)
    assert repeated == result
    assert index.exists()


def test_cadec_material_replay_fails_if_receipt_is_missing_or_task_substituted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, (_document("DOC.1", "match PRIVATE-FIXTURE-NEVER-PERSIST"),))
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    scope = _scope()
    terminal = terminal_source_task(running, result, RUN_ID)
    with pytest.raises(CadecMaterialError):
        runtime.read_material(
            "run:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            scope,
            terminal,
            terminal.operation_results[1],
        )
    receipt_files = tuple((tmp_path / "snapshots" / "cadec" / "material").rglob("*.json"))
    receipt_files[0].unlink()
    with pytest.raises(CadecMaterialError):
        runtime.validate_terminal_task(terminal, scope)


def test_unavailable_asset_keeps_failed_coverage_and_zero_material(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    assert result.terminal_outcome_ref.outcome.execution_status.value == "failed"
    assert result.evidence_refs == ()
    terminal = terminal_source_task(running, result, RUN_ID)
    runtime.validate_terminal_task(terminal, _scope())
    assert not (tmp_path / "snapshots" / "cadec" / "material").exists()


def test_retrieval_time_and_exact_asset_are_bound_to_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, (_document("DOC.1", "match PRIVATE-FIXTURE-NEVER-PERSIST"),))
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    terminal = terminal_source_task(running, result, RUN_ID)
    receipt = next((tmp_path / "snapshots" / "cadec" / "material").rglob("*.json"))
    original = receipt.read_bytes()
    altered = json.loads(original)
    altered["retrieved_at_utc"] = "2026-09-19T12:00:00Z"
    receipt.write_bytes(canonical_json(altered).encode("utf-8"))
    with pytest.raises(CadecMaterialError):
        runtime.validate_terminal_task(terminal, _scope())
    receipt.write_bytes(original)
    _install(monkeypatch, (_document("DOC.1", "match changed original source"),))
    with pytest.raises(ValueError):
        runtime.validate_terminal_task(terminal, _scope())


def test_malformed_receipt_operation_inventory_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, (_document("DOC.1", "match PRIVATE-FIXTURE-NEVER-PERSIST"),))
    runtime = _runtime(tmp_path)
    running, result = _collected(runtime)
    terminal = terminal_source_task(running, result, RUN_ID)
    receipt = next((tmp_path / "snapshots" / "cadec" / "material").rglob("*.json"))
    altered = json.loads(receipt.read_bytes())
    altered["legacy_collection"]["required_operations"] = []
    receipt.write_bytes(canonical_json(altered).encode("utf-8"))
    with pytest.raises(CadecMaterialError):
        runtime.validate_terminal_task(terminal, _scope())
