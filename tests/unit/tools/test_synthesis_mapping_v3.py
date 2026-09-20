"""Named V3 pre-semantic registry generation preserves candidate material."""

from __future__ import annotations

from dataclasses import replace

import pytest
from tests.unit.tools.test_generation_v2 import _candidate, _input, _qualitative_claim, _trusted

from medevidence.tools.report_validation import (
    M3_VALIDATION_CONFIGURATION_V2,
    M3_VALIDATION_CONFIGURATION_V3,
    NumericalContextInput,
    canonical_evidence_id,
)
from medevidence.tools.synthesis_mapping import (
    SynthesisMappingError,
    map_generation_v2_to_registry,
    map_generation_v2_to_registry_v3,
)


def _metadata_reference(evidence):  # type: ignore[no-untyped-def]
    metadata = replace(
        evidence,
        evidence_id="evidence:sha256:" + "0" * 64,
        source_record_id="record:pubmed:metadata",
        snapshot_id="snapshot:pubmed:metadata",
        content_hash="sha256:" + "c" * 64,
        locators=("locator:pubmed:metadata",),
        normalized_excerpt="Verified publication title; abstract unavailable.",
        permitted_claim_classes=frozenset(),
        permitted_inference_uses=frozenset(),
        numerical_facts=(),
    )
    return replace(metadata, evidence_id=canonical_evidence_id(metadata))


def test_named_v3_registry_differs_only_by_closed_configuration_version() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    old = map_generation_v2_to_registry(generation_input, candidate, trusted_evidence=(evidence,))
    new = map_generation_v2_to_registry_v3(
        generation_input, candidate, trusted_evidence=(evidence,)
    )
    assert old.registry.configuration_version == M3_VALIDATION_CONFIGURATION_V2
    assert new.registry.configuration_version == M3_VALIDATION_CONFIGURATION_V3
    assert old.candidate_hash == new.candidate_hash
    assert old.registry.claims == new.registry.claims
    assert old.registry.citations == new.registry.citations
    assert old.registry.evidence == new.registry.evidence
    assert old.registry.semantic_expectations == new.registry.semantic_expectations


def test_v3_keeps_metadata_in_registry_but_out_of_provider_generation() -> None:
    evidence = _trusted()
    metadata = _metadata_reference(evidence)
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    mapped = map_generation_v2_to_registry_v3(
        generation_input,
        candidate,
        trusted_evidence=(evidence,),
        all_verified_source_references=(evidence, metadata),
    )
    assert tuple(item.evidence_id for item in generation_input.evidence) == (evidence.evidence_id,)
    assert mapped.registry.evidence == (evidence, metadata)
    assert {item.evidence_id for item in mapped.registry.citations} == {evidence.evidence_id}


def test_v3_metadata_reference_cannot_become_a_candidate_citation() -> None:
    evidence = _trusted()
    metadata = _metadata_reference(evidence)
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(metadata))
    with pytest.raises(SynthesisMappingError, match="generation_v2_candidate_not_admitted"):
        map_generation_v2_to_registry_v3(
            generation_input,
            candidate,
            trusted_evidence=(evidence,),
            all_verified_source_references=(evidence, metadata),
        )


@pytest.mark.parametrize(
    "attack",
    (
        "omitted_claimable",
        "extra_claimable",
        "half_permission",
        "metadata_fact",
        "foreign_run",
        "duplicate_id",
        "duplicate_authority",
        "foreign_source",
    ),
)
def test_v3_registry_only_material_cannot_expand_provider_authority(attack: str) -> None:
    evidence = _trusted()
    metadata = _metadata_reference(evidence)
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    all_refs = (evidence, metadata)
    if attack == "omitted_claimable":
        all_refs = (metadata,)
    elif attack == "extra_claimable":
        extra = _trusted(index=1)
        all_refs = (evidence, extra, metadata)
    elif attack == "half_permission":
        half = replace(metadata, permitted_claim_classes=evidence.permitted_claim_classes)
        all_refs = (evidence, replace(half, evidence_id=canonical_evidence_id(half)))
    elif attack == "metadata_fact":
        numeric = _trusted(
            index=1,
            context=NumericalContextInput("1", "count", "none", "none", "test", "test"),
        )
        numeric_metadata = replace(
            numeric,
            permitted_claim_classes=frozenset(),
            permitted_inference_uses=frozenset(),
        )
        numeric_metadata = replace(
            numeric_metadata, evidence_id=canonical_evidence_id(numeric_metadata)
        )
        all_refs = (evidence, numeric_metadata)
    elif attack == "foreign_run":
        foreign = replace(metadata, authorized_run_id="run:foreign")
        all_refs = (evidence, replace(foreign, evidence_id=canonical_evidence_id(foreign)))
    elif attack == "duplicate_id":
        all_refs = (evidence, evidence)
    elif attack == "duplicate_authority":
        all_refs = (
            evidence,
            replace(
                metadata,
                snapshot_id=evidence.snapshot_id,
                content_hash=evidence.content_hash,
                locators=evidence.locators,
                evidence_id=canonical_evidence_id(
                    replace(
                        metadata,
                        snapshot_id=evidence.snapshot_id,
                        content_hash=evidence.content_hash,
                        locators=evidence.locators,
                    )
                ),
            ),
        )
    elif attack == "foreign_source":
        foreign = replace(metadata, source=type(evidence.source).FAERS)
        all_refs = (evidence, replace(foreign, evidence_id=canonical_evidence_id(foreign)))
    with pytest.raises(SynthesisMappingError, match="v3_source_reference_inventory_invalid"):
        map_generation_v2_to_registry_v3(
            generation_input,
            candidate,
            trusted_evidence=(evidence,),
            all_verified_source_references=all_refs,
        )
