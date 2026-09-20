"""Generation V2 exact claim/citation contract and pure canonical mapping."""

from __future__ import annotations

import json
from dataclasses import fields, replace

import pytest
from pydantic import ValidationError
from tests.unit.tools import test_generation as v1
from tests.unit.tools import test_report_validation as report

from medevidence.domain import ResultStatus, SourceType, canonical_json
from medevidence.tools.deepseek_generation import DEEPSEEK_GENERATION_CONFIGURATION_HASH
from medevidence.tools.generation import (
    GENERATION_PROMPT_HASH,
    GENERATION_SCHEMA_HASH,
    GenerationComparison,
    GenerationConflict,
    GenerationInput,
)
from medevidence.tools.generation_v2 import (
    GENERATION_V2_CONFIG_HASH,
    GENERATION_V2_PROMPT_HASH,
    GENERATION_V2_SCHEMA_HASH,
    CandidateCitationV2,
    CandidateClaimV2,
    GenerationCandidateV2,
    GenerationV2ContractError,
    generation_v2_candidate_bytes,
    generation_v2_response_schema,
    parse_generation_v2_candidate,
    validate_generation_v2_candidate,
)
from medevidence.tools.report_validation import (
    COMPARABILITY_DIMENSIONS,
    CitationReferenceInput,
    ClaimClass,
    ClaimReferenceInput,
    ComparableFindingRelation,
    ComparisonInput,
    ConflictInput,
    ConflictOutcome,
    DimensionInput,
    EvidenceInput,
    InferenceUse,
    NumericalContextInput,
    NumericalFactInput,
    QualitativeCode,
    ValidationMode,
    _comparison_hash,
    _conflict_hash,
    _copy_registry,
    _qualitative_form,
    canonical_evidence_id,
    canonical_numerical_text,
    canonical_validate_report,
)
from medevidence.tools.synthesis_mapping import (
    SynthesisMappingError,
    generation_evidence_from_trusted,
    map_generation_v2_to_registry,
)


def _trusted(
    *,
    index: int = 0,
    source: SourceType = SourceType.PUBMED,
    context: NumericalContextInput | None = None,
) -> EvidenceInput:
    locator = f"locator:{source.value}:{index:03d}"
    facts: tuple[NumericalFactInput, ...] = ()
    excerpt = "Exact bounded evidence excerpt."
    if context is not None:
        fact = NumericalFactInput(
            locator,
            "",
            *(getattr(context, item.name) for item in fields(context)),
        )
        fact = replace(fact, exact_text=canonical_numerical_text(fact))
        facts = (fact,)
        excerpt = fact.exact_text
    value = report._evidence(source, index=index, facts=facts, excerpt=excerpt)
    return replace(value, evidence_id=canonical_evidence_id(value))


def _input(*evidence: EvidenceInput) -> GenerationInput:
    source = evidence[0].source
    assert all(item.source is source for item in evidence)
    context = v1.source_context(source=source)
    return GenerationInput(
        run_id=report.RUN_ID,
        scope_id=report._scope(source).scope_id,
        research_question="What does the exact bounded evidence establish?",
        selected_sources=(source,),
        source_plan=(v1.plan(source),),
        source_contexts=(context,),
        evidence=tuple(generation_evidence_from_trusted(item) for item in evidence),
        comparisons=(),
        conflicts=(),
    )


def _qualitative_claim(evidence: EvidenceInput) -> CandidateClaimV2:
    code = {
        SourceType.PUBMED: QualitativeCode.PUBMED_DESCRIPTIVE,
        SourceType.DAILYMED: QualitativeCode.DAILYMED_DESCRIPTIVE,
        SourceType.FAERS: QualitativeCode.FAERS_DESCRIPTIVE_CONTEXT,
        SourceType.CADEC: QualitativeCode.CADEC_AUXILIARY_CONTEXT,
    }[evidence.source]
    source, claim_class, use, statement = _qualitative_form(code)
    limitations = {
        SourceType.FAERS: ("faers_mandatory_limitations",),
        SourceType.CADEC: ("cadec_mandatory_limitations",),
    }.get(source, ())
    return CandidateClaimV2(
        ordinal=1,
        source=source,
        statement=statement,
        claim_class=claim_class,
        inference_use=use,
        qualitative_code=code,
        numerical_context=None,
        citations=(
            CandidateCitationV2(
                evidence_id=evidence.evidence_id,
                locator_ref=evidence.locators[0],
                relationship="supports",
            ),
        ),
        presented_limitation_ids=limitations,
        conflict_ids=(),
    )


