"""Explicit composition of durable source, model, graph, and review adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, cast
from uuid import uuid4

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver

from medevidence.composition import LocalSourceRuntimeBundle, build_local_source_runtime
from medevidence.domain import ResearchScope, SourceType, canonical_json
from medevidence.infrastructure.deepseek_generation_v2 import DeepSeekResponsesGenerationV2Gateway
from medevidence.infrastructure.deepseek_generation_v2_receipts import (
    DeepSeekGenerationV2ReceiptStore,
)
from medevidence.infrastructure.langgraph_checkpoint import postgres_checkpoint_saver
from medevidence.infrastructure.local_export_writer import LocalExportWriter
from medevidence.infrastructure.local_runtime_identity import (
    RuntimeImplementationIdentity,
    bind_runtime_implementation,
    capture_runtime_identity,
)
from medevidence.infrastructure.local_runtime_settings import LocalRuntimeSettings
from medevidence.infrastructure.local_source_policy import SourceAwareLocalScopeSafety
from medevidence.infrastructure.local_synthesis_runtime import LocalSynthesisRuntime
from medevidence.infrastructure.qwen_semantic_cache import DurableQwenSemanticEvaluationPortV2
from medevidence.infrastructure.qwen_semantic_evaluator import QwenChatSemanticEvaluatorV2
from medevidence.infrastructure.review_export_store import ReviewExportStore
from medevidence.infrastructure.runtime_application import ResearchApplicationService
from medevidence.infrastructure.v2_receipt_store import V2ReceiptStore
from medevidence.infrastructure.validation_registry_store import SnapshotValidationRegistryStore
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.orchestration.contracts import OrchestrationState, RuntimeContext
from medevidence.orchestration.langgraph_runtime import LangGraphOrchestrationRuntime
from medevidence.orchestration.workflow import ControlledOrchestrationWorkflow
from medevidence.persistence.repositories import PersistenceRepository, ReviewExportRepository
from medevidence.persistence.research_jobs import ResearchJobIntegrityError, ResearchJobRepository
from medevidence.persistence.semantic_cache import SemanticCacheRepository
from medevidence.tools.generation_v2_service import DeepSeekGenerationV2Service
from medevidence.tools.report_document import EvidenceProvenanceV1
from medevidence.tools.report_validation import CanonicalReportRequest, SemanticEvaluationInput


class _NoLegacySemanticEvaluation:
    def evaluate(self, value: SemanticEvaluationInput) -> object:
        del value
        raise ValueError("legacy semantic evaluation is not configured in the Qwen runtime")


@dataclass(frozen=True, slots=True)
class _Run:
    scope: ResearchScope
    sources: LocalSourceRuntimeBundle
    synthesis: LocalSynthesisRuntime


class LocalRuntimeFactory:
    """Run-bound adapters; persisted jobs/checkpoints remain the state authority."""

    def __init__(
        self,
        *,
        settings: LocalRuntimeSettings,
        repository: PersistenceRepository,
        jobs: ResearchJobRepository,
        snapshots: SnapshotStore,
        receipts: V2ReceiptStore,
        generation: DeepSeekGenerationV2Service,
        generation_receipts: DeepSeekGenerationV2ReceiptStore,
        semantic: DurableQwenSemanticEvaluationPortV2,
        checkpointer: BaseCheckpointSaver[Any],
        source_transport_factory: Callable[[], httpx.BaseTransport],
        implementation: RuntimeImplementationIdentity,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._jobs = jobs
        self._snapshots = snapshots
        self._receipts = receipts
        self._generation = generation
        self._generation_receipts = generation_receipts
        self._semantic = semantic
        self._checkpointer = checkpointer
        self._source_transport_factory = source_transport_factory
        self._implementation = implementation
        self._registry = SnapshotValidationRegistryStore(snapshots)
        self._safety = SourceAwareLocalScopeSafety()
        self._runs: dict[str, _Run] = {}
        self._lock = RLock()
        self._review: ReviewExportStore | None = None

    def bind_review(self, review: ReviewExportStore) -> None:
        if self._review is not None:
            raise ValueError("review store is already bound")
        self._review = review

    def close(self) -> None:
        with self._lock:
            for entry in self._runs.values():
                entry.sources.close()
            self._runs.clear()

    def _run(self, run_id: str) -> _Run:
        with self._lock:
            row = self._jobs.load(run_id)
            if row is None:
                raise ResearchJobIntegrityError("runtime job is not registered")
            scope = ResearchScope.model_validate_json(
                canonical_json(row["scope_payload"]), strict=True
            )
            if scope.scope_id != row["scope_id"]:
                raise ResearchJobIntegrityError("runtime job scope differs")
            if run_id in self._runs:
                entry = self._runs[run_id]
                if entry.scope != scope:
                    raise ResearchJobIntegrityError("runtime scope changed")
                return entry
            # Bound retained connector resources without evicting an active review/run.
            if len(self._runs) >= 128:
                raise ResearchJobIntegrityError(
                    "local runtime adapter capacity reached; restart required"
                )
            bind_runtime_implementation(self._snapshots, self._implementation, run_id=run_id)
            sources = build_local_source_runtime(
                run_id=run_id,
                scope=scope,
                run_created_at_utc=cast(datetime, row["created_at_utc"]),
                code_revision=self._settings.code_revision,
                snapshots=self._snapshots,
                repository=self._repository,
                jobs=self._jobs,
                transport_factory=self._source_transport_factory,
                attempt_id_factory=lambda: "attempt:" + str(uuid4()),
                utc_now=lambda: datetime.now(UTC),
                cadec_archive_path=self._settings.cadec_archive,
                cadec_manifest_path=self._settings.cadec_manifest,
            )
            synthesis = LocalSynthesisRuntime(
                material_reader=sources.material_reader,
                generation=self._generation,
                generation_receipts=self._generation_receipts,
                validation_receipts=self._receipts,
                registry_store=self._registry,
                snapshots=self._snapshots,
            )
            entry = _Run(scope, sources, synthesis)
            self._runs[run_id] = entry
            return entry

    def __call__(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        report_id: str,
        checkpoint_id: str,
        destination_id: str,
    ) -> LangGraphOrchestrationRuntime:
        row = self._jobs.load(run_id)
        if row is None or any(
            row[name] != value
            for name, value in (
                ("scope_id", scope.scope_id),
                ("report_id", report_id),
                ("checkpoint_id", checkpoint_id),
                ("destination_id", destination_id),
            )
        ):
            raise ResearchJobIntegrityError("runtime request differs from its registered job")
        entry = self._run(run_id)
        if entry.scope != scope or self._review is None:
            raise ResearchJobIntegrityError("runtime scope or review binding is unavailable")
        workflow = ControlledOrchestrationWorkflow(
            scope_safety=self._safety,
            source_planning=entry.sources.planning,
            evidence_collection=entry.sources.evidence_collection,
            synthesis=entry.synthesis,
            runtime_context=RuntimeContext(
                run_id=run_id, report_id=report_id, scope_id=scope.scope_id
            ),
            validation_registry_provider=self._registry,
            semantic_result_provider=_NoLegacySemanticEvaluation(),
            semantic_result_provider_v2=self._semantic,
            stage1_receipt_store=self._receipts,
            validation_receipt_store=self._receipts,
            draft_persistence=self._review,
            export_approval=self._review,
            export=self._review,
        )
        return LangGraphOrchestrationRuntime(workflow=workflow, checkpointer=self._checkpointer)

    def material_provider(
        self, state: OrchestrationState
    ) -> tuple[CanonicalReportRequest, tuple[EvidenceProvenanceV1, ...], datetime]:
        return self._run(state.run_id).synthesis.material_provider(state)

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
    ) -> EvidenceProvenanceV1 | None:
        return self._run(run_id).sources.provenance_store.load_verified_provenance(
            run_id=run_id,
            evidence_id=evidence_id,
            source=source,
            source_record_id=source_record_id,
            source_version=source_version,
            snapshot_id=snapshot_id,
            content_hash=content_hash,
        )


@contextmanager
def open_local_application(
    settings: LocalRuntimeSettings,
    *,
    source_transport_factory: Callable[[], httpx.BaseTransport] = httpx.HTTPTransport,
    generation_transport: httpx.BaseTransport | None = None,
    qwen_transport: httpx.AsyncBaseTransport | None = None,
    export_writer: LocalExportWriter | None = None,
) -> Iterator[ResearchApplicationService]:
    """Open only local infrastructure; source/model I/O requires explicit submission."""
    implementation = capture_runtime_identity(settings.code_revision)
    with ExitStack() as resources:
        repository = PersistenceRepository(settings.database)
        resources.callback(repository.close)
        jobs = ResearchJobRepository(settings.database)
        resources.callback(jobs.close)
        review_repository = ReviewExportRepository(settings.database)
        resources.callback(review_repository.close)
        journal = SemanticCacheRepository(settings.database)
        resources.callback(journal.close)
        snapshots = SnapshotStore(settings.snapshot_root)
        receipts = V2ReceiptStore(repository)
        generation_receipts = DeepSeekGenerationV2ReceiptStore(snapshots)
        generation_http = (
            generation_transport if generation_transport is not None else httpx.HTTPTransport()
        )
        resources.callback(generation_http.close)
        qwen_http = (
            qwen_transport
            if qwen_transport is not None
            else httpx.AsyncHTTPTransport(
                limits=httpx.Limits(
                    max_connections=1, max_keepalive_connections=1, keepalive_expiry=30
                ),
                retries=0,
            )
        )
        evaluator = QwenChatSemanticEvaluatorV2(
            api_key=settings.qwen_api_key, endpoint=settings.qwen_endpoint, transport=qwen_http
        )
        resources.callback(evaluator.close)
        semantic = DurableQwenSemanticEvaluationPortV2(
            evaluator=evaluator, journal=journal, stage1_receipts=receipts
        )
        generation = DeepSeekGenerationV2Service(
            gateway=DeepSeekResponsesGenerationV2Gateway(
                api_key=settings.generation_api_key, transport=generation_http
            ),
            store=generation_receipts,
        )
        saver = resources.enter_context(postgres_checkpoint_saver(settings.database, setup=True))
        factory = LocalRuntimeFactory(
            settings=settings,
            repository=repository,
            jobs=jobs,
            snapshots=snapshots,
            receipts=receipts,
            generation=generation,
            generation_receipts=generation_receipts,
            semantic=semantic,
            checkpointer=saver,
            source_transport_factory=source_transport_factory,
            implementation=implementation,
        )
        resources.callback(factory.close)
        review = ReviewExportStore(
            review_repository,
            receipt_store=receipts,
            provenance_store=factory,
            writer=export_writer,
        )
        factory.bind_review(review)
        service = ResearchApplicationService(
            runtime_factory=factory,
            scope_safety=SourceAwareLocalScopeSafety(),
            jobs=jobs,
            review_export=review,
            material_provider=factory.material_provider,
            receipt_store=receipts,
        )
        resources.callback(service.close)
        yield service
