"""Source-bound report material survives exact immutable roundtrip."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.unit.tools.test_generation_v2 import _candidate, _input, _qualitative_claim, _trusted
from tests.unit.tools.test_report_validation import _v2_request
from tests.unit.tools.test_report_validation_source_bindings_v3 import (
    _v3_report_with_child_evidence,
)

from medevidence.domain import derive_identity
from medevidence.infrastructure.local_synthesis_runtime import (
    LocalSynthesisError,
    LocalSynthesisRuntime,
    _decode_material,
    _encode_material,
    _Material,
    _semantic_plans_match_receipt,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.tools.generation_v2_service import DeepSeekGenerationReceiptRefV2
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import (
    M3_VALIDATION_CONFIGURATION_V4,
    CitationRelationship,
    PlannedStage2SemanticInputV2,
    SemanticSupport,
)
from medevidence.tools.report_validation_source_bindings_v3 import evidence_locator_matches
from medevidence.tools.semantic_evaluation import QWEN_SEMANTIC_V2_PROVIDER_METHOD
from medevidence.tools.synthesis_mapping import map_generation_v2_to_registry_v4


def test_v4_child_bound_material_roundtrip_and_tamper_rejection() -> None:
    request = _v3_report_with_child_evidence()
    registry = replace(
        request.registry,
        evaluator_identity=replace(
            request.registry.evaluator_identity,
            method=QWEN_SEMANTIC_V2_PROVIDER_METHOD,
        ),
        configuration_version=M3_VALIDATION_CONFIGURATION_V4,
    )
    request = replace(request, registry=registry)
    evidence = registry.evidence[0]
    origin = EvidenceProvenanceV1(
        evidence_id=evidence.evidence_id,
        source=evidence.source,
        source_record_id=evidence.source_record_id,
        source_version=evidence.source_version,
        snapshot_id=evidence.snapshot_id,
        content_hash=evidence.content_hash,
        source_url=None,
        lookup_key="local:test",
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        transformation_lineage=("verified-source-reader",),
    )
    receipt = DeepSeekGenerationReceiptRefV2(
        receipt_id="generation-receipt:sha256:" + "1" * 64,
        receipt_content_hash="sha256:" + "2" * 64,
        run_id=request.run_id,
        scope_id=request.scope.scope_id,
        candidate_hash="sha256:" + "3" * 64,
        generation_material_hash="sha256:" + "4" * 64,
    )
    material = _Material(request, (origin,), datetime(2026, 9, 18, tzinfo=UTC), receipt)
    encoded = _encode_material(material)
    assert _decode_material(encoded) == material
    with pytest.raises(LocalSynthesisError, match="report_material_invalid"):
        _decode_material(encoded + b"\n")


def test_qwen_registry_retains_generation_evidence_and_exact_citation_plan() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    mapped = map_generation_v2_to_registry_v4(
        generation_input,
        candidate,
        trusted_evidence=(evidence,),
        all_verified_source_references=(evidence,),
    )
    assert mapped.registry.evidence == (evidence,)
    assert mapped.registry.evaluator_identity.method == QWEN_SEMANTIC_V2_PROVIDER_METHOD
    assert mapped.registry.configuration_version == M3_VALIDATION_CONFIGURATION_V4
    assert tuple(item.method for item in mapped.registry.semantic_expectations) == (
        QWEN_SEMANTIC_V2_PROVIDER_METHOD,
    )


def test_unknown_generation_attempt_is_not_sent_twice(tmp_path: Path) -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    snapshots = SnapshotStore(tmp_path / "snapshots", free_bytes=lambda _: 20_000_000_000)
    runtime = LocalSynthesisRuntime(
        material_reader=None,  # type: ignore[arg-type]
        generation=None,  # type: ignore[arg-type]
        generation_receipts=None,  # type: ignore[arg-type]
        validation_receipts=None,  # type: ignore[arg-type]
        registry_store=None,  # type: ignore[arg-type]
        snapshots=snapshots,
    )
    runtime._start_generation_attempt(
        report_id="report:sha256:" + "a" * 64,
        generation_input=generation_input,
        trusted_evidence=(evidence,),
        prior_report_content_hash=None,
    )
    with pytest.raises(LocalSynthesisError, match="synthesis_attempt_outcome_unknown"):
        runtime._start_generation_attempt(
            report_id="report:sha256:" + "a" * 64,
            generation_input=generation_input,
            trusted_evidence=(evidence,),
            prior_report_content_hash=None,
        )


def test_pubmed_child_locator_requires_exact_derived_identity() -> None:
    request = _v3_report_with_child_evidence()
    task = request.tasks[0]
    raw_locator = request.registry.evidence[0].locators[0]
    derived = derive_identity("pubmed-material-locator", raw_locator)
    assert evidence_locator_matches(task, derived, raw_locator, M3_VALIDATION_CONFIGURATION_V4)
    assert not evidence_locator_matches(
        task,
        derive_identity("pubmed-material-locator", raw_locator + "foreign"),
        raw_locator,
        M3_VALIDATION_CONFIGURATION_V4,
    )
    assert not evidence_locator_matches(
        task, derived, raw_locator, "M3_VALIDATION_CONFIGURATION_V2"
    )


def test_receipt_projection_cannot_drop_planned_comparison_or_conflict() -> None:
    _, _, projections = _v2_request(
        (CitationRelationship.SUPPORTS, CitationRelationship.CONTEXT_ONLY),
        (SemanticSupport.SUPPORTED, SemanticSupport.SUPPORTED),
    )
    plans = tuple(
        PlannedStage2SemanticInputV2(
            item.citation_id,
            item.input_digest,
            item.method,
            item.version,
            item.comparison_id,
            item.conflict_id,
        )
        for item in projections
    )
    assert _semantic_plans_match_receipt(plans, projections)
    assert not _semantic_plans_match_receipt(
        (replace(plans[0], comparison_id="comparison:sha256:" + "a" * 64), *plans[1:]),
        projections,
    )
    assert not _semantic_plans_match_receipt(
        (replace(plans[0], conflict_id="conflict:sha256:" + "b" * 64), *plans[1:]),
        projections,
    )
