"""Exact abstract citations and deterministic attributed extract claims."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from .identifiers import (
    CitationId,
    ClaimId,
    DurableModel,
    ExactText,
    Pmid,
    PublicationStatusIdentity,
    PublicationVersionId,
    SchemaVersion,
    ScopeId,
    Sha256Digest,
    WarningCode,
    derive_identity,
)
from .publications import (
    CorrectionContentDisposition,
    PublicationRecord,
    PublicationStatusValue,
    RelationshipResolution,
)
from .scope import SourceType


class CitationRelationship(StrEnum):
    """How an exact cited span relates to an attributed extract."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT_ONLY = "context_only"


class CitationValidationCode(StrEnum):
    """Deterministic success reasons retained on a valid citation."""

    PMID_MATCH = "pmid_match"
    PUBLICATION_VERSION_MATCH = "publication_version_match"
    ABSTRACT_HASH_MATCH = "abstract_hash_match"
    QUOTE_SPAN_MATCH = "quote_span_match"
    PUBLICATION_STATUS_MATCH = "publication_status_match"
    STATUS_WARNING_MATCH = "status_warning_match"


class CitationValidationErrorCode(StrEnum):
    """Typed structural drift failures for citation validation."""

    PMID_MISMATCH = "pmid_mismatch"
    PUBLICATION_VERSION_MISMATCH = "publication_version_mismatch"
    ABSTRACT_MISSING = "abstract_missing"
    ABSTRACT_HASH_MISMATCH = "abstract_hash_mismatch"
    INVALID_SPAN = "invalid_span"
    QUOTE_MISMATCH = "quote_mismatch"
    PUBLICATION_STATUS_MISMATCH = "publication_status_mismatch"
    PUBLICATION_STATUS_IDENTITY_MISMATCH = "publication_status_identity_mismatch"
    STATUS_WARNING_MISMATCH = "status_warning_mismatch"


