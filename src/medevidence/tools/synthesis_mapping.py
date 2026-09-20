"""Pure Generation V2 to canonical validation-registry projection."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from medevidence.domain import sha256_digest

from .generation import (
    CandidateClaimClass,
    CandidateInferenceUse,
    GenerationEvidence,
    GenerationInput,
    reconstruct_generation_input,
)
from .generation_v2 import (
    CandidateClaimV2,
    GenerationCandidateV2,
    GenerationV2ContractError,
    generation_v2_candidate_bytes,
    limitation_texts,
    validate_generation_v2_candidate,
)
from .report_validation import (
    M3_SEMANTIC_EVALUATION_V2,
    M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
    M3_VALIDATION_CONFIGURATION_V2,
    M3_VALIDATION_CONFIGURATION_V3,
    M3_VALIDATION_CONFIGURATION_V4,
    CitationInput,
    CitationRelationship,
    ClaimInclusion,
    ClaimInput,
    ComparisonInput,
    ConflictInput,
    EvaluatorIdentityInput,
    EvidenceInput,
    NumericalContextInput,
    PlannedStage2SemanticInputV2,
    ValidationRegistryInput,
    _copy_comparison,
    _copy_conflict,
    _copy_evidence,
    _copy_registry,
    _source_semantics_allowed,
    canonical_citation_id,
    canonical_claim_id,
    canonical_evidence_id,
    canonical_semantic_input_digest,
)
from .semantic_evaluation import QWEN_SEMANTIC_V2_PROVIDER_METHOD


class SynthesisMappingError(ValueError):
    """A generated candidate cannot become an exact canonical registry."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MappedGenerationV2:
    candidate_hash: str
    registry: ValidationRegistryInput


def generation_evidence_from_trusted(value: EvidenceInput) -> GenerationEvidence:
    """Project exact canonical evidence into the provider-neutral generation graph."""

    try:
        exact = _copy_evidence(value)
        if exact != value or exact.evidence_id != canonical_evidence_id(exact):
            raise ValueError("trusted evidence reconstruction drift")
        classes = tuple(
            CandidateClaimClass(item.value)
            for item in sorted(exact.permitted_claim_classes, key=lambda item: item.value)
        )
        uses = tuple(
            CandidateInferenceUse(item.value)
            for item in sorted(exact.permitted_inference_uses, key=lambda item: item.value)
        )
        return GenerationEvidence.create(
            evidence_id=exact.evidence_id,
            run_id=exact.authorized_run_id,
            source=exact.source,
            source_record_id=exact.source_record_id,
            source_version=exact.source_version,
            snapshot_id=exact.snapshot_id,
            content_hash=exact.content_hash,
            locators=exact.locators,
            permitted_claim_classes=classes,
            permitted_inference_uses=uses,
            excerpt=exact.normalized_excerpt,
        )
    except (TypeError, ValueError) as error:
        raise SynthesisMappingError("trusted_evidence_generation_projection_invalid") from error


def _comparison_graph(
    generation_input: GenerationInput,
    comparisons: tuple[ComparisonInput, ...],
    conflicts: tuple[ConflictInput, ...],
) -> tuple[tuple[ComparisonInput, ...], tuple[ConflictInput, ...]]:
    if type(comparisons) is not tuple or type(conflicts) is not tuple:
        raise SynthesisMappingError("comparison_graph_wrong_type")
    try:
        exact_comparisons = tuple(_copy_comparison(item) for item in comparisons)
        exact_conflicts = tuple(_copy_conflict(item) for item in conflicts)
    except (TypeError, ValueError) as error:
        raise SynthesisMappingError("comparison_graph_invalid") from error
    if len(exact_comparisons) > 1 or len(exact_conflicts) > 1:
        raise SynthesisMappingError("comparison_graph_membership_ambiguous")
    if tuple((item.comparison_id, item.artifact_hash) for item in exact_comparisons) != tuple(
        (item.comparison_id, item.artifact_hash) for item in generation_input.comparisons
    ):
        raise SynthesisMappingError("generation_comparison_binding_drift")
    if tuple(
        (item.conflict_id, item.comparison_id, item.artifact_hash) for item in exact_conflicts
    ) != tuple(
        (item.conflict_id, item.comparison_id, item.artifact_hash)
        for item in generation_input.conflicts
    ):
        raise SynthesisMappingError("generation_conflict_binding_drift")
    if exact_comparisons != () and (
        len(exact_conflicts) != 1
        or exact_conflicts[0].comparison_id != exact_comparisons[0].comparison_id
    ):
        raise SynthesisMappingError("comparison_conflict_pair_incomplete")
    return exact_comparisons, exact_conflicts


