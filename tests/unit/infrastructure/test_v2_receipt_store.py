"""Offline canonical boundaries for the durable V2 receipt adapter."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from tests.unit.tools import test_report_validation as fixtures

from medevidence.infrastructure.v2_receipt_store import V2ReceiptStore
from medevidence.persistence.repositories import PersistenceIntegrityError, PersistenceRepository
from medevidence.tools.report_validation import (
    PlannedStage2SemanticInputV2,
    SemanticSupport,
    ValidationMode,
    canonical_stage1_receipt_payload_v2,
    canonical_validate_report,
    canonical_validation_receipt_payload,
)


class MemoryRepository:
    def __init__(self) -> None:
        self.stage1: dict[str, object] | None = None
        self.final: dict[str, object] | None = None

    def save_stage1_receipt(self, payload: dict[str, object]) -> dict[str, object]:
        self.stage1 = payload
        return payload

    def load_stage1_receipt(self, receipt_id: str) -> dict[str, object] | None:
        return self.stage1

    def save_receipt(self, payload: dict[str, object]) -> dict[str, object]:
        self.final = payload
        return payload

    def load_receipt(self, receipt_id: str) -> dict[str, object] | None:
        return self.final


def _stage1_payload() -> dict[str, object]:
    source, _, projections = fixtures._v2_request(
        (fixtures.CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    plans = tuple(
        PlannedStage2SemanticInputV2(item.citation_id, item.input_digest, item.method, item.version)
        for item in projections
    )
    request = replace(source, registry=replace(source.registry, semantic_expectations=plans))
    audit = canonical_validate_report(request, mode=ValidationMode.PREPARE_STAGE1)
    assert audit.stage1_receipt is not None
    return canonical_stage1_receipt_payload_v2(audit.stage1_receipt)


def _final_payload() -> dict[str, object]:
    request, provider, _ = fixtures._v2_request(
        (fixtures.CitationRelationship.SUPPORTS,), (SemanticSupport.SUPPORTED,)
    )
    audit = canonical_validate_report(
        request, mode=ValidationMode.ASSESS, semantic_result_provider=provider
    )
    assert audit.receipt is not None
    return canonical_validation_receipt_payload(audit.receipt)


def _store(repository: MemoryRepository) -> V2ReceiptStore:
    return V2ReceiptStore(cast(PersistenceRepository, repository))


def test_stage1_receipt_exact_save_reload_and_corruption_rejected() -> None:
    repository = MemoryRepository()
    store = _store(repository)
    payload = _stage1_payload()
    saved = store.save_stage1_receipt(payload)
    assert store.load_stage1_receipt(cast(str, saved["receipt_id"])) == saved

    repository.stage1 = {**cast(dict[str, object], saved), "scope_id": "scope:foreign"}
    with pytest.raises(PersistenceIntegrityError, match="noncanonical"):
        store.load_stage1_receipt(cast(str, saved["receipt_id"]))


def test_stage1_foreign_or_malformed_payload_never_reaches_repository() -> None:
    repository = MemoryRepository()
    store = _store(repository)
    payload = _stage1_payload()
    for mutated in (
        {**payload, "report_id": "report:foreign"},
        {**payload, "stage1_passed": False},
        {**payload, "stage1_passed": 1},
        {**payload, "claim_result_ids": [("claim:foreign", "result:foreign")]},
        {**payload, "unexpected": True},
        {**payload, "citation_ids": ["x"] * 401},
    ):
        with pytest.raises(ValueError):
            store.save_stage1_receipt(mutated)
        assert repository.stage1 is None


def test_final_v2_receipt_exact_save_reload_and_corruption_rejected() -> None:
    repository = MemoryRepository()
    store = _store(repository)
    payload = _final_payload()
    saved = store.save_receipt(payload)
    assert store.load_receipt(cast(str, saved["receipt_id"])) == saved

    repository.final = {
        **cast(dict[str, object], saved),
        "routing_policy_hash": "sha256:" + "0" * 64,
    }
    with pytest.raises(PersistenceIntegrityError, match="noncanonical"):
        store.load_receipt(cast(str, saved["receipt_id"]))


def test_final_v2_receipt_invalid_nested_routing_is_rejected_before_save() -> None:
    repository = MemoryRepository()
    store = _store(repository)
    payload = _final_payload()
    claims = cast(list[dict[str, object]], payload["claim_results"])
    citations = cast(list[dict[str, object]], claims[0]["citation_results"])
    tampered_citations = [{**citations[0], "human_review_required": "yes"}]
    tampered = {
        **payload,
        "claim_results": [{**claims[0], "citation_results": tampered_citations}],
    }
    with pytest.raises(ValueError):
        store.save_receipt(tampered)
    assert repository.final is None
