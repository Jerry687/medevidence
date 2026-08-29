"""One source-neutral deterministic authority for report validation."""

# ruff: noqa: E501, E701, E702, I001, RUF021, UP047
# fmt: off
from __future__ import annotations

import re
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Protocol, TypeVar, cast
from medevidence.domain import CADEC_MANDATORY_LIMITATIONS, FAERS_MANDATORY_LIMITATIONS, AdverseEventConcept, ComparisonIntent, CoverageStatus, DrugConcept, ExecutionBounds, ExecutionStatus, InclusiveDateRange, QueryBounds, ResearchScope, ResultBounds, ResultStatus, SourceType, canonical_json, derive_identity, sha256_digest

M3_VALIDATION_RECEIPT_V1 = "M3_VALIDATION_RECEIPT_V1"
M3_VALIDATION_POLICY_V1 = "M3_VALIDATION_POLICY_V1"
M3_VALIDATION_CONFIGURATION_V1 = "M3_VALIDATION_CONFIGURATION_V1"

class ValidationMode(StrEnum):
    ASSESS = "assess"
    VERIFY_BINDING = "verify_binding"

class ClaimClass(StrEnum):
    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    CAUSAL = "causal"
    REGULATORY_OR_LABELING = "regulatory_or_labeling"
    METHODOLOGICAL_OR_LIMITATION = "methodological_or_limitation"

class InferenceUse(StrEnum):
    DESCRIPTIVE = "descriptive"
    ASSOCIATIONAL = "associational"
    CLINICAL = "clinical"
    CAUSAL = "causal"
    REGULATORY = "regulatory"
    INCIDENCE = "incidence"
    RISK = "risk"
    RELATIVE_RISK = "relative_risk"
    PRODUCT_COMPARISON = "product_comparison"
    PRODUCT_RANKING = "product_ranking"
    AUXILIARY_NLP_RETRIEVAL = "auxiliary_nlp_retrieval"
    METHODOLOGICAL_LIMITATION = "methodological_limitation"
    DIAGNOSIS_TREATMENT_OR_ADVICE = "diagnosis_treatment_or_advice"

class ClaimInclusion(StrEnum):
    FORMAL = "formal"
    REMOVED = "removed"

