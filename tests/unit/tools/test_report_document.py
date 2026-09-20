"""Offline tests for the display document's exact authority and safe rendering."""

from __future__ import annotations

import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.tools import test_report_validation as fixtures

from medevidence.domain import CoverageStatus, ExecutionStatus, ResultStatus, SourceType
from medevidence.tools.report_document import (
    EvidenceProvenanceV1,
    report_document_to_json,
    report_document_to_markdown,
)
from medevidence.tools.report_document import (
    build_report_document as render_from_stores,
)
from medevidence.tools.report_validation import (
    CanonicalValidationError,
    CitationRelationship,
    NumericalContextInput,
    NumericalFactInput,
    SemanticSupport,
    StoredValidationInput,
    ValidationMode,
    canonical_numerical_text,
    canonical_validate_report,
    canonical_validation_receipt_payload,
)

RETRIEVED = datetime(2026, 1, 1, tzinfo=UTC)
GENERATED = datetime(2026, 2, 1, tzinfo=UTC)


class FakeReceiptStore:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self.payload = payload
        self.read_ids: list[str] = []

    def load_receipt(self, receipt_id: str) -> dict[str, object] | None:
        self.read_ids.append(receipt_id)
        return self.payload


class FakeProvenanceStore:
    def __init__(self, run_id: str, rows: tuple[EvidenceProvenanceV1, ...]) -> None:
        self.rows = {
            (
                run_id,
                row.evidence_id,
                row.source,
                row.source_record_id,
                row.source_version,
                row.snapshot_id,
                row.content_hash,
            ): row
            for row in rows
        }
        self.read_keys: list[tuple[object, ...]] = []

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
        key = (
            run_id,
            evidence_id,
            source,
            source_record_id,
            source_version,
            snapshot_id,
            content_hash,
        )
        self.read_keys.append(key)
        return self.rows.get(key)


def build_report_document(
    request,
    receipt,
    *,
    source_provenance,
    generated_at,
    receipt_store: FakeReceiptStore | None = None,
    provenance_store: FakeProvenanceStore | None = None,
):
    """Test convenience: default stores represent fixed test fixtures only."""

    return render_from_stores(
        request,
        receipt,
        source_provenance=source_provenance,
        generated_at=generated_at,
        receipt_store=receipt_store or FakeReceiptStore(receipt if type(receipt) is dict else None),
        provenance_store=provenance_store or FakeProvenanceStore(request.run_id, source_provenance),
    )


def _passed(source: SourceType = SourceType.PUBMED):
    request = fixtures._material_request(source)
    audit = canonical_validate_report(
        request,
        mode=ValidationMode.ASSESS,
        semantic_result_provider=fixtures.Provider(),
    )
    assert audit.summary.passed and audit.receipt is not None
    stored = StoredValidationInput(True, True, True, ())
    return (
        replace(request, stored_validation=stored),
        canonical_validation_receipt_payload(audit.receipt),
    )


def test_numeric_claim_preserves_exact_context_in_hash_json_and_safe_markdown() -> None:
    context = NumericalContextInput(
        "7",
        "per 100 <units>",
        "under [sample]",
        "vs *control*",
        "2026 Q1",
        "Adults | group",
    )
    fact = NumericalFactInput(
        "locator:pubmed:000",
        "",
        *(getattr(context, item.name) for item in fields(context)),
    )
    fact = replace(fact, exact_text=canonical_numerical_text(fact))
    request = fixtures._material_request(SourceType.PUBMED, context=context, facts=(fact,))
    audit = canonical_validate_report(
        request, mode=ValidationMode.ASSESS, semantic_result_provider=fixtures.Provider()
    )
    assert audit.summary.passed and audit.receipt is not None
    stored = replace(request, stored_validation=StoredValidationInput(True, True, True, ()))
    document = build_report_document(
        stored,
        canonical_validation_receipt_payload(audit.receipt),
        source_provenance=_provenance(stored),
        generated_at=GENERATED,
    )
    assert document.claims[0].numerical_context == context
    payload = json.loads(report_document_to_json(document))
    assert payload["claims"][0]["numerical_context"] == {
        item.name: getattr(context, item.name) for item in fields(context)
    }
    markdown = report_document_to_markdown(document)
    assert "denominator=under \\[sample\\]" in markdown
    assert "comparator=vs \\*control\\*" in markdown
    assert "unit=per 100 &lt;units&gt;" in markdown
    assert "population scope=Adults \\| group" in markdown
    attacked_claim = replace(
        document.claims[0],
        numerical_context=replace(context, denominator="forged denominator"),
    )
    with pytest.raises(CanonicalValidationError, match="report_document_render_hash_drift"):
        report_document_to_json(replace(document, claims=(attacked_claim,)))


def test_qualitative_claim_has_no_numerical_context_markup() -> None:
    request, receipt = _passed()
    document = build_report_document(
        request, receipt, source_provenance=_provenance(request), generated_at=GENERATED
    )
    assert document.claims[0].numerical_context is None
    assert "numerical_context" not in json.loads(report_document_to_json(document))["claims"][0]
    assert "Numerical context:" not in report_document_to_markdown(document)


