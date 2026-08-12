"""Stable structured DailyMed operations over an injected execution port."""

from __future__ import annotations

from medevidence.domain import DailyMedCandidateLabel, LabelSelectionDecision

from .contracts import (
    DailyMedDiscoveryRequest,
    DailyMedDiscoveryResponse,
    DailyMedFetchRequest,
    DailyMedFetchResponse,
)
from .ports import DailyMedExecutionPort


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