def _claim_input(candidate: CandidateClaimV2) -> ClaimInput:
    context = candidate.numerical_context
    exact_context = (
        None
        if context is None
        else NumericalContextInput(*(getattr(context, item.name) for item in fields(context)))
    )
    provisional = ClaimInput(
        claim_id="claim:sha256:" + "0" * 64,
        source=candidate.source,
        qualitative_code=candidate.qualitative_code,
        statement=candidate.statement,
        claim_class=candidate.claim_class,
        inference_use=candidate.inference_use,
        citation_ids=(),
        presented_limitations=limitation_texts(
            candidate.source, candidate.presented_limitation_ids
        ),
        inclusion=ClaimInclusion.FORMAL,
        numerical_context=exact_context,
    )
    return ClaimInput(
        claim_id=canonical_claim_id(provisional),
        source=provisional.source,
        qualitative_code=provisional.qualitative_code,
        statement=provisional.statement,
        claim_class=provisional.claim_class,
        inference_use=provisional.inference_use,
        citation_ids=(),
        presented_limitations=provisional.presented_limitations,
        inclusion=provisional.inclusion,
        numerical_context=provisional.numerical_context,
    )


def map_generation_v2_to_registry(
    generation_input: GenerationInput,
    candidate: GenerationCandidateV2,
    *,
    trusted_evidence: tuple[EvidenceInput, ...],
    comparisons: tuple[ComparisonInput, ...] = (),
    conflicts: tuple[ConflictInput, ...] = (),
) -> MappedGenerationV2:
    """Project one validated candidate without changing its statement or evidence."""

    try:
        exact_input = reconstruct_generation_input(generation_input)
        exact_candidate = validate_generation_v2_candidate(
            exact_input, candidate, trusted_evidence=trusted_evidence
        )
    except (GenerationV2ContractError, TypeError, ValueError) as error:
        raise SynthesisMappingError("generation_v2_candidate_not_admitted") from error
    try:
        exact_evidence = tuple(_copy_evidence(item) for item in trusted_evidence)
    except (TypeError, ValueError) as error:
        raise SynthesisMappingError("trusted_evidence_not_canonical") from error
    if exact_evidence != trusted_evidence:
        raise SynthesisMappingError("trusted_evidence_reconstruction_drift")
    exact_comparisons, exact_conflicts = _comparison_graph(exact_input, comparisons, conflicts)
    contexts = {item.source: item.outcome for item in exact_input.source_contexts}
    evidence_by_id = {item.evidence_id: item for item in exact_evidence}
    generation_conflicts = {item.conflict_id: item for item in exact_input.conflicts}
    conflict_by_id = {item.conflict_id: item for item in exact_conflicts}
    comparison_by_id = {item.comparison_id: item for item in exact_comparisons}
    claims: list[ClaimInput] = []
    citations: list[CitationInput] = []
    plans: list[PlannedStage2SemanticInputV2] = []
    for candidate_claim in exact_candidate.claims:
        claim = _claim_input(candidate_claim)
        outcome = contexts.get(claim.source)
        if outcome is None:
            raise SynthesisMappingError("candidate_source_outcome_missing")
        if len(candidate_claim.conflict_ids) > 1:
            raise SynthesisMappingError("candidate_conflict_membership_ambiguous")
        comparison_id: str | None = None
        conflict_id: str | None = None
        if exact_conflicts and not candidate_claim.conflict_ids:
            raise SynthesisMappingError("candidate_comparability_omission_ambiguous")
        if candidate_claim.conflict_ids:
            conflict_id = candidate_claim.conflict_ids[0]
            conflict = conflict_by_id.get(conflict_id)
            comparison = None if conflict is None else comparison_by_id.get(conflict.comparison_id)
            if conflict is None or comparison is None:
                raise SynthesisMappingError("candidate_conflict_pair_missing")
            comparison_id = comparison.comparison_id
            generated_conflict = generation_conflicts[conflict_id]
            if set(item.evidence_id for item in candidate_claim.citations) - set(
                generated_conflict.evidence_ids
            ):
                raise SynthesisMappingError("candidate_conflict_evidence_binding_drift")
        claim_citations: list[CitationInput] = []
        for candidate_citation in candidate_claim.citations:
            evidence = evidence_by_id[candidate_citation.evidence_id]
            citation = CitationInput(
                citation_id="citation:sha256:" + "0" * 64,
                claim_id=claim.claim_id,
                evidence_id=evidence.evidence_id,
                relationship=CitationRelationship(candidate_citation.relationship),
                source_record_id=evidence.source_record_id,
                source_version=evidence.source_version,
                snapshot_id=evidence.snapshot_id,
                content_hash=evidence.content_hash,
                locator_ref=candidate_citation.locator_ref,
                execution_status=outcome.execution_status,
                coverage_status=outcome.coverage_status,
                result_status=outcome.result_status,
            )
            citation = CitationInput(
                citation_id=canonical_citation_id(citation),
                claim_id=citation.claim_id,
                evidence_id=citation.evidence_id,
                relationship=citation.relationship,
                source_record_id=citation.source_record_id,
                source_version=citation.source_version,
                snapshot_id=citation.snapshot_id,
                content_hash=citation.content_hash,
                locator_ref=citation.locator_ref,
                execution_status=citation.execution_status,
                coverage_status=citation.coverage_status,
                result_status=citation.result_status,
            )
            claim_citations.append(citation)
            plans.append(
                PlannedStage2SemanticInputV2(
                    citation_id=citation.citation_id,
                    input_digest=canonical_semantic_input_digest(
                        exact_input.run_id, claim, citation, evidence
                    ),
                    method=M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2,
                    version=M3_SEMANTIC_EVALUATION_V2,
                    comparison_id=comparison_id,
                    conflict_id=conflict_id,
                )
            )
        claim = ClaimInput(
            claim_id=claim.claim_id,
            source=claim.source,
            qualitative_code=claim.qualitative_code,
            statement=claim.statement,
            claim_class=claim.claim_class,
            inference_use=claim.inference_use,
            citation_ids=tuple(item.citation_id for item in claim_citations),
            presented_limitations=claim.presented_limitations,
            inclusion=claim.inclusion,
            numerical_context=claim.numerical_context,
        )
        claims.append(claim)
        citations.extend(claim_citations)
    if len({item.claim_id for item in claims}) != len(claims):
        raise SynthesisMappingError("candidate_canonical_claim_duplicate")
    registry = ValidationRegistryInput(
        run_id=exact_input.run_id,
        scope_id=exact_input.scope_id,
        claims=tuple(claims),
        citations=tuple(citations),
        evidence=exact_evidence,
        semantic_expectations=tuple(plans),
        evaluator_identity=EvaluatorIdentityInput(
            M3_STAGE2_SEMANTIC_PROVIDER_METHOD_V2, M3_SEMANTIC_EVALUATION_V2
        ),
        comparisons=exact_comparisons,
        conflicts=exact_conflicts,
        resolutions=(),
        configuration_version=M3_VALIDATION_CONFIGURATION_V2,
    )
    return MappedGenerationV2(
        candidate_hash=sha256_digest(generation_v2_candidate_bytes(exact_candidate)),
        registry=registry,
    )


