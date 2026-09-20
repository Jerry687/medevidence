"""Closed identity distinction for the metadata-only CADEC successor profile."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from medevidence.connectors.cadec.loader import _CadecAdmittedDocumentText, _member_artifact_id
from medevidence.domain import (
    CADEC_EXTERNAL_MANIFEST_SHA256,
    CADEC_RECOVERY_AUDIT_SHA256,
    CADEC_RECOVERY_CORPUS_VERSION,
    CADEC_RECOVERY_MANIFEST_SHA256,
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
)
from medevidence.infrastructure.cadec_local_search import _evidence_ref
from medevidence.infrastructure.cadec_material_runtime import _material
from medevidence.tools.cadec_runtime import (
    CadecVerifiedCorpus,
    plan_cadec_local_search,
    reconstruct_cadec_local_search_plan,
)


def _scope() -> ResearchScope:
    return ResearchScope.create(
        drugs=(DrugConcept(concept_id="drug-a", preferred_term="Synthetic"),),
        adverse_reactions=(AdverseEventConcept(concept_id="event-a", preferred_term="Reaction"),),
        date_range=None,
        selected_sources=(SourceType.CADEC,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=1, max_total_seconds=30),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def test_release_profiles_are_distinct_and_hybrids_reject() -> None:
    old = CadecReleaseManifestV1.create()
    recovered = CadecReleaseManifestV1.create(recovery=True)
    assert old.external_manifest_sha256 == CADEC_EXTERNAL_MANIFEST_SHA256
    assert recovered.external_manifest_sha256 == CADEC_RECOVERY_MANIFEST_SHA256
    assert old.corpus_version != recovered.corpus_version
    assert old.work_item == "M1B-CADEC-001"
    assert recovered.work_item == "CADEC-ASSET-RECOVERY-20260918"
    assert old.terminal_freeze_audit_sha256 != recovered.terminal_freeze_audit_sha256
    hybrid = recovered.model_dump(mode="python")
    hybrid["terminal_freeze_audit_sha256"] = old.terminal_freeze_audit_sha256
    with pytest.raises(ValueError, match="closed manifest and audit profile"):
        CadecReleaseManifestV1.model_validate(hybrid)
    hybrid["terminal_freeze_audit_sha256"] = recovered.terminal_freeze_audit_sha256
    hybrid["work_item"] = old.work_item
    with pytest.raises(ValueError, match="closed manifest and audit profile"):
        CadecReleaseManifestV1.model_validate(hybrid)


def test_search_plan_binds_selected_manifest_and_rejects_unknown_identity() -> None:
    scope = _scope()
    old = plan_cadec_local_search(scope)
    recovered = plan_cadec_local_search(scope, manifest_sha256=CADEC_RECOVERY_MANIFEST_SHA256)
    assert old.query_id != recovered.query_id
    assert reconstruct_cadec_local_search_plan(recovered, scope) == recovered
    with pytest.raises(ValueError, match="two closed admission profiles"):
        plan_cadec_local_search(scope, manifest_sha256="0" * 64)


def test_verification_does_not_accept_a_mixed_manifest_profile() -> None:
    from medevidence.tools.cadec_runtime import _EXACT_CADEC_VERIFICATION

    old = dict(_EXACT_CADEC_VERIFICATION)
    recovered = {
        **old,
        "manifest_sha256": CADEC_RECOVERY_MANIFEST_SHA256,
        "manifest_bytes": 1_235_699,
    }
    assert (
        CadecVerifiedCorpus.model_validate(recovered).manifest_sha256
        == CADEC_RECOVERY_MANIFEST_SHA256
    )
    with pytest.raises(ValueError, match="complete exact approved admission"):
        CadecVerifiedCorpus.model_validate({**recovered, "manifest_bytes": old["manifest_bytes"]})


def test_recovered_material_lineage_names_the_recovered_manifest() -> None:
    payload = b"synthetic"
    digest = hashlib.sha256(payload).hexdigest()
    path = "cadec/text/DOC.1.txt"
    artifact = _member_artifact_id(path, digest)
    ownership = {
        "corpus_version": CADEC_RECOVERY_CORPUS_VERSION,
        "release_manifest_sha256": CADEC_RECOVERY_CORPUS_VERSION,
        "terminal_freeze_audit_sha256": f"sha256:{CADEC_RECOVERY_AUDIT_SHA256}",
        "split": CadecSplit.TRAIN,
        "artifact_id": artifact,
        "artifact_sha256": f"sha256:{digest}",
    }
    provenance = CadecProvenanceContextV1.create(**ownership, lineage_artifact_ids=())
    document = CadecCorpusDocumentV1.create(
        **ownership,
        document_id="DOC.1",
        member_path=path,
        text_length=len(payload),
        text_sha256=f"sha256:{digest}",
        provenance=provenance,
    )
    item = _evidence_ref(_CadecAdmittedDocumentText(document=document, text="synthetic"), 1.0)
    material = _material(
        "run:sha256:" + "1" * 64,
        "snapshot:sha256:" + "2" * 64,
        item,
        datetime(2026, 9, 18, tzinfo=UTC),
        manifest_sha256=CADEC_RECOVERY_MANIFEST_SHA256,
    )
    assert (
        f"approved manifest sha256:{CADEC_RECOVERY_MANIFEST_SHA256}"
        in material.provenance.transformation_lineage
    )
    assert (
        f"approved manifest sha256:{CADEC_EXTERNAL_MANIFEST_SHA256}"
        not in material.provenance.transformation_lineage
    )
