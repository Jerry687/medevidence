"""Durable local synthesis over verified source material and Generation V2."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Protocol, cast, final

from medevidence.domain import (
    M1BSourcePlanEntryV1,
    PlanningStatus,
    ResearchScope,
    SourceType,
    canonical_json,
    derive_identity,
    sha256_digest,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import (
    CitationReference,
    ClaimReference,
    ComparabilityReference,
    ConflictReference,
    OrchestrationState,
    RuntimeContext,
    SourceTaskState,
    SourceTaskStatus,
    SynthesisState,
)
from medevidence.orchestration.validation_projection import (
    build_validation_request_projection,
    project_stored_validation,
)
from medevidence.tools.generation import (
    GenerationInput,
    GenerationSourceContext,
    generation_input_bytes,
)
from medevidence.tools.generation_v2_service import (
    DeepSeekGenerationReceiptRefV2,
    DeepSeekGenerationV2ReceiptStorePort,
    DeepSeekGenerationV2Service,
    deepseek_generation_v2_receipt_ref,
    deepseek_generation_v2_trusted_evidence_hash,
    verify_deepseek_generation_v2_receipt,
)
from medevidence.tools.report_document import EvidenceProvenanceV1, ReceiptReadPort
from medevidence.tools.report_validation import (
    CanonicalReportRequest,
    EvidenceInput,
    PlannedStage2SemanticInputV2,
    Stage2SemanticInputV2,
    ValidationMode,
    ValidationReceiptV2,
    canonical_evidence_id,
    canonical_report_content_hash,
    canonical_validate_report,
    stage2_projections_from_receipt_v2,
    validation_receipt_from_payload,
    verify_validation_receipt,
)
from medevidence.tools.synthesis_mapping import (
    generation_evidence_from_trusted,
    map_generation_v2_to_registry_v4,
)

from .report_material_codec import (
    decode_provenance,
    decode_report_request,
    encode_provenance,
    encode_report_request,
)
from .validation_registry_store import SnapshotValidationRegistryStore

_MAX_MATERIAL_BYTES = 16_777_216
_ZERO_HASH = "sha256:" + "0" * 64


class LocalSynthesisError(ValueError):
    """One fixed, credential-free material or binding failure."""


class VerifiedMaterialView(Protocol):
    @property
    def evidence(self) -> EvidenceInput: ...

    @property
    def provenance(self) -> EvidenceProvenanceV1: ...


class VerifiedMaterialReader(Protocol):
    def load(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        tasks: tuple[SourceTaskState, ...],
    ) -> tuple[VerifiedMaterialView, ...]: ...


@dataclass(frozen=True, slots=True)
class _Material:
    request: CanonicalReportRequest
    provenance: tuple[EvidenceProvenanceV1, ...]
    generated_at: datetime
    generation_receipt_ref: DeepSeekGenerationReceiptRefV2


def _material_path(report_hash: str) -> str:
    digest = report_hash.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise LocalSynthesisError("report_material_hash_invalid")
    return f"m3/report-material/sha256/{digest[:2]}/{digest}.json"


def _encode_material(value: _Material) -> bytes:
    payload = {
        "request": json.loads(encode_report_request(value.request)),
        "provenance": json.loads(encode_provenance(value.provenance)),
        "generated_at": value.generated_at.isoformat(timespec="microseconds"),
        "generation_receipt_ref": value.generation_receipt_ref.model_dump(mode="json"),
    }
    raw = canonical_json(payload).encode("utf-8")
    if not 1 <= len(raw) <= _MAX_MATERIAL_BYTES:
        raise LocalSynthesisError("report_material_size_invalid")
    return raw


def _decode_material(raw: bytes) -> _Material:
    if not 1 <= len(raw) <= _MAX_MATERIAL_BYTES:
        raise LocalSynthesisError("report_material_size_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if type(payload) is not dict or set(payload) != {
            "request",
            "provenance",
            "generated_at",
            "generation_receipt_ref",
        }:
            raise ValueError("material shape differs")
        request = decode_report_request(canonical_json(payload["request"]))
        provenance = decode_provenance(canonical_json(payload["provenance"]))
        generated_at = datetime.fromisoformat(payload["generated_at"])
        if generated_at.tzinfo is None or generated_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("material timestamp is not UTC")
        receipt_ref = DeepSeekGenerationReceiptRefV2.model_validate(
            payload["generation_receipt_ref"]
        )
        result = _Material(request, provenance, generated_at, receipt_ref)
        if _encode_material(result) != raw:
            raise ValueError("material differs from canonical reconstruction")
        return result
    except (TypeError, ValueError, UnicodeError) as error:
        raise LocalSynthesisError("report_material_invalid") from error


def _research_question(scope: ResearchScope) -> str:
    drugs = ", ".join(item.preferred_term for item in scope.drugs)
    reactions = ", ".join(item.preferred_term for item in scope.adverse_reactions)
    return f"What bounded drug-safety evidence relates {drugs} to {reactions}?"


def _checkpoint_locator_ref(evidence: EvidenceInput) -> str:
    if len(evidence.locators) != 1:
        raise LocalSynthesisError("verified_material_locator_ambiguous")
    locator = evidence.locators[0]
    return (
        derive_identity("pubmed-material-locator", locator)
        if evidence.source is SourceType.PUBMED
        else locator
    )


def _semantic_plans_match_receipt(
    plans: tuple[object, ...], projections: tuple[Stage2SemanticInputV2, ...]
) -> bool:
    if any(type(item) is not PlannedStage2SemanticInputV2 for item in plans):
        return False
    exact_plans = cast(tuple[PlannedStage2SemanticInputV2, ...], plans)
    return tuple(
        (
            item.citation_id,
            item.input_digest,
            item.method,
            item.version,
            item.comparison_id,
            item.conflict_id,
        )
        for item in projections
    ) == tuple(
        (
            item.citation_id,
            item.input_digest,
            item.method,
            item.version,
            item.comparison_id,
            item.conflict_id,
        )
        for item in exact_plans
    )


@final
class LocalSynthesisRuntime:
    """One exact synthesis and readback path used by graph and report service."""

    def __init__(
        self,
        *,
        material_reader: VerifiedMaterialReader,
        generation: DeepSeekGenerationV2Service,
        generation_receipts: DeepSeekGenerationV2ReceiptStorePort,
        validation_receipts: ReceiptReadPort,
        registry_store: SnapshotValidationRegistryStore,
        snapshots: SnapshotStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._material_reader = material_reader
        self._generation = generation
        self._generation_receipts = generation_receipts
        self._validation_receipts = validation_receipts
        self._registry_store = registry_store
        self._snapshots = snapshots
        self._clock = clock

    def _verified_material(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        tasks: tuple[SourceTaskState, ...],
    ) -> tuple[tuple[EvidenceInput, ...], tuple[EvidenceProvenanceV1, ...]]:
        rows = self._material_reader.load(run_id=run_id, scope=scope, tasks=tasks)
        if type(rows) is not tuple:
            raise LocalSynthesisError("verified_material_collection_invalid")
        expected = tuple(ref for task in tasks for ref in task.evidence_refs)
        if len(rows) != len(expected):
            raise LocalSynthesisError("verified_material_inventory_incomplete")
        evidence: list[EvidenceInput] = []
        provenance: list[EvidenceProvenanceV1] = []
        for row, ref in zip(rows, expected, strict=True):
            item, origin = row.evidence, row.provenance
            locator_ref = _checkpoint_locator_ref(item) if type(item) is EvidenceInput else None
            if (
                type(item) is not EvidenceInput
                or type(origin) is not EvidenceProvenanceV1
                or item.evidence_id != canonical_evidence_id(item)
                or item.authorized_run_id != run_id
                or (
                    item.evidence_id,
                    item.source,
                    item.snapshot_id,
                    item.content_hash,
                    locator_ref,
                )
                != (
                    ref.evidence_id,
                    ref.source,
                    ref.snapshot_id,
                    ref.content_hash,
                    ref.locator_ref,
                )
                or (
                    origin.evidence_id,
                    origin.source,
                    origin.source_record_id,
                    origin.source_version,
                    origin.snapshot_id,
                    origin.content_hash,
                )
                != (
                    item.evidence_id,
                    item.source,
                    item.source_record_id,
                    item.source_version,
                    item.snapshot_id,
                    item.content_hash,
                )
            ):
                raise LocalSynthesisError("verified_material_authority_drift")
            evidence.append(item)
            provenance.append(origin)
        return tuple(evidence), tuple(provenance)

    def _publish(self, value: _Material) -> None:
        raw = _encode_material(value)
        path = _material_path(value.request.synthesis.report_content_hash)
        if self._snapshots.has_writer_lock:
            self._snapshots.publish_bytes(path, raw, artifact_class="journal")
        else:
            with self._snapshots.writer():
                self._snapshots.publish_bytes(path, raw, artifact_class="journal")
        if self._load(value.request.synthesis.report_content_hash) != value:
            raise LocalSynthesisError("published_report_material_drift")

    def _start_generation_attempt(
        self,
        *,
        report_id: str,
        generation_input: GenerationInput,
        trusted_evidence: tuple[EvidenceInput, ...],
        prior_report_content_hash: str | None,
    ) -> None:
        """Fence an unknown provider outcome before any external generation call."""

        payload = {
            "report_id": report_id,
            "generation_input_hash": sha256_digest(generation_input_bytes(generation_input)),
            "trusted_evidence_hash": deepseek_generation_v2_trusted_evidence_hash(
                generation_input, trusted_evidence
            ),
            "prior_report_content_hash": prior_report_content_hash,
        }
        attempt_id = derive_identity("local-synthesis-attempt", payload)
        digest = attempt_id.removeprefix("local-synthesis-attempt:sha256:")
        relative = f"m3/synthesis-attempts/sha256/{digest[:2]}/{digest}.json"
        target = self._snapshots.root.joinpath(*PurePosixPath(relative).parts)

        def publish_once() -> None:
            self._snapshots._require_safe_path(target, allow_missing_leaf=True)
            if target.exists():
                raise LocalSynthesisError("synthesis_attempt_outcome_unknown")
            self._snapshots.publish_bytes(
                relative,
                canonical_json({"attempt_id": attempt_id, **payload}).encode("utf-8"),
                artifact_class="journal",
            )

        if self._snapshots.has_writer_lock:
            publish_once()
        else:
            with self._snapshots.writer():
                publish_once()

    def _load(self, report_hash: str) -> _Material:
        path = self._snapshots.root.joinpath(*PurePosixPath(_material_path(report_hash)).parts)
        try:
            self._snapshots._require_safe_path(path, allow_missing_leaf=False)
            size = path.stat().st_size
            if not 1 <= size <= _MAX_MATERIAL_BYTES:
                raise LocalSynthesisError("report_material_size_invalid")
            with path.open("rb") as stream:
                raw = stream.read(_MAX_MATERIAL_BYTES + 1)
            self._snapshots._require_safe_path(path, allow_missing_leaf=False)
            if len(raw) != size:
                raise LocalSynthesisError("report_material_changed_during_read")
            result = _decode_material(raw)
            if result.request.synthesis.report_content_hash != report_hash:
                raise LocalSynthesisError("report_material_hash_drift")
            return result
        except OSError as error:
            raise LocalSynthesisError("report_material_unavailable") from error

    def synthesize(
        self,
        *,
        run_id: str,
        report_id: str,
        scope: ResearchScope,
        source_plan: tuple[M1BSourcePlanEntryV1, ...],
        source_tasks: tuple[SourceTaskState, ...],
        prior_report_content_hash: str | None,
    ) -> SynthesisState:
        selected = tuple(
            row.source for row in source_plan if row.planning_status is PlanningStatus.SELECTED
        )
        if (
            type(scope) is not ResearchScope
            or type(source_plan) is not tuple
            or type(source_tasks) is not tuple
            or tuple(row.source for row in source_plan) != scope.selected_sources
            or tuple(task.source for task in source_tasks) != selected
            or any(
                task.status is not SourceTaskStatus.TERMINAL or task.terminal_outcome_ref is None
                for task in source_tasks
            )
        ):
            raise LocalSynthesisError("synthesis_source_graph_invalid")
        all_references, provenance = self._verified_material(
            run_id=run_id, scope=scope, tasks=source_tasks
        )
        claimable = tuple(
            item
            for item in all_references
            if item.permitted_claim_classes and item.permitted_inference_uses
        )
        contexts = tuple(
            GenerationSourceContext.create(
                run_id=run_id,
                source=task.source,
                outcome=task.terminal_outcome_ref.outcome,
                limitation_ids=tuple(sorted(task.terminal_outcome_ref.outcome.warning_codes)),
            )
            for task in source_tasks
            if task.terminal_outcome_ref is not None
        )
        generation_input = GenerationInput(
            run_id=run_id,
            scope_id=scope.scope_id,
            research_question=_research_question(scope),
            selected_sources=scope.selected_sources,
            source_plan=source_plan,
            source_contexts=contexts,
            evidence=tuple(generation_evidence_from_trusted(item) for item in claimable),
            comparisons=(),
            conflicts=(),
        )
        self._start_generation_attempt(
            report_id=report_id,
            generation_input=generation_input,
            trusted_evidence=claimable,
            prior_report_content_hash=prior_report_content_hash,
        )
        generated = self._generation.generate(generation_input, trusted_evidence=claimable)
        mapped = map_generation_v2_to_registry_v4(
            generation_input,
            generated.candidate,
            trusted_evidence=claimable,
            all_verified_source_references=all_references,
        )
        if (
            generated.receipt_ref.run_id != run_id
            or generated.receipt_ref.scope_id != scope.scope_id
            or generated.receipt_ref.candidate_hash != mapped.candidate_hash
        ):
            raise LocalSynthesisError("generation_receipt_mapping_drift")
        registry = mapped.registry
        warnings = {
            code
            for task in source_tasks
            if task.terminal_outcome_ref is not None
            for code in task.terminal_outcome_ref.outcome.warning_codes
        }

        if any(task.source is SourceType.FAERS for task in source_tasks):
            warnings.add("faers_mandatory_limitations")
        if any(task.source is SourceType.CADEC for task in source_tasks):
            warnings.add("cadec_mandatory_limitations")
        provisional = SynthesisState(
            report_content_hash=_ZERO_HASH,
            claims=tuple(ClaimReference(claim_id=item.claim_id) for item in registry.claims),
            citations=tuple(
                CitationReference(
                    citation_id=item.citation_id,
                    claim_id=item.claim_id,
                    evidence_id=item.evidence_id,
                )
                for item in registry.citations
            ),
            comparability_refs=tuple(
                ComparabilityReference(
                    comparability_id=item.comparison_id, artifact_hash=item.artifact_hash
                )
                for item in registry.comparisons
            ),
            conflict_refs=tuple(
                ConflictReference(conflict_id=item.conflict_id, artifact_hash=item.artifact_hash)
                for item in registry.conflicts
            ),
            warning_codes=tuple(sorted(warnings)),
        )
        preliminary = build_validation_request_projection(
            run_id=run_id,
            report_id=report_id,
            scope=scope,
            source_plan=source_plan,
            source_tasks=source_tasks,
            synthesis=provisional,
            registry=registry,
        )
        report_hash = canonical_report_content_hash(preliminary)
        reference = self._registry_store.publish_registry(
            context=RuntimeContext(run_id=run_id, report_id=report_id, scope_id=scope.scope_id),
            report_content_hash=report_hash,
            registry=registry,
        )
        synthesis = provisional.model_copy(
            update={
                "report_content_hash": report_hash,
                "validation_registry_ref": reference,
            }
        )
        request = build_validation_request_projection(
            run_id=run_id,
            report_id=report_id,
            scope=scope,
            source_plan=source_plan,
            source_tasks=source_tasks,
            synthesis=synthesis,
            registry=registry,
        )
        if canonical_report_content_hash(request) != report_hash:
            raise LocalSynthesisError("report_content_hash_drift")
        generated_at = self._clock()
        if (
            type(generated_at) is not datetime
            or generated_at.tzinfo is None
            or generated_at.utcoffset() != UTC.utcoffset(None)
        ):
            raise LocalSynthesisError("report_generation_time_invalid")
        self._publish(_Material(request, provenance, generated_at, generated.receipt_ref))
        return synthesis

    def material_provider(
        self, state: OrchestrationState
    ) -> tuple[CanonicalReportRequest, tuple[EvidenceProvenanceV1, ...], datetime]:
        synthesis = state.synthesis
        scope = state.interpreted_scope or state.original_scope
        if synthesis is None or synthesis.validation_registry_ref is None:
            raise LocalSynthesisError("synthesis_registry_unavailable")
        registry = self._registry_store.load_registry(synthesis.validation_registry_ref)
        material = self._load(synthesis.report_content_hash)
        expected = build_validation_request_projection(
            run_id=state.run_id,
            report_id=state.report_id,
            scope=scope,
            source_plan=state.source_plan,
            source_tasks=state.source_tasks,
            synthesis=synthesis,
            registry=registry,
        )
        if material.request != expected:
            raise LocalSynthesisError("report_material_checkpoint_drift")
        receipt_ref = material.generation_receipt_ref
        if receipt_ref.run_id != state.run_id or receipt_ref.scope_id != scope.scope_id:
            raise LocalSynthesisError("generation_receipt_context_drift")
        generation_receipt, _ = self._generation_receipts.load(receipt_ref)
        if (
            deepseek_generation_v2_receipt_ref(
                verify_deepseek_generation_v2_receipt(generation_receipt)
            )
            != receipt_ref
        ):
            raise LocalSynthesisError("generation_receipt_readback_drift")
        _, provenance = self._verified_material(
            run_id=state.run_id, scope=scope, tasks=state.source_tasks
        )
        if provenance != material.provenance:
            raise LocalSynthesisError("report_material_provenance_drift")
        validation_ref = state.validation_receipt_ref
        if validation_ref is None:
            raise LocalSynthesisError("final_validation_receipt_unavailable")
        payload = self._validation_receipts.load_receipt(validation_ref.receipt_id)
        if payload is None:
            raise LocalSynthesisError("final_validation_receipt_unavailable")
        validation_receipt = validation_receipt_from_payload(dict(payload))
        if (
            type(validation_receipt) is not ValidationReceiptV2
            or validation_receipt.receipt_id != validation_ref.receipt_id
            or validation_receipt.receipt_content_hash != validation_ref.receipt_content_hash
            or (
                validation_receipt.run_id,
                validation_receipt.report_id,
                validation_receipt.report_content_hash,
            )
            != (state.run_id, state.report_id, synthesis.report_content_hash)
            or validation_receipt.configuration_version != registry.configuration_version
        ):
            raise LocalSynthesisError("final_validation_receipt_binding_drift")
        projections = stage2_projections_from_receipt_v2(validation_receipt)
        plans = registry.semantic_expectations
        if not _semantic_plans_match_receipt(plans, projections):
            raise LocalSynthesisError("final_semantic_projection_binding_drift")
        final = replace(
            expected,
            registry=replace(registry, semantic_expectations=projections),
            stored_validation=project_stored_validation(state.validation),
        )
        if canonical_report_content_hash(final) != synthesis.report_content_hash:
            raise LocalSynthesisError("final_report_content_hash_drift")
        audit = canonical_validate_report(final, mode=ValidationMode.VERIFY_BINDING)
        verify_validation_receipt(validation_receipt, request=final, audit=audit)
        return final, provenance, material.generated_at