class CitationValidationError(ValueError):
    """Typed failure raised when a citation drifts from its publication."""

    def __init__(self, code: CitationValidationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ClaimUseContext(StrEnum):
    """Deterministic publication-status use policy for M1A extracts."""

    AFFIRMATIVE_SUPPORT = "affirmative_support"
    SUPPORT_LIMITED = "support_limited"
    SOURCE_STATUS_CONTEXT = "source_status_context"


REQUIRED_CITATION_CODES = tuple(sorted(code for code in CitationValidationCode))


class Citation(DurableModel):
    """Exact Unicode code-point span bound to one publication version."""

    schema_version: SchemaVersion = "1.0"
    citation_id: CitationId
    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_status: PublicationStatusValue
    publication_status_identity: PublicationStatusIdentity
    status_warning_references: tuple[WarningCode, ...]
    canonical_abstract_sha256: Sha256Digest
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: ExactText
    relationship: CitationRelationship
    validation_state: Literal["passed"] = "passed"
    validation_codes: tuple[CitationValidationCode, ...] = REQUIRED_CITATION_CODES

    @classmethod
    def from_publication(
        cls,
        publication: PublicationRecord,
        *,
        start_offset: int,
        end_offset: int,
        relationship: CitationRelationship = CitationRelationship.SUPPORTS,
    ) -> Self:
        """Create and validate an exact citation from a stored canonical abstract."""

        if publication.canonical_abstract is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_MISSING)
        if publication.canonical_abstract_sha256 is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_HASH_MISMATCH)
        if start_offset < 0 or end_offset <= start_offset:
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        if end_offset > len(publication.canonical_abstract):
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        quote = publication.canonical_abstract[start_offset:end_offset]
        payload = {
            "schema_version": "1.0",
            "pmid": publication.pmid,
            "publication_version_id": publication.publication_version_id,
            "publication_status": publication.publication_status.status,
            "publication_status_identity": (
                publication.publication_status.publication_status_identity
            ),
            "status_warning_references": publication.publication_status.warning_codes,
            "canonical_abstract_sha256": publication.canonical_abstract_sha256,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "exact_quote": quote,
            "relationship": relationship,
            "validation_state": "passed",
            "validation_codes": REQUIRED_CITATION_CODES,
        }
        citation = cls(
            citation_id=derive_identity("citation", payload),
            pmid=publication.pmid,
            publication_version_id=publication.publication_version_id,
            publication_status=publication.publication_status.status,
            publication_status_identity=(
                publication.publication_status.publication_status_identity
            ),
            status_warning_references=publication.publication_status.warning_codes,
            canonical_abstract_sha256=publication.canonical_abstract_sha256,
            start_offset=start_offset,
            end_offset=end_offset,
            exact_quote=quote,
            relationship=relationship,
        )
        citation.validate_against(publication)
        return citation

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.end_offset <= self.start_offset:
            raise ValueError("citation span must be non-empty and half-open")
        if len(set(self.status_warning_references)) != len(self.status_warning_references):
            raise ValueError("status warning references must be unique")
        if self.status_warning_references != tuple(sorted(self.status_warning_references)):
            raise ValueError("status warning references must be canonically sorted")
        if self.validation_codes != REQUIRED_CITATION_CODES:
            raise ValueError("citation must retain the complete deterministic success codes")
        expected = derive_identity(
            "citation",
            self.model_dump(mode="python", exclude={"citation_id"}),
        )
        if self.citation_id != expected:
            raise ValueError("citation_id does not match canonical citation content")
        return self

    def validate_against(self, publication: PublicationRecord) -> None:
        """Fail closed on any approved publication, status, warning, or span drift."""

        if self.pmid != publication.pmid:
            raise CitationValidationError(CitationValidationErrorCode.PMID_MISMATCH)
        if self.publication_version_id != publication.publication_version_id:
            raise CitationValidationError(CitationValidationErrorCode.PUBLICATION_VERSION_MISMATCH)
        if self.publication_status is not publication.publication_status.status:
            raise CitationValidationError(CitationValidationErrorCode.PUBLICATION_STATUS_MISMATCH)
        if (
            self.publication_status_identity
            != publication.publication_status.publication_status_identity
        ):
            raise CitationValidationError(
                CitationValidationErrorCode.PUBLICATION_STATUS_IDENTITY_MISMATCH
            )
        if self.status_warning_references != publication.publication_status.warning_codes:
            raise CitationValidationError(CitationValidationErrorCode.STATUS_WARNING_MISMATCH)
        if publication.canonical_abstract is None:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_MISSING)
        if self.canonical_abstract_sha256 != publication.canonical_abstract_sha256:
            raise CitationValidationError(CitationValidationErrorCode.ABSTRACT_HASH_MISMATCH)
        if (
            self.start_offset < 0
            or self.end_offset <= self.start_offset
            or self.end_offset > len(publication.canonical_abstract)
        ):
            raise CitationValidationError(CitationValidationErrorCode.INVALID_SPAN)
        if publication.canonical_abstract[self.start_offset : self.end_offset] != self.exact_quote:
            raise CitationValidationError(CitationValidationErrorCode.QUOTE_MISMATCH)