def _candidate(value: GenerationInput, claim: CandidateClaimV2) -> GenerationCandidateV2:
    return GenerationCandidateV2(
        source_context_ids=tuple(item.context_id for item in value.source_contexts),
        visible_comparison_ids=tuple(item.comparison_id for item in value.comparisons),
        visible_conflict_ids=tuple(item.conflict_id for item in value.conflicts),
        claims=(claim,),
    )


def test_qualitative_candidate_maps_without_statement_or_locator_rewrite() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    admitted = validate_generation_v2_candidate(
        generation_input, candidate, trusted_evidence=(evidence,)
    )
    mapped = map_generation_v2_to_registry(generation_input, admitted, trusted_evidence=(evidence,))
    claim = mapped.registry.claims[0]
    citation = mapped.registry.citations[0]
    assert claim.statement == candidate.claims[0].statement
    assert claim.qualitative_code is candidate.claims[0].qualitative_code
    assert citation.locator_ref == candidate.claims[0].citations[0].locator_ref
    assert mapped.registry.semantic_expectations[0].citation_id == citation.citation_id
    assert _copy_registry(mapped.registry) == mapped.registry
    assert mapped.candidate_hash.startswith("sha256:")
    base = report._material_request()
    synthesis = replace(
        base.synthesis,
        claims=(ClaimReferenceInput(claim.claim_id),),
        citations=(
            CitationReferenceInput(citation.citation_id, claim.claim_id, evidence.evidence_id),
        ),
    )
    request = report._rebind(
        replace(
            base,
            tasks=(
                report._task(
                    SourceType.PUBMED,
                    report._outcome(SourceType.PUBMED, result=ResultStatus.MATCHES),
                    (evidence,),
                ),
            ),
            synthesis=synthesis,
            registry=mapped.registry,
        )
    )
    preflight = canonical_validate_report(request, mode=ValidationMode.PREPARE_STAGE1)
    assert preflight.stage1_receipt is not None


def test_exact_numeric_context_maps_and_requires_authoritative_fact() -> None:
    context = NumericalContextInput(
        "7", "count", "population", "none", "window", "bounded population"
    )
    evidence = _trusted(context=context)
    generation_input = _input(evidence)
    claim = CandidateClaimV2(
        ordinal=1,
        source=SourceType.PUBMED,
        statement=canonical_numerical_text(context),
        claim_class=ClaimClass.DESCRIPTIVE,
        inference_use=InferenceUse.DESCRIPTIVE,
        qualitative_code=None,
        numerical_context=context,
        citations=(
            CandidateCitationV2(
                evidence_id=evidence.evidence_id,
                locator_ref=evidence.locators[0],
                relationship="supports",
            ),
        ),
        presented_limitation_ids=(),
        conflict_ids=(),
    )
    candidate = _candidate(generation_input, claim)
    assert parse_generation_v2_candidate(generation_v2_candidate_bytes(candidate)) == candidate
    mapped = map_generation_v2_to_registry(
        generation_input, candidate, trusted_evidence=(evidence,)
    )
    assert mapped.registry.claims[0].numerical_context == context
    without_fact = replace(evidence, numerical_facts=())
    without_fact = replace(without_fact, evidence_id=canonical_evidence_id(without_fact))
    without_fact_input = _input(without_fact)
    without_fact_claim = claim.model_copy(
        update={
            "citations": (
                claim.citations[0].model_copy(update={"evidence_id": without_fact.evidence_id}),
            )
        }
    )
    with pytest.raises(GenerationV2ContractError, match="numeric_fact_not_supplied"):
        validate_generation_v2_candidate(
            without_fact_input,
            _candidate(without_fact_input, without_fact_claim),
            trusted_evidence=(without_fact,),
        )


