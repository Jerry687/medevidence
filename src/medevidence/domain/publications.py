"""Versioned PubMed publication and publication-status contracts."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from .identifiers import (
    Doi,
    DurableModel,
    ExactText,
    LongText,
    NonBlankText,
    Pmcid,
    Pmid,
    PublicationNoticeId,
    PublicationStatusIdentity,
    PublicationVersionId,
    SchemaVersion,
    Sha256Digest,
    ShortText,
    UtcDateTime,
    WarningCode,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from .scope import SourceType
from .sources import DomainWarning, Provenance, ResultStatus


class PublicationStatusValue(StrEnum):
    """Source-neutral publication-status values approved for M1A."""

    CURRENT_OR_NO_KNOWN_NOTICE = "current_or_no_known_notice"
    CORRECTED = "corrected"
    RETRACTED = "retracted"
    EXPRESSION_OF_CONCERN = "expression_of_concern"
    UNKNOWN_OR_UNVERIFIED = "unknown_or_unverified"


class NoticeType(StrEnum):
    """Recognized publication notice types."""

    CORRECTION = "correction"
    RETRACTION = "retraction"
    EXPRESSION_OF_CONCERN = "expression_of_concern"


class PublicationRelationshipType(StrEnum):
    """Typed relationship between a publication and status notice."""

    CORRECTION_OF = "correction_of"
    CORRECTED_BY = "corrected_by"
    RETRACTION_OF = "retraction_of"
    RETRACTED_BY = "retracted_by"
    EXPRESSION_OF_CONCERN_FOR = "expression_of_concern_for"
    HAS_EXPRESSION_OF_CONCERN = "has_expression_of_concern"
    OTHER = "other"


class RelationshipResolution(StrEnum):
    """Whether upstream notice relationships were deterministically resolved."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"


class CorrectionContentDisposition(StrEnum):
    """Permitted use of content affected by publication-status relationships."""

    NOT_APPLICABLE = "not_applicable"
    RESOLVED_CURRENT_CONTENT = "resolved_current_content"
    STATUS_CONTEXT_ONLY = "status_context_only"
    NOT_ESTABLISHED = "not_established"


class IndexingStatus(StrEnum):
    """Source indexing state, separate from publication status."""

    INDEXED = "indexed"
    NOT_INDEXED = "not_indexed"
    UNKNOWN = "unknown"


class EvidenceScope(StrEnum):
    """Exact evidence body available for a publication record."""

    TITLE_AND_ABSTRACT = "title_and_abstract"
    TITLE_ONLY = "title_only"