def _provenance(request, *, url: str | None = "https://example.org/source?x=1"):
    return tuple(
        EvidenceProvenanceV1(
            item.evidence_id,
            item.source,
            item.source_record_id,
            item.source_version,
            item.snapshot_id,
            item.content_hash,
            url,
            None if url else f"local:{item.source_record_id}",
            RETRIEVED,
            ("verified snapshot", "normalized evidence"),
        )
        for item in request.registry.evidence
    )


def test_exact_receipt_and_source_binding_and_deterministic_serializers() -> None:
    request, receipt = _passed()
    provenance = _provenance(request)
    first = build_report_document(
        request, receipt, source_provenance=provenance, generated_at=GENERATED
    )
    second = build_report_document(
        request, receipt, source_provenance=provenance, generated_at=GENERATED
    )
    assert first == second
    assert first.report_content_hash == request.synthesis.report_content_hash
    assert first.render_document_hash != first.report_content_hash
    assert first.validation_receipt_id == receipt["receipt_id"]
    assert first.review_status == "awaiting_human_export_approval"
    assert first.retrieval_as_of == RETRIEVED
    assert first.claims[0].citations[0].exact_locator == request.registry.citations[0].locator_ref
    assert report_document_to_json(first) == report_document_to_json(second)
    assert report_document_to_markdown(first) == report_document_to_markdown(second)
    payload = json.loads(report_document_to_json(first))
    assert payload["render_document_hash"] == first.render_document_hash
    assert (
        payload["claims"][0]["citations"][0]["source_record_id"] == provenance[0].source_record_id
    )
    assert "[source record](https://example.org/source?x=1)" in report_document_to_markdown(first)