def map_generation_v2_to_registry_v3(
    generation_input: GenerationInput,
    candidate: GenerationCandidateV2,
    *,
    trusted_evidence: tuple[EvidenceInput, ...],
    comparisons: tuple[ComparisonInput, ...] = (),
    conflicts: tuple[ConflictInput, ...] = (),
    all_verified_source_references: tuple[EvidenceInput, ...] | None = None,
) -> MappedGenerationV2:
    """Admit optional registry-only metadata without exposing it to generation."""

    all_references = trusted_evidence
    if all_verified_source_references is not None:
        try:
            exact_input = reconstruct_generation_input(generation_input)
            if type(all_verified_source_references) is not tuple:
                raise ValueError("source references must be an exact tuple")
            all_references = tuple(_copy_evidence(item) for item in all_verified_source_references)
            if all_references != all_verified_source_references:
                raise ValueError("source references changed during reconstruction")
            contexts = {item.source for item in exact_input.source_contexts}
            if len(contexts) != len(exact_input.source_contexts):
                raise ValueError("source contexts are ambiguous")
            identities: set[str] = set()
            authorities: set[tuple[object, ...]] = set()
            claimable: list[EvidenceInput] = []
            for evidence in all_references:
                if (
                    evidence.evidence_id != canonical_evidence_id(evidence)
                    or evidence.authorized_run_id != exact_input.run_id
                    or evidence.source not in contexts
                    or len(evidence.locators) != 1
                ):
                    raise ValueError("source reference is foreign or noncanonical")
                authority = (
                    evidence.source,
                    evidence.snapshot_id,
                    evidence.content_hash,
                    evidence.locators[0],
                )
                if evidence.evidence_id in identities or authority in authorities:
                    raise ValueError("source reference identity is duplicated")
                identities.add(evidence.evidence_id)
                authorities.add(authority)
                classes = evidence.permitted_claim_classes
                uses = evidence.permitted_inference_uses
                if classes and uses:
                    if not any(
                        _source_semantics_allowed(evidence.source, claim_class, use)
                        for claim_class in classes
                        for use in uses
                    ):
                        raise ValueError("source permissions have no admitted pair")
                    claimable.append(evidence)
                elif classes or uses or evidence.numerical_facts:
                    raise ValueError("metadata source reference grants claim authority")
            if tuple(claimable) != trusted_evidence:
                raise ValueError("generation evidence is not the exact claimable subset")
        except (TypeError, ValueError) as error:
            raise SynthesisMappingError("v3_source_reference_inventory_invalid") from error

    mapped = map_generation_v2_to_registry(
        generation_input,
        candidate,
        trusted_evidence=trusted_evidence,
        comparisons=comparisons,
        conflicts=conflicts,
    )
    registry = _copy_registry(
        replace(
            mapped.registry,
            evidence=all_references,
            configuration_version=M3_VALIDATION_CONFIGURATION_V3,
        )
    )
    return MappedGenerationV2(candidate_hash=mapped.candidate_hash, registry=registry)