def test_modified_statement_cross_source_and_locator_fail_closed() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    valid = _qualitative_claim(evidence)
    with pytest.raises(ValidationError, match="canonical code form"):
        CandidateClaimV2.model_validate(
            {**valid.model_dump(mode="python"), "statement": valid.statement + " modified"}
        )
    constructed = CandidateClaimV2.model_construct(
        **{**valid.model_dump(mode="python"), "statement": valid.statement + " modified"}
    )
    with pytest.raises(GenerationV2ContractError, match="candidate_invalid"):
        validate_generation_v2_candidate(
            generation_input,
            GenerationCandidateV2.model_construct(
                source_context_ids=tuple(
                    item.context_id for item in generation_input.source_contexts
                ),
                visible_comparison_ids=(),
                visible_conflict_ids=(),
                claims=(constructed,),
            ),
            trusted_evidence=(evidence,),
        )
    wrong_source = _trusted(source=SourceType.DAILYMED)
    daily = _qualitative_claim(wrong_source)
    cross = daily.model_copy(
        update={
            "citations": (
                daily.citations[0].model_copy(update={"evidence_id": evidence.evidence_id}),
            )
        }
    )
    cross_input = GenerationInput(
        run_id=report.RUN_ID,
        scope_id=generation_input.scope_id,
        research_question=generation_input.research_question,
        selected_sources=(SourceType.DAILYMED, SourceType.PUBMED),
        source_plan=(v1.plan(SourceType.DAILYMED), v1.plan(SourceType.PUBMED)),
        source_contexts=(
            v1.source_context(source=SourceType.DAILYMED),
            v1.source_context(source=SourceType.PUBMED),
        ),
        evidence=(
            generation_evidence_from_trusted(wrong_source),
            generation_evidence_from_trusted(evidence),
        ),
        comparisons=(),
        conflicts=(),
    )
    with pytest.raises(GenerationV2ContractError, match="citation_binding_drift"):
        validate_generation_v2_candidate(
            cross_input,
            _candidate(cross_input, cross),
            trusted_evidence=(wrong_source, evidence),
        )
    wrong_locator = valid.model_copy(
        update={
            "citations": (valid.citations[0].model_copy(update={"locator_ref": "locator:foreign"}),)
        }
    )
    with pytest.raises(GenerationV2ContractError, match="citation_binding_drift"):
        validate_generation_v2_candidate(
            generation_input,
            _candidate(generation_input, wrong_locator),
            trusted_evidence=(evidence,),
        )


def test_unsupported_numeric_forms_and_trusted_inventory_reject() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    unsafe = replace(
        evidence,
        permitted_inference_uses=frozenset(
            {*evidence.permitted_inference_uses, InferenceUse.INCIDENCE}
        ),
    )
    unsafe = replace(unsafe, evidence_id=canonical_evidence_id(unsafe))
    with pytest.raises(SynthesisMappingError, match="generation_projection_invalid"):
        generation_evidence_from_trusted(unsafe)
    malformed_fact = NumericalFactInput(
        evidence.locators[0],
        "forged text",
        "7",
        "count",
        "population",
        "none",
        "window",
        "bounded population",
    )
    malformed = replace(
        evidence,
        normalized_excerpt="forged text",
        numerical_facts=(malformed_fact,),
    )
    malformed = replace(malformed, evidence_id=canonical_evidence_id(malformed))
    with pytest.raises(SynthesisMappingError, match="generation_projection_invalid"):
        generation_evidence_from_trusted(malformed)
    context = NumericalContextInput("1", "count", "none", "none", "window", "corpus")
    with pytest.raises(ValidationError, match="CADEC numeric"):
        CandidateClaimV2(
            ordinal=1,
            source=SourceType.CADEC,
            statement=canonical_numerical_text(context),
            claim_class=ClaimClass.METHODOLOGICAL_OR_LIMITATION,
            inference_use=InferenceUse.METHODOLOGICAL_LIMITATION,
            qualitative_code=None,
            numerical_context=context,
            citations=(
                CandidateCitationV2(
                    evidence_id=evidence.evidence_id,
                    locator_ref=evidence.locators[0],
                    relationship="supports",
                ),
            ),
            presented_limitation_ids=("cadec_mandatory_limitations",),
            conflict_ids=(),
        )
    with pytest.raises(ValidationError, match="bounded count semantics"):
        CandidateClaimV2(
            ordinal=1,
            source=SourceType.FAERS,
            statement=(
                "FAERS bounded spontaneous-report count: "
                + canonical_numerical_text(context)
                + " "
                + report.FAERS_MANDATORY_LIMITATIONS[1]
            ),
            claim_class=ClaimClass.DESCRIPTIVE,
            inference_use=InferenceUse.DESCRIPTIVE,
            qualitative_code=None,
            numerical_context=context,
            citations=(
                CandidateCitationV2(
                    evidence_id=evidence.evidence_id,
                    locator_ref=evidence.locators[0],
                    relationship="supports",
                ),
            ),
            presented_limitation_ids=("faers_mandatory_limitations",),
            conflict_ids=(),
        )
    for invalid in (replace(context, denominator=""), replace(context, unit="x" * 513)):
        with pytest.raises(ValidationError, match="bounded and nonblank"):
            CandidateClaimV2(
                ordinal=1,
                source=SourceType.PUBMED,
                statement=canonical_numerical_text(invalid),
                claim_class=ClaimClass.DESCRIPTIVE,
                inference_use=InferenceUse.DESCRIPTIVE,
                qualitative_code=None,
                numerical_context=invalid,
                citations=(
                    CandidateCitationV2(
                        evidence_id=evidence.evidence_id,
                        locator_ref=evidence.locators[0],
                        relationship="supports",
                    ),
                ),
                presented_limitation_ids=(),
                conflict_ids=(),
            )
    foreign = replace(evidence, source_version="version:foreign")
    foreign = replace(foreign, evidence_id=canonical_evidence_id(foreign))
    with pytest.raises(GenerationV2ContractError, match="inventory_drift"):
        validate_generation_v2_candidate(
            generation_input,
            _candidate(generation_input, _qualitative_claim(evidence)),
            trusted_evidence=(foreign,),
        )


