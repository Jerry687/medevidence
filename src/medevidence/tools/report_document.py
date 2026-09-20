"""Store-verified report material followed by deterministic draft rendering."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol
from urllib.parse import quote, urlsplit

from medevidence.domain import (
    CADEC_MANDATORY_LIMITATIONS,
    FAERS_MANDATORY_LIMITATIONS,
    RESEARCH_ONLY_NOTICE,
    CoverageStatus,
    ExecutionStatus,
    ResultStatus,
    SourceType,
    canonical_json,
    sha256_digest,
)

from .report_validation import (
    CanonicalReportRequest,
    CanonicalValidationError,
    ClaimInclusion,
    ComparisonInput,
    ConflictInput,
    NumericalContextInput,
    ScopeInput,
    ValidationMode,
    ValidationReceipt,
    ValidationReceiptV2,
    canonical_report_content_hash,
    canonical_validate_report,
    canonical_validation_receipt_payload,
    validation_receipt_from_payload,
    verify_validation_receipt,
)

REPORT_DOCUMENT_VERSION_V1 = "MEDEVIDENCE_REPORT_DOCUMENT_V1"
_MAX_URL = 2048
_MAX_LINEAGE = 20
_MAX_LINEAGE_ITEM = 512
_MARKDOWN_META = re.compile(r"([\\`*_{}\[\]()#+.!|~>-])")


def _utc(value: datetime, code: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CanonicalValidationError(code)
    return value.astimezone(UTC)


def _source_url(value: str) -> str:
    if (
        type(value) is not str
        or len(value) > _MAX_URL
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
    ):
        raise CanonicalValidationError("report_source_url_unsafe")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise CanonicalValidationError("report_source_url_unsafe") from error
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
        or parsed.fragment
        or "\\" in value
        or any(char in value for char in "<>\"'")
    ):
        raise CanonicalValidationError("report_source_url_unsafe")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceProvenanceV1:
    """Claimed retrieved metadata checked against a verified source reader."""

    evidence_id: str
    source: SourceType
    source_record_id: str
    source_version: str
    snapshot_id: str
    content_hash: str
    source_url: str | None
    lookup_key: str | None
    retrieved_at: datetime
    transformation_lineage: tuple[str, ...]

    def __post_init__(self) -> None:
        if (self.source_url is None) == (self.lookup_key is None):
            raise CanonicalValidationError("report_provenance_locator_missing_or_ambiguous")
        if self.source_url is not None:
            _source_url(self.source_url)
        if self.lookup_key is not None and (
            type(self.lookup_key) is not str
            or not self.lookup_key.strip()
            or len(self.lookup_key) > _MAX_URL
            or any(ord(char) < 32 or ord(char) == 127 for char in self.lookup_key)
        ):
            raise CanonicalValidationError("report_provenance_lookup_key_invalid")
        _utc(self.retrieved_at, "report_provenance_retrieval_time_invalid")
        if (
            type(self.transformation_lineage) is not tuple
            or not 1 <= len(self.transformation_lineage) <= _MAX_LINEAGE
            or any(
                type(item) is not str
                or not item.strip()
                or len(item) > _MAX_LINEAGE_ITEM
                or any(ord(char) < 32 or ord(char) == 127 for char in item)
                for item in self.transformation_lineage
            )
        ):
            raise CanonicalValidationError("report_provenance_lineage_invalid")


class ReceiptReadPort(Protocol):
    """Server-owned readback of an independently persisted final receipt."""

    def load_receipt(self, receipt_id: str) -> Mapping[str, object] | None: ...


class VerifiedProvenanceReadPort(Protocol):
    """Server-owned reader that verifies immutable source-snapshot lineage."""

    def load_verified_provenance(
        self,
        *,
        run_id: str,
        evidence_id: str,
        source: SourceType,
        source_record_id: str,
        source_version: str,
        snapshot_id: str,
        content_hash: str,
    ) -> EvidenceProvenanceV1 | None: ...


@dataclass(frozen=True, slots=True)
class ReportCitationV1:
    citation_id: str
    evidence_id: str
    relationship: str
    source: SourceType
    source_record_id: str
    source_version: str
    snapshot_id: str
    content_hash: str
    exact_locator: str
    source_url: str | None
    lookup_key: str | None
    retrieved_at: datetime
    transformation_lineage: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportClaimV1:
    claim_id: str
    statement: str
    source: SourceType
    claim_class: str
    inference_use: str
    limitations: tuple[str, ...]
    citations: tuple[ReportCitationV1, ...]
    numerical_context: NumericalContextInput | None = None


@dataclass(frozen=True, slots=True)
class SourceCoverageV1:
    source: SourceType
    selected_for_execution: bool
    query_id: str | None
    execution_status: ExecutionStatus | None
    coverage_status: CoverageStatus | None
    result_status: ResultStatus | None
    valid_result_count: int | None
    truncated: bool | None
    warning_codes: tuple[str, ...]
    interpretation: str
    retrieval_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class ReportDocumentV1:
    """Immutable display content; human export approval is a separate operation."""

    marker: str
    report_id: str
    run_id: str
    scope_id: str
    source_plan_id: str
    scope: ScopeInput
    generated_at: datetime
    retrieval_as_of: datetime | None
    report_content_hash: str
    validation_receipt_id: str
    validation_receipt_hash: str
    review_status: str
    research_only_notice: str
    coverage: tuple[SourceCoverageV1, ...]
    claims: tuple[ReportClaimV1, ...]
    evidence_provenance: tuple[EvidenceProvenanceV1, ...]
    comparisons: tuple[ComparisonInput, ...]
    conflicts: tuple[ConflictInput, ...]
    warning_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    render_document_hash: str


def _plain(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return (
            _utc(value, "report_document_time_invalid")
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if type(value) is tuple:
        return [_plain(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        payload = {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
        if type(value) is ReportClaimV1 and value.numerical_context is None:
            del payload["numerical_context"]
        return payload
    raise CanonicalValidationError("report_document_value_invalid")


def _document_payload(document: ReportDocumentV1, *, include_hash: bool) -> dict[str, object]:
    result = {item.name: _plain(getattr(document, item.name)) for item in fields(document)}
    if not include_hash:
        del result["render_document_hash"]
    return result


def _verified_document(document: ReportDocumentV1) -> dict[str, object]:
    if type(document) is not ReportDocumentV1 or document.marker != REPORT_DOCUMENT_VERSION_V1:
        raise CanonicalValidationError("report_document_type_invalid")
    payload = _document_payload(document, include_hash=False)
    if document.render_document_hash != sha256_digest(canonical_json(payload)):
        raise CanonicalValidationError("report_document_render_hash_drift")
    return payload


def _coverage_interpretation(
    execution: ExecutionStatus, coverage: CoverageStatus, result: ResultStatus
) -> str:
    if execution is ExecutionStatus.SUCCEEDED and coverage is CoverageStatus.COMPLETE:
        return "complete_no_match" if result is ResultStatus.NO_MATCH else "complete_matches"
    if coverage is CoverageStatus.PARTIAL and result is ResultStatus.MATCHES:
        return "partial_matches_not_exhaustive"
    return "indeterminate_not_evidence_of_absence"


def build_report_document(
    request: CanonicalReportRequest,
    stored_receipt: ValidationReceipt | ValidationReceiptV2 | dict[str, object],
    *,
    source_provenance: tuple[EvidenceProvenanceV1, ...],
    generated_at: datetime,
    receipt_store: ReceiptReadPort,
    provenance_store: VerifiedProvenanceReadPort,
) -> ReportDocumentV1:
    """Render only material that matches server-owned receipt and source readers."""

    generated = _utc(generated_at, "report_generated_time_invalid")
    if receipt_store is None or provenance_store is None:
        raise CanonicalValidationError("report_authority_store_missing")
    if type(source_provenance) is not tuple:
        raise CanonicalValidationError("report_provenance_collection_invalid")
    if type(stored_receipt) is dict:
        receipt = validation_receipt_from_payload(stored_receipt)
    elif isinstance(stored_receipt, (ValidationReceipt, ValidationReceiptV2)):
        receipt = validation_receipt_from_payload(
            canonical_validation_receipt_payload(stored_receipt)
        )
    else:
        raise CanonicalValidationError("report_stored_receipt_missing")
    persisted_payload = receipt_store.load_receipt(receipt.receipt_id)
    if persisted_payload is None or not isinstance(persisted_payload, Mapping):
        raise CanonicalValidationError("report_receipt_not_stored")
    persisted_receipt = validation_receipt_from_payload(dict(persisted_payload))
    if persisted_receipt != receipt:
        raise CanonicalValidationError("report_receipt_store_mismatch")
    audit = canonical_validate_report(request, mode=ValidationMode.VERIFY_BINDING)
    if (
        not audit.summary.passed
        or not all((receipt.structural_passed, receipt.semantic_passed, receipt.safety_passed))
        or receipt.reason_codes
    ):
        raise CanonicalValidationError("report_final_validation_not_passed")
    receipt = verify_validation_receipt(receipt, request=request, audit=audit)
    if (
        receipt.report_content_hash != canonical_report_content_hash(request)
        or receipt.report_content_hash != request.synthesis.report_content_hash
    ):
        raise CanonicalValidationError("report_content_binding_drift")

    evidence = request.registry.evidence
    if len(source_provenance) != len(evidence) or any(
        type(item) is not EvidenceProvenanceV1 for item in source_provenance
    ):
        raise CanonicalValidationError("report_provenance_coverage_mismatch")
    provenance_by_id = {item.evidence_id: item for item in source_provenance}
    if len(provenance_by_id) != len(source_provenance) or set(provenance_by_id) != {
        item.evidence_id for item in evidence
    }:
        raise CanonicalValidationError("report_provenance_coverage_mismatch")
    for item in evidence:
        provenance = provenance_by_id[item.evidence_id]
        if (
            provenance.source,
            provenance.source_record_id,
            provenance.source_version,
            provenance.snapshot_id,
            provenance.content_hash,
        ) != (
            item.source,
            item.source_record_id,
            item.source_version,
            item.snapshot_id,
            item.content_hash,
        ):
            raise CanonicalValidationError("report_provenance_authority_drift")
        verified = provenance_store.load_verified_provenance(
            run_id=request.run_id,
            evidence_id=item.evidence_id,
            source=item.source,
            source_record_id=item.source_record_id,
            source_version=item.source_version,
            snapshot_id=item.snapshot_id,
            content_hash=item.content_hash,
        )
        if type(verified) is not EvidenceProvenanceV1 or verified != provenance:
            raise CanonicalValidationError("report_provenance_store_mismatch")
        if provenance.retrieved_at > generated:
            raise CanonicalValidationError("report_provenance_after_generation")
    ordered_provenance = tuple(provenance_by_id[item.evidence_id] for item in evidence)
    citation_map = {item.citation_id: item for item in request.registry.citations}
    claim_map = {item.claim_id: item for item in request.registry.claims}
    claims: list[ReportClaimV1] = []
    for reference in request.synthesis.claims:
        claim = claim_map[reference.claim_id]
        if claim.inclusion is not ClaimInclusion.FORMAL:
            raise CanonicalValidationError("report_nonformal_claim_visible")
        citations: list[ReportCitationV1] = []
        for citation_id in claim.citation_ids:
            citation = citation_map[citation_id]
            provenance = provenance_by_id[citation.evidence_id]
            citations.append(
                ReportCitationV1(
                    citation.citation_id,
                    citation.evidence_id,
                    citation.relationship.value,
                    provenance.source,
                    provenance.source_record_id,
                    provenance.source_version,
                    provenance.snapshot_id,
                    provenance.content_hash,
                    citation.locator_ref,
                    provenance.source_url,
                    provenance.lookup_key,
                    provenance.retrieved_at,
                    provenance.transformation_lineage,
                )
            )
        claims.append(
            ReportClaimV1(
                claim.claim_id,
                claim.statement,
                claim.source,
                claim.claim_class.value,
                claim.inference_use.value,
                claim.presented_limitations,
                tuple(citations),
                claim.numerical_context,
            )
        )
    tasks = {task.source: task for task in request.tasks}
    coverage_rows: list[SourceCoverageV1] = []
    limitations: list[str] = []
    for source in request.scope.selected_sources:
        task = tasks.get(source)
        retrieval_times = tuple(
            item.retrieved_at for item in ordered_provenance if item.source is source
        )
        if task is None:
            coverage_rows.append(
                SourceCoverageV1(
                    source,
                    False,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    (),
                    "not_executed_see_source_plan",
                    None,
                )
            )
            limitations.append(
                f"{source.value}: source was not executed; "
                "consult the bound source plan for its reason."
            )
            continue
        outcome = task.outcome
        interpretation = _coverage_interpretation(
            outcome.execution_status, outcome.coverage_status, outcome.result_status
        )
        coverage_rows.append(
            SourceCoverageV1(
                source,
                True,
                outcome.query_id,
                outcome.execution_status,
                outcome.coverage_status,
                outcome.result_status,
                outcome.valid_result_count,
                outcome.truncated,
                outcome.warning_codes,
                interpretation,
                max(retrieval_times) if retrieval_times else None,
            )
        )
        if interpretation == "partial_matches_not_exhaustive":
            limitations.append(
                f"{source.value}: coverage is partial; retained matches are not exhaustive."
            )
        elif interpretation == "indeterminate_not_evidence_of_absence":
            limitations.append(
                f"{source.value}: coverage is incomplete or failed; zero results are indeterminate."
            )
        if source is SourceType.FAERS:
            limitations.extend(FAERS_MANDATORY_LIMITATIONS)
        elif source is SourceType.CADEC:
            limitations.extend(CADEC_MANDATORY_LIMITATIONS)
    for rendered_claim in claims:
        limitations.extend(rendered_claim.limitations)
    for conflict in request.registry.conflicts:
        if conflict.outcome.value.startswith("unresolved"):
            limitations.append(
                f"{conflict.conflict_id}: comparable-source conflict remains unresolved."
            )
    deduplicated_limitations = tuple(dict.fromkeys(limitations))
    document = ReportDocumentV1(
        REPORT_DOCUMENT_VERSION_V1,
        request.report_id,
        request.run_id,
        request.scope.scope_id,
        request.source_plan_id,
        request.scope,
        generated,
        max((item.retrieved_at for item in ordered_provenance), default=None),
        receipt.report_content_hash,
        receipt.receipt_id,
        receipt.receipt_content_hash,
        "awaiting_human_export_approval",
        RESEARCH_ONLY_NOTICE,
        tuple(coverage_rows),
        tuple(claims),
        ordered_provenance,
        request.registry.comparisons,
        request.registry.conflicts,
        request.synthesis.warning_codes,
        deduplicated_limitations,
        "",
    )
    from dataclasses import replace

    return replace(
        document,
        render_document_hash=sha256_digest(
            canonical_json(_document_payload(document, include_hash=False))
        ),
    )


def report_document_to_json(document: ReportDocumentV1) -> str:
    """Return canonical UTF-8-ready JSON text with a terminal newline."""

    _verified_document(document)
    return canonical_json(_document_payload(document, include_hash=True)) + "\n"


def _md(value: object) -> str:
    return _MARKDOWN_META.sub(r"\\\1", html.escape(str(value), quote=True)).replace("\n", " ")


def _md_fields(*pairs: tuple[str, object]) -> str:
    return "; ".join(f"{label}={_md(value)}" for label, value in pairs)


def report_document_to_markdown(document: ReportDocumentV1) -> str:
    """Render safe Markdown without interpreting evidence text as markup."""

    _verified_document(document)
    lines = [
        "# Research evidence report",
        "",
        _md(document.research_only_notice),
        "",
        f"Report: {_md(document.report_id)}  ",
        f"Run: {_md(document.run_id)}  ",
        f"Scope: {_md(document.scope_id)}  ",
        f"Source plan: {_md(document.source_plan_id)}  ",
        f"Report content hash: {_md(document.report_content_hash)}  ",
        "Validation receipt: "
        + _md_fields(
            ("id", document.validation_receipt_id),
            ("hash", document.validation_receipt_hash),
        ),
        f"Review status: {_md(document.review_status)}  ",
        f"Generated: {_md(_plain(document.generated_at))}  ",
        "Retrieved as of: "
        + _md(_plain(document.retrieval_as_of) if document.retrieval_as_of else "not available"),
        "",
        "## Scope",
        "",
        f"Drugs: {_md(document.scope.drugs)}  ",
        f"Adverse reactions: {_md(document.scope.adverse_reactions)}  ",
        f"Date range: {_md(document.scope.date_range)}  ",
        f"Comparison intent: {_md(document.scope.comparison_intent.value)}",
        "",
        "## Source coverage",
        "",
    ]
    for row in document.coverage:
        lines.append(
            f"- {_md(row.source.value)}: "
            + _md_fields(
                ("interpretation", row.interpretation),
                (
                    "execution",
                    row.execution_status.value if row.execution_status else "not executed",
                ),
                ("coverage", row.coverage_status.value if row.coverage_status else "not available"),
                ("result", row.result_status.value if row.result_status else "indeterminate"),
                ("query", row.query_id or "none"),
                (
                    "records",
                    row.valid_result_count
                    if row.valid_result_count is not None
                    else "not available",
                ),
                (
                    "retrieved as of",
                    _plain(row.retrieval_as_of) if row.retrieval_as_of else "not available",
                ),
            )
        )
    lines.extend(["", "## Claims and citations", ""])
    if not document.claims:
        lines.append("No formal claims were accepted for this report.")
    for claim in document.claims:
        lines.append(f"### {_md(claim.claim_id)}")
        lines.append("")
        lines.append(_md(claim.statement))
        lines.append("")
        lines.append(
            _md_fields(
                ("source", claim.source.value),
                ("class", claim.claim_class),
                ("inference", claim.inference_use),
            )
        )
        if claim.numerical_context is not None:
            context = claim.numerical_context
            lines.append(
                "Numerical context: "
                + _md_fields(
                    ("value", context.value),
                    ("unit", context.unit),
                    ("denominator", context.denominator),
                    ("comparator", context.comparator),
                    ("time basis", context.time_basis),
                    ("population scope", context.population_scope),
                )
            )
        for citation in claim.citations:
            source_link = (
                "[source record](" + quote(citation.source_url, safe="/:?#[]@!$&'*+,;=%-._~") + ")"
                if citation.source_url
                else f"lookup key: {_md(citation.lookup_key)}"
            )
            lines.append(
                f"- Citation {_md(citation.citation_id)} ({_md(citation.relationship)}): "
                + source_link
                + "; "
                + _md_fields(
                    ("record", citation.source_record_id),
                    ("version", citation.source_version),
                    ("snapshot", citation.snapshot_id),
                    ("content hash", citation.content_hash),
                    ("locator", citation.exact_locator),
                    ("retrieved", _plain(citation.retrieved_at)),
                    ("lineage", citation.transformation_lineage),
                )
            )
        if claim.limitations:
            lines.append("Limitations: " + "; ".join(_md(item) for item in claim.limitations))
        lines.append("")
    lines.extend(["## Comparisons and conflicts", ""])
    for comparison in document.comparisons:
        lines.append(
            f"- Comparison {_md(comparison.comparison_id)}: "
            + _md_fields(
                ("relation", comparison.relation.value),
                ("source unavailable", comparison.source_unavailable),
                ("hash", comparison.artifact_hash),
            )
        )
        for dimension in comparison.dimensions:
            lines.append(
                f"  - {_md(dimension.dimension.value)}: "
                + _md_fields(
                    ("applicable", dimension.applicable),
                    ("left", dimension.left_value),
                    ("right", dimension.right_value),
                )
            )
    for conflict in document.conflicts:
        lines.append(
            f"- Conflict {_md(conflict.conflict_id)}: "
            + _md_fields(
                ("outcome", conflict.outcome.value),
                ("comparison", conflict.comparison_id),
                ("hash", conflict.artifact_hash),
            )
        )
    if not document.comparisons and not document.conflicts:
        lines.append("No comparison or conflict artifact was registered.")
    lines.extend(["", "## Limitations and warnings", ""])
    for item in document.limitations:
        lines.append(f"- {_md(item)}")
    for code in document.warning_codes:
        lines.append(f"- Warning code: {_md(code)}")
    lines.extend(["", f"Render document hash: {_md(document.render_document_hash)}", ""])
    return "\n".join(lines)
