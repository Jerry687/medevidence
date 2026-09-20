"""Run-bound DailyMed V2 source projection and verified material inventory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from medevidence.domain import (
    M1BResearchRequestV1,
    ResearchScope,
    SourceOutcome,
    SourceType,
    derive_identity,
)
from medevidence.domain.dailymed_enrichment import (
    DailyMedDiscoveryGroupV2,
    DailyMedSelectionDecisionV2,
)
from medevidence.domain.dailymed_v2_execution import (
    DailyMedV2PackagingResult,
    DailyMedV2SelectedSplResult,
)
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import (
    CollectedEvidenceResult,
    CollectionFailureClassification,
    RequiredSourceOperation,
    SourceOperationInputRef,
    SourceOperationInputRole,
    SourceOperationKind,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskProgressResult,
    SourceTaskState,
    SourceTaskStatus,
    TerminalSourceOperationResult,
    TerminalSourceOutcomeRef,
    validate_required_operation_plan,
)
from medevidence.orchestration.dailymed_faers_capability import FAERS_MANDATORY_WARNING
from medevidence.orchestration.ports import EvidenceCollectionPort
from medevidence.orchestration.source_capabilities import SourceCapabilities
from medevidence.orchestration.source_task_projection import (
    canonical_terminal_source_outcome,
    required_source_operation,
    source_operation_acquisition,
    source_operation_observation,
)
from medevidence.persistence import PersistenceRepository
from medevidence.persistence.dailymed_v2 import DailyMedV2RecordInput
from medevidence.tools.contracts import DailyMedDiscoveryRequest, ResolvedConceptCatalog
from medevidence.tools.dailymed_v2_material import DailyMedV2EvidenceChunk
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import EvidenceInput
from medevidence.tools.source_evidence_material import canonical_faers_bucket_evidence

from .dailymed_v2_provenance import DailyMedV2ProvenanceStore
from .dailymed_v2_record_store import DailyMedV2RecordStore, LoadedDailyMedV2Record
from .dailymed_v2_source_execution import DailyMedV2RunResult, DailyMedV2SourceExecutionBridge
from .evidence_provenance import VerifiedEvidenceProvenanceStore
from .m1b_evidence_provenance import VerifiedM1BEvidenceProvenanceStore
from .m1b_source_execution import FaersSourceExecutionBridge
from .pubmed_material_store import SnapshotPubMedMaterialStore


@dataclass(frozen=True, slots=True)
class VerifiedSourceMaterial:
    """One exact source reference and its reverified original-source lineage."""

    evidence: EvidenceInput
    provenance: EvidenceProvenanceV1


type DailyMedV2BridgeFactory = Callable[
    [SourceTaskState, SourceTaskAttemptRef], DailyMedV2SourceExecutionBridge
]
type FaersBridgeFactory = Callable[
    [SourceTaskState, SourceTaskAttemptRef], FaersSourceExecutionBridge
]
type CadecMaterialReader = Callable[
    [str, ResearchScope, SourceTaskState, TerminalSourceOperationResult],
    tuple[VerifiedSourceMaterial, ...],
]


class VerifiedSourceMaterialReader:
    """Reconstruct every checkpointed reference from durable original-source readers."""

    def __init__(
        self,
        *,
        repository: PersistenceRepository,
        provenance: VerifiedEvidenceProvenanceStore,
        m1b_provenance: VerifiedM1BEvidenceProvenanceStore,
        dailymed_v2_provenance: DailyMedV2ProvenanceStore,
        dailymed_v2_records: DailyMedV2RecordStore,
        pubmed_material: SnapshotPubMedMaterialStore | None,
        pubmed_catalog: ResolvedConceptCatalog | None,
        faers_bridge_factory: FaersBridgeFactory | None,
        cadec_material_reader: CadecMaterialReader | None = None,
    ) -> None:
        self._repository = repository
        self._provenance = provenance
        self._m1b = m1b_provenance
        self._daily = dailymed_v2_provenance
        self._records = dailymed_v2_records
        self._pubmed = pubmed_material
        self._catalog = pubmed_catalog
        self._faers_factory = faers_bridge_factory
        self._cadec = cadec_material_reader

    @staticmethod
    def _material(
        evidence: EvidenceInput, provenance: EvidenceProvenanceV1 | None
    ) -> VerifiedSourceMaterial:
        if provenance is None or (
            provenance.evidence_id != evidence.evidence_id
            or provenance.source is not evidence.source
            or provenance.source_record_id != evidence.source_record_id
            or provenance.source_version != evidence.source_version
            or provenance.snapshot_id != evidence.snapshot_id
            or provenance.content_hash != evidence.content_hash
        ):
            raise ValueError("source material lacks exact verified provenance")
        return VerifiedSourceMaterial(evidence=evidence, provenance=provenance)

    def load(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        tasks: tuple[SourceTaskState, ...],
    ) -> tuple[VerifiedSourceMaterial, ...]:
        if type(scope) is not ResearchScope or type(tasks) is not tuple:
            raise TypeError("source material reader requires exact scope and task inventory")
        output: list[VerifiedSourceMaterial] = []
        for task in tasks:
            if (
                type(task) is not SourceTaskState
                or task.status is not SourceTaskStatus.TERMINAL
                or task.terminal_outcome_ref is None
                or task.terminal_outcome_ref.acquisition.run_id != run_id
                or task.source not in scope.selected_sources
            ):
                raise ValueError("source material task is foreign or nonterminal")
            expected_refs = tuple(task.evidence_refs)
            task_output: list[VerifiedSourceMaterial] = []
            for result in task.operation_results:
                if result.operation.run_id != run_id or result.operation.scope_id != scope.scope_id:
                    raise ValueError("source material operation belongs to another run or scope")
                if result.operation.kind is SourceOperationKind.PUBMED_FETCH:
                    if self._pubmed is None or self._catalog is None:
                        raise ValueError("verified PubMed reader is unavailable")
                    if not result.observations:
                        continue
                    metadata = self._repository.get_snapshot(result.acquisition.snapshot_id)
                    if metadata is None or len(metadata.publications) != 1:
                        raise ValueError("PubMed fetch has no sole persisted publication")
                    publication = metadata.publications[0]
                    if publication["pmid"] != result.operation.input_refs[0].value:
                        raise ValueError("PubMed fetch PMID differs from persisted publication")
                    selection = self._pubmed.load_verified_selection(
                        run_id=run_id,
                        scope=scope,
                        catalog=self._catalog,
                        publication_version_id=publication["publication_version_id"],
                        snapshot_id=result.acquisition.snapshot_id,
                    )
                    if selection is None:
                        raise ValueError("PubMed material journal is missing")
                    evidence = selection.source_reference
                    proof = self._provenance.load_verified_provenance(
                        run_id=run_id,
                        evidence_id=evidence.evidence_id,
                        source=SourceType.PUBMED,
                        source_record_id=evidence.source_record_id,
                        source_version=evidence.source_version,
                        snapshot_id=evidence.snapshot_id,
                        content_hash=evidence.content_hash,
                    )
                    task_output.append(self._material(evidence, proof))
                elif result.operation.kind is SourceOperationKind.DAILYMED_FETCH:
                    for observation in result.observations:
                        loaded = self._records.load_chunk_evidence(
                            run_id=run_id, evidence_id=observation.evidence_id
                        )
                        if loaded is None or type(loaded.payload) is not DailyMedV2EvidenceChunk:
                            raise ValueError("DailyMed V2 evidence chunk is missing")
                        evidence = loaded.payload.evidence()
                        verified = self._daily.load_verified_material(
                            run_id=run_id,
                            evidence_id=evidence.evidence_id,
                            source_record_id=evidence.source_record_id,
                            source_version=evidence.source_version,
                            snapshot_id=evidence.snapshot_id,
                            content_hash=evidence.content_hash,
                        )
                        if verified is None or verified.chunk != loaded.payload:
                            raise ValueError("DailyMed V2 material differs from source replay")
                        task_output.append(self._material(evidence, verified.provenance))
                elif result.operation.kind is SourceOperationKind.FAERS_AGGREGATE:
                    if self._faers_factory is None:
                        raise ValueError("verified FAERS reader is unavailable")
                    bridge = self._faers_factory(task, result.attempt)
                    execution = bridge._load_execution(
                        {
                            "run_id": run_id,
                            "task_id": task.task_id,
                            "attempt_id": result.attempt.attempt_id,
                            "query_id": result.operation.query_id,
                            "acquisition_intent_id": result.acquisition.acquisition_intent_id,
                        }
                    )
                    persisted = bridge.persist(execution).execution
                    source_outcome = persisted.result.source_outcome
                    policy_outcome = SourceOutcome.model_validate(
                        {
                            **source_outcome.model_dump(mode="python"),
                            "warning_codes": tuple(
                                sorted({*source_outcome.warning_codes, FAERS_MANDATORY_WARNING})
                            ),
                        }
                    )
                    if (
                        policy_outcome != result.outcome
                        or persisted.result.snapshot_id != result.acquisition.snapshot_id
                        or persisted.result.query.query_id != result.operation.query_id
                    ):
                        raise ValueError("FAERS material differs from terminal source outcome")
                    for index, _bucket in enumerate(persisted.result.buckets):
                        evidence = canonical_faers_bucket_evidence(persisted, index)
                        faers_verified = self._m1b.load_verified_material(
                            run_id=run_id,
                            evidence_id=evidence.evidence_id,
                            source=SourceType.FAERS,
                            source_record_id=evidence.source_record_id,
                            source_version=evidence.source_version,
                            snapshot_id=evidence.snapshot_id,
                            content_hash=evidence.content_hash,
                        )
                        if (
                            faers_verified is None
                            or faers_verified.locator_ref != evidence.locators[0]
                        ):
                            raise ValueError("FAERS material differs from source replay")
                        task_output.append(self._material(evidence, faers_verified.provenance))
                elif result.operation.kind is SourceOperationKind.CADEC_SEARCH:
                    if result.observations:
                        if self._cadec is None:
                            raise ValueError("CADEC verified material reader is not admitted")
                        task_output.extend(self._cadec(run_id, scope, task, result))
                elif result.observations:
                    raise ValueError("source observations have no verified material reader")
            actual_refs = tuple(
                (
                    item.evidence.evidence_id,
                    item.evidence.source,
                    item.evidence.snapshot_id,
                    item.evidence.content_hash,
                    derive_identity("pubmed-material-locator", item.evidence.locators[0])
                    if item.evidence.source is SourceType.PUBMED
                    else item.evidence.locators[0],
                )
                for item in task_output
            )
            expected = tuple(
                (
                    item.evidence_id,
                    item.source,
                    item.snapshot_id,
                    item.content_hash,
                    item.locator_ref,
                )
                for item in expected_refs
            )
            if actual_refs != expected:
                raise ValueError("verified material inventory differs from source checkpoint")
            output.extend(task_output)
        return tuple(output)


class LocalDailyMedV2Capability:
    """Adapt durable V2 execution to the existing source-neutral task contract."""

    def __init__(
        self,
        *,
        run_id: str,
        request: M1BResearchRequestV1,
        records: DailyMedV2RecordStore,
        bridge_factory: DailyMedV2BridgeFactory,
    ) -> None:
        if (
            type(request) is not M1BResearchRequestV1
            or SourceType.DAILYMED not in request.requested_sources
        ):
            raise TypeError("DailyMed V2 capability requires its exact governed request")
        self._run_id = run_id
        self._request = M1BResearchRequestV1.model_validate(
            request.model_dump(mode="python"), strict=True
        )
        self._records = records
        self._bridge_factory = bridge_factory

    def _initial_operations(self, scope: ResearchScope) -> tuple[RequiredSourceOperation, ...]:
        return tuple(
            required_source_operation(
                run_id=self._run_id,
                scope_id=scope.scope_id,
                source=SourceType.DAILYMED,
                ordinal=ordinal,
                kind=SourceOperationKind.DAILYMED_DISCOVERY,
                query_id=query_id,
                input_refs=(
                    SourceOperationInputRef(
                        role=SourceOperationInputRole.REQUEST,
                        value=derive_identity("dailymed-discovery-request", request),
                    ),
                ),
            )
            for ordinal, selection in enumerate(self._request.dailymed_selection_requests)
            for query_id in (
                derive_identity(
                    "dailymed-discovery-query",
                    {"run_id": self._run_id, "scope_id": scope.scope_id, "request": selection},
                ),
            )
            for request in (
                DailyMedDiscoveryRequest(selection_request=selection, query_id=query_id),
            )
        )

    def _require_context(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> None:
        if (
            type(task) is not SourceTaskState
            or type(scope) is not ResearchScope
            or type(attempt) is not SourceTaskAttemptRef
            or scope != self._request.scope
            or task.source is not SourceType.DAILYMED
            or task.task_id != self._initial_operations(scope)[0].task_id
            or attempt.task_id != task.task_id
        ):
            raise ValueError("DailyMed V2 task belongs to another run or scope")

    def plan_operations(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> tuple[RequiredSourceOperation, ...]:
        self._require_context(task, scope, attempt)
        operations = self._initial_operations(scope)
        if task.status is SourceTaskStatus.PENDING:
            if task.attempts != 0 or task.required_operations or attempt.attempt_number != 1:
                raise ValueError("DailyMed V2 pending plan is not pristine")
        elif task.status is SourceTaskStatus.RUNNING:
            if task.active_attempt != attempt or task.required_operations != operations:
                raise ValueError("DailyMed V2 running plan differs")
        else:
            raise ValueError("DailyMed V2 plan requires pending or running task")
        return operations

    def _load_slot(
        self, attempt: SourceTaskAttemptRef, kind: str, query_id: str
    ) -> LoadedDailyMedV2Record:
        loaded = self._records.load_slot(
            run_id=self._run_id,
            attempt_id=attempt.attempt_id,
            record_kind=kind,  # type: ignore[arg-type]
            query_id=query_id,
        )
        if loaded is None or loaded.record.task_id != attempt.task_id:
            raise ValueError("DailyMed V2 executed operation has no exact durable record")
        return loaded

    @staticmethod
    def _result(
        operation: RequiredSourceOperation,
        attempt: SourceTaskAttemptRef,
        record: DailyMedV2RecordInput,
        outcome: object,
        evidence: tuple[EvidenceInput, ...] = (),
    ) -> TerminalSourceOperationResult:
        from medevidence.domain import SourceOutcome

        checked = SourceOutcome.model_validate(outcome)
        if (
            record.run_id != operation.run_id
            or record.task_id != operation.task_id
            or record.attempt_id != attempt.attempt_id
            or record.query_id != operation.query_id
            or checked.query_id != operation.query_id
        ):
            raise ValueError("DailyMed V2 record differs from planned source operation")
        acquisition = source_operation_acquisition(
            operation=operation,
            attempt_id=attempt.attempt_id,
            acquisition_intent_id=record.acquisition_intent_id,
            outcome=checked,
            snapshot_id=record.snapshot_id,
        )
        observations = tuple(
            source_operation_observation(
                operation=operation,
                acquisition=acquisition,
                evidence_id=item.evidence_id,
                content_hash=item.content_hash,
                locator_ref=item.locators[0],
            )
            for item in evidence
        )
        return TerminalSourceOperationResult(
            operation=operation,
            attempt=attempt,
            acquisition=acquisition,
            outcome=checked,
            observations=observations,
        )

    def _project(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
        executed: DailyMedV2RunResult | None,
    ) -> CollectedEvidenceResult:
        operations = list(self._initial_operations(scope))
        results: list[TerminalSourceOperationResult] = []
        groups: list[DailyMedDiscoveryGroupV2] = []
        for operation in operations:
            loaded = self._load_slot(attempt, "discovery", operation.query_id)
            if type(loaded.payload) is not DailyMedDiscoveryGroupV2:
                raise ValueError("DailyMed V2 discovery record type differs")
            groups.append(loaded.payload)
            results.append(self._result(operation, attempt, loaded.record, loaded.payload.outcome))
        if executed is not None and tuple(groups) != executed.groups:
            raise ValueError("DailyMed V2 discovery result differs from durable replay")

        packaging: list[DailyMedV2PackagingResult] = []
        for group in groups:
            for summary in group.summaries:
                query_id = derive_identity(
                    "dailymed-packaging-query-v2",
                    {
                        "summary_id": summary.summary_id,
                        "setid": summary.setid,
                        "spl_version": summary.current_spl_version,
                    },
                )
                packaging_loaded = self._records.load_slot(
                    run_id=self._run_id,
                    attempt_id=attempt.attempt_id,
                    record_kind="packaging",
                    query_id=query_id,
                )
                if packaging_loaded is None:
                    continue
                if type(packaging_loaded.payload) is not DailyMedV2PackagingResult:
                    raise ValueError("DailyMed V2 packaging record type differs")
                packaging.append(packaging_loaded.payload)
                operation = required_source_operation(
                    run_id=self._run_id,
                    scope_id=scope.scope_id,
                    source=SourceType.DAILYMED,
                    ordinal=len(operations),
                    kind=SourceOperationKind.DAILYMED_CANDIDATE_ENRICHMENT,
                    query_id=query_id,
                    input_refs=(
                        SourceOperationInputRef(
                            role=SourceOperationInputRole.DISCOVERY_SUMMARY,
                            value=summary.summary_id,
                        ),
                        SourceOperationInputRef(
                            role=SourceOperationInputRole.DAILYMED_DISCOVERY_QUERY,
                            value=group.discovery_query_id,
                        ),
                        SourceOperationInputRef(
                            role=SourceOperationInputRole.SETID, value=summary.setid
                        ),
                        SourceOperationInputRef(
                            role=SourceOperationInputRole.SPL_VERSION,
                            value=summary.current_spl_version,
                        ),
                    ),
                )
                operations.append(operation)
                results.append(
                    self._result(
                        operation,
                        attempt,
                        packaging_loaded.record,
                        packaging_loaded.payload.source_outcome,
                    )
                )
        if executed is not None and tuple(packaging) != executed.packaging:
            raise ValueError("DailyMed V2 packaging result differs from durable replay")

        decisions: list[DailyMedSelectionDecisionV2] = []
        for group in groups:
            loaded = self._load_slot(attempt, "decision", group.discovery_query_id)
            if type(loaded.payload) is not DailyMedSelectionDecisionV2:
                raise ValueError("DailyMed V2 decision record type differs")
            decisions.append(loaded.payload)
        if executed is not None and tuple(decisions) != executed.decisions:
            raise ValueError("DailyMed V2 selection decisions differ from durable replay")

        selected = []
        chunks = []
        for decision in decisions:
            if decision.selected_candidate_id is None:
                continue
            if decision.selected_setid is None or decision.selected_spl_version is None:
                raise ValueError("DailyMed V2 selected decision lacks exact identity")
            loaded = self._load_slot(attempt, "selected_spl", decision.discovery_query_id)
            if type(loaded.payload) is not DailyMedV2SelectedSplResult:
                raise ValueError("DailyMed V2 selected SPL record type differs")
            record = loaded.payload.selected
            if record is not None:
                selected.append(record)
            operation = required_source_operation(
                run_id=self._run_id,
                scope_id=scope.scope_id,
                source=SourceType.DAILYMED,
                ordinal=len(operations),
                kind=SourceOperationKind.DAILYMED_FETCH,
                query_id=decision.discovery_query_id,
                input_refs=(
                    SourceOperationInputRef(
                        role=SourceOperationInputRole.DAILYMED_DECISION, value=decision.decision_id
                    ),
                    SourceOperationInputRef(
                        role=SourceOperationInputRole.CANDIDATE,
                        value=decision.selected_candidate_id,
                    ),
                    SourceOperationInputRef(
                        role=SourceOperationInputRole.SETID, value=decision.selected_setid
                    ),
                    SourceOperationInputRef(
                        role=SourceOperationInputRole.SPL_VERSION,
                        value=decision.selected_spl_version,
                    ),
                ),
            )
            operations.append(operation)
            selected_chunks = tuple(
                self._records.load_chunk_evidence(run_id=self._run_id, evidence_id=item)
                for item in (() if record is None else record.evidence_chunk_ids)
            )
            if any(item is None for item in selected_chunks):
                raise ValueError("DailyMed V2 selected chunk disappeared")
            current_chunks: list[DailyMedV2EvidenceChunk] = []
            for item in selected_chunks:
                assert item is not None
                if type(item.payload) is not DailyMedV2EvidenceChunk:
                    raise ValueError("DailyMed V2 selected chunk type differs")
                chunks.append(item.payload)
                current_chunks.append(item.payload)
            evidence = tuple(item.evidence() for item in current_chunks)
            results.append(
                self._result(
                    operation, attempt, loaded.record, loaded.payload.source_outcome, evidence
                )
            )
        if executed is not None and tuple(selected) != executed.selected_spl:
            raise ValueError("DailyMed V2 selected SPL results differ from durable replay")
        if executed is not None and tuple(chunks) != executed.evidence_chunks:
            raise ValueError("DailyMed V2 admitted chunks differ from durable replay")
        if len(chunks) > 100:
            raise ValueError("DailyMed V2 task material cap exceeded during replay")
        plan = tuple(operations)
        terminal_results = tuple(results)
        validate_required_operation_plan(SourceType.DAILYMED, plan)
        outcome = canonical_terminal_source_outcome(plan, terminal_results)
        representative = terminal_results[0].acquisition
        from medevidence.domain import AcquisitionOutcomeRef

        terminal = TerminalSourceOutcomeRef(
            terminal_outcome_id=derive_identity("source-task-terminal-outcome", outcome),
            operation_acquisition_ids=tuple(
                item.acquisition.acquisition_id for item in terminal_results
            ),
            acquisition=AcquisitionOutcomeRef(
                run_id=self._run_id,
                source=SourceType.DAILYMED,
                acquisition_id=representative.acquisition_id,
                acquisition_intent_id=representative.acquisition_intent_id,
                acquisition_ordinal=representative.ordinal,
                operation="search",
                query_id=representative.query_id,
                source_outcome_id=representative.source_outcome_id,
                snapshot_id=representative.snapshot_id,
            ),
            outcome=outcome,
        )
        limitations = set()
        if outcome.coverage_status.value != "complete":
            limitations.add("DailyMed current-label source coverage is partial or unavailable.")
        if any(item.selected_candidate_id is None for item in decisions):
            limitations.add("At least one DailyMed current-label selection remained unresolved.")
        if any(
            item.operation.kind is SourceOperationKind.DAILYMED_FETCH
            and item.outcome.coverage_status.value != "complete"
            for item in terminal_results
        ):
            limitations.add("At least one selected DailyMed current label was unavailable.")
        if outcome.result_status.value == "matches" and not chunks:
            limitations.add(
                "DailyMed candidates supplied no verified current-label section material."
            )
        return CollectedEvidenceResult(
            attempt=attempt,
            required_operations=plan,
            operation_results=terminal_results,
            terminal_outcome_ref=terminal,
            evidence_refs=tuple(
                observation.evidence_reference
                for result in terminal_results
                for observation in result.observations
            ),
            limitations=tuple(sorted(limitations)),
        )

    def collect(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> CollectedEvidenceResult | SourceTaskFailureRef:
        self.plan_operations(task, scope, attempt)
        if task.status is not SourceTaskStatus.RUNNING:
            raise ValueError("DailyMed V2 collection requires a running task")
        bridge = self._bridge_factory(task, attempt)
        if type(bridge) is not DailyMedV2SourceExecutionBridge:
            raise TypeError("DailyMed V2 factory returned a noncanonical execution bridge")
        executed = bridge.execute_current()
        if {"task_chunk_cap_exceeded", "chunk_cap_exceeded"} & set(executed.review_reason_codes):
            return SourceTaskFailureRef(
                failure_id=derive_identity(
                    "source-task-material-admission-failure",
                    {
                        "run_id": self._run_id,
                        "task_id": task.task_id,
                        "attempt_id": attempt.attempt_id,
                        "reason": "dailymed_material_cap_exceeded",
                    },
                ),
                attempt=attempt,
                classification=CollectionFailureClassification.PERMANENT,
                reason_code="dailymed_material_cap_exceeded",
            )
        return self._project(task, scope, attempt, executed)

    def validate_terminal_task(self, task: SourceTaskState, scope: ResearchScope) -> None:
        if task.status is not SourceTaskStatus.TERMINAL or not task.operation_results:
            raise ValueError("DailyMed V2 replay requires a terminal task")
        attempt = task.operation_results[0].attempt
        self._require_context(task, scope, attempt)
        projected = self._project(task, scope, attempt, None)
        if (
            task.required_operations != projected.required_operations
            or task.operation_results != projected.operation_results
            or task.terminal_outcome_ref != projected.terminal_outcome_ref
            or task.evidence_refs != projected.evidence_refs
            or task.limitations != projected.limitations
        ):
            raise ValueError("DailyMed V2 terminal checkpoint differs from durable replay")


class LocalSourceEvidenceCollection:
    """Dispatch run-scoped V2 and FAERS authorities around sealed source services."""

    def __init__(
        self,
        *,
        base: EvidenceCollectionPort,
        snapshots: SnapshotStore,
        dailymed_v2: LocalDailyMedV2Capability | None,
        faers_factory: Callable[[SourceTaskState, SourceTaskAttemptRef], SourceCapabilities] | None,
    ) -> None:
        self._base = base
        self._snapshots = snapshots
        self._daily = dailymed_v2
        self._faers_factory = faers_factory

    def plan_operations(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> tuple[RequiredSourceOperation, ...]:
        if task.source is SourceType.DAILYMED:
            if self._daily is None:
                raise ValueError("DailyMed V2 capability is not configured")
            return self._daily.plan_operations(task, scope, attempt)
        if task.source is SourceType.FAERS:
            if self._faers_factory is None:
                raise ValueError("FAERS capability is not configured")
            return self._faers_factory(task, attempt).plan_operations(task, scope, attempt)
        return self._base.plan_operations(task, scope, attempt)

    def collect(
        self, task: SourceTaskState, scope: ResearchScope, attempt: SourceTaskAttemptRef
    ) -> CollectedEvidenceResult | SourceTaskFailureRef | SourceTaskProgressResult:
        if task.source is SourceType.DAILYMED:
            if self._daily is None:
                raise ValueError("DailyMed V2 capability is not configured")
            return self._daily.collect(task, scope, attempt)
        if task.source is SourceType.FAERS:
            if self._faers_factory is None:
                raise ValueError("FAERS capability is not configured")
            return self._faers_factory(task, attempt).collect(task, scope, attempt)
        if task.source is SourceType.PUBMED:
            with self._snapshots.writer():
                return self._base.collect(task, scope, attempt)
        return self._base.collect(task, scope, attempt)

    def validate_terminal_task(self, task: SourceTaskState, scope: ResearchScope) -> None:
        if task.source is SourceType.DAILYMED:
            if self._daily is None:
                raise ValueError("DailyMed V2 capability is not configured")
            self._daily.validate_terminal_task(task, scope)
            return
        if task.source is SourceType.FAERS:
            if self._faers_factory is None or not task.operation_results:
                raise ValueError("FAERS terminal replay lacks its exact attempt")
            self._faers_factory(task, task.operation_results[0].attempt).validate_terminal_task(
                task, scope
            )
            return
        self._base.validate_terminal_task(task, scope)