class EvidenceClaim(DurableModel):
    """One deterministic attributed abstract extract with no medical synthesis."""

    schema_version: SchemaVersion = "1.0"
    claim_id: ClaimId
    claim_kind: Literal["attributed_abstract_extract"] = "attributed_abstract_extract"
    claim_text: ExactText
    scope_id: ScopeId
    source_type: Literal[SourceType.PUBMED] = SourceType.PUBMED
    pmid: Pmid
    publication_version_id: PublicationVersionId
    publication_status: PublicationStatusValue
    publication_status_identity: PublicationStatusIdentity
    supporting_citation_ids: tuple[CitationId, ...] = Field(min_length=1, max_length=1)
    use_context: ClaimUseContext
    publication_warning_references: tuple[WarningCode, ...]
    limitations: tuple[WarningCode, ...]

    @classmethod
    def from_citation(
        cls,
        *,
        scope_id: ScopeId,
        citation: Citation,
        publication: PublicationRecord,
        use_context: ClaimUseContext,
        additional_limitations: tuple[WarningCode, ...] = (),
    ) -> Self:
        """Build an exact attributed extract after publication-status policy checks."""

        citation.validate_against(publication)
        limitations = tuple(sorted({"abstract_only", *additional_limitations}))
        payload = {
            "schema_version": "1.0",
            "claim_kind": "attributed_abstract_extract",
            "claim_text": citation.exact_quote,
            "scope_id": scope_id,
            "source_type": SourceType.PUBMED,
            "pmid": citation.pmid,
            "publication_version_id": citation.publication_version_id,
            "publication_status": citation.publication_status,
            "publication_status_identity": citation.publication_status_identity,
            "supporting_citation_ids": (citation.citation_id,),
            "use_context": use_context,
            "publication_warning_references": citation.status_warning_references,
            "limitations": limitations,
        }
        claim = cls(
            claim_id=derive_identity("claim", payload),
            claim_text=citation.exact_quote,
            scope_id=scope_id,
            pmid=citation.pmid,
            publication_version_id=citation.publication_version_id,
            publication_status=citation.publication_status,
            publication_status_identity=citation.publication_status_identity,
            supporting_citation_ids=(citation.citation_id,),
            use_context=use_context,
            publication_warning_references=citation.status_warning_references,
            limitations=limitations,
        )
        claim.validate_against(citation, publication)
        return claim

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.publication_warning_references != tuple(
            sorted(self.publication_warning_references)
        ):
            raise ValueError("publication warning references must be canonically sorted")
        if len(set(self.publication_warning_references)) != len(
            self.publication_warning_references
        ):
            raise ValueError("publication warning references must be unique")
        if "abstract_only" not in self.limitations:
            raise ValueError("abstract_only limitation is mandatory")
        if self.limitations != tuple(sorted(self.limitations)):
            raise ValueError("claim limitations must be canonically sorted")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("claim limitations must be unique")
        expected = derive_identity(
            "claim",
            self.model_dump(mode="python", exclude={"claim_id"}),
        )
        if self.claim_id != expected:
            raise ValueError("claim_id does not match canonical claim content")
        return self

    def validate_against(
        self,
        citation: Citation,
        publication: PublicationRecord,
    ) -> None:
        """Revalidate exact quote, identity, warnings, and ADR-009 status policy."""

        citation.validate_against(publication)
        if self.supporting_citation_ids != (citation.citation_id,):
            raise ValueError("claim must reference exactly its validated citation")
        if self.claim_text != citation.exact_quote:
            raise ValueError("claim text must equal the exact cited abstract span")
        if self.pmid != publication.pmid or self.publication_version_id != (
            publication.publication_version_id
        ):
            raise ValueError("claim publication identity does not match citation")
        if (
            self.pmid != citation.pmid
            or self.publication_version_id != citation.publication_version_id
            or self.publication_status is not citation.publication_status
            or self.publication_status_identity != citation.publication_status_identity
        ):
            raise ValueError("claim publication status identity does not match citation")
        if self.publication_warning_references != (publication.publication_status.warning_codes):
            raise ValueError("claim must preserve all publication-status warnings")

        expected_relationship = {
            ClaimUseContext.AFFIRMATIVE_SUPPORT: CitationRelationship.SUPPORTS,
            ClaimUseContext.SUPPORT_LIMITED: CitationRelationship.SUPPORTS,
            ClaimUseContext.SOURCE_STATUS_CONTEXT: CitationRelationship.CONTEXT_ONLY,
        }[self.use_context]
        if citation.relationship is CitationRelationship.CONTRADICTS:
            raise ValueError("contradicting citations require a future typed claim contract")
        if citation.relationship is not expected_relationship:
            raise ValueError("claim use context does not match citation relationship")

        status = publication.publication_status.status
        if status is PublicationStatusValue.RETRACTED:
            if self.use_context is not ClaimUseContext.SOURCE_STATUS_CONTEXT:
                raise ValueError("retracted publication is limited to source-status context")
        elif status in {
            PublicationStatusValue.EXPRESSION_OF_CONCERN,
            PublicationStatusValue.UNKNOWN_OR_UNVERIFIED,
        }:
            if self.use_context not in {
                ClaimUseContext.SUPPORT_LIMITED,
                ClaimUseContext.SOURCE_STATUS_CONTEXT,
            }:
                raise ValueError("non-current publication cannot be affirmative support")
        elif self.use_context is ClaimUseContext.SUPPORT_LIMITED:
            raise ValueError("support_limited is reserved for concern or unknown status")
        elif (
            status is PublicationStatusValue.CORRECTED
            and self.use_context is ClaimUseContext.AFFIRMATIVE_SUPPORT
        ):
            relationship = publication.publication_status.relationship
            if (
                relationship is None
                or relationship.resolution is not RelationshipResolution.RESOLVED
                or relationship.content_disposition
                is not CorrectionContentDisposition.RESOLVED_CURRENT_CONTENT
            ):
                raise ValueError("corrected affirmative support requires resolved current content")