def _pair(evidence_ids: tuple[str, str]):
    comparison = ComparisonInput(
        comparison_id="comparison:sha256:" + "a" * 64,
        artifact_hash="sha256:" + "0" * 64,
        dimensions=tuple(
            DimensionInput(item, True, "same", "same") for item in COMPARABILITY_DIMENSIONS
        ),
        relation=ComparableFindingRelation.CONSISTENT,
        source_unavailable=False,
    )
    comparison = replace(comparison, artifact_hash=_comparison_hash(comparison))
    conflict = ConflictInput(
        conflict_id="conflict:sha256:" + "b" * 64,
        artifact_hash="sha256:" + "0" * 64,
        comparison_id=comparison.comparison_id,
        outcome=ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE,
    )
    conflict = replace(conflict, artifact_hash=_conflict_hash(conflict))
    generated_comparison = GenerationComparison.create(
        comparison_id=comparison.comparison_id,
        run_id=report.RUN_ID,
        artifact_hash=comparison.artifact_hash,
        evidence_ids=tuple(sorted(evidence_ids)),
        summary="The exact evidence scopes are comparable.",
    )
    generated_conflict = GenerationConflict.create(
        conflict_id=conflict.conflict_id,
        run_id=report.RUN_ID,
        comparison_id=comparison.comparison_id,
        comparison_artifact_hash=comparison.artifact_hash,
        artifact_hash=conflict.artifact_hash,
        evidence_ids=tuple(sorted(evidence_ids)),
        summary="The exact comparable findings are consistent.",
    )
    return comparison, conflict, generated_comparison, generated_conflict


def test_known_single_pair_is_bound_to_planned_semantic_input() -> None:
    first, second = _trusted(index=0), _trusted(index=1)
    base = _input(first, second)
    comparison, conflict, generated_comparison, generated_conflict = _pair(
        (first.evidence_id, second.evidence_id)
    )
    generation_input = base.model_copy(
        update={"comparisons": (generated_comparison,), "conflicts": (generated_conflict,)}
    )
    generation_input = GenerationInput.model_validate(
        generation_input.model_dump(mode="python"), strict=True
    )
    claim = _qualitative_claim(first).model_copy(update={"conflict_ids": (conflict.conflict_id,)})
    candidate = _candidate(generation_input, claim)
    mapped = map_generation_v2_to_registry(
        generation_input,
        candidate,
        trusted_evidence=(first, second),
        comparisons=(comparison,),
        conflicts=(conflict,),
    )
    planned = mapped.registry.semantic_expectations[0]
    assert planned.comparison_id == comparison.comparison_id
    assert planned.conflict_id == conflict.conflict_id
    without_membership = _candidate(generation_input, _qualitative_claim(first))
    with pytest.raises(SynthesisMappingError, match="comparability_omission_ambiguous"):
        map_generation_v2_to_registry(
            generation_input,
            without_membership,
            trusted_evidence=(first, second),
            comparisons=(comparison,),
            conflicts=(conflict,),
        )
    with pytest.raises(SynthesisMappingError, match="comparison_graph_invalid"):
        map_generation_v2_to_registry(
            generation_input,
            candidate,
            trusted_evidence=(first, second),
            comparisons=(replace(comparison, artifact_hash="sha256:" + "f" * 64),),
            conflicts=(conflict,),
        )


