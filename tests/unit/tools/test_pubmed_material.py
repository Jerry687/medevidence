"""Exact local abstract selection and conservative source-status permissions."""

from dataclasses import replace

import pytest
from tests.unit.tools.test_pubmed_local_bounds import LocalCatalog
from tests.unit.tools.test_research import (
    RUN_ID,
    _corrected_context_only_status,
    _outcome,
    _publication,
    _scope,
)

from medevidence.domain import (
    CoverageStatus,
    PublicationRecord,
    PublicationStatusValue,
    ResultStatus,
)
from medevidence.tools.ports import PersistedPublicationBinding, PersistedPublicationLineageEdge
from medevidence.tools.pubmed_material import (
    PubMedMaterialExclusion,
    select_pubmed_material,
)
from medevidence.tools.report_validation import ClaimClass, InferenceUse, _copy_evidence
from medevidence.tools.synthesis_mapping import generation_evidence_from_trusted


def material_case(
    abstract="😀 SEMAGLUTIDE distant gastrointestinal. semaglutide gastrointestinal",
    status=PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
    context_only=False,
    coverage=CoverageStatus.COMPLETE,
):
    publication = _publication(
        _outcome(result=ResultStatus.MATCHES, count=1, coverage=coverage),
        abstract=abstract,
        status=status,
    )
    if context_only:
        fields = {
            name: getattr(publication, name)
            for name in (
                "pmid",
                "doi",
                "pmcid",
                "title",
                "abstract_sections",
                "authors",
                "journal",
                "publication_types",
                "publication_date",
                "indexing_status",
                "provenance",
                "parse_warnings",
            )
        }
        publication = PublicationRecord.create(
            **fields, publication_status=_corrected_context_only_status()
        )
    snapshot = "sha256:" + "c" * 64
    binding = PersistedPublicationBinding(
        pmid=publication.pmid,
        publication_version_id=publication.publication_version_id,
        publication_artifact_id=publication.content_hash,
        snapshot_id=snapshot,
        manifest_id=snapshot,
        artifact_ids=tuple(sorted((publication.content_hash, snapshot))),
        lineage_edges=(
            PersistedPublicationLineageEdge(
                parent_artifact_id=publication.content_hash,
                child_artifact_id=snapshot,
            ),
        ),
    )
    provenance = publication.provenance.model_copy(
        update={
            "snapshot_id": snapshot,
            "artifact_ids": binding.artifact_ids,
            "transformation_lineage": (publication.content_hash, snapshot),
        }
    )
    publication = PublicationRecord.model_validate(
        {
            **publication.model_dump(mode="python"),
            "provenance": provenance,
        }
    )
    return publication, binding


def select(publication, binding, *, run_id=RUN_ID):
    scope = _scope()
    return select_pubmed_material(
        run_id=run_id,
        scope=scope,
        catalog=LocalCatalog(scope).resolve(scope.scope_id),
        publication=publication,
        binding=binding,
    )


def test_candidate_preserves_exact_unicode_offsets_and_source_identity():
    publication, binding = material_case()
    selection = select(publication, binding)
    assert selection.exclusion is None
    evidence, citation = selection.evidence, selection.citation
    assert evidence is not None and citation is not None
    assert selection.source_reference == evidence
    assert evidence.normalized_excerpt == "semaglutide gastrointestinal"
    assert (
        evidence.normalized_excerpt
        == publication.canonical_abstract[citation.start_offset : citation.end_offset]
    )
    assert evidence.source_version == publication.publication_version_id
    assert evidence.content_hash == publication.content_hash
    assert str(citation.start_offset) + ":" + str(citation.end_offset) in evidence.locators[0]
    assert publication.canonical_abstract_sha256 in evidence.locators[0]
    assert _copy_evidence(evidence) == evidence
    assert evidence.numerical_facts == ()
    assert ClaimClass.CAUSAL not in evidence.permitted_claim_classes
    assert InferenceUse.CLINICAL not in evidence.permitted_inference_uses
    assert select(publication, binding) == selection
    other = select(publication, binding, run_id="run:00000000-0000-4000-8000-000000000003")
    assert other.evidence.evidence_id != evidence.evidence_id


def test_ascii_case_conversion_does_not_shift_unicode_positions():
    publication, binding = material_case("İ 😀 SEMAGLUTIDE GASTROINTESTINAL")
    selection = select(publication, binding)
    assert selection.evidence.normalized_excerpt == "SEMAGLUTIDE GASTROINTESTINAL"
    assert selection.citation.start_offset == len("İ 😀 ")


