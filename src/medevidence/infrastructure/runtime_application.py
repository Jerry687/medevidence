"""PostgreSQL-backed local research application over the real LangGraph runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import BoundedSemaphore, Lock
from typing import Protocol, cast

from pydantic import ValidationError

from medevidence.domain import ResearchScope, canonical_json, derive_identity, sha256_digest
from medevidence.orchestration.contracts import (
    ExportDestinationRef,
    OrchestrationState,
    ReviewDecision,
    ReviewRecord,
    SafetyOutcome,
    WorkflowDisposition,
    WorkflowNode,
    export_idempotency_key,
)
from medevidence.orchestration.langgraph_runtime import (
    LangGraphOrchestrationRuntime,
)
from medevidence.orchestration.ports import ScopeSafetyPort
from medevidence.persistence.repositories import PersistenceConflict
from medevidence.persistence.research_jobs import (
    ResearchJobConflict,
    ResearchJobIntegrityError,
    ResearchJobRepository,
)
from medevidence.tools.report_document import EvidenceProvenanceV1, ReceiptReadPort
from medevidence.tools.report_validation import CanonicalReportRequest
from medevidence.tools.research_application import (
    ResearchApplicationErrorCode,
    ResearchApplicationFailure,
    ResearchExportArtifact,
    ResearchExportFormat,
    ResearchReportView,
    ResearchReviewCommand,
    ResearchRunList,
    ResearchRunStatus,
    ResearchRunView,
    ResearchSubmission,
)

from .review_export_store import ReviewExportStore

_LOGGER = logging.getLogger(__name__)
_MAX_QUEUED = 8
type MaterialProvider = Callable[
    [OrchestrationState],
    tuple[CanonicalReportRequest, tuple[EvidenceProvenanceV1, ...], datetime],
]


class RuntimeFactory(Protocol):
    """Bind one trusted job context to a fresh runtime over shared checkpoints."""

    def __call__(
        self,
        *,
        run_id: str,
        scope: ResearchScope,
        report_id: str,
        checkpoint_id: str,
        destination_id: str,
    ) -> LangGraphOrchestrationRuntime: ...


def _fail(code: ResearchApplicationErrorCode) -> ResearchApplicationFailure:
    return ResearchApplicationFailure(code)


class ResearchApplicationService:
    """Own bounded dispatch; PostgreSQL jobs and LangGraph checkpoints own state."""

    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        scope_safety: ScopeSafetyPort,
        jobs: ResearchJobRepository,
        review_export: ReviewExportStore,
        material_provider: MaterialProvider,
        receipt_store: ReceiptReadPort,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._scope_safety = scope_safety
        self._jobs = jobs
        self._review_export = review_export
        self._material_provider = material_provider
        self._receipt_store = receipt_store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research-job")
        self._slots = BoundedSemaphore(_MAX_QUEUED)
        self._queued: set[str] = set()
        self._queued_lock = Lock()

    def close(self) -> None:
        self._executor.shutdown(wait=True)

    def _schedule(self, run_id: str) -> None:
        if not self._slots.acquire(blocking=False):
            return
        with self._queued_lock:
            if run_id in self._queued:
                self._slots.release()
                return
            self._queued.add(run_id)
        try:
            self._executor.submit(self._run_start, run_id)
        except RuntimeError:
            with self._queued_lock:
                self._queued.discard(run_id)
            self._slots.release()
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None

    def dispatch_submitted(self) -> int:
        """Queue registered-only jobs; never retry running or unknown attempts."""

        count = 0
        for row in self._jobs.list(limit=50, offset=0):
            if row["phase"] == "submitted":
                self._schedule(cast(str, row["run_id"]))
                count += 1
        return count

    @staticmethod
    def _verified_scope(row: dict[str, object]) -> ResearchScope:
        raw_scope = row["scope_payload"]
        if type(raw_scope) is not dict:
            raise ResearchJobIntegrityError("permitted job lacks canonical scope")
        scope = ResearchScope.model_validate_json(canonical_json(raw_scope), strict=True)
        if scope.scope_id != row["scope_id"]:
            raise ResearchJobIntegrityError("persisted typed scope identity drift")
        if scope.model_dump(mode="json") != raw_scope:
            raise ResearchJobIntegrityError("persisted typed scope payload drift")
        return scope

    @staticmethod
    def _initial(row: dict[str, object]) -> OrchestrationState:
        scope = ResearchApplicationService._verified_scope(row)
        return OrchestrationState(
            workflow_id=cast(str, row["workflow_id"]),
            checkpoint_id=cast(str, row["checkpoint_id"]),
            run_id=cast(str, row["run_id"]),
            report_id=cast(str, row["report_id"]),
            original_scope=scope,
            destination=ExportDestinationRef(destination_id=cast(str, row["destination_id"])),
        )

    def _runtime_for(self, row: dict[str, object]) -> LangGraphOrchestrationRuntime:
        runtime = self._runtime_factory(
            run_id=cast(str, row["run_id"]),
            scope=self._verified_scope(row),
            report_id=cast(str, row["report_id"]),
            checkpoint_id=cast(str, row["checkpoint_id"]),
            destination_id=cast(str, row["destination_id"]),
        )
        if type(runtime) is not LangGraphOrchestrationRuntime:
            raise ResearchJobIntegrityError("runtime factory returned an invalid runtime")
        return runtime

    def _prepare_material(self, state: OrchestrationState) -> None:
        ref = state.validation_receipt_ref
        synthesis = state.synthesis
        if ref is None or synthesis is None or state.pending_draft is None:
            raise ResearchJobIntegrityError("review interrupt lacks final validated bindings")
        payload = self._receipt_store.load_receipt(ref.receipt_id)
        if payload is None:
            raise ResearchJobIntegrityError("final validation receipt is unavailable")
        existing = self._review_export.get_document(state.report_id, synthesis.report_content_hash)
        if existing is not None:
            document = existing.document
            if (
                document.run_id != state.run_id
                or document.scope_id != state.original_scope.scope_id
                or document.validation_receipt_id != ref.receipt_id
                or document.validation_receipt_hash != ref.receipt_content_hash
            ):
                raise ResearchJobIntegrityError("persisted report material differs from checkpoint")
            return
        request, provenance, generated_at = self._material_provider(state)
        if (
            type(request) is not CanonicalReportRequest
            or type(provenance) is not tuple
            or type(generated_at) is not datetime
            or request.run_id != state.run_id
            or request.report_id != state.report_id
            or request.synthesis.report_content_hash != synthesis.report_content_hash
        ):
            raise ResearchJobIntegrityError("material provider differs from checkpoint")
        self._review_export.prepare_document(request, payload, provenance, generated_at)

    def _run_start(self, run_id: str) -> None:
        try:
            row = self._jobs.transition(run_id, expected="submitted", target="running")
            if row is None:
                return
            try:
                result = self._runtime_for(row).start(self._initial(row))
            except Exception:
                _LOGGER.error("research runtime start failed", extra={"run_id": run_id})
                self._jobs.transition(
                    run_id,
                    expected="running",
                    target="unavailable",
                    error_code="execution_unavailable",
                )
                return
            if result.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL:
                try:
                    self._prepare_material(result.state)
                except Exception:
                    _LOGGER.error(
                        "research report material is unavailable", extra={"run_id": run_id}
                    )
                    self._jobs.transition(
                        run_id,
                        expected="running",
                        target="unavailable",
                        error_code="material_unavailable",
                    )
                    return
                self._jobs.transition(run_id, expected="running", target="pending_review")
            elif result.terminal:
                self._jobs.transition(
                    run_id,
                    expected="running",
                    target="blocked",
                    error_code="execution_blocked",
                )
            else:
                self._jobs.transition(
                    run_id,
                    expected="running",
                    target="unavailable",
                    error_code="execution_unavailable",
                )
        except Exception:
            _LOGGER.error("research worker registry operation failed", extra={"run_id": run_id})
        finally:
            with self._queued_lock:
                self._queued.discard(run_id)
            self._slots.release()
            try:
                self.dispatch_submitted()
            except Exception:
                _LOGGER.error("research queue dispatch failed")

    def submit(self, request: ResearchSubmission) -> ResearchRunView:
        if type(request) is not ResearchSubmission:
            raise ValueError("research submission type is invalid")
        try:
            safety = self._scope_safety.evaluate(request.scope)
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if safety.decision.outcome is not SafetyOutcome.PERMITTED:
            raise _fail(ResearchApplicationErrorCode.SCOPE_REJECTED)
        try:
            scope_payload = request.scope.model_dump(mode="json")
            if (
                ResearchScope.model_validate_json(canonical_json(scope_payload), strict=True)
                != request.scope
            ):
                raise ValueError("submitted scope typed roundtrip drift")
            row, _ = self._jobs.create(
                idempotency_key=request.idempotency_key,
                scope_id=request.scope.scope_id,
                scope_payload=scope_payload,
            )
            self._verified_scope(row)
        except ResearchJobConflict:
            raise _fail(ResearchApplicationErrorCode.CONFLICT) from None
        except (ResearchJobIntegrityError, ValueError, ValidationError):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if row["phase"] == "submitted":
            self._schedule(cast(str, row["run_id"]))
        if row["phase"] in ("submitted", "running"):
            return self._registered_view(row)
        return self._view(row)

    @staticmethod
    def _registered_view(row: dict[str, object]) -> ResearchRunView:
        """Expose the allocated registry identity, without implying a checkpoint exists."""

        return ResearchRunView(
            run_id=cast(str, row["run_id"]),
            report_id=cast(str, row["report_id"]),
            scope_id=cast(str, row["scope_id"]),
            checkpoint_id=cast(str, row["checkpoint_id"]),
            status=ResearchRunStatus.SUBMITTED,
            destination_id=cast(str, row["destination_id"]),
        )

    def _view(self, row: dict[str, object]) -> ResearchRunView:
        try:
            self._verified_scope(row)
        except (ResearchJobIntegrityError, ValueError, ValidationError):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        phase = row["phase"]
        if phase == "submitted":
            return self._registered_view(row)
        run_id = cast(str, row["run_id"])
        try:
            result = self._runtime_for(row).inspect(run_id)
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        state = result.state
        if (
            state.run_id != run_id
            or state.report_id != row["report_id"]
            or state.original_scope.scope_id != row["scope_id"]
            or state.destination.destination_id != row["destination_id"]
        ):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE)
        if phase in ("blocked", "unavailable"):
            status = ResearchRunStatus.BLOCKED
        elif state.disposition is WorkflowDisposition.REJECTED:
            status = ResearchRunStatus.REJECTED
        elif state.disposition is WorkflowDisposition.EXPORTED:
            status = ResearchRunStatus.EXPORTED
        elif result.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL:
            status = ResearchRunStatus.PENDING_REVIEW
        else:
            status = ResearchRunStatus.ACTIVE
        synthesis = state.synthesis
        try:
            prepared = (
                None
                if synthesis is None
                else self._review_export.get_document(
                    state.report_id, synthesis.report_content_hash
                )
            )
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if status in {
            ResearchRunStatus.PENDING_REVIEW,
            ResearchRunStatus.APPROVED,
            ResearchRunStatus.REJECTED,
            ResearchRunStatus.EXPORTED,
        } and (prepared is None or state.pending_draft is None):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE)
        return ResearchRunView(
            run_id=state.run_id,
            report_id=state.report_id,
            scope_id=state.original_scope.scope_id,
            checkpoint_id=state.checkpoint_id,
            status=status,
            report_content_hash=None if synthesis is None else synthesis.report_content_hash,
            render_document_hash=None if prepared is None else prepared.render_document_hash,
            pending_draft_id=None
            if state.pending_draft is None
            else state.pending_draft.persistence_id,
            destination_id=state.destination.destination_id,
            warning_codes=() if synthesis is None else synthesis.warning_codes,
        )

    def get_run(self, run_id: str) -> ResearchRunView:
        try:
            row = self._jobs.load(run_id)
        except (ResearchJobIntegrityError, ValueError):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if row is None:
            raise _fail(ResearchApplicationErrorCode.NOT_FOUND)
        return self._view(row)

    def list_runs(self, *, limit: int, offset: int) -> ResearchRunList:
        try:
            rows = self._jobs.list(limit=limit, offset=offset)
        except (ResearchJobIntegrityError, ValueError):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        items = tuple(self._view(row) for row in rows)
        next_offset = offset + len(items) if len(items) == limit else None
        return ResearchRunList(items=items, next_offset=next_offset)

    def get_report(self, run_id: str) -> ResearchReportView:
        run = self.get_run(run_id)
        if run.report_content_hash is None:
            raise _fail(ResearchApplicationErrorCode.CONFLICT)
        try:
            prepared = self._review_export.get_document(run.report_id, run.report_content_hash)
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if prepared is None or prepared.render_document_hash != run.render_document_hash:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE)
        return ResearchReportView(run=run, document=prepared.document)

    def review(self, command: ResearchReviewCommand) -> ResearchRunView:
        if type(command) is not ResearchReviewCommand:
            raise ValueError("research review command type is invalid")
        try:
            row = self._jobs.load(command.run_id)
        except (ResearchJobIntegrityError, ValueError):
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if row is None:
            raise _fail(ResearchApplicationErrorCode.NOT_FOUND)
        if row["phase"] not in ("pending_review", "reviewing", "rejected", "exported"):
            raise _fail(ResearchApplicationErrorCode.CONFLICT)
        try:
            runtime = self._runtime_for(row)
            result = runtime.inspect(command.run_id)
            state = result.state
            synthesis = state.synthesis
            pending = state.pending_draft
            if synthesis is None or pending is None:
                raise ValueError("review checkpoint lacks pending document")
            prepared = self._review_export.get_document(
                state.report_id, synthesis.report_content_hash
            )
            if prepared is None or (
                command.report_id,
                command.report_content_hash,
                command.render_document_hash,
                command.pending_draft_id,
                command.destination_id,
            ) != (
                state.report_id,
                synthesis.report_content_hash,
                prepared.render_document_hash,
                pending.persistence_id,
                state.destination.destination_id,
            ):
                raise ValueError("review command differs from checkpoint")
            decision = ReviewDecision(command.decision.value)
            review_id = derive_identity("review", {"command_key": command.idempotency_key})
            existing = self._review_export.get_review(
                pending_draft_persistence_id=pending.persistence_id,
                report_id=state.report_id,
                report_content_hash=synthesis.report_content_hash,
                destination=state.destination,
            )
            if existing is None:
                review = ReviewRecord(
                    review_id=review_id,
                    report_id=state.report_id,
                    report_content_hash=synthesis.report_content_hash,
                    pending_draft_persistence_id=pending.persistence_id,
                    destination=state.destination,
                    source_outcome_refs=tuple(
                        task.terminal_outcome_ref
                        for task in state.source_tasks
                        if task.terminal_outcome_ref is not None
                    ),
                    warning_codes=synthesis.warning_codes,
                    decision=decision,
                    reviewer_id=command.reviewer_id,
                    decided_at_utc=datetime.now(UTC),
                )
                try:
                    self._review_export.submit_review(review, source_tasks=state.source_tasks)
                except PersistenceConflict:
                    raced = self._review_export.get_review(
                        pending_draft_persistence_id=pending.persistence_id,
                        report_id=state.report_id,
                        report_content_hash=synthesis.report_content_hash,
                        destination=state.destination,
                    )
                    if raced is None or (
                        raced.review_id != review_id
                        or raced.decision is not decision
                        or raced.reviewer_id != command.reviewer_id
                    ):
                        raise
            elif (
                existing.review_id != review_id
                or existing.decision is not decision
                or existing.reviewer_id != command.reviewer_id
            ):
                raise ResearchJobConflict("review command conflicts with stored decision")
        except (ResearchJobConflict, PersistenceConflict):
            raise _fail(ResearchApplicationErrorCode.CONFLICT) from None
        except (ValueError, ValidationError):
            raise _fail(ResearchApplicationErrorCode.CONFLICT) from None
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        if row["phase"] in ("rejected", "exported"):
            return self.get_run(command.run_id)
        if row["phase"] == "reviewing":
            if row["review_command_key"] != command.idempotency_key:
                raise _fail(ResearchApplicationErrorCode.CONFLICT)
            return self.get_run(command.run_id)
        claimed = self._jobs.transition(
            command.run_id,
            expected="pending_review",
            target="reviewing",
            review_command_key=command.idempotency_key,
        )
        if claimed is None:
            current = self._jobs.load(command.run_id)
            if current is not None and (
                current["review_command_key"] == command.idempotency_key
                and current["phase"] in ("reviewing", "rejected", "exported")
            ):
                return self.get_run(command.run_id)
            raise _fail(ResearchApplicationErrorCode.CONFLICT)
        try:
            resumed = runtime.resume(command.run_id)
            if resumed.interrupted_before is WorkflowNode.REQUEST_EXPORT_APPROVAL:
                self._prepare_material(resumed.state)
                target = "pending_review"
            elif resumed.state.disposition is WorkflowDisposition.REJECTED:
                target = "rejected"
            elif resumed.state.disposition is WorkflowDisposition.EXPORTED:
                target = "exported"
            elif resumed.terminal:
                target = "blocked"
            else:
                raise ValueError("review resume lacks terminal or interrupt")
            self._jobs.transition(
                command.run_id,
                expected="reviewing",
                target=target,
                error_code="execution_blocked" if target == "blocked" else None,
            )
        except Exception:
            self._jobs.transition(
                command.run_id,
                expected="reviewing",
                target="unavailable",
                error_code="review_unavailable",
            )
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
        return self.get_run(command.run_id)

    def download_export(self, run_id: str, format: ResearchExportFormat) -> ResearchExportArtifact:
        run = self.get_run(run_id)
        if run.status is not ResearchRunStatus.EXPORTED or run.report_content_hash is None:
            raise _fail(ResearchApplicationErrorCode.CONFLICT)
        try:
            row = self._jobs.load(run_id)
            if row is None:
                raise ValueError("committed job is unavailable")
            state = self._runtime_for(row).inspect(run_id).state
            approval = state.active_approval
            export = state.export_record
            if approval is None or export is None:
                raise ValueError("export checkpoint lacks active approval")
            key = export_idempotency_key(
                state.report_id, run.report_content_hash, state.destination
            )
            record, content = self._review_export.read_export(
                report_id=state.report_id,
                report_content_hash=run.report_content_hash,
                destination=state.destination,
                idempotency_key=key,
                approval=approval,
                format=format.value,
            )
            if record != export or len(content) > 2_097_152:
                raise ValueError("committed export differs from checkpoint")
            return ResearchExportArtifact(
                run_id=run_id,
                report_id=run.report_id,
                report_content_hash=run.report_content_hash,
                render_document_hash=cast(str, run.render_document_hash),
                export_id=record.export_id,
                approval_review_id=record.approval_review_id,
                format=format,
                content=content,
                content_hash=sha256_digest(content),
            )
        except Exception:
            raise _fail(ResearchApplicationErrorCode.UNAVAILABLE) from None