def test_claim_cannot_select_pair_for_foreign_evidence_graph() -> None:
    first, second, foreign = _trusted(index=0), _trusted(index=1), _trusted(index=2)
    base = _input(first, second, foreign)
    comparison, conflict, generated_comparison, generated_conflict = _pair(
        (first.evidence_id, second.evidence_id)
    )
    generation_input = GenerationInput.model_validate(
        base.model_copy(
            update={"comparisons": (generated_comparison,), "conflicts": (generated_conflict,)}
        ).model_dump(mode="python"),
        strict=True,
    )
    claim = _qualitative_claim(foreign).model_copy(update={"conflict_ids": (conflict.conflict_id,)})
    with pytest.raises(SynthesisMappingError, match="conflict_evidence_binding_drift"):
        map_generation_v2_to_registry(
            generation_input,
            _candidate(generation_input, claim),
            trusted_evidence=(first, second, foreign),
            comparisons=(comparison,),
            conflicts=(conflict,),
        )


def test_schema_prompt_and_parser_are_separate_from_v1_and_fail_closed() -> None:
    evidence = _trusted()
    generation_input = _input(evidence)
    candidate = _candidate(generation_input, _qualitative_claim(evidence))
    raw = generation_v2_candidate_bytes(candidate)
    assert parse_generation_v2_candidate(raw) == candidate
    assert generation_v2_response_schema()["properties"]["schema_version"]["const"] == (
        "m3.generation.candidate.v2"
    )
    schema = generation_v2_response_schema()
    inference_values = schema["properties"]["claims"]["items"]["properties"]["inference_use"][
        "enum"
    ]
    assert not {
        "incidence",
        "risk",
        "relative_risk",
        "product_comparison",
        "product_ranking",
        "diagnosis_treatment_or_advice",
    } & set(inference_values)
    assert GENERATION_V2_PROMPT_HASH.startswith("sha256:")
    assert GENERATION_V2_PROMPT_HASH == (
        "sha256:b696cccb72580fa995e69043935c02bdeacec416156123067ecc7ec92ee185fc"
    )
    assert GENERATION_V2_SCHEMA_HASH == (
        "sha256:287cdb777c8935370f84ae28cb34872bfda4ca77ea2c4dfaa1f270df1a3a1d1f"
    )
    assert GENERATION_V2_CONFIG_HASH == (
        "sha256:95c8d447b9abc83f97c1a950eab19270f8c83cf077a6c8792af2aaa29e2526ac"
    )
    assert GENERATION_PROMPT_HASH == (
        "sha256:fe7d643288b859019ea4779ba377e11a81bf84786b30c834793f20b467e76bbf"
    )
    assert GENERATION_SCHEMA_HASH == (
        "sha256:46889968b47d55cf1ec7793bf326e9ef35460db2dbdb0997986f3e822bce393f"
    )
    assert DEEPSEEK_GENERATION_CONFIGURATION_HASH == (
        "sha256:4becb5158c4f1ed0e808987b79129b889d3b28d3db308ac80177db3745707ee1"
    )
    duplicate = raw.replace(b'{"claims":', b'{"claims":[],"claims":', 1)
    with pytest.raises(GenerationV2ContractError, match="duplicate_key"):
        parse_generation_v2_candidate(duplicate)
    altered = json.loads(raw)
    altered["claims"][0]["statement"] += " forged"
    with pytest.raises(GenerationV2ContractError, match="output_invalid"):
        parse_generation_v2_candidate(canonical_json(altered).encode("utf-8"))
