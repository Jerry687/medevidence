"""Closed selected-current-SPL result after DailyMed V2 enrichment."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .dailymed_enrichment import (
    DailyMedEnrichedCandidateV2,
    DailyMedEnrichmentReason,
    DailyMedPackagingExecutionV2,
    DailyMedSelectionDecisionV2,
)
from .identifiers import DurableModel, Sha256Digest, derive_identity
from .scope import SourceType
from .sources import (
    CoverageStatus,
    DailyMedSourceNativeSectionV1,
    ExecutionStatus,
    ResultStatus,
    SourceOutcome,
)


class DailyMedV2PackagingResult(DurableModel):
    """Exact executed packaging outcome, including unsupported complete pagination."""

    schema_version: Literal["m3.dailymed-v2-packaging-result.v1"] = (
        "m3.dailymed-v2-packaging-result.v1"
    )
    summary_id: str
    discovery_query_id: str
    packaging_query_id: str
    setid: str
    expected_current_spl_version: str
    source_outcome: SourceOutcome
    execution: DailyMedPackagingExecutionV2 | None = None
    reason: DailyMedEnrichmentReason | None = None

    @model_validator(mode="after")
    def exact_packaging_state(self) -> Self:
        if (
            self.source_outcome.source is not SourceType.DAILYMED
            or self.source_outcome.query_id != self.packaging_query_id
            or (self.execution is None) != (self.reason is not None)
            or self.packaging_query_id
            != derive_identity(
                "dailymed-packaging-query-v2",
                {
                    "summary_id": self.summary_id,
                    "setid": self.setid,
                    "spl_version": self.expected_current_spl_version,
                },
            )
        ):
            raise ValueError("DailyMed V2 packaging outcome binding differs")
        if self.execution is not None and (
            self.reason is not None
            or self.source_outcome.execution_status is not ExecutionStatus.SUCCEEDED
            or self.source_outcome.coverage_status is not CoverageStatus.COMPLETE
            or self.source_outcome.result_status is not ResultStatus.MATCHES
            or self.execution.parent.query_id != self.packaging_query_id
            or len(self.execution.products) != self.source_outcome.valid_result_count
        ):
            raise ValueError("DailyMed V2 complete packaging execution differs")
        if self.reason is not None and self.reason not in {
            DailyMedEnrichmentReason.ENRICHMENT_UNAVAILABLE,
            DailyMedEnrichmentReason.ENRICHMENT_PAGINATION_UNSUPPORTED,
        }:
            raise ValueError("DailyMed V2 packaging reason is invalid")
        return self


class DailyMedV2SectionRef(DurableModel):
    """Exact metadata for every allowlisted source-native occurrence, including no-text parents."""

    section_occurrence_id: str
    section_ordinal: int = Field(ge=0)
    parent_section_ordinal: int | None = Field(default=None, ge=0)
    section_code: str
    xml_path: str
    full_text_hash: Sha256Digest
    retrieval_eligible: bool

    @classmethod
    def from_section(cls, section: DailyMedSourceNativeSectionV1) -> DailyMedV2SectionRef:
        exact = DailyMedSourceNativeSectionV1.model_validate(
            section.model_dump(mode="python"), strict=True
        )
        if exact != section:
            raise ValueError("DailyMed V2 source-native section differs")
        return cls(
            section_occurrence_id=section.section_occurrence_id,
            section_ordinal=section.section_ordinal,
            parent_section_ordinal=section.parent_section_ordinal,
            section_code=section.section_code,
            xml_path=section.xml_path,
            full_text_hash=section.text_sha256,
            retrieval_eligible=section.retrieval_eligible,
        )


class DailyMedV2SelectedSplRecord(DurableModel):
    """One selected current label, with exact V2 selection ancestry and source-native refs."""

    schema_version: Literal["m3.dailymed-v2-selected-spl.v1"] = "m3.dailymed-v2-selected-spl.v1"
    decision: DailyMedSelectionDecisionV2
    candidate: DailyMedEnrichedCandidateV2
    run_id: str
    attempt_id: str
    discovery_query_id: str
    fetch_query_id: str
    fetch_snapshot_id: str
    fetch_manifest_id: Sha256Digest
    stable_spl_hash: Sha256Digest
    section_refs: tuple[DailyMedV2SectionRef, ...] = Field(max_length=128)
    evidence_chunk_ids: tuple[str, ...] = Field(max_length=100)

    @model_validator(mode="after")
    def exact_selected_ancestry(self) -> Self:
        if (
            self.decision.status.value != "selected"
            or self.decision.selected_candidate_id != self.candidate.candidate_id
            or self.decision.selected_setid != self.candidate.summary.setid
            or self.decision.selected_spl_version != self.candidate.summary.current_spl_version
            or self.discovery_query_id != self.decision.discovery_query_id
            or self.candidate.summary.parent.run_id != self.run_id
            or self.candidate.summary.parent.attempt_id != self.attempt_id
            or self.fetch_query_id != self.discovery_query_id
            or tuple(item.section_ordinal for item in self.section_refs)
            != tuple(sorted({item.section_ordinal for item in self.section_refs}))
            or len(set(self.evidence_chunk_ids)) != len(self.evidence_chunk_ids)
        ):
            raise ValueError("DailyMed V2 selected SPL ancestry differs")
        return self


class DailyMedV2SelectedSplResult(DurableModel):
    """Executed current-SPL fetch outcome, including fail-closed no-evidence states."""

    schema_version: Literal["m3.dailymed-v2-selected-spl-result.v1"] = (
        "m3.dailymed-v2-selected-spl-result.v1"
    )
    source_outcome: SourceOutcome
    selected: DailyMedV2SelectedSplRecord | None = None
    review_reason: (
        Literal["source_unavailable", "current_version_drift", "chunk_cap_exceeded"] | None
    ) = None

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        if self.source_outcome.source is not SourceType.DAILYMED:
            raise ValueError("DailyMed V2 selected result source differs")
        if self.selected is None and self.review_reason is None:
            raise ValueError("DailyMed V2 missing current SPL requires review reason")
        if self.selected is not None and (
            self.source_outcome.execution_status is not ExecutionStatus.SUCCEEDED
            or self.source_outcome.coverage_status is not CoverageStatus.COMPLETE
            or self.source_outcome.result_status is not ResultStatus.MATCHES
            or self.source_outcome.query_id != self.selected.fetch_query_id
            or self.review_reason not in (None, "chunk_cap_exceeded")
        ):
            raise ValueError("DailyMed V2 selected result outcome differs")
        return self
