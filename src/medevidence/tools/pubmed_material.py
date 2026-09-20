"""Deterministic local abstract extracts; persistence must still authenticate the source."""

from dataclasses import dataclass, replace
from enum import StrEnum

from pydantic import TypeAdapter

from medevidence.domain import (
    Citation,
    ClaimUseContext,
    EvidenceClaim,
    PublicationRecord,
    ResearchScope,
    SourceType,
)
from medevidence.domain.catalogs import LOCAL_RESEARCH_CATALOG_HASH
from medevidence.domain.identifiers import RunId

from .contracts import ResolvedConceptCatalog
from .ports import PersistedPublicationBinding
from .pubmed import build_pubmed_query
from .report_validation import ClaimClass, EvidenceInput, InferenceUse, canonical_evidence_id
from .research import _eligible_use_context, _occurrences, _smallest_term_span

PUBMED_MATERIAL_POLICY = "m3.pubmed.abstract-span.v1"
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class PubMedMaterialExclusion(StrEnum):
    ABSTRACT_MISSING = "abstract_missing"
    STATUS_NOT_ELIGIBLE = "status_not_eligible"
    TERMS_NOT_PRESENT = "terms_not_present"
    EXCERPT_EXCEEDS_BOUND = "excerpt_exceeds_bound"
    SELECTION_BUDGET_EXCEEDED = "selection_budget_exceeded"


@dataclass(frozen=True, slots=True)
class PubMedMaterialSelection:
    """One source-derived candidate or an explicit material exclusion, never a verification seal."""

    evidence: EvidenceInput | None
    citation: Citation | None
    exclusion: PubMedMaterialExclusion | None
    limitations: tuple[str, ...]
    source_reference: EvidenceInput


