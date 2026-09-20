"""Pure exact source-native DailyMed V2 section slices for evidence admission."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    DailyMedSourceNativeSectionV1,
    SourceType,
    derive_identity,
    sha256_digest,
)
from medevidence.domain.identifiers import DurableModel

from .report_validation import (
    ClaimClass,
    EvidenceInput,
    InferenceUse,
    _copy_evidence,
    canonical_evidence_id,
)

DAILYMED_V2_CHUNK_CODEPOINTS = 4096
DAILYMED_V2_LABEL_CHUNK_CAP = 100
DAILYMED_V2_TASK_CHUNK_CAP = 100


class DailyMedV2EvidenceChunk(DurableModel):
    """One unaltered contiguous span of a verified source-native SPL section."""

    schema_version: Literal["m3.dailymed-v2-evidence-chunk.v1"] = "m3.dailymed-v2-evidence-chunk.v1"
    run_id: str
    snapshot_id: str
    source_version: str
    setid: str
    spl_version: str
    section_occurrence_id: str
    section_code: str
    section_ordinal: int = Field(ge=0)
    parent_section_ordinal: int | None = Field(default=None, ge=0)
    xml_path: str
    full_section_hash: str
    chunk_ordinal: int = Field(ge=0, lt=DAILYMED_V2_LABEL_CHUNK_CAP)
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)
    chunk_text: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    chunk_hash: str
    source_record_id: str
    locator_ref: str
    evidence_id: str

    @model_validator(mode="after")
    def exact_chunk(self) -> Self:
        if (
            self.end_codepoint - self.start_codepoint != len(self.chunk_text)
            or sha256_digest(self.chunk_text) != self.chunk_hash
        ):
            raise ValueError("DailyMed V2 chunk text/span/hash differs")
        record_id = derive_identity(
            "dailymed-v2-section-chunk",
            {
                "section_occurrence_id": self.section_occurrence_id,
                "full_section_hash": self.full_section_hash,
                "chunk_ordinal": self.chunk_ordinal,
                "start_codepoint": self.start_codepoint,
                "end_codepoint": self.end_codepoint,
                "chunk_hash": self.chunk_hash,
            },
        )
        locator = derive_identity(
            "dailymed-v2-locator",
            {
                "section_occurrence_id": self.section_occurrence_id,
                "section_code": self.section_code,
                "xml_path": self.xml_path,
                "start_codepoint": self.start_codepoint,
                "end_codepoint": self.end_codepoint,
            },
        )
        if self.source_record_id != record_id or self.locator_ref != locator:
            raise ValueError("DailyMed V2 chunk source identity differs")
        if self.evidence_id != canonical_evidence_id(self.evidence()):
            raise ValueError("DailyMed V2 chunk evidence identity differs")
        return self

    def evidence(self) -> EvidenceInput:
        """Project the exact slice into the existing source-neutral registry contract."""

        return EvidenceInput(
            evidence_id=self.evidence_id,
            authorized_run_id=self.run_id,
            source=SourceType.DAILYMED,
            source_record_id=self.source_record_id,
            source_version=self.source_version,
            snapshot_id=self.snapshot_id,
            content_hash=self.chunk_hash,
            locators=(self.locator_ref,),
            permitted_claim_classes=frozenset(
                {
                    ClaimClass.DESCRIPTIVE,
                    ClaimClass.REGULATORY_OR_LABELING,
                    ClaimClass.METHODOLOGICAL_OR_LIMITATION,
                }
            ),
            permitted_inference_uses=frozenset(
                {
                    InferenceUse.DESCRIPTIVE,
                    InferenceUse.REGULATORY,
                    InferenceUse.METHODOLOGICAL_LIMITATION,
                }
            ),
            normalized_excerpt=self.chunk_text,
            numerical_facts=(),
        )


def build_dailymed_v2_chunks(
    *,
    run_id: str,
    snapshot_id: str,
    source_version: str,
    sections: tuple[DailyMedSourceNativeSectionV1, ...],
) -> tuple[DailyMedV2EvidenceChunk, ...]:
    """Slice every eligible section by Unicode codepoint, or reject over-cap labels."""

    if type(sections) is not tuple or any(
        type(item) is not DailyMedSourceNativeSectionV1 for item in sections
    ):
        raise TypeError("DailyMed V2 chunks require exact source-native sections")
    chunks: list[DailyMedV2EvidenceChunk] = []
    for section in sections:
        exact = DailyMedSourceNativeSectionV1.model_validate(
            section.model_dump(mode="python"), strict=True
        )
        if exact != section:
            raise ValueError("DailyMed V2 source-native section differs")
        if not section.retrieval_eligible:
            continue
        text = section.extracted_text
        for start in range(0, len(text), DAILYMED_V2_CHUNK_CODEPOINTS):
            if len(chunks) >= DAILYMED_V2_LABEL_CHUNK_CAP:
                raise ValueError("dailymed_v2_label_chunk_cap_exceeded")
            end = min(len(text), start + DAILYMED_V2_CHUNK_CODEPOINTS)
            chunk_text = text[start:end]
            chunk_hash = sha256_digest(chunk_text)
            ordinal = len(chunks)
            source_record_id = derive_identity(
                "dailymed-v2-section-chunk",
                {
                    "section_occurrence_id": section.section_occurrence_id,
                    "full_section_hash": section.text_sha256,
                    "chunk_ordinal": ordinal,
                    "start_codepoint": start,
                    "end_codepoint": end,
                    "chunk_hash": chunk_hash,
                },
            )
            locator = derive_identity(
                "dailymed-v2-locator",
                {
                    "section_occurrence_id": section.section_occurrence_id,
                    "section_code": section.section_code,
                    "xml_path": section.xml_path,
                    "start_codepoint": start,
                    "end_codepoint": end,
                },
            )
            provisional = DailyMedV2EvidenceChunk.model_construct(
                run_id=run_id,
                snapshot_id=snapshot_id,
                source_version=source_version,
                setid=section.setid,
                spl_version=section.spl_version,
                section_occurrence_id=section.section_occurrence_id,
                section_code=section.section_code,
                section_ordinal=section.section_ordinal,
                parent_section_ordinal=section.parent_section_ordinal,
                xml_path=section.xml_path,
                full_section_hash=section.text_sha256,
                chunk_ordinal=ordinal,
                start_codepoint=start,
                end_codepoint=end,
                chunk_text=chunk_text,
                chunk_hash=chunk_hash,
                source_record_id=source_record_id,
                locator_ref=locator,
                evidence_id="evidence:sha256:" + "0" * 64,
            )
            evidence = provisional.evidence()
            chunk = DailyMedV2EvidenceChunk.model_validate(
                {
                    **provisional.model_dump(mode="python"),
                    "evidence_id": canonical_evidence_id(evidence),
                },
                strict=True,
            )
            if _copy_evidence(chunk.evidence()) != chunk.evidence():
                raise ValueError("DailyMed V2 chunk cannot enter canonical validation")
            chunks.append(chunk)
    return tuple(chunks)


def admit_dailymed_v2_task_chunks(
    labels: tuple[tuple[DailyMedV2EvidenceChunk, ...], ...],
) -> tuple[DailyMedV2EvidenceChunk, ...]:
    """Admit all selected labels only if their combined source task fits."""

    if type(labels) is not tuple or any(
        type(label) is not tuple
        or any(type(chunk) is not DailyMedV2EvidenceChunk for chunk in label)
        for label in labels
    ):
        raise TypeError("DailyMed V2 task material must contain exact chunks")
    if sum(len(label) for label in labels) > DAILYMED_V2_TASK_CHUNK_CAP:
        raise ValueError("dailymed_v2_task_chunk_cap_exceeded")
    return tuple(chunk for label in labels for chunk in label)


__all__ = [
    "DAILYMED_V2_CHUNK_CODEPOINTS",
    "DAILYMED_V2_LABEL_CHUNK_CAP",
    "DAILYMED_V2_TASK_CHUNK_CAP",
    "DailyMedV2EvidenceChunk",
    "admit_dailymed_v2_task_chunks",
    "build_dailymed_v2_chunks",
]
