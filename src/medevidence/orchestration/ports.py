"""Injected source-neutral capabilities consumed by thin workflow nodes."""

from __future__ import annotations

from typing import Protocol

from medevidence.domain import M1BSourcePlanEntryV1, ReportId, ResearchScope, RunId
from medevidence.domain.identifiers import Sha256Digest

from .contracts import (
    CollectedEvidenceResult,
    ExportDestinationRef,
    ExportRecord,
    PendingDraftRef,
    ReportValidationState,
    ReviewRecord,
    SafetyDecision,
    ScopeSafetyEvaluation,
    SourceTaskAttemptRef,
    SourceTaskFailureRef,
    SourceTaskState,
    SynthesisState,
)


class ScopeSafetyPort(Protocol):
    """Classify and interpret a scope before any source execution."""

    def evaluate(self, scope: ResearchScope) -> ScopeSafetyEvaluation: ...


class SourcePlanningPort(Protocol):
    """Produce the bounded source plan without executing a source."""

    def plan(
        self,
        scope: ResearchScope,
        safety_decision: SafetyDecision,
    ) -> tuple[M1BSourcePlanEntryV1, ...]: ...


class EvidenceCollectionPort(Protocol):
    """Execute one selected source task through a stable application capability."""

    def collect(
        self,
        task: SourceTaskState,
        scope: ResearchScope,
        attempt: SourceTaskAttemptRef,
    ) -> CollectedEvidenceResult | SourceTaskFailureRef:
        """Dispatch one stable idempotency-bound logical attempt."""

        ...


class SynthesisPort(Protocol):
    """Create claim/report references without exposing a provider-native model."""

    def synthesize(
        self,
        *,
        run_id: RunId,
        report_id: ReportId,
        scope: ResearchScope,
        source_tasks: tuple[SourceTaskState, ...],
        prior_report_content_hash: Sha256Digest | None,
    ) -> SynthesisState: ...


class ReportValidationPort(Protocol):
    """Evaluate citation and safety gates outside prompts and graph nodes."""

    def validate(
        self,
        *,
        run_id: RunId,
        report_id: ReportId,
        scope: ResearchScope,
        source_tasks: tuple[SourceTaskState, ...],
        synthesis: SynthesisState,
    ) -> ReportValidationState: ...


class DraftPersistencePort(Protocol):
    """Persist one validated pending draft idempotently."""

    def save_pending(
        self,
        *,
        report_id: ReportId,
        report_content_hash: Sha256Digest,
    ) -> PendingDraftRef: ...


class ExportApprovalPort(Protocol):
    """Obtain the sole human interrupt decision for formal export."""

    def request_approval(
        self,
        *,
        report_id: ReportId,
        report_content_hash: Sha256Digest,
        destination: ExportDestinationRef,
        source_tasks: tuple[SourceTaskState, ...],
        warning_codes: tuple[str, ...],
    ) -> ReviewRecord: ...


class ExportPort(Protocol):
    """Idempotently finalize one already approved report."""

    def finalize(
        self,
        *,
        report_id: ReportId,
        report_content_hash: Sha256Digest,
        destination: ExportDestinationRef,
        idempotency_key: Sha256Digest,
        approval: ReviewRecord,
    ) -> ExportRecord: ...