class DatePrecision(StrEnum):
    """Explicit publication-date precision."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"


PRIMARY_STATUS_WARNINGS: dict[PublicationStatusValue, str] = {
    PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE: (
        "publication_status_current_or_no_known_notice"
    ),
    PublicationStatusValue.CORRECTED: "publication_status_corrected",
    PublicationStatusValue.RETRACTED: "publication_status_retracted",
    PublicationStatusValue.EXPRESSION_OF_CONCERN: ("publication_status_expression_of_concern"),
    PublicationStatusValue.UNKNOWN_OR_UNVERIFIED: ("publication_status_unknown_or_unverified"),
}
RELATIONSHIP_UNRESOLVED_WARNING = "publication_status_relationship_unresolved"

STATUS_DISCLOSURES: dict[PublicationStatusValue, str] = {
    PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE: (
        "No known publication-status notice was identified by the declared "
        "status source as of the recorded retrieval time; this is not a guarantee "
        "that no later or unindexed notice exists."
    ),
    PublicationStatusValue.CORRECTED: (
        "A correction exists; the resolved relationship and current corrected "
        "content must be disclosed."
    ),
    PublicationStatusValue.RETRACTED: (
        "This publication is retracted and cannot support an affirmative material claim."
    ),
    PublicationStatusValue.EXPRESSION_OF_CONCERN: (
        "This publication has an expression of concern and cannot be presented "
        "as unqualified support."
    ),
    PublicationStatusValue.UNKNOWN_OR_UNVERIFIED: (
        "Publication status is unknown or unverified and must not be treated as current."
    ),
}


class PublicationRelationship(DurableModel):
    """Typed, traceable publication-notice relationship."""

    relationship_type: PublicationRelationshipType
    upstream_relationship_type: NonBlankText
    related_pmid: Pmid | None = None
    notice_id: PublicationNoticeId | None = None
    resolution: RelationshipResolution
    content_disposition: CorrectionContentDisposition

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if self.resolution is RelationshipResolution.RESOLVED and (
            self.related_pmid is None and self.notice_id is None
        ):
            raise ValueError("resolved relationship requires related PMID or notice identity")
        if (
            self.relationship_type is PublicationRelationshipType.OTHER
            and self.resolution is RelationshipResolution.RESOLVED
        ):
            raise ValueError("unrecognized relationship cannot be marked resolved")
        if (
            self.resolution
            in {
                RelationshipResolution.UNRESOLVED,
                RelationshipResolution.CONFLICTING,
            }
            and self.content_disposition is CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
        ):
            raise ValueError("unresolved relationship cannot use resolved current content")
        return self


class PublicationStatus(DurableModel):
    """Immutable publication status with deterministic identity and disclosure."""

    schema_version: SchemaVersion = "1.0"
    status: PublicationStatusValue
    status_source: NonBlankText
    notice_type: NoticeType | None = None
    relationship: PublicationRelationship | None = None
    retrieved_as_of: UtcDateTime
    warning_codes: tuple[WarningCode, ...]
    disclosure_text: LongText
    publication_status_identity: PublicationStatusIdentity

    @classmethod
    def create(
        cls,
        *,
        status: PublicationStatusValue,
        status_source: str,
        notice_type: NoticeType | None,
        relationship: PublicationRelationship | None,
        retrieved_as_of: UtcDateTime,
        additional_warning_codes: tuple[WarningCode, ...] = (),
    ) -> Self:
        """Construct a publication status with required warnings and identity."""

        warnings = {PRIMARY_STATUS_WARNINGS[status], *additional_warning_codes}
        if relationship is not None and relationship.resolution in {
            RelationshipResolution.UNRESOLVED,
            RelationshipResolution.CONFLICTING,
        }:
            warnings.add(RELATIONSHIP_UNRESOLVED_WARNING)
        warning_codes = tuple(sorted(warnings))
        payload = {
            "schema_version": "1.0",
            "status": status,
            "status_source": status_source,
            "notice_type": notice_type,
            "relationship": relationship,
            "retrieved_as_of": retrieved_as_of,
            "warning_codes": warning_codes,
            "disclosure_text": STATUS_DISCLOSURES[status],
        }
        return cls(
            status=status,
            status_source=status_source,
            notice_type=notice_type,
            relationship=relationship,
            retrieved_as_of=retrieved_as_of,
            warning_codes=warning_codes,
            disclosure_text=STATUS_DISCLOSURES[status],
            publication_status_identity=derive_identity(
                "publication-status",
                payload,
            ),
        )

    @model_validator(mode="after")
    def validate_status_contract(self) -> Self:
        primary_codes = set(PRIMARY_STATUS_WARNINGS.values())
        present_primary = primary_codes.intersection(self.warning_codes)
        if present_primary != {PRIMARY_STATUS_WARNINGS[self.status]}:
            raise ValueError("exactly one matching primary status warning is required")
        if len(set(self.warning_codes)) != len(self.warning_codes):
            raise ValueError("publication-status warnings must be unique")
        if self.warning_codes != tuple(sorted(self.warning_codes)):
            raise ValueError("publication-status warnings must be canonically sorted")
        if self.disclosure_text != STATUS_DISCLOSURES[self.status]:
            raise ValueError("publication-status disclosure is not deterministic")

        known_notice = {
            PublicationStatusValue.CORRECTED: NoticeType.CORRECTION,
            PublicationStatusValue.RETRACTED: NoticeType.RETRACTION,
            PublicationStatusValue.EXPRESSION_OF_CONCERN: (NoticeType.EXPRESSION_OF_CONCERN),
        }
        if self.status is PublicationStatusValue.CURRENT_OR_NO_KNOWN_NOTICE:
            if self.notice_type is not None or self.relationship is not None:
                raise ValueError("current/no-known-notice status forbids notice relationship")
        elif self.status in known_notice:
            if self.notice_type is not known_notice[self.status]:
                raise ValueError("notice_type does not match publication status")
            if (
                self.relationship is None
                or self.relationship.resolution is not RelationshipResolution.RESOLVED
            ):
                raise ValueError("known publication status requires a resolved relationship")
            expected_relationships = {
                PublicationStatusValue.CORRECTED: {
                    PublicationRelationshipType.CORRECTION_OF,
                    PublicationRelationshipType.CORRECTED_BY,
                },
                PublicationStatusValue.RETRACTED: {
                    PublicationRelationshipType.RETRACTION_OF,
                    PublicationRelationshipType.RETRACTED_BY,
                },
                PublicationStatusValue.EXPRESSION_OF_CONCERN: {
                    PublicationRelationshipType.EXPRESSION_OF_CONCERN_FOR,
                    PublicationRelationshipType.HAS_EXPRESSION_OF_CONCERN,
                },
            }[self.status]
            if self.relationship.relationship_type not in expected_relationships:
                raise ValueError("relationship_type does not match publication status")
            allowed_dispositions = {
                PublicationStatusValue.CORRECTED: {
                    CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT,
                    CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
                },
                PublicationStatusValue.RETRACTED: {
                    CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
                },
                PublicationStatusValue.EXPRESSION_OF_CONCERN: {
                    CorrectionContentDisposition.STATUS_CONTEXT_ONLY,
                },
            }[self.status]
            if self.relationship.content_disposition not in allowed_dispositions:
                raise ValueError("content disposition does not match publication status")
        else:
            if self.notice_type is not None:
                raise ValueError("unknown status cannot coerce an unresolved notice type")
            if self.relationship is not None:
                if self.relationship.resolution is RelationshipResolution.RESOLVED:
                    raise ValueError("unknown status cannot fabricate a resolved relationship")
                if (
                    self.relationship.content_disposition
                    is not CorrectionContentDisposition.NOT_ESTABLISHED
                ):
                    raise ValueError("unknown status relationship must remain not established")

        unresolved = self.relationship is not None and self.relationship.resolution in {
            RelationshipResolution.UNRESOLVED,
            RelationshipResolution.CONFLICTING,
        }
        if unresolved and self.status is not PublicationStatusValue.UNKNOWN_OR_UNVERIFIED:
            raise ValueError("unresolved relationship requires unknown_or_unverified status")
        if unresolved and RELATIONSHIP_UNRESOLVED_WARNING not in self.warning_codes:
            raise ValueError("unresolved relationship warning is required")
        if not unresolved and RELATIONSHIP_UNRESOLVED_WARNING in self.warning_codes:
            raise ValueError("unresolved relationship warning has no unresolved relationship")

        expected = derive_identity(
            "publication-status",
            self.model_dump(mode="python", exclude={"publication_status_identity"}),
        )
        if self.publication_status_identity != expected:
            raise ValueError("publication_status_identity does not match status content")
        return self


class AbstractSection(DurableModel):
    """Exact PubMed abstract section content in source order."""

    label: ShortText | None = None
    text: ExactText

    @model_validator(mode="after")
    def reject_noncanonical_line_endings(self) -> Self:
        if "\r" in self.text:
            raise ValueError("abstract sections must use canonical LF line endings")
        return self


class PartialDate(DurableModel):
    """Publication date with explicit year/month/day precision."""

    year: int = Field(ge=1, le=9999)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    precision: DatePrecision

    @model_validator(mode="after")
    def validate_precision(self) -> Self:
        if self.precision is DatePrecision.YEAR and (
            self.month is not None or self.day is not None
        ):
            raise ValueError("year precision forbids month and day")
        if self.precision is DatePrecision.MONTH and (self.month is None or self.day is not None):
            raise ValueError("month precision requires month and forbids day")
        if self.precision is DatePrecision.DAY and (self.month is None or self.day is None):
            raise ValueError("day precision requires month and day")
        if self.month is not None and self.day is not None:
            date(self.year, self.month, self.day)
        return self


class PublicationRecord(DurableModel):
    """Source-neutral, exact-content PubMed publication record."""

    schema_version: SchemaVersion = "1.0"
    source_type: Literal[SourceType.PUBMED] = SourceType.PUBMED
    pmid: Pmid
    doi: Doi | None = None
    pmcid: Pmcid | None = None
    title: NonBlankText
    abstract_sections: tuple[AbstractSection, ...] = ()
    canonical_abstract: str | None = None
    canonical_abstract_sha256: Sha256Digest | None = None
    authors: tuple[NonBlankText, ...] = ()
    journal: NonBlankText
    language: Literal["en"] = "en"
    publication_types: tuple[ShortText, ...] = ()
    publication_date: PartialDate | None = None
    publication_status: PublicationStatus
    indexing_status: IndexingStatus
    evidence_scope: EvidenceScope
    provenance: Provenance
    parse_warnings: tuple[DomainWarning, ...] = ()
    content_hash: Sha256Digest
    publication_version_id: PublicationVersionId

    @classmethod
    def create(
        cls,
        *,
        pmid: Pmid,
        doi: Doi | None,
        pmcid: Pmcid | None,
        title: str,
        abstract_sections: tuple[AbstractSection, ...],
        authors: tuple[str, ...],
        journal: str,
        publication_types: tuple[str, ...],
        publication_date: PartialDate | None,
        publication_status: PublicationStatus,
        indexing_status: IndexingStatus,
        provenance: Provenance,
        parse_warnings: tuple[DomainWarning, ...] = (),
    ) -> Self:
        """Construct canonical abstract, record hash, and publication identity."""

        canonical_abstract = (
            "\n\n".join(section.text for section in abstract_sections)
            if abstract_sections
            else None
        )
        abstract_hash = (
            sha256_digest(canonical_abstract) if canonical_abstract is not None else None
        )
        evidence_scope = (
            EvidenceScope.TITLE_AND_ABSTRACT
            if canonical_abstract is not None
            else EvidenceScope.TITLE_ONLY
        )
        canonical_types = tuple(sorted(set(publication_types)))
        canonical_authors = tuple(authors)
        canonical_parse_warnings = tuple(sorted(parse_warnings, key=lambda warning: warning.code))
        version_payload = {
            "schema_version": "1.0",
            "source_type": SourceType.PUBMED,
            "pmid": pmid,
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "abstract_sections": abstract_sections,
            "canonical_abstract": canonical_abstract,
            "canonical_abstract_sha256": abstract_hash,
            "authors": canonical_authors,
            "journal": journal,
            "language": "en",
            "publication_types": canonical_types,
            "publication_date": publication_date,
            "publication_status": publication_status,
            "indexing_status": indexing_status,
            "evidence_scope": evidence_scope,
            "parse_warnings": canonical_parse_warnings,
        }
        content_hash = sha256_digest(canonical_json(version_payload))
        digest = content_hash.removeprefix("sha256:")
        return cls(
            pmid=pmid,
            doi=doi,
            pmcid=pmcid,
            title=title,
            abstract_sections=abstract_sections,
            canonical_abstract=canonical_abstract,
            canonical_abstract_sha256=abstract_hash,
            authors=canonical_authors,
            journal=journal,
            publication_types=canonical_types,
            publication_date=publication_date,
            publication_status=publication_status,
            indexing_status=indexing_status,
            evidence_scope=evidence_scope,
            provenance=provenance,
            parse_warnings=canonical_parse_warnings,
            content_hash=content_hash,
            publication_version_id=f"pubmed:{pmid}:sha256:{digest}",
        )

    def version_payload(self) -> dict[str, object]:
        """Return stable publication content, excluding acquisition-only provenance."""

        return self.model_dump(
            mode="python",
            exclude={"content_hash", "publication_version_id", "provenance"},
        )

    @model_validator(mode="after")
    def validate_record_identity(self) -> Self:
        expected_abstract = (
            "\n\n".join(section.text for section in self.abstract_sections)
            if self.abstract_sections
            else None
        )
        if self.canonical_abstract != expected_abstract:
            raise ValueError("canonical abstract does not match exact source sections")
        expected_abstract_hash = (
            sha256_digest(expected_abstract) if expected_abstract is not None else None
        )
        if self.canonical_abstract_sha256 != expected_abstract_hash:
            raise ValueError("canonical abstract SHA-256 does not match abstract")
        expected_scope = (
            EvidenceScope.TITLE_AND_ABSTRACT
            if expected_abstract is not None
            else EvidenceScope.TITLE_ONLY
        )
        if self.evidence_scope is not expected_scope:
            raise ValueError("evidence_scope does not match available abstract")
        if self.provenance.source is not SourceType.PUBMED:
            raise ValueError("publication provenance must be PubMed")
        if self.provenance.source_record_id != self.pmid:
            raise ValueError("publication provenance must preserve PMID source identity")
        if self.provenance.source_outcome.result_status is not ResultStatus.MATCHES:
            raise ValueError("retained publication requires a matches source outcome")
        if len(set(self.publication_types)) != len(self.publication_types):
            raise ValueError("publication types must be unique")
        if self.publication_types != tuple(sorted(self.publication_types)):
            raise ValueError("publication types must be canonically sorted")
        parse_codes = tuple(warning.code for warning in self.parse_warnings)
        if len(set(parse_codes)) != len(parse_codes):
            raise ValueError("parse warnings must be unique")
        if parse_codes != tuple(sorted(parse_codes)):
            raise ValueError("parse warnings must be canonically sorted")
        expected_content_hash = sha256_digest(canonical_json(self.version_payload()))
        if self.content_hash != expected_content_hash:
            raise ValueError("publication content_hash does not match stable content")
        digest = expected_content_hash.removeprefix("sha256:")
        expected_version = f"pubmed:{self.pmid}:sha256:{digest}"
        if self.publication_version_id != expected_version:
            raise ValueError("publication_version_id does not match PMID and content")
        return self
