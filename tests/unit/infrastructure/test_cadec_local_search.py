"""Infrastructure tests for transient exact-asset CADEC search."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import cast

import pytest

import medevidence.infrastructure.cadec_local_search as adapter_module
import medevidence.tools.cadec_runtime as runtime
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
    ExecutionBounds,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
)
from medevidence.infrastructure.cadec_local_search import CadecLocalSearchAdapter

ARCHIVE = Path("C:/approved/CADEC.v2.zip")
MANIFEST = Path("C:/approved/manifest.json")


def _scope(*, term: str = "match") -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="drug-a", preferred_term=term),),
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


def _verification() -> CadecVerificationSummary:
    return CadecVerificationSummary(
        archive_sha256="4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a",
        archive_bytes=1_870_497,
        manifest_sha256="1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa",
        manifest_bytes=1_699_979,
        inventory_sha256="eabcff5564e2266bb8b749bf4b68c164d36aeb0b511fb775674baf762b9b10b8",
        inventory_entry_count=5_005,
        inventory_file_count=5_000,
        inventory_directory_count=5,
        inventory_uncompressed_bytes=1_627_015,
        canonical_document_count=1_250,
        canonical_document_sha256="0007626fa17053350628a9d3a619bceaada9db9a6e660e113fa6c4cd8681fb2a",
        approved_document_count=1_248,
        approved_document_sha256="7f168cc7496d2b140182e30d96afdf4367ce67f122e30447e0ecbbb17358cfa6",
        excluded_document_count=2,
        excluded_document_sha256="14b01844c6471d597e1b0c5e9a9483a32992b3c0a5158ef7966e171f42aa84dd",
        train_count=992,
        train_membership_sha256="e533c904637a86b447ce4cee5973b4041ff8de1679fcb073e78a0525835c8329",
        development_count=119,
        development_membership_sha256="dd219af2c42b717fb1df7d24b04de9bb031c099d4deb513091c6d49d4b2b799f",
        test_count=137,
        test_membership_sha256="6bf824a4fe7a708a836cf08b007734622bb02c2fecf0d1441febfb0103a3e26a",
        encoding_exception_verified=True,
        empty_document_count=2,
        malformed_row_count=5,
        original_reference_binding_limitation_count=2,
        meddra_reference_binding_limitation_count=44,
        sct_reference_binding_limitation_count=45,
        raw_out_of_order_transition_count=43,
        raw_out_of_order_document_count=26,
        provider_gold_only=True,
        predicted_artifact_admitted=False,
        output_document_count=1_248,
        output_annotation_count=24_478,
        output_original_annotation_count=9_089,
        output_meddra_annotation_count=6_300,
        output_sct_annotation_count=9_089,
        output_locator_count=24_478,
        all_validation_passed=True,
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    documents: tuple[_CadecAdmittedDocumentText, ...],
) -> _CadecTextLoadResult:
    admitted = list(documents)
    for index in range(2 - sum(not item.text for item in admitted)):
        admitted.append(_document(f"EMPTY.{index + 100}", ""))
    for index in range(1_248 - len(admitted)):
        admitted.append(_document(f"PAD.{index + 1}", "unrelated"))
    assert len(admitted) == 1_248
    documents = tuple(admitted)
    verification = _verification()
    loaded = _CadecTextLoadResult(
        admitted=CadecLoadResult(
            release_manifest=CadecReleaseManifestV1.create(),
            documents=tuple(item.document for item in documents),
            annotations=(),
            locators=(),
            verification=verification,
        ),
        document_texts=documents,
    )
    monkeypatch.setattr(adapter_module, "_load_cadec_archive_with_text", lambda *_args: loaded)
    return loaded


def test_adapter_requires_explicit_absolute_paths() -> None:
    with pytest.raises(ValueError, match="absolute"):
        CadecLocalSearchAdapter(archive_path="relative.zip", manifest_path="manifest.json")


def test_adapter_scores_every_nonempty_document_and_returns_payload_free_top_twenty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents = (
        *(_document(f"DOC.{index}", "match") for index in range(1, 26)),
        _document("EMPTY.1", ""),
    )
    _install(monkeypatch, documents)
    observed: dict[str, object] = {}

    class FakeIndex:
        def __init__(
            self,
            doc_ids: tuple[str, ...],
            texts: tuple[str, ...],
            *,
            k1: float,
            b: float,
        ) -> None:
            observed.update(doc_ids=doc_ids, texts=len(texts), k1=k1, b=b)

        def search(self, query: str, limit: int) -> list[tuple[str, float]]:
            observed.update(query=query, limit=limit)
            return [
                (document_id, 1.0 if document_id.startswith("DOC.") else 0.0)
                for document_id in reversed(cast(tuple[str, ...], observed["doc_ids"]))
            ]

    monkeypatch.setattr(adapter_module, "BM25Index", FakeIndex)
    scope = _scope()
    result = CadecLocalSearchAdapter(archive_path=ARCHIVE, manifest_path=MANIFEST).search(
        plan=runtime.plan_cadec_local_search(scope), scope=scope
    )

    assert observed["k1"] == 0.9 and observed["b"] == 0.4
    assert observed["texts"] == observed["limit"] == 1_246
    assert result.documents_scored == 1_246
    assert len(result.evidence_refs) == 20
    assert tuple(item.document_id for item in result.evidence_refs) == tuple(
        sorted(
            (item.document.document_id for item in documents[:-1]),
            key=lambda item: item.encode("utf-8"),
        )[:20]
    )
    assert result.outcome.coverage_status.value == "complete"
    assert result.outcome.truncated is False
    assert result.outcome.configured_bounds == ExecutionBounds.from_scope(scope)
    assert result.scope_bounds == ExecutionBounds.from_scope(scope)
    assert result.outcome.configured_bounds.max_records == 100
    assert result.result_limit == 20
    assert "text" not in type(result).model_fields
    assert all("text" not in type(item).model_fields for item in result.evidence_refs)


def test_plan_and_materialization_drift_fail_closed_without_partial_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden(*_args: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(adapter_module, "_load_cadec_archive_with_text", forbidden)
    scope = _scope()
    drifted = runtime.plan_cadec_local_search(scope).model_copy(update={"query": "foreign"})
    with pytest.raises(runtime.CadecRuntimeError) as plan_error:
        CadecLocalSearchAdapter(archive_path=ARCHIVE, manifest_path=MANIFEST).search(
            plan=drifted, scope=scope
        )
    assert plan_error.value.code is runtime.CadecRuntimeErrorCode.PLAN_INTEGRITY
    assert calls == 0

    valid = _document("VALID.1", "match")
    _install(
        monkeypatch,
        (_CadecAdmittedDocumentText(document=valid.document, text="tampered"),),
    )
    with pytest.raises(runtime.CadecRuntimeError) as materialization:
        CadecLocalSearchAdapter(archive_path=ARCHIVE, manifest_path=MANIFEST).search(
            plan=runtime.plan_cadec_local_search(scope), scope=scope
        )
    assert materialization.value.code is runtime.CadecRuntimeErrorCode.MATERIALIZATION
    assert materialization.value.evidence_refs == ()


def test_transient_handoff_requires_every_exact_admitted_metadata_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _install(monkeypatch, (_document("VALID.1", "match"),))
    foreign = _document("FOREIGN.1", "match")
    drifted = _CadecTextLoadResult(
        admitted=loaded.admitted,
        document_texts=(foreign, *loaded.document_texts[1:]),
    )
    monkeypatch.setattr(
        adapter_module,
        "_load_cadec_archive_with_text",
        lambda *_args: drifted,
    )
    scope = _scope()

    with pytest.raises(runtime.CadecRuntimeError) as raised:
        CadecLocalSearchAdapter(archive_path=ARCHIVE, manifest_path=MANIFEST).search(
            plan=runtime.plan_cadec_local_search(scope),
            scope=scope,
        )
    assert raised.value.code is runtime.CadecRuntimeErrorCode.MATERIALIZATION
    assert raised.value.evidence_refs == ()


def test_adapter_is_the_only_concrete_loader_and_retrieval_boundary() -> None:
    source = inspect.getsource(adapter_module)
    assert "medevidence.connectors.cadec.loader" in source
    assert "medevidence.retrieval.core" in source
    assert "persistence" not in source.casefold()
    assert "qdrant" not in source.casefold()
