"""Stable structured DailyMed operations over an injected execution port."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from medevidence.domain import (
    AcquisitionOutcomeRef,
    DailyMedCandidateLabel,
    LabelSelectionDecision,
    RunId,
    Sha256Digest,
    SourceType,
)
from medevidence.domain.identifiers import DurableModel

from .contracts import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
)
from .ports import DailyMedExecutionPort

type StableProjectionId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class DailyMedSectionEvidenceProjection(DurableModel):
    """Content-free identity for one persisted, retrieval-eligible label section."""

    schema_version: Literal["m3.dailymed-section-evidence-projection.v1"] = (
        "m3.dailymed-section-evidence-projection.v1"
    )
    section_id: StableProjectionId
    evidence_id: StableProjectionId
    content_hash: Sha256Digest
    locator_ref: StableProjectionId


class DailyMedDiscoveryProvenanceProjection(DurableModel):
    """Persisted discovery acquisition identity with no selection authority."""

    schema_version: Literal["m3.dailymed-discovery-provenance.v1"] = (
        "m3.dailymed-discovery-provenance.v1"
    )
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    acquisition: AcquisitionOutcomeRef

    @model_validator(mode="after")
    def validate_acquisition(self) -> Self:
        acquisition = AcquisitionOutcomeRef.model_validate(
            self.acquisition.model_dump(mode="python"), strict=True
        )
        if acquisition != self.acquisition or (
            acquisition.source is not SourceType.DAILYMED or acquisition.operation != "search"
        ):
            raise ValueError("DailyMed discovery provenance requires an exact search acquisition")
        return self


class DailyMedFetchProvenanceProjection(DurableModel):
    """Persisted fetch and section identities with no selection authority."""

    schema_version: Literal["m3.dailymed-fetch-provenance.v1"] = "m3.dailymed-fetch-provenance.v1"
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    acquisition: AcquisitionOutcomeRef
    section_evidence: tuple[DailyMedSectionEvidenceProjection, ...] = Field(
        default=(), max_length=100
    )

    @model_validator(mode="after")
    def validate_acquisition(self) -> Self:
        acquisition = AcquisitionOutcomeRef.model_validate(
            self.acquisition.model_dump(mode="python"), strict=True
        )
        if acquisition != self.acquisition or (
            acquisition.source is not SourceType.DAILYMED or acquisition.operation != "fetch"
        ):
            raise ValueError("DailyMed fetch provenance requires an exact fetch acquisition")
        evidence_ids = tuple(item.evidence_id for item in self.section_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("DailyMed section provenance identities must be unique")
        return self


class DailyMedDiscoveryExecutionProjection(DurableModel):
    """Exact discovery response plus its already-persisted acquisition identity."""

    schema_version: Literal["m3.dailymed-discovery-execution-projection.v1"] = (
        "m3.dailymed-discovery-execution-projection.v1"
    )
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    response: DailyMedDiscoveryResponse
    acquisition: AcquisitionOutcomeRef

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        response = DailyMedDiscoveryResponse.model_validate(self.response.model_dump(mode="python"))
        acquisition = AcquisitionOutcomeRef.model_validate(
            self.acquisition.model_dump(mode="python")
        )
        if response != self.response or acquisition != self.acquisition:
            raise ValueError("DailyMed discovery projection contains unvalidated contracts")
        if (
            acquisition.source is not SourceType.DAILYMED
            or acquisition.operation != "search"
            or acquisition.query_id != response.query_id
            or acquisition.source_outcome_id != response.source_outcome_id
            or acquisition.snapshot_id != response.candidate_set_snapshot_id
        ):
            raise ValueError("DailyMed discovery projection acquisition identity drift")
        return self


class DailyMedFetchExecutionProjection(DurableModel):
    """Exact fetch response plus persisted section evidence identities."""

    schema_version: Literal["m3.dailymed-fetch-execution-projection.v1"] = (
        "m3.dailymed-fetch-execution-projection.v1"
    )
    run_id: RunId
    scope_id: StableProjectionId
    task_id: StableProjectionId
    attempt_id: StableProjectionId
    response: DailyMedFetchResponse
    acquisition: AcquisitionOutcomeRef
    section_evidence: tuple[DailyMedSectionEvidenceProjection, ...] = Field(
        default=(), max_length=100
    )

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        response = DailyMedFetchResponse.model_validate(self.response.model_dump(mode="python"))
        acquisition = AcquisitionOutcomeRef.model_validate(
            self.acquisition.model_dump(mode="python")
        )
        if response != self.response or acquisition != self.acquisition:
            raise ValueError("DailyMed fetch projection contains unvalidated contracts")
        if (
            acquisition.source is not SourceType.DAILYMED
            or acquisition.operation != "fetch"
            or acquisition.query_id != response.request.query_id
            or acquisition.source_outcome_id != response.source_outcome_id
            or acquisition.snapshot_id != response.fetch_snapshot_id
        ):
            raise ValueError("DailyMed fetch projection acquisition identity drift")
        section_ids = tuple(item.section_id for item in self.section_evidence)
        if section_ids != response.section_ids:
            raise ValueError("DailyMed section evidence must equal the exact eligible section set")
        evidence_ids = tuple(item.evidence_id for item in self.section_evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("DailyMed section evidence identities must be unique")
        return self


def discover_dailymed_labels(
    request: DailyMedDiscoveryRequest,
    *,
    execution: DailyMedExecutionPort,
) -> DailyMedDiscoveryResponse:
    """Run one bounded discovery and require an exact request echo."""

    validated_request = DailyMedDiscoveryRequest.model_validate(request.model_dump(mode="python"))
    raw_response, raw_candidates, decision = execution.discover(validated_request)
    response = DailyMedDiscoveryResponse.model_validate(raw_response.model_dump(mode="python"))
    if not all(isinstance(candidate, DailyMedCandidateLabel) for candidate in raw_candidates):
        raise ValueError("DailyMed discovery candidates require authoritative domain records")
    candidates = tuple(
        DailyMedCandidateLabel.model_validate(candidate.model_dump(mode="python"))
        for candidate in raw_candidates
    )
    if decision is not None and not isinstance(decision, LabelSelectionDecision):
        raise ValueError("DailyMed discovery decision requires authoritative domain context")
    if response.selection_request != validated_request.selection_request:
        raise ValueError("DailyMed discovery response belongs to another selection request")
    if response.query_id != validated_request.query_id:
        raise ValueError("DailyMed discovery response belongs to another query")
    _validate_discovery_authority(response, candidates=candidates, decision=decision)
    return response


def fetch_dailymed_label(
    request: DailyMedFetchRequest,
    *,
    execution: DailyMedExecutionPort,
) -> DailyMedFetchResponse:
    """Run one exact selected-label fetch and require an exact request echo."""

    validated_request = DailyMedFetchRequest.model_validate(request.model_dump(mode="python"))
    response = DailyMedFetchResponse.model_validate(
        execution.fetch(validated_request).model_dump(mode="python")
    )
    if response.request != validated_request:
        raise ValueError("DailyMed fetch response belongs to another exact request")
    return response


def _validate_discovery_authority(
    response: DailyMedDiscoveryResponse,
    *,
    candidates: tuple[DailyMedCandidateLabel, ...],
    decision: LabelSelectionDecision | None,
) -> None:
    """Bind the structured projection to the authoritative domain decision."""

    if decision is None:
        if candidates or response.decision_id is not None or response.selection_status is not None:
            raise ValueError("decisionless discovery requires empty authoritative context")
        return

    decision.validate_against(
        outcome=response.source_outcome,
        candidates=candidates,
        source_outcome_id=response.source_outcome_id,
        discovery_manifest_content_hash=decision.discovery_manifest_content_hash,
    )
    projected = (
        response.candidate_set_snapshot_id,
        response.discovery_manifest_id,
        response.candidate_ids,
        response.decision_id,
        response.selection_status,
        response.selected_candidate_id,
        response.selected_setid,
        response.selected_spl_version,
    )
    authoritative = (
        decision.candidate_set_snapshot_id,
        decision.discovery_manifest_id,
        decision.candidate_ids,
        decision.decision_id,
        decision.status,
        decision.selected_candidate_id,
        decision.selected_setid,
        decision.selected_spl_version,
    )
    if projected != authoritative:
        raise ValueError("structured discovery response differs from authoritative decision")