def select_pubmed_material(
    *,
    run_id: str,
    scope: ResearchScope,
    catalog: ResolvedConceptCatalog,
    publication: PublicationRecord,
    binding: PersistedPublicationBinding,
) -> PubMedMaterialSelection:
    """Select one exact attributed span with bounded lexical work and status-limited use."""
    run_id = TypeAdapter(RunId).validate_python(run_id, strict=True)
    scope = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
    catalog = ResolvedConceptCatalog.model_validate(catalog.model_dump(mode="python"), strict=True)
    publication = PublicationRecord.model_validate(
        publication.model_dump(mode="python"), strict=True
    )
    binding = PersistedPublicationBinding.model_validate(
        binding.model_dump(mode="python"), strict=True
    )
    if (
        catalog.catalog_version != "m3.local-research-input.v1"
        or catalog.catalog_content_hash != LOCAL_RESEARCH_CATALOG_HASH
        or SourceType.PUBMED not in scope.selected_sources
    ):
        raise ValueError("PubMed local material requires its admitted source and catalog")
    build_pubmed_query(scope, catalog)
    if (
        publication.pmid != binding.pmid
        or publication.publication_version_id != binding.publication_version_id
        or publication.content_hash != binding.publication_artifact_id
        or publication.provenance.snapshot_id != binding.snapshot_id
        or publication.provenance.artifact_ids != binding.artifact_ids
    ):
        raise ValueError("PubMed material differs from its persisted source binding")

    def excluded(reason: PubMedMaterialExclusion) -> PubMedMaterialSelection:
        reference = EvidenceInput(
            evidence_id="pending",
            authorized_run_id=run_id,
            source=SourceType.PUBMED,
            source_record_id=publication.pmid,
            source_version=publication.publication_version_id,
            snapshot_id=binding.snapshot_id,
            content_hash=publication.content_hash,
            locators=(
                f"m3.pubmed.record-metadata.v1/{publication.publication_version_id}/"
                f"normalized-title/0:{len(publication.title)}",
            ),
            permitted_claim_classes=frozenset(),
            permitted_inference_uses=frozenset(),
            normalized_excerpt=publication.title,
            numerical_facts=(),
        )
        reference = replace(reference, evidence_id=canonical_evidence_id(reference))
        return PubMedMaterialSelection(
            evidence=None,
            citation=None,
            exclusion=reason,
            limitations=(
                f"PubMed PMID {publication.pmid}: abstract material excluded ({reason.value}).",
                *(
                    f"PubMed PMID {publication.pmid}: {warning}."
                    for warning in sorted(
                        {
                            *publication.publication_status.warning_codes,
                            *publication.provenance.source_outcome.warning_codes,
                        }
                    )
                ),
            ),
            source_reference=reference,
        )

    abstract = publication.canonical_abstract
    if abstract is None or not abstract.strip():
        return excluded(PubMedMaterialExclusion.ABSTRACT_MISSING)
    use = _eligible_use_context(publication)
    if use is None:
        return excluded(PubMedMaterialExclusion.STATUS_NOT_ELIGIBLE)
    if len(abstract) > 262_144:
        return excluded(PubMedMaterialExclusion.SELECTION_BUDGET_EXCEEDED)
    # ASCII translation preserves every Unicode code-point offset in the original.
    lowered = abstract.translate(_ASCII_LOWER)
    drugs = tuple(item.preferred_term.translate(_ASCII_LOWER) for item in catalog.drugs)
    events = tuple(
        item.preferred_term.translate(_ASCII_LOWER) for item in catalog.adverse_reactions
    )
    if any(not term.isascii() for term in (*drugs, *events)):
        raise ValueError("local material terms must use the admitted ASCII vocabulary")
    if sum(len(_occurrences(lowered, term)) for term in (*drugs, *events)) > 512:
        return excluded(PubMedMaterialExclusion.SELECTION_BUDGET_EXCEEDED)
    span = _smallest_term_span(lowered, drugs, events)
    if span is None:
        return excluded(PubMedMaterialExclusion.TERMS_NOT_PRESENT)
    if span[1] - span[0] > 4096:
        return excluded(PubMedMaterialExclusion.EXCERPT_EXCEEDS_BOUND)
    citation = Citation.from_publication(publication, start_offset=span[0], end_offset=span[1])
    # Reuse the existing domain status/use gate; this is an extract, not a medical claim.
    extract = EvidenceClaim.from_citation(
        scope_id=scope.scope_id, citation=citation, publication=publication, use_context=use
    )
    locator = (
        f"{PUBMED_MATERIAL_POLICY}/{publication.publication_version_id}/"
        f"{publication.canonical_abstract_sha256}/{span[0]}:{span[1]}"
    )
    limited = use is ClaimUseContext.SUPPORT_LIMITED
    classes = frozenset((ClaimClass.METHODOLOGICAL_OR_LIMITATION,))
    uses = frozenset((InferenceUse.METHODOLOGICAL_LIMITATION,))
    if not limited:
        classes |= frozenset((ClaimClass.DESCRIPTIVE,))
        uses |= frozenset((InferenceUse.DESCRIPTIVE,))
    evidence = EvidenceInput(
        evidence_id="pending",
        authorized_run_id=run_id,
        source=SourceType.PUBMED,
        source_record_id=publication.pmid,
        source_version=publication.publication_version_id,
        snapshot_id=binding.snapshot_id,
        content_hash=publication.content_hash,
        locators=(locator,),
        permitted_claim_classes=classes,
        permitted_inference_uses=uses,
        normalized_excerpt=citation.exact_quote,
        numerical_facts=(),
    )
    evidence = replace(evidence, evidence_id=canonical_evidence_id(evidence))
    warnings = sorted(
        {
            *extract.limitations,
            *extract.publication_warning_references,
            *publication.provenance.source_outcome.warning_codes,
        }
    )
    limitations = (
        "PubMed material is one attributed abstract extract; "
        "full-text evidence and clinical conclusions are outside this material's scope.",
        *(f"PubMed PMID {publication.pmid}: {warning}." for warning in warnings),
    )
    return PubMedMaterialSelection(evidence, citation, None, limitations, evidence)