class CitationRelationship(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT_ONLY = "context_only"

class SemanticSupport(StrEnum):
    SUPPORTED = "supported"
    UNCERTAIN = "uncertain"
    UNSUPPORTED = "unsupported"

class ResolutionAction(StrEnum):
    ADJUDICATED_TO_SUPPORTED = "adjudicated_to_supported"
    REMOVED = "removed"

class ComparableFindingRelation(StrEnum):
    CONSISTENT = "consistent"
    CONFLICTING = "conflicting"

class ConflictOutcome(StrEnum):
    CONSISTENT_COMPARABLE_SCOPE = "consistent_comparable_scope"
    APPARENT_DIFFERENCE_SCOPE_MISMATCH = "apparent_difference_scope_mismatch"
    UNRESOLVED_CONFLICT_COMPARABLE_SCOPE = "unresolved_conflict_comparable_scope"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    SOURCE_UNAVAILABLE = "source_unavailable"

class ComparabilityDimension(StrEnum):
    INGREDIENT_PRODUCT = "ingredient_product"
    FORMULATION = "formulation"
    ROUTE = "route"
    STRENGTH = "strength"
    POPULATION = "population"
    INDICATION = "indication"
    DOSE_EXPOSURE = "dose_exposure"
    OBSERVATION_PUBLICATION_WINDOW = "observation_publication_window"
    ADVERSE_EVENT_OUTCOME_DEFINITION = "adverse_event_outcome_definition"
    COMPARATOR = "comparator"
    SOURCE_QUESTION = "source_question"


COMPARABILITY_DIMENSIONS = tuple(ComparabilityDimension)

class QualitativeCode(StrEnum):
    PUBMED_DESCRIPTIVE = "pubmed_descriptive"
    PUBMED_ASSOCIATIONAL = "pubmed_associational"
    PUBMED_CAUSAL = "pubmed_causal"
    PUBMED_CLINICAL = "pubmed_clinical"
    PUBMED_LIMITATION = "pubmed_limitation"
    DAILYMED_DESCRIPTIVE = "dailymed_descriptive"
    DAILYMED_CLINICAL = "dailymed_clinical"
    DAILYMED_LABELING = "dailymed_labeling"
    DAILYMED_LIMITATION = "dailymed_limitation"
    FAERS_DESCRIPTIVE_CONTEXT = "faers_descriptive_context"
    FAERS_LIMITATION = "faers_limitation"
    CADEC_AUXILIARY_CONTEXT = "cadec_auxiliary_context"
    CADEC_LIMITATION = "cadec_limitation"

class CanonicalValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

def _bounded_tuple(value: object, maximum: int, code: str, *, type_code: str | None = None) -> None:
    if type(value) is not tuple:
        raise CanonicalValidationError(code if type_code is None else type_code)
    if len(value) > maximum:
        raise CanonicalValidationError(code)

@dataclass(frozen=True, slots=True)
class ScopeInput:
    scope_id: str
    drugs: tuple[tuple[str, str], ...]
    adverse_reactions: tuple[tuple[str, str], ...]
    date_range: tuple[str, str] | None
    selected_sources: tuple[SourceType, ...]
    comparison_intent: ComparisonIntent
    max_query_characters: int
    max_pages: int
    max_total_seconds: int
    max_records: int
    max_payload_bytes: int

    def __post_init__(self) -> None:
        _check_scope_cardinality(self)

@dataclass(frozen=True, slots=True)
class ExecutionBoundsInput:
    max_query_characters: int
    max_pages: int
    max_records: int
    max_payload_bytes: int
    max_total_seconds: int

@dataclass(frozen=True, slots=True)
class AcquisitionInput:
    run_id: str
    source: SourceType
    acquisition_id: str
    acquisition_intent_id: str
    acquisition_ordinal: int
    operation: str
    query_id: str
    source_outcome_id: str
    snapshot_id: str

@dataclass(frozen=True, slots=True)
class SourceOutcomeInput:
    source: SourceType
    query_id: str
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus
    configured_bounds: ExecutionBoundsInput
    valid_result_count: int
    pages_completed: int
    truncated: bool
    warning_codes: tuple[str, ...]
    failure_id: str | None

    def __post_init__(self) -> None:
        _bounded_tuple(self.warning_codes, 100, "outcome_warning_cardinality_exceeded")

@dataclass(frozen=True, slots=True)
class EvidenceReferenceInput:
    evidence_id: str
    source: SourceType
    snapshot_id: str
    content_hash: str
    locator_ref: str

@dataclass(frozen=True, slots=True)
class TerminalTaskInput:
    task_id: str
    source: SourceType
    terminal: bool
    acquisition: AcquisitionInput
    outcome: SourceOutcomeInput
    evidence_refs: tuple[EvidenceReferenceInput, ...]

    def __post_init__(self) -> None:
        if type(self.evidence_refs) is not tuple or len(self.evidence_refs) > 100:
            raise CanonicalValidationError("task_evidence_cardinality_exceeded")

@dataclass(frozen=True, slots=True)
class ClaimReferenceInput:
    claim_id: str

@dataclass(frozen=True, slots=True)
class CitationReferenceInput:
    citation_id: str
    claim_id: str
    evidence_id: str

@dataclass(frozen=True, slots=True)
class ArtifactReferenceInput:
    artifact_id: str
    artifact_hash: str

@dataclass(frozen=True, slots=True)
class SynthesisInput:
    report_content_hash: str
    claims: tuple[ClaimReferenceInput, ...]
    citations: tuple[CitationReferenceInput, ...]
    comparison_refs: tuple[ArtifactReferenceInput, ...]
    conflict_refs: tuple[ArtifactReferenceInput, ...]
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        checks = (
            (self.claims, 200, "synthesis_claim_cardinality_exceeded"),
            (self.citations, 400, "synthesis_citation_cardinality_exceeded"),
            (self.comparison_refs, 100, "synthesis_comparison_cardinality_exceeded"),
            (self.conflict_refs, 100, "synthesis_conflict_cardinality_exceeded"),
            (self.warning_codes, 100, "synthesis_warning_cardinality_exceeded"),
        )
        for values, maximum, code in checks:
            if type(values) is not tuple or len(values) > maximum:
                raise CanonicalValidationError(code)
@dataclass(frozen=True, slots=True)
class NumericalContextInput:
    value: str
    unit: str
    denominator: str
    comparator: str
    time_basis: str
    population_scope: str

@dataclass(frozen=True, slots=True)
class NumericalFactInput:
    locator_ref: str
    exact_text: str
    value: str
    unit: str
    denominator: str
    comparator: str
    time_basis: str
    population_scope: str

@dataclass(frozen=True, slots=True)
class ClaimInput:
    claim_id: str
    source: SourceType
    qualitative_code: QualitativeCode | None
    statement: str
    claim_class: ClaimClass
    inference_use: InferenceUse
    citation_ids: tuple[str, ...]
    presented_limitations: tuple[str, ...]
    inclusion: ClaimInclusion
    numerical_context: NumericalContextInput | None

    def __post_init__(self) -> None:
        _bounded_tuple(self.citation_ids, 300, "claim_citation_cardinality_exceeded", type_code="claim_collection_invalid")
        _bounded_tuple(self.presented_limitations, 100, "claim_limitation_cardinality_exceeded", type_code="claim_collection_invalid")

@dataclass(frozen=True, slots=True)
class CitationInput:
    citation_id: str
    claim_id: str
    evidence_id: str
    relationship: CitationRelationship
    source_record_id: str
    source_version: str
    snapshot_id: str
    content_hash: str
    locator_ref: str
    execution_status: ExecutionStatus
    coverage_status: CoverageStatus
    result_status: ResultStatus

@dataclass(frozen=True, slots=True)
class EvidenceInput:
    evidence_id: str
    authorized_run_id: str
    source: SourceType
    source_record_id: str
    source_version: str
    snapshot_id: str
    content_hash: str
    locators: tuple[str, ...]
    permitted_claim_classes: frozenset[ClaimClass]
    permitted_inference_uses: frozenset[InferenceUse]
    normalized_excerpt: str
    numerical_facts: tuple[NumericalFactInput, ...]

    def __post_init__(self) -> None:
        _check_evidence_cardinality(self)

@dataclass(frozen=True, slots=True)
class SemanticExpectationInput:
    citation_id: str
    input_digest: str
    method: str
    version: str
    result: SemanticSupport

@dataclass(frozen=True, slots=True)
class SemanticEvaluationInput:
    run_id: str
    claim: ClaimInput
    citation: CitationInput
    evidence: EvidenceInput

@dataclass(frozen=True, slots=True)
class SemanticResultInput:
    result: SemanticSupport
    method: str
    version: str

class SemanticResultProvider(Protocol):
    def evaluate(self, value: SemanticEvaluationInput) -> SemanticResultInput: ...

@dataclass(frozen=True, slots=True)
class ResolutionInput:
    claim_id: str
    action: ResolutionAction
    record_id: str
    method: str
    version: str
    comparison_id: str | None = None
    conflict_id: str | None = None

@dataclass(frozen=True, slots=True)
class DimensionInput:
    dimension: ComparabilityDimension
    applicable: bool
    left_value: str | None
    right_value: str | None

@dataclass(frozen=True, slots=True)
class ComparisonInput:
    comparison_id: str
    artifact_hash: str
    dimensions: tuple[DimensionInput, ...]
    relation: ComparableFindingRelation
    source_unavailable: bool

    def __post_init__(self) -> None:
        _bounded_tuple(self.dimensions, 11, "comparison_dimension_cardinality_exceeded")

@dataclass(frozen=True, slots=True)
class ConflictInput:
    conflict_id: str
    artifact_hash: str
    comparison_id: str
    outcome: ConflictOutcome

@dataclass(frozen=True, slots=True)
class EvaluatorIdentityInput:
    method: str
    version: str

@dataclass(frozen=True, slots=True)
class ValidationRegistryInput:
    run_id: str
    scope_id: str
    claims: tuple[ClaimInput, ...]
    citations: tuple[CitationInput, ...]
    evidence: tuple[EvidenceInput, ...]
    semantic_expectations: tuple[SemanticExpectationInput, ...]
    evaluator_identity: EvaluatorIdentityInput
    comparisons: tuple[ComparisonInput, ...] = ()
    conflicts: tuple[ConflictInput, ...] = ()
    resolutions: tuple[ResolutionInput, ...] = ()
    configuration_version: str = M3_VALIDATION_CONFIGURATION_V1

    def __post_init__(self) -> None:
        checks = (
            (self.claims, 200, "registry_claim_cardinality_exceeded"),
            (self.resolutions, 200, "registry_resolution_cardinality_exceeded"),
            (self.citations, 400, "registry_citation_cardinality_exceeded"),
            (
                self.semantic_expectations,
                400,
                "registry_semantic_expectation_cardinality_exceeded",
            ),
            (self.evidence, 400, "registry_evidence_cardinality_exceeded"),
            (self.comparisons, 100, "registry_comparison_cardinality_exceeded"),
            (self.conflicts, 100, "registry_conflict_cardinality_exceeded"),
        )
        for values, maximum, code in checks:
            if type(values) is not tuple or len(values) > maximum:
                raise CanonicalValidationError(code)

@dataclass(frozen=True, slots=True)
class StoredValidationInput:
    structural_passed: bool
    semantic_passed: bool
    safety_passed: bool
    reason_codes: tuple[str, ...]
@dataclass(frozen=True, slots=True)
class CanonicalReportRequest:
    run_id: str
    report_id: str
    scope: ScopeInput
    source_plan_id: str
    selected_task_sources: tuple[SourceType, ...]
    tasks: tuple[TerminalTaskInput, ...]
    synthesis: SynthesisInput
    registry: ValidationRegistryInput
    stored_validation: StoredValidationInput | None = None
    def __post_init__(self) -> None:
        _bounded_tuple(self.tasks, 4, "task_cardinality_exceeded", type_code="task_collection_wrong_type")
@dataclass(frozen=True, slots=True)
class CitationTrace:
    citation_id: str
    input_digest: str
    method: str
    version: str
    result: SemanticSupport
    relationship: CitationRelationship

@dataclass(frozen=True, slots=True)
class ClaimAudit:
    claim_id: str
    stage1_passed: bool
    reason_codes: tuple[str, ...]
    citation_traces: tuple[CitationTrace, ...]
    formal_claim_accepted: bool
    aggregate_result: SemanticSupport | None

@dataclass(frozen=True, slots=True)
class ValidationSummary:
    structural_passed: bool
    semantic_passed: bool
    safety_passed: bool
    reason_codes: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.structural_passed and self.semantic_passed and self.safety_passed

@dataclass(frozen=True, slots=True)
class ValidationCitationReceipt:
    citation_result_id: str
    citation_id: str
    input_digest: str
    method: str
    version: str
    result: SemanticSupport
    relationship: CitationRelationship

@dataclass(frozen=True, slots=True)
class ValidationClaimReceipt:
    claim_result_id: str
    claim_id: str
    stage1_passed: bool
    stage1_reason_codes: tuple[str, ...]
    citation_results: tuple[ValidationCitationReceipt, ...]
    aggregate_result: SemanticSupport | None
    resolution_action: ResolutionAction | None
    resolution_record_id: str | None
    resolution_method: str | None
    resolution_version: str | None
    comparison_id: str | None
    conflict_id: str | None
    formal_claim_accepted: bool

@dataclass(frozen=True, slots=True)
class ValidationReceipt:
    marker: str
    receipt_id: str
    receipt_content_hash: str
    run_id: str
    report_id: str
    report_content_hash: str
    validation_input_hash: str
    task_binding_hash: str
    stage1_result_id: str
    evaluator_method: str
    evaluator_version: str
    claim_results: tuple[ValidationClaimReceipt, ...]
    structural_passed: bool
    semantic_passed: bool
    safety_passed: bool
    reason_codes: tuple[str, ...]
    policy_version: str
    configuration_version: str

@dataclass(frozen=True, slots=True)
class ReportValidationAudit:
    summary: ValidationSummary
    claims: tuple[ClaimAudit, ...]
    conflict_outcomes: tuple[tuple[str, ConflictOutcome], ...]
    receipt: ValidationReceipt | None = None


_T = TypeVar("_T")
_E = TypeVar("_E", bound=StrEnum)
_DIGEST, _REPORT_ID, _RUN_ID, _ACQUISITION_INTENT, _REASON = (re.compile(r"sha256:[0-9a-f]{64}"), re.compile(r"report:sha256:[0-9a-f]{64}"), re.compile(r"run:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"), re.compile(r"acquisition-intent:sha256:[0-9a-f]{64}"), re.compile(r"[a-z][a-z0-9_]{0,127}"))
_COUNT_FIELDS = ("value", "unit", "denominator", "comparator", "time_basis", "population_scope")
_FAERS_NUMBER = ("provider_count_occurrence", "no exposure denominator", "no product comparator", "configured query window", "bounded FAERS spontaneous reports")

def _exact(value: object, expected: type[_T], code: str) -> _T:
    if type(value) is not expected:
        raise CanonicalValidationError(code)
    return value

def _text(value: object, code: str, *, blank: bool = False, maximum: int = 512) -> str:
    if type(value) is not str or len(value) > maximum or (not blank and (not value.strip() or value != " ".join(value.split()))):
        raise CanonicalValidationError(code)
    return value

def _digest(value: object, code: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise CanonicalValidationError(code)
    return value

def _reason_tuple(value: object, code: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str or _REASON.fullmatch(item) is None for item in value):
        raise CanonicalValidationError(code)
    if value != tuple(sorted(set(value))):
        raise CanonicalValidationError(code)
    return value

def _primitive(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if type(value) is tuple:
        return tuple(_primitive(item) for item in value)
    if type(value) is frozenset:
        return tuple(sorted((_primitive(item) for item in value), key=str))
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _primitive(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _primitive(getattr(value, item.name)) for item in fields(value)}
    raise CanonicalValidationError("nonprimitive_value")

def _identity(prefix: str, payload: object) -> str:
    return f"{prefix}:sha256:{sha256_digest(canonical_json(payload)).removeprefix('sha256:')}"

def canonical_numerical_text(value: NumericalContextInput | NumericalFactInput) -> str:
    return " | ".join(f"{name}={getattr(value, name)}" for name in _COUNT_FIELDS)

def canonical_claim_id(value: ClaimInput) -> str:
    payload = {
        "source": value.source,
        "qualitative_code": value.qualitative_code,
        "statement": value.statement,
        "claim_class": value.claim_class,
        "inference_use": value.inference_use,
        "presented_limitations": value.presented_limitations,
        "inclusion": value.inclusion,
        "numerical_context": value.numerical_context,
    }
    return _identity("claim", _primitive(payload))

def canonical_evidence_id(value: EvidenceInput) -> str:
    payload = {item.name: getattr(value, item.name) for item in fields(value) if item.name != "evidence_id"}
    return _identity("evidence", _primitive(payload))

def canonical_citation_id(value: CitationInput) -> str:
    payload = {item.name: getattr(value, item.name) for item in fields(value) if item.name != "citation_id"}
    return _identity("citation", _primitive(payload))

def canonical_semantic_input_digest(
    run_id: str,
    claim: ClaimInput,
    citation: CitationInput,
    evidence: EvidenceInput,
) -> str:
    payload = {
        "run_id": run_id,
        "claim_id": claim.claim_id,
        "citation_id": citation.citation_id,
        "evidence_id": evidence.evidence_id,
        "relationship": citation.relationship,
        "source_record_id": evidence.source_record_id,
        "source_version": evidence.source_version,
        "snapshot_id": evidence.snapshot_id,
        "content_hash": evidence.content_hash,
        "locator_ref": citation.locator_ref,
    }
    return sha256_digest(canonical_json(_primitive(payload)))

def _copy_scope(value: ScopeInput) -> ScopeInput:
    _exact(value, ScopeInput, "scope_wrong_type")
    _check_scope_cardinality(value)
    drugs = tuple(DrugConcept(concept_id=_text(row[0], "drug_id_invalid"), preferred_term=_text(row[1], "drug_term_invalid")) for row in value.drugs if type(row) is tuple and len(row) == 2)
    reactions = tuple(AdverseEventConcept(concept_id=_text(row[0], "reaction_id_invalid"), preferred_term=_text(row[1], "reaction_term_invalid")) for row in value.adverse_reactions if type(row) is tuple and len(row) == 2)
    if len(drugs) != len(value.drugs) or len(reactions) != len(value.adverse_reactions):
        raise CanonicalValidationError("scope_concept_wrong_type")
    date_range = None
    if value.date_range is not None:
        if type(value.date_range) is not tuple or len(value.date_range) != 2 or any(type(item) is not str for item in value.date_range):
            raise CanonicalValidationError("scope_date_invalid")
        try:
            date_range = InclusiveDateRange(start_date=date.fromisoformat(value.date_range[0]), end_date=date.fromisoformat(value.date_range[1]))
        except ValueError as error:
            raise CanonicalValidationError("scope_date_invalid") from error
    if type(value.selected_sources) is not tuple or any(type(item) is not SourceType for item in value.selected_sources):
        raise CanonicalValidationError("scope_sources_wrong_type")
    rebuilt = ResearchScope.create(
        drugs=drugs,
        adverse_reactions=reactions,
        date_range=date_range,
        selected_sources=value.selected_sources,
        comparison_intent=_exact(value.comparison_intent, ComparisonIntent, "scope_intent_wrong_type"),
        query_bounds=QueryBounds(max_query_characters=value.max_query_characters, max_pages=value.max_pages, max_total_seconds=value.max_total_seconds),
        result_bounds=ResultBounds(max_records=value.max_records, max_payload_bytes=value.max_payload_bytes),
    )
    if rebuilt.scope_id != value.scope_id:
        raise CanonicalValidationError("scope_identity_drift")
    return ScopeInput(value.scope_id, tuple((item.concept_id, item.preferred_term) for item in rebuilt.drugs), tuple((item.concept_id, item.preferred_term) for item in rebuilt.adverse_reactions), None if rebuilt.date_range is None else (rebuilt.date_range.start_date.isoformat(), rebuilt.date_range.end_date.isoformat()), rebuilt.selected_sources, rebuilt.comparison_intent, rebuilt.query_bounds.max_query_characters, rebuilt.query_bounds.max_pages, rebuilt.query_bounds.max_total_seconds, rebuilt.result_bounds.max_records, rebuilt.result_bounds.max_payload_bytes)

def _copy_bounds(value: ExecutionBoundsInput) -> ExecutionBoundsInput:
    _exact(value, ExecutionBoundsInput, "execution_bounds_wrong_type")
    numbers = tuple(getattr(value, item.name) for item in fields(value))
    if any(type(item) is not int or item < 1 for item in numbers):
        raise CanonicalValidationError("execution_bounds_invalid")
    rebuilt = ExecutionBounds(max_query_characters=numbers[0], max_pages=numbers[1], max_records=numbers[2], max_payload_bytes=numbers[3], max_total_seconds=numbers[4])
    return ExecutionBoundsInput(rebuilt.max_query_characters, rebuilt.max_pages, rebuilt.max_records, rebuilt.max_payload_bytes, rebuilt.max_total_seconds)

def _copy_outcome(value: SourceOutcomeInput) -> SourceOutcomeInput:
    _exact(value, SourceOutcomeInput, "outcome_wrong_type")
    _bounded_tuple(value.warning_codes, 100, "outcome_warning_cardinality_exceeded")
    bounds = _copy_bounds(value.configured_bounds)
    warnings = _reason_tuple(value.warning_codes, "outcome_warning_invalid")
    source = _exact(value.source, SourceType, "outcome_source_wrong_type")
    execution = _exact(value.execution_status, ExecutionStatus, "outcome_execution_wrong_type")
    coverage = _exact(value.coverage_status, CoverageStatus, "outcome_coverage_wrong_type")
    result = _exact(value.result_status, ResultStatus, "outcome_result_wrong_type")
    if any(type(item) is not int for item in (value.valid_result_count, value.pages_completed)) or type(value.truncated) is not bool:
        raise CanonicalValidationError("outcome_primitive_wrong_type")
    triples = {
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.MATCHES),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.COMPLETE, ResultStatus.NO_MATCH),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
        (ExecutionStatus.SUCCEEDED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE),
        (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.MATCHES),
        (ExecutionStatus.FAILED, CoverageStatus.PARTIAL, ResultStatus.INDETERMINATE),
        (ExecutionStatus.FAILED, CoverageStatus.UNAVAILABLE, ResultStatus.INDETERMINATE),
    }
    if (execution, coverage, result) not in triples:
        raise CanonicalValidationError("outcome_terminal_triple_invalid")
    if value.valid_result_count < 0 or value.valid_result_count > bounds.max_records or value.pages_completed < 0 or value.pages_completed > bounds.max_pages:
        raise CanonicalValidationError("outcome_bounds_invalid")
    if (result is ResultStatus.MATCHES) != (value.valid_result_count > 0):
        raise CanonicalValidationError("outcome_count_result_invalid")
    if coverage is CoverageStatus.COMPLETE and value.truncated:
        raise CanonicalValidationError("outcome_complete_truncated")
    if coverage is CoverageStatus.UNAVAILABLE and (value.pages_completed or value.valid_result_count):
        raise CanonicalValidationError("outcome_unavailable_has_results")
    if coverage in (CoverageStatus.PARTIAL, CoverageStatus.UNAVAILABLE) and not warnings:
        raise CanonicalValidationError("outcome_degradation_warning_missing")
    if execution is ExecutionStatus.FAILED and (type(value.failure_id) is not str or not value.failure_id) or execution is ExecutionStatus.SUCCEEDED and value.failure_id is not None:
        raise CanonicalValidationError("outcome_failure_identity_invalid")
    return SourceOutcomeInput(source, _text(value.query_id, "outcome_query_invalid"), execution, coverage, result, bounds, value.valid_result_count, value.pages_completed, value.truncated, warnings, value.failure_id)

def _copy_task(value: TerminalTaskInput) -> TerminalTaskInput:
    _exact(value, TerminalTaskInput, "task_wrong_type")
    if type(value.evidence_refs) is not tuple or len(value.evidence_refs) > 100:
        raise CanonicalValidationError("task_evidence_cardinality_exceeded")
    if type(value.terminal) is not bool or not value.terminal:
        raise CanonicalValidationError("task_not_terminal")
    acquisition = _exact(value.acquisition, AcquisitionInput, "acquisition_wrong_type")
    if type(acquisition.acquisition_ordinal) is not int or not 0 <= acquisition.acquisition_ordinal <= 7 or acquisition.operation not in ("search", "fetch"):
        raise CanonicalValidationError("acquisition_primitive_invalid")
    intent = _text(acquisition.acquisition_intent_id, "acquisition_intent_invalid")
    if _ACQUISITION_INTENT.fullmatch(intent) is None: raise CanonicalValidationError("acquisition_intent_invalid")
    acquisition = AcquisitionInput(_text(acquisition.run_id, "acquisition_run_invalid"), _exact(acquisition.source, SourceType, "acquisition_source_wrong_type"), _text(acquisition.acquisition_id, "acquisition_id_invalid"), intent, acquisition.acquisition_ordinal, acquisition.operation, _text(acquisition.query_id, "acquisition_query_invalid"), _text(acquisition.source_outcome_id, "source_outcome_id_invalid"), _text(acquisition.snapshot_id, "acquisition_snapshot_invalid"))
    outcome = _copy_outcome(value.outcome)
    refs: list[EvidenceReferenceInput] = []
    for raw in value.evidence_refs:
        ref = _exact(raw, EvidenceReferenceInput, "evidence_reference_wrong_type")
        refs.append(EvidenceReferenceInput(_text(ref.evidence_id, "evidence_reference_id_invalid"), _exact(ref.source, SourceType, "evidence_reference_source_wrong_type"), _text(ref.snapshot_id, "evidence_reference_snapshot_invalid"), _digest(ref.content_hash, "evidence_reference_hash_invalid"), _text(ref.locator_ref, "evidence_reference_locator_invalid")))
    source = _exact(value.source, SourceType, "task_source_wrong_type")
    if source is not acquisition.source or source is not outcome.source or acquisition.query_id != outcome.query_id or any(item.source is not source for item in refs):
        raise CanonicalValidationError("task_source_binding_invalid")
    return TerminalTaskInput(_text(value.task_id, "task_id_invalid"), source, True, acquisition, outcome, tuple(refs))

def _copy_fact(value: NumericalFactInput) -> NumericalFactInput:
    _exact(value, NumericalFactInput, "numerical_fact_wrong_type")
    copied = NumericalFactInput(*(_text(getattr(value, name), "numerical_fact_field_invalid", maximum=4096 if name == "exact_text" else 512) for name in ("locator_ref", "exact_text", *_COUNT_FIELDS)))
    if copied.exact_text != canonical_numerical_text(copied):
        raise CanonicalValidationError("numerical_fact_text_invalid")
    return copied

def _copy_context(value: NumericalContextInput) -> NumericalContextInput:
    _exact(value, NumericalContextInput, "numerical_context_wrong_type")
    return NumericalContextInput(*(_text(getattr(value, name), "numerical_context_field_invalid") for name in _COUNT_FIELDS))

def _copy_evidence(value: EvidenceInput) -> EvidenceInput:
    _exact(value, EvidenceInput, "evidence_wrong_type")
    _check_evidence_cardinality(value)
    if not value.locators:
        raise CanonicalValidationError("evidence_collection_invalid")
    locators = tuple(_text(item, "evidence_locator_invalid") for item in value.locators)
    if locators != tuple(dict.fromkeys(locators)):
        raise CanonicalValidationError("evidence_locator_duplicate")
    if type(value.permitted_claim_classes) is not frozenset or any(type(item) is not ClaimClass for item in value.permitted_claim_classes) or type(value.permitted_inference_uses) is not frozenset or any(type(item) is not InferenceUse for item in value.permitted_inference_uses):
        raise CanonicalValidationError("evidence_permissions_invalid")
    copied = EvidenceInput(_text(value.evidence_id, "evidence_id_invalid"), _text(value.authorized_run_id, "evidence_run_invalid"), _exact(value.source, SourceType, "evidence_source_wrong_type"), _text(value.source_record_id, "evidence_record_invalid"), _text(value.source_version, "evidence_version_invalid"), _text(value.snapshot_id, "evidence_snapshot_invalid"), _digest(value.content_hash, "evidence_hash_invalid"), locators, frozenset(value.permitted_claim_classes), frozenset(value.permitted_inference_uses), _text(value.normalized_excerpt, "evidence_excerpt_invalid", blank=True, maximum=4096), tuple(_copy_fact(item) for item in value.numerical_facts))
    if copied.evidence_id != canonical_evidence_id(copied):
        raise CanonicalValidationError("evidence_identity_drift")
    if copied.source is SourceType.CADEC and copied.numerical_facts:
        raise CanonicalValidationError("cadec_numerical_fact_forbidden")
    if copied.source is SourceType.FAERS and any(not _faers_number(item) for item in copied.numerical_facts):
        raise CanonicalValidationError("faers_numerical_fact_invalid")
    if any(item.locator_ref not in copied.locators or item.exact_text not in copied.normalized_excerpt for item in copied.numerical_facts):
        raise CanonicalValidationError("numerical_fact_lineage_invalid")
    return copied

def _copy_claim(value: ClaimInput) -> ClaimInput:
    _exact(value, ClaimInput, "claim_wrong_type")
    _bounded_tuple(value.citation_ids, 300, "claim_citation_cardinality_exceeded", type_code="claim_collection_invalid")
    _bounded_tuple(value.presented_limitations, 100, "claim_limitation_cardinality_exceeded", type_code="claim_collection_invalid")
    context = None if value.numerical_context is None else _copy_context(value.numerical_context)
    code = value.qualitative_code
    if (code is None) == (context is None) or code is not None and type(code) is not QualitativeCode:
        raise CanonicalValidationError("claim_closed_form_invalid")
    copied = ClaimInput(_text(value.claim_id, "claim_id_invalid"), _exact(value.source, SourceType, "claim_source_wrong_type"), code, _text(value.statement, "claim_statement_invalid", maximum=4096), _exact(value.claim_class, ClaimClass, "claim_class_wrong_type"), _exact(value.inference_use, InferenceUse, "claim_use_wrong_type"), tuple(_text(item, "claim_citation_id_invalid") for item in value.citation_ids), tuple(_text(item, "claim_limitation_invalid", maximum=4096) for item in value.presented_limitations), _exact(value.inclusion, ClaimInclusion, "claim_inclusion_wrong_type"), context)
    if copied.claim_id != canonical_claim_id(copied):
        raise CanonicalValidationError("claim_identity_drift")
    if code is not None and (copied.source, copied.claim_class, copied.inference_use, copied.statement) != _qualitative_form(code):
        raise CanonicalValidationError("qualitative_claim_noncanonical")
    if context is not None:
        expected = canonical_numerical_text(context)
        if copied.source is SourceType.FAERS:
            expected = f"FAERS bounded spontaneous-report count: {expected} {FAERS_MANDATORY_LIMITATIONS[1]}"
            if not _faers_number(context) or copied.claim_class is not ClaimClass.DESCRIPTIVE or copied.inference_use is not InferenceUse.DESCRIPTIVE:
                raise CanonicalValidationError("faers_numerical_claim_invalid")
        if copied.source is SourceType.CADEC:
            raise CanonicalValidationError("cadec_numerical_claim_forbidden")
        if copied.statement != expected:
            raise CanonicalValidationError("numerical_claim_text_invalid")
    return copied

def _copy_citation(value: CitationInput) -> CitationInput:
    _exact(value, CitationInput, "citation_wrong_type")
    copied = CitationInput(_text(value.citation_id, "citation_id_invalid"), _text(value.claim_id, "citation_claim_invalid"), _text(value.evidence_id, "citation_evidence_invalid"), _exact(value.relationship, CitationRelationship, "citation_relationship_wrong_type"), _text(value.source_record_id, "citation_record_invalid"), _text(value.source_version, "citation_version_invalid"), _text(value.snapshot_id, "citation_snapshot_invalid"), _digest(value.content_hash, "citation_hash_invalid"), _text(value.locator_ref, "citation_locator_invalid"), _exact(value.execution_status, ExecutionStatus, "citation_execution_wrong_type"), _exact(value.coverage_status, CoverageStatus, "citation_coverage_wrong_type"), _exact(value.result_status, ResultStatus, "citation_result_wrong_type"))
    if copied.citation_id != canonical_citation_id(copied):
        raise CanonicalValidationError("citation_identity_drift")
    return copied

def _copy_registry(value: ValidationRegistryInput) -> ValidationRegistryInput:
    _exact(value, ValidationRegistryInput, "registry_wrong_type")
    _check_registry_cardinality(value)
    identity = _exact(value.evaluator_identity, EvaluatorIdentityInput, "evaluator_identity_wrong_type")
    identity = EvaluatorIdentityInput(_text(identity.method, "evaluator_method_invalid"), _text(identity.version, "evaluator_version_invalid"))
    expectations: list[SemanticExpectationInput] = []
    for expectation_raw in value.semantic_expectations:
        expectation = _exact(expectation_raw, SemanticExpectationInput, "semantic_expectation_wrong_type")
        expectations.append(SemanticExpectationInput(_text(expectation.citation_id, "expectation_citation_invalid"), _digest(expectation.input_digest, "expectation_digest_invalid"), _text(expectation.method, "expectation_method_invalid"), _text(expectation.version, "expectation_version_invalid"), _exact(expectation.result, SemanticSupport, "expectation_result_wrong_type")))
    resolutions: list[ResolutionInput] = []
    for resolution_raw in value.resolutions:
        resolution = _exact(resolution_raw, ResolutionInput, "resolution_wrong_type")
        resolutions.append(ResolutionInput(_text(resolution.claim_id, "resolution_claim_invalid"), _exact(resolution.action, ResolutionAction, "resolution_action_wrong_type"), _text(resolution.record_id, "resolution_record_invalid"), _text(resolution.method, "resolution_method_invalid"), _text(resolution.version, "resolution_version_invalid"), None if resolution.comparison_id is None else _text(resolution.comparison_id, "resolution_comparison_invalid"), None if resolution.conflict_id is None else _text(resolution.conflict_id, "resolution_conflict_invalid")))
    comparisons = tuple(_copy_comparison(item) for item in value.comparisons)
    conflicts = tuple(_copy_conflict(item) for item in value.conflicts)
    return ValidationRegistryInput(_text(value.run_id, "registry_run_invalid"), _text(value.scope_id, "registry_scope_invalid"), tuple(_copy_claim(item) for item in value.claims), tuple(_copy_citation(item) for item in value.citations), tuple(_copy_evidence(item) for item in value.evidence), tuple(expectations), identity, comparisons, conflicts, tuple(resolutions), _text(value.configuration_version, "registry_configuration_version_invalid"))

def _copy_comparison(value: ComparisonInput) -> ComparisonInput:
    _exact(value, ComparisonInput, "comparison_wrong_type")
    _bounded_tuple(value.dimensions, 11, "comparison_dimension_cardinality_exceeded", type_code="comparison_dimensions_wrong_type")
    dimensions: list[DimensionInput] = []
    for raw in value.dimensions:
        item = _exact(raw, DimensionInput, "comparison_dimension_wrong_type")
        if type(item.applicable) is not bool:
            raise CanonicalValidationError("comparison_applicability_wrong_type")
        left = None if item.left_value is None else _text(item.left_value, "comparison_left_invalid")
        right = None if item.right_value is None else _text(item.right_value, "comparison_right_invalid")
        if item.applicable != (left is not None and right is not None):
            raise CanonicalValidationError("comparison_values_invalid")
        dimensions.append(DimensionInput(_exact(item.dimension, ComparabilityDimension, "comparison_dimension_enum_wrong_type"), item.applicable, left, right))
    copied = ComparisonInput(_text(value.comparison_id, "comparison_id_invalid"), _digest(value.artifact_hash, "comparison_hash_invalid"), tuple(dimensions), _exact(value.relation, ComparableFindingRelation, "comparison_relation_wrong_type"), _exact(value.source_unavailable, bool, "comparison_unavailable_wrong_type"))
    if tuple(item.dimension for item in copied.dimensions) != COMPARABILITY_DIMENSIONS or copied.artifact_hash != _comparison_hash(copied):
        raise CanonicalValidationError("comparison_authority_invalid")
    return copied

def _copy_conflict(value: ConflictInput) -> ConflictInput:
    _exact(value, ConflictInput, "conflict_wrong_type")
    copied = ConflictInput(_text(value.conflict_id, "conflict_id_invalid"), _digest(value.artifact_hash, "conflict_hash_invalid"), _text(value.comparison_id, "conflict_comparison_invalid"), _exact(value.outcome, ConflictOutcome, "conflict_outcome_wrong_type"))
    if copied.artifact_hash != _conflict_hash(copied):
        raise CanonicalValidationError("conflict_authority_invalid")
    return copied

def _check_scope_cardinality(value: ScopeInput) -> None:
    _bounded_tuple(value.drugs, 4, "scope_drug_cardinality_exceeded", type_code="scope_collection_wrong_type")
    _bounded_tuple(value.adverse_reactions, 8, "scope_adverse_reaction_cardinality_exceeded", type_code="scope_collection_wrong_type")
    _bounded_tuple(value.selected_sources, 4, "scope_source_cardinality_exceeded", type_code="scope_sources_wrong_type")
def _selected_task_sources(value: object, scope_sources: tuple[SourceType, ...]) -> tuple[SourceType, ...]:
    _bounded_tuple(value, 4, "selected_task_source_cardinality_exceeded", type_code="selected_task_sources_wrong_type")
    selected = cast(tuple[SourceType, ...], value)
    if any(type(item) is not SourceType for item in selected): raise CanonicalValidationError("selected_task_sources_wrong_type")
    if selected != tuple(source for source in scope_sources if source in set(selected)): raise CanonicalValidationError("selected_task_sources_invalid")
    return selected
def _check_evidence_cardinality(value: EvidenceInput) -> None:
    _bounded_tuple(value.locators, 1, "evidence_locator_cardinality_exceeded", type_code="evidence_collection_invalid")
    _bounded_tuple(value.numerical_facts, 100, "evidence_numerical_fact_cardinality_exceeded", type_code="evidence_collection_invalid")
    if type(value.permitted_claim_classes) is not frozenset or type(value.permitted_inference_uses) is not frozenset:
        raise CanonicalValidationError("evidence_permissions_invalid")
    if len(value.permitted_claim_classes) > len(ClaimClass):
        raise CanonicalValidationError("evidence_claim_class_cardinality_exceeded")
    if len(value.permitted_inference_uses) > len(InferenceUse):
        raise CanonicalValidationError("evidence_inference_use_cardinality_exceeded")

def _check_registry_cardinality(value: ValidationRegistryInput) -> None:
    checks = (
        (value.claims, 200, "registry_claim_cardinality_exceeded"),
        (value.resolutions, 200, "registry_resolution_cardinality_exceeded"),
        (value.citations, 400, "registry_citation_cardinality_exceeded"),
        (value.semantic_expectations, 400, "registry_semantic_expectation_cardinality_exceeded"),
        (value.evidence, 400, "registry_evidence_cardinality_exceeded"),
        (value.comparisons, 100, "registry_comparison_cardinality_exceeded"),
        (value.conflicts, 100, "registry_conflict_cardinality_exceeded"),
    )
    for values, maximum, code in checks:
        if type(values) is not tuple or len(values) > maximum:
            raise CanonicalValidationError(code)

def _registry_has_duplicate_identity(value: ValidationRegistryInput) -> bool:
    groups = (
        tuple(item.claim_id for item in value.claims), tuple(item.citation_id for item in value.citations), tuple(item.evidence_id for item in value.evidence),
        tuple(item.citation_id for item in value.semantic_expectations), tuple(item.claim_id for item in value.resolutions), tuple(item.comparison_id for item in value.comparisons),
        tuple(item.conflict_id for item in value.conflicts), tuple(item.comparison_id for item in value.conflicts),
    )
    return any(len(group) != len(set(group)) for group in groups)

def _check_nested_cardinality(value: ValidationRegistryInput) -> None:
    for claim in value.claims:
        if type(claim) is ClaimInput:
            _bounded_tuple(claim.citation_ids, 300, "claim_citation_cardinality_exceeded", type_code="claim_collection_invalid")
            _bounded_tuple(claim.presented_limitations, 100, "claim_limitation_cardinality_exceeded", type_code="claim_collection_invalid")
    for evidence in value.evidence:
        if type(evidence) is EvidenceInput:
            _check_evidence_cardinality(evidence)
    for comparison in value.comparisons:
        if type(comparison) is ComparisonInput:
            _bounded_tuple(comparison.dimensions, 11, "comparison_dimension_cardinality_exceeded", type_code="comparison_dimensions_wrong_type")

def _outer_cardinality(request: CanonicalReportRequest) -> None:
    _exact(request, CanonicalReportRequest, "request_wrong_type")
    _check_scope_cardinality(_exact(request.scope, ScopeInput, "scope_wrong_type")); _selected_task_sources(request.selected_task_sources, request.scope.selected_sources)
    _bounded_tuple(request.tasks, 4, "task_cardinality_exceeded", type_code="task_collection_wrong_type")
    for task in request.tasks:
        if type(task) is TerminalTaskInput and (type(task.evidence_refs) is not tuple or len(task.evidence_refs) > 100):
            raise CanonicalValidationError("task_evidence_cardinality_exceeded")
        if type(task) is TerminalTaskInput and type(task.outcome) is SourceOutcomeInput:
            _bounded_tuple(task.outcome.warning_codes, 100, "outcome_warning_cardinality_exceeded")
    synthesis = _exact(request.synthesis, SynthesisInput, "synthesis_wrong_type")
    checks = (
        (synthesis.claims, 200, "synthesis_claim_cardinality_exceeded"),
        (synthesis.citations, 400, "synthesis_citation_cardinality_exceeded"),
        (synthesis.comparison_refs, 100, "synthesis_comparison_cardinality_exceeded"),
        (synthesis.conflict_refs, 100, "synthesis_conflict_cardinality_exceeded"),
        (synthesis.warning_codes, 100, "synthesis_warning_cardinality_exceeded"),
    )
    for values, maximum, code in checks:
        if type(values) is not tuple or len(values) > maximum:
            raise CanonicalValidationError(code)
    registry = _exact(request.registry, ValidationRegistryInput, "registry_wrong_type")
    _check_registry_cardinality(registry)
    _check_nested_cardinality(registry)
def _copy_request(value: CanonicalReportRequest) -> CanonicalReportRequest:
    scope = _copy_scope(value.scope); source_plan_id = _text(value.source_plan_id, "source_plan_id_invalid"); selected_task_sources = _selected_task_sources(value.selected_task_sources, scope.selected_sources)
    if re.fullmatch(r"source-plan:sha256:[0-9a-f]{64}", source_plan_id) is None: raise CanonicalValidationError("source_plan_id_invalid")
    tasks = tuple(_copy_task(item) for item in value.tasks)
    synthesis = value.synthesis
    claim_refs = tuple(ClaimReferenceInput(_text(_exact(item, ClaimReferenceInput, "claim_reference_wrong_type").claim_id, "claim_reference_invalid")) for item in synthesis.claims)
    citation_refs = tuple(CitationReferenceInput(_text(_exact(item, CitationReferenceInput, "citation_reference_wrong_type").citation_id, "citation_reference_invalid"), _text(item.claim_id, "citation_reference_claim_invalid"), _text(item.evidence_id, "citation_reference_evidence_invalid")) for item in synthesis.citations)
    comparison_refs = tuple(ArtifactReferenceInput(_text(_exact(item, ArtifactReferenceInput, "comparison_reference_wrong_type").artifact_id, "comparison_reference_id_invalid"), _digest(item.artifact_hash, "comparison_reference_hash_invalid")) for item in synthesis.comparison_refs)
    conflict_refs = tuple(ArtifactReferenceInput(_text(_exact(item, ArtifactReferenceInput, "conflict_reference_wrong_type").artifact_id, "conflict_reference_id_invalid"), _digest(item.artifact_hash, "conflict_reference_hash_invalid")) for item in synthesis.conflict_refs)
    synthesis = SynthesisInput(_digest(synthesis.report_content_hash, "report_hash_invalid"), claim_refs, citation_refs, comparison_refs, conflict_refs, _reason_tuple(synthesis.warning_codes, "synthesis_warning_invalid"))
    registry = _copy_registry(value.registry)
    stored = value.stored_validation
    if stored is not None:
        stored = _exact(stored, StoredValidationInput, "stored_validation_wrong_type")
        if any(type(item) is not bool for item in (stored.structural_passed, stored.semantic_passed, stored.safety_passed)):
            raise CanonicalValidationError("stored_validation_gate_wrong_type")
    return CanonicalReportRequest(_text(value.run_id, "run_id_invalid"), _text(value.report_id, "report_id_invalid"), scope, source_plan_id, selected_task_sources, tasks, synthesis, registry, stored)
def _qualitative_form(code: QualitativeCode) -> tuple[SourceType, ClaimClass, InferenceUse, str]:
    values = {
        QualitativeCode.PUBMED_DESCRIPTIVE: (SourceType.PUBMED, ClaimClass.DESCRIPTIVE, InferenceUse.DESCRIPTIVE, "The bounded publication supplies descriptive evidence."),
        QualitativeCode.PUBMED_ASSOCIATIONAL: (SourceType.PUBMED, ClaimClass.ASSOCIATIONAL, InferenceUse.ASSOCIATIONAL, "The bounded publication supplies associational evidence."),
        QualitativeCode.PUBMED_CAUSAL: (SourceType.PUBMED, ClaimClass.CAUSAL, InferenceUse.CAUSAL, "The bounded publication supplies causal-analysis evidence."),
        QualitativeCode.PUBMED_CLINICAL: (SourceType.PUBMED, ClaimClass.DESCRIPTIVE, InferenceUse.CLINICAL, "The bounded publication supplies clinical research context."),
        QualitativeCode.PUBMED_LIMITATION: (SourceType.PUBMED, ClaimClass.METHODOLOGICAL_OR_LIMITATION, InferenceUse.METHODOLOGICAL_LIMITATION, "The bounded publication supplies methodological context."),
        QualitativeCode.DAILYMED_DESCRIPTIVE: (SourceType.DAILYMED, ClaimClass.DESCRIPTIVE, InferenceUse.DESCRIPTIVE, "The identified label section supplies descriptive labeling evidence."),
        QualitativeCode.DAILYMED_CLINICAL: (SourceType.DAILYMED, ClaimClass.DESCRIPTIVE, InferenceUse.CLINICAL, "The identified label section supplies clinical labeling context."),
        QualitativeCode.DAILYMED_LABELING: (SourceType.DAILYMED, ClaimClass.REGULATORY_OR_LABELING, InferenceUse.REGULATORY, "The identified label section supplies regulatory labeling evidence."),
        QualitativeCode.DAILYMED_LIMITATION: (SourceType.DAILYMED, ClaimClass.METHODOLOGICAL_OR_LIMITATION, InferenceUse.METHODOLOGICAL_LIMITATION, "The identified label section supplies methodological context."),
        QualitativeCode.FAERS_DESCRIPTIVE_CONTEXT: (SourceType.FAERS, ClaimClass.DESCRIPTIVE, InferenceUse.DESCRIPTIVE, f"The configured FAERS query supplies descriptive spontaneous-report context. {FAERS_MANDATORY_LIMITATIONS[1]}"),
        QualitativeCode.FAERS_LIMITATION: (SourceType.FAERS, ClaimClass.METHODOLOGICAL_OR_LIMITATION, InferenceUse.METHODOLOGICAL_LIMITATION, f"The configured FAERS query supplies methodological limitation context. {FAERS_MANDATORY_LIMITATIONS[1]}"),
        QualitativeCode.CADEC_AUXILIARY_CONTEXT: (SourceType.CADEC, ClaimClass.METHODOLOGICAL_OR_LIMITATION, InferenceUse.AUXILIARY_NLP_RETRIEVAL, "The approved CADEC corpus supplies auxiliary NLP and retrieval context only."),
        QualitativeCode.CADEC_LIMITATION: (SourceType.CADEC, ClaimClass.METHODOLOGICAL_OR_LIMITATION, InferenceUse.METHODOLOGICAL_LIMITATION, "The approved CADEC corpus supplies methodological limitation context only."),
    }
    return values[code]

def _source_semantics_allowed(source: SourceType, claim_class: ClaimClass, use: InferenceUse) -> bool:
    allowed = {
        SourceType.PUBMED: ({ClaimClass.DESCRIPTIVE, ClaimClass.ASSOCIATIONAL, ClaimClass.CAUSAL, ClaimClass.REGULATORY_OR_LABELING, ClaimClass.METHODOLOGICAL_OR_LIMITATION}, {InferenceUse.DESCRIPTIVE, InferenceUse.ASSOCIATIONAL, InferenceUse.CLINICAL, InferenceUse.CAUSAL, InferenceUse.METHODOLOGICAL_LIMITATION}),
        SourceType.DAILYMED: ({ClaimClass.DESCRIPTIVE, ClaimClass.REGULATORY_OR_LABELING, ClaimClass.METHODOLOGICAL_OR_LIMITATION}, {InferenceUse.DESCRIPTIVE, InferenceUse.CLINICAL, InferenceUse.REGULATORY, InferenceUse.METHODOLOGICAL_LIMITATION}),
        SourceType.FAERS: ({ClaimClass.DESCRIPTIVE, ClaimClass.METHODOLOGICAL_OR_LIMITATION}, {InferenceUse.DESCRIPTIVE, InferenceUse.METHODOLOGICAL_LIMITATION}),
        SourceType.CADEC: ({ClaimClass.METHODOLOGICAL_OR_LIMITATION}, {InferenceUse.AUXILIARY_NLP_RETRIEVAL, InferenceUse.METHODOLOGICAL_LIMITATION}),
    }
    classes, uses = allowed[source]
    return claim_class in classes and use in uses

def _mandatory_limitations(source: SourceType) -> tuple[str, ...]:
    if source is SourceType.FAERS:
        return tuple(FAERS_MANDATORY_LIMITATIONS)
    if source is SourceType.CADEC:
        return tuple(CADEC_MANDATORY_LIMITATIONS)
    return ()

def _faers_number(value: NumericalContextInput | NumericalFactInput) -> bool:
    return re.fullmatch(r"0|[1-9][0-9]*", value.value) is not None and tuple(getattr(value, name) for name in _COUNT_FIELDS[1:]) == _FAERS_NUMBER

def _comparison_hash(value: ComparisonInput) -> str:
    payload = {"comparison_id": value.comparison_id, "dimensions": value.dimensions, "relation": value.relation, "source_unavailable": value.source_unavailable}
    return sha256_digest(canonical_json(_primitive(payload)))

def _conflict_hash(value: ConflictInput) -> str:
    payload = {"conflict_id": value.conflict_id, "comparison_id": value.comparison_id, "outcome": value.outcome}
    return sha256_digest(canonical_json(_primitive(payload)))

def _task_bindings(tasks: tuple[TerminalTaskInput, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((item.task_id, sha256_digest(canonical_json(_primitive(item)))) for item in tasks)
def canonical_report_content_hash(request: CanonicalReportRequest) -> str:
    registry = request.registry
    citation_map = {item.citation_id: item for item in registry.citations}
    payload = {
        "run_id": request.run_id,
        "report_id": request.report_id,
        "scope": request.scope, "selected_task_sources": request.selected_task_sources,
        "source_task_bindings": _task_bindings(request.tasks),
        "claim_ids": tuple(item.claim_id for item in request.synthesis.claims),
        "citation_bindings": tuple((item.citation_id, item.claim_id, item.evidence_id, citation_map[item.citation_id].relationship if item.citation_id in citation_map else "unresolved") for item in request.synthesis.citations),
        "evidence_ids": tuple(item.evidence_id for item in registry.evidence),
        "comparison_bindings": tuple((item.artifact_id, item.artifact_hash) for item in request.synthesis.comparison_refs),
        "conflict_bindings": tuple((item.artifact_id, item.artifact_hash) for item in request.synthesis.conflict_refs),
        "warning_codes": request.synthesis.warning_codes,
        "evaluator_identity": registry.evaluator_identity,
        "semantic_expectations": registry.semantic_expectations,
        "resolutions": registry.resolutions,
    }
    return sha256_digest(canonical_json(_primitive(payload)))
def _aggregate_semantic_results(traces: tuple[CitationTrace, ...]) -> SemanticSupport:
    if any(item.result is SemanticSupport.UNSUPPORTED for item in traces):
        return SemanticSupport.UNSUPPORTED
    direct = tuple(item for item in traces if item.relationship is not CitationRelationship.CONTEXT_ONLY)
    if any(item.result is SemanticSupport.UNCERTAIN for item in direct):
        return SemanticSupport.UNCERTAIN
    if any(item.relationship is CitationRelationship.CONTRADICTS and item.result is SemanticSupport.SUPPORTED for item in traces):
        return SemanticSupport.UNCERTAIN
    if any(item.relationship is CitationRelationship.SUPPORTS and item.result is SemanticSupport.SUPPORTED for item in traces):
        return SemanticSupport.SUPPORTED
    return SemanticSupport.UNCERTAIN

def _governed_resolution(value: ResolutionInput | None, registry: ValidationRegistryInput) -> bool:
    if value is None or value.comparison_id is None or value.conflict_id is None:
        return False
    comparison = next((item for item in registry.comparisons if item.comparison_id == value.comparison_id), None)
    conflict = next((item for item in registry.conflicts if item.conflict_id == value.conflict_id), None)
    return comparison is not None and conflict is not None and conflict.comparison_id == comparison.comparison_id and conflict.outcome is ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH
def _validation_input_hash(request: CanonicalReportRequest) -> str:
    payload = {"run_id": request.run_id, "report_id": request.report_id, "scope": request.scope, "source_plan_id": request.source_plan_id, "selected_task_sources": request.selected_task_sources, "tasks": request.tasks, "synthesis": request.synthesis, "registry": request.registry}; return sha256_digest(canonical_json(_primitive(payload)))
def _receipt_content(value: ValidationReceipt) -> dict[str, object]:
    return {item.name: _primitive(getattr(value, item.name)) for item in fields(value) if item.name not in {"receipt_id", "receipt_content_hash"}}
def _build_validation_receipt(request: CanonicalReportRequest, summary: ValidationSummary, audits: tuple[ClaimAudit, ...]) -> ValidationReceipt:
    claim_results = []
    for audit in audits:
        citation_results = []
        for trace in audit.citation_traces:
            payload: dict[str, object] = {"citation_id": trace.citation_id, "input_digest": trace.input_digest, "method": trace.method, "version": trace.version, "result": trace.result, "relationship": trace.relationship}
            citation_results.append(ValidationCitationReceipt(derive_identity("validation-citation-result", _primitive(payload)), trace.citation_id, trace.input_digest, trace.method, trace.version, trace.result, trace.relationship))
        aggregate = None if audit.aggregate_result is None else _exact(audit.aggregate_result, SemanticSupport, "validation_receipt_aggregate_invalid")
        matching_resolutions = tuple(item for item in request.registry.resolutions if item.claim_id == audit.claim_id)
        resolution = matching_resolutions[0] if len(matching_resolutions) == 1 else None
        payload = {"claim_id": audit.claim_id, "stage1_passed": audit.stage1_passed, "stage1_reason_codes": audit.reason_codes, "citation_results": tuple(citation_results), "aggregate_result": aggregate, "resolution_action": None if resolution is None else resolution.action, "resolution_record_id": None if resolution is None else resolution.record_id, "resolution_method": None if resolution is None else resolution.method, "resolution_version": None if resolution is None else resolution.version, "comparison_id": None if resolution is None else resolution.comparison_id, "conflict_id": None if resolution is None else resolution.conflict_id, "formal_claim_accepted": audit.formal_claim_accepted}
        claim_results.append(ValidationClaimReceipt(derive_identity("validation-claim-result", _primitive(payload)), audit.claim_id, audit.stage1_passed, audit.reason_codes, tuple(citation_results), aggregate, None if resolution is None else resolution.action, None if resolution is None else resolution.record_id, None if resolution is None else resolution.method, None if resolution is None else resolution.version, None if resolution is None else resolution.comparison_id, None if resolution is None else resolution.conflict_id, audit.formal_claim_accepted))
    stage1_payload = tuple((item.claim_id, item.stage1_passed, item.reason_codes) for item in audits)
    identity = request.registry.evaluator_identity
    receipt = ValidationReceipt(M3_VALIDATION_RECEIPT_V1, "", "sha256:" + "0" * 64, request.run_id, request.report_id, request.synthesis.report_content_hash, _validation_input_hash(request), sha256_digest(canonical_json(_primitive(_task_bindings(request.tasks)))), derive_identity("validation-stage1-result", _primitive(stage1_payload)), identity.method, identity.version, tuple(claim_results), summary.structural_passed, summary.semantic_passed, summary.safety_passed, summary.reason_codes, M3_VALIDATION_POLICY_V1, request.registry.configuration_version)
    content = _receipt_content(receipt)
    return ValidationReceipt(receipt.marker, derive_identity("validation-receipt", content), sha256_digest(canonical_json(content)), receipt.run_id, receipt.report_id, receipt.report_content_hash, receipt.validation_input_hash, receipt.task_binding_hash, receipt.stage1_result_id, receipt.evaluator_method, receipt.evaluator_version, receipt.claim_results, receipt.structural_passed, receipt.semantic_passed, receipt.safety_passed, receipt.reason_codes, receipt.policy_version, receipt.configuration_version)

def _copy_validation_receipt(value: ValidationReceipt, expected: ValidationReceipt) -> ValidationReceipt:
    _exact(value, ValidationReceipt, "validation_receipt_wrong_type")
    if type(value.reason_codes) is not tuple or len(value.reason_codes) != len(expected.reason_codes):
        raise CanonicalValidationError("validation_receipt_summary_reason_cardinality_mismatch")
    if type(value.claim_results) is not tuple or len(value.claim_results) != len(expected.claim_results):
        raise CanonicalValidationError("validation_receipt_claim_cardinality_mismatch")
    claims = []
    for raw_claim, expected_claim in zip(value.claim_results, expected.claim_results, strict=True):
        claim = _exact(raw_claim, ValidationClaimReceipt, "validation_receipt_claim_wrong_type")
        if type(claim.stage1_reason_codes) is not tuple or len(claim.stage1_reason_codes) != len(expected_claim.stage1_reason_codes):
            raise CanonicalValidationError("validation_receipt_reason_cardinality_mismatch")
        if type(claim.citation_results) is not tuple or len(claim.citation_results) != len(expected_claim.citation_results):
            raise CanonicalValidationError("validation_receipt_citation_cardinality_mismatch")
        citations = []
        for raw_citation in claim.citation_results:
            item = _exact(raw_citation, ValidationCitationReceipt, "validation_receipt_citation_wrong_type")
            copied = ValidationCitationReceipt(_text(item.citation_result_id, "validation_receipt_citation_identity_invalid"), _text(item.citation_id, "validation_receipt_citation_id_invalid"), _digest(item.input_digest, "validation_receipt_input_digest_invalid"), _text(item.method, "validation_receipt_method_invalid"), _text(item.version, "validation_receipt_version_invalid"), _exact(item.result, SemanticSupport, "validation_receipt_result_invalid"), _exact(item.relationship, CitationRelationship, "validation_receipt_relationship_invalid"))
            payload: dict[str, object] = {"citation_id": copied.citation_id, "input_digest": copied.input_digest, "method": copied.method, "version": copied.version, "result": copied.result, "relationship": copied.relationship}
            if copied.citation_result_id != derive_identity("validation-citation-result", _primitive(payload)):
                raise CanonicalValidationError("validation_receipt_citation_identity_drift")
            citations.append(copied)
        resolution = None if claim.resolution_action is None else _exact(claim.resolution_action, ResolutionAction, "validation_receipt_resolution_invalid")
        resolution_values = (claim.resolution_record_id, claim.resolution_method, claim.resolution_version)
        if resolution is None and any(item is not None for item in resolution_values) or resolution is not None and any(item is None for item in resolution_values):
            raise CanonicalValidationError("validation_receipt_resolution_binding_invalid")
        copied_resolution = tuple(None if item is None else _text(item, "validation_receipt_resolution_text_invalid") for item in resolution_values)
        governed_values = (claim.comparison_id, claim.conflict_id)
        copied_governed = tuple(None if item is None else _text(item, "validation_receipt_governed_id_invalid") for item in governed_values)
        aggregate = None if claim.aggregate_result is None else _exact(claim.aggregate_result, SemanticSupport, "validation_receipt_aggregate_invalid")
        copied_claim = ValidationClaimReceipt(_text(claim.claim_result_id, "validation_receipt_claim_identity_invalid"), _text(claim.claim_id, "validation_receipt_claim_id_invalid"), _exact(claim.stage1_passed, bool, "validation_receipt_stage1_invalid"), _reason_tuple(claim.stage1_reason_codes, "validation_receipt_reason_invalid"), tuple(citations), aggregate, resolution, copied_resolution[0], copied_resolution[1], copied_resolution[2], copied_governed[0], copied_governed[1], _exact(claim.formal_claim_accepted, bool, "validation_receipt_acceptance_invalid"))
        payload = {"claim_id": copied_claim.claim_id, "stage1_passed": copied_claim.stage1_passed, "stage1_reason_codes": copied_claim.stage1_reason_codes, "citation_results": copied_claim.citation_results, "aggregate_result": copied_claim.aggregate_result, "resolution_action": copied_claim.resolution_action, "resolution_record_id": copied_claim.resolution_record_id, "resolution_method": copied_claim.resolution_method, "resolution_version": copied_claim.resolution_version, "comparison_id": copied_claim.comparison_id, "conflict_id": copied_claim.conflict_id, "formal_claim_accepted": copied_claim.formal_claim_accepted}
        if copied_claim.claim_result_id != derive_identity("validation-claim-result", _primitive(payload)):
            raise CanonicalValidationError("validation_receipt_claim_identity_drift")
        claims.append(copied_claim)
    copied_receipt = ValidationReceipt(_text(value.marker, "validation_receipt_marker_invalid"), _text(value.receipt_id, "validation_receipt_identity_invalid"), _digest(value.receipt_content_hash, "validation_receipt_content_hash_invalid"), _text(value.run_id, "validation_receipt_run_invalid"), _text(value.report_id, "validation_receipt_report_invalid"), _digest(value.report_content_hash, "validation_receipt_report_hash_invalid"), _digest(value.validation_input_hash, "validation_receipt_input_hash_invalid"), _digest(value.task_binding_hash, "validation_receipt_task_hash_invalid"), _text(value.stage1_result_id, "validation_receipt_stage1_identity_invalid"), _text(value.evaluator_method, "validation_receipt_method_invalid"), _text(value.evaluator_version, "validation_receipt_version_invalid"), tuple(claims), _exact(value.structural_passed, bool, "validation_receipt_summary_invalid"), _exact(value.semantic_passed, bool, "validation_receipt_summary_invalid"), _exact(value.safety_passed, bool, "validation_receipt_summary_invalid"), _reason_tuple(value.reason_codes, "validation_receipt_summary_reason_invalid"), _text(value.policy_version, "validation_receipt_policy_invalid"), _text(value.configuration_version, "validation_receipt_configuration_invalid"))
    content = _receipt_content(copied_receipt)
    if copied_receipt.receipt_content_hash != sha256_digest(canonical_json(content)):
        raise CanonicalValidationError("validation_receipt_content_hash_drift")
    if copied_receipt.receipt_id != derive_identity("validation-receipt", content):
        raise CanonicalValidationError("validation_receipt_identity_drift")
    return copied_receipt

def verify_validation_receipt(receipt: ValidationReceipt, *, request: CanonicalReportRequest, audit: ReportValidationAudit) -> ValidationReceipt:
    _outer_cardinality(request)
    value = _copy_request(request)
    audit = _exact(audit, ReportValidationAudit, "validation_receipt_audit_wrong_type")
    expected = _build_validation_receipt(value, audit.summary, audit.claims)
    copied = _copy_validation_receipt(receipt, expected)
    if copied.marker != M3_VALIDATION_RECEIPT_V1 or copied.policy_version != M3_VALIDATION_POLICY_V1:
        raise CanonicalValidationError("validation_receipt_policy_drift")
    if (copied.evaluator_method, copied.evaluator_version) != (expected.evaluator_method, expected.evaluator_version):
        raise CanonicalValidationError("validation_receipt_evaluator_drift")
    if copied != expected:
        raise CanonicalValidationError("validation_receipt_binding_drift")
    return copied

def _payload_object(value: object, model: type[Any], code: str) -> dict[object, object]:
    expected = {item.name for item in fields(model)}
    if type(value) is not dict or set(value) != expected:
        raise CanonicalValidationError(code)
    return value

def _payload_list(value: object, maximum: int, code: str) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise CanonicalValidationError(code)
    return value

def _payload_enum(value: object, expected: type[_E], code: str) -> _E:
    if type(value) is not str:
        raise CanonicalValidationError(code)
    try:
        return expected(value)
    except ValueError as error:
        raise CanonicalValidationError(code) from error

def canonical_validation_receipt_payload(receipt: ValidationReceipt) -> dict[str, object]:
    copied = _copy_validation_receipt(receipt, receipt)
    if copied.marker != M3_VALIDATION_RECEIPT_V1 or copied.policy_version != M3_VALIDATION_POLICY_V1:
        raise CanonicalValidationError("validation_receipt_policy_drift")
    payload = json.loads(canonical_json(_primitive(copied)))
    if type(payload) is not dict:
        raise CanonicalValidationError("validation_receipt_payload_invalid")
    return payload

def validation_receipt_from_payload(payload: object) -> ValidationReceipt:
    raw = _payload_object(payload, ValidationReceipt, "validation_receipt_payload_keys_invalid")
    raw_reasons = _payload_list(raw["reason_codes"], 100, "validation_receipt_payload_reason_cardinality_exceeded")
    raw_claims = _payload_list(raw["claim_results"], 200, "validation_receipt_payload_claim_cardinality_exceeded")
    claim_rows = []
    total_citations = 0
    for raw_claim_value in raw_claims:
        raw_claim = _payload_object(raw_claim_value, ValidationClaimReceipt, "validation_receipt_payload_claim_keys_invalid")
        claim_reasons = _payload_list(raw_claim["stage1_reason_codes"], 100, "validation_receipt_payload_claim_reason_cardinality_exceeded")
        raw_citations = _payload_list(raw_claim["citation_results"], 300, "validation_receipt_payload_citation_cardinality_exceeded")
        total_citations += len(raw_citations)
        claim_rows.append((raw_claim, claim_reasons, raw_citations))
    if total_citations > 400:
        raise CanonicalValidationError("validation_receipt_payload_total_citation_cardinality_exceeded")
    claims: list[ValidationClaimReceipt] = []
    for raw_claim, claim_reasons, raw_citations in claim_rows:
        citations: list[ValidationCitationReceipt] = []
        for raw_citation_value in raw_citations:
            item = _payload_object(raw_citation_value, ValidationCitationReceipt, "validation_receipt_payload_citation_keys_invalid")
            citations.append(ValidationCitationReceipt(_text(item["citation_result_id"], "validation_receipt_citation_identity_invalid"), _text(item["citation_id"], "validation_receipt_citation_id_invalid"), _digest(item["input_digest"], "validation_receipt_input_digest_invalid"), _text(item["method"], "validation_receipt_method_invalid"), _text(item["version"], "validation_receipt_version_invalid"), _payload_enum(item["result"], SemanticSupport, "validation_receipt_result_invalid"), _payload_enum(item["relationship"], CitationRelationship, "validation_receipt_relationship_invalid")))
        aggregate = None if raw_claim["aggregate_result"] is None else _payload_enum(raw_claim["aggregate_result"], SemanticSupport, "validation_receipt_aggregate_invalid")
        action = None if raw_claim["resolution_action"] is None else _payload_enum(raw_claim["resolution_action"], ResolutionAction, "validation_receipt_resolution_invalid")
        optional_text = tuple(None if raw_claim[name] is None else _text(raw_claim[name], "validation_receipt_resolution_text_invalid") for name in ("resolution_record_id", "resolution_method", "resolution_version"))
        governed_text = tuple(None if raw_claim[name] is None else _text(raw_claim[name], "validation_receipt_governed_id_invalid") for name in ("comparison_id", "conflict_id"))
        claims.append(ValidationClaimReceipt(_text(raw_claim["claim_result_id"], "validation_receipt_claim_identity_invalid"), _text(raw_claim["claim_id"], "validation_receipt_claim_id_invalid"), _exact(raw_claim["stage1_passed"], bool, "validation_receipt_stage1_invalid"), _reason_tuple(tuple(claim_reasons), "validation_receipt_reason_invalid"), tuple(citations), aggregate, action, optional_text[0], optional_text[1], optional_text[2], governed_text[0], governed_text[1], _exact(raw_claim["formal_claim_accepted"], bool, "validation_receipt_acceptance_invalid")))
    receipt = ValidationReceipt(_text(raw["marker"], "validation_receipt_marker_invalid"), _text(raw["receipt_id"], "validation_receipt_identity_invalid"), _digest(raw["receipt_content_hash"], "validation_receipt_content_hash_invalid"), _text(raw["run_id"], "validation_receipt_run_invalid"), _text(raw["report_id"], "validation_receipt_report_invalid"), _digest(raw["report_content_hash"], "validation_receipt_report_hash_invalid"), _digest(raw["validation_input_hash"], "validation_receipt_input_hash_invalid"), _digest(raw["task_binding_hash"], "validation_receipt_task_hash_invalid"), _text(raw["stage1_result_id"], "validation_receipt_stage1_identity_invalid"), _text(raw["evaluator_method"], "validation_receipt_method_invalid"), _text(raw["evaluator_version"], "validation_receipt_version_invalid"), tuple(claims), _exact(raw["structural_passed"], bool, "validation_receipt_summary_invalid"), _exact(raw["semantic_passed"], bool, "validation_receipt_summary_invalid"), _exact(raw["safety_passed"], bool, "validation_receipt_summary_invalid"), _reason_tuple(tuple(raw_reasons), "validation_receipt_summary_reason_invalid"), _text(raw["policy_version"], "validation_receipt_policy_invalid"), _text(raw["configuration_version"], "validation_receipt_configuration_invalid"))
    copied = _copy_validation_receipt(receipt, receipt)
    if copied.marker != M3_VALIDATION_RECEIPT_V1 or copied.policy_version != M3_VALIDATION_POLICY_V1:
        raise CanonicalValidationError("validation_receipt_policy_drift")
    return copied

def canonical_validate_report(
    request: CanonicalReportRequest,
    *,
    mode: ValidationMode,
    semantic_result_provider: SemanticResultProvider | None = None,
) -> ReportValidationAudit:
    _outer_cardinality(request)
    mode = _exact(mode, ValidationMode, "validation_mode_wrong_type")
    value = _copy_request(request)
    registry = value.registry
    identity_duplicate = _registry_has_duplicate_identity(registry)
    if _REPORT_ID.fullmatch(value.report_id) is None or _RUN_ID.fullmatch(value.run_id) is None:
        raise CanonicalValidationError("report_id_invalid")
    if mode is ValidationMode.ASSESS and value.stored_validation is not None: raise CanonicalValidationError("stored_validation_forbidden_in_assess")
    if mode is ValidationMode.VERIFY_BINDING and semantic_result_provider is not None: raise CanonicalValidationError("semantic_provider_forbidden_in_verify")
    structural: set[str] = set()
    safety: set[str] = set()
    semantic: set[str] = set()
    tasks = value.tasks
    synthesis = value.synthesis
    if identity_duplicate:
        structural.add("registry_identity_duplicate")
    if value.run_id != registry.run_id:
        structural.add("unauthorized_run")
    if value.scope.scope_id != registry.scope_id:
        structural.add("unauthorized_scope")
    task_sources = tuple(item.source for item in tasks)
    if task_sources != value.selected_task_sources or len(set(task_sources)) != len(task_sources):
        structural.add("selected_source_task_mismatch")
    for task in tasks:
        expected_task_id = f"source-task:{value.run_id.removeprefix('run:')}:{task.source.value}"
        if task.task_id != expected_task_id:
            structural.add("source_task_identity_drift")
        if task.acquisition.run_id != value.run_id:
            structural.add("source_not_in_authorized_run")
        if task.outcome.configured_bounds != ExecutionBoundsInput(value.scope.max_query_characters, value.scope.max_pages, value.scope.max_records, value.scope.max_payload_bytes, value.scope.max_total_seconds): structural.add("source_bounds_scope_mismatch")
    references = tuple((task, ref) for task in tasks for ref in task.evidence_refs)
    if len({ref.evidence_id for _, ref in references}) != len(references):
        structural.add("duplicate_evidence_reference")
    authorities = tuple((ref.source, ref.snapshot_id, ref.content_hash, ref.locator_ref) for _, ref in references)
    if len(set(authorities)) != len(authorities):
        structural.add("duplicate_durable_evidence_authority")
    if tuple(ref.evidence_id for _, ref in references) != tuple(item.evidence_id for item in registry.evidence):
        structural.add("evidence_registry_mismatch")
    reference_map = {} if identity_duplicate else {ref.evidence_id: (task, ref) for task, ref in references}
    for registered_evidence in registry.evidence:
        pair = reference_map.get(registered_evidence.evidence_id)
        if registered_evidence.authorized_run_id != value.run_id:
            structural.add("source_not_in_authorized_run")
        if pair is None or (pair[1].source, pair[1].snapshot_id, pair[1].content_hash, (pair[1].locator_ref,)) != (registered_evidence.source, registered_evidence.snapshot_id, registered_evidence.content_hash, registered_evidence.locators):
            structural.add("evidence_registry_authority_drift")
        elif pair[0].acquisition.snapshot_id != registered_evidence.snapshot_id:
            structural.add("evidence_acquisition_snapshot_drift")
    required_warnings = {warning for task in tasks for warning in task.outcome.warning_codes}
    for task in tasks:
        if task.source is SourceType.FAERS:
            required_warnings.add("faers_mandatory_limitations")
        if task.source is SourceType.CADEC:
            required_warnings.add("cadec_mandatory_limitations")
    if synthesis.warning_codes != tuple(sorted(required_warnings)):
        safety.add("mandatory_coverage_warning_missing")
    formal_claims = tuple(item for item in registry.claims if item.inclusion is ClaimInclusion.FORMAL)
    removed_claims = tuple(item for item in registry.claims if item.inclusion is ClaimInclusion.REMOVED)
    formal_citations = tuple(item for item in registry.citations if item.claim_id in {claim.claim_id for claim in formal_claims})
    if tuple(item.claim_id for item in synthesis.claims) != tuple(item.claim_id for item in formal_claims):
        structural.add("claim_registry_mismatch")
    if tuple(item.citation_id for item in synthesis.citations) != tuple(item.citation_id for item in formal_citations):
        structural.add("citation_registry_mismatch")
    if not identity_duplicate and synthesis.report_content_hash != canonical_report_content_hash(value):
        structural.add("report_content_binding_mismatch")
    claims = {} if identity_duplicate else {item.claim_id: item for item in registry.claims}
    citations = {} if identity_duplicate else {item.citation_id: item for item in registry.citations}
    evidences = {} if identity_duplicate else {item.evidence_id: item for item in registry.evidence}
    resolutions = {} if identity_duplicate else {item.claim_id: item for item in registry.resolutions}
    expectation_map = {} if identity_duplicate else {item.citation_id: item for item in registry.semantic_expectations}
    if tuple(item.citation_id for item in registry.semantic_expectations) != tuple(item.citation_id for item in formal_citations):
        structural.add("semantic_expectation_registry_mismatch")
    if any(item.claim_id not in claims for item in registry.resolutions):
        structural.add("resolution_claim_missing")
    if any(item.claim_id not in claims or item.evidence_id not in evidences for item in registry.citations): structural.add("registry_reference_graph_invalid")
    if any(item.claim_id not in resolutions or resolutions[item.claim_id].action is not ResolutionAction.REMOVED for item in removed_claims):
        structural.add("removed_candidate_requires_recorded_removal")
    stage1: list[tuple[ClaimInput, tuple[tuple[CitationInput, EvidenceInput], ...], tuple[str, ...]]] = []
    for claim in formal_claims:
        claim_reasons: set[str] = set()
        refs = tuple(item for item in synthesis.citations if item.claim_id == claim.claim_id)
        if not refs or claim.citation_ids != tuple(item.citation_id for item in refs):
            claim_reasons.add("claim_citation_binding_mismatch")
        resolved_pairs_list: list[tuple[CitationInput, EvidenceInput]] = []
        supports = False
        for ref in refs:
            citation = citations.get(ref.citation_id)
            resolved_evidence = evidences.get(ref.evidence_id)
            pair = reference_map.get(ref.evidence_id)
            if citation is None or resolved_evidence is None or pair is None:
                claim_reasons.add("citation_or_evidence_not_registered")
                continue
            task, durable = pair
            outcome = task.outcome
            if citation.claim_id != claim.claim_id or citation.evidence_id != ref.evidence_id or ref.claim_id != claim.claim_id:
                claim_reasons.add("claim_citation_evidence_binding_mismatch")
            if (durable.source, durable.snapshot_id, durable.content_hash, durable.locator_ref) != (resolved_evidence.source, resolved_evidence.snapshot_id, resolved_evidence.content_hash, citation.locator_ref) or (citation.source_record_id, citation.source_version, citation.snapshot_id, citation.content_hash) != (resolved_evidence.source_record_id, resolved_evidence.source_version, resolved_evidence.snapshot_id, resolved_evidence.content_hash) or citation.locator_ref not in resolved_evidence.locators:
                claim_reasons.add("citation_evidence_lineage_drift")
            if (citation.execution_status, citation.coverage_status, citation.result_status) != (outcome.execution_status, outcome.coverage_status, outcome.result_status) or outcome.result_status is not ResultStatus.MATCHES or outcome.valid_result_count < 1:
                claim_reasons.add("coverage_qualifier_untruthful")
            if claim.source is not resolved_evidence.source or not _source_semantics_allowed(resolved_evidence.source, claim.claim_class, claim.inference_use) or claim.claim_class not in resolved_evidence.permitted_claim_classes or claim.inference_use not in resolved_evidence.permitted_inference_uses:
                claim_reasons.add("policy_source_semantics_not_permitted")
            if not set(_mandatory_limitations(resolved_evidence.source)).issubset(claim.presented_limitations):
                claim_reasons.add("policy_mandatory_limitation_missing")
            supports |= citation.relationship is CitationRelationship.SUPPORTS
            resolved_pairs_list.append((citation, resolved_evidence))
        if not supports:
            claim_reasons.add("formal_claim_requires_supporting_citation")
        if claim.numerical_context is not None and not any(citation.relationship is CitationRelationship.SUPPORTS and any((fact.value, fact.unit, fact.denominator, fact.comparator, fact.time_basis, fact.population_scope, fact.locator_ref) == (claim.numerical_context.value, claim.numerical_context.unit, claim.numerical_context.denominator, claim.numerical_context.comparator, claim.numerical_context.time_basis, claim.numerical_context.population_scope, citation.locator_ref) for fact in evidence.numerical_facts) for citation, evidence in resolved_pairs_list):
            claim_reasons.add("numerical_claim_not_bound_to_authoritative_fact")
        for citation, evidence in resolved_pairs_list:
            expectation, digest = expectation_map.get(citation.citation_id), canonical_semantic_input_digest(value.run_id, claim, citation, evidence)
            if expectation is None or expectation.input_digest != digest or (expectation.method, expectation.version) != (registry.evaluator_identity.method, registry.evaluator_identity.version): claim_reasons.add("semantic_expectation_binding_drift")
        for reason in claim_reasons:
            (safety if reason.startswith("policy_") else structural).add(reason)
        stage1.append((claim, tuple(resolved_pairs_list), tuple(sorted(claim_reasons))))
    conflict_outcomes: list[tuple[str, ConflictOutcome]] = []
    comparison_map = {} if identity_duplicate else {item.comparison_id: item for item in registry.comparisons}
    conflict_map = {} if identity_duplicate else {item.comparison_id: item for item in registry.conflicts}
    if tuple(comparison_map) != tuple(item.comparison_id for item in registry.conflicts): structural.add("comparison_conflict_registry_mismatch")
    if tuple(item.artifact_id for item in synthesis.comparison_refs) != tuple(item.comparison_id for item in registry.comparisons) or tuple(item.artifact_id for item in synthesis.conflict_refs) != tuple(item.conflict_id for item in registry.conflicts):
        structural.add("comparison_conflict_registry_mismatch")
    for reference in synthesis.comparison_refs:
        comparison = comparison_map.get(reference.artifact_id)
        if comparison is None or reference.artifact_hash != comparison.artifact_hash:
            structural.add("comparison_hash_drift")
            continue
        applicable = tuple(item for item in comparison.dimensions if item.applicable)
        expected_conflict = ConflictOutcome.SOURCE_UNAVAILABLE if comparison.source_unavailable else ConflictOutcome.INSUFFICIENT_INFORMATION if not applicable else ConflictOutcome.APPARENT_DIFFERENCE_SCOPE_MISMATCH if any(item.left_value != item.right_value for item in applicable) else ConflictOutcome.CONSISTENT_COMPARABLE_SCOPE if comparison.relation is ComparableFindingRelation.CONSISTENT else ConflictOutcome.UNRESOLVED_CONFLICT_COMPARABLE_SCOPE
        conflict = conflict_map.get(comparison.comparison_id)
        conflict_ref = next((item for item in synthesis.conflict_refs if conflict is not None and item.artifact_id == conflict.conflict_id), None)
        if conflict is None or conflict_ref is None or conflict.outcome is not expected_conflict or conflict_ref.artifact_hash != conflict.artifact_hash:
            structural.add("conflict_classification_or_hash_drift")
        else:
            conflict_outcomes.append((conflict.conflict_id, expected_conflict))
    audits: list[ClaimAudit] = []
    if structural or safety:
        semantic.add("stage1_failed_before_semantic_evaluation")
        audits.extend(ClaimAudit(claim.claim_id, not reasons, reasons, (), False, None) for claim, _, reasons in stage1)
    else:
        for claim, resolved_pairs, _ in stage1:
            traces: list[CitationTrace] = []
            for citation, evidence in resolved_pairs:
                expectation = expectation_map.get(citation.citation_id)
                digest = canonical_semantic_input_digest(value.run_id, claim, citation, evidence)
                if expectation is None or expectation.input_digest != digest or (expectation.method, expectation.version) != (registry.evaluator_identity.method, registry.evaluator_identity.version):
                    raise CanonicalValidationError("semantic_expectation_binding_drift")
                if mode is ValidationMode.ASSESS:
                    if semantic_result_provider is None:
                        raise CanonicalValidationError("semantic_result_provider_missing")
                    try:
                        raw_result = semantic_result_provider.evaluate(SemanticEvaluationInput(value.run_id, claim, citation, evidence))
                    except Exception as error:
                        raise CanonicalValidationError("semantic_result_acquisition_failed") from error
                    result = _exact(raw_result, SemanticResultInput, "semantic_result_wrong_type")
                    result = SemanticResultInput(_exact(result.result, SemanticSupport, "semantic_result_enum_wrong_type"), _text(result.method, "semantic_result_method_invalid"), _text(result.version, "semantic_result_version_invalid"))
                    if (result.result, result.method, result.version) != (expectation.result, expectation.method, expectation.version):
                        raise CanonicalValidationError("semantic_result_expectation_mismatch")
                else:
                    result = SemanticResultInput(expectation.result, expectation.method, expectation.version)
                traces.append(CitationTrace(citation.citation_id, digest, result.method, result.version, result.result, citation.relationship))
            combined = _aggregate_semantic_results(tuple(traces))
            resolution = resolutions.get(claim.claim_id)
            confirmed_contradiction = any(item.relationship is CitationRelationship.CONTRADICTS and item.result is SemanticSupport.SUPPORTED for item in traces)
            no_governed_binding = resolution is not None and resolution.comparison_id is None and resolution.conflict_id is None
            adjudicated = resolution is not None and resolution.action is ResolutionAction.ADJUDICATED_TO_SUPPORTED and (confirmed_contradiction and _governed_resolution(resolution, registry) or not confirmed_contradiction and no_governed_binding)
            accepted = combined is SemanticSupport.SUPPORTED and resolution is None or combined is SemanticSupport.UNCERTAIN and adjudicated
            if not accepted:
                semantic.add("material_claim_not_accepted")
            audits.append(ClaimAudit(claim.claim_id, True, (), tuple(traces), accepted, combined))
    all_reasons = tuple(sorted(structural | safety | semantic))
    summary = ValidationSummary(not structural, not semantic, not safety, all_reasons)
    receipt = _build_validation_receipt(value, summary, tuple(audits)) if mode is ValidationMode.ASSESS else None
    if mode is ValidationMode.VERIFY_BINDING:
        stored = value.stored_validation
        if stored is not None and type(stored.reason_codes) is not tuple:
            raise CanonicalValidationError("stored_validation_reason_invalid")
        if stored is not None and len(stored.reason_codes) != len(summary.reason_codes):
            raise CanonicalValidationError("stored_validation_reason_cardinality_mismatch")
        stored_reasons = None if stored is None else _reason_tuple(stored.reason_codes, "stored_validation_reason_invalid")
        if stored is None or (stored.structural_passed, stored.semantic_passed, stored.safety_passed, stored_reasons) != (summary.structural_passed, summary.semantic_passed, summary.safety_passed, summary.reason_codes):
            structural.add("stored_validation_binding_mismatch")
            all_reasons = tuple(sorted(structural | safety | semantic))
            summary = ValidationSummary(False, not semantic, not safety, all_reasons)
    return ReportValidationAudit(summary, tuple(audits), tuple(conflict_outcomes), receipt)
