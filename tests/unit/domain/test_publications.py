"""Publication, publication-status, and exact-citation contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from medevidence.domain import (
    AbstractSection,
    Citation,
    CitationValidationError,
    CitationValidationErrorCode,
    CorrectionContentDisposition,
    CoverageStatus,
    DatePrecision,
    EvidenceScope,
    ExecutionBounds,
    ExecutionStatus,
    IndexingStatus,
    NoticeType,
    PartialDate,
    Provenance,
    PublicationRecord,
    PublicationRelationship,
    PublicationRelationshipType,
    PublicationStatus,
    PublicationStatusValue,
    RelationshipResolution,
    ResultStatus,
    SourceOutcome,
    SourceType,
    sha256_digest,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def bounds() -> ExecutionBounds:
    return ExecutionBounds(
        max_query_characters=512,
        max_pages=5,
        max_records=100,
        max_payload_bytes=5_242_880,
        max_total_seconds=60,
    )


def matches_outcome() -> SourceOutcome:
    return SourceOutcome(
        source=SourceType.PUBMED,
        query_id="query:publication",
        execution_status=ExecutionStatus.SUCCEEDED,
        coverage_status=CoverageStatus.COMPLETE,
        result_status=ResultStatus.MATCHES,
        configured_bounds=bounds(),
        valid_result_count=1,
        pages_completed=1,
        truncated=False,
    )


def provenance(pmid: str = "12345") -> Provenance:
    return Provenance(
        source=SourceType.PUBMED,
        source_record_id=pmid,
        query_id="query:publication",
        source_lookup_key=f"pubmed:{pmid}",
        retrieved_at=NOW,
        connector_version="fixture-1.0",
        content_hash=sha256_digest(b"raw"),
        source_outcome=matches_outcome(),
        configured_bounds=bounds(),
    )


def relationship_for(status: PublicationStatusValue) -> PublicationRelationship | None:
    if status is PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE:
        return None
    mapping = {
        PublicationStatusValue.CORRECTED: (
            PublicationRelationshipType.CORRECTED_BY,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
        ),
        PublicationStatusValue.RETRACTED: (
            PublicationRelationshipType.RETRACTED_BY,
            CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
        PublicationStatusValue.EXPRESSION_OF_CONCERN: (
            PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN,
            CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
    }
    relationship_type, disposition = mapping[status]
    return PublicationRelationship(
        relationship_type=relationship_type,
        upstream_relationship_type=relationship_type.value,
        related_pmid="99999",
        resolution=RelationshipResolution.RESOLVED,
        content_disposition=disposition,
    )


def relationship(
    relationship_type: PublicationRelationshipType,
    disposition: CorrectionContentDisposition,
    *,
    resolution: RelationshipResolution = RelationshipResolution.RESOLVED,
    related_pmid: str | None = "99999",
) -> PublicationRelationship:
    return PublicationRelationship(
        relationship_type=relationship_type,
        upstream_relationship_type=relationship_type.value,
        related_pmid=related_pmid,
        resolution=resolution,
        content_disposition=disposition,
    )


def status_for(
    value: PublicationStatusValue = PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
) -> PublicationStatus:
    if value is PublicationStatusValue.UNKNOWN_OR_UNVERIFIED:
        unresolved = PublicationRelationship(
            relationship_type=PublicationRelationshipType.OTHER,
            upstream_relationship_type="UnrecognizedUpstreamRelation",
            related_pmid="99999",
            resolution=RelationshipResolution.UNRESOLVED,
            content_disposition=CorrectionContentDisposition.NOT_ESTABLISHED,
        )
        return PublicationStatus.create(
            status=value,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=unresolved,
            retrieved_as_of=NOW,
        )
    notice_types = {
        PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE: None,
        PublicationStatusValue.CORRECTED: NoticeType.CORRECTION,
        PublicationStatusValue.RETRACTED: NoticeType.RETRACTION,
        PublicationStatusValue.EXPRESSION_OF_CONCERN: (NoticeType.EXPRESSION_OF_CONCERN),
    }
    return PublicationStatus.create(
        status=value,
        status_source="PubMed relationship metadata",
        notice_type=notice_types[value],
        relationship=relationship_for(value),
        retrieved_as_of=NOW,
    )


def publication(
    *,
    status: PublicationStatus | None = None,
    sections: tuple[AbstractSection, ...] | None = None,
    pmid: str = "12345",
) -> PublicationRecord:
    return PublicationRecord.create(
        pmid=pmid,
        doi="10.1234/example",
        pmcid="PMC12345",
        title="Exact source title",
        abstract_sections=sections
        if sections is not None
        else (
            AbstractSection(label="BACKGROUND", text="Café e\u0301 remains exact."),
            AbstractSection(label="RESULTS", text="Emoji 🙂 offsets are code points."),
        ),
        authors=("Alpha Author", "Beta Author"),
        journal="Example Journal",
        publication_types=("Journal Article",),
        publication_date=PartialDate(
            year=2026,
            month=7,
            day=27,
            precision=DatePrecision.DAY,
        ),
        publication_status=status or status_for(),
        indexing_status=IndexingStatus.INDEXED,
        provenance=provenance(pmid),
    )


def test_ps01_current_record_has_as_of_provenance_warning_and_disclosure() -> None:
    record = publication()

    assert record.publication_status.status is PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE
    assert record.publication_status.retrieved_as_of == NOW
    assert record.publication_status.warning_codes == (
        "publication_status_current_or_no_known_notice",
    )
    assert "not a guarantee" in record.publication_status.disclosure_text


def test_canonical_abstract_preserves_unicode_whitespace_case_and_section_order() -> None:
    sections = (
        AbstractSection(text="A  Café e\u0301"),
        AbstractSection(text="lower CASE\nline"),
    )
    record = publication(sections=sections)

    assert record.canonical_abstract == "A  Café e\u0301\n\nlower CASE\nline"
    assert record.canonical_abstract_sha256 == sha256_digest("A  Café e\u0301\n\nlower CASE\nline")
    assert record.evidence_scope is EvidenceScope.TITLE_AND_ABSTRACT
    assert "BACKGROUND" not in record.canonical_abstract


def test_abstract_rejects_cr_and_title_only_cannot_create_citation() -> None:
    with pytest.raises(ValidationError):
        AbstractSection(text="CRLF\r\nis not canonical")
    title_only = publication(sections=())
    assert title_only.evidence_scope is EvidenceScope.TITLE_ONLY
    assert title_only.canonical_abstract is None
    assert title_only.canonical_abstract_sha256 is None
    with pytest.raises(CitationValidationError) as error:
        Citation.from_publication(title_only, start_offset=0, end_offset=1)
    assert error.value.code is CitationValidationErrorCode.ABSTRACT_MISSING


def test_abstract_and_exact_claim_span_are_not_limited_to_query_length() -> None:
    exact_text = "A" * 600
    record = publication(sections=(AbstractSection(text=exact_text),))
    citation = Citation.from_publication(
        record,
        start_offset=0,
        end_offset=len(exact_text),
    )

    assert citation.exact_quote == exact_text


def test_unicode_citation_offsets_are_zero_based_half_open_code_points() -> None:
    record = publication()
    assert record.canonical_abstract is not None
    start = record.canonical_abstract.index("🙂")
    citation = Citation.from_publication(
        record,
        start_offset=start,
        end_offset=start + 1,
    )

    assert citation.exact_quote == "🙂"
    citation.validate_against(record)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"pmid": "54321"}, CitationValidationErrorCode.PMID_MISMATCH),
        (
            {"publication_version_id": f"pubmed:12345:sha256:{'0' * 64}"},
            CitationValidationErrorCode.PUBLICATION_VERSION_MISMATCH,
        ),
        (
            {"canonical_abstract_sha256": f"sha256:{'0' * 64}"},
            CitationValidationErrorCode.ABSTRACT_HASH_MISMATCH,
        ),
        ({"start_offset": 999}, CitationValidationErrorCode.INVALID_SPAN),
        ({"exact_quote": "drift"}, CitationValidationErrorCode.QUOTE_MISMATCH),
        (
            {"publication_status": PublicationStatusValue.RETRACTED},
            CitationValidationErrorCode.PUBLICATION_STATUS_MISMATCH,
        ),
        (
            {"publication_status_identity": f"publication-status:sha256:{'0' * 64}"},
            CitationValidationErrorCode.PUBLICATION_STATUS_IDENTITY_MISMATCH,
        ),
        (
            {"status_warning_references": ()},
            CitationValidationErrorCode.STATUS_WARNING_MISMATCH,
        ),
    ],
)
def test_citation_fails_for_every_direct_drift(
    changes: dict[str, object],
    code: CitationValidationErrorCode,
) -> None:
    record = publication()
    citation = Citation.from_publication(record, start_offset=0, end_offset=4)
    drifted = citation.model_copy(update=changes)

    with pytest.raises(CitationValidationError) as error:
        drifted.validate_against(record)
    assert error.value.code is code


def test_ps02_corrected_record_resolves_and_discloses_notice() -> None:
    corrected = status_for(PublicationStatusValue.CORRECTED)
    record = publication(status=corrected)

    assert corrected.relationship is not None
    assert corrected.relationship.resolution is RelationshipResolution.RESOLVED
    assert corrected.relationship.related_pmid == "99999"
    assert "correction exists" in corrected.disclosure_text
    assert "publication_status_corrected" in record.publication_status.warning_codes


def test_ps06_missing_required_status_warning_is_rejected() -> None:
    current = status_for()
    with pytest.raises(ValidationError):
        PublicationStatus(
            **{
                **current.model_dump(mode="python"),
                "warning_codes": (),
            }
        )


def test_ps07_status_mismatch_between_record_and_citation_is_rejected() -> None:
    record = publication()
    citation = Citation.from_publication(record, start_offset=0, end_offset=4)
    drifted = citation.model_copy(update={"publication_status": PublicationStatusValue.RETRACTED})

    with pytest.raises(CitationValidationError) as error:
        drifted.validate_against(record)
    assert error.value.code is CitationValidationErrorCode.PUBLICATION_STATUS_MISMATCH


def test_ps08_relationship_notice_and_status_provenance_change_identity() -> None:
    original_status = status_for(PublicationStatusValue.CORRECTED)
    original = publication(status=original_status)
    citation = Citation.from_publication(original, start_offset=0, end_offset=4)
    changed_relationship = original_status.relationship.model_copy(update={"related_pmid": "88888"})
    changed_status = PublicationStatus.create(
        status=PublicationStatusValue.CORRECTED,
        status_source="PubMed relationship metadata v2",
        notice_type=NoticeType.CORRECTION,
        relationship=changed_relationship,
        retrieved_as_of=datetime(2026, 7, 27, 13, 0, tzinfo=UTC),
    )
    changed = publication(status=changed_status)

    assert (
        changed.publication_status.publication_status_identity
        != original.publication_status.publication_status_identity
    )
    assert changed.publication_version_id != original.publication_version_id
    with pytest.raises(CitationValidationError):
        citation.validate_against(changed)


def test_ps09_unknown_status_is_disclosed_and_never_treated_as_current() -> None:
    unknown = status_for(PublicationStatusValue.UNKNOWN_OR_UNVERIFIED)

    assert "publication_status_unknown_or_unverified" in unknown.warning_codes
    assert "publication_status_relationship_unresolved" in unknown.warning_codes
    assert "must not be treated as current" in unknown.disclosure_text
    assert unknown.status is not PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE


@pytest.mark.parametrize(
    ("status", "notice_type", "relationship_type", "disposition"),
    [
        (
            PublicationStatusValue.RETRACTED,
            NoticeType.RETRACTION,
            PublicationRelationshipType.RETRACTED_BY,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
        ),
        (
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            NoticeType.EXPRESSION_OF_CONCERN,
            PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
        ),
        (
            PublicationStatusValue.CORRECTED,
            NoticeType.CORRECTION,
            PublicationRelationshipType.RETRACTED_BY,
            CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
        (
            PublicationStatusValue.RETRACTED,
            NoticeType.RETRACTION,
            PublicationRelationshipType.CORRECTED_BY,
            CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
        ),
        (
            PublicationStatusValue.CORRECTED,
            NoticeType.RETRACTION,
            PublicationRelationshipType.CORRECTED_BY,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
        ),
    ],
)
def test_publication_status_rejects_incompatible_notice_relationship_and_disposition(
    status: PublicationStatusValue,
    notice_type: NoticeType,
    relationship_type: PublicationRelationshipType,
    disposition: CorrectionContentDisposition,
) -> None:
    with pytest.raises(ValidationError):
        PublicationStatus.create(
            status=status,
            status_source="PubMed relationship metadata",
            notice_type=notice_type,
            relationship=relationship(relationship_type, disposition),
            retrieved_as_of=NOW,
        )


def test_relationship_resolution_fails_closed_on_identity_and_disposition() -> None:
    with pytest.raises(ValidationError, match="related PMID or notice"):
        relationship(
            PublicationRelationshipType.CORRECTED_BY,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
            related_pmid=None,
        )
    with pytest.raises(ValidationError, match="unresolved relationship"):
        relationship(
            PublicationRelationshipType.CORRECTED_BY,
            CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
            resolution=RelationshipResolution.UNRESOLVED,
        )


def test_current_and_unknown_status_reject_fabricated_notice_relationships() -> None:
    retraction = relationship(
        PublicationRelationshipType.RETRACTED_BY,
        CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
    )
    with pytest.raises(ValidationError, match="forbids notice relationship"):
        PublicationStatus.create(
            status=PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=retraction,
            retrieved_as_of=NOW,
        )
    with pytest.raises(ValidationError, match="fabricate a resolved relationship"):
        PublicationStatus.create(
            status=PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
            status_source="PubMed relationship metadata",
            notice_type=None,
            relationship=retraction,
            retrieved_as_of=NOW,
        )


def test_publication_identity_rejects_hash_version_and_provenance_drift() -> None:
    record = publication()
    for changes in (
        {"content_hash": f"sha256:{'0' * 64}"},
        {"publication_version_id": f"pubmed:12345:sha256:{'0' * 64}"},
        {"provenance": provenance("54321")},
    ):
        with pytest.raises(ValidationError):
            PublicationRecord(
                **{
                    **record.model_dump(mode="python"),
                    **changes,
                }
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pmid", "012345"),
        ("pmid", " 12345"),
        ("pmcid", "pmc12345"),
        ("doi", "not-a-doi"),
    ],
)
def test_publication_identifiers_reject_invalid_formats(
    field: str,
    value: str,
) -> None:
    record = publication()
    with pytest.raises(ValidationError):
        PublicationRecord(
            **{
                **record.model_dump(mode="python"),
                field: value,
            }
        )


@pytest.mark.parametrize(
    "partial_date",
    [
        PartialDate(year=2026, precision=DatePrecision.YEAR),
        PartialDate(year=2026, month=7, precision=DatePrecision.MONTH),
        PartialDate(
            year=2026,
            month=7,
            day=27,
            precision=DatePrecision.DAY,
        ),
    ],
)
def test_all_publication_date_precisions_are_explicit(
    partial_date: PartialDate,
) -> None:
    assert partial_date.precision in DatePrecision


def test_publication_status_is_strict_frozen_and_versioned() -> None:
    status = status_for()
    assert status.schema_version == "1.0"
    with pytest.raises(ValidationError):
        status.status_source = "mutated"
    with pytest.raises(ValidationError):
        PublicationStatus(
            **{
                **status.model_dump(mode="python"),
                "provider_payload": {},
            }
        )