@pytest.mark.parametrize(
    "status,context_only",
    (
        (PublicationStatusValue.RETRACTED, False),
        (PublicationStatusValue.CORRECTED, True),
    ),
)
def test_ineligible_publication_is_visible_exclusion_not_empty_source(status, context_only):
    publication, binding = material_case(status=status, context_only=context_only)
    result = select(publication, binding)
    assert result.evidence is None
    assert result.exclusion is PubMedMaterialExclusion.STATUS_NOT_ELIGIBLE
    assert publication.provenance.source_outcome.valid_result_count == 1
    assert publication.pmid in result.limitations[0]
    for warning in publication.publication_status.warning_codes:
        assert any(warning in limitation for limitation in result.limitations)
    reference = result.source_reference
    assert reference.normalized_excerpt == publication.title
    assert reference.source_version == publication.publication_version_id
    assert reference.snapshot_id == binding.snapshot_id
    assert reference.content_hash == publication.content_hash
    assert not reference.permitted_claim_classes
    assert not reference.permitted_inference_uses
    assert reference.numerical_facts == ()
    assert _copy_evidence(reference) == reference
    with pytest.raises(ValueError):
        generation_evidence_from_trusted(reference)


def test_resolved_current_corrected_content_remains_eligible():
    result = select(*material_case(status=PublicationStatusValue.CORRECTED))
    assert result.exclusion is None
    assert result.evidence is not None


@pytest.mark.parametrize(
    "status",
    (
        PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
        PublicationStatusValue.EXPRESSION_OF_CONCERN,
    ),
)
def test_uncertain_status_never_gains_descriptive_or_clinical_permission(status):
    publication, binding = material_case(status=status)
    result = select(publication, binding)
    assert result.evidence.permitted_claim_classes == frozenset(
        (ClaimClass.METHODOLOGICAL_OR_LIMITATION,)
    )
    assert result.evidence.permitted_inference_uses == frozenset(
        (InferenceUse.METHODOLOGICAL_LIMITATION,)
    )
    assert len(result.limitations) > 1
    for warning in publication.publication_status.warning_codes:
        assert any(warning in limitation for limitation in result.limitations)


@pytest.mark.parametrize(
    "abstract,reason",
    (
        (None, PubMedMaterialExclusion.ABSTRACT_MISSING),
        ("Unrelated synthetic abstract.", PubMedMaterialExclusion.TERMS_NOT_PRESENT),
        (
            "semaglutide" + "x" * 4096 + "gastrointestinal",
            PubMedMaterialExclusion.EXCERPT_EXCEEDS_BOUND,
        ),
        (
            "semaglutide " * 513 + "gastrointestinal",
            PubMedMaterialExclusion.SELECTION_BUDGET_EXCEEDED,
        ),
    ),
)
def test_missing_or_over_bound_material_is_not_silently_truncated(abstract, reason):
    publication, binding = material_case(abstract)
    result = select(publication, binding)
    assert result.exclusion is reason
    assert result.evidence is None
    assert result.source_reference.normalized_excerpt == publication.title
    assert not result.source_reference.permitted_claim_classes


def test_cross_snapshot_and_recomputed_text_substitution_rejected():
    publication, binding = material_case()
    with pytest.raises(ValueError):
        select(publication, binding.model_copy(update={"snapshot_id": "sha256:" + "d" * 64}))
    evidence = select(publication, binding).evidence
    with pytest.raises(ValueError):
        _copy_evidence(replace(evidence, normalized_excerpt="fabricated"))


def test_exact_selection_work_bound_keeps_original_text():
    publication, binding = material_case("semaglutide " * 511 + "gastrointestinal")
    selection = select(publication, binding)
    assert selection.evidence is not None
    assert selection.evidence.normalized_excerpt == "semaglutide gastrointestinal"


def test_large_original_is_excluded_instead_of_chopped_into_a_fake_complete_abstract():
    publication, binding = material_case("x" * 262_144 + " semaglutide gastrointestinal")
    selection = select(publication, binding)
    assert selection.exclusion is PubMedMaterialExclusion.SELECTION_BUDGET_EXCEEDED
    assert len(publication.canonical_abstract) > 262_144


def test_partial_source_warning_survives_material_selection():
    selection = select(*material_case(coverage=CoverageStatus.PARTIAL))
    assert selection.evidence is not None
    assert any("source_coverage_incomplete" in item for item in selection.limitations)
