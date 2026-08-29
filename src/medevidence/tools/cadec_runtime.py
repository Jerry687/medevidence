"""Deterministic transient search over the exact approved local CADEC asset."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import Field, StringConstraints, ValidationError, model_validator

from medevidence.domain import (
    CADEC_APPROVED_DOCUMENT_COUNT,
    CADEC_ARCHIVE_SHA256,
    CADEC_CANONICAL_DOCUMENT_COUNT,
    CADEC_EXTERNAL_MANIFEST_SHA256,
    CADEC_MANDATORY_LIMITATIONS,
    ArtifactId,
    CadecSplit,
    CorpusDocumentId,
    CoverageStatus,
    ExecutionBounds,
    ExecutionStatus,
    QueryId,
    ResearchScope,
    ResultStatus,
    ScopeId,
    SourceOutcome,
    SourceRecordId,
    SourceType,
    derive_identity,
)
from medevidence.domain.identifiers import DurableModel

CADEC_BM25_K1: Final = 0.9
CADEC_BM25_B: Final = 0.4
CADEC_RESULT_LIMIT: Final = 20
CADEC_LIMITATION_WARNING: Final = "cadec_mandatory_limitations"

_EXACT_CADEC_VERIFICATION: Final[tuple[tuple[str, object], ...]] = (
    ("archive_sha256", CADEC_ARCHIVE_SHA256),
    ("archive_bytes", 1_870_497),
    ("manifest_sha256", CADEC_EXTERNAL_MANIFEST_SHA256),
    ("manifest_bytes", 1_699_979),
    ("inventory_sha256", "eabcff5564e2266bb8b749bf4b68c164d36aeb0b511fb775674baf762b9b10b8"),
    ("inventory_entry_count", 5_005),
    ("inventory_file_count", 5_000),
    ("inventory_directory_count", 5),
    ("inventory_uncompressed_bytes", 1_627_015),
    ("canonical_document_count", CADEC_CANONICAL_DOCUMENT_COUNT),
    (
        "canonical_document_sha256",
        "0007626fa17053350628a9d3a619bceaada9db9a6e660e113fa6c4cd8681fb2a",
    ),
    ("approved_document_count", CADEC_APPROVED_DOCUMENT_COUNT),
    (
        "approved_document_sha256",
        "7f168cc7496d2b140182e30d96afdf4367ce67f122e30447e0ecbbb17358cfa6",
    ),
    ("excluded_document_count", 2),
    (
        "excluded_document_sha256",
        "14b01844c6471d597e1b0c5e9a9483a32992b3c0a5158ef7966e171f42aa84dd",
    ),
    ("train_count", 992),
    ("train_membership_sha256", "e533c904637a86b447ce4cee5973b4041ff8de1679fcb073e78a0525835c8329"),
    ("development_count", 119),
    (
        "development_membership_sha256",
        "dd219af2c42b717fb1df7d24b04de9bb031c099d4deb513091c6d49d4b2b799f",
    ),
    ("test_count", 137),
    ("test_membership_sha256", "6bf824a4fe7a708a836cf08b007734622bb02c2fecf0d1441febfb0103a3e26a"),
    ("encoding_exception_verified", True),
    ("empty_document_count", 2),
    ("malformed_row_count", 5),
    ("original_reference_binding_limitation_count", 2),
    ("meddra_reference_binding_limitation_count", 44),
    ("sct_reference_binding_limitation_count", 45),
    ("raw_out_of_order_transition_count", 43),
    ("raw_out_of_order_document_count", 26),
    ("provider_gold_only", True),
    ("predicted_artifact_admitted", False),
    ("output_document_count", 1_248),
    ("output_annotation_count", 24_478),
    ("output_original_annotation_count", 9_089),
    ("output_meddra_annotation_count", 6_300),
    ("output_sct_annotation_count", 9_089),
    ("output_locator_count", 24_478),
    ("all_validation_passed", True),
)

type RawSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type PrefixedSha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class CadecRuntimeErrorCode(StrEnum):
    """Stable failure categories for later source-outcome mapping."""

    INVALID_SCOPE = "invalid_scope"
    QUERY_BOUND = "query_bound"
    PLAN_INTEGRITY = "plan_integrity"
    ASSET_INTEGRITY = "asset_integrity"
    MATERIALIZATION = "materialization"
    SEARCH_INTEGRITY = "search_integrity"


class CadecRuntimeError(ValueError):
    """Fail-closed local CADEC error that never carries partial evidence refs."""

    evidence_refs: tuple[()] = ()
    execution_status: Final = ExecutionStatus.FAILED
    coverage_status: Final = CoverageStatus.UNAVAILABLE
    result_status: Final = ResultStatus.INDETERMINATE
    warning_codes: Final = (CADEC_LIMITATION_WARNING,)
    limitations: Final = CADEC_MANDATORY_LIMITATIONS

    def __init__(self, code: CadecRuntimeErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class CadecVerifiedCorpus(DurableModel):
    """Complete payload-free copy of the exact loader verification summary."""

    archive_sha256: RawSha256
    archive_bytes: int = Field(ge=0)
    manifest_sha256: RawSha256
    manifest_bytes: int = Field(ge=0)
    inventory_sha256: RawSha256
    inventory_entry_count: int = Field(ge=0)
    inventory_file_count: int = Field(ge=0)
    inventory_directory_count: int = Field(ge=0)
    inventory_uncompressed_bytes: int = Field(ge=0)
    canonical_document_count: int = Field(ge=0)
    canonical_document_sha256: RawSha256
    approved_document_count: int = Field(ge=0)
    approved_document_sha256: RawSha256
    excluded_document_count: int = Field(ge=0)
    excluded_document_sha256: RawSha256
    train_count: int = Field(ge=0)
    train_membership_sha256: RawSha256
    development_count: int = Field(ge=0)
    development_membership_sha256: RawSha256
    test_count: int = Field(ge=0)
    test_membership_sha256: RawSha256
    encoding_exception_verified: bool
    empty_document_count: int = Field(ge=0)
    malformed_row_count: int = Field(ge=0)
    original_reference_binding_limitation_count: int = Field(ge=0)
    meddra_reference_binding_limitation_count: int = Field(ge=0)
    sct_reference_binding_limitation_count: int = Field(ge=0)
    raw_out_of_order_transition_count: int = Field(ge=0)
    raw_out_of_order_document_count: int = Field(ge=0)
    provider_gold_only: bool
    predicted_artifact_admitted: bool
    output_document_count: int = Field(ge=0)
    output_annotation_count: int = Field(ge=0)
    output_original_annotation_count: int = Field(ge=0)
    output_meddra_annotation_count: int = Field(ge=0)
    output_sct_annotation_count: int = Field(ge=0)
    output_locator_count: int = Field(ge=0)
    all_validation_passed: bool

    @model_validator(mode="after")
    def validate_complete_admission(self) -> Self:
        observed = tuple((name, getattr(self, name)) for name, _value in _EXACT_CADEC_VERIFICATION)
        if observed != _EXACT_CADEC_VERIFICATION:
            raise ValueError("CADEC verification is not the complete exact approved admission")
        return self


class CadecLocalSearchPlan(DurableModel):
    """Pure exact plan for one later local CADEC archive search."""

    schema_version: Literal["m3.cadec.local-search-plan.v1"] = "m3.cadec.local-search-plan.v1"
    source: Literal[SourceType.CADEC] = SourceType.CADEC
    scope_id: ScopeId
    query: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    query_id: QueryId
    archive_sha256: RawSha256
    manifest_sha256: RawSha256
    bm25_k1: float
    bm25_b: float
    tokenizer: Literal["unicode_lower_alnum_v1"] = "unicode_lower_alnum_v1"
    result_limit: Literal[20] = CADEC_RESULT_LIMIT

    @model_validator(mode="after")
    def validate_exact_plan(self) -> Self:
        if (
            self.archive_sha256 != CADEC_ARCHIVE_SHA256
            or self.manifest_sha256 != CADEC_EXTERNAL_MANIFEST_SHA256
            or self.bm25_k1 != CADEC_BM25_K1
            or self.bm25_b != CADEC_BM25_B
            or self.result_limit != CADEC_RESULT_LIMIT
        ):
            raise ValueError("CADEC local-search plan differs from the exact approved config")
        if self.query_id != _query_id_for_plan(self):
            raise ValueError("CADEC local-search plan query identity differs from its content")
        return self


class CadecDocumentEvidenceRef(DurableModel):
    """Document-level auxiliary reference; it contains no corpus text."""

    source: Literal[SourceType.CADEC] = SourceType.CADEC
    auxiliary_only: Literal[True] = True
    document_id: CorpusDocumentId
    document_record_id: SourceRecordId
    member_path: str
    member_sha256: PrefixedSha256
    artifact_id: ArtifactId
    artifact_sha256: PrefixedSha256
    content_sha256: PrefixedSha256
    split: CadecSplit
    split_membership_sha256: PrefixedSha256
    provenance_context_id: SourceRecordId
    provenance_lineage_artifact_ids: tuple[ArtifactId, ...]
    locator_kind: Literal["cadec_whole_document"] = "cadec_whole_document"
    locator_ref: SourceRecordId
    char_start: Literal[0] = 0
    char_end: int = Field(gt=0)
    score: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_document_reference(self) -> Self:
        if self.member_path != f"cadec/text/{self.document_id}.txt":
            raise ValueError("CADEC evidence member path is not canonical")
        if not (self.member_sha256 == self.artifact_sha256 == self.content_sha256):
            raise ValueError("CADEC evidence hashes must bind one exact text member")
        if self.provenance_lineage_artifact_ids:
            raise ValueError("CADEC document provenance must have no parent artifact")
        expected_locator = _document_locator_ref(
            document_id=self.document_id,
            document_record_id=self.document_record_id,
            member_path=self.member_path,
            content_sha256=self.content_sha256,
            split=self.split,
            split_membership_sha256=self.split_membership_sha256,
            artifact_id=self.artifact_id,
            provenance_context_id=self.provenance_context_id,
            char_end=self.char_end,
        )
        if self.locator_ref != expected_locator:
            raise ValueError("CADEC whole-document locator identity differs from its content")
        return self


class CadecSearchResult(DurableModel):
    """Source-neutral deterministic CADEC result with auxiliary refs only."""

    schema_version: Literal["m3.cadec.search-result.v1"] = "m3.cadec.search-result.v1"
    source: Literal[SourceType.CADEC] = SourceType.CADEC
    scope_id: ScopeId
    query: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    query_id: QueryId
    bm25_k1: float = CADEC_BM25_K1
    bm25_b: float = CADEC_BM25_B
    result_limit: Literal[20] = CADEC_RESULT_LIMIT
    scope_bounds: ExecutionBounds
    documents_scored: int = Field(ge=0)
    verification: CadecVerifiedCorpus
    evidence_refs: tuple[CadecDocumentEvidenceRef, ...] = Field(max_length=CADEC_RESULT_LIMIT)
    outcome: SourceOutcome
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_complete_result(self) -> Self:
        expected_count = self.verification.approved_document_count - (
            self.verification.empty_document_count
        )
        if self.documents_scored != expected_count:
            raise ValueError("CADEC scored-document count differs from all eligible documents")
        if self.bm25_k1 != CADEC_BM25_K1 or self.bm25_b != CADEC_BM25_B:
            raise ValueError("CADEC BM25 configuration differs from the exact approved values")
        if self.limitations != tuple(CADEC_MANDATORY_LIMITATIONS):
            raise ValueError("CADEC mandatory limitations differ from the governed text")
        if self.outcome.source is not SourceType.CADEC or self.outcome.query_id != self.query_id:
            raise ValueError("CADEC outcome identity differs from the exact local query")
        if self.outcome.configured_bounds != self.scope_bounds:
            raise ValueError("CADEC outcome bounds differ from its carried exact scope bounds")
        expected_result = ResultStatus.MATCHES if self.evidence_refs else ResultStatus.NO_MATCH
        if (
            self.outcome.execution_status is not ExecutionStatus.SUCCEEDED
            or self.outcome.coverage_status is not CoverageStatus.COMPLETE
            or self.outcome.result_status is not expected_result
            or self.outcome.valid_result_count != len(self.evidence_refs)
            or self.outcome.pages_completed != 1
            or self.outcome.truncated
            or self.outcome.warning_codes != (CADEC_LIMITATION_WARNING,)
            or self.outcome.failure_id is not None
        ):
            raise ValueError("CADEC outcome differs from the complete local-search contract")
        expected_order = tuple(
            sorted(
                self.evidence_refs,
                key=lambda item: (-item.score, item.document_id.encode("utf-8")),
            )
        )
        if self.evidence_refs != expected_order:
            raise ValueError("CADEC evidence refs are not in deterministic bytewise order")
        if len({item.document_id for item in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError("CADEC evidence refs contain duplicate documents")
        return self


def plan_cadec_local_search(scope: ResearchScope) -> CadecLocalSearchPlan:
    """Build the exact local CADEC plan without file, search, or persistence I/O."""

    return _build_plan(_validated_cadec_scope(scope))


def _build_plan(scope: ResearchScope) -> CadecLocalSearchPlan:
    query = " ".join(
        (
            *(item.preferred_term for item in scope.drugs),
            *(item.preferred_term for item in scope.adverse_reactions),
        )
    )
    if len(query) > scope.query_bounds.max_query_characters:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.QUERY_BOUND,
            "canonical CADEC query exceeds the configured scope query bound",
        )
    provisional = CadecLocalSearchPlan.model_construct(
        scope_id=scope.scope_id,
        query=query,
        query_id="pending",
        archive_sha256=CADEC_ARCHIVE_SHA256,
        manifest_sha256=CADEC_EXTERNAL_MANIFEST_SHA256,
        bm25_k1=CADEC_BM25_K1,
        bm25_b=CADEC_BM25_B,
        result_limit=CADEC_RESULT_LIMIT,
    )
    return CadecLocalSearchPlan(
        scope_id=scope.scope_id,
        query=query,
        query_id=_query_id_for_plan(provisional),
        archive_sha256=CADEC_ARCHIVE_SHA256,
        manifest_sha256=CADEC_EXTERNAL_MANIFEST_SHA256,
        bm25_k1=CADEC_BM25_K1,
        bm25_b=CADEC_BM25_B,
        result_limit=CADEC_RESULT_LIMIT,
    )


def _query_id_for_plan(plan: CadecLocalSearchPlan) -> str:
    return derive_identity(
        "cadec-local-query",
        {
            "scope_id": plan.scope_id,
            "query": plan.query,
            "archive_sha256": plan.archive_sha256,
            "manifest_sha256": plan.manifest_sha256,
            "bm25_k1": plan.bm25_k1,
            "bm25_b": plan.bm25_b,
            "tokenizer": plan.tokenizer,
            "result_limit": plan.result_limit,
        },
    )


def reconstruct_cadec_local_search_plan(
    candidate: CadecLocalSearchPlan,
    scope: ResearchScope,
) -> CadecLocalSearchPlan:
    try:
        if type(candidate) is not CadecLocalSearchPlan:
            raise TypeError("plan must be the exact CadecLocalSearchPlan type")
        copied = CadecLocalSearchPlan.model_validate(
            candidate.model_dump(mode="python"), strict=True
        )
        expected = _build_plan(scope)
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.PLAN_INTEGRITY,
            "CADEC local-search plan failed closed reconstruction",
        ) from error
    if copied != candidate or copied != expected:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.PLAN_INTEGRITY,
            "CADEC local-search plan differs from canonical reconstruction",
        )
    return copied


def reconstruct_cadec_search_result(
    candidate: object,
    *,
    scope: ResearchScope,
    plan: CadecLocalSearchPlan,
) -> CadecSearchResult:
    """Reconstruct and bind an untrusted adapter result to its exact pure plan."""

    try:
        validated_scope = _validated_cadec_scope(scope)
        validated_plan = reconstruct_cadec_local_search_plan(plan, validated_scope)
        if type(candidate) is not CadecSearchResult:
            raise TypeError("result must be the exact CadecSearchResult type")
        copied = CadecSearchResult.model_validate(candidate.model_dump(mode="python"), strict=True)
        if copied != candidate or (
            copied.scope_id != validated_scope.scope_id
            or copied.query != validated_plan.query
            or copied.query_id != validated_plan.query_id
            or copied.bm25_k1 != validated_plan.bm25_k1
            or copied.bm25_b != validated_plan.bm25_b
            or copied.result_limit != validated_plan.result_limit
            or copied.scope_bounds != ExecutionBounds.from_scope(validated_scope)
        ):
            raise ValueError("result differs from its exact plan")
        return copied
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.SEARCH_INTEGRITY,
            "CADEC local-search result failed closed reconstruction",
        ) from error


def cadec_verification_input_identity(plan: CadecLocalSearchPlan) -> str:
    """Bind verification to every exact frozen asset and corpus-admission identity."""

    plan = CadecLocalSearchPlan.model_validate(plan.model_dump(mode="python"), strict=True)
    return derive_identity(
        "cadec-verification-input",
        {
            "scope_id": plan.scope_id,
            "archive_sha256": plan.archive_sha256,
            "manifest_sha256": plan.manifest_sha256,
            "exact_verification": _EXACT_CADEC_VERIFICATION,
        },
    )


def cadec_search_input_identity(plan: CadecLocalSearchPlan) -> str:
    """Bind search to the exact canonical query, corpus identities, and BM25 config."""

    plan = CadecLocalSearchPlan.model_validate(plan.model_dump(mode="python"), strict=True)
    return derive_identity("cadec-search-input", plan)


def _validated_cadec_scope(scope: ResearchScope) -> ResearchScope:
    try:
        if type(scope) is not ResearchScope:
            raise TypeError("scope must be the exact ResearchScope type")
        validated = ResearchScope.model_validate(scope.model_dump(mode="python"), strict=True)
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.INVALID_SCOPE,
            "CADEC local search requires a valid exact research scope",
        ) from error
    if SourceType.CADEC not in validated.selected_sources:
        raise CadecRuntimeError(
            CadecRuntimeErrorCode.INVALID_SCOPE,
            "CADEC local search requires CADEC selected in the research scope",
        )
    return validated


def _document_locator_ref(
    *,
    document_id: str,
    document_record_id: str,
    member_path: str,
    content_sha256: str,
    split: CadecSplit,
    split_membership_sha256: str,
    artifact_id: str,
    provenance_context_id: str,
    char_end: int,
) -> str:
    return derive_identity(
        "cadec-whole-document-locator",
        {
            "source": SourceType.CADEC,
            "document_id": document_id,
            "document_record_id": document_record_id,
            "member_path": member_path,
            "content_sha256": content_sha256,
            "split": split,
            "split_membership_sha256": split_membership_sha256,
            "artifact_id": artifact_id,
            "provenance_context_id": provenance_context_id,
            "char_start": 0,
            "char_end": char_end,
        },
    )


__all__ = [
    "CADEC_BM25_B",
    "CADEC_BM25_K1",
    "CADEC_RESULT_LIMIT",
    "CadecDocumentEvidenceRef",
    "CadecLocalSearchPlan",
    "CadecRuntimeError",
    "CadecRuntimeErrorCode",
    "CadecSearchResult",
    "CadecVerifiedCorpus",
    "cadec_search_input_identity",
    "cadec_verification_input_identity",
    "plan_cadec_local_search",
    "reconstruct_cadec_local_search_plan",
    "reconstruct_cadec_search_result",
]