def map_generation_v2_to_registry_v4(
    generation_input: GenerationInput,
    candidate: GenerationCandidateV2,
    *,
    trusted_evidence: tuple[EvidenceInput, ...],
    comparisons: tuple[ComparisonInput, ...] = (),
    conflicts: tuple[ConflictInput, ...] = (),
    all_verified_source_references: tuple[EvidenceInput, ...] | None = None,
) -> MappedGenerationV2:
    """Preserve V3 source authority while selecting the fixed Qwen semantic profile."""

    mapped = map_generation_v2_to_registry_v3(
        generation_input,
        candidate,
        trusted_evidence=trusted_evidence,
        comparisons=comparisons,
        conflicts=conflicts,
        all_verified_source_references=all_verified_source_references,
    )
    registry = _copy_registry(
        replace(
            mapped.registry,
            semantic_expectations=tuple(
                replace(item, method=QWEN_SEMANTIC_V2_PROVIDER_METHOD)
                for item in mapped.registry.semantic_expectations
            ),
            evaluator_identity=EvaluatorIdentityInput(
                QWEN_SEMANTIC_V2_PROVIDER_METHOD, M3_SEMANTIC_EVALUATION_V2
            ),
            configuration_version=M3_VALIDATION_CONFIGURATION_V4,
        )
    )
    return MappedGenerationV2(candidate_hash=mapped.candidate_hash, registry=registry)