def test_final_v2_receipt_renders_without_provider_call() -> None:
    request, provider, _ = fixtures._v2_request(
        (CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    audit = canonical_validate_report(
        request, mode=ValidationMode.ASSESS, semantic_result_provider=provider
    )
    assert audit.summary.passed and audit.receipt is not None
    prior_calls = len(provider.calls)
    stored = replace(request, stored_validation=StoredValidationInput(True, True, True, ()))
    document = build_report_document(
        stored,
        canonical_validation_receipt_payload(audit.receipt),
        source_provenance=_provenance(stored),
        generated_at=GENERATED,
    )
    assert len(provider.calls) == prior_calls
    assert document.validation_receipt_id == audit.receipt.receipt_id
    assert document.claims[0].citations[0].evidence_id == stored.registry.evidence[0].evidence_id


def test_rejects_missing_stale_foreign_receipt_and_mutated_request() -> None:
    request, receipt = _passed()
    provenance = _provenance(request)
    with pytest.raises(CanonicalValidationError):
        build_report_document(
            replace(request, stored_validation=None),
            receipt,
            source_provenance=provenance,
            generated_at=GENERATED,
        )
    with pytest.raises(CanonicalValidationError):
        build_report_document(request, None, source_provenance=provenance, generated_at=GENERATED)  # type: ignore[arg-type]
    attacked_receipt = dict(receipt)
    attacked_receipt["receipt_content_hash"] = "sha256:" + "f" * 64
    with pytest.raises(CanonicalValidationError):
        build_report_document(
            request, attacked_receipt, source_provenance=provenance, generated_at=GENERATED
        )
    mutated = replace(request, source_plan_id="source-plan:sha256:" + "f" * 64)
    with pytest.raises(CanonicalValidationError):
        build_report_document(
            mutated, receipt, source_provenance=provenance, generated_at=GENERATED
        )


def test_store_readback_rejects_unpersisted_receipt_and_forged_metadata() -> None:
    request, receipt = _passed()
    provenance = _provenance(request)
    receipt_store = FakeReceiptStore(receipt)
    provenance_store = FakeProvenanceStore(request.run_id, provenance)
    original = build_report_document(
        request,
        receipt,
        source_provenance=provenance,
        generated_at=GENERATED,
        receipt_store=receipt_store,
        provenance_store=provenance_store,
    )
    assert original.validation_receipt_id in receipt_store.read_ids
    assert provenance_store.read_keys == [
        (
            request.run_id,
            provenance[0].evidence_id,
            provenance[0].source,
            provenance[0].source_record_id,
            provenance[0].source_version,
            provenance[0].snapshot_id,
            provenance[0].content_hash,
        )
    ]
    for claimed in (
        replace(provenance[0], source_url="https://attacker.example/forged"),
        replace(provenance[0], retrieved_at=RETRIEVED + timedelta(days=1)),
        replace(provenance[0], transformation_lineage=("attacker transform",)),
        replace(provenance[0], source_url=None, lookup_key="attacker:key"),
    ):
        with pytest.raises(CanonicalValidationError, match="report_provenance_store_mismatch"):
            build_report_document(
                request,
                receipt,
                source_provenance=(claimed,),
                generated_at=GENERATED,
                receipt_store=receipt_store,
                provenance_store=provenance_store,
            )
    with pytest.raises(CanonicalValidationError, match="report_receipt_not_stored"):
        build_report_document(
            request,
            receipt,
            source_provenance=provenance,
            generated_at=GENERATED,
            receipt_store=FakeReceiptStore(None),
            provenance_store=provenance_store,
        )
    _, foreign_receipt = _passed(SourceType.DAILYMED)
    with pytest.raises(CanonicalValidationError, match="report_receipt_store_mismatch"):
        build_report_document(
            request,
            receipt,
            source_provenance=provenance,
            generated_at=GENERATED,
            receipt_store=FakeReceiptStore(foreign_receipt),
            provenance_store=provenance_store,
        )
    with pytest.raises(CanonicalValidationError, match="report_provenance_store_mismatch"):
        build_report_document(
            request,
            receipt,
            source_provenance=provenance,
            generated_at=GENERATED,
            receipt_store=receipt_store,
            provenance_store=FakeProvenanceStore(request.run_id, ()),
        )
    with pytest.raises(CanonicalValidationError, match="report_authority_store_missing"):
        render_from_stores(
            request,
            receipt,
            source_provenance=provenance,
            generated_at=GENERATED,
            receipt_store=None,  # type: ignore[arg-type]
            provenance_store=provenance_store,
        )


def test_rejects_missing_extra_foreign_or_incomplete_provenance() -> None:
    request, receipt = _passed()
    provenance = _provenance(request)
    for rows in (
        (),
        provenance + provenance,
        (replace(provenance[0], evidence_id="evidence:foreign"),),
        (replace(provenance[0], source_record_id="record:foreign"),),
    ):
        with pytest.raises(CanonicalValidationError):
            build_report_document(request, receipt, source_provenance=rows, generated_at=GENERATED)
    with pytest.raises(CanonicalValidationError):
        EvidenceProvenanceV1(
            provenance[0].evidence_id,
            SourceType.PUBMED,
            provenance[0].source_record_id,
            provenance[0].source_version,
            provenance[0].snapshot_id,
            provenance[0].content_hash,
            "javascript:alert(1)",
            None,
            RETRIEVED,
            ("verified snapshot",),
        )
    with pytest.raises(CanonicalValidationError):
        replace(
            provenance[0], retrieved_at=RETRIEVED + timedelta(hours=1), transformation_lineage=()
        )
    with pytest.raises(CanonicalValidationError):
        build_report_document(
            request,
            receipt,
            source_provenance=(
                replace(provenance[0], retrieved_at=GENERATED + timedelta(hours=1)),
            ),
            generated_at=GENERATED,
        )


def test_partial_and_failed_zero_results_remain_indeterminate() -> None:
    outcomes = (
        fixtures._outcome(
            SourceType.PUBMED,
            ExecutionStatus.FAILED,
            CoverageStatus.UNAVAILABLE,
            ResultStatus.INDETERMINATE,
        ),
        fixtures._outcome(
            SourceType.PUBMED,
            ExecutionStatus.SUCCEEDED,
            CoverageStatus.PARTIAL,
            ResultStatus.INDETERMINATE,
        ),
    )
    for outcome in outcomes:
        request = fixtures._empty_request(SourceType.PUBMED, outcomes=(outcome,))
        audit = canonical_validate_report(request, mode=ValidationMode.ASSESS)
        assert audit.summary.passed and audit.receipt is not None
        stored = replace(request, stored_validation=StoredValidationInput(True, True, True, ()))
        document = build_report_document(
            stored,
            canonical_validation_receipt_payload(audit.receipt),
            source_provenance=(),
            generated_at=GENERATED,
        )
        assert document.coverage[0].interpretation == "indeterminate_not_evidence_of_absence"
        assert document.retrieval_as_of is None
        assert any("indeterminate" in item for item in document.limitations)
    complete_request = fixtures._empty_request(SourceType.PUBMED)
    complete_audit = canonical_validate_report(complete_request, mode=ValidationMode.ASSESS)
    assert complete_audit.summary.passed and complete_audit.receipt is not None
    complete_document = build_report_document(
        replace(complete_request, stored_validation=StoredValidationInput(True, True, True, ())),
        canonical_validation_receipt_payload(complete_audit.receipt),
        source_provenance=(),
        generated_at=GENERATED,
    )
    assert complete_document.coverage[0].interpretation == "complete_no_match"


def test_html_markdown_and_url_injection_are_escaped() -> None:
    request, receipt = _passed()
    provenance = _provenance(request, url=None)
    unsafe_lookup = replace(
        provenance[0], lookup_key="local:<img src=x onerror=alert(1)> [bad](javascript:1)"
    )
    document = build_report_document(
        request, receipt, source_provenance=(unsafe_lookup,), generated_at=GENERATED
    )
    markdown = report_document_to_markdown(document)
    assert "<img" not in markdown
    assert "[bad](javascript:1)" not in markdown
    assert "&lt;img" in markdown
    with pytest.raises(CanonicalValidationError):
        replace(provenance[0], source_url="https://example.org/a\n# injected")
    with pytest.raises(CanonicalValidationError):
        replace(provenance[0], source_url="https://user:secret@example.org/")
    with pytest.raises(CanonicalValidationError):
        report_document_to_json(replace(document, render_document_hash="sha256:" + "0" * 64))
